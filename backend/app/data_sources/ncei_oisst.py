"""NOAA NCEI's near-real-time OISST files, subsetted through its THREDDS NCSS API."""
from __future__ import annotations

import asyncio
import calendar
import re
import time
from datetime import date, datetime, timezone
from typing import Any

import httpx
import numpy as np
from netCDF4 import Dataset

from app import database
from app.data_sources.errors import NOAAError

ARCHIVE = "https://www.ncei.noaa.gov/data/sea-surface-temperature-optimum-interpolation/v2.1/access/avhrr"
NCSS = "https://www.ncei.noaa.gov/thredds/ncss/grid/ncFC/fc-oisst-daily-avhrr-only-dly/files"
DATASET_ID = "noaa_ncei_oisst_v2.1_avhrr_nrt_region_mean_1deg_v2"
DATASET_INFO = "https://www.ncei.noaa.gov/products/optimum-interpolation-sst"
_catalog_cache: dict[str, tuple[float, dict[str, str]]] = {}


def _is_netcdf(content: bytes) -> bool:
    # NetCDF classic starts with CDF; NetCDF4 uses the HDF5 signature.
    return content.startswith(b"CDF") or content.startswith(b"\x89HDF\r\n\x1a\n")


def _months(start: date, end: date) -> list[str]:
    months, y, m = [], start.year, start.month
    while (y, m) <= (end.year, end.month):
        months.append(f"{y}{m:02d}")
        if m == 12:
            y, m = y + 1, 1
        else:
            m += 1
    return months


async def _archive_files(client: httpx.AsyncClient, month: str) -> dict[str, str]:
    cached = _catalog_cache.get(month)
    if cached and time.monotonic() - cached[0] < 3600:
        return cached[1]
    response = await client.get(f"{ARCHIVE}/{month}/")
    response.raise_for_status()
    files: dict[str, str] = {}
    for filename in re.findall(r"oisst-avhrr-v02r01\.\d{8}(?:_preliminary)?\.nc", response.text):
        day = re.search(r"\.(\d{8})", filename)
        if day:
            # If both versions are present, prefer the final file.
            key = datetime.strptime(day.group(1), "%Y%m%d").date().isoformat()
            if key not in files or "_preliminary" in files[key]:
                files[key] = filename
    _catalog_cache[month] = (time.monotonic(), files)
    return files


def _parse_netcdf(content: bytes, day: str, bounds: dict[str, float], spatial_stride: int = 1) -> dict[str, Any]:
    try:
        with Dataset("orca_ncei_subset.nc", mode="r", memory=content) as ds:
            lat = np.asarray(ds.variables["lat"][:], dtype=float)
            lon = np.asarray(ds.variables["lon"][:], dtype=float)
            lat_idx = np.flatnonzero((lat >= bounds["lat_min"]) & (lat <= bounds["lat_max"]))
            lon_idx = np.flatnonzero((lon >= bounds["lon_min"]) & (lon <= bounds["lon_max"]))
            if not len(lat_idx) or not len(lon_idx):
                raise NOAAError(f"NOAA OISST returned no cells inside the requested region for {day}.")
            # NCSS has already applied its stride. Full-file fallback needs local subsetting.
            if spatial_stride > 1:
                lat_idx = lat_idx[::spatial_stride]
                lon_idx = lon_idx[::spatial_stride]
            values = np.ma.asarray(ds.variables["sst"][0, 0, :, :], dtype=float)
            values = values[np.ix_(lat_idx, lon_idx)]
            sample_lat = lat[lat_idx]
            weights = np.cos(np.deg2rad(sample_lat))[:, None]
            raw = np.asarray(np.ma.filled(values, np.nan), dtype=float)
            valid = np.isfinite(raw) & (raw >= -3) & (raw <= 45)
            if not valid.any():
                raise NOAAError(f"NOAA OISST has no valid ocean cells for {day} in this region.")
            cell_weights = np.broadcast_to(weights, raw.shape)[valid]
            mean = float(np.average(raw[valid], weights=cell_weights))
            return {"date": day, "sst_c": round(mean, 4), "sst_samples": int(valid.sum()),
                    "chlorophyll_mg_m3": None, "chlorophyll_samples": 0}
    except NOAAError:
        raise
    except Exception as exc:
        raise NOAAError(f"Could not decode NOAA OISST NetCDF subset for {day}: {exc}") from exc


async def _fetch_day(client: httpx.AsyncClient, day: str, filename: str,
                     bounds: dict[str, float], spatial_stride: int) -> dict[str, Any]:
    cached = database.get_source_cache(DATASET_ID, day, filename)
    if cached:
        return cached
    month = day[:4] + day[5:7]
    url = f"{NCSS}/{month}/{filename}"
    params = [
        ("var", "sst"), ("north", str(bounds["lat_max"])), ("west", str(bounds["lon_min"])),
        ("east", str(bounds["lon_max"])), ("south", str(bounds["lat_min"])),
        ("disableProjSubset", "on"), ("horizStride", str(spatial_stride)),
        ("time", f"{day}T12:00:00Z"), ("accept", "netcdf"),
    ]
    try:
        response = await client.get(url, params=params, timeout=httpx.Timeout(18.0, connect=10.0))
        if response.status_code >= 400:
            raise NOAAError(f"NOAA NCSS returned HTTP {response.status_code} for {day}.")
        if not _is_netcdf(response.content):
            raise NOAAError(f"NOAA NCSS did not return NetCDF for {day}.")
        content = response.content
        source_file = filename
        retrieval_method = "ncei_thredds_ncss"
        parse_stride = 1
    except Exception as subset_error:
        try:
            full = await client.get(f"{ARCHIVE}/{month}/{filename}", timeout=httpx.Timeout(60.0, connect=10.0))
            full.raise_for_status()
            if not _is_netcdf(full.content):
                raise NOAAError("NOAA NCEI archive did not return NetCDF.")
            content = full.content
            source_file = filename
            retrieval_method = "ncei_archive_fallback"
            parse_stride = spatial_stride
        except Exception as archive_error:
            raise NOAAError(f"NOAA NCSS failed ({type(subset_error).__name__}); archive fallback failed ({type(archive_error).__name__}).") from archive_error
    row = _parse_netcdf(content, day, bounds, parse_stride)
    row["preliminary"] = "_preliminary" in filename
    row["source_file"] = source_file
    row["retrieval_method"] = retrieval_method
    database.save_source_cache(DATASET_ID, day, filename, row)
    return row


async def fetch_sst(region: dict[str, float], start: date, end: date) -> dict[str, Any]:
    headers = {"User-Agent": "ORCA-X/0.2 (marine research prototype; NOAA NCEI OISST client)"}
    # NCEI 0.25° grid: a four-cell stride gives about 1° regional sampling.
    stride = max(1, round(1.0 / 0.25))
    timeout = httpx.Timeout(35.0, connect=10.0)
    limits = httpx.Limits(max_connections=4, max_keepalive_connections=4)
    sem = asyncio.Semaphore(4)
    async with httpx.AsyncClient(timeout=timeout, limits=limits, headers=headers, follow_redirects=True) as client:
        files: dict[str, str] = {}
        try:
            for month in _months(start, end):
                files.update(await _archive_files(client, month))
        except httpx.HTTPError as exc:
            raise NOAAError(f"NOAA NCEI OISST archive catalog is unavailable: {exc}") from exc
        days = [(date.fromisoformat(day), filename) for day, filename in files.items()
                if start.isoformat() <= day <= end.isoformat()]
        days.sort(key=lambda item: item[0])
        if not days:
            raise NOAAError("NOAA NCEI has no OISST files for the requested date window.")
        async def get_one(day: date, filename: str):
            async with sem:
                return await _fetch_day(client, day.isoformat(), filename, region, stride)
        results = await asyncio.gather(*(get_one(day, filename) for day, filename in days), return_exceptions=True)
    observations, errors = [], []
    for row in results:
        if isinstance(row, Exception):
            errors.append(f"{type(row).__name__}: {row}")
        else:
            observations.append(row)
    if not observations:
        detail = errors[0][:300] if errors else "No daily subsets returned."
        raise NOAAError(f"Unable to retrieve regional NOAA OISST values: {detail}")
    source = {"id": DATASET_ID, "name": "NOAA NCEI OISST v2.1 AVHRR near-real-time daily SST",
              "url": DATASET_INFO, "data_url": f"{ARCHIVE}/", "variable": "sst", "units": "°C",
              "dataset_coverage": {"start": observations[0]["date"], "end": observations[-1]["date"]},
              "retrieved_cells": sum(r["sst_samples"] for r in observations),
              "returned_grid_rows": len(observations),
              "preliminary_days": sum(bool(r["preliminary"]) for r in observations),
              "retrieval_errors": errors[:5]}
    return {"observations": observations, "source": source}
