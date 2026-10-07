"""Real-data operation: `fit` learns from real history, `cycle` produces the live forecast every 6 hours.

    python -m weavia.live check                      # confirm model ids and endpoints (needs internet)
    python -m weavia.live fit   --out data_live      # back-fill from Previous Runs + archive truth, train
    python -m weavia.live cycle --out data_live      # one live cycle: fetch, score, publish
    python -m weavia.live loop  --out data_live      # cycle every 6 h (refit daily)
    WEAVIA_DATA=data_live uvicorn weavia.api.main:app

Honest limits (also stated in meta.json and surfaced by the API and UI):
  * Truth is the Open-Meteo archive: reanalysis-based, NOT independent of the models. Verification is vs reanalysis.
  * Back-test leads are 24/48/72 h (Previous Runs gives day offsets only).
  * Live rows are scored with models and error memory from the last fit. Memory is refreshed by `fit` (daily in
    `loop`), so between fits it can be up to a day plus the truth lag old. It is never newer than the forecast.
  * A model missing in a cycle is dropped and weights renormalised. The cycle is flagged `degraded`.
  * Any number of models from 3 up. More sources need history to train on (see docs/REAL_DATA_PLAN.md).
"""
from __future__ import annotations

import argparse
import json
import os
import time
from datetime import datetime, timezone
from pathlib import Path

import joblib
import numpy as np
import pandas as pd

from . import config
from .config import ALL_VARS, BLEND_VARS, LEADS, MODELS
from . import extremes
from .features import add_error_memory, build_serving_cases
from .harmonize import harmonize
from .infer import score_cases
from .locations import LOCATIONS
from .pipeline import CASE_COLS, run_from_sources
from .providers.base import FetchSpec
from .providers.openmeteo import (DEFAULT_MODELS, MODEL_CATALOG, OpenMeteoArchiveObservations, OpenMeteoClient,
                                  OpenMeteoModelProvider, check_models, floor_to_cycle)
from .regime_labels import label_regime

REAL_LEADS = (24, 48, 72)
CYCLE_HOURS = 6


def _set_models(keys, leads):
    if len(keys) < 3:
        raise ValueError(f"at least 3 models are required (trust compares each model with the others), got {len(keys)}")
    MODELS[:] = list(keys)          # in place: every module shares these list objects
    LEADS[:] = [int(l) for l in leads]


def _notice(models) -> str:
    names = ", ".join(MODEL_CATALOG[m]["name"] for m in models)
    return (f"REAL FORECAST DATA from Open-Meteo ({names}). Truth is the Open-Meteo archive, which is reanalysis-based "
            "and NOT independent of these models, so verification is against reanalysis, not station observations. "
            "Back-test leads are 24/48/72 h. Not an official forecast: use IMD for warnings.")


def _truth_and_regimes(obs: pd.DataFrame):
    wide = obs.pivot_table(index=["timestamp", "location_id"], columns="variable", values="value", aggfunc="first").reset_index()
    wide = wide.rename(columns={"timestamp": "time"}).sort_values(["location_id", "time"]).reset_index(drop=True)
    for v in ALL_VARS:
        if v not in wide:
            raise RuntimeError(f"truth is missing variable {v!r}")
    wide["regime"] = label_regime(wide)
    regime_obs = wide[["time", "location_id", "regime"]].rename(columns={"time": "valid_time", "regime": "obs_regime"})
    return wide, regime_obs


# ----------------------------------------------------------------------------------------------- fit
def fit(out_dir="data_live", models=DEFAULT_MODELS, days=365, truth_lag_days=6, locations=LOCATIONS, client=None,
        now=None, seed=7, log=print) -> dict:
    """Back-fill real history and train the whole stack through the same code path as the synthetic run."""
    t0 = time.time()
    _set_models(models, REAL_LEADS)
    client = client or OpenMeteoClient()
    now = floor_to_cycle(now if now is not None else pd.Timestamp.now(tz="UTC"))
    ve = now.normalize() - pd.Timedelta(days=truth_lag_days)       # newest valid time we ask for: truth must exist
    vs = ve - pd.Timedelta(days=days)
    spec = FetchSpec(locations, start=vs, end=ve, leads=REAL_LEADS)
    frames, reports, metas, daily_parts = {}, {}, {}, []
    for key in models:
        p = OpenMeteoModelProvider(key, "previous_runs", client=client, issue_time=now)
        df, rep = p.get_forecasts(spec)
        if not rep.ok or df.empty:
            raise RuntimeError(f"{key}: no usable history ({rep.issues or 'empty'}). Run `python -m weavia.live check`.")
        frames[key], reports[key], metas[key] = df, rep.as_dict(), p.meta.__dict__
        daily_parts.append(p.daily)
        log(f"[history:{key}] {len(df):,} rows")
    fc = harmonize(frames)
    arch = OpenMeteoArchiveObservations(client)
    obs = arch.fetch(FetchSpec(locations, start=vs - pd.Timedelta(days=2), end=ve))
    truth, regime_obs = _truth_and_regimes(obs)
    log(f"[truth] {len(obs):,} rows from {OpenMeteoArchiveObservations.SOURCE}")
    meta_extra = {
        "data_mode": "real", "data_notice": _notice(models), "seed": seed, "models": metas, "validation_reports": reports,
        "truth_source": OpenMeteoArchiveObservations.SOURCE, "truth_lag_days": truth_lag_days,
        "history_start": str(vs), "history_end": str(ve), "fitted_at": datetime.now(timezone.utc).isoformat(),
    }
    ver = run_from_sources(out_dir, fc, obs, regime_obs, truth, meta_extra, seed=seed, log=log,
                           use_issue_obs=False, save_full=True, t0=t0)
    for f in ("live_status.json", "daily_extremes.parquet", "daily_verification.json"):
        (Path(out_dir) / f).unlink(missing_ok=True)
    ver["daily_extremes"] = _fit_daily(Path(out_dir), arch, locations, pd.concat(daily_parts, ignore_index=True), log)
    return ver


def _fit_daily(out: Path, arch, locations, daily_fc: pd.DataFrame, log) -> dict:
    """IMD-aligned daily products (heat-wave indicator, 24 h rain). A failure here never breaks the main fit."""
    try:
        normals = arch.fetch_normals(locations)
        blend = pd.read_parquet(out / "blend.parquet")
        df, bands = extremes.build_products(daily_fc, blend, list(MODELS), arch.daily, normals)
        if df.empty:
            raise RuntimeError("no daily rows could be matched to WEAVIA cases")
        ver = extremes.verify_daily(df, list(MODELS))
        normals.to_parquet(out / "normals.parquet")
        joblib.dump(bands, out / "daily_bands.joblib")
        _write_atomic(df, out / "daily_extremes.parquet")
        (out / "daily_verification.json").write_text(json.dumps(ver, indent=2, default=str))
        log(f"[extremes] {len(df):,} daily rows, normals for {normals.location_id.nunique()} stations")
        return {"state": "ok", "rows": int(len(df))}
    except Exception as e:                          # noqa: BLE001
        log(f"[extremes] skipped: {type(e).__name__}: {e}")
        return {"state": "skipped", "reason": f"{type(e).__name__}: {e}"}


# ----------------------------------------------------------------------------------------------- cycle
def _write_atomic(df: pd.DataFrame, path: Path):
    tmp = path.with_suffix(".tmp.parquet")
    df.to_parquet(tmp)
    os.replace(tmp, path)


def _status(out: Path, **kw) -> dict:
    st = {"fetched_at": datetime.now(timezone.utc).isoformat(), **kw}
    tmp = out / "live_status.json.tmp"
    tmp.write_text(json.dumps(st, indent=2, default=str))
    os.replace(tmp, out / "live_status.json")
    return st


def cycle(out_dir="data_live", now=None, client=None, locations=LOCATIONS, min_models=2, log=print) -> dict:
    """One live cycle. Never raises for provider trouble: it reports `degraded` or `failed` and keeps serving the
    previous artifacts. Raises only for a setup error (no fitted real-data artifacts)."""
    out = Path(out_dir)
    meta_path = out / "meta.json"
    if not meta_path.exists():
        raise FileNotFoundError(f"{meta_path} not found: run `python -m weavia.live fit` first")
    meta = json.loads(meta_path.read_text())
    if meta.get("data_mode") != "real":
        raise RuntimeError("cycle needs artifacts from `weavia.live fit` (data_mode=real)")
    _set_models(meta["model_ids"], meta["leads"])
    client = client or OpenMeteoClient()
    issue = floor_to_cycle(now if now is not None else pd.Timestamp.now(tz="UTC"))
    spec = FetchSpec(locations, leads=tuple(LEADS))
    frames, failed, daily_parts = {}, {}, []
    for key in MODELS:
        try:
            prov = OpenMeteoModelProvider(key, "live", client=client, issue_time=issue)
            df, rep = prov.get_forecasts(spec)
            if not rep.ok:
                raise RuntimeError("validation: " + "; ".join(rep.issues))
            if df.empty:
                raise RuntimeError("empty response")
            frames[key] = df
            daily_parts.append(prov.daily)
        except Exception as e:                      # noqa: BLE001 - isolate every model failure
            failed[key] = f"{type(e).__name__}: {e}"
            log(f"[cycle] {key} unavailable: {failed[key]}")
    base = {"issue_time": issue.isoformat(), "models_ok": sorted(frames), "models_missing": failed,
            "truth_source": meta.get("truth_source"), "history_end": meta.get("history_end")}
    if len(frames) < min_models:
        return _status(out, state="failed", reason=f"only {len(frames)} of {len(MODELS)} models responded", **base)

    fc = harmonize(frames)
    missing = tuple(m for m in MODELS if m not in frames)
    if missing:       # impute a missing model with the mean of the available ones; its blend weight is forced to 0 below
        keys = ["issue_time", "valid_time", "location_id", "lead_h", "variable"]
        avg = fc.groupby(keys, as_index=False)["value"].mean()
        fc = pd.concat([fc] + [avg.assign(model_id=m)[fc.columns] for m in missing], ignore_index=True)
    live = build_serving_cases(fc)
    fcols = [f"f_{v}_{m}" for v in ALL_VARS for m in MODELS]
    complete = live[fcols].notna().all(axis=1)
    n_incomplete = int((~complete).sum())
    live = live[complete].reset_index(drop=True)
    if live.empty:
        return _status(out, state="failed", reason="no complete cases in the live response", **base)
    if n_incomplete:
        log(f"[cycle] dropped {n_incomplete} cases with missing forecast values")

    hist = pd.read_parquet(out / "cases_full.parquet")
    for c in ("issue_time", "valid_time"):
        hist[c] = pd.to_datetime(hist[c], utc=True)
    hist = hist[hist.split != "live"]
    live["case_id"] = np.arange(int(hist.case_id.max()) + 1, int(hist.case_id.max()) + 1 + len(live))
    both = pd.concat([hist, live], ignore_index=True).sort_values(["location_id", "lead_h", "issue_time"]).reset_index(drop=True)
    mem = [c for c in both.columns if c.split("_")[0] in ("hist", "rec", "histb", "recb")]
    both = add_error_memory(both.drop(columns=mem))   # recompute memory over history + live: live rows see only
                                                       # errors of cases verified before them
    live_f = both[both.split == "live"].reset_index(drop=True)

    models = joblib.load(out / "models.joblib")
    blend_new, proba_new, live_f = score_cases(live_f, models, train_ref=hist, missing=missing)

    # publish: replace any earlier rows for this issue (idempotent), keep every other live issue
    blend = pd.read_parquet(out / "blend.parquet")
    cases = pd.read_parquet(out / "cases.parquet")
    rproba = pd.read_parquet(out / "regime_proba.parquet")
    keep_cases = ~((cases.split == "live") & (pd.to_datetime(cases.issue_time, utc=True) == issue))
    drop_ids = set(cases.loc[~keep_cases, "case_id"])
    next_id = int(cases.case_id.max()) + 1
    remap = {old: next_id + i for i, old in enumerate(live_f.case_id.values)}
    live_f["case_id"] = live_f.case_id.map(remap)
    blend_new["case_id"] = blend_new.case_id.map(remap)
    proba_df = pd.DataFrame(proba_new.astype("float32"), columns=[c for c in rproba.columns if c != "case_id"])
    proba_df.insert(0, "case_id", live_f.case_id.values)
    cases = pd.concat([cases[keep_cases], live_f[CASE_COLS + ["regime_pred", "regime_conf"]]], ignore_index=True)
    blend = pd.concat([blend[~blend.case_id.isin(drop_ids)], blend_new], ignore_index=True)
    rproba = pd.concat([rproba[~rproba.case_id.isin(drop_ids)], proba_df], ignore_index=True)
    for name, df in (("cases", cases), ("regime_proba", rproba), ("blend", blend)):   # blend last: it is what readers key on
        _write_atomic(df, out / f"{name}.parquet")
    daily_state = _cycle_daily(out, daily_parts, blend_new, missing, issue, log)
    state = "ok" if not failed and not n_incomplete else "degraded"
    st = _status(out, state=state, daily_extremes=daily_state, n_cases=int(len(live_f)), n_incomplete_dropped=n_incomplete, rain_events_flagged=int(((blend_new.variable == "rain") & (blend_new.event_prob >= 0.5)).sum()), **base)
    log(f"[cycle] {state}: issue {issue:%Y-%m-%d %H:%MZ}, {len(frames)}/{len(MODELS)} models, {len(live_f)} cases")
    return st


def _cycle_daily(out: Path, daily_parts, blend_new: pd.DataFrame, missing, issue, log) -> str:
    """Daily products for this issue. Never fails the cycle: any problem is reported in the status instead."""
    if not (out / "daily_bands.joblib").exists():
        return "not fitted (run fit again once Open-Meteo is reachable)"
    try:
        bands = joblib.load(out / "daily_bands.joblib")
        normals = pd.read_parquet(out / "normals.parquet")
        dfc = pd.concat(daily_parts, ignore_index=True) if daily_parts else pd.DataFrame()
        new, _ = extremes.build_products(dfc, blend_new, list(MODELS), None, normals, bands=bands, missing=missing)
        if new.empty:
            return "no daily rows this cycle"
        path = out / "daily_extremes.parquet"
        old = pd.read_parquet(path)
        keep = ~((old.split == "live") & (pd.to_datetime(old.issue_time, utc=True) == issue))
        _write_atomic(pd.concat([old[keep], new], ignore_index=True), path)
        return f"ok ({len(new)} rows)"
    except Exception as e:                          # noqa: BLE001
        log(f"[cycle] daily extremes skipped: {type(e).__name__}: {e}")
        return f"skipped: {type(e).__name__}: {e}"


def loop(out_dir="data_live", client=None, refit_hours=24, log=print):
    """Cycle every 6 h, shortly after each run lands; refit daily. Ctrl-C to stop."""
    last_fit = pd.Timestamp.now(tz="UTC")
    while True:
        now = pd.Timestamp.now(tz="UTC")
        try:
            if (now - last_fit) >= pd.Timedelta(hours=refit_hours):
                fit(out_dir, client=client, log=log)
                last_fit = pd.Timestamp.now(tz="UTC")
            cycle(out_dir, client=client, log=log)
        except Exception as e:                      # noqa: BLE001 - the loop must survive anything
            log(f"[loop] cycle error: {type(e).__name__}: {e}")
        nxt = floor_to_cycle(pd.Timestamp.now(tz="UTC")) + pd.Timedelta(hours=CYCLE_HOURS, minutes=45)
        time.sleep(max(60, (nxt - pd.Timestamp.now(tz="UTC")).total_seconds()))


def main(argv=None):
    ap = argparse.ArgumentParser(prog="weavia.live")
    ap.add_argument("cmd", choices=["check", "fit", "cycle", "loop"])
    ap.add_argument("--out", default="data_live")
    ap.add_argument("--days", type=int, default=365)
    ap.add_argument("--truth-lag-days", type=int, default=6)
    a = ap.parse_args(argv)
    if a.cmd == "check":
        rep = check_models()
        for k, v in rep.items():
            print(f"{'OK  ' if v == 'ok' else 'FAIL'} {k}" + ("" if v == "ok" else f"  {v}"))
        raise SystemExit(0 if all(v == "ok" for v in rep.values()) else 1)
    if a.cmd == "fit":
        fit(a.out, days=a.days, truth_lag_days=a.truth_lag_days)
    elif a.cmd == "cycle":
        print(json.dumps(cycle(a.out), indent=2, default=str))
    else:
        loop(a.out)


if __name__ == "__main__":
    main()
