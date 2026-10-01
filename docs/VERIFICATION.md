# WEAVIA Verification

**Smart India Hackathon 2026 · SIH26081 · Ministry of Earth Sciences (MoES)**

> ⚠️ **Every number here comes from a synthetic multi-model world** with designed, context-dependent model errors. These results show that the pipeline works. They are **not** evidence of skill against real weather models. No real-world accuracy claim is made.

## 1. Principles

1. Evaluate only on a **held-out test slice** the models never saw.
2. Compare against **simple baselines**, including a strong one.
3. Report **confidence intervals**. Claim improvement only when the interval excludes zero.
4. Verify **uncertainty** by realised coverage, not by assertion.
5. State **limitations** next to results.

## 2. Data split

Issue dates are split chronologically, never randomly.

| Slice | Share | Used for |
|---|---|---|
| Train | 60% | Skill memory, inverse-error baseline, meta-model fitting, regime classifier |
| Validation | 15% | Trust temperature, uncertainty calibration, event model tuning |
| Test | 25% | **Verification only** |

Leads evaluated: 6, 12, 24, 48, 72 hours. Variables: rain, temperature, wind.

## 3. Methods compared

Every method is scored on the same test cases.

| Method | Description |
|---|---|
| Individual models | `model_a` to `model_d` |
| Equal ensemble | Mean of all models |
| Inverse-error | Weight ∝ 1 / MAE per location, variable, lead. Fit on train only |
| Best single (train-selected) | The model with lowest train MAE. A fair, deployable baseline |
| Best single (test-selected) | The best model chosen using test data. An **oracle** no real system could use. Included as a conservative bar |
| **WEAVIA** | Context-aware adaptive blend |

## 4. Statistical method

- **Metric:** MAE reduction relative to a baseline, as a percentage.
- **Interval:** paired, **date-block bootstrap**, 2,000 resamples. Whole issue dates are resampled together, which respects correlation across locations and leads on the same day.
- **Reported range:** 95% percentile interval.
- **Rule:** a result is marked significant only if the lower bound is above zero. Otherwise the UI shows **"CI includes 0: no claim"**.
- **Events:** if too few events exist, the UI shows **"too few events"** instead of a skill number.

## 5. Latest results (synthetic, 3-year run, test slice)

| Variable | MAE change vs equal ensemble | 95% CI | Significant |
|---|---|---|---|
| Rain | −42.3% | 38.6 to 46.2 | Yes |
| Temperature | −34.4% | 33.3 to 35.5 | Yes |
| Wind | −14.6% | 13.9 to 15.3 | Yes |

| Regime classifier | Value |
|---|---|
| Test accuracy | 0.914 |
| Majority-class baseline | 0.851 |

**Reading this correctly:** the synthetic world was built so that models have different strengths in different contexts. A system that learns context should win there. That confirms the machinery can find and use that structure. It says nothing yet about whether real models have exploitable, stable structure.

## 6. Uncertainty verification

Nominal P10–P90 coverage is 80%. Realised coverage on the test slice:

| Variable | Realised coverage |
|---|---|
| Rain | 71–79% across leads, below nominal |

Known failures, stated openly:

- **Rain intervals are too narrow.** In one autopsy case the observation was 98 mm against a band of about 26.5 to 26.6 mm. Rain is heavy-tailed, and spread-based scaling underestimates it.
- **Confidence is overconfident and poorly spread.** Rain mean confidence is 0.99 against 0.95 realised.

Planned fix: quantile or conformal calibration on `log1p(rain)`, then re-check coverage per lead.

## 7. Leakage controls

| Control | How |
|---|---|
| Chronological split | No random shuffling across time |
| Skill memory | Built from the train period only |
| Inverse-error baseline | Fit on train only |
| Error memory | 1-day lag so a case never sees its own outcome |
| Regime probabilities on train | Out-of-fold |
| Calibration | Validation slice, never test |

Automated tests for these controls are **not written yet**. They are on the roadmap: error-memory no-leakage, harmonize round trip, bootstrap.

## 8. What would count as real evidence

1. A provider for real forecast and observation history behind the existing interface.
2. The same protocol, same baselines, same bootstrap, on real data.
3. Confidence intervals that exclude zero on real data, reported by context.
4. Interval coverage near nominal after calibration.

Until then, treat all skill numbers as validation of the pipeline only.

## 9. Reproduce

```bash
cd backend
pip install -r requirements.txt fastapi uvicorn httpx pyarrow
python -u -W ignore -c "from weavia.pipeline import run; run('data', days=1095)"
```

Run it in the foreground (about 135 s). Results are written to `data/verification.json` and served at `GET /api/v1/verification`.
