"""Whitelisted scientific methods and their data requirements."""

METHODS = {
    "marine_heatwave_detection": {
        "intents": ["DETECTION"], "variables": ["SST"],
        "required_data": ["daily_sst", "daily_seasonal_climatology", "daily_90th_percentile"],
        "minimum_baseline_years": 20, "preferred_baseline_years": 30,
        "minimum_samples": 5, "output": ["status", "events", "daily_series", "data_quality"],
        "assumptions": ["Regional means may dilute local events."],
        "limitations": ["Grid-cell event coverage requires gridded daily SST and thresholds."],
    },
    "time_series_trend": {
        "intents": ["TREND_ANALYSIS"], "variables": ["SST", "CHLOROPHYLL_A"],
        "required_data": ["dated_observations", "adequate_temporal_coverage"],
        "minimum_samples": 12, "output": ["slope", "uncertainty", "coverage"],
        "assumptions": ["Trend estimates depend on period and temporal sampling."],
        "limitations": ["The short live retrieval window cannot support multi-decadal trends."],
    },
    "seasonal_anomaly": {
        "intents": ["ANOMALY_DETECTION"], "variables": ["SST", "CHLOROPHYLL_A"],
        "required_data": ["observations", "matched_seasonal_baseline"],
        "minimum_samples": 1, "output": ["anomaly", "baseline", "coverage"],
        "assumptions": ["Baseline must represent the relevant season and spatial support."],
        "limitations": ["No anomaly is reported without a compatible baseline."],
    },
    "paired_association": {
        "intents": ["CORRELATION_ANALYSIS"], "variables": ["two_or_more_variables"],
        "required_data": ["temporally_aligned_observations"], "minimum_samples": 30,
        "output": ["association", "sample_size", "uncertainty"],
        "assumptions": ["Pairing does not establish causation."],
        "limitations": ["Confounding, seasonality, and autocorrelation require further analysis."],
    },
}


def methods_for_intents(intents: list[str], query: str = "") -> list[str]:
    q = query.casefold()
    selected = []
    if "DETECTION" in intents and any(term in q for term in ("marine heatwave", "heatwave", "marine heat wave")):
        selected.append("marine_heatwave_detection")
    if "TREND_ANALYSIS" in intents:
        selected.append("time_series_trend")
    if "ANOMALY_DETECTION" in intents:
        selected.append("seasonal_anomaly")
    if "CORRELATION_ANALYSIS" in intents:
        selected.append("paired_association")
    return selected
