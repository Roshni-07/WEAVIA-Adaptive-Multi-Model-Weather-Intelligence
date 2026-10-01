"""Synthetic atmosphere + synthetic forecast models (development / pipeline validation only).

Truth  : 6-hourly temp / rain / wind / rh / pressure for 20 Indian locations with monsoon
         seasonality, diurnal cycle, convective bursts, heat spells and cyclone episodes.
Models : truth + context-dependent error (see model_specs.py).

Everything returned is in CANONICAL units. Providers convert to *native* units/names/time
zones so the harmonisation layer is genuinely exercised.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from ..config import ALL_VARS, LEADS, MODELS, REGIMES, STEP_H
from ..locations import LOCATIONS, Location, season_of_month
from ..regime_labels import label_regime
from . import model_specs as ms


def _ar1(rng: np.random.Generator, n: int, phi: float) -> np.ndarray:
    eps = rng.standard_normal(n)
    x = np.empty(n)
    x[0] = eps[0]
    s = np.sqrt(1 - phi**2)
    for t in range(1, n):
        x[t] = phi * x[t - 1] + s * eps[t]
    return x


def _bump(doy: np.ndarray, peak: float, width: float) -> np.ndarray:
    d = np.abs(doy - peak)
    d = np.minimum(d, 365 - d)
    return np.exp(-((d / width) ** 2))


def _episodes(rng, times: pd.DatetimeIndex, per_year: float, dur: tuple[int, int],
              windows: list[tuple[int, int]]) -> np.ndarray:
    """Bell-shaped (0..1) episodes placed randomly inside day-of-year windows."""
    n = len(times)
    out = np.zeros(n)
    doy = times.dayofyear.values
    yrs = times.year.values
    for y in np.unique(yrs):
        k = rng.poisson(per_year)
        for _ in range(k):
            lo, hi = windows[rng.integers(len(windows))]
            cand = np.where((yrs == y) & (doy >= lo) & (doy <= hi))[0]
            if len(cand) == 0:
                continue
            s = int(rng.choice(cand))
            D = int(rng.integers(dur[0], dur[1] + 1))
            e = min(n, s + D)
            shape = np.sin(np.pi * (np.arange(e - s) + 0.5) / D) ** 1.5
            out[s:e] = np.maximum(out[s:e], shape)
    return out


class SyntheticWorld:
    def __init__(self, seed: int = 7, start: str = "2023-01-01", days: int = 731):
        self.seed = seed
        self.rng = np.random.default_rng(seed)
        self.times = pd.date_range(start, periods=days * (24 // STEP_H), freq=f"{STEP_H}h", tz="UTC")
        self.truth = self._simulate_truth()
        self.forecasts = self._simulate_forecasts()

    # ------------------------------------------------------------------ truth
    def _simulate_truth(self) -> pd.DataFrame:
        rng, times = self.rng, self.times
        n = len(times)
        doy = times.dayofyear.values.astype(float)
        hour = times.hour.values.astype(float)
        regions = sorted({l.region for l in LOCATIONS})
        z_reg = {r: _ar1(rng, n, 0.92) for r in regions}
        cyc_reg = {r: _episodes(rng, times, 2.2, (8, 16), [(100, 160), (280, 340)]) for r in regions}
        heat_reg = {r: _episodes(rng, times, 3.0, (12, 28), [(85, 175)]) * rng.uniform(3.5, 7.0) for r in regions}

        frames = []
        for loc in LOCATIONS:
            m = loc.monsoon * _bump(doy, loc.m_peak, loc.m_width)
            z = np.sqrt(0.6) * z_reg[loc.region] + np.sqrt(0.4) * _ar1(rng, n, 0.9)
            p_burst = 0.004 + 0.022 * m
            shock = (rng.random(n) < p_burst) * (1 + rng.exponential(1.0, n))
            burst = np.zeros(n)
            for t in range(n):
                burst[t] = (burst[t - 1] * 0.5 if t else 0.0) + shock[t]
            cyc = cyc_reg[loc.region] * (rng.uniform(0.6, 1.0) if loc.coastal else 0.0)
            heat = heat_reg[loc.region] * (1.0 if loc.region in ("NORTH", "CENTRAL") else 0.25) * (1 if loc.id != "sxr" else 0.4)
            inst = z + 1.2 * burst

            lh = (hour + 5.5) % 24
            diur = np.cos(2 * np.pi * (lh - 14) / 24)
            temp = (loc.t_mean + loc.t_amp * np.sin(2 * np.pi * (doy - 110) / 365) - 4.0 * m
                    + (5.5 - 3.0 * m) * diur - 1.0 * np.maximum(inst, 0) * (0.5 + m)
                    + heat - 2.0 * cyc + 0.6 * _ar1(rng, n, 0.85))
            rh = np.clip(52 + 30 * m + 9 * z + 12 * burst + 8 * cyc - 6 * diur * (1 - 0.5 * m)
                         - 1.2 * heat + rng.normal(0, 2.5, n), 8, 100)
            pressure = (1008 - 3 * m - 2.0 * z - 1.5 * burst - 14 * cyc + 1.0 * _ar1(rng, n, 0.9))
            lam = 1 / (1 + np.exp(-(-2.2 + 1.1 * inst + 2.2 * m + 2.5 * cyc)))
            scale = loc.rain_scale * (0.6 + 1.5 * m) * (1 + 1.2 * np.maximum(burst, 0) + 3 * cyc)
            amt = rng.gamma(0.9, scale)
            rain = np.where(rng.random(n) < lam, amt, 0.0)
            rh = np.clip(rh + 0.35 * np.minimum(rain, 30), 8, 100)
            wind = (loc.wind_scale * (1 + 0.25 * m) * rng.weibull(2.0, n) * 0.85
                    + 3 * np.maximum(inst, 0) + 40 * cyc + 9 * np.maximum(burst, 0))
            frames.append(pd.DataFrame({
                "time": times, "location_id": loc.id, "temp": temp, "rain": rain, "wind": wind,
                "rh": rh, "pressure": pressure}))
        df = pd.concat(frames, ignore_index=True)
        df["regime"] = label_regime(df)
        return df

    # -------------------------------------------------------------- forecasts
    def _simulate_forecasts(self) -> dict[str, pd.DataFrame]:
        rng = np.random.default_rng(self.seed + 1)
        n = len(self.times)
        k_per_day = 24 // STEP_H
        issues = np.arange(0, n - max(LEADS) // STEP_H, k_per_day)
        reg_code = {r: i for i, r in enumerate(REGIMES)}
        out: dict[str, list[pd.DataFrame]] = {m: [] for m in MODELS}

        for loc in LOCATIONS:
            td = self.truth[self.truth.location_id == loc.id].reset_index(drop=True)
            tv = {v: td[v].values for v in ALL_VARS}
            rcode = td["regime"].map(reg_code).values
            months = td["time"].dt.month.values
            seasons = np.array([season_of_month(int(m)) for m in months])
            for lead in LEADS:
                k = lead // STEP_H
                vidx = issues + k
                lead_days = lead / 24.0
                rc = rcode[vidx]
                sea = seasons[vidx]
                truth_v = {v: tv[v][vidx] for v in ALL_VARS}
                common = {v: rng.standard_normal(len(issues)) for v in ("rain", "temp", "wind")}
                for mid in MODELS:
                    cols = {}
                    rmult = np.array([ms.REGIME_MULT[mid][r] for r in REGIMES])[rc]
                    smult = np.array([ms.SEASON_MULT[mid][s] for s in sea])
                    gmult = ms.REGION_MULT[mid].get(loc.region, 1.0)
                    for var in ("temp", "wind", "rain"):
                        sd = ms.SD0[var][mid] * (1 + ms.GROWTH[var][mid] * lead_days) * rmult * smult * gmult
                        eps = np.sqrt(ms.COMMON_RHO) * common[var] + np.sqrt(1 - ms.COMMON_RHO) * rng.standard_normal(len(issues))
                        bias_tab = ms.REGIME_BIAS[var][mid]
                        bias = np.array([bias_tab.get(r, 0.0) for r in REGIMES])[rc]
                        t = truth_v[var]
                        if var == "temp":
                            f = t + bias + sd * eps
                        elif var == "wind":
                            f = np.clip(t + bias + sd * eps * (0.6 + 0.03 * t), 0.0, 350.0)
                        else:
                            wet = t > 0
                            mult = np.exp(bias + sd * eps)
                            p_miss = 0.04 + 0.03 * lead_days
                            p_fa = 0.05 + 0.03 * lead_days
                            fa = (rng.random(len(t)) < p_fa) * rng.exponential(1.5, len(t))
                            f = np.minimum(350.0, np.where(wet, np.where(rng.random(len(t)) < p_miss, 0.0, t * mult), fa))
                        cols[var] = f
                    cols["rh"] = np.clip(truth_v["rh"] + rng.normal(0, ms.CTX_SD["rh"] * (1 + 0.3 * lead_days), len(issues)), 0, 100)
                    cols["pressure"] = truth_v["pressure"] + rng.normal(0, ms.CTX_SD["pressure"] * (1 + 0.3 * lead_days), len(issues))
                    itimes = self.times[issues]
                    vtimes = self.times[vidx]
                    for var, vals in cols.items():
                        out[mid].append(pd.DataFrame({
                            "issue_time": itimes, "valid_time": vtimes, "lead_h": lead,
                            "location_id": loc.id, "variable": var, "value": vals}))
        return {m: pd.concat(v, ignore_index=True) for m, v in out.items()}

    # ------------------------------------------------------------------ views
    def observations(self) -> pd.DataFrame:
        """Canonical long-form observations."""
        t = self.truth
        long = t.melt(id_vars=["time", "location_id"], value_vars=ALL_VARS, var_name="variable", value_name="value")
        long = long.rename(columns={"time": "timestamp"})
        long["source"] = "synthetic-truth"
        return long

    def regime_obs(self) -> pd.DataFrame:
        return self.truth[["time", "location_id", "regime"]].rename(columns={"time": "valid_time", "regime": "obs_regime"})
