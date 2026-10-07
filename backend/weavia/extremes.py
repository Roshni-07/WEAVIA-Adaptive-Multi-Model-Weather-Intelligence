"""Daily extreme-weather products aligned with IMD definitions.

Products (per station, valid day, lead day):
  tmax    daily maximum temperature (IST calendar day) and the IMD heat-wave INDICATOR built on it
  rain24  IMD-day rainfall (24 h ending 08:30 IST) and its IMD class / heavy-rain probability

How the daily blend works. Per-model daily values come from the provider's hourly responses. The model weights
are the ones WEAVIA's trust engine assigned to the 6-hourly case of the same station and lead nearest in time to
the day's midpoint (temperature weights for tmax, rain weights for rain24). So the daily products inherit the
context-aware weights instead of re-learning them from scratch. Uncertainty comes from empirical residuals of the
blended daily value on the calibration days. Heat-wave probability is P(tmax >= the value at which the IMD
criterion starts to hold for that station and day), which makes it exact for the departure and absolute rules.

Honest limits:
  * Indicator, not an IMD declaration. Normals are reanalysis-based, not IMD's gridded normals.
  * Station groups for the persistence rule are WEAVIA's coarse regions, not IMD sub-divisions.
  * Live (single-run) and back-test (day-offset) daily values differ slightly in lead definition.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from . import imd_criteria as imd
from .locations import LOC_BY_ID
from .verify import _bootstrap

SRC_VAR = {"tmax": "temp", "rain24": "rain"}
RAIN_EDGES = np.array([0.5, 5.0, 25.0, imd.HEAVY_RAIN_24H_MM])
MIN_CELL = 100
MIN_EVENTS = 30          # station-days
MIN_EVENT_DAYS = 5       # distinct dates
SPLIT_FRACS = (0.60, 0.15)


def assign_splits(days: pd.Series) -> pd.Series:
    """Chronological train/val/test by valid day (same 60/15/25 as the pipeline)."""
    u = np.sort(days.unique())
    a, b = u[int(len(u) * SPLIT_FRACS[0])], u[int(len(u) * (SPLIT_FRACS[0] + SPLIT_FRACS[1]))]
    return pd.Series(np.where(days < a, "train", np.where(days < b, "val", "test")), index=days.index)


# ------------------------------------------------------------------------------------------------ blending
def _midpoint(variable: str, days: pd.Series) -> pd.Series:
    d = pd.to_datetime(days).dt.normalize()
    off = pd.Timedelta(hours=6, minutes=30) if variable == "tmax" else -pd.Timedelta(hours=9)   # IST noon / IMD-day middle
    return (d + off).dt.tz_localize("UTC")


def daily_blend(daily_fc: pd.DataFrame, blend: pd.DataFrame, models: list[str], missing: tuple[str, ...] = ()) -> pd.DataFrame:
    """Blend per-model daily values with the matching 6-hourly case weights.

    daily_fc: model_id, valid_day, lead_day, location_id, variable, value. blend: WEAVIA 6-hourly output with
    w_<model> columns. Models in `missing` are imputed (mean of the others) and carry the weight WEAVIA gave them
    (zero in a degraded live cycle)."""
    out = []
    for var, src in SRC_VAR.items():
        d = daily_fc[daily_fc.variable == var]
        if d.empty:
            continue
        wide = d.pivot_table(index=["valid_day", "lead_day", "location_id"], columns="model_id", values="value", aggfunc="first")
        for m in missing:
            wide[m] = wide[[c for c in models if c not in missing and c in wide]].mean(axis=1)
        wide = wide[[m for m in models if m in wide]].dropna().reset_index()
        if wide.empty:
            continue
        wide["lead_h"] = (wide.lead_day * 24).astype("int64")
        wide["mid"] = _midpoint(var, wide.valid_day)
        wide = wide.sort_values("mid")
        b = blend[blend.variable == src][["location_id", "lead_h", "valid_time", "issue_time"] + [f"w_{m}" for m in models]].copy()
        b["valid_time"] = pd.to_datetime(b.valid_time, utc=True)
        b["lead_h"] = b.lead_h.astype("int64")
        b = b.sort_values("valid_time")
        m_ = pd.merge_asof(wide, b, left_on="mid", right_on="valid_time", by=["location_id", "lead_h"],
                           direction="nearest", tolerance=pd.Timedelta(hours=12))
        m_ = m_.dropna(subset=[f"w_{m}" for m in models]).copy()
        F = m_[models].to_numpy(float)
        W = m_[[f"w_{m}" for m in models]].to_numpy(float)
        W = W / W.sum(1, keepdims=True)
        m_["variable"] = var
        m_["blend"] = (W * F).sum(1)
        m_["equal"] = F.mean(1)
        m_ = m_.rename(columns={m: f"f_{m}" for m in models}).drop(columns=["mid", "valid_time", "lead_h"])
        out.append(m_)
    if not out:
        return pd.DataFrame()
    r = pd.concat(out, ignore_index=True)
    r["valid_day"] = pd.to_datetime(r.valid_day)
    return r


def attach_truth(df: pd.DataFrame, truth_daily: pd.DataFrame | None) -> pd.DataFrame:
    df = df.copy()
    if truth_daily is None or truth_daily.empty:
        df["obs"] = np.nan
        return df
    t = truth_daily.rename(columns={"value": "obs"}).copy()
    t["valid_day"] = pd.to_datetime(t.valid_day)
    return df.merge(t[["valid_day", "location_id", "variable", "obs"]], on=["valid_day", "location_id", "variable"], how="left")


def normal_lookup(normals: pd.DataFrame, location_ids, days) -> np.ndarray:
    idx = normals.set_index(["location_id", "doy"]).normal_tmax
    key = list(zip(location_ids, pd.to_datetime(pd.Series(days)).dt.dayofyear))
    return idx.reindex(pd.MultiIndex.from_tuples(key, names=["location_id", "doy"])).to_numpy(float)


# ------------------------------------------------------------------------------------------------ uncertainty
class DailyBands:
    """Empirical residual distributions. tmax: additive, per lead day. rain24: on log1p, per lead day and forecast level."""

    def __init__(self):
        self.cells: dict = {}

    @staticmethod
    def _bin(x):
        return np.digitize(x, RAIN_EDGES)

    def fit(self, df: pd.DataFrame) -> "DailyBands":
        df = df.dropna(subset=["obs", "blend"])
        for var in ("tmax", "rain24"):
            d = df[df.variable == var]
            if d.empty:
                continue
            r = d.obs.values - d.blend.values if var == "tmax" else np.log1p(d.obs.values) - np.log1p(d.blend.values)
            ks, bi = d.lead_day.values, (self._bin(d.blend.values) if var == "rain24" else np.zeros(len(d), int))
            nb = len(RAIN_EDGES) + 1 if var == "rain24" else 1
            for k in list(np.unique(ks)) + [None]:
                for b in list(range(nb)) + [None]:
                    m = np.ones(len(d), bool)
                    if k is not None:
                        m &= ks == k
                    if b is not None:
                        m &= bi == b
                    self.cells[(var, k, b)] = np.sort(r[m])
        return self

    def _cell(self, var, k, b) -> np.ndarray:
        for key in ((var, k, b), (var, None, b), (var, k, None), (var, None, None)):
            a = self.cells.get(key)
            if a is not None and len(a) >= MIN_CELL:
                return a
        a = self.cells.get((var, None, None))
        if a is None or len(a) == 0:
            raise ValueError(f"no calibration data for {var}")
        return a

    def _each(self, var, k, blend):
        blend = np.asarray(blend, float)
        k = np.broadcast_to(np.asarray(k), blend.shape)
        bi = self._bin(blend) if var == "rain24" else np.zeros(len(blend), int)
        for kk in np.unique(k):
            for b in np.unique(bi):
                m = (k == kk) & (bi == b)
                yield m, self._cell(var, int(kk), int(b) if var == "rain24" else None)

    def prob_ge(self, var: str, k, blend, thr) -> np.ndarray:
        """P(true value >= thr). thr may be scalar or per-row."""
        blend = np.asarray(blend, float)
        thr = np.broadcast_to(np.asarray(thr, float), blend.shape)
        p = np.zeros(len(blend))
        for m, a in self._each(var, k, blend):
            need = (thr[m] - blend[m]) if var == "tmax" else (np.log1p(thr[m]) - np.log1p(blend[m]))
            p[m] = 1.0 - np.searchsorted(a, need, side="left") / len(a)
        return np.clip(p, 0.0, 1.0)

    def interval(self, var: str, k, blend, lo=0.1, hi=0.9):
        blend = np.asarray(blend, float)
        p_lo, p_hi = np.zeros(len(blend)), np.zeros(len(blend))
        for m, a in self._each(var, k, blend):
            ql, qh = np.quantile(a, [lo, hi])
            if var == "tmax":
                p_lo[m], p_hi[m] = blend[m] + ql, blend[m] + qh
            else:
                p_lo[m], p_hi[m] = np.maximum(np.expm1(np.log1p(blend[m]) + ql), 0.0), np.expm1(np.log1p(blend[m]) + qh)
        return p_lo, p_hi


# ------------------------------------------------------------------------------------------------ indicators
def add_indicators(df: pd.DataFrame, normals: pd.DataFrame, bands: DailyBands) -> pd.DataFrame:
    """Add IMD-aligned classes and probabilities. Output columns: normal, terrain, p10, p90, cls_blend, cls_equal,
    cls_obs (heat-wave class 0/1/2), p_event (P heat wave / P heavy rain), p_severe (P severe / P very heavy), rain_class."""
    df = df.copy()
    n = len(df)
    for c in ("normal", "p10", "p90", "p_event", "p_severe", "cls_blend", "cls_equal", "cls_obs"):
        df[c] = np.nan
    df["terrain"], df["rain_class"] = None, None
    t = (df.variable == "tmax").to_numpy()
    if t.any():
        sub = df[t]
        terr = np.array([LOC_BY_ID[l].terrain for l in sub.location_id], dtype=object)
        normal = normal_lookup(normals, sub.location_id.values, sub.valid_day.values)
        k = sub.lead_day.values
        b = sub.blend.values
        thr, thr_s = imd.heat_wave_threshold(normal, terr), imd.heat_wave_threshold(normal, terr, severe=True)
        p10, p90 = bands.interval("tmax", k, b)
        df.loc[t, "normal"], df.loc[t, "terrain"] = normal, terr
        df.loc[t, "p10"], df.loc[t, "p90"] = p10, p90
        df.loc[t, "p_event"] = bands.prob_ge("tmax", k, b, thr)
        df.loc[t, "p_severe"] = bands.prob_ge("tmax", k, b, thr_s)
        ok = ~np.isnan(normal)
        for col, vals in (("cls_blend", b), ("cls_equal", sub.equal.values), ("cls_obs", sub.obs.values)):
            cls = np.full(len(sub), np.nan)
            good = ok & ~np.isnan(vals)
            cls[good] = imd.heat_wave_class(vals[good], normal[good], terr[good])
            df.loc[t, col] = cls
    r = (df.variable == "rain24").to_numpy()
    if r.any():
        sub = df[r]
        k, b = sub.lead_day.values, sub.blend.values
        p10, p90 = bands.interval("rain24", k, b)
        df.loc[r, "p10"], df.loc[r, "p90"] = p10, p90
        df.loc[r, "p_event"] = bands.prob_ge("rain24", k, b, imd.HEAVY_RAIN_24H_MM)
        df.loc[r, "p_severe"] = bands.prob_ge("rain24", k, b, imd.VERY_HEAVY_RAIN_24H_MM)
        df.loc[r, "rain_class"] = imd.rain_class(b)
        # observed / equal-ensemble heavy-rain flags reuse the cls_* columns: 1 if >= 64.5 mm
        for col, vals in (("cls_blend", b), ("cls_equal", sub.equal.values), ("cls_obs", sub.obs.values)):
            cls = np.where(np.isnan(vals), np.nan, (vals >= imd.HEAVY_RAIN_24H_MM).astype(float))
            df.loc[r, col] = cls
    return df


# ------------------------------------------------------------------------------------------------ verification
def _f1(tp, fp, fn):
    d = 2 * tp + fp + fn
    return np.where(d > 0, 2 * tp / np.where(d > 0, d, 1), np.nan)


def _event_block(d: pd.DataFrame, n_boot: int, seed: int) -> dict:
    """Event skill by date-block bootstrap. d needs valid_day, cls_obs, cls_blend, cls_equal and individual f_* classes."""
    d = d.dropna(subset=["cls_obs", "cls_blend", "cls_equal"])
    obs = (d.cls_obs >= 1).to_numpy()
    n_ev, n_days = int(obs.sum()), int(d.loc[obs, "valid_day"].nunique())
    out = {"n_cases": int(len(d)), "n_obs_events": n_ev, "n_event_days": n_days,
           "insufficient_events": bool(n_ev < MIN_EVENTS or n_days < MIN_EVENT_DAYS)}
    if len(d) == 0:
        return out
    dates = d.valid_day.to_numpy()
    uniq, inv = np.unique(dates, return_inverse=True)
    rng = np.random.default_rng(seed)
    idx = rng.integers(0, len(uniq), (n_boot, len(uniq)))
    res = {}
    for name, col in (("weavia", "cls_blend"), ("equal", "cls_equal")):
        pred = (d[col] >= 1).to_numpy()
        tp = np.bincount(inv, weights=(pred & obs), minlength=len(uniq))
        fp = np.bincount(inv, weights=(pred & ~obs), minlength=len(uniq))
        fn = np.bincount(inv, weights=(~pred & obs), minlength=len(uniq))
        tps, fps, fns = tp.sum(), fp.sum(), fn.sum()
        res[name] = {"precision": float(tps / (tps + fps)) if tps + fps else None, "recall": float(tps / (tps + fns)) if tps + fns else None,
                     "f1": float(_f1(tps, fps, fns)), "tp": int(tps), "fp": int(fps), "fn": int(fns),
                     "_boot": _f1(tp[idx].sum(1), fp[idx].sum(1), fn[idx].sum(1))}
    diff = res["weavia"]["_boot"] - res["equal"]["_boot"]
    diff = diff[~np.isnan(diff)]
    out["methods"] = {k: {kk: vv for kk, vv in v.items() if kk != "_boot"} for k, v in res.items()}
    if len(diff):
        lo, hi = float(np.quantile(diff, 0.025)), float(np.quantile(diff, 0.975))
        out["f1_gain_vs_equal"] = {"value": float(res["weavia"]["f1"] - res["equal"]["f1"]), "ci95": [lo, hi],
                                   "significant": bool(lo > 0 and not out["insufficient_events"])}
    return out


def jsonable(o):
    """Recursively make a result JSON-safe: NaN and inf become None, numpy scalars become Python numbers."""
    if isinstance(o, dict):
        return {str(k): jsonable(v) for k, v in o.items()}
    if isinstance(o, (list, tuple)):
        return [jsonable(v) for v in o]
    if isinstance(o, (np.floating, float)):
        return None if not np.isfinite(o) else float(o)
    if isinstance(o, np.integer):
        return int(o)
    if isinstance(o, np.bool_):
        return bool(o)
    return o


def verify_daily(df: pd.DataFrame, models: list[str], n_boot: int = 2000, seed: int = 0) -> dict:
    """Held-out (test) verification of daily products with date-block bootstrap CIs. Never claims skill when events
    are too few or a CI includes zero."""
    d = df.dropna(subset=["obs"])
    train = d[d.split == "train"]
    test = d[d.split == "test"]
    res: dict = {"n_test_rows": int(len(test)), "mae": [], "heat_wave": None, "heavy_rain": None, "regional_heat_wave": None}
    for var in ("tmax", "rain24"):
        for k in sorted(test.lead_day.unique()):
            tt, tr = test[(test.variable == var) & (test.lead_day == k)], train[(train.variable == var) & (train.lead_day == k)]
            if tt.empty or tr.empty:
                continue
            best = min(models, key=lambda m: float((tr[f"f_{m}"] - tr.obs).abs().mean()))
            err = {"weavia": (tt.blend - tt.obs).abs(), "equal": (tt.equal - tt.obs).abs(), "best_single_train": (tt[f"f_{best}"] - tt.obs).abs()}
            for m in models:
                err[m] = (tt[f"f_{m}"] - tt.obs).abs()
            days = tt.valid_day.to_numpy()
            uniq, inv = np.unique(days, return_inverse=True)
            cnt = np.bincount(inv).astype(float)
            row = {"variable": var, "lead_day": int(k), "n": int(len(tt)), "best_single_train": best,
                   "mae": {n: float(e.mean()) for n, e in err.items()}, "vs": {}}
            for ref in ["equal", "best_single_train"] + models:
                sums = np.stack([np.bincount(inv, weights=err["weavia"].to_numpy()), np.bincount(inv, weights=err[ref].to_numpy())], 1)
                dr = _bootstrap(sums, cnt, B=n_boot, seed=seed)
                rel = -(dr[:, 0] - dr[:, 1]) / dr[:, 1]
                lo, hi = float(np.quantile(rel, 0.025)), float(np.quantile(rel, 0.975))
                pt = float(-(err["weavia"].mean() - err[ref].mean()) / err[ref].mean())
                row["vs"][ref] = {"improvement_pct": 100 * pt, "ci95_pct": [100 * lo, 100 * hi], "significant": bool(lo > 0)}
            res["mae"].append(row)
    for name, var in (("heat_wave", "tmax"), ("heavy_rain", "rain24")):
        tt = test[test.variable == var]
        if len(tt):
            res[name] = {int(k): _event_block(g, n_boot, seed) for k, g in tt.groupby("lead_day")}
    hw = test[test.variable == "tmax"].dropna(subset=["cls_obs", "cls_blend"])
    hw = hw[hw.lead_day == 1] if (hw.lead_day == 1).any() else hw[hw.lead_day == hw.lead_day.min()] if len(hw) else hw
    if len(hw):
        res["regional_heat_wave"] = regional_declarations(hw)
    return jsonable(res)


def regional_declarations(hw: pd.DataFrame) -> dict:
    """Apply IMD's persistence rule per WEAVIA region (a stand-in for IMD sub-divisions) to forecast and observed
    station flags, then count region-day hits, misses and false alarms."""
    hw = hw.assign(group=[LOC_BY_ID[l].region for l in hw.location_id], date=hw.valid_day)
    fc = imd_flags(hw, "cls_blend")
    ob = imd_flags(hw, "cls_obs")
    m = fc.merge(ob, on=["group", "date"], suffixes=("_fc", "_obs"))
    pf, po = m.declared_fc.to_numpy(), m.declared_obs.to_numpy()
    tp, fp, fn = int((pf & po).sum()), int((pf & ~po).sum()), int((~pf & po).sum())
    return {"group": "WEAVIA region (not IMD sub-division)", "n_region_days": int(len(m)), "observed_declared_days": int(po.sum()),
            "hits": tp, "false_alarms": fp, "misses": fn,
            "insufficient_events": bool(po.sum() < 5), "status": "indicator, not an IMD declaration"}


def imd_flags(hw: pd.DataFrame, col: str) -> pd.DataFrame:
    x = hw[["date", "location_id", "group", col]].rename(columns={"location_id": "station", col: "cls"}).copy()
    x["cls"] = x.cls.fillna(0).astype(int)
    r = imd.declare_heat_wave(x)
    return r[["group", "date", "declared"]]


def build_products(daily_fc, blend, models, truth_daily, normals, bands: DailyBands | None = None, missing=()):
    """daily_fc -> blended daily products (+ truth if given).

    Without `bands` (a fit): chronological splits, bands fitted on train + val rows.
    With `bands` (a live cycle): rows are split='live' and use the fitted bands unchanged."""
    df = daily_blend(daily_fc, blend, models, missing=missing)
    if df.empty:
        return df, bands
    df = attach_truth(df, truth_daily)
    if bands is None:
        df["split"] = assign_splits(df.valid_day)
        bands = DailyBands().fit(df[df.split.isin(["train", "val"])])
    else:
        df["split"] = "live"
    return add_indicators(df, normals, bands), bands


def regional_outlook(df: pd.DataFrame) -> list[dict]:
    """Heat-wave indicator by WEAVIA region for consecutive lead days of ONE issue (IMD persistence rule applied
    to forecast flags). df: live product rows for tmax."""
    t = df[(df.variable == "tmax")].dropna(subset=["cls_blend"])
    if t.empty:
        return []
    t = t.assign(group=[LOC_BY_ID[l].region for l in t.location_id], date=t.valid_day)
    r = imd.declare_heat_wave(t[["date", "location_id", "group", "cls_blend"]].rename(columns={"location_id": "station", "cls_blend": "cls"}).assign(cls=lambda x: x.cls.astype(int)))
    return [{"region": g, "date": f"{d:%Y-%m-%d}", "stations_meeting_criterion": int(n), "declared_indicator": bool(dec),
             "severe_indicator": bool(sv)} for g, d, n, dec, sv in zip(r.group, r.date, r.n_stations, r.declared, r.severe_declared)]
