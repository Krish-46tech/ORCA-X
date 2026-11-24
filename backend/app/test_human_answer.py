"""Offline presentation regressions. Prompt-supplied SST values are a fixture, not fresh data."""
from datetime import date, timedelta

from app.presentation.human_answer import build_human_answer
from app.query.temporal import resolve_relative_period


def _fixture_rows():
    start = date(2026, 10, 23)
    return [{"date": (start + timedelta(days=i)).isoformat(),
             "sst_c": 26.85 if i not in {4, 9, 16} else None, "chlorophyll_mg_m3": None}
            for i in range(30)]


def _fixture_sources(chl_status="unavailable"):
    return [
        {"id": "oisst", "name": "NOAA OISST fixture source", "variable": "sst", "units": "°C",
         "status": "retrieved", "dataset_coverage": {"start": "2026-10-23", "end": "2026-11-21"}},
        {"id": "viirs", "name": "NOAA VIIRS chlorophyll fixture source", "variable": "chlor_a",
         "units": "mg m^-3", "status": chl_status, "error": "fixture HTTP 502" if chl_status != "retrieved" else None},
    ]


def test_prior_sst_chlorophyll_fixture_is_human_readable_and_missing_stays_missing():
    answer = build_human_answer(query="Analyze recent sea surface temperature and chlorophyll-a conditions in the Arabian Sea.",
        region="Arabian Sea", start="2026-10-23", end="2026-11-21", requested_days=30,
        observations=_fixture_rows(), statistics={"sst": {"n_days": 27, "mean_c": 26.85, "min_c": 25.55,
            "max_c": 29.56, "linear_trend_c_per_month": 4.97}, "chlorophyll": {"n_days": 0,
            "mean_mg_m3": None}, "paired_days": 0}, sources=_fixture_sources())
    assert "26.85°C" in answer["direct_answer"]
    assert any("27 of 30" in item and "3 days were missing" in item for item in answer["key_findings"])
    assert any("could not be retrieved" in item for item in answer["key_findings"])
    assert all("4.97" not in item for item in [answer["direct_answer"], *answer["key_findings"]])
    assert answer["data_period"]["observed"]["missing_days"] == 3
    assert answer["exploratory_trend"] is None
    assert answer["temporal_sources"][1]["temporal_role"] == "recent_observations"


def test_trend_question_labels_short_slope_exploratory_and_does_not_claim_climate_trend():
    answer = build_human_answer(query="Is the Arabian Sea warming over the last 30 days?", region="Arabian Sea",
        start="2026-10-23", end="2026-11-21", requested_days=30, observations=_fixture_rows(),
        statistics={"sst": {"n_days": 27, "mean_c": 26.85, "min_c": 25.55, "max_c": 29.56,
            "linear_trend_c_per_month": 4.97}, "chlorophyll": {"n_days": 0}}, sources=_fixture_sources("retrieved"))
    assert "cannot establish a sustained" in answer["direct_answer"]
    assert answer["exploratory_trend"]["status"] == "exploratory_only"
    assert "not a climate trend" in answer["exploratory_trend"]["reason"]


def test_mhw_baseline_is_labeled_historical_reference_not_forecast():
    mhw = {"status": "mhw_detected", "affected_cells": 12, "area_weighted_percent_affected_any_day": 18.4,
           "baseline_period": ["1991", "2020"], "baseline_dataset_id": "oisst-final",
           "limitations": ["Near-real-time observations can be revised."]}
    answer = build_human_answer(query="Are marine heatwave conditions detected?", region="Arabian Sea",
        start="2026-11-01", end="2026-11-20", requested_days=20, observations=_fixture_rows(),
        statistics={"sst": {"n_days": 27}, "chlorophyll": {"n_days": 0}}, sources=_fixture_sources(), mhw=mhw)
    baseline = answer["temporal_sources"][-1]
    assert baseline["data_type"] == "climatological_baseline"
    assert baseline["temporal_role"] == "historical_reference"
    assert "not a forecast" in baseline["used_for"]
    assert answer["explore"]["marine_heatwave_map"] is True


def test_insufficient_mhw_baseline_cannot_be_presented_as_positive_or_attach_unused_baseline():
    mhw = {"status": "insufficient_data", "reason": "Historical baseline retrieval failed."}
    answer = build_human_answer(query="Are marine heatwave conditions detected?", region="Arabian Sea",
        start="2026-11-01", end="2026-11-20", requested_days=20, observations=_fixture_rows(),
        statistics={"sst": {"n_days": 27}, "chlorophyll": {"n_days": 0}}, sources=_fixture_sources(), mhw=mhw)
    assert "not enough validated" in answer["direct_answer"]
    assert "detector found qualifying" not in answer["direct_answer"]
    assert not any(source["data_type"] == "climatological_baseline" for source in answer["temporal_sources"])


def test_forecast_request_does_not_present_observations_as_prediction():
    answer = build_human_answer(query="Forecast Arabian Sea temperatures next week", region="Arabian Sea",
        start="2026-11-01", end="2026-11-20", requested_days=20, observations=_fixture_rows(),
        statistics={"sst": {"n_days": 27, "mean_c": 26.85}, "chlorophyll": {"n_days": 0}}, sources=_fixture_sources())
    assert answer["forecast_supported"] is False
    assert "cannot provide a forecast" in answer["direct_answer"]
    assert "not future conditions" in answer["direct_answer"]
    assert answer["metrics"] == []


def test_chlorophyll_only_query_does_not_require_or_fabricate_sst():
    answer = build_human_answer(query="Describe recent chlorophyll conditions in the Arabian Sea.",
        region="Arabian Sea", start="2026-11-01", end="2026-11-20", requested_days=20,
        observations=[{"date":"2026-11-01","sst_c":None,"chlorophyll_mg_m3":0.42}],
        statistics={"sst":{"n_days":0}, "chlorophyll":{"n_days":1,"mean_mg_m3":0.42}},
        sources=[{"id":"viirs","name":"NOAA VIIRS","variable":"chlor_a","status":"retrieved"}])
    assert "chlorophyll-a concentration" in answer["direct_answer"].lower()
    assert "0.420 mg/m³" in answer["direct_answer"]
    assert all("temperature" not in metric["label"].lower() for metric in answer["metrics"])


def test_common_relative_periods_are_interpreted_with_source_lag():
    today = date(2026, 11, 24)  # Tuesday
    assert resolve_relative_period("What happened today?", today=today) == {
        "start": "2026-11-21", "end": "2026-11-21", "label": "today request; latest expected source day"}
    assert resolve_relative_period("Summarize this week", today=today) == {
        "start": "2026-11-21", "end": "2026-11-21",
        "label": "no observations expected yet this week; latest available source day"}
    assert resolve_relative_period("Analyze last month", today=today) == {
        "start": "2026-10-01", "end": "2026-10-31", "label": "previous calendar month"}
    capped = resolve_relative_period("Compare the last 500 days", today=today)
    assert capped["start"] == "2025-11-22"
    assert "capped at the 365-day retrieval limit" in capped["label"]
