# ORCA-X scientific data audit

Audit date: 2026-11-21. This describes the code and runtime checks in this checkout. “Implemented and tested” means a real request returned data that the connector parsed; catalogue metadata alone never counts as a working connector.

## Baseline implementation

- Frontend: React/Vite research, history, prompt registry, evaluation, and settings pages. It originally exposed only a region and short day-window selector.
- Backend: FastAPI with ten versioned JSON prompt specs, a Groq-compatible chat-completions client, NOAA clients, Python statistics, and SQLite history plus daily OISST cache.
- Groq: `openai/gpt-oss-120b`, OpenAI-compatible endpoint `https://api.groq.com/openai/v1/chat/completions`, JSON object output. The API key remains backend-only. Requests now use `max_completion_tokens`; transient errors, provider retry times, and constrained-JSON generation errors have bounded recovery.
- Baseline data: NOAA NCEI OISST v2.1; NOAA CoastWatch NOAA-20 VIIRS chlorophyll connector. NCEI retrieval used regional archive files when the NCSS path timed out. CoastWatch was unreachable from the environment and was not treated as successful.
- Baseline analysis: daily regional mean, min/max, an OLS slope for the selected window, paired-day Pearson correlation. The original date-window limit was one year; this is not a multi-decade trend engine.
- Fake data: synthetic demo endpoint returns HTTP 410. CSV/JSON upload only validates/previews; it is not silently used as analysis evidence.

## Dataset catalogue and status

| Dataset / category | Provider and ID | Status | Working path and limits |
|---|---|---|---|
| Historical SST | NOAA NCEI OISST v2.1; `noaa_ncei_oisst_v2.1_avhrr_nrt_region_mean_1deg_v2` | `IMPLEMENTED_AND_TESTED` | Real regional daily SST retrieval, NetCDF parse, bounded cache; current run windows up to 365 days. The daily regional summaries do not implement multi-decade comparison or marine-heatwave methodology. [NOAA product](https://www.ncei.noaa.gov/products/optimum-interpolation-sst) |
| Satellite SST | MODIS Aqua L2P; `MODIS_A-JPL-L2P-v2019.0` | `AUTHENTICATION_REQUIRED` | Metadata catalogue only; NASA Earthdata credentials and granule reader are not configured. [PO.DAAC dataset](https://podaac.jpl.nasa.gov/dataset/MODIS_A-JPL-L2P-v2019.0) |
| Surface salinity | SMAP RSS L2C; `SMAP_RSS_L2_SSS_NRT_V6` | `AUTHENTICATION_REQUIRED` | Metadata catalogue only; Earthdata login required. [PO.DAAC dataset](https://podaac.jpl.nasa.gov/dataset/SMAP_RSS_L2_SSS_NRT_V6) |
| Sea surface height and currents | Copernicus Marine physics; `cmems_mod_glo_phy_anfc_0.083deg_P1D-m` | `AUTHENTICATION_REQUIRED` | Product metadata only; authenticated Toolbox subset retrieval is not configured. [Copernicus Marine](https://marine.copernicus.eu/) |
| Argo profiles | Argo GDAC; `ARGO_GDAC` | `METADATA_ONLY` | Public NetCDF/index source is catalogued; no GDAC index/profile parser is integrated. [Argo data](https://argo.ucsd.edu/data/) |
| MODIS Aqua chlorophyll | NASA Ocean Color; `MODISA_L3m_CHL` | `AUTHENTICATION_REQUIRED` | Metadata only; NASA Earthdata credentials are not configured. [NASA Ocean Color](https://oceancolor.gsfc.nasa.gov/) |
| Long-term ocean color | NASA SeaWiFS/multisensor; `NASA_OCEAN_COLOR_SEAWIFS` | `AUTHENTICATION_REQUIRED` | Metadata only; no cross-sensor harmonization is claimed. [NASA Ocean Color](https://oceancolor.gsfc.nasa.gov/) |
| Biogeochemistry | Copernicus Marine BGC; `GLOBAL_ANALYSISFORECAST_BGC_001_028` | `AUTHENTICATION_REQUIRED` | Metadata only; selected variables require authenticated product access. [Copernicus Marine](https://marine.copernicus.eu/) |
| Surface wind | NOAA ASCAT; `NOAA_ASCATA_WIND` | `METADATA_ONLY` | NCEI metadata catalogued; no direct subset/parser integrated. [NCEI metadata](https://www.ncei.noaa.gov/access/metadata/landing-page/bin/iso?id=gov.noaa.ncdc%3AC01659) |
| Historical climatology | NOAA WOA23; `WOA23` | `METADATA_ONLY` | Official variables, units, depth levels, grid, and 1991–2020 normal are catalogued; connector/anomaly calculation against this dataset is not integrated. [WOA23 data](https://www.ncei.noaa.gov/access/world-ocean-atlas-2023/) |
| Marine biodiversity | OBIS v3; `OBIS_OCCURRENCES` | `IMPLEMENTED_AND_TESTED` | Real bounded occurrence subset retrieved and parsed. Occurrence records are sampling records, not abundance, population health, or current presence. Licenses/citations follow contributing datasets. [OBIS API](https://api.obis.org/) |
| Fishing activity | GFW 4Wings; `GFW_4WINGS` | `AUTHENTICATION_REQUIRED` | Official API metadata only; no bearer token configured, and no scraping/bypass is used. [GFW API](https://api-doc.globalfishingwatch.org/our-apis/documentation/docs/v3/4wings) |
| Additional existing chlorophyll connector | NOAA-20 VIIRS `nesdisVHNnoaa20chlaDaily` | `UNAVAILABLE` | ERDDAP connector exists and records failure; host was unreachable during environment checks. This source is queried only when chlorophyll is relevant. |
| Scientific literature metadata | Crossref REST; `CROSSREF_WORKS` | `IMPLEMENTED_AND_TESTED` | Real work metadata and deposited abstracts retrieved; full text is not implied. [Crossref API](https://api.crossref.org/swagger-ui/index.html) |

The registry stores provider, ID, variables/units, access type, geographic/time coverage, resolution, authentication, license note, status, and scientific limitations. Dataset inventory also joins real successful retrieval timestamps and local NOAA cache size when present.

## Query and analysis behavior

- The selector is deterministic and independent of Groq, and is tested against the 16 specified query scenarios using registry IDs.
- Supported live retrieval is currently OISST, NOAA-20 chlorophyll (upstream unavailable here), OBIS occurrences, and Crossref literature. Other selected sources remain clearly marked metadata-only or require authentication.
- Query-specific retrieval skips unrelated NOAA variables; OBIS-only questions do not download SST. `GET /api/query/understand` exposes intent, selected source IDs, and availability.
- Multi-year requested periods and multi-region comparisons are detected and explicitly marked as unsupported by the current one-region, 365-day live-analysis path. Current-window results are not presented as if they answered a long-period comparison.
- Analysis functions include descriptive statistics and percentiles, missing-value counts, z-scores, moving averages, supplied-baseline anomaly calculation, seasonal bins, period mean comparison, endpoint vertical-profile gradient, and supported unit conversion. A valid climatology baseline is required to call an anomaly; WOA23 is not yet connected to the live path.
- Evidence IDs are mapped to actual retrieved source summaries/calculations. Claims without recognized references are marked unsupported. Quick mode skips redundant planner/synthesis calls but retains verification, critic, and final-report stages; comprehensive mode retains all seven AI prompt stages.

## Current gaps

- A common provenance-preserving observation schema is now used for NOAA regional aggregates and OBIS occurrence records and persisted in SQLite per research session; spatial coordinates remain null for area means because assigning a point would be misleading.
- Cache TTL/refresh/version invalidation and cache deletion are available only in basic form; OISST cache is keyed by date and source filename/version. OBIS/Crossref retrievals are audited but not cached.
- No download progress/streaming interface, generic connector test runner, CSV export of arbitrary provider subsets outside saved research results, or user-configurable NASA/Copernicus/GFW credentials.
- The scientific utilities are reusable, but only the available OISST summaries and OBIS/literature records participate in live workflows. The UI must not be read as indicating all twelve domains are fully operational.
- Multi-region, long-baseline anomaly/trend, Argo vertical profile ingestion, sensor harmonization, nutrient/oxygen analysis, currents/wind/fishing analysis, and causal inference remain incomplete.

## Validation performed

- All 16 query-selection scenarios tested against selected catalogue IDs.
- Groq request tests cover exact endpoint, model, JSON object response format, current token parameter, transient retry, provider retry-after, and malformed-constrained-output recovery.
- Statistics/schema/export tests cover missing values, percentiles, baseline anomalies, moving averages, comparisons, seasons, unit conversion, vertical gradient, provenance persistence, and normalized CSV export.
- Live read-only requests retrieved and parsed an OBIS subset and Crossref work metadata. Prior local OISST retrieval produced and cached seven daily rows. A short-mode live workflow completed all essential AI stages once; repeated runs may encounter the configured Groq organization TPM cap and use retry-after backoff.
- Current code checks: `backend/.venv/bin/python -m pytest -q backend/app` and `cd frontend && npm run build`.
