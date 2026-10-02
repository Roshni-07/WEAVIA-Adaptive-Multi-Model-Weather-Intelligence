"""End-to-end pipeline: provider -> harmonise -> cases -> regime -> skill -> trust -> blend ->
uncertainty -> verification -> artifacts."""
from __future__ import annotations

import json
import time
from datetime import datetime, timezone
from pathlib import Path

import joblib
import numpy as np
import pandas as pd

from . import verify
from .config import (BLEND_VARS, EVENT_NAME, EVENT_THRESH, LEADS, MODELS, REGIMES, SPLIT_FRACS, CANON_UNIT)
from .features import build_cases
from .harmonize import harmonize
from .locations import LOCATIONS
from .providers.base import FetchSpec
from .providers.synthetic import SyntheticModelProvider, SyntheticObservationProvider
from .regime import RegimeDetector, top_regime
from .synthetic.world import SyntheticWorld
from .trust import TrustEngine, inverse_error_weights, make_long
from .events import EventModel, event_features
from .uncertainty import UncertaintyCalibrator, weighted_spread

CASE_COLS = ["case_id", "issue_time", "valid_time", "lead_h", "location_id", "region", "split", "season", "month",
             "ens_temp", "ens_rain", "ens_wind", "ens_rh", "ens_pressure", "spr_temp", "spr_rain", "spr_wind",
             "dT", "dP", "obs_temp", "obs_rain", "obs_wind", "obs_rh", "obs_pressure", "obs_regime"]


def build_skill_table(cx: pd.DataFrame) -> pd.DataFrame:
    tr = cx[cx.split == "train"]
    parts = []
    for var in BLEND_VARS:
        for m in MODELS:
            e = tr[f"f_{var}_{m}"] - tr[f"obs_{var}"]
            d = pd.DataFrame({"location_id": tr.location_id.values, "lead_h": tr.lead_h.values,
                              "season": tr.season.values, "regime": tr.obs_regime.values, "e": e.values})
            g = d.groupby(["location_id", "lead_h", "season", "regime"])["e"]
            t = pd.DataFrame({"n": g.size(), "sae": g.apply(lambda s: s.abs().sum()),
                              "sse": g.apply(lambda s: (s**2).sum()), "sum_err": g.sum()}).reset_index()
            t["model_id"] = m
            t["variable"] = var
            parts.append(t)
    sk = pd.concat(parts, ignore_index=True)
    sk["mae"] = sk.sae / sk.n
    sk["rmse"] = np.sqrt(sk.sse / sk.n)
    sk["bias"] = sk.sum_err / sk.n
    return sk


def build_events(blend: pd.DataFrame) -> pd.DataFrame:
    t = blend[(blend.split == "test") & (blend.lead_h == 24)].copy()
    rows = []
    for var in BLEND_VARS:
        d = t[t.variable == var]
        ex = d[d.obs >= EVENT_THRESH[var]].copy()
        ex["event_type"] = EVENT_NAME[var]
        ex["severity"] = ex.obs / EVENT_THRESH[var]
        miss = d.assign(ae=(d.blend - d.obs).abs()).nlargest(12, "ae").copy()
        miss["event_type"] = "Forecast miss"
        miss["severity"] = miss["ae"]
        for kind, dd in (("exceed", ex), ("miss", miss)):
            for _, r in dd.iterrows():
                rows.append({"event_id": f"EV-{r.valid_time:%Y%m%d}-{r.location_id}-{var}-{kind[0]}",
                             "location_id": r.location_id, "variable": var, "event_type": r.event_type,
                             "valid_time": r.valid_time, "observed_value": r.obs, "severity": r.severity,
                             "kind": kind})
    ev = pd.DataFrame(rows).drop_duplicates("event_id")
    return ev.sort_values(["variable", "severity"], ascending=[True, False]).reset_index(drop=True)


def run(out_dir: str | Path = "data", seed: int = 7, days: int = 1461, log=print) -> dict:
    t0 = time.time()
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)

    # 1. data (synthetic providers behind the real provider interface)
    world = SyntheticWorld(seed=seed, days=days)
    spec = FetchSpec(LOCATIONS)
    frames, reports, metas = {}, {}, {}
    for m in MODELS:
        p = SyntheticModelProvider(m, world)
        df, rep = p.get_forecasts(spec)
        if not rep.ok:
            raise RuntimeError(f"validation failed for {m}: {rep.issues}")
        frames[m], reports[m], metas[m] = df, rep.as_dict(), p.meta.__dict__
    fc = harmonize(frames)
    obs = SyntheticObservationProvider(world).fetch(spec)
    log(f"[data] forecasts {len(fc):,} rows, observations {len(obs):,} rows ({time.time()-t0:.0f}s)")

    # 2. cases + error memory
    cx = build_cases(fc, obs, world.regime_obs())
    tr_mask = (cx.split == "train").values
    va_mask = (cx.split == "val").values
    te_mask = (cx.split == "test").values
    log(f"[cases] {len(cx):,} cases; train/val/test = {tr_mask.sum():,}/{va_mask.sum():,}/{te_mask.sum():,}")

    # 3. regimes (OOF on train, full model on val/test)
    rd = RegimeDetector(seed).fit(cx[tr_mask])
    proba = np.zeros((len(cx), len(REGIMES)))
    proba[tr_mask] = rd.oof_proba(cx[tr_mask])
    proba[~tr_mask] = rd.predict_proba(cx[~tr_mask])
    reg_pred, reg_conf = top_regime(proba)
    cx["regime_pred"], cx["regime_conf"] = reg_pred, reg_conf
    regime_metrics = verify.regime_metrics(cx[te_mask], proba[te_mask])
    log(f"[regime] test accuracy {regime_metrics['accuracy']:.3f} (majority baseline {regime_metrics['majority_baseline']:.3f})")

    # 4. skill memory table
    skill = build_skill_table(cx)

    # 5. trust + blend + uncertainty, per variable
    trust = TrustEngine(seed)
    calib = UncertaintyCalibrator()
    evm = EventModel(seed)
    frames_b = []
    for var in BLEND_VARS:
        tr_long = make_long(cx[tr_mask], var, proba[tr_mask])
        va_long = make_long(cx[va_mask], var, proba[va_mask])
        F_va = np.stack([cx.loc[va_mask, f"f_{var}_{m}"].values for m in MODELS], 1)
        trust.fit_var(var, tr_long, va_long, F_va, cx.loc[va_mask, f"obs_{var}"].values)
        all_long = make_long(cx, var, proba, with_target=False)
        pred = trust.predict_err(var, all_long, len(cx))
        w = trust.weights(var, pred)
        F = np.stack([cx[f"f_{var}_{m}"].values for m in MODELS], 1)
        wi = inverse_error_weights(cx, var, tr_mask)
        blend = (w * F).sum(1)
        spread = weighted_spread(F, w)
        lead = cx.lead_h.values
        obs_v = cx[f"obs_{var}"].values
        # calibrate on train + validation: the chronological validation block alone can miss a whole season
        cal_mask = tr_mask | va_mask
        calib.fit(var, lead[cal_mask], blend[cal_mask], spread[cal_mask], obs_v[cal_mask])
        p10, p50, p90, conf, pev_resid = calib.apply(var, lead, blend, spread)
        d = pd.DataFrame({
            "case_id": cx.case_id.values, "variable": var, "issue_time": cx.issue_time.values,
            "valid_time": cx.valid_time.values, "lead_h": lead, "location_id": cx.location_id.values,
            "split": cx.split.values, "season": cx.season.values, "blend": blend,
            "blend_equal": F.mean(1), "blend_inv": (wi * F).sum(1), "spread": spread,
            "model_spread": F.std(1), "obs": obs_v, "p10": p10, "p50": p50, "p90": p90,
            "confidence": conf, "event_prob_resid": pev_resid,
            "regime_pred": cx.regime_pred.values, "regime_conf": cx.regime_conf.values,
            "regime_obs": cx.obs_regime.values,
        })
        for j, m in enumerate(MODELS):
            d[f"f_{m}"] = F[:, j]
            d[f"w_{m}"] = w[:, j]
            d[f"wi_{m}"] = wi[:, j]
            d[f"pe_{m}"] = pred[:, j]
            d[f"hist_{m}"] = cx[f"hist_{var}_{m}"].values
            d[f"rec_{m}"] = cx[f"rec_{var}_{m}"].values
            d[f"histb_{m}"] = cx[f"histb_{var}_{m}"].values
            d[f"recb_{m}"] = cx[f"recb_{var}_{m}"].values
        Xe = event_features(cx, d, proba)
        ye = (obs_v >= EVENT_THRESH[var]).astype(int)
        evm.fit_var(var, Xe[cal_mask], ye[cal_mask], d["issue_time"].values[cal_mask])
        d["event_prob"] = evm.predict(var, Xe)
        log(f"[events:{var}] {evm.fit_info[var]}")
        frames_b.append(d)
        log(f"[trust:{var}] tau={trust.tau[var]}  val MAE by tau: " +
            ", ".join(f"{k}:{v:.3f}" for k, v in trust.val_mae_by_tau[var].items()))
    blend = pd.concat(frames_b, ignore_index=True)
    for k, r in enumerate(REGIMES):
        pass
    proba_df = pd.DataFrame(proba.astype("float32"), columns=[f"p_{r}" for r in REGIMES])
    proba_df.insert(0, "case_id", cx.case_id.values)

    # 6. verification on the untouched test slice
    ver = verify.evaluate(blend, skill, regime_metrics, evm.alert_thr)
    events = build_events(blend)

    # 7. artifacts
    cx[CASE_COLS + ["regime_pred", "regime_conf"]].to_parquet(out / "cases.parquet")
    blend.to_parquet(out / "blend.parquet")
    proba_df.to_parquet(out / "regime_proba.parquet")
    skill.to_parquet(out / "skill.parquet")
    events.to_parquet(out / "events.parquet")
    world.truth.to_parquet(out / "truth.parquet")
    joblib.dump({"trust": trust, "calib": calib, "regime": rd, "events": evm}, out / "models.joblib")
    cut = cx.groupby("split")["issue_time"].agg(["min", "max"])
    meta = {
        "data_mode": "synthetic",
        "data_notice": ("SYNTHETIC DEVELOPMENT DATA. Four synthetic models with designed context-dependent errors. "
                        "Verification numbers validate the WEAVIA pipeline; they are NOT evidence of real-world forecast skill."),
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "seed": seed, "models": metas, "validation_reports": reports,
        "splits": {k: {"start": str(v["min"]), "end": str(v["max"])} for k, v in cut.iterrows()},
        "tau": trust.tau, "event_model": evm.fit_info, "alert_thr": evm.alert_thr, "thresholds": EVENT_THRESH, "units": CANON_UNIT,
        "leads": LEADS, "n_cases": int(len(cx)), "locations": [l.__dict__ for l in LOCATIONS],
        "model_version": "weavia-meta-lgbm-0.1",
    }
    (out / "meta.json").write_text(json.dumps(meta, indent=2, default=str))
    (out / "verification.json").write_text(json.dumps(ver, indent=2, default=str))
    log(f"[done] artifacts in {out} ({time.time()-t0:.0f}s)")
    return ver


if __name__ == "__main__":
    import sys
    run(sys.argv[1] if len(sys.argv) > 1 else "data")
