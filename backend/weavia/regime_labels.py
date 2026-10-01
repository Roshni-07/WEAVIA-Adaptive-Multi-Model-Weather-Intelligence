"""Observation-derived regime labels.

Regimes are *defined* from what actually happened (observed / reanalysis fields) using
transparent thresholds. The same function is used on synthetic truth and on real
observations (e.g. ERA5). A supervised classifier (regime.py) then learns to predict
these labels from information available at forecast time.
"""
from __future__ import annotations
import numpy as np
import pandas as pd

from .config import REGIMES

RAIN_HEAVY = 20.0      # mm / 6 h
RAIN_CONV = 5.0
WIND_HIGH = 25.0       # km/h
HEAT_ANOM = 4.0        # degC above location-month climatology
HEAT_ABS = 35.0
CYC_P = 999.0          # hPa
CYC_W = 25.0
TRANS_DP = 3.0         # hPa per 12 h
TRANS_DT = 5.0         # degC per 24 h


def label_regime(df: pd.DataFrame) -> np.ndarray:
    """df: one location's (or many locations') time-ordered obs with columns
    time, location_id, temp, rain, wind, rh, pressure. Returns array of regime names."""
    d = df.copy()
    d["month"] = d["time"].dt.month
    clim = d.groupby(["location_id", "month"])["temp"].transform("mean")
    g = d.groupby("location_id")
    dP = (d["pressure"] - g["pressure"].shift(2)).fillna(0.0).abs()
    dT = (d["temp"] - g["temp"].shift(4)).fillna(0.0).abs()
    conds = [
        (d["pressure"] < CYC_P) & (d["wind"] >= CYC_W),
        d["rain"] >= RAIN_HEAVY,
        d["wind"] >= WIND_HIGH,
        ((d["temp"] - clim) >= HEAT_ANOM) & (d["temp"] >= HEAT_ABS),
        (d["rain"] >= RAIN_CONV) & (d["rh"] >= 70),
        (dP >= TRANS_DP) | (dT >= TRANS_DT),
        (d["rain"] < 0.1) & (d["rh"] < 40),
    ]
    choices = ["CYCLONIC", "HEAVY_RAIN", "HIGH_WIND", "HEAT", "CONVECTIVE", "TRANSITION", "DRY"]
    out = np.select([c.values for c in conds], choices, default="NORMAL")
    assert set(out) <= set(REGIMES)
    return out
