# WEAVIA Product Requirements Document

**Smart India Hackathon 2026 · SIH26081 · Ministry of Earth Sciences (MoES) · Software · Disaster Management**

| | |
|---|---|
| Product | WEAVIA, Adaptive Multi-Model Weather Intelligence |
| Problem statement | SIH26081, Hybrid AI–NWP Multi-Model Forecast Blending System |
| Version | MVP prototype, October 2026 |
| Data status | Synthetic multi-model world. Real-data integration planned |

> All performance figures in this project come from synthetic data. They validate the pipeline, not real-world skill. No accuracy claim is made until it is measured on real data.

---

## 1. Problem

No single forecast model is best everywhere, for every variable, at every lead time. Physical NWP models, ensembles and AI/ML weather models each win in different conditions. A plain average ignores that. Picking one model ignores it too.

Forecasters and disaster managers need one forecast they can trust, with a clear reason for that trust and an honest statement of uncertainty.

**Core question:** which forecast source should be trusted most for this location, variable, lead time, season and weather regime, and why?

## 2. Goals

1. Produce a **dynamically blended forecast** from multiple sources, with context-aware weights.
2. Show **model weight maps**: which source dominates where, and by how much.
3. **Measure** whether the blend beats individual models and baselines, with confidence intervals.
4. Give **extreme-weather guidance** (heavy rain, heat wave, high wind) with uncertainty and false-alarm reporting.
5. Provide an **operational workflow**: one pipeline, one API, one dashboard.
6. Make every weight and number **explainable and traceable**.

## 3. Non-goals

- Replacing NWP or AI weather models. WEAVIA blends them.
- An LLM generating weather values. Any language layer only explains structured outputs.
- Claiming skill that has not been verified.
- Hard-coding or faking data in the interface.

## 4. Intended users

| User | Need |
|---|---|
| Forecaster / analyst | See which model to lean on, and why, for a given place and lead time |
| Disaster-management planner | Early, calibrated signals for heavy rain, heat and wind |
| Model developer / evaluator | Skill by region, variable, lead time, season and regime |

## 5. Scope (MVP)

**Variables:** rainfall, temperature, wind speed.
**Locations:** 20 stations across India.
**Sources:** synthetic multi-model sources behind a `ForecastProvider` interface. Real sources plug into the same interface.

### Functional requirements

| # | Requirement | Status |
|---|---|---|
| F1 | Harmonize sources (time, units, variables, QC) | Done |
| F2 | Detect weather regime from features | Done |
| F3 | Score model trust by context and recent error | Done |
| F4 | Blend with adaptive weights. Compare to equal and inverse-error baselines | Done |
| F5 | Attach uncertainty (spread, intervals, confidence) | Done, with a known gap: wet-case rain coverage 74–76% vs 80% |
| F6 | Extreme-event signals | Done for rain, temperature, wind. Point estimates, no event CIs yet |
| F7 | Verify against observations with bootstrap CIs | Done |
| F8 | Explain each forecast from real weights and errors | Done |
| F9 | Autopsy of forecast failures | Done |
| F10 | Counterfactual Lab (live back-test of alternative weights) | Done |
| F11 | REST API (14 routes under `/api/v1`) | Done |
| F12 | Dashboard: globe, forecast, trust, regime, models, autopsy, lab | Done |
| F13 | Real data provider (Open-Meteo) | Planned. See [REAL_DATA_PLAN.md](REAL_DATA_PLAN.md) |
| F14 | Wind direction and wind particles | Planned |
| F15 | PostgreSQL/PostGIS, Redis, docker-compose | Planned |

### Non-functional requirements

- **Honesty:** synthetic banner always shown. UI shows "CI includes 0: no claim" and "too few events" instead of skill claims.
- **Reproducibility:** one command builds the data store (about 135 s for 3 years). Same inputs, same outputs.
- **No leakage:** error memory uses only information available at issue time.
- **Modularity:** swapping a provider does not touch blending.
- **Accessibility:** skip link, landmarks, focus states, reduced-motion support, keyboard location select.
- **Shareability:** UI state is in the URL (`?view=&loc=&var=&lead=&issue=`).

## 6. Success metrics

Reported on a held-out test slice, by context, with bootstrap CIs.

| Metric | Definition |
|---|---|
| Continuous skill | MAE, RMSE, bias, vs equal-weight and inverse-error baselines |
| Event skill | Precision, recall, F1, false-alarm rate, missed-event rate |
| Uncertainty | P10–P90 coverage vs 80% nominal |
| Regime accuracy | vs majority-class baseline |

A claim of improvement requires the CI to exclude 0.

**Current synthetic results:** regime accuracy 0.920 vs 0.844 majority. MAE vs equal ensemble: rain −38.0%, temperature −34.3%, wind −15.0%, all CIs excluding 0. Synthetic only.

**Exit criterion for a real-skill claim:** the same protocol run on real forecast and observation history, with CIs excluding 0.

## 7. Risks and open issues

| Risk | Impact | Plan |
|---|---|---|
| Wet-case rain coverage 74–76% vs 80% nominal (test period wetter than calibration) | Slightly narrow wet-case intervals | Real-data recalibration, rolling windows already tried without gain |
| Rain confidence overconfident in the middle (0.4–0.8 band) | Misleading mid-range trust signal | Recalibrate confidence separately from the interval |
| Synthetic data may flatter the method | Overstated skill | Real-data verification before any claim |
| Open-Meteo archives give day-offset leads (24/48/72 h) over about 2.7 years, true per-run data only since April 2026 | Limits real back-test leads and length | Start with 24/48/72 h. See [REAL_DATA_PLAN.md](REAL_DATA_PLAN.md) |
| Reanalysis is not independent truth | Circular verification | Independent station or satellite truth, named on every result |
| Event metrics lack confidence intervals | Event skill claims are weak | Add block bootstrap for events |
| No wind direction | No wind particles | Add u/v to pipeline |

## 8. Roadmap

1. ✅ **Uncertainty calibration** and missing tests (done).
2. **Real data:** Open-Meteo provider behind the existing interface.
3. **Wind u/v**, wind particles, "most active day" control.
4. **Infrastructure:** database schema, docker-compose, deployment for a live demo.

## 9. References

- [README](../README.md): overview, quickstart, API, known limitations
- SIH26081 problem statement, Ministry of Earth Sciences (MoES), Smart India Hackathon 2026
