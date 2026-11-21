import asyncio
import json

import httpx
from fastapi.testclient import TestClient

from app.main import app
from app.agents import orchestrator
from app import database

client = TestClient(app)


def test_dataset_catalog_has_all_twelve_categories_and_honest_statuses():
    database.initialize()
    response = client.get("/api/datasets")
    assert response.status_code == 200
    datasets = response.json()
    # Existing NOAA-20 chlorophyll connector is retained in addition to the 12 required categories.
    assert len(datasets) >= 12
    assert {d["category"] for d in datasets} >= {"satellite_sst", "salinity", "currents_ssh", "argo", "chlorophyll", "long_term_ocean_color", "biogeochemistry", "wind", "climatology", "biodiversity", "fishing"}
    assert all(d["status"] in {"IMPLEMENTED_AND_TESTED", "IMPLEMENTED_BUT_NOT_FULLY_TESTED", "METADATA_ONLY", "AUTHENTICATION_REQUIRED", "NOT_IMPLEMENTED", "UNAVAILABLE", "ERROR"} for d in datasets)


def test_query_understanding_endpoint_selects_registered_ids():
    result = client.post("/api/query/understand", json={"query": "What marine species have been recorded in the Arabian Sea?"})
    assert result.status_code == 200
    assert "OBIS_OCCURRENCES" in {d["id"] for d in result.json()["datasets"]}


def test_cache_delete_requires_explicit_confirmation():
    assert client.delete("/api/data-management/cache/sample").status_code == 400


def test_normalized_data_csv_export_route():
    database.initialize()
    result = {"session_id":"csv-test", "query":"csv export", "mode":"quick", "status":"completed", "data_status":"live",
              "created_at":"2026-01-01T00:00:00Z", "report":{"region":"Arabian Sea"}, "chart":{"data":[]},
              "normalized_observations":[{"dataset_id":"noaa-test","provider":"NOAA","original_variable":"sst",
                "standardized_variable":"SST","value":26,"original_units":"degree_C","standardized_units":"°C",
                "latitude":None,"longitude":None,"observation_time":"2026-01-01","depth_m":None,"quality_flag":None,
                "source_metadata":{"samples":12},"retrieval_timestamp":"2026-01-01T00:00:00Z","processing_history":["regional mean"]}]}
    database.save_session(result)
    response = client.get("/api/research/csv-test/data.csv")
    assert response.status_code == 200 and "standardized_variable" in response.text and "noaa-test" in response.text
    database.delete_session("csv-test")


def test_answer_preferences_validation(monkeypatch):
    monkeypatch.delenv("GROQ_API_KEY", raising=False)
    good = client.post("/api/research", json={"query":"analyze sea surface temperature", "answer_preferences":{"length":"short","technical_level":"beginner","format":"bullets","visualization":"none","evidence":"strict"}})
    # This environment test omits a key, so the request is rejected before running a model or provider call.
    assert good.status_code == 503
    bad = client.post("/api/research", json={"query":"analyze sea surface temperature", "answer_preferences":{"length":"huge"}})
    assert bad.status_code == 422


def test_groq_request_uses_supported_endpoint_and_payload(monkeypatch):
    monkeypatch.setenv("GROQ_API_KEY", "unit-test-key")
    monkeypatch.setattr(orchestrator, "GROQ_CHAT_URL", "https://api.groq.com/openai/v1/chat/completions")
    captured = {}
    def handler(request):
        captured["url"] = str(request.url)
        captured["headers"] = dict(request.headers)
        captured["body"] = json.loads(request.content)
        return httpx.Response(200, json={"choices":[{"message":{"content":"{\"ok\":true}"}}], "usage":{"prompt_tokens":4,"completion_tokens":2}})
    async def run():
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client_:
            return await orchestrator._groq_agent("orchestrator", {"answer_preferences":{"length":"short"}}, client_)
    value, usage = asyncio.run(run())
    assert value == {"ok": True} and usage["prompt_tokens"] == 4
    assert captured["url"] == "https://api.groq.com/openai/v1/chat/completions"
    assert captured["headers"]["authorization"] == "Bearer unit-test-key"
    assert captured["body"]["model"] == "openai/gpt-oss-120b"
    assert captured["body"]["response_format"] == {"type":"json_object"}
    assert captured["body"]["max_completion_tokens"] == 700
    assert "max_tokens" not in captured["body"]


def test_groq_retries_transient_provider_failure(monkeypatch):
    monkeypatch.setenv("GROQ_API_KEY", "unit-test-key")
    monkeypatch.setattr(orchestrator, "GROQ_CHAT_URL", "https://api.groq.com/openai/v1/chat/completions")
    count = 0
    def handler(request):
        nonlocal count
        count += 1
        if count == 1:
            return httpx.Response(503, json={"error":{"message":"temporary"}})
        return httpx.Response(200, json={"choices":[{"message":{"content":"{}"}}],"usage":{}})
    async def run():
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client_:
            return await orchestrator._groq_agent("orchestrator", {}, client_)
    asyncio.run(run())
    assert count == 2


def test_groq_retries_json_generation_failure_with_more_budget(monkeypatch):
    monkeypatch.setenv("GROQ_API_KEY", "unit-test-key")
    monkeypatch.setattr(orchestrator, "GROQ_CHAT_URL", "https://api.groq.com/openai/v1/chat/completions")
    bodies = []
    def handler(request):
        body = json.loads(request.content); bodies.append(body)
        if len(bodies) == 1:
            return httpx.Response(400, json={"error":{"message":"Failed to generate JSON. Please adjust your prompt."}})
        return httpx.Response(200, json={"choices":[{"message":{"content":"{\"ok\":true}"}}],"usage":{}})
    async def run():
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client_:
            return await orchestrator._groq_agent("research_planner", {}, client_)
    asyncio.run(run())
    assert len(bodies) == 2
    assert bodies[1]["max_completion_tokens"] >= 2400
    assert bodies[1]["reasoning_effort"] == "low"


def test_groq_obeys_provider_retry_after_seconds(monkeypatch):
    monkeypatch.setenv("GROQ_API_KEY", "unit-test-key")
    monkeypatch.setattr(orchestrator, "GROQ_CHAT_URL", "https://api.groq.com/openai/v1/chat/completions")
    count = 0
    def handler(request):
        nonlocal count
        count += 1
        if count == 1:
            return httpx.Response(429, json={"error":{"message":"Rate limit reached. Please try again in 0.0s."}})
        return httpx.Response(200, json={"choices":[{"message":{"content":"{}"}}],"usage":{}})
    async def run():
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client_:
            return await orchestrator._groq_agent("orchestrator", {}, client_)
    asyncio.run(run())
    assert count == 2


def test_quick_workflow_keeps_verification_critic_and_final_answer(monkeypatch):
    from datetime import date
    from app.main import ResearchRequest
    from app import database
    database.initialize()
    async def fake_fetch(region, start, end, *, include_sst=True, include_chlorophyll=True):
        observations = [{"date": f"2026-01-0{i}", "sst_c": 25.0 + i, "sst_samples": 10,
                         "chlorophyll_mg_m3": 1.0 + i, "chlorophyll_samples": 8} for i in (1,2,3)]
        return {"observations":observations, "sources":[
            {"id":"noaa_ncei_oisst_v2.1_avhrr_nrt_region_mean_1deg_v2","name":"NOAA OISST","url":"https://example.org","data_url":"https://example.org/data","variable":"sst","units":"°C","status":"retrieved","returned_grid_rows":3},
            {"id":"nesdisVHNnoaa20chlaDaily","name":"VIIRS chlorophyll","url":"https://example.org","data_url":"https://example.org/data","variable":"chlor_a","units":"mg m^-3","status":"retrieved","returned_grid_rows":3}],
            "start_date":"2026-01-01","end_date":"2026-01-03","retrieved_at":"2026-01-04T00:00:00Z","bounds":{}}
    count = 0
    async def fake_agent(prompt_id, context, client_):
        nonlocal count
        count += 1
        if prompt_id == "final_report": return ({"executive_summary":"Measured test summary."}, {"prompt_tokens":3,"completion_tokens":2})
        if prompt_id == "evidence_verification": return ({"claims":[]}, {"prompt_tokens":3,"completion_tokens":2})
        return ({"review":"checked"}, {"prompt_tokens":3,"completion_tokens":2})
    monkeypatch.setattr(orchestrator, "fetch_region", fake_fetch)
    monkeypatch.setattr(orchestrator, "_groq_agent", fake_agent)
    monkeypatch.setenv("GROQ_API_KEY", "unit-test-key")
    async def run():
        request = ResearchRequest(query="Give me a short SST summary with evidence", region="Arabian Sea", window_days=7, mode="quick", answer_preferences={"length":"short"})
        return await orchestrator.run_research(request)
    result = asyncio.run(run())
    assert result["ai_status"] == "completed"
    assert count == 3
    assert len(result["normalized_observations"]) == 6
    assert all(next(s for s in result["stages"] if s["id"] == stage)["status"] == "completed" for stage in ("evidence_verification","critic","final_report"))
