"""Numerical analysis over actual NOAA regional daily means."""
from __future__ import annotations

import math
import statistics
from typing import Any


def _mean(values: list[float]) -> float | None:
    return statistics.fmean(values) if values else None


def pearson(x: list[float], y: list[float]) -> float | None:
    if len(x) < 3 or len(x) != len(y):
        return None
    xbar, ybar = statistics.fmean(x), statistics.fmean(y)
    numerator = sum((a - xbar) * (b - ybar) for a, b in zip(x, y))
    denominator = math.sqrt(sum((a - xbar) ** 2 for a in x) * sum((b - ybar) ** 2 for b in y))
    return numerator / denominator if denominator else None


def analyze(observations: list[dict[str, Any]]) -> dict[str, Any]:
    sst = [(r["date"], float(r["sst_c"])) for r in observations if r.get("sst_c") is not None]
    chl = [(r["date"], float(r["chlorophyll_mg_m3"])) for r in observations if r.get("chlorophyll_mg_m3") is not None]
    sst_map = dict(sst)
    chl_map = dict(chl)
    shared_days = sorted(sst_map.keys() & chl_map.keys())
    xs = [sst_map[d] for d in shared_days]
    ys = [chl_map[d] for d in shared_days]
    trend = None
    if len(sst) >= 3:
        t = [i for i, _ in enumerate(sst)]
        tm, vm = statistics.fmean(t), statistics.fmean(v for _, v in sst)
        denom = sum((v - tm) ** 2 for v in t)
        trend = (sum((i - tm) * (value - vm) for i, (_, value) in zip(t, sst)) / denom * 30.4375) if denom else None
    return {
        "sst": {"n_days": len(sst), "mean_c": _mean([v for _, v in sst]),
                "min_c": min((v for _, v in sst), default=None), "max_c": max((v for _, v in sst), default=None),
                "linear_trend_c_per_month": trend},
        "chlorophyll": {"n_days": len(chl), "mean_mg_m3": _mean([v for _, v in chl]),
                        "min_mg_m3": min((v for _, v in chl), default=None),
                        "max_mg_m3": max((v for _, v in chl), default=None)},
        "paired_days": len(shared_days),
        "daily_area_mean_pearson_r": pearson(xs, ys),
        "interpretation_limit": "Exploratory association over the requested daily window; not a causal estimate or long-term climate trend.",
    }
