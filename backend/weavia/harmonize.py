"""Forecast harmonisation layer: common units, UTC time, common variable names, common points.

Canonical schema (long):
    model_id | issue_time (UTC) | valid_time (UTC) | lead_h | location_id | variable | value
"""
from __future__ import annotations
from dataclasses import dataclass, field

import numpy as np
import pandas as pd
import xarray as xr

from .config import ALL_VARS, CANON_UNIT

# unit -> (to_canonical, from_canonical). Canonical units: see config.CANON_UNIT.
UNITS = {
    "mm/6h": (lambda x: x, lambda x: x),
    "mm/h": (lambda x: x * 6.0, lambda x: x / 6.0),
    "degC": (lambda x: x, lambda x: x),
    "K": (lambda x: x - 273.15, lambda x: x + 273.15),
    "km/h": (lambda x: x, lambda x: x),
    "m/s": (lambda x: x * 3.6, lambda x: x / 3.6),
    "%": (lambda x: x, lambda x: x),
    "frac": (lambda x: x * 100.0, lambda x: x / 100.0),
    "hPa": (lambda x: x, lambda x: x),
    "Pa": (lambda x: x / 100.0, lambda x: x * 100.0),
}
BOUNDS = {"rain": (0, 500), "temp": (-60, 60), "wind": (0, 400), "rh": (0, 100), "pressure": (850, 1090)}
SCHEMA = ["model_id", "issue_time", "valid_time", "lead_h", "location_id", "variable", "value"]


def to_canonical(values, unit: str):
    return UNITS[unit][0](np.asarray(values, dtype=float))


def from_canonical(values, unit: str):
    return UNITS[unit][1](np.asarray(values, dtype=float))


@dataclass
class ValidationReport:
    model_id: str
    n_rows: int
    nan_frac: float
    out_of_bounds: dict = field(default_factory=dict)
    duplicates: int = 0
    ok: bool = True
    issues: list = field(default_factory=list)

    def as_dict(self):
        return self.__dict__.copy()


def validate_frame(df: pd.DataFrame, model_id: str, max_nan: float = 0.02) -> ValidationReport:
    rep = ValidationReport(model_id, len(df), float(df["value"].isna().mean()))
    missing = [c for c in SCHEMA if c not in df.columns]
    if missing:
        rep.ok = False
        rep.issues.append(f"missing columns {missing}")
        return rep
    if rep.nan_frac > max_nan:
        rep.ok = False
        rep.issues.append(f"NaN fraction {rep.nan_frac:.3f} > {max_nan}")
    for var, (lo, hi) in BOUNDS.items():
        v = df.loc[df.variable == var, "value"]
        bad = int(((v < lo) | (v > hi)).sum())
        if bad:
            rep.out_of_bounds[var] = bad
            rep.ok = False
            rep.issues.append(f"{bad} out-of-bounds values for {var}")
    rep.duplicates = int(df.duplicated(["issue_time", "valid_time", "location_id", "variable"]).sum())
    if rep.duplicates:
        rep.ok = False
        rep.issues.append(f"{rep.duplicates} duplicate rows")
    if not (df["lead_h"] > 0).all():
        rep.ok = False
        rep.issues.append("non-positive lead")
    unknown = set(df.variable.unique()) - set(ALL_VARS)
    if unknown:
        rep.ok = False
        rep.issues.append(f"unknown variables {unknown}")
    return rep


def harmonize(frames: dict[str, pd.DataFrame]) -> pd.DataFrame:
    """Concatenate already-normalised provider frames; enforce identical schema / dtype."""
    out = []
    for mid, df in frames.items():
        d = df[SCHEMA].copy()
        d["model_id"] = mid
        out.append(d)
    return pd.concat(out, ignore_index=True)


def regrid_to_points(ds: xr.Dataset, lats, lons, method: str = "linear") -> xr.Dataset:
    """Bilinear interpolation of a lat/lon gridded dataset (any native resolution) onto
    station/city points. Used when a provider returns GRIB/NetCDF grids (e.g. ECMWF open data)
    instead of point time-series."""
    la = xr.DataArray(np.asarray(lats), dims="point")
    lo = xr.DataArray(np.asarray(lons), dims="point")
    return ds.interp(latitude=la, longitude=lo, method=method)
