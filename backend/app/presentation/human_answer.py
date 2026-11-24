"""Build a plain-language answer from computed results without inventing findings."""
from __future__ import annotations

import re
from datetime import date, datetime, timedelta, timezone
from typing import Any


def _fmt(value: Any, digits: int = 2) -> str | None:
    try:
        return f"{float(value):.{digits}f}" if value is not None else None
    except (TypeError, ValueError):
        return None


def build_human_answer(*, query: str, region: str, start: str, end: str,
                       requested_days: int, observations: list[dict[str, Any]],
                       statistics: dict[str, Any], sources: list[dict[str, Any]],
                       mhw: dict[str, Any] | None = None,
                       retrieved_at: str | None = None,
                       requested_period: dict[str, Any] | None = None) -> dict[str, Any]:
    """Return Understand/Explore/Evidence-ready content derived from this run."""
    q = query.lower()
    forecast = bool(re.search(r"\b(forecast|predict|prediction|future)\b", q))
    trend_requested = bool(re.search(r"\b(trend|warming|long[- ]term|over the (?:last|past))\b", q))
    sst = statistics.get("sst", {})
    chl = statistics.get("chlorophyll", {})
    valid_sst, valid_chl = int(sst.get("n_days", 0)), int(chl.get("n_days", 0))
    sst_mean, sst_min, sst_max = (_fmt(sst.get(k)) for k in ("mean_c", "min_c", "max_c"))
    chl_sources = [s for s in sources if s.get("variable") == "chlor_a"]
    chl_failed = any(s.get("status") != "retrieved" for s in chl_sources)
    findings: list[str] = []
    metrics: list[dict[str, Any]] = []
    limitations: list[str] = []

    if forecast:
        direct = ("ORCA-X cannot provide a forecast for this question because no validated forecast product or prediction model is connected. "
                  "The available NOAA observations describe measured past conditions, not future conditions.")
        limitations.append("No forecast dataset or validated prediction model is available in this workflow.")
    elif mhw is not None:
        status = mhw.get("status")
        if status == "mhw_detected":
            coverage = mhw.get("area_weighted_percent_affected_any_day")
            affected = mhw.get("affected_cells")
            direct = f"The detector found qualifying marine heatwave conditions in the analyzed {region} grid cells during {start} to {end}."
            if coverage is not None:
                direct += f" At least one event was detected across {float(coverage):.1f}% of the valid analyzed area over the period."
            if affected is not None:
                findings.append(f"{affected} grid cells met the event criteria at least once during the analysis period.")
            if coverage is not None:
                metrics.append({"label": "Area affected", "value": f"{float(coverage):.1f}%", "meaning": "Valid analyzed ocean area affected on at least one day in the period", "kind": "computed"})
        elif status == "no_mhw_detected":
            direct = f"The detector did not find a qualifying marine heatwave in the valid {region} grid cells during {start} to {end}. This does not rule out conditions outside the available data coverage."
        else:
            direct = f"There is not enough validated temperature or historical reference data to determine whether a marine heatwave occurred in the {region} during {start} to {end}."
            limitations.append(str(mhw.get("reason") or "Required target observations or historical reference data were unavailable or incomplete."))
        baseline = mhw.get("baseline_period")
        if baseline and status != "insufficient_data":
            period = "–".join(str(x) for x in baseline)
            findings.append(f"To identify unusually warm conditions, the analysis compared daily temperatures with the same-season historical reference from {period}; that reference is not a forecast.")
        limitations.extend(mhw.get("limitations", []) or [])
    elif sst_mean is not None:
        direct = f"Across the available observations, average sea surface temperature in the {region} was {sst_mean}°C from {start} to {end}."
        if trend_requested:
            direct += " This short-window analysis cannot establish a sustained or climate-scale warming trend."
        if sst_min is not None and sst_max is not None:
            findings.append(f"Observed regional daily means ranged from {sst_min}°C to {sst_max}°C.")
            metrics.append({"label": "Observed temperature range", "value": f"{sst_min}–{sst_max}°C", "meaning": "Lowest to highest available daily regional mean", "kind": "observed"})
        metrics.insert(0, {"label": "Average sea surface temperature", "value": f"{sst_mean}°C", "meaning": f"Average of {valid_sst} available daily regional observations", "kind": "computed"})
    elif valid_chl:
        chl_mean = _fmt(chl.get("mean_mg_m3"), 3)
        direct = f"Satellite chlorophyll-a concentration in the {region} averaged {chl_mean} mg/m³ over {valid_chl} available observation days from {start} to {end}. This is an ocean-color indicator, not a direct measurement of primary productivity."
        metrics.append({"label": "Average chlorophyll-a concentration", "value": f"{chl_mean} mg/m³", "meaning": "Satellite ocean-color measurement; not a direct productivity measurement", "kind": "computed"})
    else:
        direct = f"I could not determine the requested ocean conditions for the {region} because this run returned no valid sea-surface-temperature observations."
        limitations.append("No valid SST observations were returned for the requested period.")

    if not forecast:
        if "capped at the 365-day retrieval limit" in str((requested_period or {}).get("label", "")):
            limitations.append("The requested interval exceeds this connector's one-year retrieval limit; this answer covers only the capped 365-day window.")
        if re.search(r"\b(today|right now|currently)\b", q):
            limitations.append(f"The satellite product is delayed; this run reports observations only through {end}, not a same-day measurement.")
        if valid_sst:
            missing = max(0, requested_days - valid_sst)
            findings.append(f"Temperature data was available for {valid_sst} of {requested_days} requested days" + (f"; {missing} days were missing." if missing else "."))
            metrics.append({"label": "Temperature coverage", "value": f"{valid_sst}/{requested_days} days", "meaning": "Days with valid SST observations out of days requested", "kind": "coverage"})
        if chl_sources:
            if valid_chl:
                cmean = _fmt(chl.get("mean_mg_m3"), 3)
                if not valid_sst:
                    findings.append(f"Chlorophyll-a data was available on {valid_chl} observation days.")
                findings.append(f"Chlorophyll-a observations were available on {valid_chl} days" + (f", averaging {cmean} mg/m³." if cmean else "."))
                metrics.append({"label": "Average chlorophyll-a", "value": f"{cmean} mg/m³" if cmean else "Unavailable", "meaning": "Satellite chlorophyll-a concentration; it is not a direct productivity measurement", "kind": "computed"})
            else:
                findings.append("Chlorophyll-a data could not be retrieved, so biological conditions and any SST–chlorophyll relationship could not be assessed.")
                limitations.append("Chlorophyll-a observations were unavailable; missing data does not mean chlorophyll was low or zero.")
        if trend_requested:
            limitations.append("A simple slope over a short daily window is exploratory only; this workflow does not adjust it for seasonal cycles or temporal autocorrelation, so it is not shown as a warming trend.")

    actual_days = sorted(str(row.get("date"))[:10] for row in observations if row.get("sst_c") is not None)
    requested = requested_period or {"start": start, "end": end, "days": requested_days}
    data_period = {"requested": requested,
                   "observed": {"start": actual_days[0] if actual_days else None,
                                "end": actual_days[-1] if actual_days else None,
                                "valid_days": valid_sst, "missing_days": max(0, requested_days-valid_sst)}}
    temporal_sources = []
    historical = False
    try:
        historical = date.fromisoformat(end[:10]) < datetime.now(timezone.utc).date() - timedelta(days=30)
    except ValueError:
        pass
    for source in sources:
        variable = source.get("variable")
        valid_source_days = valid_sst if variable == "sst" else valid_chl if variable == "chlor_a" else None
        provider = source.get("provider") or ("NOAA/NCEI" if "noaa" in str(source.get("name", "") + source.get("id", "")).lower() else None)
        source_name = str(source.get("name", ""))
        version = "OISST v2.1" if "oisst" in (source_name + str(source.get("id", ""))).lower() else None
        record = {**source,
                  "temporal_role": "historical_observations" if historical else "recent_observations",
                  "data_type": "historical_observations" if historical else "observational",
                  "provider": provider, "dataset_version": version,
                  "observation_period": source.get("dataset_coverage") or {"start": start, "end": end},
                  "retrieved_at": source.get("retrieved_at") or retrieved_at,
                  "valid_observation_days": valid_source_days,
                  "missing_observation_days": max(0, requested_days-valid_source_days) if valid_source_days is not None else None}
        temporal_sources.append(record)
    if mhw is not None and mhw.get("baseline_period") and mhw.get("status") != "insufficient_data":
        temporal_sources.append({"name": "NOAA OISST v2.1 final historical climatology", "provider": "NOAA/NCEI",
            "dataset_id": mhw.get("baseline_dataset_id"), "data_type": "climatological_baseline",
            "temporal_role": "historical_reference", "period": mhw.get("baseline_period"),
            "retrieved_at": retrieved_at,
            "provenance": next((p for p in (mhw.get("provenance") or []) if p.get("period") == mhw.get("baseline_period")), None),
            "baseline_quality": mhw.get("baseline_quality"),
            "used_for": "Seasonal climatology and marine heatwave threshold calculation; not a forecast."})

    exploratory = None
    if trend_requested and sst.get("linear_trend_c_per_month") is not None:
        exploratory = {"label": "Unadjusted short-window linear slope", "value": sst.get("linear_trend_c_per_month"),
                       "units": "°C/month", "period": {"start": start, "end": end}, "sample_days": valid_sst,
                       "method": "Ordinary least-squares fit over the order of valid SST samples, scaled to °C/month; sample dates are not used to adjust uneven gaps.",
                       "status": "exploratory_only", "reason": "Not seasonally adjusted and not corrected for temporal autocorrelation; not a climate trend."}

    why = ("These observations describe conditions during the stated period. Ecological effects require relevant biological observations and are not inferred from temperature alone." if chl_failed else None)
    if why is None and mhw is not None and mhw.get("status") in {"mhw_detected", "no_mhw_detected"}:
        why = "A marine heatwave classification means temperatures met (or did not meet) a sustained seasonal threshold; it does not by itself measure effects on marine life."
    if why is None and sst_mean is not None:
        why = "Sea-surface temperature describes the ocean's surface conditions during this period. By itself, it does not show a long-term climate trend or a measured ecological impact."

    return {"version": "human-answer-v1", "title": f"{region}: research findings", "direct_answer": direct,
            "key_findings": findings[:4], "metrics": metrics[:4],
            "why_it_matters": why,
            "limitations": list(dict.fromkeys(limitations)), "data_period": data_period,
            "temporal_sources": temporal_sources, "forecast_supported": False if forecast else None,
            "exploratory_trend": exploratory,
            "explore": {"time_series": bool(observations), "marine_heatwave_map": mhw is not None,
                        "chlorophyll_series": valid_chl > 0},
            "scientific_evidence": {"statistics": statistics, "sources": temporal_sources,
                                    "marine_heatwave_analysis": mhw}}
