"""Extreme-event model: calibrated probability that the observed value exceeds the event threshold.

LightGBM classifier on forecast-time features (per-model forecasts, WEAVIA weights/blend/spread,
regime probabilities, context) + isotonic calibration. Isotonic calibration and the alert threshold (F1-optimal) come from time-blocked
out-of-fold predictions on train + validation (never test).
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

    def _make_clf(self):
        return lgb.LGBMClassifier(n_estimators=300, learning_rate=0.05, num_leaves=15, min_child_samples=20,
                                  subsample=0.8, subsample_freq=1, colsample_bytree=0.8, reg_lambda=2.0,
                                  random_state=self.seed, verbose=-1, n_jobs=4)

    def fit_var(self, var, X, y, t, n_blocks: int = 5, min_events: int = 30):
        """Fit on train + validation with time-blocked cross-fitting.

        A single chronological validation block can miss a season (the synthetic one has no monsoon and no
        heat season), which starves calibration and threshold choice of events. Instead the pooled
        train+validation issue dates are cut into contiguous blocks; each block is predicted by a model fit
        on the other blocks. Isotonic calibration and the F1-optimal alert threshold are fit on those
        out-of-fold probabilities. The final classifier is fit on all pooled rows. Test is never touched.
        """
        thr_default = 0.5
        y = np.asarray(y).astype(int)
        if y.sum() < min_events:
            self.clf[var], self.iso[var] = None, None
            self.alert_thr[var] = thr_default
            self.fit_info[var] = {"fitted": False, "reason": f"too few events (calibration pool {int(y.sum())}, need {min_events})"}
            return
        dates = np.sort(pd.unique(pd.Series(t)))
        block_of = {d: i for i, chunk in enumerate(np.array_split(dates, n_blocks)) for d in chunk}
        blk = pd.Series(t).map(block_of).to_numpy()
        oof = np.full(len(y), np.nan)
        for b in range(n_blocks):
            te, tr = blk == b, blk != b
            if y[tr].sum() < 5 or te.sum() == 0:
                continue
            oof[te] = self._make_clf().fit(X[tr], y[tr]).predict_proba(X[te])[:, 1]
        ok = ~np.isnan(oof)
        iso = IsotonicRegression(out_of_bounds="clip", y_min=0, y_max=1).fit(oof[ok], y[ok].astype(float))
        p = iso.predict(oof[ok])
        yo = y[ok]
        best, best_f1 = thr_default, -1
        for thr in np.linspace(0.1, 0.7, 25):
            pred = p >= thr
            tp = (pred & (yo == 1)).sum(); fp = (pred & (yo == 0)).sum(); fn = (~pred & (yo == 1)).sum()
            f1 = 2 * tp / (2 * tp + fp + fn) if (2 * tp + fp + fn) else 0
            if f1 > best_f1:
                best, best_f1 = float(thr), float(f1)
        clf = self._make_clf().fit(X, y)
        self.clf[var], self.iso[var], self.alert_thr[var] = clf, iso, best
        self.fit_info[var] = {"fitted": True, "method": f"{n_blocks}-block time cross-fit on train+val",
                              "oof_f1_at_alert_threshold": best_f1, "alert_threshold": best,
                              "calibration_events": int(y.sum()), "oof_coverage": float(ok.mean())}

    def predict(self, var, X) -> np.ndarray:
        if self.clf[var] is None:
            return np.full(len(X), np.nan)
        return self.iso[var].predict(self.clf[var].predict_proba(X)[:, 1])
