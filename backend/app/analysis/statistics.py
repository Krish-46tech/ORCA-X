"""Numerical analysis over actual NOAA regional daily means."""
from __future__ import annotations

import math
import statistics
from datetime import date
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


def describe(values: list[float | int | None], units: str = "") -> dict[str, Any]:
    """Finite-value descriptive summary with an explicit sample count."""
    valid = [float(x) for x in values if x is not None and math.isfinite(float(x))]
    if not valid:
        return {"n": 0, "missing": len(values), "units": units, "mean": None, "median": None,
                "std_dev": None, "variance": None, "min": None, "max": None, "percentiles": {}}
    def pct(p: float) -> float:
        ordered = sorted(valid)
        rank = (len(ordered) - 1) * p
        lo = int(rank); hi = min(lo + 1, len(ordered) - 1)
        return ordered[lo] + (ordered[hi] - ordered[lo]) * (rank - lo)
    return {"n": len(valid), "missing": len(values) - len(valid), "units": units,
            "mean": statistics.fmean(valid), "median": statistics.median(valid),
            "std_dev": statistics.stdev(valid) if len(valid) > 1 else None,
            "variance": statistics.variance(valid) if len(valid) > 1 else None,
            "min": min(valid), "max": max(valid),
            "percentiles": {"p05": pct(.05), "p25": pct(.25), "p75": pct(.75), "p95": pct(.95)}}


def z_scores(values: list[float | int | None]) -> list[float | None]:
    valid = [float(x) for x in values if x is not None and math.isfinite(float(x))]
    if len(valid) < 2:
        return [None for _ in values]
    mean, sd = statistics.fmean(valid), statistics.stdev(valid)
    if sd == 0:
        return [0.0 if x is not None and math.isfinite(float(x)) else None for x in values]
    return [(float(x) - mean) / sd if x is not None and math.isfinite(float(x)) else None for x in values]


def moving_average(values: list[float | int | None], window: int) -> list[float | None]:
    if window < 1:
        raise ValueError("Moving-average window must be at least 1.")
    result: list[float | None] = []
    for end in range(len(values)):
        chunk = values[max(0, end-window+1):end+1]
        valid = [float(x) for x in chunk if x is not None and math.isfinite(float(x))]
        result.append(statistics.fmean(valid) if len(valid) == window else None)
    return result


def anomaly(value: float, baseline: list[float | int | None], *, units: str = "",
            baseline_period: str | None = None) -> dict[str, Any]:
    summary = describe(baseline, units)
    if summary["n"] < 1:
        raise ValueError("Anomaly requires at least one valid baseline measurement.")
    difference = float(value) - summary["mean"]
    sd = summary["std_dev"]
    return {"value": float(value), "baseline_mean": summary["mean"], "anomaly": difference,
            "standardized_anomaly": difference / sd if sd not in (None, 0) else None,
            "units": units, "baseline_period": baseline_period, "baseline_n": summary["n"],
            "method": "value minus arithmetic mean of supplied baseline; z anomaly uses sample standard deviation"}


def compare_periods(rows: list[dict[str, Any]], value_key: str, period_a: tuple[str, str],
                    period_b: tuple[str, str], units: str = "") -> dict[str, Any]:
    def collect(period: tuple[str, str]) -> list[float]:
        out = []
        for row in rows:
            day = str(row.get("date", ""))[:10]
            value = row.get(value_key)
            if period[0] <= day <= period[1] and value is not None and math.isfinite(float(value)):
                out.append(float(value))
        return out
    a, b = collect(period_a), collect(period_b)
    sa, sb = describe(a, units), describe(b, units)
    difference = sb["mean"] - sa["mean"] if sa["mean"] is not None and sb["mean"] is not None else None
    return {"period_a": {"start": period_a[0], "end": period_a[1], **sa},
            "period_b": {"start": period_b[0], "end": period_b[1], **sb},
            "mean_difference_b_minus_a": difference, "units": units,
            "method": "unpaired difference in arithmetic period means; no causal interpretation"}


def seasonal_aggregate(rows: list[dict[str, Any]], value_key: str, units: str = "") -> dict[str, Any]:
    buckets: dict[str, list[float]] = {"DJF": [], "MAM": [], "JJA": [], "SON": []}
    for row in rows:
        value, day = row.get(value_key), row.get("date")
        if value is None or not day:
            continue
        try:
            month = date.fromisoformat(str(day)[:10]).month
            season = "DJF" if month in (12,1,2) else "MAM" if month in (3,4,5) else "JJA" if month in (6,7,8) else "SON"
            buckets[season].append(float(value))
        except (ValueError, TypeError):
            continue
    return {season: describe(values, units) for season, values in buckets.items()}


def vertical_profile_gradient(records: list[dict[str, Any]], depth_key: str = "depth_m",
                              value_key: str = "temperature_c") -> dict[str, Any]:
    pairs = sorted((float(r[depth_key]), float(r[value_key])) for r in records
                   if r.get(depth_key) is not None and r.get(value_key) is not None
                   and math.isfinite(float(r[depth_key])) and math.isfinite(float(r[value_key])))
    if len(pairs) < 2:
        raise ValueError("Vertical gradient requires at least two valid depth measurements.")
    depth_span = pairs[-1][0] - pairs[0][0]
    if depth_span <= 0:
        raise ValueError("Vertical profile must span at least two distinct depths.")
    return {"n_levels": len(pairs), "surface_depth_m": pairs[0][0], "deepest_depth_m": pairs[-1][0],
            "value_change": pairs[-1][1] - pairs[0][1], "gradient_per_m": (pairs[-1][1] - pairs[0][1]) / depth_span,
            "method": "deepest minus shallowest measurement divided by depth span; endpoint gradient, not a fitted thermocline"}


def convert_units(value: float, from_unit: str, to_unit: str) -> float:
    """Convert common marine temperature, length, and speed units; reject unknown conversions."""
    unit = lambda s: s.strip().lower().replace("°", "deg").replace(" ", "")
    a, b = unit(from_unit), unit(to_unit)
    if a == b:
        return float(value)
    temp = {"c": lambda x:x, "degc":lambda x:x, "celsius":lambda x:x,
            "k":lambda x:x-273.15, "kelvin":lambda x:x-273.15,
            "f":lambda x:(x-32)*5/9, "degf":lambda x:(x-32)*5/9, "fahrenheit":lambda x:(x-32)*5/9}
    temp_out = {"c":lambda x:x, "degc":lambda x:x, "celsius":lambda x:x,
                "k":lambda x:x+273.15, "kelvin":lambda x:x+273.15,
                "f":lambda x:x*9/5+32, "degf":lambda x:x*9/5+32, "fahrenheit":lambda x:x*9/5+32}
    if a in temp and b in temp_out:
        return temp_out[b](temp[a](float(value)))
    factors = {"m/s":1.0, "ms-1":1.0, "ms^-1":1.0, "mps":1.0, "km/h":1/3.6, "kmh-1":1/3.6, "kn":0.514444, "knot":0.514444,
               "m":1.0, "meter":1.0, "meters":1.0, "km":1000.0, "cm":0.01}
    if a in factors and b in factors and ((a in {"m/s","ms-1","ms^-1","mps","km/h","kmh-1","kn","knot"}) == (b in {"m/s","ms-1","ms^-1","mps","km/h","kmh-1","kn","knot"})):
        return float(value) * factors[a] / factors[b]
    raise ValueError(f"Unsupported unit conversion: {from_unit} to {to_unit}")
