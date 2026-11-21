# ORCA-X intelligence and evidence audit

## Root causes addressed

- The workflow selected SST for a marine-heatwave question, then computed descriptive values and a slope over the requested short window. It had no event method, daily seasonal threshold, duration check, or baseline retrieval.
- Verification was based on whether a model claim referenced any retrieved evidence ID. A NOAA SST reference could therefore appear to support an unrelated event classification.
- The final model prompt requested a general research report, and the UI displayed the same report, chart, and generic limitations for every question.
- Data retrieval used approximately 1-degree sampling for regional means. The old workflow did not report that scale reduction as part of every scientific result, and it could not resolve local event extent.
- The pipeline was mostly sequential prompt calls, with no separate structured intent stage and no deterministic method registry.

## Changes

- Added multilabel scientific intent fields and a structured Groq classifier before dataset selection. The classifier output is schema constrained by enum validation; only code-whitelisted intent labels and methods affect routing.
- Added a method registry declaring required variables, baseline and sample requirements, outputs, assumptions, and limitations.
- Added a deterministic Hobday-style daily MHW implementation. It builds a seasonal climatology from daily OISST (1991–2020), uses an 11-day centered percentile window and 31-day smoothing, detects threshold runs with the five-day event minimum, and calculates duration and intensity metrics.
- Added a NOAA ERDDAP reader for historical and near-real-time daily regional OISST. The baseline and target are sampled consistently at approximately 2 degrees and cached by date/region. Current data use the NRT product when dates are within its coverage; baseline uses final OISST.
- Added hard MHW claim filtering and a deterministic final conclusion. SST-only evidence cannot support an MHW claim. Missing/invalid baseline or incomplete daily coverage yields `insufficient_data`.
- Added an MHW result view and threshold-overlay visualization when data are available and the user has not disabled visualizations.
- Made limitations relevant to the selected analysis rather than always appending the same general caveats.

## Scope and remaining limits

- MHW classification is for an area-weighted regional mean on an approximately 2-degree sample. It does not calculate per-grid-cell event maps or spatial coverage; local hotspots can be diluted in a regional mean.
- The 20-question benchmark exercises intent classification, while MHW numerical tests use deterministic synthetic inputs with known event outcomes. Provider-dependent live calls are not part of automated tests.
- The wider application still has incomplete providers and does not yet have validated end-to-end methods for every catalogued dataset or scientific intent. A registered dataset is not considered retrieved evidence unless its connector succeeds.
- NOAA final and NRT product coverage and ERDDAP availability can change. Retrieval errors are surfaced as an unclassifiable result, never converted into a positive finding.
