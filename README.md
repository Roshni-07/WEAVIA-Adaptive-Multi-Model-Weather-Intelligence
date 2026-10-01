<div align="center">

# 🌦️ WEAVIA

### Hybrid AI–NWP multi-model forecast blending for disaster management

*Adaptive. Explainable. Verified against observations.*

![SIH](https://img.shields.io/badge/SIH-2026-E8742C?labelColor=555555&style=flat-square)
![PS](https://img.shields.io/badge/PS-SIH26081-0A7EC2?labelColor=555555&style=flat-square)
![Org](https://img.shields.io/badge/ORG-MoES-1F6F5C?labelColor=555555&style=flat-square)
![Theme](https://img.shields.io/badge/THEME-DISASTER%20MANAGEMENT-C0392B?labelColor=555555&style=flat-square)
![Data](https://img.shields.io/badge/DATA-SYNTHETIC%20(REAL%20WIP)-E0A030?labelColor=555555&style=flat-square)

![Python](https://img.shields.io/badge/PYTHON-3.12-3776AB?labelColor=555555&style=flat-square&logo=python&logoColor=white)
![FastAPI](https://img.shields.io/badge/FASTAPI-API-009688?labelColor=555555&style=flat-square&logo=fastapi&logoColor=white)
![LightGBM](https://img.shields.io/badge/LIGHTGBM-ML-2E8B57?labelColor=555555&style=flat-square)
![Next.js](https://img.shields.io/badge/NEXT.JS-14-000000?labelColor=555555&style=flat-square&logo=nextdotjs&logoColor=white)
![React Three Fiber](https://img.shields.io/badge/R3F-GLOBE-1A1A1A?labelColor=555555&style=flat-square&logo=threedotjs&logoColor=white)
![TypeScript](https://img.shields.io/badge/TYPESCRIPT-STRICT-3178C6?labelColor=555555&style=flat-square&logo=typescript&logoColor=white)

[🎥 Intro Video](#-intro-video) ·
[📄 PRD](docs/WEAVIA_MVP_Master_Blueprint.md) ·
[🧩 Architecture](#3-how-it-works) ·
[🛠️ Tech Stack](#11-technology) ·
[📊 Results](#6-verification-and-results) ·
[🔗 API](#api-surface-apiv1) ·
[🗺️ Roadmap](#9-roadmap-to-sih-2026-demo)

</div>

> **Weather models do not have to agree. The system has to know when to trust each one.**

**Smart India Hackathon 2026 · SIH26081 · Ministry of Earth Sciences (MoES) · Software · Disaster Management**

---

## 🎥 Intro Video

*A short walkthrough of the problem statement and our solution.*

<!-- Replace with your video. YouTube: [![WEAVIA intro](https://img.youtube.com/vi/VIDEO_ID/maxresdefault.jpg)](https://www.youtube.com/watch?v=VIDEO_ID) -->
▶️ *Video coming soon.*

---

## At a glance

| | |
|---|---|
| **Event** | Smart India Hackathon 2026 |
| **Problem Statement** | SIH26081, Hybrid AI–NWP Multi-Model Forecast Blending System |
| **Organization** | Ministry of Earth Sciences (MoES) |
| **Category / Theme** | Software / Disaster Management |
| **Project** | WEAVIA, Adaptive Multi-Model Weather Intelligence |
| **Status** | Working end-to-end prototype on **synthetic data**. Real-data integration in progress. See [Project status](#4-project-status) |

> ⚠️ **Honesty notice.** All verification numbers in this repository come from a **synthetic** multi-model world. They prove the machinery works. They are **not** evidence of skill against real weather models. The UI shows a synthetic-data banner at all times. No accuracy claim is made until it is measured on real data.

---

## 1. The problem

No single forecast model is best everywhere, for every variable, at every lead time.

- A physical **NWP** model can win in one region or situation.
- An **ensemble** gives better uncertainty information.
- An **AI/ML weather model** can win for particular variables, lead times, or regimes.

So "which model is best?" is the wrong question. The useful one is:

> **Which forecast source should we trust most for this location, variable, lead time, season and weather regime, and why?**

WEAVIA is built around that question. It scores each source in context, learns from verified history, assigns adaptive weights, blends, attaches uncertainty and extreme-event signals, and then **verifies itself against observations** so the next forecast is better informed.

A simple average treats every source as equally trustworthy:

```text
Model A → 20 mm
Model B → 40 mm        Equal average = 40 mm
Model C → 60 mm
```

WEAVIA weights by context and measured skill:

```text
Model A → 20 mm × 0.20
Model B → 40 mm × 0.50
Model C → 60 mm × 0.30
                         ─────
Blended forecast       = 42 mm
```

The weights are **not hard-coded**. They are learned from historical error, regime and context.

---

## 2. SIH 2026 alignment (SIH26081)

The problem statement lists five expected outcomes. This is how WEAVIA addresses each one, and where it stands today.

| SIH26081 expected outcome | WEAVIA response | Status |
|---|---|---|
| Dynamically blended forecast | Context-aware adaptive blending of multiple sources (rain, temperature, wind) | 🟢 Implemented (synthetic sources) |
| Model weight maps | Globe/map of dominant-model trust and per-model weights, served from `/map` and `/trust` | 🟢 Implemented |
| Improved forecast skill vs individual models | Baseline-vs-adaptive verification with bootstrap confidence intervals | 🟢 Machinery implemented, 🟡 real-data proof pending |
| Extreme-weather guidance (heavy rain, heat wave, high wind) | Event models with uncertainty and false-alarm/miss reporting | 🟡 Heavy rain and high wind work, heat event model blocked (too few synthetic heat events) |
| Operational workflow / dashboard | One-command pipeline + FastAPI service + Next.js command center | 🟢 Implemented |

Additional SIH requirements, region-aware, season-aware, lead-time-aware, and regime-aware weighting, are handled by the Trust and Regime engines (Section 5).

---

## 3. How it works

```text
        MULTIPLE FORECAST SOURCES
                    │
                    ▼
          FORECAST HARMONIZATION
                    │
                    ▼
             CONTEXT ENGINE
       ┌────────────┼────────────┐
     Region       Season      Lead time
       └────────────┼────────────┘
                    ▼
          WEATHER REGIME DETECTION
                    │
                    ▼
            MODEL TRUST ENGINE  ◄────── SKILL MEMORY
                    │                        ▲
                    ▼                        │
           ADAPTIVE WEIGHTING                │
                    │                        │
                    ▼                        │
             BLENDED FORECAST                │
          ┌─────────┴─────────┐              │
     UNCERTAINTY        EXTREME-EVENT        │
       SIGNALS             SIGNALS           │
          └─────────┬─────────┘              │
                    ▼                        │
              VERIFICATION ──────────────────┘
```

> **Blending is the mechanism. Learning which forecast to trust is the intelligence.**

### Adaptive blending

For sources $F_1 \dots F_n$ with normalized weights:

$$
\sum_{i=1}^{n} w_i = 1, \qquad F_{WEAVIA} = \sum_{i=1}^{n} w_i F_i
$$

Weights depend on context:

$$
w_i = f(\text{region},\ \text{lead time},\ \text{season},\ \text{variable},\ \text{regime},\ \text{historical skill},\ \text{recent error},\ \text{model disagreement})
$$

The exact functional form may evolve. The design requirement does not: weights stay **adaptive, measurable and explainable**.

---

## 4. Project status

Legend: 🟢 Implemented · 🟡 In progress · 🔵 Planned · ⚪ Mock / synthetic

### Backend (Python 3.12, FastAPI)

| Component | Status | Notes |
|---|---|---|
| Config, locations (20 India stations), regime labels | 🟢 | |
| Synthetic multi-model world | ⚪ | Behind the same provider interface real sources will use |
| Provider interface + synthetic providers | 🟢 | |
| Harmonization (time, units, variables, QC) | 🟢 | |
| Feature builder | 🟢 | |
| Regime detection | 🟢 | |
| Trust engine (skill × context, recent error) | 🟢 | |
| Blending (equal, inverse-error, adaptive) | 🟢 | |
| Uncertainty (spread, intervals, confidence) | 🟡 | Rain intervals too narrow, see [Known limitations](#8-known-limitations) |
| Extreme-event models | 🟡 | Rain and wind done, temperature/heat blocked on data |
| Verification (bootstrap CIs vs baselines) | 🟢 | |
| Explain, Autopsy, Lab modules | 🟢 | |
| Parquet store + pipeline | 🟢 | ~135 s for a 3-year synthetic run |
| FastAPI service (14 routes under `/api/v1`) | 🟢 | Pydantic models, 422/404 validation, CORS |
| Test suite | 🟡 | API tests pass (6). Leakage, harmonize round-trip and bootstrap tests still to add |
| Real data provider (Open-Meteo) | 🔵 | Per-model history depth to be checked first |
| PostgreSQL/PostGIS, Redis, Celery, docker-compose | 🔵 | |

### Frontend (Next.js 14, React 18, TypeScript)

| Component | Status | Notes |
|---|---|---|
| Typed API client, URL-synced Zustand store | 🟢 | `?view=&loc=&var=&lead=&issue=` makes every view shareable |
| 3D globe: rain, temperature, wind-speed and risk fields | 🟢 | Interpolated from station values returned by `/map`, clipped to India |
| Model-trust markers, alert rings, weight flow lines | 🟢 | |
| Command center (forecast, trust bar, lead/issue sliders, alerts) | 🟢 | |
| Why, Regime, Models (skill atlas), Autopsy, Lab views | 🟢 | Lab runs a live back-test |
| Accessibility pass (skip link, landmarks, focus, reduced motion) | 🟢 | |
| Wind particles on globe | 🔵 | Needs wind direction in the pipeline. Not faked |
| MapLibre, D3, Framer Motion | 🔵 | |

---

## 5. Intelligence modules

### WEAVIA TRUST: dynamic model trust

Trust is contextual, never global. A model can be best for `Region A + Rainfall + 24 h + Monsoon` and poor for `Region B + Temperature + 72 h + Heat`.

```text
Model × Region × Variable × Lead time × Season × Regime
```

Historical skill and recent error feed the trust score. Every weight carries a stored reason.

### WEAVIA REGIME: weather regime detection

Classifies current conditions into operational regimes (`NORMAL`, `CONVECTIVE`, `HEAVY RAIN`, `HEAT`, `HIGH WIND`, `CYCLONIC`, `DRY`, `TRANSITION`) from temperature, humidity, pressure, wind, precipitation, tendencies and model spread. The regime set is an implementation framework, not a fixed standard.

### WEAVIA MEMORY: historical skill

```text
Forecast → Observation → Error → Skill update → Trust update → Future weights
```

Continuous variables: **MAE, RMSE, bias**. Events: **precision, recall, F1, false alarms, missed events**. Probabilistic: **interval coverage**, CRPS planned.

### WEAVIA EXPLAIN: why this forecast?

```text
FINAL FORECAST  42 mm
Model A  20 mm  20%      • Model B has stronger recent rainfall skill
Model B  40 mm  50%      • Current regime resembles conditions where B performs well
Model C  60 mm  30%      • Model C has higher recent error
```

Explanations are generated from real weights and errors. When no model stands out, or errors are near zero, the system says so instead of inventing reasons.

### WEAVIA AUTOPSY: forecast failure analysis

After an event, compare every model and the blend against observation. Which model was closest, who over- or under-predicted, did the regime matter, did the weighting over-trust a model, was the event outside learned experience.

### WEAVIA LAB: counterfactual blending

"What if Model B were trusted 10% more?" "What if a model were removed?" Runs a **live back-test** over alternative weights, so the answer is measured, not guessed.

---

## 6. Verification and results

### Protocol

The adaptive blend is compared on the **same held-out test slice** against:

```text
Individual models  vs  Equal-weight blend  vs  Inverse-error blend  vs  Adaptive WEAVIA blend
```

Improvements are reported with **bootstrap confidence intervals**. If a CI includes 0, the UI shows **"CI includes 0: no claim"**. If events are too few, it shows **"too few events"**.

### Latest run (synthetic data, 3-year run, test slice)

| Metric | Result |
|---|---|
| Regime classification accuracy | **0.914** vs 0.851 majority-class baseline |
| Rain MAE vs equal ensemble | **−42.3%** (CI −38.6 to −46.2) |
| Temperature MAE vs equal ensemble | **−34.4%** (CI −33.3 to −35.5) |
| Wind MAE vs equal ensemble | **−14.6%** (CI −13.9 to −15.3) |

All CIs exclude 0. **These are synthetic-world results. They validate the pipeline, not real-world skill.** Real-data verification is the next milestone.

---

## 7. Quickstart

### Backend

```bash
cd backend
pip install -r requirements.txt fastapi uvicorn httpx pyarrow

# Build the data store (about 135 s). Run in the foreground.
python -u -W ignore -c "from weavia.pipeline import run; run('data', days=1095)"

# Serve the API
uvicorn weavia.api.main:app --port 8000

# Tests (API tests need data/ and skip otherwise)
pytest
```

### Frontend

```bash
cd weavia-frontend
npm install
npm run dev        # http://localhost:3000
```

The frontend proxies `/api/v1/*` to `WEAVIA_API` (default `http://127.0.0.1:8000`). The UI consumes the API only. No values are hard-coded.

### API surface (`/api/v1`)

| Route | Purpose |
|---|---|
| `GET /health` | Service health |
| `GET /meta` | Models, variables, locations, issue dates |
| `GET /map` | Per-station field values, trust, alerts for the globe |
| `GET /overview` | Command-center summary |
| `GET /forecast` | Blended and per-model forecast, uncertainty, context |
| `GET /timeline` | Forecast across lead times |
| `GET /trust` | Current weights and skill |
| `GET /regime` | Detected regime, confidence, features |
| `GET /explain` | Weight drivers and model contributions |
| `GET /skill-atlas` | Model skill by region, variable, lead time, season |
| `GET /verification` | Baseline-vs-adaptive results with CIs |
| `GET /events` | Extreme-event signals and event verification |
| `GET /autopsy/{id}` | Forecast-vs-observation failure analysis |
| `POST /lab/simulate` | Counterfactual weight back-test |

---

## 8. Known limitations

Stated openly, because this project's value depends on being truthful.

1. **Rain intervals are too narrow.** The P10–P90 band is near zero width on some cases (one autopsy example: observed 98 mm against a band of about 26.5 mm). Coverage is 71–79% against an 80% nominal target. Fix planned: quantile/conformal calibration on `log1p`, heavy-tailed.
2. **Confidence is overconfident and poorly spread** (rain mean 0.99 vs 0.95 realised).
3. **No temperature extreme-event model yet.** The synthetic world has too few heat episodes to fit one. The UI shows n/a.
4. **No wind direction** in the pipeline, so the globe shows wind **speed only**. Wind particles would be fabricated, so they are not drawn.
5. **Dry default view.** The latest issue date is dry, so globe layers look empty. A "jump to most active day" control is planned.
6. **Noisy per-model reasons** when errors are about zero. To be suppressed.
7. **Globe is mouse-driven.** A keyboard location select is the accessible alternative.
8. **No real data yet.** `providers/openmeteo.py` is not written.
9. `db/`, `docs/`, `scripts/` are placeholders.

---

## 9. Roadmap to SIH 2026 demo

| # | Milestone | Why |
|---|---|---|
| 1 | **Uncertainty calibration**: conformal rain intervals, confidence spread, per-lead coverage, add heat episodes, add leakage/harmonize/bootstrap tests | Biggest science gap. Trust claims depend on it |
| 2 | **Real data**: Open-Meteo provider behind the existing `ForecastProvider` interface, check per-model history depth first | Turns synthetic validation into real evidence |
| 3 | **Wind u/v** in the pipeline, direction in `/map`, real wind particles, "most active day" jump | Visual completeness without faking |
| 4 | **Infra**: `db/schema.sql`, docker-compose (PostgreSQL/PostGIS, Redis) | Operational deployment story |

---

## 10. Engineering principles

1. **Do not fake intelligence.** A random weight generator is not an adaptive engine. Prototypes are labelled as prototypes.
2. **Do not fake accuracy.** No "WEAVIA improves accuracy by X%" unless measured under the documented protocol with CIs that exclude 0.
3. **Do not hide uncertainty.** Model disagreement is information.
4. **Do not make an LLM the weather model.** Any conversational layer explains structured outputs. It never invents meteorological values.
5. **Baselines first.** A sophisticated model only means something against simpler alternatives.
6. **Keep providers modular.** Swapping a source must not touch the blending engine.
7. **Keep verification independent.** Evaluation never uses WEAVIA's own forecast as ground truth.
8. **Make every number traceable:** `Source → Processing → Weight → Blend → Verification`.
9. **UI consumes the API only.** No hard-coded fake values in the interface.

---

## 11. Technology

**Backend:** Python 3.12, NumPy, Pandas, LightGBM, scikit-learn, xarray, FastAPI, pydantic, joblib, pytest, pyarrow, uvicorn, httpx

**Frontend:** Next.js 14.2, React 18, TypeScript, React Three Fiber + three 0.160 + drei, Zustand, topojson-client + world-atlas, IBM Plex Sans / Mono

**Planned:** MapLibre GL, D3, Framer Motion, PostgreSQL + PostGIS, Redis, Celery, docker-compose

**Design language:** dark atmospheric command center. IBM Plex Mono numerics. Semantic colour: temperature amber, rain cyan, wind pale green, risk red/orange. No decorative 3D or spin.

---

## 12. Repository layout

```text
WEAVIA/
├── README.md
├── backend/
│   ├── weavia/
│   │   ├── api/main.py        # FastAPI, 14 routes
│   │   ├── synthetic/         # synthetic multi-model world
│   │   ├── providers/         # ForecastProvider interface + sources
│   │   ├── harmonize.py  features.py  regime.py  regime_labels.py
│   │   ├── trust.py  uncertainty.py  events.py  verify.py
│   │   ├── explain.py  autopsy.py  lab.py
│   │   ├── pipeline.py  store.py  config.py  locations.py
│   └── tests/                 # test_api.py
├── weavia-frontend/
│   ├── app/
│   ├── components/            # Globe, Command, Why, Regime, Models, Autopsy, Lab, ui
│   └── lib/                   # api, store, useApi, format
├── db/                        # planned
├── docs/                      # planned
└── scripts/                   # planned
```

---

## 13. Forecast provider contract

Sources are modular. Synthetic and real providers sit behind the same interface, so moving to real data does not change the blending engine.

```text
                 ForecastProvider
       ┌───────────────┼───────────────┐
    NWP model     Ensemble        AI/ML model
       └───────────────┼───────────────┘
                       ▼
        Harmonize → Common forecast schema → WEAVIA core
```

Harmonization normalizes grid, coordinates, time, units, variable names, horizons and missing values **before** anything reaches trust or blending.

---

## 14. Metrics

$$MAE = \frac{1}{N}\sum |y_i-\hat{y}_i|, \qquad RMSE = \sqrt{\frac{1}{N}\sum (y_i-\hat{y}_i)^2}, \qquad Bias = \frac{1}{N}\sum (\hat{y}_i-y_i)$$

Events: precision, recall, F1, false-alarm rate, missed-event rate.
Uncertainty: P10–P90 interval coverage against nominal 80%.

Results are reported **by context** (region, variable, lead time, season, regime, event type), not only as one overall score.

---

## 📜 SIH reference

**Smart India Hackathon 2026**
**Problem Statement ID:** SIH26081
**Problem Statement:** Hybrid AI–NWP Multi-Model Forecast Blending System
**Organization:** Ministry of Earth Sciences (MoES)
**Category:** Software
**Theme:** Disaster Management

**WEAVIA, Adaptive Multi-Model Weather Intelligence**
*Weaving forecasts. Predicting smarter.*
