import json
from datetime import date

from fastapi.testclient import TestClient

from app import database
from app.analysis.statistics import analyze, pearson
from app.data_sources.noaa_erddap import REGIONS, SOURCES, _grid_query, select_window
from app.main import app

client = TestClient(app)


def test_health_and_config_never_expose_key(monkeypatch):
    monkeypatch.setenv("GROQ_API_KEY", "test-secret-value")
    payload = client.get("/api/config/status").json()
    assert payload["groq_configured"] is True
    assert "test-secret-value" not in json.dumps(payload)
    assert client.get("/api/health").json()["database"] == "sqlite"


def test_ten_prompt_specs_have_distinct_ids():
    prompts = client.get("/api/prompts").json()
    assert len(prompts) == 10
    assert len({item["id"] for item in prompts}) == 10
    assert all(item["instructions"] and item["version"] for item in prompts)


def test_unknown_region_is_rejected():
    assert client.post("/api/research", json={"query": "Analyze coastal conditions", "region": "Atlantis"}).status_code == 422


def test_synthetic_demo_endpoint_is_disabled():
    assert client.get("/api/demo-data").status_code == 410


def test_no_key_does_not_return_a_fake_report(monkeypatch):
    monkeypatch.delenv("GROQ_API_KEY", raising=False)
    response = client.post("/api/research", json={"query": "Analyze SST and chlorophyll"})
    assert response.status_code == 503
    assert "GROQ_API_KEY" in response.json()["detail"]


def test_noaa_query_uses_bounded_real_products():
    from datetime import date
    bounds = REGIONS["Arabian Sea"]
    sst = _grid_query(SOURCES["sst"], bounds, date(2026, 10, 1), date(2026, 10, 30))
    chl = _grid_query(SOURCES["chlorophyll"], bounds, date(2026, 10, 1), date(2026, 10, 30))
    assert "sst[(2026-10-01T12:00:00Z)" in sst
    assert "chlor_a[(2026-10-01T12:00:00Z)" in chl
    assert "(30):27:(5)" in chl  # NOAA VIIRS latitude axis is descending.
    assert "noaa_ncei_oisst" in SOURCES["sst"]["id"]


def test_daily_analysis_is_numerical_and_correlation_is_not_causality():
    rows = [
        {"date": "2026-01-01", "sst_c": 25.0, "chlorophyll_mg_m3": 1.0},
        {"date": "2026-01-02", "sst_c": 26.0, "chlorophyll_mg_m3": 2.0},
        {"date": "2026-01-03", "sst_c": 27.0, "chlorophyll_mg_m3": 3.0},
    ]
    stats = analyze(rows)
    assert stats["sst"]["mean_c"] == 26.0
    assert stats["daily_area_mean_pearson_r"] == 1.0
    assert "not a causal" in stats["interpretation_limit"]
    assert pearson([1, 1, 1], [1, 2, 3]) is None


def test_database_persists_session_and_observations(monkeypatch, tmp_path):
    monkeypatch.setenv("ORCA_DB_PATH", str(tmp_path / "orca-test.sqlite3"))
    database.initialize()
    result = {"session_id": "test-session", "query": "test question", "mode": "comprehensive",
              "status": "completed", "data_status": "live", "created_at": "2026-01-01T00:00:00+00:00",
              "report": {"region": "Arabian Sea"},
              "chart": {"data": [{"date": "2026-01-01", "sst_c": 26.0, "sst_samples": 10,
                                    "chlorophyll_mg_m3": 1.2, "chlorophyll_samples": 8}]}}
    result["normalized_observations"] = [{"dataset_id":"test","standardized_variable":"SST","observation_time":"2026-01-01","value":26.0}]
    database.save_session(result)
    assert database.get_session("test-session")["query"] == "test question"
    assert database.list_sessions()[0]["session_id"] == "test-session"
    with database.connect() as db:
        assert db.execute("SELECT COUNT(*) FROM normalized_marine_observations WHERE session_id='test-session'").fetchone()[0] == 1
    assert database.delete_session("test-session") is True
    assert database.get_session("test-session") is None


def test_date_window_caps_to_one_year():
    try:
        select_window("2020-01-01", "2022-01-01", 30)
        assert False, "expected date limit to raise"
    except ValueError as exc:
        assert "365 days" in str(exc)
