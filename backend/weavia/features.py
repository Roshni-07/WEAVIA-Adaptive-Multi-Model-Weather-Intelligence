"""Build the wide 'cases' table (one row per issue x location x lead) and model-error memory."""
from __future__ import annotations

import numpy as np
import pandas as pd

from .config import ALL_VARS, BLEND_VARS, LEADS, MODELS, RECENT_WINDOW, REGIMES, SPLIT_FRACS
from .locations import LOC_BY_ID, REGION_LIST, season_of_month


def assign_split(cx: pd.DataFrame) -> pd.DataFrame:
    dates = np.sort(cx["issue_time"].unique())
    n = len(dates)
    a = int(n * SPLIT_FRACS[0])
    b = int(n * (SPLIT_FRACS[0] + SPLIT_FRACS[1]))
    cut_a, cut_b = dates[a], dates[b]
    cx["split"] = np.where(cx["issue_time"] < cut_a, "train", np.where(cx["issue_time"] < cut_b, "val", "test"))
    return cx


def build_cases(fc_long: pd.DataFrame, obs_long: pd.DataFrame, regime_obs: pd.DataFrame) -> pd.DataFrame:
    piv = fc_long.pivot_table(index=["issue_time", "location_id", "lead_h", "valid_time"],
                              columns=["variable", "model_id"], values="value", aggfunc="first")
    piv.columns = [f"f_{v}_{m}" for v, m in piv.columns]
    cx = piv.reset_index()

    obs = obs_long.pivot_table(index=["timestamp", "location_id"], columns="variable", values="value", aggfunc="first").reset_index()
    o_valid = obs.rename(columns={"timestamp": "valid_time", **{v: f"obs_{v}" for v in ALL_VARS}})
    cx = cx.merge(o_valid, on=["valid_time", "location_id"], how="left")
    o_issue = obs.rename(columns={"timestamp": "issue_time", "temp": "obsi_temp", "pressure": "obsi_pressure"})
    cx = cx.merge(o_issue[["issue_time", "location_id", "obsi_temp", "obsi_pressure"]], on=["issue_time", "location_id"], how="left")
    cx = cx.merge(regime_obs, on=["valid_time", "location_id"], how="left")

    for v in ALL_VARS:
        cols = [f"f_{v}_{m}" for m in MODELS]
        cx[f"ens_{v}"] = cx[cols].mean(axis=1)
        cx[f"spr_{v}"] = cx[cols].std(axis=1, ddof=0)
    cx["lat"] = cx.location_id.map(lambda i: LOC_BY_ID[i].lat)
    cx["lon"] = cx.location_id.map(lambda i: LOC_BY_ID[i].lon)
    cx["region"] = cx.location_id.map(lambda i: LOC_BY_ID[i].region)
    cx["region_code"] = cx.region.map({r: i for i, r in enumerate(REGION_LIST)})
    cx["month"] = cx["valid_time"].dt.month
    cx["season"] = cx["month"].map(season_of_month)
    cx["m_sin"] = np.sin(2 * np.pi * cx["month"] / 12)
    cx["m_cos"] = np.cos(2 * np.pi * cx["month"] / 12)
    cx["dT"] = cx["ens_temp"] - cx["obsi_temp"]
    cx["dP"] = cx["ens_pressure"] - cx["obsi_pressure"]
    cx = cx.dropna(subset=[f"obs_{v}" for v in BLEND_VARS]).copy()
    cx = cx.sort_values(["location_id", "lead_h", "issue_time"]).reset_index(drop=True)
    cx = assign_split(cx)
    cx = add_error_memory(cx)
    cx["case_id"] = np.arange(len(cx))
    return cx


def add_error_memory(cx: pd.DataFrame) -> pd.DataFrame:
    """Leakage-safe model memory. For a forecast issued at t with lead L, only errors of
    forecasts whose valid time <= t are visible (shift by max(1, L//24) daily issues)."""
    new = {}
    for var in BLEND_VARS:
        for m in MODELS:
            err = cx[f"f_{var}_{m}"] - cx[f"obs_{var}"]
            ae = err.abs()
            keys = {k: np.full(len(cx), np.nan) for k in ("hist", "rec", "histb", "recb")}
            for lead in LEADS:
                lag = max(1, lead // 24)
                idx = np.where(cx.lead_h.values == lead)[0]
                sub = pd.DataFrame({"loc": cx.location_id.values[idx], "ae": ae.values[idx], "se": err.values[idx]})
                g = sub.groupby("loc")
                sub["ae_l"] = g["ae"].shift(lag)
                sub["se_l"] = g["se"].shift(lag)
                g = sub.groupby("loc")
                keys["hist"][idx] = g["ae_l"].transform(lambda s: s.expanding(min_periods=5).mean()).values
                keys["rec"][idx] = g["ae_l"].transform(lambda s: s.rolling(RECENT_WINDOW, min_periods=3).mean()).values
                keys["histb"][idx] = g["se_l"].transform(lambda s: s.expanding(min_periods=5).mean()).values
                keys["recb"][idx] = g["se_l"].transform(lambda s: s.rolling(RECENT_WINDOW, min_periods=3).mean()).values
            for k, arr in keys.items():
                new[f"{k}_{var}_{m}"] = arr
    return pd.concat([cx, pd.DataFrame(new, index=cx.index)], axis=1)
