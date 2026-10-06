# WEAVIA Real-Data and Live-Operations Plan

**Smart India Hackathon 2026 · SIH26081 · Ministry of Earth Sciences (MoES)**

Status: **built and tested offline, not yet run against the real service.** Phases 1 to 3 below exist in code (`providers/openmeteo.py`, `live.py`, `infer.py`) and pass tests on a fake of the documented Open-Meteo API backed by the synthetic world. The development sandbox has no outbound internet, so the first real run is yours: `python -m weavia.live check`. Items marked *verify* depend on provider terms and coverage that must be confirmed.

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

| Phase | Deliverable | Status |
|---|---|---|
| 0 | Check per-model history, model ids, endpoint parameters, provider terms, truth access | **Yours to run.** `python -m weavia.live check` probes every model on both endpoints plus the archive and prints OK or the exact failure |
| 1 | Provider (Previous Runs, leads 24/48/72) and archive truth provider | Built. 11 provider tests, including retries, 429, 400, partial windows, wrong location counts |
| 2 | Real back-test through the existing verification protocol | Code path built (`weavia.live fit`). **Not run on real data.** Results will be "vs reanalysis" |
| 3 | Live 6-hourly cycle, scheduler loop, freshness, missing-model handling | Built. 10 end-to-end tests: scoring equals the pipeline exactly, no hindsight, idempotent, missing model, total outage, API reload, stale flag |
| 4 | Single Runs for 6 h and 12 h, IMD/NCMRWF source, independent truth | Not started |

### What the offline tests prove

- A live case is scored by the same fitted models as a stored case: scoring stored validation and test cases through the live code reproduces `blend.parquet` to 1e-6.
- History used for training ends at the issue. A live case carries no outcome.
- A model that fails is dropped with weights renormalised and a visible flag. A total outage keeps the last good artifacts and reports `failed`, and nothing is half-written.
- The API picks up a new cycle without a restart and flags data older than 9 hours as stale.

### What they cannot prove

- That the model ids (`ecmwf_ifs025`, `ecmwf_aifs025_single`, `gfs_global`, `icon_global`) and the Previous Runs `start_date`/`end_date` parameters behave as assumed. The fake follows the documentation, not the live service.
- Any real forecast skill.

### Daily IMD-aligned products

`fit` also builds daily products from the same hourly responses: IST-day maximum temperature, IMD-day (08:30 to 08:30 IST) rainfall, per-station normals (1991 to 2020 reanalysis, within 7 days of each date), calibrated bands, and verification with date-block bootstrap CIs. `cycle` adds them for each live issue. A failure here never breaks the main fit or cycle: it is reported as `skipped` in the status. Their weights are the trust weights of the nearest 6-hourly case, so they inherit WEAVIA's context-aware weighting. The first real `fit` must also confirm that the archive accepts daily aggregates, which the offline fake cannot prove.

### Known design limits

- Truth is reanalysis, so verification is not independent. Replace it with station or satellite truth before claiming skill.
- Live rows use error memory from the last fit. `loop` refits daily, so memory can be a day plus the truth lag old. It is never newer than the forecast.
- Live issue time is the fetch cycle, not the model's own run time.
- Three or more models are supported (the trust engine no longer assumes four). More sources only help if they have history to train on.

Until Phase 2 passes on real data, no accuracy claim about real weather is made.
