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
| Train | 60% | Skill memory, inverse-error baseline, meta-model fitting, regime classifier, calibration (with validation) |
| Validation | 15% | Trust-temperature selection. Also pooled with train for uncertainty calibration and event-model cross-fitting |
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

| Variable | MAE change vs equal ensemble | 95% CI | vs inverse-error | vs best single (train-selected) |
|---|---|---|---|---|
| Rain | −38.0% | 33.3 to 42.5 | −32.0% (27.0 to 36.6) | −38.7% (35.3 to 42.3) |
| Temperature | −34.3% | 33.2 to 35.3 | −24.2% (23.4 to 25.1) | −35.5% (34.6 to 36.3) |
| Wind | −15.0% | 14.3 to 15.7 | −10.2% (9.5 to 10.8) | −28.5% (27.7 to 29.3) |

All intervals exclude zero. Regime classifier test accuracy: **0.920** against 0.844 for always predicting the majority regime.

**Reading this correctly:** the synthetic world was built so that models have different strengths in different contexts. A system that learns context should win there. That confirms the machinery can find and use that structure. It says nothing yet about whether real models have exploitable, stable structure.

**Why the rain figure moved from −42.3% to −38.0%:** the synthetic world was regenerated with more heat spells, which changes the random stream. The two intervals overlap, so this is not a method regression or gain. Do not compare single runs as if they were an experiment.

### Extreme events (test slice)

| Event | Observed events | WEAVIA F1 (precision / recall) | Equal-ensemble F1 | Brier skill score |
|---|---|---|---|---|
| Rain ≥ 20 mm | 326 | 0.67 (0.69 / 0.65) | 0.59 | 0.57 |
| Temperature ≥ 38 °C | 52 | 0.81 (0.72 / 0.92) | 0.67 | 0.67 |
| Wind ≥ 30 km/h | 285 | 0.88 (0.90 / 0.86) | 0.79 | 0.81 |

**No confidence intervals on event metrics yet**, so no claim of significance is made. Heat has 52 events, but they cluster in a few spells at 9 stations, so the number of independent episodes is much smaller. Treat the heat result as indicative.

## 6. Uncertainty verification

Nominal P10–P90 coverage is 80%.

| Lead (h) | Rain, all cases | Rain, **non-dry** forecasts | Non-dry mean width (mm) | Temperature | Wind |
|---|---|---|---|---|---|
| 6 | 87.3% | 75.9% | 3.8 | 76.2% | 76.6% |
| 12 | 85.9% | 75.7% | 4.3 | 75.8% | 77.7% |
| 24 | 86.2% | 75.8% | 4.9 | 77.3% | 79.0% |
| 48 | 85.4% | 74.0% | 5.7 | 79.0% | 78.4% |
| 72 | 86.0% | 74.1% | 6.1 | 80.0% | 78.8% |

**Use the non-dry column for rain.** Dry forecasts get a near-zero-width interval that trivially contains an observed 0, which inflates the "all cases" figure.

### What was fixed

The earlier rain interval had a width of about 0.01 mm, because one normalised-residual quantile was shared by dry and wet cases. Rain residuals are now taken on the `log1p` scale and calibrated per forecast-amount bin and lead. Dry forecasts get a point interval and wet forecasts get a wide, skewed one. Calibration now uses train plus validation, because the validation block alone contains no monsoon (a calibration slice must contain every season).

### What is still wrong

- **Wet-case coverage is 74–76%, not 80%.** The test period is wetter than the calibration period, so calibrated spreads are slightly too narrow. Rolling-window recalibration (60, 120 and 240 days) was tried and did not close the gap. Adding regime, location or spread cells did not help either.
- **Rain confidence is overconfident in the middle.** Forecasts with confidence 0.4–0.6 are right 42.8% of the time (mean confidence 0.538). Confidence 0.6–0.8 is right 60.6% (mean 0.697). High confidence (0.8–1.0) is well calibrated: 0.990 against 0.986 realised.
- Temperature and wind confidence run slightly **under**, not over (for example wind 0.6–0.8: mean 0.743, realised 0.827).

## 7. Leakage controls

| Control | How | Automated test |
|---|---|---|
| Chronological split | No random shuffling across time | Pipeline design |
| Skill memory | Train period only | Pipeline design |
| Inverse-error baseline | Fit on train only | Pipeline design |
| Error memory | A lead-L forecast is verified at issue + L, so a case only uses cases already verified (lag of at least one issue) | **Yes.** Changing one outcome must not change memory of any case that could not yet see it. Checked at all five leads. Confirmed to fail when a leak is injected |
| Regime probabilities on train | Out-of-fold | Pipeline design |
| Uncertainty calibration | Train + validation only, never test | Pipeline design |
| Event model | Time-blocked cross-fitting on train + validation, never test | Test checks blocks and outputs |

Other automated checks: unit conversion round trips, validation of bad frames, bootstrap detects a real 20% improvement and does not invent one from noise, rain intervals are non-degenerate and cover about 80% on held-out synthetic data, and the rate limiter. 40 tests in total.

## 7b. Real-data mode

`python -m weavia.live fit` runs the same protocol on real forecasts. Two differences, both stated in every real-mode artifact:

1. **Truth is the Open-Meteo archive**, which is reanalysis-based and not independent of the models. Real-mode results are "vs reanalysis".
2. **Leads are 24, 48 and 72 h**, because Previous Runs provides day offsets.

No real-mode result has been produced yet. Live (unmatured) cases are excluded from verification, training and calibration.

## 8. What would count as real evidence

1. A provider for real forecast and observation history behind the existing interface. Plan and data limits: [REAL_DATA_PLAN.md](REAL_DATA_PLAN.md).
2. The same protocol, same baselines, same bootstrap, on real data, scored against an **independent** observation source (not reanalysis built from the models).
3. Confidence intervals that exclude zero on real data, reported by context.
4. Interval coverage near nominal after calibration.

Until then, treat all skill numbers as validation of the pipeline only.

## 9. Reproduce

```bash
cd backend
pip install -r requirements.txt
python -u -W ignore -c "from weavia.pipeline import run; run('data', days=1095)"
```

Run it in the foreground (about 135 s). Results are written to `data/verification.json` and served at `GET /api/v1/verification`.
