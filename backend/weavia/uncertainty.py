"""Uncertainty calibrated on verified residuals.

Rain (zero-inflated, heavy-tailed): residuals are taken on the log1p scale,
    r = log1p(obs) - log1p(blend),
and calibrated per (variable, lead, blend-level bin). Binning by forecast level is what lets a
"dry" forecast get a (near) point interval while a wet forecast gets a wide, skewed one; pooling
them, as a single normalised-residual quantile does, collapses the rain interval to ~zero width.
P10/P50/P90 are back-transformed with expm1; confidence = P(|error| <= tol) and exceedance
probabilities come from the same conditional residual distribution.

Temperature / wind: z = (obs - blend) / (weighted_spread + floor), empirical quantiles per lead.

The calibration slice must contain every season. A chronological validation block can miss one
entirely (the synthetic validation block has no monsoon), so the pipeline fits on train + validation.
Realised coverage is always verified on the untouched test slice (verify.py), reported both overall
and for "wet" forecasts, because an overall figure is inflated by trivially covered dry cases.
"""
from __future__ import annotations

import numpy as np

from .config import EVENT_THRESH, LEADS, SPREAD_FLOOR, tolerance

RAIN_EDGES = np.array([0.05, 0.5, 2.0, 8.0])   # forecast mm/6h bin edges: dry | trace | light | moderate | heavy
N_RAIN_BINS = len(RAIN_EDGES) + 1
MIN_CELL = 100                                  # smallest cell trusted before pooling over leads / bins


def rain_bin(blend: np.ndarray) -> np.ndarray:
    return np.digitize(blend, RAIN_EDGES)


def weighted_spread(F: np.ndarray, w: np.ndarray) -> np.ndarray:
    mu = (w * F).sum(1, keepdims=True)
    return np.sqrt((w * (F - mu) ** 2).sum(1))


class UncertaintyCalibrator:
    def __init__(self):
        self.q: dict = {}
        self.z_sorted: dict = {}
        self.absz_sorted: dict = {}
        self.r_cells: dict = {}      # rain: (lead|None, bin|None) -> sorted log1p residuals

    # ------------------------------------------------------------------ fit
    def fit(self, var: str, lead: np.ndarray, blend: np.ndarray, spread: np.ndarray, obs: np.ndarray):
        ok = np.isfinite(blend) & np.isfinite(spread) & np.isfinite(obs)    # never calibrate on gaps
        if not ok.all():
            lead, blend, spread, obs = lead[ok], blend[ok], spread[ok], obs[ok]
        if var == "rain":
            return self._fit_rain(lead, blend, obs)
        c = SPREAD_FLOOR[var]
        z = (obs - blend) / (spread + c)
        for L in LEADS:
            zz = z[lead == L]
            if len(zz) < 50:
                zz = z
            self.q[(var, L)] = tuple(np.quantile(zz, [0.1, 0.5, 0.9]))
            self.z_sorted[(var, L)] = np.sort(zz)
            self.absz_sorted[(var, L)] = np.sort(np.abs(zz))

    def _fit_rain(self, lead, blend, obs):
        r = np.log1p(obs) - np.log1p(blend)
        bi = rain_bin(blend)
        cells = {}
        for L in LEADS + [None]:
            for k in list(range(N_RAIN_BINS)) + [None]:
                m = np.ones(len(r), bool)
                if L is not None:
                    m &= lead == L
                if k is not None:
                    m &= bi == k
                cells[(L, k)] = np.sort(r[m])
        self.r_cells = cells

    def _cell(self, L: int, k: int) -> np.ndarray:
        for key in ((L, k), (None, k), (L, None), (None, None)):
            a = self.r_cells.get(key)
            if a is not None and len(a) >= MIN_CELL:
                return a
        return self.r_cells[(None, None)]

    # ------------------------------------------------------------------ apply
    def apply(self, var: str, lead: np.ndarray, blend: np.ndarray, spread: np.ndarray):
        if var == "rain":
            return self._apply_rain(lead, blend)
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
        if var == "wind":
            p10, p50, p90 = (np.maximum(a, 0.0) for a in (p10, p50, p90))
        return p10, p50, p90, conf, pev

    def _apply_rain(self, lead, blend):
        n = len(blend)
        p10, p50, p90, conf, pev = (np.zeros(n) for _ in range(5))
        tb = np.log1p(blend)
        bi = rain_bin(blend)
        tol = tolerance("rain", blend)
        lt = np.log1p(EVENT_THRESH["rain"])
        for L in LEADS:
            for k in range(N_RAIN_BINS):
                m = (lead == L) & (bi == k)
                if not m.any():
                    continue
                a = self._cell(L, k)
                q10, q50, q90 = np.quantile(a, [0.1, 0.5, 0.9])
                p10[m] = np.expm1(tb[m] + q10)
                p50[m] = np.expm1(tb[m] + q50)
                p90[m] = np.expm1(tb[m] + q90)
                # no lower constraint when blend - tol <= 0: rain cannot be negative, so every residual below is a hit
                lo = np.where(blend[m] - tol[m] <= 0.0, -np.inf, np.log1p(np.maximum(blend[m] - tol[m], 0.0)) - tb[m])
                hi = np.log1p(blend[m] + tol[m]) - tb[m]
                conf[m] = (np.searchsorted(a, hi, side="right") - np.searchsorted(a, lo, side="left")) / len(a)
                pev[m] = 1.0 - np.searchsorted(a, lt - tb[m], side="left") / len(a)
        p10, p50, p90 = (np.maximum(x, 0.0) for x in (p10, p50, p90))
        return p10, p50, p90, conf, pev
