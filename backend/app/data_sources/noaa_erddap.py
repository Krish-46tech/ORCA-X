"""Bounded regional requests to NOAA CoastWatch ERDDAP gridded products."""
from __future__ import annotations

import asyncio
import math
from collections import defaultdict
from datetime import date, datetime, timedelta, timezone
from typing import Any
from urllib.parse import quote

import httpx

from app.data_sources.errors import NOAAError
from app.data_sources.ncei_oisst import fetch_sst

BASE = "https://coastwatch.pfeg.noaa.gov/erddap"
SOURCES = {
    "sst": {
        "id": "noaa_ncei_oisst_v2.1_avhrr_nrt",
        "name": "NOAA NCEI OISST v2.1 AVHRR near-real-time daily SST",
        "variable": "sst",
        "unit": "°C",
        "url": "https://www.ncei.noaa.gov/products/optimum-interpolation-sst",
        "data_url": "https://www.ncei.noaa.gov/data/sea-surface-temperature-optimum-interpolation/v2.1/access/avhrr/",
        "lat_res": 0.25,
        "latitude_descending": False,
        "time_dim": "time",
        "vertical_dim": "zlev",
        "vertical_value": "0",
        "time_coverage": None,
    },
    "chlorophyll": {
        "id": "nesdisVHNnoaa20chlaDaily",
        "name": "NOAA NOAA-20 VIIRS daily near-real-time chlorophyll-a",
        "variable": "chlor_a",
        "unit": "mg m^-3",
        "url": f"{BASE}/info/nesdisVHNnoaa20chlaDaily/index.html",
        "data_url": f"{BASE}/griddap/nesdisVHNnoaa20chlaDaily",
        "lat_res": 0.0375,
        "latitude_descending": True,
        "time_dim": "time",
        "vertical_dim": "altitude",
        "vertical_value": "0",
        "time_coverage": None,
    },
}

REGIONS: dict[str, dict[str, float]] = {
    "Arabian Sea": {"lat_min": 5, "lat_max": 30, "lon_min": 50, "lon_max": 80},
    "Indian Ocean": {"lat_min": -40, "lat_max": 30, "lon_min": 20, "lon_max": 120},
    "Bay of Bengal": {"lat_min": 5, "lat_max": 25, "lon_min": 80, "lon_max": 100},
    "South China Sea": {"lat_min": -5, "lat_max": 25, "lon_min": 99, "lon_max": 121},
}


def select_window(start_date: str | None, end_date: str | None, window_days: int) -> tuple[date, date]:
    latest_available_estimate = datetime.now(timezone.utc).date() - timedelta(days=3)
    end = date.fromisoformat(end_date) if end_date else latest_available_estimate
    if end > latest_available_estimate:
        end = latest_available_estimate
    start = date.fromisoformat(start_date) if start_date else end - timedelta(days=window_days - 1)
    if start > end:
        raise ValueError("Start date must be on or before the latest available end date.")
    if (end - start).days > 364:
        raise ValueError("The requested date window is limited to 365 days.")
    return start, end


def _time_query(day: date, stride: int, end: date) -> str:
    return f"({day.isoformat()}T12:00:00Z):{stride}:({end.isoformat()}T12:00:00Z)"


def _grid_query(source: dict[str, Any], region: dict[str, float], start: date, end: date) -> str:
    days = (end - start).days + 1
    time_stride = max(1, math.ceil(days / 90))
    # Return about one grid cell per degree: small enough for repeated web requests,
    # still broad enough for regional area-mean summaries.
    spatial_stride = max(1, round(1.0 / float(source["lat_res"])))
    if source.get("latitude_descending"):
        # NOAA-20 VIIRS latitude axis is descending in ERDDAP metadata.
        latitude = f"({region['lat_max']}):{spatial_stride}:({region['lat_min']})"
    else:
        latitude = f"({region['lat_min']}):{spatial_stride}:({region['lat_max']})"
    longitude = f"({region['lon_min']}):{spatial_stride}:({region['lon_max']})"
    return (f"{source['variable']}[{_time_query(start, time_stride, end)}]"
            f"[({source['vertical_value']})][{latitude}][{longitude}]")


async def _get_metadata(client: httpx.AsyncClient, source: dict[str, Any]) -> dict[str, Any]:
    response = await client.get(f"{BASE}/info/{source['id']}/index.json")
    response.raise_for_status()
    table = response.json().get("table", {})
    columns, rows = table.get("columnNames", []), table.get("rows", [])
    try:
        type_i, var_i, name_i, value_i = (columns.index(k) for k in ("Row Type", "Variable Name", "Attribute Name", "Value"))
    except ValueError as exc:
        raise NOAAError(f"Unexpected metadata format for {source['id']}") from exc
    attrs = {row[name_i]: row[value_i] for row in rows
             if row[type_i] == "attribute" and row[var_i] == "NC_GLOBAL"}
    source["time_coverage"] = {"start": attrs.get("time_coverage_start"), "end": attrs.get("time_coverage_end")}
    return attrs


async def _get_grid(client: httpx.AsyncClient, source: dict[str, Any], region: dict[str, float],
                    start: date, end: date) -> dict[str, Any]:
    query = quote(_grid_query(source, region, start, end), safe="[]():,.TZ-")
    response = await client.get(f"{source['data_url']}.json?{query}")
    if response.status_code >= 400:
        raise NOAAError(f"NOAA {source['id']} returned HTTP {response.status_code}: {response.text[:300]}")
    data = response.json().get("table")
    if not data:
        raise NOAAError(f"NOAA {source['id']} did not return a tabular grid response.")
    names, rows = data.get("columnNames", []), data.get("rows", [])
    if source["variable"] not in names or "time" not in names or "latitude" not in names:
        raise NOAAError(f"NOAA {source['id']} response is missing expected coordinates or variable.")
    indices = {key: names.index(key) for key in ("time", "latitude", "longitude", source["variable"])}
    grouped: dict[str, list[tuple[float, float]]] = defaultdict(list)
    for row in rows:
        value = row[indices[source["variable"]]]
        if value is None:
            continue
        try:
            value = float(value)
            latitude = float(row[indices["latitude"]])
        except (TypeError, ValueError):
            continue
        # ERDDAP emits fill values for missing cells; exclude them from stats.
        if not math.isfinite(value) or value < (0.001 if source["variable"] == "chlor_a" else -3) or value > (1000 if source["variable"] == "chlor_a" else 45):
            continue
        timestamp = str(row[indices["time"]])
        day = timestamp[:10]
        area_weight = max(0.01, math.cos(math.radians(latitude)))
        grouped[day].append((value, area_weight))
    daily = {}
    for day, values in grouped.items():
        total_weight = sum(weight for _, weight in values)
        daily[day] = {"value": sum(value * weight for value, weight in values) / total_weight,
                      "samples": len(values)}
    if not daily:
        raise NOAAError(f"NOAA {source['id']} returned no valid cells for the selected area and dates.")
    return {"daily": daily, "grid_rows": len(rows), "valid_cells": sum(v["samples"] for v in daily.values()),
            "coverage": source["time_coverage"]}


async def fetch_region(region_name: str, start: date, end: date) -> dict[str, Any]:
    if region_name not in REGIONS:
        raise ValueError(f"Unsupported region. Choose one of: {', '.join(REGIONS)}")
    bounds = REGIONS[region_name]
    timeout = httpx.Timeout(45.0, connect=12.0)
    limits = httpx.Limits(max_connections=4, max_keepalive_connections=2)
    headers = {"User-Agent": "ORCA-X/0.2 (marine research prototype; NOAA CoastWatch ERDDAP client)"}
    sst = await fetch_sst(bounds, start, end)
    sst_daily = {row["date"]: row for row in sst["observations"]}
    chl_daily: dict[str, dict[str, Any]] = {}
    chl_source: dict[str, Any] = {"id": SOURCES["chlorophyll"]["id"], "name": SOURCES["chlorophyll"]["name"],
                                  "url": SOURCES["chlorophyll"]["url"], "data_url": SOURCES["chlorophyll"]["data_url"],
                                  "variable": SOURCES["chlorophyll"]["variable"], "units": SOURCES["chlorophyll"]["unit"],
                                  "status": "unavailable", "dataset_coverage": None,
                                  "retrieved_cells": 0, "returned_grid_rows": 0}
    chl_error = None
    try:
        async with httpx.AsyncClient(timeout=httpx.Timeout(25.0, connect=8.0), limits=limits,
                                     headers=headers, follow_redirects=True) as client:
            metadata = await _get_metadata(client, SOURCES["chlorophyll"])
            chl_start = max(start, date.fromisoformat(str(metadata.get("time_coverage_start"))[:10]))
            chl_end = min(end, date.fromisoformat(str(metadata.get("time_coverage_end"))[:10]))
            if chl_start > chl_end:
                raise NOAAError("NOAA VIIRS chlorophyll product has no coverage in this date window.")
            result = await _get_grid(client, SOURCES["chlorophyll"], bounds, chl_start, chl_end)
            chl_daily = result["daily"]
            chl_source = {"id": SOURCES["chlorophyll"]["id"], "name": SOURCES["chlorophyll"]["name"],
                          "url": SOURCES["chlorophyll"]["url"], "data_url": SOURCES["chlorophyll"]["data_url"],
                          "variable": SOURCES["chlorophyll"]["variable"], "units": SOURCES["chlorophyll"]["unit"],
                          "dataset_coverage": result["coverage"], "retrieved_cells": result["valid_cells"],
                          "returned_grid_rows": result["grid_rows"], "status": "retrieved"}
    except Exception as exc:
        chl_error = str(exc)[:400]
        chl_source["error"] = chl_error
    dates = sorted(set(sst_daily) | set(chl_daily))
    observations = [{"date": day,
                     "sst_c": sst_daily.get(day, {}).get("sst_c"),
                     "sst_samples": sst_daily.get(day, {}).get("sst_samples", 0),
                     "chlorophyll_mg_m3": round(chl_daily[day]["value"], 5) if day in chl_daily else None,
                     "chlorophyll_samples": chl_daily.get(day, {}).get("samples", 0)} for day in dates]
    sources = [sst["source"], chl_source]
    live_dates = [d for d in dates if sst_daily.get(d, {}).get("sst_c") is not None]
    return {"observations": observations, "bounds": bounds, "sources": sources,
            "start_date": min(live_dates), "end_date": max(live_dates),
            "retrieved_at": datetime.now(timezone.utc).isoformat(),
            "metadata": {"chlorophyll_error": chl_error}}
