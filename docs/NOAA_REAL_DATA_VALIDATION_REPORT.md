# ORCA-X NOAA MHW validation status

**Status: PARTIALLY VERIFIED; live observations BLOCKED by an HTTP 503 on the NOAA ERDDAP data route.**

## Execution path inspected

The research request passes through deterministic query understanding and dataset selection in `app/query/understanding.py` and `app/analysis/methods.py`. The orchestrator (`app/agents/orchestrator.py`) detects the `marine_heatwave_detection` method, retrieves target SST with `fetch_oisst_spatial_grid`, retrieves the 1991–2020 final OISST period through the same function, builds a per-cell climatology and threshold, calls `detect_spatial_mhw`, then includes that result in evidence verification and the final report context. The deterministic final MHW summary is generated from the detector status. Regional means are still calculated as a supplementary chart/statistics product; they are not the MHW classifier.

## Data source and metadata

- Target: NOAA/NCEI OISST v2.1 AVHRR preliminary, ERDDAP ID `ncdcOisst21NrtAgg`.
- Baseline: NOAA/NCEI OISST v2.1 final, ERDDAP ID `oisst_rclone`.
- Variable: `sst`, units `degree_C`, daily; metadata reports 0.25° coordinates and a depth/z coordinate at 0 m.
- Metadata pages: [preliminary dataset](https://upwell.pfeg.noaa.gov/erddap/griddap/ncdcOisst21NrtAgg.html), [final dataset](https://upwell.pfeg.noaa.gov/erddap/griddap/oisst_rclone.html).
- These metadata pages do not constitute retrieval of observations by ORCA-X.

## Retrieval and baseline implementation

The gridded retrieval decodes NetCDF `sst`, time, latitude and longitude, masks fill values and implausible SST, normalizes coordinate order, and rejects unexpected units. Requests longer than 366 days are divided into contiguous 365-day chunks; each chunk is checked for complete unique daily coverage and matching coordinates before assembly. Successful chunks are cached as compressed NPZ files under the system temporary directory, keyed by the complete ERDDAP request URL (dataset, bounds, variable, dates, and spatial subset). A corrupt cache entry is deleted and re-fetched. The detector refuses a grid mismatch or incomplete time chunk.

The configured baseline remains 1991–2020. Cell-specific climatology uses an 11-day circular calendar window, 90th percentile, and 31-day circular smoothing; an event requires five days and may join exceedance runs across up to two valid non-exceedance days. Missing SST breaks an event. The baseline builder requires at least 20 years and adequate per-cell samples; empty windows remain NaN.

**Live execution attempts:**

1. In the default restricted execution environment, DNS lookup of `upwell.pfeg.noaa.gov` failed with `[Errno 8] nodename nor servname provided, or not known`.
2. With external network access enabled for the command, the NOAA metadata endpoint returned HTTP 200. A one-day regional data request returned HTTP 503 after redirect from `upwell.pfeg.noaa.gov` to `coastwatch.pfeg.noaa.gov`; the application retrieval exhausted its three attempts. No SST values were downloaded, parsed, or analyzed. NOAA metadata was accessible, but its data query route returned a temporary service-unavailable response. This does not establish a NOAA-wide outage.

An actual ORCA-X `POST /api/research` request was then run for “Are there signs of marine heatwave conditions in the Arabian Sea?” using a 7-day window. The API returned HTTP 200 with `data_status=unavailable`; the retrieval stage records dataset ID `ncdcOisst21NrtAgg`, status `unavailable`, and zero grid observations. The MHW stage was unavailable because target SST retrieval failed, so the baseline and detector were not run. The evidence-verification and final-report stages completed; the saved claim states there is insufficient data and carries `Insufficient evidence`. No NOAA-derived scientific result was generated.

## Test and verification results

- Full backend suite: `61 passed`, one Starlette/httpx TestClient deprecation warning.
- NOAA real-observation retrieval: attempted; metadata succeeded, regional observation query returned HTTP 503 after redirect to CoastWatch.
- Real 1991–2020 baseline download/assembly: not verified.
- Real-data spatial MHW result: not produced.
- Live backend question pipeline: executed; stopped honestly at unavailable target retrieval; no frontend browser session was exercised.
- Synthetic/offline method tests are not real-world validation.

## Reproduction

From `backend/`, with network access and the declared requirements installed:

```bash
python - <<'PY'
import asyncio
from datetime import date
from app.data_sources.mhw_oisst import fetch_oisst_spatial_grid
from app.data_sources.noaa_erddap import REGIONS

async def main():
    grid = await fetch_oisst_spatial_grid(REGIONS["Arabian Sea"], date(2026, 11, 18),
        date(2026, 11, 18), dataset_id="ncdcOisst21NrtAgg")
    print(grid["dataset_id"], grid["dates"], len(grid["latitudes"]),
          len(grid["longitudes"]), grid["units"])

asyncio.run(main())
PY
pytest -q app
```

Run a complete MHW query through `POST /api/research` after the ERDDAP regional data endpoint serves the requested grid. Do not interpret the current metadata, backend 200 response, or offline tests as a real-data classification.

## NOAA Alternative Access Investigation — 2026-11-24

> **Historical snapshot:** The status below records the investigation before Milestone B completed. It was superseded by the verified baseline, detector, and API results in the Milestone B section at the end of this report.

### Network and endpoint diagnostics

No HTTP proxy variables were configured. DNS resolves `upwell.pfeg.noaa.gov` (IPv4) and `coastwatch.pfeg.noaa.gov` (IPv6) in the network-enabled command environment. The default sandbox previously failed DNS. NOAA ERDDAP metadata for `ncdcOisst21NrtAgg` returned HTTP 200. An ERDDAP observation query redirected to CoastWatch; that route returned HTTP 503 for a point query, and the spatial query timed out after retries. Thus metadata and data endpoints behave differently; the tested ERDDAP observation route is not usable in this run.

The official NCEI THREDDS fileServer route was tested as an alternative and returned HTTP 200 for an actual daily preliminary NetCDF file. This is an official NCEI-hosted file distribution route, not synthetic data. The OPeNDAP metadata descriptor for the preliminary file returned HTTP 200, but an OPeNDAP query against the final best-time-series dataset timed out. The guessed historical final file for 2026-11-18 returned 404 (that path/date is not an available final file); a 1991 final archive daily file route returned HTTP 200 once, but a repeat request timed out. Full baseline completeness was not established.

### Actual target observations retrieved

Successfully downloaded and parsed:

- Product: NOAA/NCEI OISST v2.1 preliminary AVHRR-only, dataset ID `ncdcOisst21NrtAgg`.
- Access: NCEI THREDDS `fileServer` daily NetCDF, [2026-11-18 preliminary file](https://www.ncei.noaa.gov/thredds/fileServer/ncFC/fc-oisst-daily-avhrr-only-dly-prelim/files/202611/oisst-avhrr-v02r01.20261118_preliminary.nc).
- HTTP 200; downloaded 1,537,643 bytes.
- Actual time coordinate: 2026-11-18 12:00 UTC; variable `sst`, units `Celsius`, fill value -999.
- Project Arabian Sea bounds: 5–30°N, 50–80°E. Subset grid: 100 × 120 cells; coordinates span 5.125–29.875°N and 50.125–79.875°E (0.25° spacing).
- Valid cells: 7,085; missing/land cells: 4,915 (40.96%). Valid SST minimum 23.46°C, maximum 30.30°C, mean 28.9605°C, standard deviation 0.7821°C.
- Compact output: `docs/noaa_arabian_sea_target_sample.json`.

This is a one-day observed gridded SST sample, not an MHW determination. Product metadata identifies a 0.25° grid; the NRT and final products are both OISST v2.1, but no actual final-baseline grid file was successfully parsed and coordinate-compared in this run. Cross-product grid compatibility is therefore not declared verified.

### Baseline, detector, and end-to-end status

- The 1991–2020 final OISST baseline was **not** retrieved or assembled. A final archive daily file route returned HTTP 200 once, but no 30-year baseline was calculated; the OPeNDAP query timed out and the current ERDDAP data path returns 503/timeouts. Per the workflow's completeness guard, a partial baseline is not used.
- Spatial detector on real observations: not executed, because the required historical threshold baseline is unavailable.
- Full real-data MHW question pipeline: previously executed against the ERDDAP primary route and safely returned insufficient evidence. It was not rerun through the NCEI fileServer fallback; the app currently uses the ERDDAP griddap route, so the successful fileServer route has not been integrated.
- Latest backend tests remain `61 passed, 1 warning` from the previous run; this validation made no source-code changes. The warning is the existing Starlette/httpx `TestClient` deprecation warning.

### Verification milestones

| Milestone | Status |
|---|---|
| NOAA metadata accessible | VERIFIED |
| Real preliminary SST observations downloaded and parsed | VERIFIED (one day, NCEI fileServer) |
| Final baseline real file/chunk fully processed | NOT VERIFIED |
| Complete 1991–2020 baseline validated | BLOCKED |
| Spatial MHW detector run on real target + baseline | NOT RUN |
| End-to-end real-data MHW classification | NOT VERIFIED |

The report does not infer a heatwave or its absence from the one-day SST sample.

## Milestone B — Real Baseline, Spatial Detection, and ORCA-X Pipeline — 2026-11-24

### Changes made

- Added a bounded NCEI THREDDS daily-file fallback for short target windows when ERDDAP fails; it validates NetCDF content, units, time, coordinates, and per-day ocean data, and caches validated grids. Multi-year baseline retrieval does not fall back to downloading thousands of global daily files.
- Changed the application baseline path to assemble validated 1991–2020 annual chunks into a disk-backed array. This avoids materializing the entire multi-decade grid as Python lists in memory. Chunks are checked for exact daily coverage, consistent grid and units, and the assembled period is checked for duplicates/gaps.
- NOAA returned HTTP 408 for one annual chunk during an initial four-way retrieval. The retry policy now retries 408 and 429 responses rather than treating 408 as a permanent client error.
- Fixed climatology percentile calculation so all-NaN land cells are excluded before percentile evaluation; they remain NaN and do not become valid temperatures.
- Compact detector evidence sent to Groq agents to include event count, peak event, area coverage, per-day coverage, and top hotspots rather than thousands of per-cell records. This resolved a provider HTTP 400 (“reduce the length of the messages or completion”) and let verification, critique, and final-report agents complete.

### A. Target data

- Retrieved through the ORCA-X research API for **2026-11-12 through 2026-11-18**.
- NOAA/NCEI OISST v2.1 AVHRR preliminary, dataset ID `ncdcOisst21NrtAgg`, daily SST in °C.
- Source query: NOAA ERDDAP griddap request recorded in the result artifact. The target array is 7 × 101 × 121 at 0.25°; 49,756 of 85,547 daily grid values are valid and 41.84% are missing in the broad regional bounding grid.
- The previous NCEI THREDDS fileServer sample remains recorded separately in `docs/noaa_arabian_sea_target_sample.json`; the successful full-week application run used the ERDDAP query route.

### B. Historical baseline

- NOAA/NCEI OISST v2.1 **final**, dataset ID `oisst_rclone`, 1991-01-01 through 2020-12-31.
- Retrieved in 30 annual chunks (365 or 366 days each). All chunks had exact daily coverage, unique chronological dates, and matching 0.25° coordinates against the target grid. Years 1991–2020 were assembled; 1991–1997 were already present in validated cache, later years were retrieved and cached during this run.
- Disk-backed baseline array: 10,958 × 101 × 121; 77,889,464 valid values and 56,028,254 missing values (41.84%). The missing grid cells are spatially consistent with land/out-of-ocean cells in the regional rectangle; 7,108 cells have valid baseline observations.
- Baseline builder used the existing settings: 11-day circular calendar window, per-cell daily mean, 90th percentile, 31-day circular smoothing, at least 20 baseline years. Target and baseline coordinate arrays matched exactly.

### C. Scientific execution and result

- Existing spatial detector executed with real preliminary target data and the real 1991–2020 final baseline.
- Grid: 0.25°; 7,108 valid ocean cells. Classification: **MHW threshold events detected** in 6,033 cells; the area-weighted footprint reached **85.07%** (about **4.51 million km²**) during the selected week.
- Detector reported 6,033 cell events, durations 5–7 days, median duration 7 days. Mean cell-event mean intensity was 1.224°C above climatology; maximum peak intensity was 2.295°C. Top hotspot: 24.875°N, 53.875°E; event 12–16 November, 5 days, mean intensity 1.493°C, peak 2.295°C.
- These are short-window marine-heatwave threshold classifications under the documented Hobday-style criteria; they are not a climate trend or causal ecological claim. The target is preliminary and may be revised.
- Full compact detector output and daily coverage: `docs/noaa_arabian_sea_mhw_result.json` (about 2.95 MB, including per-cell events and hotspot locations).

### D. ORCA-X end-to-end

The actual `POST /api/research` question was run with the 7-day period. API result: HTTP 200, `status=completed`, `data_status=live`, `ai_status=completed`. Retrieval, MHW detection, evidence verification, critic, and final report stages completed. The verifier returned a supported claim tied to `MHW_DETECTION` and `NOAA_SST`. Final answer reported detected events, 6,033 cells, approximately 85% area, peak intensity 2.30°C, and the target/baseline period. No stage was mocked.

### E. Tests and bugs

- Full backend suite after code changes: **61 passed**, one existing Starlette/httpx `TestClient` deprecation warning.
- Fixed the baseline assembly validation script's leap-day inclusive count: 1991–2020 contains 10,958 daily records, not 10,957. All 30 chunks passed after correcting the count.
- The first full API attempt found the LLM context was too large because all grid-cell events were sent to the verifier. Compact structured evidence fixed this; the second actual API run completed all required stages.

### F. Remaining limitations

- The verified question covered a specific seven-day period (2026-11-12 to 2026-11-18); results should not be generalized beyond that period or region.
- The NCEI fileServer fallback is for short target windows; the 1991–2020 baseline uses NOAA ERDDAP annual chunks and cached subsets.
- At this Milestone B snapshot, the frontend did not yet render the spatial event map; the follow-on implementation is documented below.

### Status table

> **Snapshot at Milestone B:** The frontend row below reflects the implementation state before Milestone D; the current frontend status is recorded in the Milestone D section.

| Milestone | Status |
|---|---|
| Real target SST grid retrieved and parsed | VERIFIED WITH REAL DATA |
| Complete 1991–2020 final OISST regional baseline | VERIFIED WITH REAL DATA |
| Grid compatibility and baseline chunk completeness | VERIFIED WITH REAL DATA |
| Spatial detector executed on target plus baseline | VERIFIED WITH REAL DATA |
| Actual ORCA-X API question pipeline and evidence trace | VERIFIED WITH REAL DATA |
| Full backend regression suite | VERIFIED WITH TESTS (61 passed) |
| Frontend spatial map | NOT IMPLEMENTED |

## Milestone D — Interactive Spatial Visualization — 2026-11-24

### Implementation

- Replaced the earlier MHW-only summary card in the research result with a map-first spatial analysis view that consumes `report.marine_heatwave_analysis` returned by the existing research API.
- Added a responsive native SVG map using Web Mercator coordinates and the detector's native 0.25° cell spacing. OpenStreetMap raster tiles provide coastlines and geographic context, with visible attribution. No mapping package or project dependency was added.
- Added selectable qualifying-cell, mean event anomaly, peak event intensity, and top-hotspot layers; grid-cell selection details; zoom, pan, reset; a date slider; daily cell and area-weighted coverage; analysis bounds; and expandable data provenance.
- The API detector result now includes the baseline dataset ID and target valid/total/missing grid-value counts for disclosure in the result view. This adds response metadata only; it does not alter the detector or thresholds.

### Data represented and interpretation

- The map uses detector event-cell coordinates, event dates/durations, mean event anomaly, maximum event intensity, area, hotspot ranking, daily spatial coverage, and the verified regional/baseline metadata. The daily timeline's visible cell footprint is derived from each detector event's start/end interval and was checked against all seven detector daily affected-cell counts.
- Absolute SST, local climatology, and daily per-cell anomaly arrays are not included in the detector response, so the map does not present them. “Mean event anomaly” and “peak event intensity” are event-level detector metrics, not absolute SST.
- The detector serializes qualifying event cells, not all non-event and missing cell coordinates. Those categories are not fabricated or drawn; valid and affected counts and bounding-grid missing/land percentage are shown separately.
- Basemap tiles require an internet connection. If tiles fail, the interface displays a basemap warning while retaining the NOAA-coordinate event overlay.

### Verification

- `frontend`: `npm run build` passed. Vite reports the application bundle is over its 500 kB advisory threshold (about 674 kB minified); build completes successfully.
- `backend`: `pytest -q app` — **61 passed, 1 Starlette/httpx TestClient deprecation warning**.
- Browser smoke check used a temporary local fixture API backed directly by `docs/noaa_arabian_sea_mhw_result.json`; it did not request new NOAA data or call Groq. The UI rendered the actual saved result (7,108 valid cells; 6,033 cells with events), map coastlines, cell overlays, and controls. Selecting 2026-11-12 showed 6,020 affected cells and 84.9% area; selecting 2026-11-18 showed 5,665 cells and 79.9%, matching the artifact. A clicked cell displayed its stored coordinates and event metrics. Mean-anomaly layer switching and mobile-width layout were also checked.
- The exact production `/api/research` route was not rerun after this frontend work. The component is wired to the route's existing MHW result payload; the browser smoke check verifies rendering against the saved real detector output, not a new end-to-end scientific execution.

### Status

| Capability | Status |
|---|---|
| Real detector event cells rendered geographically | VERIFIED AGAINST SAVED REAL RESULT |
| Daily timeline and spatial coverage display | VERIFIED AGAINST SAVED REAL RESULT |
| Layer switching and selected-cell details | BROWSER CHECKED |
| Production API wiring | IMPLEMENTED; no new live API run in this milestone |
| Mobile layout | BROWSER CHECKED at narrow viewport |
| Non-event/missing-cell raster layer | UNAVAILABLE in current detector output |
| Absolute SST/anomaly field map | UNAVAILABLE in current API detector output |
| Offline basemap coastlines | UNAVAILABLE; online OSM tiles are used |
## Milestone E presentation update — 2026-11-24

This is a presentation/API metadata update only. No new NOAA request, download, baseline assembly, detector run, or scientific result was produced in this milestone. The validation findings and historical run records above are unchanged.

- The API now adds a deterministic human-readable answer and temporal source roles to each response.
- The ordinary answer hides the generic short-window SST slope; trend-oriented questions may inspect it only as exploratory output.
- The result UI separates Understand, Explore, and Scientific evidence. The MHW map remains conditional on real detector output.
- The previous SST/chlorophyll figures in the Milestone E prompt are used only as a controlled test fixture, not as newly verified data.
- Offline status for this change: backend suite 68 passed (one Starlette/httpx deprecation warning); frontend production build succeeded with a bundle-size advisory.
