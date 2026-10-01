"""Weather-regime detector: supervised classifier predicting observation-derived regime labels
from information available at forecast time (ensemble-mean forecast state, spread, tendencies)."""
from __future__ import annotations

import numpy as np
import pandas as pd
import lightgbm as lgb

from .config import REGIMES

REG_IDX = {r: i for i, r in enumerate(REGIMES)}
FEATS = ["lat", "lon", "m_sin", "m_cos", "lead_h", "region_code", "ens_temp", "ens_rh", "ens_pressure",
         "ens_wind", "ens_rain", "spr_rain", "spr_wind", "spr_temp", "dT", "dP", "t_anom"]


class RegimeDetector:
    def __init__(self, seed: int = 0):
        self.seed = seed
        self.model: lgb.LGBMClassifier | None = None
        self.clim: pd.Series | None = None

    def _prep(self, cx: pd.DataFrame) -> pd.DataFrame:
        X = cx.copy()
        key = list(zip(X.location_id, X.month))
        X["t_anom"] = X["ens_temp"].values - np.array([self.clim.get(k, np.nan) for k in key])
        return X[FEATS]

    def _new(self):
        return lgb.LGBMClassifier(objective="multiclass", n_estimators=220, learning_rate=0.05, num_leaves=15,
                                  min_child_samples=30, subsample=0.8, subsample_freq=1, colsample_bytree=0.9,
                                  random_state=self.seed, verbose=-1, n_jobs=1)

    @staticmethod
    def _full_proba(clf, X) -> np.ndarray:
        p = clf.predict_proba(X)
        out = np.zeros((len(X), len(REGIMES)))
        for j, c in enumerate(clf.classes_):
            out[:, int(c)] = p[:, j]
        return out

    def fit(self, cx_train: pd.DataFrame) -> "RegimeDetector":
        self.clim = cx_train.groupby(["location_id", "month"])["obs_temp"].mean().to_dict()
        X = self._prep(cx_train)
        y = cx_train["obs_regime"].map(REG_IDX).values
        self.model = self._new().fit(X, y)
        return self

    def oof_proba(self, cx_train: pd.DataFrame, k: int = 5) -> np.ndarray:
        """Out-of-fold probabilities for training rows (contiguous date blocks) so downstream
        meta-models never see over-confident in-sample regime probabilities."""
        X = self._prep(cx_train)
        y = cx_train["obs_regime"].map(REG_IDX).values
        dates = np.sort(cx_train["issue_time"].unique())
        edges = np.array_split(dates, k)
        out = np.zeros((len(cx_train), len(REGIMES)))
        for blk in edges:
            te = cx_train["issue_time"].isin(blk).values
            clf = self._new().fit(X[~te], y[~te])
            out[te] = self._full_proba(clf, X[te])
        return out

    def predict_proba(self, cx: pd.DataFrame) -> np.ndarray:
        return self._full_proba(self.model, self._prep(cx))


def top_regime(proba: np.ndarray):
    i = proba.argmax(axis=1)
    return np.array(REGIMES)[i], proba[np.arange(len(proba)), i]
