"""End-to-end real-data chain on a fake Open-Meteo backed by the synthetic world:
fit (Previous Runs + archive) -> cycle (live) -> store -> API. Proves plumbing, scoring equivalence and no-hindsight
behaviour. It cannot prove real-service behaviour or real skill."""
import json
import shutil

import numpy as np
import pandas as pd
import pytest
from fastapi.testclient import TestClient

from weavia import config, live
from weavia.infer import score_cases
from weavia.synthetic.world import SyntheticWorld
from world_fake import WorldFake, make_client

ISSUE = pd.Timestamp("2024-02-21T00:00:00Z")            # last synthetic issue: a full 72 h of truth follows it
FIT_NOW = ISSUE + pd.Timedelta(days=6)                  # truth lag 6 days -> history ends exactly at ISSUE
NOW = ISSUE + pd.Timedelta(hours=2)


@pytest.fixture(scope="module")
def world():
    return SyntheticWorld(seed=7, days=420)


@pytest.fixture(scope="module")
def art(world, tmp_path_factory):
    out = tmp_path_factory.mktemp("live")
    saved = (list(config.MODELS), list(config.LEADS))
    client = make_client(WorldFake(world, ISSUE))
    ver = live.fit(str(out), days=330, now=FIT_NOW, client=client, log=lambda *_: None)
    yield out, ver
    config.MODELS[:], config.LEADS[:] = saved


def _fresh(art, tmp_path):
    out = tmp_path / "copy"
    shutil.copytree(art[0], out)
    return out


def test_fit_labels_real_mode_honestly(art):
    out, ver = art
    meta = json.loads((out / "meta.json").read_text())
    assert meta["data_mode"] == "real" and meta["leads"] == [24, 48, 72]
    assert meta["model_ids"] == ["ifs", "aifs", "gfs", "icon"]
    assert "reanalysis" in meta["truth_source"] and "NOT independent" in meta["data_notice"]
    assert meta["history_end"].startswith("2024-02-21")
    assert (out / "cases_full.parquet").exists() and "headline" in ver


def test_scoring_matches_the_pipeline_exactly(art):
    """score_cases (used live) must reproduce blend.parquet for stored validation/test cases."""
    import joblib
    out, _ = art
    cx = pd.read_parquet(out / "cases_full.parquet")
    for c in ("issue_time", "valid_time"):
        cx[c] = pd.to_datetime(cx[c], utc=True)
    sub = cx[cx.split.isin(["val", "test"])].sample(1500, random_state=1).reset_index(drop=True)
    got, _, _ = score_cases(sub, joblib.load(out / "models.joblib"), train_ref=None)
    ref = pd.read_parquet(out / "blend.parquet")
    m = got.merge(ref, on=["case_id", "variable"], suffixes=("", "_ref"))
    assert len(m) == len(got) == 1500 * 3
    for col in ["blend", "p10", "p90", "confidence", "event_prob", "spread", "w_ifs", "w_aifs", "w_gfs", "w_icon"]:
        assert np.allclose(m[col], m[col + "_ref"], atol=1e-6, equal_nan=True), col


def test_cycle_publishes_a_live_issue_without_hindsight(art, world, tmp_path):
    out = _fresh(art, tmp_path)
    st = live.cycle(str(out), now=NOW, client=make_client(WorldFake(world, ISSUE)), log=lambda *_: None)
    assert st["state"] == "ok" and st["models_ok"] == ["aifs", "gfs", "icon", "ifs"] and not st["models_missing"]
    blend = pd.read_parquet(out / "blend.parquet")
    lv = blend[blend.split == "live"]
    assert len(lv) == 20 * 3 * 3 and (pd.to_datetime(lv.issue_time, utc=True) == ISSUE).all()
    assert lv.obs.isna().all()                                         # no outcome exists for a live case
    assert set(lv.lead_h) == {24, 48, 72}
    w = lv[[f"w_{m}" for m in ("ifs", "aifs", "gfs", "icon")]].values
    assert np.allclose(w.sum(1), 1) and (w >= 0).all()
    assert lv[['blend', 'p10', 'p90', 'confidence']].notna().all().all() and (lv.p10 <= lv.p90).all()
    fitted = json.loads((out / "meta.json").read_text())["event_model"]
    for var, g in lv.groupby("variable"):
        if fitted[var]["fitted"]:
            assert g.event_prob.between(0, 1).all(), var                # fitted: a real probability
        else:
            assert g.event_prob.isna().all(), var                       # unfitted: honestly absent, never invented
    truth_after = world.truth[world.truth.time > ISSUE]                 # the future the cycle must not have used
    cases = pd.read_parquet(out / "cases.parquet")
    assert cases[cases.split == "live"].obs_temp.isna().all()
    assert len(truth_after) > 0
    # history in the training artifacts ends at the issue, never beyond
    hist = pd.read_parquet(out / "cases_full.parquet")
    assert pd.to_datetime(hist.valid_time, utc=True).max() <= ISSUE


def test_cycle_is_idempotent(art, world, tmp_path):
    out = _fresh(art, tmp_path)
    c = make_client(WorldFake(world, ISSUE))
    live.cycle(str(out), now=NOW, client=c, log=lambda *_: None)
    n1 = len(pd.read_parquet(out / "blend.parquet"))
    live.cycle(str(out), now=NOW + pd.Timedelta(hours=1), client=c, log=lambda *_: None)   # same 6 h cycle
    blend = pd.read_parquet(out / "blend.parquet")
    assert len(blend) == n1 and len(blend[blend.split == "live"]) == 20 * 3 * 3        # same cycle replaced, not duplicated
    assert blend.groupby(["case_id", "variable"]).size().max() == 1


def test_missing_model_is_dropped_flagged_and_weights_renormalised(art, world, tmp_path):
    out = _fresh(art, tmp_path)
    st = live.cycle(str(out), now=NOW, client=make_client(WorldFake(world, ISSUE, down_models={"model_c"})), log=lambda *_: None)
    assert st["state"] == "degraded" and list(st["models_missing"]) == ["gfs"] and "gfs" not in st["models_ok"]
    lv = pd.read_parquet(out / "blend.parquet").query("split == 'live'")
    assert (lv.w_gfs == 0).all()
    assert np.allclose(lv[["w_ifs", "w_aifs", "w_icon"]].sum(1), 1)
    assert lv.blend.notna().all() and np.isfinite(lv.blend).all()


def test_total_outage_reports_failed_and_keeps_serving_old_artifacts(art, world, tmp_path):
    out = _fresh(art, tmp_path)
    before = pd.read_parquet(out / "blend.parquet")
    st = live.cycle(str(out), now=NOW, client=make_client(WorldFake(world, ISSUE, all_down=True)), log=lambda *_: None)
    assert st["state"] == "failed" and len(st["models_missing"]) == 4
    assert pd.read_parquet(out / "blend.parquet").shape == before.shape        # nothing half-written
    assert json.loads((out / "live_status.json").read_text())["state"] == "failed"


def test_cycle_requires_a_real_fit(tmp_path):
    with pytest.raises(FileNotFoundError):
        live.cycle(str(tmp_path / "nothing"))


def test_api_serves_the_live_issue_with_freshness(art, world, tmp_path, monkeypatch):
    import weavia.api.main as api
    out = _fresh(art, tmp_path)
    live.cycle(str(out), now=NOW, client=make_client(WorldFake(world, ISSUE)), log=lambda *_: None)
    monkeypatch.setattr(api, "DATA_DIR", str(out))
    monkeypatch.setattr(api, "_store", None)
    c = TestClient(api.app)
    meta = c.get("/api/v1/meta").json()
    assert meta["provenance"]["data_mode"] == "real" and "reanalysis" in meta["provenance"]["truth_source"]
    lv = meta["provenance"]["live"]
    assert lv["state"] == "ok" and lv["age_minutes"] is not None and "stale" in lv
    assert meta["latest_issue"] == "2024-02-21T00:00Z" and meta["leads"] == [24, 48, 72]
    assert [m["model_id"] for m in meta["models"]] == ["ifs", "aifs", "gfs", "icon"]
    mp = c.get("/api/v1/map?lead=24")
    assert mp.status_code == 200 and len(mp.json()["points"]) == 20
    loc = meta["locations"][0]["id"]
    f = c.get(f"/api/v1/forecast?location_id={loc}&variable=temp&lead=48")
    assert f.status_code == 200
    tl = c.get(f"/api/v1/timeline?location_id={loc}&variable=rain").json()
    assert all(r["observed"] is None for r in tl["series"])                  # live: no outcome, serialised as null
    assert c.get(f"/api/v1/regime?location_id={loc}&lead=24").json()["observed_regime"] is None
    assert c.get("/api/v1/health").json()["status"] in ("ok", "stale")
    assert c.get("/api/v1/map?lead=6").status_code == 422                    # 6 h is not a real-data lead


def test_api_reloads_after_a_new_cycle(art, world, tmp_path, monkeypatch):
    import weavia.api.main as api
    out = _fresh(art, tmp_path)
    monkeypatch.setattr(api, "DATA_DIR", str(out))
    monkeypatch.setattr(api, "_store", None)
    c = TestClient(api.app)
    assert c.get("/api/v1/health").json()["live"] is None                     # fitted, never cycled
    live.cycle(str(out), now=NOW, client=make_client(WorldFake(world, ISSUE)), log=lambda *_: None)
    h = c.get("/api/v1/health").json()                                         # same process, no restart
    assert h["live"]["state"] == "ok" and c.get("/api/v1/meta").json()["latest_issue"] == "2024-02-21T00:00Z"


def test_stale_data_is_flagged(art, tmp_path, monkeypatch):
    import weavia.api.main as api
    out = _fresh(art, tmp_path)
    (out / "live_status.json").write_text(json.dumps({"state": "ok", "issue_time": "2020-01-01", "fetched_at": "2020-01-01T00:00:00+00:00"}))
    monkeypatch.setattr(api, "DATA_DIR", str(out))
    monkeypatch.setattr(api, "_store", None)
    h = TestClient(api.app).get("/api/v1/health").json()
    assert h["status"] == "stale" and h["live"]["stale"] is True


# ----------------------------------------------------------------------------- daily IMD-aligned extremes
def test_fit_builds_daily_extremes_with_honest_verification(art):
    out, ver = art
    assert ver["daily_extremes"]["state"] == "ok", ver["daily_extremes"]
    d = pd.read_parquet(out / "daily_extremes.parquet")
    assert set(d.variable) == {"tmax", "rain24"} and set(d.split) == {"train", "val", "test"} and set(d.lead_day) == {1, 2, 3}
    assert d.loc[d.variable == "tmax", "terrain"].isin(["plains", "coastal", "hilly"]).all()
    assert d.loc[d.variable == "tmax", "p_event"].between(0, 1).all() and (d.p10 <= d.p90 + 1e-9).all()
    v = json.loads((out / "daily_verification.json").read_text())
    assert v["mae"] and all("ci95_pct" in x["vs"]["equal"] for x in v["mae"])
    for blk in (v["heat_wave"] or {}).values():
        assert "insufficient_events" in blk                      # the verdict is always stated, never implied
    assert (out / "normals.parquet").exists() and (out / "daily_bands.joblib").exists()


def test_cycle_adds_live_daily_rows_idempotently_and_never_with_outcomes(art, world, tmp_path):
    out = _fresh(art, tmp_path)
    c = make_client(WorldFake(world, ISSUE))
    st = live.cycle(str(out), now=NOW, client=c, log=lambda *_: None)
    assert str(st["daily_extremes"]).startswith("ok"), st["daily_extremes"]
    d = pd.read_parquet(out / "daily_extremes.parquet")
    lv = d[d.split == "live"]
    assert len(lv) > 0 and lv.obs.isna().all() and set(lv.lead_day) <= {1, 2, 3}
    assert (pd.to_datetime(lv.issue_time, utc=True) == ISSUE).all()
    n = len(d)
    live.cycle(str(out), now=NOW + pd.Timedelta(hours=1), client=c, log=lambda *_: None)
    assert len(pd.read_parquet(out / "daily_extremes.parquet")) == n


def test_daily_failure_never_breaks_the_cycle(art, world, tmp_path):
    out = _fresh(art, tmp_path)
    (out / "normals.parquet").unlink()
    st = live.cycle(str(out), now=NOW, client=make_client(WorldFake(world, ISSUE)), log=lambda *_: None)
    assert st["state"] == "ok" and str(st["daily_extremes"]).startswith("skipped")
    assert len(pd.read_parquet(out / "blend.parquet").query("split == 'live'")) > 0


def test_extremes_api(art, world, tmp_path, monkeypatch):
    import weavia.api.main as api
    out = _fresh(art, tmp_path)
    live.cycle(str(out), now=NOW, client=make_client(WorldFake(world, ISSUE)), log=lambda *_: None)
    monkeypatch.setattr(api, "DATA_DIR", str(out))
    monkeypatch.setattr(api, "_store", None)
    c = TestClient(api.app)
    r = c.get("/api/v1/extremes?lead_day=2")
    assert r.status_code == 200, r.text[:300]
    j = r.json()
    assert "not an IMD declaration" in j["status"] and j["lead_day"] == 2 and j["available_lead_days"] == [1, 2, 3]
    assert len(j["stations"]) == 20 and j["definitions"]["heat_wave"]["gate_c"]["coastal"] == 37.0
    s0 = j["stations"][0]
    assert {"tmax", "rain24", "terrain"} <= set(s0) and 0 <= s0["tmax"]["p_heat_wave"] <= 1
    assert s0["tmax"]["heat_wave_class"] in (0, 1, 2) and s0["rain24"]["imd_class"] in (
        "no_rain", "very_light", "light", "moderate", "heavy", "very_heavy", "extremely_heavy")
    probs = [x["tmax"]["p_heat_wave"] for x in j["stations"]]
    assert probs == sorted(probs, reverse=True)
    assert j["regional_outlook"] and {"region", "date", "declared_indicator"} <= set(j["regional_outlook"][0])
    assert c.get("/api/v1/extremes?lead_day=4").status_code == 422
    v = c.get("/api/v1/extremes/verification")
    assert v.status_code == 200 and v.json()["verification"]["mae"]


def test_extremes_404_explains_when_daily_products_are_absent(art, tmp_path, monkeypatch):
    import weavia.api.main as api
    out = _fresh(art, tmp_path)
    for f in ("daily_extremes.parquet", "daily_verification.json"):
        (out / f).unlink()
    monkeypatch.setattr(api, "DATA_DIR", str(out))
    monkeypatch.setattr(api, "_store", None)
    c = TestClient(api.app)
    for route in ("/api/v1/extremes", "/api/v1/extremes/verification"):
        r = c.get(route)
        assert r.status_code == 404 and "No daily extremes" in r.json()["detail"]
    assert c.get("/api/v1/health").status_code == 200                     # the rest of the API is unaffected
