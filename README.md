# ORCA-X

ORCA-X is an evidence-grounded marine research workspace. A research run fetches bounded, recent NOAA gridded observations, calculates regional summaries in Python, executes a ten-stage workflow with Groq-backed prompt agents and deterministic data tools, verifies model claims against available dataset evidence IDs, and stores the report and daily aggregates in SQLite.

## Live data sources

- NOAA NCEI Daily OISST v2.1 AVHRR near-real-time SST, 0.25° global grid, retrieved from the NCEI archive through THREDDS NCSS, variable `sst`, °C. Preliminary days are identified in source metadata and can later be replaced by final files.
- NOAA NOAA-20 VIIRS daily near-real-time chlorophyll-a, 4 km global grid: [`nesdisVHNnoaa20chlaDaily`](https://coastwatch.pfeg.noaa.gov/erddap/info/nesdisVHNnoaa20chlaDaily/index.html), variable `chlor_a`, mg m⁻³. NOAA metadata labels this ocean-color product near-real-time/experimental with gaps and product-specific latency.

At each run ORCA-X reads the NCEI archive catalog and downloads region-bounded SST subsets through NCSS. It fetches CoastWatch ERDDAP metadata for chlorophyll, clamps retrieval to provider coverage, and records chlorophyll as unavailable when that provider cannot be reached. The app reports the data coverage, retrieval time, source links, sampled cell counts, and completeness. It never replaces a retrieval failure with synthetic observations. The spatial subset is sampled at approximately one-degree spacing and uses cosine latitude weighting; it is a regional exploratory summary, not a full-resolution area integral.

## Workflow

1. Orchestrator, Query Decomposition, and Marine Research Planner run as separate Groq JSON-mode prompt calls.
2. Data Retrieval requests NCEI archive/NCSS SST subsets and CoastWatch ERDDAP chlorophyll metadata and grids.
3. Data Quality checks actual coverage and valid daily samples in Python.
4. Scientific Analysis computes daily weighted means, descriptive statistics, paired-day Pearson correlation, and an exploratory slope in Python.
5. Evidence Verification, Critic, Scientific Synthesis, and Final Report are separate Groq calls. Model claims are limited to recognized dataset/calculation evidence IDs; unmatched claims are marked unsupported.
6. The result, stage outputs, and daily observations are saved in SQLite.

Ten prompt specifications live as separate, versioned JSON files in `backend/app/prompts/`. Stages 4–6 use the actual NOAA client and deterministic Python calculations; the other seven stages call the configured Groq chat completion endpoint. A failed Groq call is recorded, remaining model stages are skipped, and the result is marked partial. NOAA failure returns an error; it does not produce a fake report.

## Run locally

Requires Python 3.11+ and Node 20+.

1. Copy `.env.example` to `.env` and set `GROQ_API_KEY`.
2. Install and start the backend:

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r backend/requirements.txt
uvicorn app.main:app --app-dir backend --host 127.0.0.1 --port 8000
```

3. In another terminal:

```bash
cd frontend
npm ci
npm run dev -- --host 127.0.0.1 --port 5173
```

Open http://localhost:5173. API docs are at http://localhost:8000/docs.

## Configuration and secrets

```env
GROQ_API_KEY=                 # required; backend only
GROQ_MODEL=openai/gpt-oss-120b
GROQ_BASE_URL=https://api.groq.com/openai/v1
ORCA_DB_PATH=./orca_x.sqlite3
CORS_ORIGINS=http://localhost:5173,http://localhost:8080
```

The key is loaded by the backend and is never returned by the config endpoint or sent to the frontend. The documented Groq base URL defaults to `https://api.groq.com/openai/v1`; `GROQ_BASE_URL` is configurable for compatible gateways. The default model is `openai/gpt-oss-120b`. `.env` and the SQLite database are git-ignored. Set `GROQ_API_KEY` as a secret in any hosted environment; do not put it in `render.yaml`, frontend variables, logs, or commits.

## API

- `GET /api/health`, `/api/config/status`, `/api/data-sources`, `/api/regions`
- `POST /api/research` with `query`, `region`, `window_days` (7–365), and `mode`
- `GET /api/research/history`, `/api/research/{session_id}`, `/api/research/{session_id}/events`
- `POST /api/research/{session_id}/rerun`, `DELETE /api/research/{session_id}`
- `GET /api/prompts`, `/api/prompts/{prompt_id}`
- `POST /api/upload` validates CSV/JSON (5 MB); uploads are not yet used as analysis input

Research regions: Arabian Sea, Indian Ocean, Bay of Bengal, and South China Sea. The UI exposes history, prompt registry, run metrics, settings status, and JSON report export.

## Docker and deployment

Local multi-container development:

```bash
docker compose up --build
```

The root `Dockerfile` packages the frontend and API as one service. `render.yaml` is a Render Blueprint. For deployment, connect the GitHub repository in Render, apply the Blueprint, and set `GROQ_API_KEY` in Render's secret environment variables. SQLite on a free host may be ephemeral; use a persistent disk or PostgreSQL before relying on hosted history. No hosted deployment has been performed.

## Validation

```bash
.venv/bin/python -m pytest -q backend/app/test_api.py
cd frontend && npm run build
```

Tests cover configuration secrecy, prompt registry, region validation, removal of synthetic mode, NOAA query generation, numerical analysis, SQLite persistence, and date limits. Live provider availability depends on network access and upstream data freshness; near-real-time products can have several days of latency and may be revised. Pearson correlation is exploratory and does not establish ecosystem causation. The interface is a research prototype, not a validated operational scientific instrument.
