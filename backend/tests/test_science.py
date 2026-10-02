"""Science tests. These need no pipeline artifacts, except the two regression guards at the bottom."""
import json
import os

import numpy as np
import pandas as pd
import pytest

from weavia.config import BLEND_VARS, EVENT_THRESH, LEADS, MODELS, tolerance
from weavia.events import EventModel
from weavia.features import add_error_memory
from weavia.harmonize import BOUNDS, SCHEMA, UNITS, from_canonical, to_canonical, validate_frame
from weavia.uncertainty import UncertaintyCalibrator, rain_bin
from weavia.verify import _bootstrap


# --------------------------------------------------------------------- error memory: no leakage
def _case_frame(n_issues: int, seed: int = 0) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    rows = []
    for lead in LEADS:
        d = pd.DataFrame({"location_id": "blr", "lead_h": lead, "issue_idx": np.arange(n_issues)})
        for var in BLEND_VARS:
            d[f"obs_{var}"] = rng.gamma(2.0, 2.0, n_issues)
            for m in MODELS:
                d[f"f_{var}_{m}"] = d[f"obs_{var}"] + rng.normal(0, 1.0, n_issues)
        rows.append(d)
    return pd.concat(rows, ignore_index=True)


@pytest.mark.parametrize("lead", LEADS)
def test_error_memory_never_sees_current_or_unverified_outcome(lead):
    """Changing the observation of issue k must not change the memory of any case that could not yet
    have seen it. A lead-L forecast issued at t is verified at t+L, so case i may only use cases
    whose valid time is <= its issue time: lag = max(1, L // 24) daily issues."""
    n, k = 60, 30
    lag = max(1, lead // 24)
    base = _case_frame(n)
    pert = base.copy()
    sel = (pert.lead_h == lead) & (pert.issue_idx == k)
    for var in BLEND_VARS:
        pert.loc[sel, f"obs_{var}"] += 1000.0
    a, b = add_error_memory(base), add_error_memory(pert)
    sub_a = a[a.lead_h == lead].sort_values("issue_idx")
    sub_b = b[b.lead_h == lead].sort_values("issue_idx")
    mem_cols = [c for c in a.columns if c.split("_")[0] in ("hist", "rec", "histb", "recb")]
    assert mem_cols
    early = sub_a.issue_idx.values < k + lag          # cases issued before the outcome was verifiable
    for c in mem_cols:
        x, y = sub_a[c].values[early], sub_b[c].values[early]
        assert np.allclose(x, y, equal_nan=True), f"{c} leaks a not-yet-verified outcome at lead {lead}"
    late = sub_a.issue_idx.values >= k + lag
    assert any(not np.allclose(sub_a[c].values[late], sub_b[c].values[late], equal_nan=True) for c in mem_cols), \
        "memory should respond once the outcome is verifiable"


# --------------------------------------------------------------------- harmonize round trip
@pytest.mark.parametrize("unit", sorted(UNITS))
def test_unit_round_trip(unit):
    x = np.array([0.0, 0.7, 3.2, 12.5, 40.0])
    assert np.allclose(from_canonical(to_canonical(x, unit), unit), x)


def test_known_conversions():
    assert np.isclose(to_canonical(300.0, "K"), 26.85)
    assert np.isclose(to_canonical(10.0, "m/s"), 36.0)
    assert np.isclose(to_canonical(2.0, "mm/h"), 12.0)
    assert np.isclose(to_canonical(101325.0, "Pa"), 1013.25)


def _good_frame(n=50):
    return pd.DataFrame({
        "model_id": "m", "issue_time": pd.date_range("2024-01-01", periods=n, freq="6h", tz="UTC"),
        "valid_time": pd.date_range("2024-01-02", periods=n, freq="6h", tz="UTC"),
        "lead_h": 24, "location_id": "blr", "variable": "temp", "value": 25.0})


def test_validation_accepts_clean_and_flags_bad_frames():
    assert validate_frame(_good_frame(), "m").ok
    bad = _good_frame()
    bad.loc[0, "value"] = BOUNDS["temp"][1] + 5
    assert not validate_frame(bad, "m").ok
    dup = pd.concat([_good_frame(), _good_frame().iloc[:3]], ignore_index=True)
    assert validate_frame(dup, "m").duplicates == 3
    assert not validate_frame(_good_frame().drop(columns=["value"]), "m").ok
    assert set(SCHEMA) <= set(_good_frame().columns)


# --------------------------------------------------------------------- bootstrap
def _paired_sums(better: float, D=300, per=10, seed=1, same=False):
    rng = np.random.default_rng(seed)
    ref = np.abs(rng.normal(1.0, 0.5, (D, per)))
    w = ref * better if not same else np.abs(rng.normal(1.0, 0.5, (D, per)))
    return np.stack([w.sum(1), ref.sum(1)], 1), np.full(D, float(per))


def _rel_ci(sums, counts):
    d = _bootstrap(sums, counts)
    rel = -(d[:, 0] - d[:, 1]) / d[:, 1]
    return np.quantile(rel, [0.025, 0.975])


def test_bootstrap_detects_a_real_improvement():
    lo, hi = _rel_ci(*_paired_sums(0.8))
    assert lo > 0 and abs((lo + hi) / 2 - 0.2) < 0.02


def test_bootstrap_does_not_claim_improvement_from_noise():
    lo, hi = _rel_ci(*_paired_sums(1.0, same=True))
    assert lo < 0 < hi


def test_bootstrap_is_deterministic_and_resamples_dates():
    s, c = _paired_sums(0.9)
    assert np.array_equal(_bootstrap(s, c), _bootstrap(s, c))
    assert _bootstrap(s, c).shape == (2000, 2)


# --------------------------------------------------------------------- rain uncertainty
def _rain_world(n=60000, seed=3):
    rng = np.random.default_rng(seed)
    wet = rng.random(n) < 0.25
    blend = np.where(wet, rng.lognormal(1.2, 1.1, n), 0.0)
    obs = np.where(wet, blend * rng.lognormal(0.0, 0.5, n), 0.0)       # multiplicative, heavy-tailed
    lead = rng.choice(LEADS, n)
    spread = np.where(wet, 0.3 * blend, 0.0)
    return lead, blend, spread, obs


def test_rain_interval_is_not_degenerate_and_covers_nondry_cases():
    lead, blend, spread, obs = _rain_world()
    h = len(blend) // 2
    cal = UncertaintyCalibrator()
    cal.fit("rain", lead[:h], blend[:h], spread[:h], obs[:h])
    p10, p50, p90, conf, pev = cal.apply("rain", lead[h:], blend[h:], spread[h:])
    b, o = blend[h:], obs[h:]
    assert (p10 >= 0).all() and (p10 <= p50 + 1e-9).all() and (p50 <= p90 + 1e-9).all()
    assert ((conf >= 0) & (conf <= 1)).all() and ((pev >= 0) & (pev <= 1)).all()
    assert (p90 - p10)[b == 0].max() < 0.05                       # dry forecast: near point interval
    heavy = b > 8
    assert (p90 - p10)[heavy].mean() > 2.0                        # wet forecast: wide band (regression: was ~0.01)
    nd = b >= 0.05
    cov = ((o >= p10) & (o <= p90))[nd].mean()
    assert 0.74 < cov < 0.86, cov                                 # nominal 0.80, iid held-out data


def test_rain_confidence_is_calibrated_and_falls_with_forecast_amount():
    lead, blend, spread, obs = _rain_world()
    h = len(blend) // 2
    cal = UncertaintyCalibrator()
    cal.fit("rain", lead[:h], blend[:h], spread[:h], obs[:h])
    _, _, _, conf, pev = cal.apply("rain", lead[h:], blend[h:], spread[h:])
    b, o = blend[h:], obs[h:]
    hit = np.abs(o - b) <= tolerance("rain", b)
    assert abs(conf.mean() - hit.mean()) < 0.03
    bins = rain_bin(b)
    assert conf[bins == 0].mean() > conf[bins == 4].mean()
    order = np.argsort(b)
    assert (np.diff(pev[order]) >= -1e-9).all() or np.corrcoef(b, pev)[0, 1] > 0.5
    ev = o >= EVENT_THRESH["rain"]
    assert abs(pev.mean() - ev.mean()) < 0.01


# --------------------------------------------------------------------- event model
def _event_data(n_days=120, per_day=40, seed=5, rate=0.08):
    rng = np.random.default_rng(seed)
    n = n_days * per_day
    t = np.repeat(pd.date_range("2024-01-01", periods=n_days).values, per_day)
    X = pd.DataFrame(rng.normal(size=(n, 6)), columns=list("abcdef"))
    logit = 3.0 * X["a"].values + 1.5 * X["b"].values + np.log(rate / (1 - rate)) - 2.0
    y = (rng.random(n) < 1 / (1 + np.exp(-logit))).astype(int)
    return X, y, t


def test_event_model_fits_with_time_blocks_and_outputs_probabilities():
    X, y, t = _event_data()
    evm = EventModel(seed=0)
    evm.fit_var("heat", X, y, t, n_blocks=5)
    info = evm.fit_info["heat"]
    assert info["fitted"] and info["oof_coverage"] == 1.0
    p = evm.predict("heat", X)
    assert ((p >= 0) & (p <= 1)).all()
    assert p[y == 1].mean() > p[y == 0].mean()
    assert 0.1 <= evm.alert_thr["heat"] <= 0.7


def test_event_model_refuses_when_events_are_too_few():
    X, y, t = _event_data(rate=0.0005)
    y[:] = 0
    y[:5] = 1
    evm = EventModel(seed=0)
    evm.fit_var("heat", X, y, t, n_blocks=5)
    assert not evm.fit_info["heat"]["fitted"]
    assert np.isnan(evm.predict("heat", X)).all()


# --------------------------------------------------------------------- regression guards on artifacts
ART = "data/verification.json"
needs_art = pytest.mark.skipif(not os.path.exists(ART), reason="pipeline artifacts missing")


@needs_art
def test_artifacts_rain_intervals_have_real_width():
    v = json.load(open(ART))
    rain = [c for c in v["coverage"] if c["variable"] == "rain"]
    assert rain and all(c["mean_interval_width_nondry"] > 1.0 for c in rain)
    assert all(c["inside_p10_p90_nondry"] > 0.65 for c in rain)


@needs_art
def test_artifacts_report_event_skill_with_enough_events():
    v = json.load(open(ART))
    ev = {e["variable"]: e for e in v["events"]}
    assert set(ev) == set(BLEND_VARS)
    assert ev["temp"]["n_obs_events"] >= 30 and not ev["temp"]["insufficient_events"]
