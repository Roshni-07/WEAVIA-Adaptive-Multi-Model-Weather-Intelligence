"""Uncertainty from model disagreement, calibrated on held-out residuals.

z = (obs - blend) / (weighted_spread + floor). Empirical quantiles/CDF of z per (variable, lead) on the
validation slice give P10/P50/P90, a confidence = P(|error| <= tol), and exceedance probabilities.
Everything is reported with realised coverage on the untouched test slice (verify.py).
"""
from __future__ import annotations

import numpy as np

from .config import EVENT_THRESH, LEADS, SPREAD_FLOOR, tolerance


def weighted_spread(F: np.ndarray, w: np.ndarray) -> np.ndarray:
    mu = (w * F).sum(1, keepdims=True)
    return np.sqrt((w * (F - mu) ** 2).sum(1))


class UncertaintyCalibrator:
    def __init__(self):
        self.q: dict = {}
        self.z_sorted: dict = {}
        self.absz_sorted: dict = {}

    def fit(self, var: str, lead: np.ndarray, blend: np.ndarray, spread: np.ndarray, obs: np.ndarray):
        c = SPREAD_FLOOR[var]
        z = (obs - blend) / (spread + c)
        for L in LEADS:
            zz = z[lead == L]
            if len(zz) < 50:
                zz = z
            self.q[(var, L)] = tuple(np.quantile(zz, [0.1, 0.5, 0.9]))
            self.z_sorted[(var, L)] = np.sort(zz)
            self.absz_sorted[(var, L)] = np.sort(np.abs(zz))

    def apply(self, var: str, lead: np.ndarray, blend: np.ndarray, spread: np.ndarray):
        c = SPREAD_FLOOR[var]
        scale = spread + c
        p10, p50, p90, conf, pev = (np.zeros(len(blend)) for _ in range(5))
        thr = EVENT_THRESH[var]
        tol = tolerance(var, blend)
        for L in LEADS:
            m = lead == L
            if not m.any():
                continue
            q10, q50, q90 = self.q[(var, L)]
            p10[m] = blend[m] + q10 * scale[m]
            p50[m] = blend[m] + q50 * scale[m]
            p90[m] = blend[m] + q90 * scale[m]
            a = self.absz_sorted[(var, L)]
            conf[m] = np.searchsorted(a, tol[m] / scale[m], side="right") / len(a)
            zs = self.z_sorted[(var, L)]
            x = (thr - blend[m]) / scale[m]
            pev[m] = 1.0 - np.searchsorted(zs, x, side="right") / len(zs)
        if var in ("rain", "wind"):
            p10, p50, p90 = (np.maximum(a, 0.0) for a in (p10, p50, p90))
        return p10, p50, p90, conf, pev
