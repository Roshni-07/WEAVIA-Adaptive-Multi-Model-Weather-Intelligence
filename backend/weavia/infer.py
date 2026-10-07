"""Score cases with already-fitted models. Mirrors the inference half of pipeline.run_from_sources exactly,
so a live issue is treated like any other case. tests/test_live.py proves the equivalence: scoring stored
validation/test cases here reproduces blend.parquet."""
from __future__ import annotations

import numpy as np
import pandas as pd

from .config import BLEND_VARS, MODELS, REGIMES
from .events import event_features
from .regime import top_regime
from .trust import inverse_error_weights, make_long
from .uncertainty import weighted_spread


def score_cases(cx: pd.DataFrame, models: dict, train_ref: pd.DataFrame | None = None,
                missing: tuple[str, ...] = ()):
    """cx: cases with features and error memory (obs may be NaN). Returns (blend_long, proba, cx_with_regime).

    missing: model ids with no data this cycle. Their forecast must already be imputed in cx; their weight is
    forced to zero and the rest renormalised, so a missing model never influences the blend directly."""
    rd, trust, calib, evm = models["regime"], models["trust"], models["calib"], models["events"]
    cx = cx.copy()
    proba = rd.predict_proba(cx)
    cx["regime_pred"], cx["regime_conf"] = top_regime(proba)
    lead = cx.lead_h.values
    miss_idx = [MODELS.index(m) for m in missing]
    if train_ref is not None:                      # inverse-error baseline needs the training rows
        both = pd.concat([train_ref, cx], ignore_index=True)
        tr_mask = (both.split == "train").values
    frames = []
    for var in BLEND_VARS:
        all_long = make_long(cx, var, proba, with_target=False)
        pred = trust.predict_err(var, all_long, len(cx))
        w = trust.weights(var, pred)
        if miss_idx:
            w = w.copy()
            w[:, miss_idx] = 0.0
            w = w / w.sum(1, keepdims=True)
        F = np.stack([cx[f"f_{var}_{m}"].values for m in MODELS], 1)
        blend = (w * F).sum(1)
        spread = weighted_spread(F, w)
        if train_ref is not None:
            wi = inverse_error_weights(both, var, tr_mask)[-len(cx):]
        else:
            wi = np.full_like(F, 1.0 / len(MODELS))
        p10, p50, p90, conf, pev_resid = calib.apply(var, lead, blend, spread)
        d = pd.DataFrame({
            "case_id": cx.case_id.values, "variable": var, "issue_time": cx.issue_time.values,
            "valid_time": cx.valid_time.values, "lead_h": lead, "location_id": cx.location_id.values,
            "split": cx.split.values, "season": cx.season.values, "blend": blend,
            "blend_equal": F.mean(1), "blend_inv": (wi * F).sum(1), "spread": spread,
            "model_spread": F.std(1), "obs": cx[f"obs_{var}"].values, "p10": p10, "p50": p50, "p90": p90,
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
        d["event_prob"] = evm.predict(var, event_features(cx, d, proba))
        frames.append(d)
    return pd.concat(frames, ignore_index=True), proba, cx
