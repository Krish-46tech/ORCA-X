"""Deterministic daily marine heatwave detection following Hobday et al. (2016).

The detector accepts a complete daily regional SST series and a matching daily
climatology/90th-percentile threshold. It deliberately returns insufficient_data
when those inputs are not available; short-window SST summaries are not a proxy.
"""
from __future__ import annotations

from datetime import date, timedelta
from typing import Any, Sequence

import numpy as np


METHOD = "Hobday et al. (2016), daily 90th percentile; 5-day minimum"


def _date_value(item: Any) -> tuple[date, float | None]:
    if isinstance(item, dict):
        raw_date, raw_value = item.get("date"), item.get("sst_c", item.get("sst"))
    else:
        raw_date, raw_value = item[0], item[1]
    day = raw_date if isinstance(raw_date, date) else date.fromisoformat(str(raw_date)[:10])
    try:
        value = float(raw_value) if raw_value is not None else None
    except (TypeError, ValueError):
        value = None
    if value is not None and not np.isfinite(value):
        value = None
    return day, value


def _calendar_day(day: date) -> int:
    """Map dates to a 366-day calendar, retaining Feb 29 separately."""
    return date(2000, day.month, day.day).timetuple().tm_yday - 1


def build_climatology(
    baseline: Sequence[Any], *, baseline_start: int, baseline_end: int,
    percentile: float = 90.0, window_days: int = 11, smooth_days: int = 31,
) -> dict[str, list[float | None]]:
    """Build a seasonally varying Hobday threshold and climatological mean.

    `baseline` must be daily regional SST for the complete baseline period.
    The percentile is calculated in a centered circular calendar-day window,
    then both mean and threshold are circularly smoothed.
    """
    if baseline_end - baseline_start + 1 < 20:
        raise ValueError("At least 20 baseline years are required; use 30 where available.")
    if not 0 < percentile < 100 or window_days < 1 or smooth_days < 1:
        raise ValueError("Percentile and smoothing windows are invalid.")
    records: dict[date, float] = {}
    for item in baseline:
        day, value = _date_value(item)
        if baseline_start <= day.year <= baseline_end and value is not None:
            records[day] = value
    expected = sum((date(y + 1, 1, 1) - date(y, 1, 1)).days for y in range(baseline_start, baseline_end + 1))
    if len(records) < expected * 0.90:
        raise ValueError(f"Baseline coverage is too sparse ({len(records)}/{expected} daily values).")
    buckets: list[list[float]] = [[] for _ in range(366)]
    for day, value in records.items():
        buckets[_calendar_day(day)].append(value)
    half = window_days // 2
    means, thresholds = [], []
    for day_index in range(366):
        values = [value for shift in range(-half, half + 1)
                  for value in buckets[(day_index + shift) % 366]]
        means.append(float(np.mean(values)) if values else np.nan)
        thresholds.append(float(np.percentile(values, percentile)) if len(values) >= 20 else np.nan)

    def circular_smooth(values: list[float], width: int) -> list[float | None]:
        half_width = width // 2
        result = []
        for index in range(366):
            sample = [values[(index + shift) % 366] for shift in range(-half_width, half_width + 1)]
            finite = [v for v in sample if np.isfinite(v)]
            result.append(float(np.mean(finite)) if len(finite) == len(sample) else None)
        return result

    return {"climatology_c": circular_smooth(means, smooth_days),
            "threshold_c": circular_smooth(thresholds, smooth_days),
            "baseline_period": [str(baseline_start), str(baseline_end)],
            "percentile": percentile, "percentile_window_days": window_days,
            "smoothing_days": smooth_days, "baseline_valid_days": len(records),
            "baseline_expected_days": expected}


def detect_marine_heatwaves(
    observations: Sequence[Any], climatology: dict[str, Any] | None, *,
    region: str, dataset: str = "NOAA OISST v2.1", minimum_duration: int = 5,
    merge_gap_days: int = 2,
) -> dict[str, Any]:
    """Classify a regional-mean time series without allowing model inference."""
    parsed = sorted((_date_value(item) for item in observations), key=lambda row: row[0])
    if not parsed:
        return _unavailable(region, dataset, "No daily SST observations were retrieved.")
    start, end = parsed[0][0], parsed[-1][0]
    unique = {d: v for d, v in parsed}
    expected = (end - start).days + 1
    coverage = sum(v is not None for v in unique.values()) / max(expected, 1)
    if coverage < 0.90:
        return {**_unavailable(region, dataset, "Daily SST coverage is below 90%; duration classification is unreliable."),
                "time_range": {"start": start.isoformat(), "end": end.isoformat()},
                "data_quality": {"valid_days": sum(v is not None for v in unique.values()), "expected_days": expected,
                                 "completeness": round(coverage, 4)}}
    if not climatology or len(climatology.get("threshold_c", [])) != 366 or len(climatology.get("climatology_c", [])) != 366:
        return {**_unavailable(region, dataset, "A validated daily seasonal climatology and 90th-percentile threshold are unavailable."),
                "time_range": {"start": start.isoformat(), "end": end.isoformat()},
                "data_quality": {"valid_days": sum(v is not None for v in unique.values()), "expected_days": expected,
                                 "completeness": round(coverage, 4)}}

    daily = []
    for offset in range(expected):
        day = start + timedelta(days=offset)
        value = unique.get(day)
        idx = _calendar_day(day)
        threshold = climatology["threshold_c"][idx]
        mean = climatology["climatology_c"][idx]
        valid = value is not None and threshold is not None and mean is not None
        daily.append({"date": day.isoformat(), "sst_c": value,
                      "climatology_c": mean if valid else None, "threshold_c": threshold if valid else None,
                      "anomaly_c": value - mean if valid else None,
                      "exceedance": bool(valid and value > threshold)})
    # Bridge up to two non-exceedance days between exceedance runs (Hobday event joining).
    indices = [i for i, row in enumerate(daily) if row["exceedance"]]
    runs: list[tuple[int, int]] = []
    for idx in indices:
        if not runs:
            runs.append((idx, idx))
        elif idx - runs[-1][1] - 1 <= merge_gap_days and all(
                daily[k]["sst_c"] is not None for k in range(runs[-1][1] + 1, idx)):
            runs[-1] = (runs[-1][0], idx)
        else:
            runs.append((idx, idx))
    events = []
    for first, last in runs:
        duration = last - first + 1
        if duration < minimum_duration:
            continue
        rows = daily[first:last + 1]
        intensities = [r["anomaly_c"] for r in rows if r["anomaly_c"] is not None]
        events.append({"start": rows[0]["date"], "end": rows[-1]["date"], "duration_days": duration,
                       "mean_intensity_c": round(float(np.mean(intensities)), 4),
                       "maximum_intensity_c": round(float(np.max(intensities)), 4),
                       "cumulative_intensity_c_days": round(float(np.sum(intensities)), 4),
                       "exceedance_days": sum(bool(r["exceedance"]) for r in rows)})
    candidate = any(r["exceedance"] for r in daily)
    status = "mhw_detected" if events else "potential_event_duration_not_met" if candidate else "no_mhw_detected"
    return {"method": METHOD, "status": status, "region": region, "dataset": dataset,
            "time_range": {"start": start.isoformat(), "end": end.isoformat()},
            "baseline_period": climatology.get("baseline_period"),
            "threshold_method": f"Seasonal {climatology.get('percentile', 90)}th percentile; centered {climatology.get('percentile_window_days', 11)}-day window; {climatology.get('smoothing_days', 31)}-day smoothing",
            "minimum_duration_days": minimum_duration, "events": events,
            "regional_mean_anomaly_mean_c": round(float(np.mean([r["anomaly_c"] for r in daily if r["anomaly_c"] is not None])), 4),
            "data_quality": {"valid_days": sum(v is not None for v in unique.values()), "expected_days": expected,
                             "completeness": round(coverage, 4)},
            "spatial_coverage": None,
            "spatial_scope": "Regional area-mean time series; grid-cell event extent and localized hotspots were not computed.",
            "daily_series": daily,
            "assumptions": ["A regional mean can dilute localized events."],
            "limitations": (["Spatial event coverage is not calculated from the regional mean."] if status != "insufficient_data" else [])}


def _unavailable(region: str, dataset: str, reason: str) -> dict[str, Any]:
    return {"method": METHOD, "status": "insufficient_data", "region": region, "dataset": dataset,
            "events": [], "reason": reason, "spatial_coverage": None,
            "limitations": [reason]}
