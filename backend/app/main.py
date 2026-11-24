from __future__ import annotations

import csv
import io
import json
import os
import uuid
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Literal

from dotenv import load_dotenv

PROJECT_ROOT = Path(__file__).resolve().parents[2]
# The ignored local .env is authoritative in development; hosted images do not include it.
load_dotenv(PROJECT_ROOT / ".env", override=True)

from fastapi import FastAPI, File, HTTPException, UploadFile, Response
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

from app import database
from app.agents.orchestrator import run_research, GROQ_BASE_URL, GROQ_CHAT_URL
from app.data_sources.noaa_erddap import NOAAError, REGIONS, SOURCES
from app.data_sources.registry import list_datasets, get_dataset
from app.query.understanding import understand_query, select_datasets
from app.data_sources.obis import fetch_occurrences
from app.data_sources.literature import search_literature
from app.presentation.human_answer import build_human_answer

@asynccontextmanager
async def lifespan(_: FastAPI):
    database.initialize()
    yield


app = FastAPI(title="ORCA-X API", version="0.2.0", description="Live NOAA-backed marine research prototype", lifespan=lifespan)
app.add_middleware(CORSMiddleware, allow_origins=os.getenv("CORS_ORIGINS", "http://localhost:5173").split(","),
                   allow_methods=["GET", "POST", "DELETE", "OPTIONS"], allow_headers=["Content-Type"])


class AnswerPreferences(BaseModel):
    length: Literal["short", "balanced", "detailed", "comprehensive"] = "balanced"
    technical_level: Literal["beginner", "intermediate", "advanced", "scientific"] = "intermediate"
    format: Literal["conversational", "bullets", "structured", "table", "paper"] = "structured"
    visualization: Literal["none", "recommended", "extensive"] = "recommended"
    evidence: Literal["normal", "strict"] = "strict"


class ResearchRequest(BaseModel):
    query: str = Field(min_length=8, max_length=4000)
    region: str = Field(default="Arabian Sea", min_length=2, max_length=80)
    start_date: str | None = None
    end_date: str | None = None
    window_days: int = Field(default=30, ge=7, le=365)
    mode: Literal["quick", "comprehensive", "data-driven"] = "comprehensive"
    answer_preferences: AnswerPreferences = Field(default_factory=AnswerPreferences)


def _prompt_specs() -> list[dict]:
    prompt_dir = Path(__file__).parent / "prompts"
    return [json.loads(path.read_text()) for path in sorted(prompt_dir.glob("*.json"))]


def _get_saved(session_id: str) -> dict:
    result = database.get_session(session_id)
    if result is None:
        raise HTTPException(404, "Research session not found")
    return result


@app.get("/api/health")
def health():
    return {"status": "ok", "service": "ORCA-X", "time": datetime.now(timezone.utc).isoformat(),
            "groq_configured": bool(os.getenv("GROQ_API_KEY")), "database": "sqlite"}


@app.get("/api/config/status")
def config_status():
    return {"groq_configured": bool(os.getenv("GROQ_API_KEY")),
            "model": os.getenv("GROQ_MODEL", "openai/gpt-oss-120b"),
            "groq_base_url": GROQ_BASE_URL.removesuffix("/chat/completions"),
            "groq_chat_endpoint": GROQ_CHAT_URL, "groq_payload_format": "OpenAI-compatible JSON object mode",
            "groq_timeout_seconds": 45, "groq_transient_retries": 2,
            "database": "SQLite persistent local database", "data_mode": "Dataset registry; NOAA OISST, NOAA VIIRS chlorophyll, OBIS occurrences, Crossref metadata; additional providers catalogued with access status",
            "api_key_exposed": False}


@app.get("/api/prompts")
def prompts():
    return _prompt_specs()


@app.get("/api/prompts/{prompt_id}")
def prompt(prompt_id: str):
    item = next((p for p in _prompt_specs() if p["id"] == prompt_id), None)
    if item is None:
        raise HTTPException(404, "Prompt not found")
    return item


@app.get("/api/data-sources")
def data_sources():
    return [{"id": item["id"], "name": item["name"], "status": "UNAVAILABLE" if item["id"] == SOURCES["chlorophyll"]["id"] else "IMPLEMENTED_AND_TESTED",
             "type": "near-real-time public dataset", "variable": item["variable"], "units": item["unit"],
             "metadata_url": item["url"], "data_url": item["data_url"]}
            for item in SOURCES.values()]


@app.get("/api/datasets")
def datasets():
    inventory = list_datasets()
    cached = {row["dataset_id"]: row for row in database.cache_inventory()}
    last_success = {}
    for retrieval in database.list_retrievals(500):
        if retrieval["status"] == "retrieved" and retrieval["dataset_id"] not in last_success:
            last_success[retrieval["dataset_id"]] = retrieval["finished_at"]
    for item in inventory:
        item["cache"] = cached.get(item["id"], {"records": 0, "bytes": 0, "downloaded": False})
        item["downloaded"] = bool(item["cache"].get("records"))
        item["last_successful_retrieval"] = last_success.get(item["id"])
    return inventory


@app.get("/api/datasets/{dataset_id}")
def dataset_detail(dataset_id: str):
    item = get_dataset(dataset_id)
    if item is None:
        raise HTTPException(404, "Dataset not found")
    item["cache"] = next((row for row in database.cache_inventory() if row["dataset_id"] == dataset_id),
                         {"records": 0, "bytes": 0, "downloaded": False})
    return item


@app.post("/api/query/understand")
def query_understand(payload: dict):
    query = str(payload.get("query", ""))
    if not query.strip() or len(query) > 4000:
        raise HTTPException(422, "Provide a query of 1–4000 characters.")
    return select_datasets(query)


@app.get("/api/data-management/cache")
def cache_inventory():
    rows = database.cache_inventory()
    return {"datasets": rows, "total_bytes": sum(row.get("bytes") or 0 for row in rows),
            "records": sum(row.get("records") or 0 for row in rows)}


@app.get("/api/data-management/retrievals")
def retrievals(limit: int = 100):
    return database.list_retrievals(limit)


@app.delete("/api/data-management/cache/{dataset_id}")
def delete_cache(dataset_id: str, confirm: bool = False):
    if not confirm:
        raise HTTPException(400, "Set confirm=true to delete this dataset's cached observations.")
    return {"deleted_records": database.delete_dataset_cache(dataset_id), "dataset_id": dataset_id}


@app.get("/api/datasets/{dataset_id}/sample")
def dataset_sample(dataset_id: str, limit: int = 20):
    if get_dataset(dataset_id) is None:
        raise HTTPException(404, "Dataset not found")
    with database.connect() as db:
        rows = db.execute("SELECT observation_date, source_version, payload_json, refreshed_at FROM source_observation_cache WHERE dataset_id=? ORDER BY observation_date DESC LIMIT ?", (dataset_id, min(max(limit,1),100))).fetchall()
    import json as _json
    return {"dataset_id": dataset_id, "records": [{"date": row[0], "version": row[1], "value": _json.loads(row[2]), "cached_at": row[3]} for row in rows]}


@app.post("/api/datasets/obis/retrieve")
async def retrieve_obis(payload: dict):
    region = payload.get("region", "Arabian Sea")
    start, end = payload.get("start_date"), payload.get("end_date")
    from datetime import datetime, timezone
    began = datetime.now(timezone.utc).isoformat()
    try:
        result = await fetch_occurrences(region, start, end, int(payload.get("limit", 100)))
        database.log_retrieval("OBIS_OCCURRENCES", "retrieved", began, finished_at=datetime.now(timezone.utc).isoformat(), region=region, date_start=start, date_end=end, records=result["returned"], provenance={"source_url": result["source_url"]})
        return result
    except Exception as exc:
        database.log_retrieval("OBIS_OCCURRENCES", "failed", began, finished_at=datetime.now(timezone.utc).isoformat(), region=region, date_start=start, date_end=end, error=f"{type(exc).__name__}: {exc}"[:500])
        raise HTTPException(502, f"OBIS retrieval failed: {type(exc).__name__}") from exc


@app.get("/api/literature/search")
async def literature_search(q: str, limit: int = 5):
    from datetime import datetime, timezone
    began = datetime.now(timezone.utc).isoformat()
    try:
        results = await search_literature(q, limit)
        database.log_retrieval("CROSSREF_WORKS", "retrieved", began, finished_at=datetime.now(timezone.utc).isoformat(), records=len(results), provenance={"query": q[:500]})
        return {"source": "Crossref", "results": results}
    except Exception as exc:
        database.log_retrieval("CROSSREF_WORKS", "failed", began, finished_at=datetime.now(timezone.utc).isoformat(), error=f"{type(exc).__name__}: {exc}"[:500], provenance={"query": q[:500]})
        raise HTTPException(502, f"Literature search failed: {type(exc).__name__}") from exc


@app.get("/api/regions")
def regions():
    return {name: bounds for name, bounds in REGIONS.items()}


@app.post("/api/research")
async def research(req: ResearchRequest):
    if not os.getenv("GROQ_API_KEY", "").strip():
        raise HTTPException(503, "Groq is not configured. Set GROQ_API_KEY in backend .env and restart the API.")
    if req.region not in REGIONS:
        raise HTTPException(422, f"Unknown marine region. Choose one of: {', '.join(REGIONS)}")
    try:
        workflow = await run_research(req)
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc
    except NOAAError as exc:
        raise HTTPException(502, str(exc)) from exc
    except Exception as exc:
        raise HTTPException(502, f"Research workflow failed: {exc}") from exc

    now = datetime.now(timezone.utc).isoformat()
    session_id = str(uuid.uuid4())
    stats = workflow["statistics"]
    sources = workflow["data"]["sources"]
    final = workflow.get("final") or {}
    quality = workflow["quality"]
    successful_sources = [source for source in sources if source.get("status") == "retrieved"]
    unavailable_sources = [source for source in sources if source.get("status") != "retrieved"]
    has_biodiversity_records = workflow.get("obis_occurrences") is not None
    data_status = ("live" if successful_sources and not unavailable_sources else
                   "partial" if successful_sources or has_biodiversity_records or workflow.get("literature") else "unavailable")
    uncertainty = final.get("uncertainty_and_limitations", [])
    if not isinstance(uncertainty, list):
        uncertainty = [str(uncertainty)]
    mhw = workflow.get("marine_heatwave")
    if not mhw:
        if any(source.get("preliminary_days", 0) for source in sources):
            uncertainty.append("Some recent OISST days are preliminary and may be revised.")
        if any(source.get("variable") == "chlor_a" for source in sources):
            uncertainty.append("Chlorophyll retrieval gaps affect the paired sample size reported above.")
        if stats.get("paired_days", 0) >= 3 and "causal_investigation" in workflow.get("dataset_selection", {}).get("intent", {}).get("analysis", []):
            uncertainty.append("The observed association is not evidence of causation.")
    if any(source.get("variable") == "chlor_a" for source in sources):
        if not any("chlorophyll" in str(item).lower() for item in uncertainty):
            uncertainty.append("Cloud and retrieval gaps limit the chlorophyll sample coverage shown above.")
    source_summary = ", ".join("{} ({})".format(source.get("name", source.get("id")), source.get("status")) for source in sources)
    unavailable_ids = workflow.get("dataset_selection", {}).get("availability", {}).get("unavailable", [])
    uncertainty.extend(workflow.get("dataset_selection", {}).get("availability", {}).get("scope_limitations", []))
    report = {
        **final,
        "executive_summary": str(final.get("executive_summary", "Report agent did not return an executive summary.")),
        "research_question": req.query,
        "region": req.region,
        "geographic_bounds": workflow["data"]["bounds"],
        "time_period": {"start": workflow["start_date"], "end": workflow["end_date"]},
        "requested_time_period": workflow.get("requested_period", {"start": req.start_date, "end": req.end_date,
                                  "window_days": req.window_days}),
        "data_sources": sources,
        "data_availability": (f"Retrieved sources: {source_summary or 'no compatible live data source was queried'}. "
                             f"Retrieved at {workflow['data']['retrieved_at']}; see per-source coverage and valid cell counts. "
                             f"Other selected datasets requiring access or implementation: {', '.join(unavailable_ids) or 'none reported'}"),
        "data_quality": quality,
        "dataset_selection": workflow.get("dataset_selection"),
        "answer_preferences": req.answer_preferences.model_dump(),
        "literature": workflow.get("literature", []),
        "biodiversity_occurrences": workflow.get("obis_occurrences"),
        "normalized_observation_count": len(workflow.get("normalized_observations", [])),
        "methodology": ("MHW detection uses NOAA OISST v2.1, a 1991–2020 daily regional climatology, the centered 11-day 90th-percentile window, 31-day smoothing, and a five-day duration criterion. The source product is 0.25-degree; this project's bounded MHW request samples at approximately 1-degree coordinate spacing."
                        if mhw else "Regional daily means use approximately 1-degree spatial subsampling with cosine latitude weights. Python calculates descriptive summaries, paired daily association, and short-window slopes where available; these do not establish long-term climate trends or causality."),
        "numerical_analysis": stats,
        "claims": workflow["claims"],
        "marine_heatwave_analysis": mhw,
        "critic_review": workflow.get("critique"),
        "references": [{"name": s["name"], "url": s["url"], "dataset_url": s["data_url"],
                        "variable": s["variable"], "units": s["units"], "dataset_coverage": s["dataset_coverage"]}
                       for s in sources],
        "uncertainty_and_limitations": list(dict.fromkeys(str(x) for x in uncertainty)),
        "model": os.getenv("GROQ_MODEL", "openai/gpt-oss-120b"),
        "token_usage": workflow["token_usage"],
    }
    report["human_answer"] = build_human_answer(
        query=req.query, region=req.region, start=workflow["start_date"], end=workflow["end_date"],
        requested_days=quality["requested_days"], observations=workflow["data"]["observations"],
        statistics=stats, sources=sources, mhw=mhw, retrieved_at=workflow["data"]["retrieved_at"],
        requested_period=workflow.get("requested_period"))
    result = {"session_id": session_id, "status": "completed" if workflow["ai_status"] == "completed" else "partial",
              "query": req.query, "mode": req.mode, "data_status": data_status,
              "ai_status": workflow["ai_status"], "stages": workflow["stages"],
              "chart": {"title": f"NOAA daily regional means · {req.region}", "data": workflow["data"]["observations"]},
              "statistics": stats, "data_quality": quality, "report": report,
              "normalized_observations": workflow.get("normalized_observations", []),
              "created_at": now, "retrieved_at": workflow["data"]["retrieved_at"]}
    database.save_session(result)
    return result


@app.get("/api/research/history")
def history():
    return database.list_sessions()


@app.get("/api/research/{session_id}/events")
def events(session_id: str):
    result = _get_saved(session_id)
    return {"session_id": session_id, "events": result["stages"]}


@app.get("/api/research/{session_id}")
def get_research(session_id: str):
    return _get_saved(session_id)


@app.get("/api/research/{session_id}/data.csv")
def export_research_csv(session_id: str):
    _get_saved(session_id)
    with database.connect() as db:
        rows = db.execute("SELECT record_json FROM normalized_marine_observations WHERE session_id=? ORDER BY observation_time, standardized_variable", (session_id,)).fetchall()
    output = io.StringIO()
    fields = ["dataset_id", "provider", "original_variable", "standardized_variable", "value", "original_units",
              "standardized_units", "latitude", "longitude", "observation_time", "depth_m", "quality_flag",
              "retrieval_timestamp", "source_metadata", "processing_history"]
    writer = csv.DictWriter(output, fieldnames=fields)
    writer.writeheader()
    for row in rows:
        item = json.loads(row[0])
        writer.writerow({**item, "source_metadata": json.dumps(item.get("source_metadata", {}), ensure_ascii=False),
                         "processing_history": "; ".join(item.get("processing_history", []))})
    return Response(output.getvalue(), media_type="text/csv",
                    headers={"Content-Disposition": f'attachment; filename="orca-x-{session_id[:8]}-observations.csv"'})


@app.delete("/api/research/{session_id}")
def delete_research(session_id: str):
    if not database.delete_session(session_id):
        raise HTTPException(404, "Research session not found")
    return {"deleted": True}


@app.post("/api/research/{session_id}/rerun")
async def rerun(session_id: str):
    old = _get_saved(session_id)
    report = old["report"]
    return await research(ResearchRequest(query=old["query"], region=report["region"],
                                           start_date=report["time_period"]["start"],
                                           end_date=report["time_period"]["end"], mode=old["mode"]))


@app.post("/api/upload")
async def upload(file: UploadFile = File(...)):
    if not file.filename or file.filename.rsplit(".", 1)[-1].lower() not in {"csv", "json"}:
        raise HTTPException(415, "Upload CSV or JSON only")
    raw = await file.read(5_000_001)
    if len(raw) > 5_000_000:
        raise HTTPException(413, "Maximum upload size is 5 MB")
    try:
        data = json.loads(raw) if file.filename.lower().endswith(".json") else list(csv.DictReader(io.StringIO(raw.decode("utf-8-sig"))))
    except Exception as exc:
        raise HTTPException(400, f"Could not parse file: {exc}") from exc
    if not isinstance(data, list) or len(data) > 100_000:
        raise HTTPException(400, "Expected a list of at most 100,000 rows")
    return {"filename": file.filename, "rows": len(data), "status": "validated",
            "preview": data[:5], "note": "Upload is validated and previewed; NOAA observations power the research workflow."}


@app.get("/api/evaluations")
def evaluations():
    return {"runs": [], "metrics": None, "note": "No independent evaluation suite has been run; metrics are not fabricated."}


@app.get("/api/demo-data")
def demo_data_removed():
    raise HTTPException(410, "Synthetic demo data has been removed. Research runs use live NOAA datasets.")


# Serve the built dashboard when packaged for deployment.
_frontend_dist = PROJECT_ROOT / "frontend" / "dist"
if _frontend_dist.is_dir():
    from fastapi.staticfiles import StaticFiles
    app.mount("/", StaticFiles(directory=str(_frontend_dist), html=True), name="frontend")
