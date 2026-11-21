# ORCA-X

ORCA-X is an evidence-grounded marine research workspace. It has a query-aware dataset registry, bounded NOAA retrieval, public OBIS occurrence and Crossref literature retrieval, deterministic Python analysis, Groq-backed verification/critique/reporting, SQLite persistence, and dataset/cache management pages. Provider status is shown honestly: most catalogue entries still require credentials or a connector.

## Live data sources

- NOAA NCEI Daily OISST v2.1 AVHRR near-real-time SST, 0.25° global grid, retrieved from the NCEI archive through THREDDS NCSS, variable `sst`, °C. Preliminary days are identified in source metadata and can later be replaced by final files.
- NOAA NOAA-20 VIIRS daily near-real-time chlorophyll-a, 4 km global grid: [`nesdisVHNnoaa20chlaDaily`](https://coastwatch.pfeg.noaa.gov/erddap/info/nesdisVHNnoaa20chlaDaily/index.html), variable `chlor_a`, mg m⁻³. NOAA metadata labels this ocean-color product near-real-time/experimental with gaps and product-specific latency.

At each query ORCA-X deterministically selects relevant dataset IDs and retrieves only supported surface variables. It reads the NCEI archive catalog and uses THREDDS NCSS with a direct archive fallback for regional OISST subsets. NOAA CoastWatch chlorophyll is queried only when relevant; it is marked unavailable when the upstream host cannot be reached. OBIS occurrence and Crossref routes have been exercised against their public APIs. The UI reports source coverage, retrieval time, sampled cell counts, cache sizes, and failed requests; it never substitutes synthetic observations. OISST regional summaries use approximately one-degree sampling and cosine latitude weighting, not a full-resolution area integral.

## Workflow

1. Query Understanding parses parameters, regions, periods, intent, answer profile, and scope limitations; Dataset Selection emits real registry IDs and access status.
2. Relevant supported connectors retrieve bounded data. Species queries use OBIS; explanatory queries can search Crossref; SST/chlorophyll queries only request relevant NOAA variables.
3. Python checks coverage and calculates descriptive statistics, period comparisons, anomaly baselines, season summaries, moving averages, z-scores, unit conversions, and vertical-profile gradients. Only the OISST summary/correlation functions are currently connected to live research runs.
4. Comprehensive runs use seven Groq stages. Quick/short runs skip redundant planning and synthesis but retain evidence verification, independent critique, and the final report. Groq calls use the official OpenAI-compatible chat endpoint, JSON mode, `max_completion_tokens`, low reasoning effort for quick replies, bounded JSON-generation recovery, and transient/rate-limit retries.
5. The report preserves measured sources, literature, OBIS occurrence caveats, selected IDs, actual window, data status, and capability/scope limits. Normalized provenance-bearing NOAA/OBIS observations and NOAA daily cache rows are stored in SQLite; retrieval success/failure is audited. Saved research supports JSON and normalized CSV export.

Ten prompt specifications live as separate, versioned JSON files in `backend/app/prompts/`. When a Groq stage ultimately fails, the error is recorded and dependent stages are skipped; a partial result is labeled partial. Historical multi-year comparisons and multi-region statistics are currently recognized but not computed by the live workflow, and the report explicitly warns about those scope mismatches.

## Run locally

Requires Python 3.11+ and Node 20+.

1. Copy `.env.example` to `.env` and set `GROQ_API_KEY`.
2. Install and start the backend:

```bash
python3 -m venv backend/.venv
source backend/.venv/bin/activate
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

The key is loaded by the backend and is never returned by the config endpoint or sent to the frontend. The documented Groq base URL defaults to `https://api.groq.com/openai/v1`; `GROQ_BASE_URL` is configurable for compatible gateways. The default model is `openai/gpt-oss-120b`. The ignored project `.env` is authoritative for local development; hosted images do not include it and use deployment environment secrets instead. `.env` and the SQLite database are git-ignored. Set `GROQ_API_KEY` as a secret in any hosted environment; do not put it in `render.yaml`, frontend variables, logs, or commits.

## API

- `GET /api/health`, `/api/config/status`, `/api/data-sources`, `/api/regions`
- `GET /api/datasets`, `/api/datasets/{dataset_id}`, `/api/datasets/{dataset_id}/sample`
- `POST /api/query/understand`, `POST /api/datasets/obis/retrieve`, `GET /api/literature/search?q=...`
- `GET /api/data-management/cache`, `/api/data-management/retrievals`; cache deletion requires `confirm=true`
- `POST /api/research` with `query`, `region`, `window_days` (7–365), and `mode`
- `GET /api/research/history`, `/api/research/{session_id}`, `/api/research/{session_id}/events`
- `POST /api/research/{session_id}/rerun`, `DELETE /api/research/{session_id}`
- `GET /api/prompts`, `/api/prompts/{prompt_id}`
- `POST /api/upload` validates CSV/JSON (5 MB); uploads are not yet used as analysis input

Research regions: Arabian Sea, Indian Ocean, Bay of Bengal, and South China Sea. The UI exposes history, prompt registry, evaluations, settings, answer preferences, dataset catalog, data management, and JSON report export.

## Docker and deployment

Local multi-container development:

```bash
docker compose up --build
```

The root `Dockerfile` packages the frontend and API as one service. `render.yaml` is a Render Blueprint. For deployment, connect the GitHub repository in Render, apply the Blueprint, and set `GROQ_API_KEY` in Render's secret environment variables. SQLite on a free host may be ephemeral; use a persistent disk or PostgreSQL before relying on hosted history. No hosted deployment has been performed.

## Validation

```bash
backend/.venv/bin/python -m pytest -q backend/app
cd frontend && npm run build
```

Tests cover 16 dataset-selection scenarios, API/catalog behavior, Groq endpoint/payload/retry behavior, scientific statistics/unit conversions, configuration secrecy, and SQLite persistence. Actual live request checks retrieved and parsed OBIS occurrences and Crossref works metadata; NOAA OISST regional values are cached locally. NOAA CoastWatch chlorophyll was unavailable from this environment. See [the data audit](docs/data-audit.md) for per-source details. Live products may have latency/gaps and be revised. Pearson correlation does not establish causation. This is a research prototype, not a validated operational scientific instrument.
