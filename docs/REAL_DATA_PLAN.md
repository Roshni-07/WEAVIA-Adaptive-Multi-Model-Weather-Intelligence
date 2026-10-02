# WEAVIA Real-Data and Live-Operations Plan

**Smart India Hackathon 2026 · SIH26081 · Ministry of Earth Sciences (MoES)**

Status: **plan, not built.** Today the pipeline runs on a synthetic world. This document says how it moves to real, multi-model data and how it runs on a schedule. Items marked *verify* depend on provider terms and coverage that must be checked before building.

## 1. Two jobs, two data paths

| Job | Needs | Path |
|---|---|---|
| **Back-test** (learn skill, prove it) | Past forecasts **as issued**, per model, at known lead times, plus ground truth | Archive APIs |
| **Live run** (serve today's forecast) | The latest run of every model, every cycle | Live forecast API |

Mixing them silently is the main way to fool yourself. The live path never feeds verification until the matching observation arrives.

## 2. Candidate source: Open-Meteo (checked October 2026)

Free, no API key, 30+ models, CC BY 4.0 data licence. *Verify:* current terms for non-commercial use and fair-use limits before any public deployment.

| Product | What it gives | Fit for WEAVIA |
|---|---|---|
| Forecast API | Latest runs, per model (`models=`) | **Live path** |
| Previous Runs API | Each model at a **fixed day offset** (1 to 7 days ahead), most models since January 2024 | **Back-test for leads 24, 48, 72 h.** About 2.7 years, all seasons. Cannot give 6 h or 12 h leads |
| Single Runs API | A complete individual run by initialisation time (`run=`). Most models since 2 April 2026, ECMWF IFS HRES since March 2024 | **Back-test for 6 h and 12 h leads, and cross-checks.** Only about six months for most models |
| Historical Forecast API | Stitched series of each run's first hours, since about 2021 | **Do not use for skill by lead.** It is effectively very short-lead output, so it hides the lead-time error WEAVIA must learn. Using it would be look-ahead |

Consequences:

1. Real-data MVP should evaluate **24, 48, 72 h first** (long history). Add 6 h and 12 h once Single Runs has enough history, or drop them from the real-data configuration.
2. Skill claims must state the real history length per lead.
3. The Single Runs window includes the 2026 monsoon but not a full winter. Seasonal skill cells will be thin. Report that.

## 3. Ground truth is the harder problem

Open-Meteo's own historical weather product is reanalysis-based, so it is partly model-derived. Scoring models against it is not independent of the models (verification principle: never score against something built from the thing being scored).

| Variable | Candidate truth | Notes (*verify* coverage and licence for the 20 stations) |
|---|---|---|
| Rain | IMD gridded or gauge data, or a satellite product such as GPM IMERG | IMD access may need a request. Satellite rain is an estimate, not a gauge |
| Temperature, wind | Station observations: IMD, or open surface-observation archives such as NOAA ISD / GHCN-style airport and synoptic stations | Station-to-grid representativeness error applies and must be stated |

Rule: the report names the truth source on every result. If only reanalysis is available, results are labelled "vs reanalysis" and not presented as skill against observations.

## 4. MoES angle

The problem statement is a Ministry of Earth Sciences one. India's own operational models (for example NCMRWF and IMD systems) are the natural real sources. Their data access terms are not known to this project. Treat them as a **requested** source, not an assumed one. The `ForecastProvider` interface means adding them later changes no blending code.

## 5. Live operation design

Cycle = one model issue time. Global models update about every six hours, so run a cycle every six hours, offset after the data lands.

```text
every cycle (scheduler: cron, then Celery):
  1. fetch latest run per model          (retry, timeout, per-model failure isolated)
  2. normalize + validate                (existing harmonize.py, same contract as synthetic)
  3. attach context                      (location, season, regime features)
  4. read stored skill memory            (verified past only)
  5. trust weights -> blend -> uncertainty -> event probability
  6. write a forecast_run row            (issue time, models used, versions, provenance)
  7. serve via API
later, when observations arrive:
  8. verify the matured forecasts -> update skill memory (lagged, never the current case)
```

Rules:

| Rule | Why |
|---|---|
| Store the **issue time** of every run and never overwrite | No hindsight. Enables honest re-verification |
| A missing or late model is **dropped and weights renormalised**, with a visible flag | Operations must degrade gracefully. Never fabricate a value |
| Stale data is labelled with its age in the UI | A six-hour-old forecast must not look live |
| Idempotent cycles keyed by (model, issue time) | Safe retries and backfills |
| `data_mode` flips from `synthetic` to `live` in provenance, and the banner follows | Synthetic and real data are never mixed in one artifact |
| Cache and respect provider limits | Free tiers are shared infrastructure |
| Skill memory updates only from matured, verified cases | Same leakage rule the tests enforce today |

## 6. Phases and acceptance

| Phase | Deliverable | Done when |
|---|---|---|
| 0 | Check per-model history, model list for India, provider terms, truth-source access | A written table of what exists for the 20 stations |
| 1 | `providers/openmeteo.py` (Previous Runs, leads 24/48/72) and one truth provider | Provider passes `validate`, pipeline runs end to end on real data |
| 2 | Real back-test with the existing verification protocol | CIs reported by lead and season, truth source named, no synthetic mixing |
| 3 | Live cycle (Forecast API), scheduler, freshness and missing-model handling | Unattended runs for a week, flags correct on injected failures |
| 4 | Single Runs for 6 h and 12 h, optional IMD/NCMRWF source | Added through the same interface |

Until Phase 2 passes, no accuracy claim about real weather is made.
