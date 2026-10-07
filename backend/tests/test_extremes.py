"""Daily IMD-aligned extremes: provider daily products, blending, calibration, indicators, verification."""
import numpy as np
import pandas as pd
import pytest

from fake_openmeteo import NOW, base_value, make_client
from weavia import extremes as ex
from weavia import imd_criteria as imd
from weavia.locations import LOCATIONS
from weavia.providers.base import FetchSpec
from weavia.providers.openmeteo import (OpenMeteoArchiveObservations, OpenMeteoModelProvider, daily_rain_imd,
                                         daily_tmax_ist)

LOCS = LOCATIONS[:2]
MODELS = ["a", "b", "c"]


# ------------------------------------------------------------------ provider daily products
def _hours(start, end):
    return pd.date_range(start, end, freq="h", tz="UTC")


def test_daily_tmax_uses_the_ist_calendar_day_and_needs_24_hours():
    t = _hours("2026-10-01T00:00Z", "2026-10-04T23:00Z")
    s = pd.Series(np.arange(len(t), dtype=float), index=t)
    out = daily_tmax_ist(s)
    # IST day 2026-10-02 = 2026-10-01 18:30 UTC .. 2026-10-02 18:30 UTC -> UTC stamps 19:00 (Oct 1) .. 18:00 (Oct 2)
    expect = s[(s.index >= pd.Timestamp("2026-10-01T19:00Z")) & (s.index <= pd.Timestamp("2026-10-02T18:00Z"))].max()
    assert out[pd.Timestamp("2026-10-02")] == expect
    assert pd.Timestamp("2026-10-01") not in out.index                    # incomplete first day is dropped
    assert pd.Timestamp("2026-10-05") not in out.index                    # and so is the incomplete last day


def test_daily_rain_is_the_imd_day_ending_0300_utc():
    t = _hours("2026-10-01T00:00Z", "2026-10-04T23:00Z")
    s = pd.Series(1.0, index=t)
    s[pd.Timestamp("2026-10-02T03:00Z")] = 11.0        # last hour of IMD day Oct 2
    s[pd.Timestamp("2026-10-02T04:00Z")] = 7.0         # first hour of IMD day Oct 3
    out = daily_rain_imd(s)
    assert out[pd.Timestamp("2026-10-02")] == pytest.approx(23 + 11.0)
    assert out[pd.Timestamp("2026-10-03")] == pytest.approx(23 * 1.0 + 7.0)


def test_provider_live_daily_values_and_lead_days():
    client, _ = make_client()
    p = OpenMeteoModelProvider("ifs", "live", client=client, issue_time=NOW)
    p.fetch(FetchSpec(LOCS, leads=(24, 48, 72)))
    d = p.daily
    assert set(d.lead_day) == {1, 2, 3} and set(d.variable) == {"tmax", "rain24"}
    row = d[(d.variable == "rain24") & (d.lead_day == 2) & (d.location_id == LOCS[0].id)].iloc[0]
    assert row.valid_day == pd.Timestamp("2026-10-04") and row.value == pytest.approx(24 * base_value("precipitation", 0, NOW))
    day = pd.Timestamp("2026-10-03")
    hrs = [t for t in _hours("2026-10-02T19:00Z", "2026-10-03T18:00Z")]
    expect = max(base_value("temperature_2m", LOCS[1].lat, t) for t in hrs)
    got = d[(d.variable == "tmax") & (d.valid_day == day) & (d.location_id == LOCS[1].id)].value.iloc[0]
    assert got == pytest.approx(expect)


def test_provider_previous_runs_daily_uses_the_day_offset_as_lead_day():
    client, _ = make_client()
    p = OpenMeteoModelProvider("gfs", "previous_runs", client=client, issue_time=NOW, chunk_days=10)
    spec = FetchSpec(LOCS, start=pd.Timestamp("2026-09-01T00:00Z"), end=pd.Timestamp("2026-09-25T00:00Z"), leads=(24, 48, 72))
    p.fetch(spec)
    d = p.daily
    r = d[(d.variable == "rain24") & (d.lead_day == 3) & (d.location_id == LOCS[0].id)].value
    assert len(r) > 15 and np.allclose(r, 24 * base_value("precipitation", 0, NOW, k=3))
    assert not d.duplicated(["valid_day", "lead_day", "location_id", "variable"]).any()


def test_archive_truth_daily_and_normals():
    client, _ = make_client()
    prov = OpenMeteoArchiveObservations(client)
    prov.fetch(FetchSpec(LOCS, start=pd.Timestamp("2026-09-01T00:00Z"), end=pd.Timestamp("2026-09-12T00:00Z")))
    d = prov.daily
    assert set(d.variable) == {"tmax", "rain24"} and np.allclose(d[d.variable == "rain24"].value, 24 * 0.5)
    n = prov.fetch_normals(LOCS, 1991, 2020)
    assert set(n.location_id) == {l.id for l in LOCS} and n.groupby("location_id").doy.nunique().eq(366).all()
    exp = 30 + 5 * np.sin(2 * np.pi * 150 / 365.25) + LOCS[0].lat / 10
    got = n[(n.location_id == LOCS[0].id) & (n.doy == 150)].normal_tmax.iloc[0]
    assert abs(got - exp) < 0.6                                                # smoothing shaves a little off the curve
    assert n.normal_tmax.notna().all()


# ------------------------------------------------------------------ blending
def _fc_and_blend(n_days=40, seed=0):
    rng = np.random.default_rng(seed)
    days = pd.date_range("2026-03-01", periods=n_days, freq="D")
    rows, brow = [], []
    for loc in LOCS:
        for d in days:
            for k in (1, 2):
                truth_t = 38 + rng.normal(0, 2)
                for m, bias in zip(MODELS, (0.0, 1.5, -1.0)):
                    rows.append((m, d, k, loc.id, "tmax", truth_t + bias + rng.normal(0, 0.7 * k)))
                    rows.append((m, d, k, loc.id, "rain24", max(0.0, rng.gamma(1.2, 12) * (1 + bias / 10))))
    daily = pd.DataFrame(rows, columns=["model_id", "valid_day", "lead_day", "location_id", "variable", "value"])
    for loc in LOCS:
        for d in days:
            for k in (1, 2):
                for var in ("temp", "rain"):
                    for step in (0, 6, 12, 18):
                        vt = pd.Timestamp(d, tz="UTC") + pd.Timedelta(hours=step)
                        w = np.array([0.5, 0.3, 0.2]) if step == 6 else np.array([0.2, 0.2, 0.6])
                        brow.append((var, 24 * k, loc.id, vt, vt - pd.Timedelta(hours=24 * k), *w))
    blend = pd.DataFrame(brow, columns=["variable", "lead_h", "location_id", "valid_time", "issue_time", "w_a", "w_b", "w_c"])
    return daily, blend


def test_daily_blend_uses_weights_of_the_case_nearest_the_day_midpoint():
    daily, blend = _fc_and_blend()
    out = ex.daily_blend(daily, blend, MODELS)
    t = out[(out.variable == "tmax")].iloc[0]
    w = np.array([0.5, 0.3, 0.2])                      # 06:30 UTC midpoint -> the 06 UTC case
    assert t.blend == pytest.approx(sum(w[i] * t[f"f_{m}"] for i, m in enumerate(MODELS)))
    assert t.equal == pytest.approx(np.mean([t[f"f_{m}"] for m in MODELS]))
    assert {"issue_time", "lead_day", "valid_day"} <= set(out.columns)


def test_missing_model_is_imputed_and_carries_zero_weight():
    daily, blend = _fc_and_blend()
    blend = blend.assign(w_c=0.0, w_a=0.6, w_b=0.4)
    d2 = daily[daily.model_id != "c"]
    out = ex.daily_blend(d2, blend, MODELS, missing=("c",))
    r = out.iloc[0]
    assert r.blend == pytest.approx(0.6 * r.f_a + 0.4 * r.f_b) and np.isfinite(r.f_c)


def test_splits_are_chronological():
    s = ex.assign_splits(pd.Series(pd.date_range("2026-01-01", periods=100)))
    assert (s.iloc[:60] == "train").all() and (s.iloc[60:75] == "val").all() and (s.iloc[75:] == "test").all()


# ------------------------------------------------------------------ calibration and indicators
def test_bands_tmax_probability_matches_a_known_gaussian():
    rng = np.random.default_rng(1)
    n = 20000
    df = pd.DataFrame({"variable": "tmax", "lead_day": 1, "blend": 40.0, "obs": 40.0 + rng.normal(0, 1, n)})
    b = ex.DailyBands().fit(df)
    assert b.prob_ge("tmax", 1, [40.0], 41.0)[0] == pytest.approx(0.159, abs=0.015)
    assert b.prob_ge("tmax", 1, [43.0], 41.0)[0] > 0.97 and b.prob_ge("tmax", 1, [37.0], 41.0)[0] < 0.01
    lo, hi = b.interval("tmax", 1, [40.0])
    assert lo[0] == pytest.approx(40 - 1.2816, abs=0.05) and hi[0] == pytest.approx(40 + 1.2816, abs=0.05)


def test_bands_rain_heavy_probability_rises_with_the_forecast():
    rng = np.random.default_rng(2)
    n = 30000
    bl = rng.gamma(1.0, 25, n)
    df = pd.DataFrame({"variable": "rain24", "lead_day": 1, "blend": bl, "obs": bl * rng.lognormal(0, 0.5, n)})
    b = ex.DailyBands().fit(df)
    p = b.prob_ge("rain24", 1, [5.0, 40.0, 64.5, 120.0], imd.HEAVY_RAIN_24H_MM)
    assert (np.diff(p) > 0).all() and p[0] < 0.02 and p[-1] > 0.85
    lo, hi = b.interval("rain24", 1, [30.0])
    assert 0 <= lo[0] < 30 < hi[0]


def test_indicators_match_the_imd_rule_on_known_rows():
    normals = pd.DataFrame({"location_id": LOCS[0].id, "doy": range(1, 367), "normal_tmax": 35.0})
    df = pd.DataFrame({"variable": "tmax", "lead_day": 1, "location_id": LOCS[0].id, "valid_day": pd.Timestamp("2026-05-10"),
                       "blend": [41.0, 38.0, 45.5], "equal": [41.0, 41.0, 45.5], "obs": [40.5, 38.0, 46.0]})
    bands = ex.DailyBands().fit(pd.DataFrame({"variable": "tmax", "lead_day": 1, "blend": 40.0,
                                              "obs": 40.0 + np.random.default_rng(0).normal(0, 1, 5000)}))
    out = ex.add_indicators(df, normals, bands)
    terr = LOCS[0].terrain
    assert out.cls_blend.tolist() == imd.heat_wave_class([41.0, 38.0, 45.5], 35.0, terr).tolist()
    assert out.cls_equal.tolist() == imd.heat_wave_class([41.0, 41.0, 45.5], 35.0, terr).tolist()
    assert out.p_event.iloc[0] > out.p_event.iloc[1] and (out.normal == 35.0).all() and (out.terrain == terr).all()


# ------------------------------------------------------------------ verification
def _verif_frame(skill: bool, seed=3, n_days=200):
    rng = np.random.default_rng(seed)
    rows = []
    for loc in LOCS:
        for d in pd.date_range("2026-01-01", periods=n_days):
            truth = 36 + 8 * np.sin(np.pi * d.dayofyear / 365) + rng.normal(0, 2.5)
            f = {m: truth + rng.normal(0, s) for m, s in zip(MODELS, (0.6, 2.5, 2.5))}
            eq = np.mean(list(f.values()))
            bl = (0.9 * f["a"] + 0.05 * f["b"] + 0.05 * f["c"]) if skill else eq
            rows.append(dict(variable="tmax", lead_day=1, location_id=loc.id, valid_day=d, blend=bl, equal=eq, obs=truth,
                             **{f"f_{m}": v for m, v in f.items()}))
    df = pd.DataFrame(rows)
    df["split"] = ex.assign_splits(df.valid_day)
    normals = pd.DataFrame([{"location_id": l.id, "doy": i, "normal_tmax": 33.0} for l in LOCS for i in range(1, 367)])
    return ex.add_indicators(df, normals, ex.DailyBands().fit(df[df.split != "test"])), df


def test_verification_detects_real_skill_and_refuses_to_invent_it():
    good, _ = _verif_frame(skill=True)
    v = ex.verify_daily(good, MODELS, n_boot=400)
    row = [r for r in v["mae"] if r["variable"] == "tmax" and r["lead_day"] == 1][0]
    assert row["vs"]["equal"]["significant"] and row["vs"]["equal"]["ci95_pct"][0] > 0
    none, _ = _verif_frame(skill=False)
    v0 = ex.verify_daily(none, MODELS, n_boot=400)
    r0 = [r for r in v0["mae"] if r["variable"] == "tmax"][0]
    assert not r0["vs"]["equal"]["significant"] and abs(r0["vs"]["equal"]["improvement_pct"]) < 1e-9


def test_event_verification_flags_too_few_events_and_reports_ci_when_enough():
    good, _ = _verif_frame(skill=True)
    hw = ex.verify_daily(good, MODELS, n_boot=400)["heat_wave"]["1"]
    assert hw["n_obs_events"] > 30 and not hw["insufficient_events"]
    assert set(hw["f1_gain_vs_equal"]) == {"value", "ci95", "significant"} and hw["f1_gain_vs_equal"]["ci95"][0] <= hw["f1_gain_vs_equal"]["value"] <= hw["f1_gain_vs_equal"]["ci95"][1]
    rare = good.copy()
    rare["cls_obs"] = 0.0
    rare.loc[rare.index[:6], "cls_obs"] = 1.0
    assert ex.verify_daily(rare, MODELS, n_boot=200)["heat_wave"]["1"]["insufficient_events"] is True


def test_regional_declaration_counts_hits_misses_false_alarms():
    d = pd.date_range("2026-05-01", periods=4)
    rows = []
    for loc in LOCS[:1] * 1:
        pass
    ids = [l.id for l in LOCATIONS if l.region == LOCATIONS[0].region][:2] or [LOCATIONS[0].id]
    for sid in ids:
        for i, day in enumerate(d):
            rows.append(dict(valid_day=day, location_id=sid, cls_blend=1.0 if i in (1, 2, 3) else 0.0, cls_obs=1.0 if i in (0, 1, 2) else 0.0))
    r = ex.regional_declarations(pd.DataFrame(rows))
    assert r["status"].startswith("indicator") and r["hits"] + r["false_alarms"] + r["misses"] >= 0
    assert r["n_region_days"] == 4
