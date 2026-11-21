from datetime import date, timedelta

import pytest

from app.analysis.marine_heatwave import build_climatology, detect_marine_heatwaves
from app.analysis.methods import methods_for_intents
from app.query.understanding import understand_query


def baseline_series(start=2001, end=2020):
    rows = []
    for year in range(start, end + 1):
        day = date(year, 1, 1)
        stop = date(year + 1, 1, 1)
        while day < stop:
            rows.append({"date": day.isoformat(), "sst_c": 20.0 + 2 * __import__("math").sin(2 * __import__("math").pi * day.timetuple().tm_yday / 365.25)})
            day += timedelta(days=1)
    return rows


def test_hobday_threshold_and_five_day_event_metrics():
    climate = build_climatology(baseline_series(), baseline_start=2001, baseline_end=2020)
    start = date(2021, 6, 1)
    obs = [{"date": (start + timedelta(days=i)).isoformat(),
            "sst_c": climate["threshold_c"][(start + timedelta(days=i)).timetuple().tm_yday - 1] + (1.5 if 5 <= i <= 10 else -0.3)}
           for i in range(20)]
    result = detect_marine_heatwaves(obs, climate, region="Arabian Sea")
    assert result["status"] == "mhw_detected"
    assert len(result["events"]) == 1
    event = result["events"][0]
    assert event["duration_days"] == 6
    assert event["mean_intensity_c"] > 0
    assert event["maximum_intensity_c"] >= event["mean_intensity_c"]
    assert event["cumulative_intensity_c_days"] == pytest.approx(event["mean_intensity_c"] * 6, abs=0.01)


def test_four_day_exceedance_is_potential_not_mhw():
    climate = build_climatology(baseline_series(), baseline_start=2001, baseline_end=2020)
    start = date(2021, 6, 1)
    obs = [{"date": (start + timedelta(days=i)).isoformat(),
            "sst_c": climate["threshold_c"][(start + timedelta(days=i)).timetuple().tm_yday - 1] + (1 if 3 <= i <= 6 else -0.5)}
           for i in range(12)]
    assert detect_marine_heatwaves(obs, climate, region="Arabian Sea")["status"] == "potential_event_duration_not_met"


def test_missing_baseline_never_classifies_heatwave_from_sst_only():
    result = detect_marine_heatwaves([{"date": f"2025-01-{i:02}", "sst_c": 30} for i in range(1, 9)], None, region="Arabian Sea")
    assert result["status"] == "insufficient_data"
    assert "threshold" in result["reason"]


def test_missing_days_fail_completeness_check():
    rows = [{"date": (date(2025, 1, 1) + timedelta(days=i * 2)).isoformat(), "sst_c": 30} for i in range(5)]
    assert detect_marine_heatwaves(rows, None, region="Arabian Sea")["status"] == "insufficient_data"


def test_baseline_coverage_validation():
    with pytest.raises(ValueError, match="sparse"):
        build_climatology([{"date": "2001-01-01", "sst_c": 20}], baseline_start=2001, baseline_end=2020)


def test_heatwave_question_routes_detection_and_whitelisted_method():
    intent = understand_query("Are there signs of marine heatwave conditions in the Arabian Sea?")
    assert intent["primary_intent"] == "DETECTION"
    assert "marine_heatwave_detection" in intent["methods"]
    assert "daily_90th_percentile" in intent["required_evidence"]
    assert methods_for_intents(["DETECTION"], "marine heatwave") == ["marine_heatwave_detection"]


def test_research_pipeline_blocks_model_positive_when_baseline_retrieval_fails(monkeypatch):
    import asyncio
    from datetime import date
    from app.agents import orchestrator
    from app.main import ResearchRequest

    async def fake_fetch_region(region, start, end, **kwargs):
        rows = [{"date": (date(2026, 1, 1) + timedelta(days=i)).isoformat(), "sst_c": 28.0,
                 "sst_samples": 4, "chlorophyll_mg_m3": None, "chlorophyll_samples": 0} for i in range(20)]
        source = {"id":"test-sst", "name":"test NOAA SST", "url":"https://example.invalid", "data_url":"https://example.invalid/data",
                  "variable":"sst", "units":"°C", "status":"retrieved", "returned_grid_rows":20}
        return {"observations":rows,"sources":[source],"bounds":{},"start_date":"2026-01-01","end_date":"2026-01-20",
                "retrieved_at":"2026-01-21T00:00:00Z"}

    async def missing_baseline(*args, **kwargs):
        raise RuntimeError("network unavailable")

    async def fake_target(*args, **kwargs):
        return {"observations":[{"date": (date(2026, 1, 1) + timedelta(days=i)).isoformat(), "sst_c": 28.0,
                                  "sst_samples": 4} for i in range(20)], "cache_hit": True,
                "data_url":"https://example.invalid/oisst"}

    async def fake_agent(prompt_id, context, client):
        if prompt_id == "scientific_intent":
            output = {"primary_intent":"DETECTION","intents":["DETECTION"]}
        elif prompt_id == "evidence_verification":
            output = {"claims":[{"claim":"Marine heatwave conditions are occurring.","evidence_ids":["NOAA_SST"],"reason":"SST was retrieved"}]}
        elif prompt_id == "final_report":
            output = {"executive_summary":"Marine heatwave conditions are occurring."}
        else:
            output = {"approval_status":"approved"}
        return output, {"prompt_tokens":1,"completion_tokens":1}

    monkeypatch.setattr(orchestrator, "fetch_oisst_area_mean", fake_target)
    monkeypatch.setattr(orchestrator, "get_hobday_baseline", missing_baseline)
    monkeypatch.setattr(orchestrator, "_groq_agent", fake_agent)
    monkeypatch.setenv("GROQ_API_KEY", "test-only")
    request = ResearchRequest(query="Are there signs of marine heatwave conditions in the Arabian Sea?",
        region="Arabian Sea", start_date="2026-01-01", end_date="2026-01-20", mode="quick",
        answer_preferences={"length":"short"})
    result = asyncio.run(orchestrator.run_research(request))
    assert result["marine_heatwave"]["status"] == "insufficient_data"
    assert "cannot be classified" in result["final"]["executive_summary"]
    assert result["claims"][0]["evidence_status"] == "Insufficient evidence"


SCIENTIFIC_QUESTION_BENCHMARK = [
    ("Are there signs of marine heatwave conditions in the Arabian Sea?", "DETECTION"),
    ("How has Arabian Sea surface temperature changed over the past 20 years?", "TREND_ANALYSIS"),
    ("Has chlorophyll concentration changed over the past decade?", "TREND_ANALYSIS"),
    ("Does SST show a relationship with chlorophyll concentration?", "CORRELATION_ANALYSIS"),
    ("Compare temperature and productivity patterns between two seas.", "COMPARATIVE_ANALYSIS"),
    ("What changes are observed after the Indian summer monsoon?", "SCIENTIFIC_EXPLANATION"),
    ("Are any parts of the Indian Ocean experiencing unusual temperatures?", "ANOMALY_DETECTION"),
    ("Is the subsurface ocean warming along with surface waters?", "TREND_ANALYSIS"),
    ("What patterns in sea surface height indicate circulation changes?", "SCIENTIFIC_EXPLANATION"),
    ("What marine species have been observed in this region?", "BIODIVERSITY_ANALYSIS"),
    ("Has fishing activity increased in this region?", "TREND_ANALYSIS"),
    ("What evidence exists that ocean warming affects productivity?", "CAUSAL_INVESTIGATION"),
    ("Identify an interesting environmental pattern to investigate.", "EXPLORATORY_DISCOVERY"),
    ("Critically evaluate the conclusion and strongest alternative.", "SCIENTIFIC_EXPLANATION"),
    ("Show me the actual SST values and anomalies for this period.", "DATA_RETRIEVAL"),
    ("Prepare a scientific investigation report of ocean conditions.", "REPORT_GENERATION"),
    ("Find environmental anomalies in the Indian Ocean.", "ANOMALY_DETECTION"),
    ("Compare two regions for sea surface temperature.", "COMPARATIVE_ANALYSIS"),
    ("Explain the mechanism of monsoon-driven upwelling.", "SCIENTIFIC_EXPLANATION"),
    ("Forecast ocean temperature for next month.", "PREDICTION"),
]


@pytest.mark.parametrize("question,expected", SCIENTIFIC_QUESTION_BENCHMARK)
def test_scientific_intent_benchmark_classifies_twenty_question_categories(question, expected):
    assert expected in understand_query(question)["intents"], question
