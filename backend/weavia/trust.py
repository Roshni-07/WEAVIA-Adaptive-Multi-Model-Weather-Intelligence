"""Dynamic trust engine.

Baselines
  equal          : w_i = 1/n
  inverse_error  : w_i ∝ 1/(MAE_i + eps) per (location, variable, lead), fit on TRAIN only
Adaptive (WEAVIA)
  A LightGBM meta-model predicts each model's expected log-absolute-error from context
  (location, season, lead, predicted regime + probabilities, model spread, model's deviation from
  consensus, verified historical skill, verified recent error ...). Trust = softmax(-pred_err / tau).
"""
from __future__ import annotations

import numpy as np
import pandas as pd
import lightgbm as lgb

from .config import BLEND_VARS, MODELS, REGIMES, SPREAD_FLOOR

BASE_FEATS = ["model_idx", "f", "ens", "dev", "abs_dev", "spread", "rel_spread", "ens_temp", "ens_rh",
              "ens_pressure", "ens_wind", "ens_rain", "dT", "dP", "lat", "lon", "m_sin", "m_cos", "lead_h",
              "region_code", "regime_code", "regime_conf", "hist", "rec", "histb", "recb"] + [f"p_{r}" for r in REGIMES]


def make_long(cx: pd.DataFrame, var: str, proba: np.ndarray, with_target: bool = True) -> pd.DataFrame:
    N = len(cx)
    F = np.stack([cx[f"f_{var}_{m}"].values for m in MODELS], 1)
    ens, spread = F.mean(1), F.std(1)
    others = (F.sum(1, keepdims=True) - F) / (len(MODELS) - 1)
    rcode = proba.argmax(1)
    rconf = proba.max(1)
    blocks = []
    for j, m in enumerate(MODELS):
        d = {
            "case_row": np.arange(N), "model_idx": np.full(N, j), "f": F[:, j], "ens": ens,
            "dev": F[:, j] - others[:, j], "abs_dev": np.abs(F[:, j] - others[:, j]), "spread": spread,
            "rel_spread": spread / (np.abs(ens) + SPREAD_FLOOR[var]),
            "regime_code": rcode, "regime_conf": rconf,
            "hist": cx[f"hist_{var}_{m}"].values, "rec": cx[f"rec_{var}_{m}"].values,
            "histb": cx[f"histb_{var}_{m}"].values, "recb": cx[f"recb_{var}_{m}"].values,
        }
        for c in ["ens_temp", "ens_rh", "ens_pressure", "ens_wind", "ens_rain", "dT", "dP", "lat", "lon", "m_sin",
                  "m_cos", "lead_h", "region_code"]:
            d[c] = cx[c].values
        for k, r in enumerate(REGIMES):
            d[f"p_{r}"] = proba[:, k]
        if with_target:
            d["y"] = np.log1p(np.abs(F[:, j] - cx[f"obs_{var}"].values))
        blocks.append(pd.DataFrame(d))
    out = pd.concat(blocks, ignore_index=True)
    return out


def softmax_weights(pred: np.ndarray, tau: float) -> np.ndarray:
    z = -pred / tau
    z = z - z.max(1, keepdims=True)
    e = np.exp(z)
    return e / e.sum(1, keepdims=True)


def inverse_error_weights(cx: pd.DataFrame, var: str, train_mask: np.ndarray, eps: float = 1e-3) -> np.ndarray:
    tr = cx[train_mask]
    mae = {}
    for m in MODELS:
        e = (tr[f"f_{var}_{m}"] - tr[f"obs_{var}"]).abs()
        mae[m] = e.groupby([tr.location_id, tr.lead_h]).mean()
    keys = pd.MultiIndex.from_arrays([cx.location_id, cx.lead_h])
    inv = np.stack([1.0 / (mae[m].reindex(keys).values + eps) for m in MODELS], 1)
    return inv / inv.sum(1, keepdims=True)


class TrustEngine:
    TAUS = [0.05, 0.1, 0.15, 0.2, 0.3, 0.5, 0.8, 1.2, 2.0]

    def __init__(self, seed: int = 0):
        self.seed = seed
        self.models: dict[str, lgb.LGBMRegressor] = {}
        self.tau: dict[str, float] = {}
        self.val_mae_by_tau: dict[str, dict] = {}

    @staticmethod
    def _X(long_df: pd.DataFrame) -> pd.DataFrame:
        X = long_df[BASE_FEATS].copy()
        X["model_idx"] = X["model_idx"].astype("category")
        return X

    def fit_var(self, var: str, tr_long: pd.DataFrame, va_long: pd.DataFrame, va_F: np.ndarray, va_obs: np.ndarray):
        reg = lgb.LGBMRegressor(n_estimators=700, learning_rate=0.05, num_leaves=31, min_child_samples=100,
                                subsample=0.8, subsample_freq=1, colsample_bytree=0.8, reg_lambda=1.0,
                                random_state=self.seed, verbose=-1, n_jobs=1)
        Xtr, Xva = self._X(tr_long), self._X(va_long)
        Xva["model_idx"] = pd.Categorical(Xva["model_idx"], categories=Xtr["model_idx"].cat.categories)
        reg.fit(Xtr, tr_long["y"], eval_set=[(Xva, va_long["y"])], callbacks=[lgb.early_stopping(40, verbose=False)])
        self.models[var] = reg
        pred = self.predict_err(var, va_long, len(va_obs))
        res = {}
        for tau in self.TAUS:
            w = softmax_weights(pred, tau)
            res[tau] = float(np.abs((w * va_F).sum(1) - va_obs).mean())
        self.val_mae_by_tau[var] = res
        self.tau[var] = min(res, key=res.get)

    def predict_err(self, var: str, long_df: pd.DataFrame, n_cases: int) -> np.ndarray:
        X = self._X(long_df)
        X["model_idx"] = pd.Categorical(X["model_idx"], categories=list(range(len(MODELS))))
        p = self.models[var].predict(X)
        return p.reshape(len(MODELS), n_cases).T

    def contribs(self, var: str, long_rows: pd.DataFrame) -> pd.DataFrame:
        X = self._X(long_rows)
        X["model_idx"] = pd.Categorical(X["model_idx"], categories=list(range(len(MODELS))))
        c = self.models[var].predict(X, pred_contrib=True)
        return pd.DataFrame(c, columns=BASE_FEATS + ["bias"], index=long_rows.index)

    def weights(self, var: str, pred_err: np.ndarray) -> np.ndarray:
        return softmax_weights(pred_err, self.tau[var])
