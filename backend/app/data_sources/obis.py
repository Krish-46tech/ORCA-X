"""Bounded public OBIS v3 occurrence search. Records are not abundance estimates."""
from __future__ import annotations

import httpx

from app.data_sources.noaa_erddap import REGIONS
from app.data_sources.schema import MarineObservation


async def fetch_occurrences(region_name: str, start_date: str | None = None,
                            end_date: str | None = None, limit: int = 100) -> dict:
    if region_name not in REGIONS:
        raise ValueError(f"Unsupported region: {region_name}")
    b = REGIONS[region_name]
    # OBIS accepts a WKT polygon, with longitude then latitude.
    geometry = (f"POLYGON(({b['lon_min']} {b['lat_min']},{b['lon_max']} {b['lat_min']},"
                f"{b['lon_max']} {b['lat_max']},{b['lon_min']} {b['lat_max']},"
                f"{b['lon_min']} {b['lat_min']}))")
    params: dict[str, str | int] = {"geometry": geometry, "size": min(max(limit, 1), 500),
                                     "fields": "id,scientificName,decimalLatitude,decimalLongitude,eventDate,dataset_id"}
    if start_date:
        params["startdate"] = start_date
    if end_date:
        params["enddate"] = end_date
    async with httpx.AsyncClient(timeout=httpx.Timeout(25, connect=8), follow_redirects=True,
                                 headers={"User-Agent": "ORCA-X/0.3 (marine research; https://github.com/Krish-46tech/ORCA-X)"}) as client:
        response = await client.get("https://api.obis.org/v3/occurrence", params=params)
        response.raise_for_status()
    payload = response.json()
    records = payload.get("results", [])
    normalized = []
    for row in records:
        item = MarineObservation(dataset_id=str(row.get("dataset_id") or "OBIS_OCCURRENCES"), provider="OBIS",
            original_variable="scientificName", standardized_variable="SPECIES_OCCURRENCE", value=1,
            original_units="record", standardized_units="record (not abundance)",
            latitude=row.get("decimalLatitude"), longitude=row.get("decimalLongitude"),
            observation_time=row.get("eventDate"), source_metadata={"scientific_name":row.get("scientificName"),
            "source_record_id":row.get("id"), "source_url":str(response.url)},
            processing_history=["OBIS v3 occurrence subset; one record represented as one occurrence event"])
        normalized.append(item.model_dump())
    return {"records": normalized, "returned": len(normalized), "total": payload.get("total"),
            "region": region_name, "source_url": str(response.url),
            "warning": "OBIS occurrence counts reflect sampled records and effort, not abundance, population health, or present-day presence."}
