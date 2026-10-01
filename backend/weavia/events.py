"""Extreme-event model: calibrated probability that the observed value exceeds the event threshold.

LightGBM classifier on forecast-time features (per-model forecasts, WEAVIA weights/blend/spread,
regime probabilities, context) + isotonic calibration on the validation slice. The alert threshold
is chosen on validation to maximise F1 (never on test).
"""
from __future__ import annotations

import numpy as np
import pandas as pd
import lightgbm as lgb
from sklearn.isotonic import IsotonicRegression

from .config import EVENT_THRESH, MODELS, REGIMES


def event_features(cx: pd.DataFrame, d: pd.DataFrame, proba: np.ndarray) -> pd.DataFrame:
    X = pd.DataFrame({
        "blend": d["blend"].values, "spread": d["spread"].values, "model_spread": d["model_spread"].values,
        "fmax": d[[f"f_{m}" for m in MODELS]].max(axis=1).values,
        "fmin": d[[f"f_{m}" for m in MODELS]].min(axis=1).values,
        "lead_h": d["lead_h"].values,
    })
    for m in MODELS:
        X[f"f_{m}"] = d[f"f_{m}"].values
        X[f"w_{m}"] = d[f"w_{m}"].values
    for c in ["ens_temp", "ens_rh", "ens_pressure", "ens_wind", "ens_rain", "dT", "dP", "lat", "lon", "m_sin", "m_cos"]:
        X[c] = cx[c].values
    for k, r in enumerate(REGIMES):
        X[f"p_{r}"] = proba[:, k]
    return X


class EventModel:
    def __init__(self, seed: int = 0):
        self.seed = seed
        self.clf: dict[str, lgb.LGBMClassifier | None] = {}
        self.iso: dict[str, IsotonicRegression | None] = {}
        self.alert_thr: dict[str, float] = {}
        self.fit_info: dict[str, dict] = {}

    def fit_var(self, var, X_tr, y_tr, X_va, y_va):
        thr_default = 0.5
        if y_tr.sum() < 15 or y_va.sum() < 5:
            self.clf[var], self.iso[var] = None, None
            self.alert_thr[var] = thr_default
            self.fit_info[var] = {"fitted": False, "reason": f"too few events (train {int(y_tr.sum())}, val {int(y_va.sum())})"}
            return
        clf = lgb.LGBMClassifier(n_estimators=300, learning_rate=0.05, num_leaves=15, min_child_samples=20,
                                 subsample=0.8, subsample_freq=1, colsample_bytree=0.8, reg_lambda=2.0,
                                 random_state=self.seed, verbose=-1, n_jobs=1)
        clf.fit(X_tr, y_tr)
        raw = clf.predict_proba(X_va)[:, 1]
        iso = IsotonicRegression(out_of_bounds="clip", y_min=0, y_max=1).fit(raw, y_va.astype(float))
        p = iso.predict(raw)
        best, best_f1 = thr_default, -1
        for t in np.linspace(0.1, 0.7, 25):
            pred = p >= t
            tp = (pred & (y_va == 1)).sum(); fp = (pred & (y_va == 0)).sum(); fn = (~pred & (y_va == 1)).sum()
            f1 = 2 * tp / (2 * tp + fp + fn) if (2 * tp + fp + fn) else 0
            if f1 > best_f1:
                best, best_f1 = float(t), float(f1)
        self.clf[var], self.iso[var], self.alert_thr[var] = clf, iso, best
        self.fit_info[var] = {"fitted": True, "val_f1_at_alert_threshold": best_f1, "alert_threshold": best,
                              "train_events": int(y_tr.sum()), "val_events": int(y_va.sum())}

    def predict(self, var, X) -> np.ndarray:
        if self.clf[var] is None:
            return np.full(len(X), np.nan)
        return self.iso[var].predict(self.clf[var].predict_proba(X)[:, 1])
