"""IMD extreme-weather criteria as pure, tested functions.

Sources (checked October 2026):
  * Rainfall classes are 24-hour totals (IMD day, 08:30 to 08:30 IST): heavy 64.5 to 115.5 mm, very heavy
    115.6 to 204.4 mm, extremely heavy 204.5 mm or more. Lower classes: light 2.5 to 15.5, moderate 15.6 to 64.4.
    (IMD weather bulletins and the IMD Pune hazard atlas.)
  * Heat wave (IMD FAQ and the IMD Pune hazard atlas):
      - considered only when station maximum is at least 40 C (plains) or 30 C (hilly);
      - departure from normal 4.5 to 6.4 C = heat wave, above 6.4 C = severe heat wave;
      - or actual maximum of 45 C or more = heat wave, 47 C or more = severe, irrespective of departure;
      - coastal stations: departure of 4.5 C or more counts, provided the actual maximum is 37 C or more;
      - declared when met at 2 or more stations in a meteorological sub-division on 2 consecutive days,
        declared on the second day.

What this module is NOT: an official declaration. Only IMD declares heat waves. Outputs built on it are labelled
"indicator". The wind threshold has no single official value in the sources checked: IMD bulletins quote gusty-wind
bands (for example 30 to 40 and 40 to 50 km/h), and WEAVIA blends sustained 10 m wind, not gusts. It is therefore a
configurable proxy, not an IMD criterion.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

# ------------------------------------------------------------------ rainfall (24 h)
RAIN_CLASS_LOWER = [0.1, 2.5, 15.6, 64.5, 115.6, 204.5]
RAIN_CLASS_NAMES = ["no_rain", "very_light", "light", "moderate", "heavy", "very_heavy", "extremely_heavy"]
HEAVY_RAIN_24H_MM = 64.5
VERY_HEAVY_RAIN_24H_MM = 115.6
EXTREME_RAIN_24H_MM = 204.5


def rain_class(mm_24h) -> np.ndarray:
    """IMD 24-hour rainfall class name for each value."""
    idx = np.digitize(np.atleast_1d(np.asarray(mm_24h, dtype=float)), RAIN_CLASS_LOWER)
    return np.asarray(RAIN_CLASS_NAMES, dtype=object)[idx]


# ------------------------------------------------------------------ heat wave
TERRAIN_GATE_C = {"plains": 40.0, "coastal": 37.0, "hilly": 30.0}
HW_DEPARTURE_C = 4.5          # heat wave: departure of at least this
SEVERE_DEPARTURE_C = 6.4      # severe heat wave: departure ABOVE this
HW_ABSOLUTE_C = 45.0
SEVERE_ABSOLUTE_C = 47.0


def _gate(terrain) -> np.ndarray:
    t = np.atleast_1d(np.asarray(terrain, dtype=object))
    bad = set(t.tolist()) - set(TERRAIN_GATE_C)
    if bad:
        raise ValueError(f"unknown terrain {sorted(bad)}; expected one of {sorted(TERRAIN_GATE_C)}")
    return np.vectorize(TERRAIN_GATE_C.get, otypes=[float])(t)


def heat_wave_class(tmax, normal, terrain) -> np.ndarray:
    """Per-day station criterion: 0 none, 1 heat wave, 2 severe heat wave.

    tmax: daily maximum temperature (C). normal: that station's normal maximum for the date (C)."""
    tmax = np.asarray(tmax, dtype=float)
    dep = tmax - np.asarray(normal, dtype=float)
    gate = _gate(terrain)
    severe = (tmax >= SEVERE_ABSOLUTE_C) | ((tmax >= gate) & (dep > SEVERE_DEPARTURE_C))
    hw = (tmax >= HW_ABSOLUTE_C) | ((tmax >= gate) & (dep >= HW_DEPARTURE_C))
    return np.where(severe, 2, np.where(hw, 1, 0)).astype(int)


def heat_wave_threshold(normal, terrain, severe: bool = False) -> np.ndarray:
    """The daily maximum at which the criterion starts to hold, so P(tmax >= threshold) is the criterion's
    probability. Equivalent to heat_wave_class for any tmax (the severe departure test is strict, so use > there)."""
    normal = np.asarray(normal, dtype=float)
    gate = _gate(terrain)
    if severe:
        return np.minimum(np.maximum(gate, normal + SEVERE_DEPARTURE_C), SEVERE_ABSOLUTE_C)
    return np.minimum(np.maximum(gate, normal + HW_DEPARTURE_C), HW_ABSOLUTE_C)


def declare_heat_wave(daily: pd.DataFrame, min_stations: int = 2, min_days: int = 2) -> pd.DataFrame:
    """Apply IMD's persistence rule per group (IMD uses a meteorological sub-division).

    daily needs columns: date, station, group, cls (0/1/2 from heat_wave_class). Returns one row per group and
    day with n_stations (criterion met), declared and severe_declared. A day is declared when the criterion held
    at min_stations or more stations on each of the last min_days consecutive days, so it is declared on the
    second day. Missing days count as not met."""
    need = {"date", "station", "group", "cls"}
    if not need <= set(daily.columns):
        raise ValueError(f"daily must have columns {sorted(need)}")
    d = daily.copy()
    d["date"] = pd.to_datetime(d["date"]).dt.normalize()
    out = []
    for g, sub in d.groupby("group"):
        days = pd.date_range(sub.date.min(), sub.date.max(), freq="D")
        hw = sub[sub.cls >= 1].groupby("date").station.nunique().reindex(days, fill_value=0)
        sv = sub[sub.cls >= 2].groupby("date").station.nunique().reindex(days, fill_value=0)
        res = pd.DataFrame({"group": g, "date": days, "n_stations": hw.values, "n_severe": sv.values})
        met, met_sv = res.n_stations >= min_stations, res.n_severe >= min_stations
        res["declared"] = met.rolling(min_days).sum().eq(min_days).fillna(False).astype(bool)
        res["severe_declared"] = met_sv.rolling(min_days).sum().eq(min_days).fillna(False).astype(bool)
        out.append(res)
    return pd.concat(out, ignore_index=True) if out else pd.DataFrame(
        columns=["group", "date", "n_stations", "n_severe", "declared", "severe_declared"])


# ------------------------------------------------------------------ wind (configurable proxy)
HIGH_WIND_KMH = 30.0
HIGH_WIND_NOTE = ("Proxy, not an IMD criterion: IMD bulletins quote gusty-wind bands (30-40, 40-50 km/h). WEAVIA blends "
                  "sustained 10 m wind speed, so this threshold is configurable.")


def definitions() -> dict:
    """Machine-readable summary for the API and docs."""
    return {
        "rain_24h_classes_mm": dict(zip(RAIN_CLASS_NAMES[1:], ["0.1-2.4", "2.5-15.5", "15.6-64.4", "64.5-115.5", "115.6-204.4", ">=204.5"])),
        "heat_wave": {"gate_c": TERRAIN_GATE_C, "departure_c": [HW_DEPARTURE_C, SEVERE_DEPARTURE_C],
                      "absolute_c": [HW_ABSOLUTE_C, SEVERE_ABSOLUTE_C], "persistence": "2 stations x 2 consecutive days",
                      "status": "indicator, not an IMD declaration"},
        "high_wind_kmh": {"value": HIGH_WIND_KMH, "note": HIGH_WIND_NOTE},
    }
