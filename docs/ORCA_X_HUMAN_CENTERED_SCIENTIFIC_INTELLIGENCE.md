# ORCA-X Human-Centered Scientific Intelligence

## Status and architecture

Milestone E adds a deterministic backend presentation layer at backend/app/presentation/human_answer.py. The layer consumes the actual API run's daily observations, computed summary statistics, source statuses, and (when present) marine heatwave detector result. It produces a versioned human_answer object in the report. It does not ask the language model to invent or restate numerical results.

The LLM synthesis remains available in the scientific evidence layer. The frontend defaults to **Understand**, with **Explore** for actual charts and detector maps and **Scientific evidence** for source metadata, methods, computed values, claims, synthesis, and orchestration diagnostics. API fields remain additive for existing clients.

## Temporal roles

- **Recent observations**: retrieved measurements for a recent requested window.
- **Historical observations**: observations for an explicitly old period.
- **Climatological baseline / historical reference**: only added to human_answer.temporal_sources when an MHW detector result carries an actually used baseline period. Its purpose is stated, and it is explicitly not a forecast.
- **Forecast / model prediction**: not implemented in the inspected workflow. A forecast/prediction query receives an explicit unsupported answer; recent measured data is not repackaged as a future prediction.

The report separately records the interpreted requested_time_period and selected time_period. Common relative phrases (today, this week, last week, this month, last month, and last N days) are resolved deterministically; explicit API dates take precedence. “Today” ends on the latest expected source day (UTC today minus three days), and the answer says that same-day data is delayed. human_answer.data_period.observed is based on days with valid SST. The source records preserve provider/dataset identifiers, retrieval status, provider coverage, retrieval timestamps where returned by the connector, and errors. Missing chlorophyll remains unavailable and is never translated to zero.

## Human answer and metric interpretation

The structure includes:

- direct_answer: concise, question-oriented text grounded in computed output.
- key_findings: available-day coverage, observed temperature range, chlorophyll availability, or detector finding when supported.
- metrics: a small set with a display label, value, plain-language meaning, and observed/computed/coverage kind.
- why_it_matters: contextualizes the data without claiming an unmeasured ecological impact.
- limitations: plain-language missing-data and method constraints.
- data_period: requested/selected window and valid observation coverage.
- temporal_sources: source provenance plus temporal role/type.
- explore: booleans indicating which actual visualization data exists.
- scientific_evidence: structured stats, provenance, and detector output.
- exploratory_trend: only for a trend-oriented question, with the existing simple slope labeled exploratory and not a climate trend.

The current SST slope remains in raw statistics for compatibility and technical investigation. It is not included in the ordinary direct answer or findings. When requested, it is relegated to the evidence layer with its period, sample count, and explicit lack of seasonal/autocorrelation adjustment. No confidence interval or significance is fabricated.

## Visualization behavior

- The daily chart is in Explore and uses returned observation values with null gaps; it does not interpolate.
- Chlorophyll's line and axis only render when there are valid chlorophyll observations. Otherwise a short availability note appears.
- The existing spatial MHW map remains in Explore and is rendered only when detector output exists.
- No generic map or anomaly plot is produced when the required analysis output is absent.

The MHW method string now clarifies the source's 0.25° grid and the approximately 1° coordinate sampling used by this bounded request. It does not imply that every source grid cell was analyzed.

## Regression and verification

backend/app/test_human_answer.py uses the exact previously reported SST/chlorophyll summary as an explicitly controlled fixture: 27/30 days, 26.85°C mean, 25.55–29.56°C range, 4.97°C/month raw slope, and missing chlorophyll. Those are not fresh observations. Tests assert that the slope does not enter the ordinary answer, missing chlorophyll stays missing, requested trends label the slope exploratory, the MHW baseline remains a historical reference, and forecasts fail closed.

At implementation time, pytest -q app completed with **68 passed** and one upstream Starlette/httpx TestClient deprecation warning. npm run build completed successfully; Vite emitted its existing large-chunk advisory (>500 kB). These offline checks do not constitute NOAA real-data validation. The prior NOAA validation record is retained; this milestone did not retrieve or validate new NOAA observations.

## Before and after

**Before:** The default result rendered a model-generated technical report, evidence IDs, a generic dual-axis chart, raw metric cards, and limitations together. An unadjusted least-squares slope from as few as three SST values could appear in the report as °C/month.

**After:** The default result starts with a deterministic plain-language answer, human-readable findings, actual coverage, and missing-data explanation. A trend-oriented query may expose the raw slope only as exploratory evidence. Users can still inspect the unchanged scientific record in the evidence layer.

## Remaining limitations

- Ambiguous phrases such as “recently” still use the selected API day window. Common calendar/rolling phrases are parsed; users can supply explicit API dates for exact custom intervals.
- The no-forecast behavior prevents a false forecast claim, but a prediction request still follows the existing retrieval workflow before presentation; a dedicated early refusal path could avoid unnecessary provider calls.
- General long-term climate trend analysis with seasonal adjustment, autocorrelation-aware uncertainty, and multi-year source coverage is not implemented by this presentation milestone.
- The current data connectors may fail at runtime. Human-readable presentation does not upgrade source availability or scientific verification status.
