"""Common provenance-preserving representation for marine observations."""
from __future__ import annotations

import math
from datetime import datetime, timezone
from typing import Any

from pydantic import BaseModel, Field, field_validator


class MarineObservation(BaseModel):
    dataset_id: str
    provider: str
    original_variable: str
    standardized_variable: str
    value: float | None
    original_units: str | None = None
    standardized_units: str | None = None
    latitude: float | None = None
    longitude: float | None = None
    observation_time: str | None = None
    depth_m: float | None = None
    quality_flag: str | None = None
    source_metadata: dict[str, Any] = Field(default_factory=dict)
    retrieval_timestamp: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    processing_history: list[str] = Field(default_factory=list)

    @field_validator("value", "latitude", "longitude", "depth_m")
    @classmethod
    def finite_numbers(cls, value):
        if value is not None and not math.isfinite(float(value)):
            raise ValueError("Observation numeric fields must be finite.")
        return value

    @field_validator("latitude")
    @classmethod
    def latitude_range(cls, value):
        if value is not None and not -90 <= value <= 90:
            raise ValueError("Latitude must be between -90 and 90 degrees.")
        return value

    @field_validator("longitude")
    @classmethod
    def longitude_range(cls, value):
        if value is not None and not -180 <= value <= 360:
            raise ValueError("Longitude must be between -180 and 360 degrees.")
        return value


def normalize_region_aggregates(data: dict, sources: list[dict]) -> list[dict]:
    by_variable = {source.get("variable"): source for source in sources}
    result = []
    for row in data.get("observations", []):
        for key, var, units, samples_key in (("sst_c", "SST", "°C", "sst_samples"),
                                              ("chlorophyll_mg_m3", "CHLOROPHYLL_A", "mg m^-3", "chlorophyll_samples")):
            value = row.get(key)
            source = by_variable.get("sst" if var == "SST" else "chlor_a")
            if value is None or source is None:
                continue
            normalized = MarineObservation(dataset_id=source["id"], provider=source.get("name", "unknown provider"),
                original_variable=source.get("variable", var), standardized_variable=var, value=float(value),
                original_units=source.get("units", units), standardized_units=units, observation_time=row.get("date"),
                quality_flag="PROVISIONAL" if row.get("sst_preliminary") and var == "SST" else None,
                source_metadata={"dataset_url":source.get("data_url"), "dataset_coverage":source.get("dataset_coverage"),
                                 "retrieved_grid_samples":row.get(samples_key, 0), "geographic_bounds":data.get("bounds")},
                processing_history=["cosine-latitude-weighted regional mean", "approximately one-degree spatial sampling"])
            result.append(normalized.model_dump())
    return result
