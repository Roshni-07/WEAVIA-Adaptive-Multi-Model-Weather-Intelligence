"""WEAVIA Lab: counterfactual weighting. Simulation for one forecast plus historical back-testing of the
same fixed weights on the held-out test slice."""
from __future__ import annotations

import numpy as np
import pandas as pd

from .config import CANON_UNIT, MODELS
from .locations import LOC_BY_ID
from .store import Store


def _norm(weights: dict) -> np.ndarray:
    w = np.array([max(0.0, float(weights.get(m, weights.get(m.replace("model_", ""), 0.0)))) for m in MODELS])
    if w.sum() <= 0:
        raise ValueError("weights must have a positive sum")
    return w / w.sum()


def simulate(store: Store, loc_id: str, var: str, issue, lead: int, weights: dict,
             scope: str = "global", same_regime: bool = False) -> dict:
    w = _norm(weights)
    b = store.row(loc_id, var, issue, lead)
    F = np.array([b[f"f_{m}"] for m in MODELS], dtype=float)
    w0 = np.array([b[f"w_{m}"] for m in MODELS], dtype=float)
    orig = float(w0 @ F)
    cf = float(w @ F)
    obs = float(b["obs"])

    loo = []
    for j, m in enumerate(MODELS):
        ww = w0.copy()
        ww[j] = 0
        ww = ww / ww.sum()
        v = float(ww @ F)
        loo.append({"model_id": m, "name": store.model_meta(m)["name"], "without_model": round(v, 3),
                    "change": round(v - orig, 3)})
    driver = max(loo, key=lambda d: abs(d["change"]))

    ts = store.test_slice(var, lead)
    loc = LOC_BY_ID[loc_id]
    if scope == "location":
        ts = ts[ts.location_id == loc_id]
    elif scope == "region":
        ts = ts[ts.location_id.isin([l.id for l in LOC_BY_ID.values() if l.region == loc.region])]
    if same_regime:
        ts = ts[ts.regime_pred == b["regime_pred"]]
    n = len(ts)
    hist = None
    if n >= 20:
        Fh = ts[[f"f_{m}" for m in MODELS]].values
        ob = ts["obs"].values
        mae_cf = float(np.abs(Fh @ w - ob).mean())
        mae_w = float(np.abs(ts["blend"].values - ob).mean())
        mae_eq = float(np.abs(Fh.mean(1) - ob).mean())
        hist = {"n": int(n), "scope": scope, "same_regime": same_regime, "mae_counterfactual": mae_cf,
                "mae_weavia": mae_w, "mae_equal": mae_eq,
                "change_vs_weavia_pct": float(100 * (mae_cf - mae_w) / mae_w) if mae_w else None,
                "verdict": ("would have increased historical MAE" if mae_cf > mae_w * 1.005 else
                            "would have reduced historical MAE" if mae_cf < mae_w * 0.995 else "no material change in historical MAE")}
    return {
        "case": {"location": loc.name, "variable": var, "unit": CANON_UNIT[var], "lead_h": lead,
                 "issue_time": pd.Timestamp(issue).isoformat()},
        "weights": {"weavia": {m: round(float(x), 4) for m, x in zip(MODELS, w0)},
                    "counterfactual": {m: round(float(x), 4) for m, x in zip(MODELS, w)}},
        "forecast": {"weavia": round(orig, 3), "counterfactual": round(cf, 3), "change": round(cf - orig, 3),
                     "equal": round(float(F.mean()), 3), "observed": round(obs, 3),
                     "weavia_error": round(orig - obs, 3), "counterfactual_error": round(cf - obs, 3),
                     "models": {m: round(float(x), 3) for m, x in zip(MODELS, F)}},
        "leave_one_out": loo,
        "driver": f"{driver['name']} moves the blend most when removed ({driver['change']:+.1f} {CANON_UNIT[var]}).",
        "historical": hist,
        "note": "Single-case result is descriptive. Historical back-test applies the same fixed weights on the held-out test slice.",
    }
