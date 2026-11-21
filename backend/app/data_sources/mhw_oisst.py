"""Regional daily OISST time series and 1991–2020 Hobday baseline via NOAA ERDDAP."""
from __future__ import annotations

from datetime import date, datetime, timedelta
from urllib.parse import quote

import httpx
import numpy as np
from netCDF4 import Dataset, num2date

from app import database
from app.data_sources.errors import NOAAError

ERDDAP = "https://upwell.pfeg.noaa.gov/erddap/griddap"
HISTORICAL_ID = "oisst_rclone"  # NOAA/NCEI final, Sep 1981–present, verified 0.25° daily
NRT_ID = "ncdcOisst21NrtAgg"  # NOAA OISST v2.1 preliminary near-real-time, 2020–present
BASELINE_START, BASELINE_END = 1991, 2020
SPATIAL_STRIDE = 8  # consistent ~2° sampling for baseline and requested daily series


def _decode_grid(content: bytes, requested_region: dict[str, float], dataset_id: str) -> list[dict]:
    try:
        with Dataset("orca_mhw_oisst.nc", mode="r", memory=content) as ds:
            variable = ds.variables["sst"]
            data = np.ma.asarray(variable[:], dtype=float)
            while data.ndim > 3:
                data = data[:, 0]
            lat_name = "latitude" if "latitude" in ds.variables else "lat"
            lon_name = "longitude" if "longitude" in ds.variables else "lon"
            lat = np.asarray(ds.variables[lat_name][:], dtype=float)
            lon = np.asarray(ds.variables[lon_name][:], dtype=float)
            times = num2date(ds.variables["time"][:], ds.variables["time"].units,
                             only_use_cftime_datetimes=False, only_use_python_datetimes=True)
            raw = np.asarray(np.ma.filled(data, np.nan), dtype=float)
            raw[(raw < -3) | (raw > 45)] = np.nan
            weights = np.broadcast_to(np.cos(np.deg2rad(lat))[None, :, None], raw.shape)
            valid = np.isfinite(raw)
            total = np.sum(np.where(valid, raw * weights, 0), axis=(1, 2))
            denom = np.sum(np.where(valid, weights, 0), axis=(1, 2))
            count = valid.sum(axis=(1, 2))
            means = np.divide(total, denom, out=np.full(total.shape, np.nan), where=denom > 0)
            return [{"date": t.date().isoformat(), "sst_c": float(v), "sst_samples": int(n),
                     "source_dataset": dataset_id, "grid_shape": [int(len(lat)), int(len(lon))]}
                    for t, v, n in zip(times, means, count) if np.isfinite(v)]
    except Exception as exc:
        raise NOAAError(f"Could not decode NOAA OISST subset: {type(exc).__name__}: {exc}") from exc


async def fetch_oisst_area_mean(region: str, bounds: dict[str, float], start: date, end: date,
                               *, dataset_id: str = HISTORICAL_ID, cache_version: str | None = None) -> dict:
    """Fetch a daily area-weighted region mean in one bounded NetCDF request."""
    version = cache_version or f"{dataset_id}-stride{SPATIAL_STRIDE}-v1"
    expected = (end - start).days + 1
    cached = [database.get_source_cache(f"MHW_OISST_{region}", (start + timedelta(days=i)).isoformat(), version)
              for i in range(expected)]
    if all(cached):
        return {"observations": cached, "cache_hit": True, "dataset_id": dataset_id, "version": version}

    # ERDDAP griddap subset: a daily interval and roughly 2° sample in each axis.
    lat_first = np.ceil((bounds["lat_min"] - 0.125) / 2.0) * 2.0 + 0.125
    lat_last = bounds["lat_max"]
    lon_first = np.ceil((bounds["lon_min"] - 0.125) / 2.0) * 2.0 + 0.125
    lon_last = bounds["lon_max"]
    constraint = (f"sst[({start.isoformat()}T12:00:00Z):1:({end.isoformat()}T12:00:00Z)]"
                  f"[(0)][({lat_first}):{SPATIAL_STRIDE}:({lat_last})]"
                  f"[({lon_first}):{SPATIAL_STRIDE}:({lon_last})]")
    url = f"{ERDDAP}/{dataset_id}.nc?{quote(constraint, safe='[]():,.TZ-')}"
    try:
        async with httpx.AsyncClient(timeout=httpx.Timeout(180, connect=15), follow_redirects=True,
                                     headers={"User-Agent": "ORCA-X scientific research client"}) as client:
            response = await client.get(url)
        response.raise_for_status()
        if not (response.content.startswith(b"CDF") or response.content.startswith(b"\x89HDF\r\n\x1a\n")):
            raise NOAAError("NOAA ERDDAP response was not NetCDF.")
        records = _decode_grid(response.content, bounds, dataset_id)
    except NOAAError:
        raise
    except Exception as exc:
        raise NOAAError(f"NOAA OISST regional daily subset failed ({type(exc).__name__}).") from exc
    by_day = {record["date"]: record for record in records}
    result = []
    for offset in range(expected):
        day = (start + timedelta(days=offset)).isoformat()
        item = by_day.get(day)
        if item:
            database.save_source_cache(f"MHW_OISST_{region}", day, version, item)
            result.append(item)
        else:
            result.append({"date": day, "sst_c": None, "sst_samples": 0,
                           "source_dataset": dataset_id, "grid_shape": None})
    return {"observations": result, "cache_hit": False, "dataset_id": dataset_id,
            "version": version, "data_url": url, "grid_stride": SPATIAL_STRIDE}


async def get_hobday_baseline(region: str, bounds: dict[str, float]) -> dict:
    start, end = date(BASELINE_START, 1, 1), date(BASELINE_END, 12, 31)
    data = await fetch_oisst_area_mean(region, bounds, start, end,
        dataset_id=HISTORICAL_ID, cache_version=f"{HISTORICAL_ID}-{BASELINE_START}-{BASELINE_END}-stride{SPATIAL_STRIDE}-v1")
    return {**data, "baseline_period": [str(BASELINE_START), str(BASELINE_END)],
            "data_url": data.get("data_url", f"{ERDDAP}/{HISTORICAL_ID}"),
            "method_note": "NOAA/NCEI OISST v2.1 final daily SST; area-weighted regional mean on an approximately 2-degree subsample."}
