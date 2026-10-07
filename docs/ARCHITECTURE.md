# WEAVIA Architecture

**Smart India Hackathon 2026 · SIH26081 · Ministry of Earth Sciences (MoES)**

> Data in this repository is **synthetic**. This document describes the machinery, which is built to accept real sources through the same interfaces.

## 1. Design rules

1. **Vertical build order:** data → harmonize → regime → trust → blend → uncertainty → verify → API → UI.
2. **The API reads stored artifacts only.** No science is recomputed at request time.
3. **The UI consumes the API only.** No hard-coded values.
4. **Providers are swappable.** Blending never sees a provider.
5. **Every number is traceable:** source → harmonized → weight → blend → verification.
6. **No claim without a measurement.** See [VERIFICATION.md](VERIFICATION.md).

## 2. System overview

```text
 Forecast providers (NWP / ensemble / AI)        Observation provider
            │ fetch → normalize → validate               │
            └────────────────────┬───────────────────────┘
                                 ▼
                    HARMONIZE  (canonical schema, units, UTC)
                                 ▼
                    CASES + ERROR MEMORY  (features.py)
                                 ▼
                    REGIME DETECTION  (regime.py)
                                 ▼
                    TRUST ENGINE  (trust.py)  ◄── verified skill + recent error
                                 ▼
                    ADAPTIVE BLEND
                         ┌───────┴────────┐
                 UNCERTAINTY          EVENT MODEL
                (uncertainty.py)      (events.py)
                         └───────┬────────┘
                                 ▼
                    VERIFICATION  (verify.py, test slice only)
                                 ▼
                    ARTIFACTS  (parquet + json + joblib)
                                 ▼
                    STORE  →  FastAPI  →  Next.js UI
```

## 3. Pipeline stages

`pipeline.run()` executes the stages in order and writes artifacts to `data/`.

| # | Stage | Module | What it does |
|---|---|---|---|
| 1 | Data | `providers/`, `synthetic/` | Four synthetic models (`model_a`..`model_d`) with designed context-dependent errors, plus synthetic observations. Each provider is validated, and the pipeline raises if validation fails |
| 2 | Harmonize | `harmonize.py` | Canonical schema: UTC time, canonical units, shared variable names, QC |
| 3 | Cases | `features.py` | One row per issue × location × lead. Chronological split. Builds historical and recent error memory |
| 4 | Regime | `regime.py`, `regime_labels.py` | Classifier over 8 regimes. Out-of-fold probabilities on train, full model on validation and test |
| 5 | Skill memory | `pipeline.build_skill_table` | MAE, RMSE, bias per location × lead × season × regime × model × variable, **train period only** |
| 6 | Trust and blend | `trust.py` | Meta-model predicts each model's expected error from context. Weights are a softmax of negative predicted error |
| 7 | Uncertainty | `uncertainty.py` | P10/P50/P90 and confidence. Rain on the log1p scale by forecast level, others from weighted spread. Calibrated on train + validation |
| 8 | Events | `events.py` | Event probability per variable, time-blocked cross-fit, alert thresholds |
| 9 | Verification | `verify.py` | Test slice only. Baselines, bootstrap CIs, coverage, regime metrics |
| 10 | Artifacts | `pipeline.py` | Parquet tables, `meta.json`, `verification.json`, `models.joblib` |

## 4. Core definitions

### Canonical configuration (`config.py`)

| Item | Value |
|---|---|
| Leads (hours) | 6, 12, 24, 48, 72 |
| Time step | 6 h |
| Blended variables | rain (mm/6h), temp (°C), wind (km/h) |
| Context variables | relative humidity, pressure (regime and features only) |
| Regimes | NORMAL, CONVECTIVE, HEAVY_RAIN, HEAT, HIGH_WIND, CYCLONIC, DRY, TRANSITION |
| Seasons | WINTER, PRE_MONSOON, MONSOON, POST_MONSOON |
| Event thresholds | rain ≥ 20 mm, temp ≥ 38 °C, wind ≥ 30 km/h (MVP proxies, configurable) |
| Split (chronological) | 60% train / 15% validation / 25% test. Calibration uses train + validation |
| Error memory | 1-day lag, 7-day recent window |

### Adaptive blending

For models $i = 1..n$ with weights $w_i$:

$$F_{WEAVIA} = \sum_i w_i F_i, \qquad w_i = \operatorname{softmax}\left(-\frac{\hat{e}_i}{\tau}\right)$$

$\hat{e}_i$ is the meta-model's predicted log absolute error for model $i$ in the current context. $\tau$ is selected on the validation slice.

**Meta-model inputs include:** location and region, season (month), lead, predicted regime and its probabilities, model spread, each model's deviation from the others, verified historical skill, verified recent error.

**Baselines kept for comparison:** equal weight, and inverse-error weight fit on train only.

### Uncertainty

**Temperature and wind.** Normalised residual on the calibration slice:

$$z = \frac{y - \hat{y}}{\sigma_w + c}$$

with $\sigma_w$ the weight-aware model spread and $c$ a per-variable floor. Empirical quantiles of $z$ per variable and lead give P10/P50/P90. Confidence is the probability that absolute error stays within a variable-specific tolerance.

**Rain** is zero-inflated and heavy-tailed, so it is calibrated on the log scale:

$$r = \log(1+y) - \log(1+\hat{y})$$

Residual distributions are stored per **lead × forecast-amount bin** (dry, trace, light, moderate, heavy; edges 0.05, 0.5, 2, 8 mm/6h), with fallback to pooled cells when a cell has fewer than 100 cases. Intervals, confidence and exceedance probability all come from the same conditional distribution, back-transformed with `expm1`. A dry forecast therefore gets a near-point interval and a heavy forecast a wide, right-skewed one.

**Calibration slice:** train + validation. A chronological validation block can miss a whole season (the synthetic one has no monsoon), so calibrating on it alone starves the tails. Coverage is always verified on the untouched test slice, reported both overall and for non-dry rain forecasts.

### Event models

LightGBM classifier per variable, isotonic calibration, F1-optimal alert threshold. Isotonic calibration and the threshold are fit on **time-blocked out-of-fold predictions** over train + validation: issue dates are cut into five contiguous blocks and each block is predicted by a model fit on the other four. The final classifier is fit on all pooled rows. A variable with fewer than 30 calibration events is not fitted, and the UI says "too few events" instead.

## 4b. Live path

```text
python -m weavia.live fit     Previous Runs (24/48/72 h) + archive truth -> run_from_sources -> artifacts + cases_full
python -m weavia.live cycle   latest run per model -> impute missing -> features -> error memory over history + live
                              -> score_cases (same fitted models) -> publish blend/cases/regime_proba atomically
                              -> live_status.json (state, models, age)
python -m weavia.live loop    cycle every 6 h (45 min after the run lands), refit daily
```

`run_from_sources` is the single entry point after data acquisition, used by both the synthetic run and `fit`. `infer.score_cases` mirrors its inference half, and a test proves it reproduces `blend.parquet`. Live cases have `split="live"`, no outcome, and never enter training, calibration or verification. The API reloads when artifacts change. Real mode sets `config.MODELS` and `config.LEADS` from `meta.json`. See [REAL_DATA_PLAN.md](REAL_DATA_PLAN.md).

## 5. Provider contract

```text
ForecastProvider
  meta: ModelMeta (model_id, name, kind: NWP | AI | ENSEMBLE, resolution, provider, synthetic)
  var_map: native variable → (canonical variable, native unit)
  fetch(spec)      → raw frame (run_time, valid_time, location_id, native_var, value)
  normalize(raw)   → canonical frame (UTC, canonical units, lead_h)
  validate(df)     → ValidationReport
  get_forecasts()  → (frame, report)

ObservationProvider
  fetch(spec)      → timestamp (UTC), location_id, variable, value, source
```

Adding a real source (for example Open-Meteo) means writing one subclass. Harmonization, trust, blending and verification are unchanged.

## 6. Artifacts (`data/`, gitignored)

| File | Contents |
|---|---|
| `cases.parquet` | Case table with features, observations, predicted regime |
| `blend.parquet` | Blend, per-model forecasts and weights, interval, confidence, event probability, per variable |
| `regime_proba.parquet` | Regime probabilities per case |
| `skill.parquet` | Verified skill memory (train only) |
| `events.parquet` | Exceedance and large-miss events for the Autopsy view |
| `truth.parquet` | Synthetic ground truth |
| `models.joblib` | Fitted trust, calibration, regime and event models |
| `meta.json` | Provenance, data-mode notice, splits, tau, thresholds, model version |
| `verification.json` | All verification results |

`data/` is regenerated by the pipeline in about 135 s for a 3-year run. It is not committed. One artifact exceeded GitHub's 100 MB file limit.

## 7. Module map

```text
backend/weavia/
├── live.py              Real-data fit / cycle / loop / check (python -m weavia.live)
├── infer.py             Scores cases with fitted models (live path, equivalent to the pipeline)
├── extremes.py          Daily IMD-aligned products: blend, calibrate, heat-wave indicator, verify
├── imd_criteria.py      IMD heat-wave, 24 h rainfall and wind definitions as tested pure functions
├── api/main.py          FastAPI app, 16 routes, reads Store only
├── api/ratelimit.py     Per-client rate limit and security headers (middleware)
├── live.py              Real-time fit, 6-hourly cycle, loop, CLI (check, fit, cycle, loop)
├── infer.py             Score cases with fitted models (live inference)
├── store.py             Typed access to artifacts
├── pipeline.py          End-to-end run, artifact writer
├── config.py            Constants, units, thresholds
├── locations.py         20 India stations
├── providers/           ForecastProvider, ObservationProvider, synthetic and Open-Meteo implementations
├── synthetic/           World generator and model error specs
├── harmonize.py         Canonical schema and validation
├── features.py          Cases, splits, error memory
├── regime.py            Regime classifier
├── regime_labels.py     Regime labelling rules
├── trust.py             Meta-model, weights, inverse-error baseline
├── uncertainty.py       Interval and confidence calibration
├── events.py            Event probability model
├── verify.py            Held-out evaluation and bootstrap
├── explain.py           Per-forecast explanation from real weights and errors
├── autopsy.py           Forecast failure analysis
└── lab.py               Counterfactual weight simulation and back-test
```

## 8. Frontend

```text
weavia-frontend/
├── app/                 Next.js app router, layout, global styles
├── components/          Globe, Command, Why, Regime, Models, Autopsy, Lab, ui
└── lib/                 api (typed client), store (Zustand, URL-synced), useApi, format
```

- `next.config.mjs` proxies `/api/v1/*` to `WEAVIA_API` (default `http://127.0.0.1:8000`).
- State lives in the URL: `?view=&loc=&var=&lead=&issue=`. Every screen is deep-linkable.
- The globe draws field layers interpolated from the station values returned by `/map`, clipped to India. It draws model-trust markers, alert rings and weight-flow lines. It does not draw wind particles, because wind direction is not in the pipeline yet.

## 9. Not built yet

PostgreSQL/PostGIS, Redis, Celery, docker-compose, MapLibre, D3, Framer Motion, wind direction, independent truth, a production scheduler (the built-in `loop` is a simple one). Real-data and live-cycle design: [REAL_DATA_PLAN.md](REAL_DATA_PLAN.md). Roadmap: [README](../README.md).
