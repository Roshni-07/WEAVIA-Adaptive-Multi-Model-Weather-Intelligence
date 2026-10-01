"""Global constants. Canonical units live here; every provider is normalised to them."""
from __future__ import annotations

STEP_H = 6                       # canonical time resolution of truth / valid times
LEADS = [6, 12, 24, 48, 72]      # forecast lead times (hours)
MODELS = ["model_a", "model_b", "model_c", "model_d"]

BLEND_VARS = ["rain", "temp", "wind"]        # variables WEAVIA blends
CONTEXT_VARS = ["rh", "pressure"]            # used for regime detection / features only
ALL_VARS = BLEND_VARS + CONTEXT_VARS

CANON_UNIT = {"rain": "mm/6h", "temp": "degC", "wind": "km/h", "rh": "%", "pressure": "hPa"}
VAR_LABEL = {"rain": "Rainfall", "temp": "Temperature", "wind": "Wind speed"}

REGIMES = ["NORMAL", "CONVECTIVE", "HEAVY_RAIN", "HEAT", "HIGH_WIND", "CYCLONIC", "DRY", "TRANSITION"]
SEASONS = ["WINTER", "PRE_MONSOON", "MONSOON", "POST_MONSOON"]

# Extreme-event thresholds on the canonical variables (MVP proxies, configurable)
EVENT_THRESH = {"rain": 20.0, "temp": 38.0, "wind": 30.0}
EVENT_NAME = {"rain": "Heavy rainfall", "temp": "Heat", "wind": "High wind"}

# Tolerance used to define "confidence" = P(|error| <= tol)
TOLERANCE = {"rain": (2.0, 0.30), "temp": (1.5, 0.0), "wind": (4.0, 0.25)}   # (absolute, relative-to-forecast): tol = max(abs, rel*|forecast|)


def tolerance(var, forecast):
    a, r = TOLERANCE[var]
    import numpy as _np
    return _np.maximum(a, r * _np.abs(forecast))
SPREAD_FLOOR = {"rain": 1.0, "temp": 0.5, "wind": 1.0}

# Chronological split of issue dates
SPLIT_FRACS = (0.60, 0.15, 0.25)   # train / validation(calibration) / test

MODEL_ERR_LAG_DAYS = 1
RECENT_WINDOW = 7
