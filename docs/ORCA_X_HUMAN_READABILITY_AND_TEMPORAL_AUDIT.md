# ORCA-X Human Readability and Temporal Integrity Audit

## Scope and inspected path

Inspected the request model and API route in `backend/app/main.py`, deterministic intent parsing in `backend/app/query/understanding.py`, date selection and NOAA source metadata in `backend/app/data_sources/noaa_erddap.py`, retrieval/analysis/evidence/synthesis in `backend/app/agents/orchestrator.py`, numerical summaries in `backend/app/analysis/statistics.py`, and result rendering in `frontend/src/App.tsx`. Also inspected the existing NOAA MHW validation artifact and current repository tests. This is a source-code audit; it does not claim a fresh NOAA run.

## Findings before remediation

| Component | Observed implementation | Status |
|---|---|---|
| Date window | `select_window()` clips the requested end date to an estimated latest available day (UTC today minus three days), defaults to the requested window length, and rejects spans over 365 days. It does not parse relative phrases such as “last month” itself. | Implemented; relative date language can be overridden only by API date fields/default window |
| Intent and datasets | Deterministic keyword rules identify variables, analysis intents, explicit year ranges, and selected datasets. “forecast/future” can create a prediction intent, but selection does not provide a forecast connector. | Partial; prediction is not backed by a forecast data source |
| Recent SST/chlorophyll | The standard path retrieves NOAA OISST and NOAA-20 VIIRS chlorophyll independently. `fetch_region()` records per-source status/errors and returns nulls for missing variable-days; chlorophyll failures are retained as source errors. | Implemented; actual success depends on live provider access |
| Historical MHW reference | The orchestrator calls `_retrieve_spatial_baseline()` only in the spatial MHW branch. It retrieves final OISST for 1991–2020 in yearly chunks, validates dates, units, and grid alignment, and caches the array. This is a climatology input, not a current observation or forecast. | Implemented; verification is represented in MHW output/provenance |
| MHW target | Spatial grid OISST is retrieved for the selected period and analyzed against that historical climatology. The map receives `report.marine_heatwave_analysis`. | Implemented; retain this path and map |
| Numerical summaries | `analyze()` computes means/ranges and SST–chlorophyll paired-day correlation. It also fits an unadjusted linear regression on observation indices whenever there are at least three valid SST values, then scales it to °C/month. The index does not account for missing-day spacing, seasonality, or serial dependence. | Implemented but unsuitable as a general/primary trend claim |
| Answer generation | The final report is produced in the orchestrator’s LLM synthesis stage from computed context and evidence. The API copies its narrative, claims, and limitations into `report`. | Implemented; narrative is not a separate deterministic plain-language presentation model |
| Evidence and coverage | The orchestrator creates `NOAA_SST`, `NOAA_CHL`, association, and MHW evidence objects; it counts valid SST/chlorophyll and paired days. API exposes source metadata, quality, stats, claims, method text, and raw LLM report. | Implemented; presentation exposes technical internals by default |
| Frontend | The main result shows a generic dual-axis SST/chlorophyll chart, mean cards (including a dash for missing chlorophyll), Groq narrative, evidence IDs, and full limitations. MHW map is conditional on a detector result. | Implemented; no separate Understand/Explore/Evidence presentation layers |
| Tests | Backend tests cover statistics, intent selection, API, and MHW behavior; tests are fixture/offline-focused. | Implemented; do not treat as live-data verification |

## Trace of the reported SST/chlorophyll example

The values 26.85°C, 25.55–29.56°C, 27 valid SST days, 4.97°C/month, 90% coverage, and absent chlorophyll were supplied as a previously reported result in the Milestone E request. The exact saved session was not established during this source audit, so these values are treated as a documented regression fixture, not as newly retrieved data. Their corresponding code paths are:

- `analyze()` derives mean/min/max and valid-day counts from non-null observation rows; it computes the short-window slope described above.
- `run_research()` computes completeness as valid SST days divided by requested days, and produces the NOAA evidence key for retrieved SST.
- `fetch_region()` keeps failed chlorophyll retrieval status/error and emits no chlorophyll values rather than interpreting absence as zero.
- The frontend renders the LLM narrative and raw statistical/evidence content without a human-readable layer.

The prompt-provided 90% is consistent with 27/30 coverage, but all listed figures remain prior-output fixture data unless a saved artifact proves otherwise.

## Baseline and temporal integrity

The 1991–2020 final OISST dataset is used in the spatial MHW path to calculate cell-level seasonal climatology and percentile thresholds. It is not used by the ordinary recent SST/chlorophyll descriptive-statistics path. The MHW result includes separate target and baseline provenance/period fields. Before remediation, the top-level API does not provide one normalized temporal-role schema for each source. No current forecast dataset or prediction model was found in the inspected question-to-answer path; forecast requests therefore must be labeled unsupported rather than answered using recent/historical observations.

## Remediation targets

1. Add a backend-built, structured, deterministic human answer based on computed values, source availability, and detector output; preserve the LLM report as scientific detail.
2. Add explicit temporal-role/source metadata, including the MHW baseline only when the detector actually used it.
3. Suppress the simplistic SST slope from the primary answer and label it exploratory in the evidence layer; do not claim long-term trend significance.
4. Render Understand, Explore, and Scientific Evidence views. Keep missing chlorophyll missing and the existing conditional MHW map intact.
5. Add fixture-backed presentation tests and run the backend suite and frontend build. Passing offline tests is not live NOAA validation.
