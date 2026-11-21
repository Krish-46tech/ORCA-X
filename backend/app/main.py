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

from fastapi import FastAPI, File, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

from app import database
from app.agents.orchestrator import run_research
from app.data_sources.noaa_erddap import NOAAError, REGIONS, SOURCES

@asynccontextmanager
async def lifespan(_: FastAPI):
    database.initialize()
    yield


app = FastAPI(title="ORCA-X API", version="0.2.0", description="Live NOAA-backed marine research prototype", lifespan=lifespan)
app.add_middleware(CORSMiddleware, allow_origins=os.getenv("CORS_ORIGINS", "http://localhost:5173").split(","),
                   allow_methods=["GET", "POST", "DELETE", "OPTIONS"], allow_headers=["Content-Type"])


class ResearchRequest(BaseModel):
    query: str = Field(min_length=8, max_length=4000)
    region: str = Field(default="Arabian Sea", min_length=2, max_length=80)
    start_date: str | None = None
    end_date: str | None = None
    window_days: int = Field(default=30, ge=7, le=365)
    mode: Literal["quick", "comprehensive", "data-driven"] = "comprehensive"


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
            "database": "SQLite persistent local database", "data_mode": "NOAA NCEI OISST + NOAA CoastWatch VIIRS chlorophyll",
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
    return [{"id": item["id"], "name": item["name"], "status": "integrated",
             "type": "near-real-time public dataset", "variable": item["variable"], "units": item["unit"],
             "metadata_url": item["url"], "data_url": item["data_url"]}
            for item in SOURCES.values()]


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
    data_status = "live" if len(sources) == 2 and sources[1].get("status") == "retrieved" else "partial"
    uncertainty = final.get("uncertainty_and_limitations", [])
    if not isinstance(uncertainty, list):
        uncertainty = [str(uncertainty)]
    uncertainty.extend([
        "Near-real-time satellite products are provisional and can be revised; use the product DOI and metadata for formal research.",
        "Regional summaries use approximately one-degree spatial subsampling of gridded products; they are not full-resolution area integrals.",
        "Short-window association does not establish ecological causality. Chlorophyll is a proxy for phytoplankton biomass, not a complete ecosystem measure.",
        "The chlorophyll product is subject to cloud and retrieval gaps; sample counts and date completeness are shown above.",
    ])
    report = {
        **final,
        "executive_summary": str(final.get("executive_summary", "Report agent did not return an executive summary.")),
        "research_question": req.query,
        "region": req.region,
        "geographic_bounds": workflow["data"]["bounds"],
        "time_period": {"start": workflow["start_date"], "end": workflow["end_date"]},
        "data_sources": sources,
        "data_availability": f"NOAA NCEI OISST was fetched through THREDDS NCSS; NOAA CoastWatch ERDDAP chlorophyll status is {sources[1].get('status', 'unknown')}. Retrieved at {workflow['data']['retrieved_at']}; see each dataset coverage and valid cell count.",
        "data_quality": quality,
        "methodology": "NOAA daily gridded SST and VIIRS chlorophyll-a regional means were computed from approximately 1-degree spatial subsamples, latitude-area weighted with cosine weights. Python computed descriptive summaries, an exploratory daily Pearson correlation, and an OLS slope over the selected window.",
        "numerical_analysis": stats,
        "claims": workflow["claims"],
        "critic_review": workflow.get("critique"),
        "references": [{"name": s["name"], "url": s["url"], "dataset_url": s["data_url"],
                        "variable": s["variable"], "units": s["units"], "dataset_coverage": s["dataset_coverage"]}
                       for s in sources],
        "uncertainty_and_limitations": list(dict.fromkeys(str(x) for x in uncertainty)),
        "model": os.getenv("GROQ_MODEL", "openai/gpt-oss-120b"),
        "token_usage": workflow["token_usage"],
    }
    result = {"session_id": session_id, "status": "completed" if workflow["ai_status"] == "completed" else "partial",
              "query": req.query, "mode": req.mode, "data_status": data_status,
              "ai_status": workflow["ai_status"], "stages": workflow["stages"],
              "chart": {"title": f"NOAA daily regional means · {req.region}", "data": workflow["data"]["observations"]},
              "statistics": stats, "data_quality": quality, "report": report,
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
