"""Grid-cell MHW detection and area-aware spatial summaries.

Input arrays are daily SST (time, lat, lon), plus per-cell day-of-year
climatology and threshold arrays (366, lat, lon). This follows the Hobday
90th-percentile/5-day definition; connectivity uses 4-neighbour cells.
"""
from __future__ import annotations

from datetime import date, timedelta
from typing import Any

import numpy as np


def build_spatial_climatology(baseline_sst: np.ndarray, baseline_dates: list[str], *,
                              percentile: float = 90, window_days: int = 11,
                              smooth_days: int = 31, minimum_years: int = 20) -> tuple[np.ndarray, np.ndarray]:
    """Build cell-specific daily climatology and threshold from a historical grid."""
    values = np.asarray(baseline_sst, dtype=float)
    if values.ndim != 3 or values.shape[0] != len(baseline_dates):
        raise ValueError("baseline SST must have shape (time, latitude, longitude)")
    if not 0 < percentile < 100 or window_days < 1 or smooth_days < 1:
        raise ValueError("Invalid percentile or seasonal window")
    dates = [date.fromisoformat(d[:10]) for d in baseline_dates]
    years = {d.year for d in dates}
    if len(years) < minimum_years:
        raise ValueError(f"Historical baseline has {len(years)} years; {minimum_years} required")
    if len(set(dates)) != len(dates):
        raise ValueError("Historical baseline contains duplicate dates")
    buckets = [[values[i] for i, d in enumerate(dates)
                if date(2000, d.month, d.day).timetuple().tm_yday - 1 == k]
               for k in range(366)]
    clim = np.full((366, *values.shape[1:]), np.nan)
    thresh = np.full_like(clim, np.nan)
    half = window_days // 2
    for k in range(366):
        samples_list = [sample for off in range(-half, half + 1)
                        for sample in buckets[(k + off) % 366]]
        if not samples_list:
            continue
        samples = np.stack(samples_list, axis=0)
        counts = np.isfinite(samples).sum(axis=0)
        minimum_samples = max(minimum_years, int(minimum_years * window_days * 0.8))
        good_flat = (counts >= minimum_samples).ravel()
        if not np.any(good_flat):
            continue
        samples_flat = samples.reshape(samples.shape[0], -1)[:, good_flat]
        count_flat = counts.ravel()[good_flat]
        mean_flat = np.nansum(samples_flat, axis=0) / count_flat
        percentile_flat = np.nanpercentile(samples_flat, percentile, axis=0)
        clim_flat, thresh_flat = clim[k].ravel(), thresh[k].ravel()
        clim_flat[good_flat], thresh_flat[good_flat] = mean_flat, percentile_flat
    def smooth(a):
        out = np.full_like(a, np.nan)
        h = smooth_days // 2
        for k in range(366):
            block = a[[(k + off) % 366 for off in range(-h, h + 1)]]
            valid_count = np.isfinite(block).sum(axis=0)
            total = np.nansum(block, axis=0)
            out[k] = np.divide(total, valid_count, out=np.full(total.shape, np.nan), where=valid_count > 0)
        return out
    return smooth(clim), smooth(thresh)


def cell_areas_km2(latitudes: np.ndarray, longitudes: np.ndarray) -> np.ndarray:
    """Approximate spherical cell areas from coordinate spacing (rectilinear grid)."""
    lat = np.asarray(latitudes, dtype=float)
    lon = np.asarray(longitudes, dtype=float)
    if lat.ndim != 1 or lon.ndim != 1 or len(lat) < 2 or len(lon) < 2:
        raise ValueError("At least two 1-D latitude and longitude coordinates are required")
    dlat = np.deg2rad(float(np.median(np.abs(np.diff(lat)))))
    dlon = np.deg2rad(float(np.median(np.abs(np.diff(lon)))))
    radius = 6371.0088
    return (radius**2 * dlat * dlon * np.cos(np.deg2rad(lat))[:, None]) * np.ones((1, len(lon)))


def detect_spatial_mhw(sst: np.ndarray, dates: list[str], climatology: np.ndarray,
                       threshold: np.ndarray, latitudes: np.ndarray,
                       longitudes: np.ndarray, *, min_duration: int = 5,
                       merge_gap_days: int = 2) -> dict[str, Any]:
    """Detect independent cell events then aggregate daily footprint and hotspots.

    Missing observations break an event. Up to `merge_gap_days` non-exceedance
    days are joined only when their SST values are present, matching Hobday
    event joining. Climatology day indexing uses a 366-day calendar.
    """
    values = np.asarray(sst, dtype=float)
    clim = np.asarray(climatology, dtype=float)
    thresh = np.asarray(threshold, dtype=float)
    lat, lon = np.asarray(latitudes, dtype=float), np.asarray(longitudes, dtype=float)
    if values.shape != (len(dates), len(lat), len(lon)):
        raise ValueError("sst must have shape (time, latitude, longitude)")
    if clim.shape != (366, len(lat), len(lon)) or thresh.shape != clim.shape:
        raise ValueError("climatology and threshold must have shape (366, latitude, longitude)")
    parsed = [date.fromisoformat(d[:10]) for d in dates]
    if any(b - a != timedelta(days=1) for a, b in zip(parsed, parsed[1:])):
        raise ValueError("dates must be unique, sorted, and daily-contiguous")
    if min_duration < 1 or merge_gap_days < 0:
        raise ValueError("duration and merge gap must be non-negative")
    areas = cell_areas_km2(lat, lon)
    dayidx = np.array([date(2000, d.month, d.day).timetuple().tm_yday - 1 for d in parsed])
    per_cell: list[dict[str, Any]] = []
    affected = np.zeros(values.shape, dtype=bool)
    for iy in range(len(lat)):
        for ix in range(len(lon)):
            series = values[:, iy, ix]
            limits = thresh[dayidx, iy, ix]
            means = clim[dayidx, iy, ix]
            valid = np.isfinite(series) & np.isfinite(limits) & np.isfinite(means)
            exceed = valid & (series > limits)
            runs: list[tuple[int, int]] = []
            for ti in np.flatnonzero(exceed):
                if runs and ti - runs[-1][1] - 1 <= merge_gap_days and valid[runs[-1][1]+1:ti].all():
                    runs[-1] = runs[-1][0], int(ti)
                else:
                    runs.append((int(ti), int(ti)))
            events = []
            for first, last in runs:
                if last - first + 1 < min_duration:
                    continue
                anomalies = series[first:last+1] - means[first:last+1]
                affected[first:last+1, iy, ix] = True
                events.append({"start": dates[first], "end": dates[last], "duration_days": last-first+1,
                    "exceedance_days": int(exceed[first:last+1].sum()), "mean_intensity_c": float(anomalies.mean()),
                    "maximum_intensity_c": float(anomalies.max()), "cumulative_intensity_c_days": float(anomalies.sum())})
            if events:
                per_cell.append({"latitude": float(lat[iy]), "longitude": float(lon[ix]),
                    "area_km2": float(areas[iy, ix]), "events": events,
                    "event_count": len(events), "total_mhw_days": sum(e["duration_days"] for e in events)})
    valid_cells = np.isfinite(values).any(axis=0) & np.isfinite(clim).any(axis=0)
    valid_area = float(areas[valid_cells].sum())
    daily = []
    for ti, day in enumerate(dates):
        valid = valid_cells & np.isfinite(values[ti])
        footprint = affected[ti] & valid
        denom = float(areas[valid].sum())
        area = float(areas[footprint].sum())
        daily.append({"date": day, "valid_cells": int(valid.sum()), "affected_cells": int(footprint.sum()),
                      "percent_cells_affected": 100*int(footprint.sum())/max(1, int(valid.sum())),
                      "affected_area_km2": area, "percent_area_affected": 100*area/denom if denom else 0.0})
    return {"method": "Hobday et al. (2016); grid-cell seasonal 90th percentile; 5-day minimum",
        "connectivity": "4-neighbour (edge-sharing) grid connectivity; component IDs not yet computed",
        "grid_spacing_degrees": {"latitude": float(np.median(np.abs(np.diff(lat)))),
                                 "longitude": float(np.median(np.abs(np.diff(lon))))},
        "valid_cells": int(valid_cells.sum()), "affected_cells": len(per_cell),
        "event_cells": per_cell, "daily_spatial_coverage": daily,
        "area_weighted_percent_affected_any_day": 100*float(areas[np.any(affected, axis=0)].sum())/valid_area if valid_area else 0.0,
        "hotspots": sorted(per_cell, key=lambda c: max(e["maximum_intensity_c"] for e in c["events"]), reverse=True)[:10]}
