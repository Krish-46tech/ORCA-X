"""Regional daily OISST time series and 1991–2020 Hobday baseline via NOAA ERDDAP."""
from __future__ import annotations

import asyncio
import hashlib
import tempfile
from datetime import date, datetime, timedelta
from pathlib import Path
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


def _decode_spatial_grid(content: bytes, dataset_id: str) -> dict:
    """Decode native OISST grid without collapsing spatial dimensions."""
    try:
        with Dataset("orca_mhw_grid.nc", mode="r", memory=content) as ds:
            var = ds.variables["sst"]
            data = np.ma.asarray(var[:], dtype=float)
            while data.ndim > 3:
                data = data[:, 0]
            lat_name = "latitude" if "latitude" in ds.variables else "lat"
            lon_name = "longitude" if "longitude" in ds.variables else "lon"
            lat = np.asarray(ds.variables[lat_name][:], dtype=float)
            lon = np.asarray(ds.variables[lon_name][:], dtype=float)
            time_var = ds.variables["time"]
            times = num2date(time_var[:], time_var.units,
                only_use_cftime_datetimes=False, only_use_python_datetimes=True)
            sst = np.asarray(np.ma.filled(data, np.nan), dtype=float)
            sst[(sst < -3) | (sst > 45)] = np.nan
            # Normalize coordinate direction and reorder data with it.
            if lat[0] > lat[-1]:
                lat = lat[::-1]; sst = sst[:, ::-1, :]
            lon = ((lon + 180) % 360) - 180
            order = np.argsort(lon); lon = lon[order]; sst = sst[:, :, order]
            return {"dates": [t.date().isoformat() for t in times], "latitudes": lat.tolist(),
                    "longitudes": lon.tolist(), "sst_c": sst.tolist(), "dataset_id": dataset_id,
                    "units": getattr(var, "units", "unknown"), "native_resolution_degrees": 0.25}
    except Exception as exc:
        raise NOAAError(f"Could not decode gridded NOAA OISST subset: {type(exc).__name__}: {exc}") from exc


async def fetch_oisst_spatial_grid(bounds: dict[str, float], start: date, end: date,
                                   *, dataset_id: str = HISTORICAL_ID) -> dict:
    """Retrieve a bounded native 0.25° OISST grid; no regional averaging/striding."""
    if end < start:
        raise ValueError("end date must not precede start date")
    if (end - start).days > 366:
        chunks = []
        cursor = start
        while cursor <= end:
            chunk_end = min(end, cursor + timedelta(days=364))
            chunks.append(await fetch_oisst_spatial_grid(bounds, cursor, chunk_end, dataset_id=dataset_id))
            cursor = chunk_end + timedelta(days=1)
        latitudes, longitudes = chunks[0]["latitudes"], chunks[0]["longitudes"]
        if any(c["latitudes"] != latitudes or c["longitudes"] != longitudes for c in chunks[1:]):
            raise NOAAError("Historical OISST chunks have incompatible coordinate grids")
        dates = [d for c in chunks for d in c["dates"]]
        if len(dates) != len(set(dates)) or dates[0] != start.isoformat() or dates[-1] != end.isoformat():
            raise NOAAError("Historical OISST chunks are incomplete or contain duplicate dates")
        return {**chunks[0], "dates": dates, "sst_c": [grid for c in chunks for grid in c["sst_c"]],
                "cache_hit": all(c.get("cache_hit") for c in chunks), "chunks": len(chunks),
                "baseline_period": [str(start.year), str(end.year)]}
    lat_first = max(-89.875, np.ceil((bounds["lat_min"] - 0.125) * 4) / 4 + 0.125)
    lat_last = min(89.875, bounds["lat_max"])
    lon_min, lon_max = bounds["lon_min"], bounds["lon_max"]
    if lon_max < lon_min:
        raise ValueError("Dateline-crossing spatial bounds must be split before retrieval")
    lon_first = max(-179.875, np.ceil((lon_min - 0.125) * 4) / 4 + 0.125)
    lon_last = min(359.875, lon_max)
    constraint = (f"sst[({start.isoformat()}T12:00:00Z):1:({end.isoformat()}T12:00:00Z)]"
                  f"[(0)][({lat_first}):1:({lat_last})][({lon_first}):1:({lon_last})]")
    url = f"{ERDDAP}/{dataset_id}.nc?{quote(constraint, safe='[]():,.TZ-')}"
    cache_root = Path(tempfile.gettempdir()) / "orca_x_noaa_grid_cache"
    cache_root.mkdir(parents=True, exist_ok=True)
    cache_file = cache_root / (hashlib.sha256(url.encode()).hexdigest() + ".npz")
    if cache_file.exists():
        try:
            with np.load(cache_file, allow_pickle=False) as cached:
                result = {"dates": cached["dates"].astype(str).tolist(), "latitudes": cached["latitudes"].tolist(),
                    "longitudes": cached["longitudes"].tolist(), "sst_c": cached["sst_c"].tolist(),
                    "units": str(cached["units"].item()), "dataset_id": dataset_id, "data_url": url, "cache_hit": True,
                    "spatial_resolution_degrees":0.25,"spatial_stride_degrees":1}
            if result["dates"] and result["dates"][0] == start.isoformat() and result["dates"][-1] == end.isoformat():
                return result
        except Exception:
            cache_file.unlink(missing_ok=True)
    last_error = None
    async with httpx.AsyncClient(timeout=httpx.Timeout(180, connect=15), follow_redirects=True,
        headers={"User-Agent": "ORCA-X scientific research client"}) as client:
        for attempt in range(3):
            try:
                response = await client.get(url)
                response.raise_for_status()
                if not (response.content.startswith(b"CDF") or response.content.startswith(b"\x89HDF\r\n\x1a\n")):
                    raise NOAAError("NOAA ERDDAP returned a non-NetCDF response")
                result = _decode_spatial_grid(response.content, dataset_id)
                result.update({"data_url":url,"cache_hit":False,"baseline_period":[str(start.year),str(end.year)],
                               "spatial_resolution_degrees":0.25,"spatial_stride_degrees":1})
                if result["units"] not in {"degree_C", "degrees_C", "degC", "Celsius", "°C"}:
                    raise NOAAError(f"Unexpected OISST units: {result['units']}")
                expected_days = (end-start).days + 1
                if len(result["dates"]) != expected_days or len(set(result["dates"])) != expected_days:
                    raise NOAAError(f"OISST chunk has incomplete time coverage ({len(result['dates'])}/{expected_days})")
                tmp = cache_file.with_suffix(".tmp.npz")
                np.savez_compressed(tmp, dates=np.asarray(result["dates"], dtype="U10"),
                    latitudes=np.asarray(result["latitudes"]), longitudes=np.asarray(result["longitudes"]),
                    sst_c=np.asarray(result["sst_c"], dtype=np.float32), units=np.asarray(result["units"]))
                tmp.replace(cache_file)
                return result
            except (httpx.TimeoutException, httpx.NetworkError, httpx.HTTPStatusError) as exc:
                last_error = exc
                if (isinstance(exc, httpx.HTTPStatusError) and 400 <= exc.response.status_code < 500
                        and exc.response.status_code not in {408, 429}):
                    break
                if attempt < 2:
                    await asyncio.sleep(0.5 * (2 ** attempt))
            except Exception:
                raise
        # ERDDAP data requests currently redirect to an intermittently failing
        # CoastWatch host. For bounded target windows, use NOAA NCEI's official
        # daily fileServer files and subset the native grid locally. Never use
        # this per-file fallback for multi-year baseline requests.
        if (end - start).days <= 30:
            fallback = await _fetch_ncei_file_grid(client, bounds, start, end, dataset_id)
            fallback.update({"data_url": fallback["source_url"], "cache_hit": False,
                "spatial_resolution_degrees": 0.25, "spatial_stride_degrees": 1,
                "access_method": "NCEI THREDDS fileServer daily NetCDF fallback"})
            expected = (end - start).days + 1
            if len(fallback["dates"]) != expected or len(set(fallback["dates"])) != expected:
                raise NOAAError("NCEI fileServer target window is incomplete or has duplicate days")
            tmp = cache_file.with_suffix(".tmp.npz")
            np.savez_compressed(tmp, dates=np.asarray(fallback["dates"], dtype="U10"),
                latitudes=np.asarray(fallback["latitudes"]), longitudes=np.asarray(fallback["longitudes"]),
                sst_c=np.asarray(fallback["sst_c"], dtype=np.float32), units=np.asarray(fallback["units"]))
            tmp.replace(cache_file)
            return fallback
    raise NOAAError(f"NOAA gridded OISST retrieval failed after 3 attempts ({type(last_error).__name__}: {last_error})")


async def _fetch_ncei_file_grid(client: httpx.AsyncClient, bounds: dict[str, float], start: date,
                                end: date, dataset_id: str) -> dict:
    if dataset_id == NRT_ID:
        base = "https://www.ncei.noaa.gov/thredds/fileServer/ncFC/fc-oisst-daily-avhrr-only-dly-prelim/files"
        suffix = "_preliminary"
    elif dataset_id == HISTORICAL_ID:
        base = "https://www.ncei.noaa.gov/thredds/fileServer/OisstBase/NetCDF/V2.1/AVHRR"
        suffix = ""
    else:
        raise NOAAError(f"No verified NCEI THREDDS file route for dataset {dataset_id}")
    rows, coordinates, units = [], None, None
    for offset in range((end-start).days + 1):
        day = start + timedelta(days=offset)
        fname = f"oisst-avhrr-v02r01.{day:%Y%m%d}{suffix}.nc"
        url = f"{base}/{day:%Y%m}/{fname}"
        response = await client.get(url)
        response.raise_for_status()
        if not (response.content.startswith(b"CDF") or response.content.startswith(b"\x89HDF\r\n\x1a\n")):
            raise NOAAError(f"NCEI fileServer returned a non-NetCDF response for {day}")
        try:
            with Dataset(fname, mode="r", memory=response.content) as ds:
                var = ds.variables["sst"]
                if getattr(var, "units", "").lower() not in {"celsius", "degree_c", "degrees_c", "degc", "°c"}:
                    raise NOAAError(f"Unexpected NCEI SST units for {day}: {getattr(var, 'units', 'unknown')}")
                lat = np.asarray(ds.variables["lat"][:], dtype=float)
                lon = np.asarray(ds.variables["lon"][:], dtype=float)
                ti = num2date(ds.variables["time"][:], ds.variables["time"].units,
                    only_use_cftime_datetimes=False, only_use_python_datetimes=True)
                if len(ti) != 1 or ti[0].date() != day:
                    raise NOAAError(f"NCEI fileServer time coordinate mismatch for {day}")
                yi = np.flatnonzero((lat >= bounds["lat_min"]) & (lat <= bounds["lat_max"]))
                xi = np.flatnonzero((lon >= bounds["lon_min"]) & (lon <= bounds["lon_max"]))
                if not len(yi) or not len(xi):
                    raise NOAAError("Requested region does not intersect NCEI grid")
                values = np.ma.asarray(var[0, 0, yi.min():yi.max()+1, xi.min():xi.max()+1], dtype=float)
                values = np.asarray(np.ma.filled(values, np.nan), dtype=float)
                values[(values < -3) | (values > 45)] = np.nan
                if not np.isfinite(values).any():
                    raise NOAAError(f"NCEI SST grid has no valid ocean cells for {day}")
                current_coords = (lat[yi.min():yi.max()+1], lon[xi.min():xi.max()+1])
                if coordinates is not None and (not np.array_equal(coordinates[0], current_coords[0]) or
                                                  not np.array_equal(coordinates[1], current_coords[1])):
                    raise NOAAError("NCEI daily files have incompatible spatial coordinates")
                coordinates, units = current_coords, var.units
                rows.append(values)
        except NOAAError:
            raise
        except Exception as exc:
            raise NOAAError(f"Could not parse NCEI OISST file for {day}: {type(exc).__name__}: {exc}") from exc
    assert coordinates is not None and units is not None
    return {"dates": [(start + timedelta(days=i)).isoformat() for i in range(len(rows))],
        "latitudes": coordinates[0].tolist(), "longitudes": coordinates[1].tolist(),
        "sst_c": np.stack(rows).tolist(), "dataset_id": dataset_id, "units": units,
        "source_url": base, "cache_hit": False}


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
