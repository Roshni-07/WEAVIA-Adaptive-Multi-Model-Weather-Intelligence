"""Error characteristics of the four SYNTHETIC forecast models.

These are *designed* to have context-dependent skill so the pipeline can be exercised
end-to-end. Verification results obtained on this data validate the machinery, not
real-world forecast skill. Real data path: providers/openmeteo.py.
"""
from __future__ import annotations

MODEL_META = {
    "model_a": dict(name="Model A", kind="NWP", label="Physics NWP (synthetic)", res_deg=0.25,
                    tz_offset=0.0, vars={
                        "precip_rate": ("rain", "mm/h"), "t2m": ("temp", "degC"), "ws10": ("wind", "km/h"),
                        "rh2m": ("rh", "%"), "mslp": ("pressure", "hPa")}),
    "model_b": dict(name="Model B", kind="NWP", label="High-res convective NWP (synthetic)", res_deg=0.10,
                    tz_offset=5.5, vars={
                        "tp": ("rain", "mm/6h"), "temperature_2m": ("temp", "degC"), "wind_speed_10m": ("wind", "km/h"),
                        "relative_humidity_2m": ("rh", "%"), "pressure_msl": ("pressure", "hPa")}),
    "model_c": dict(name="Model C", kind="AI", label="AI weather model (synthetic)", res_deg=0.25,
                    tz_offset=0.0, vars={
                        "rain_mm_6h": ("rain", "mm/6h"), "t2m_c": ("temp", "degC"), "wind_ms": ("wind", "m/s"),
                        "rh_pct": ("rh", "%"), "msl_pa": ("pressure", "Pa")}),
    "model_d": dict(name="Model D", kind="ENSEMBLE", label="Ensemble mean (synthetic)", res_deg=0.50,
                    tz_offset=0.0, vars={
                        "precip_mm_6h": ("rain", "mm/6h"), "t2m_k": ("temp", "K"), "wind_kmh": ("wind", "km/h"),
                        "rh_frac": ("rh", "frac"), "msl_hpa": ("pressure", "hPa")}),
}

# base error sd at lead 0 : temp degC, wind km/h, rain = sd of log multiplier
SD0 = {
    "temp": {"model_a": 0.9, "model_b": 1.3, "model_c": 0.6, "model_d": 1.1},
    "wind": {"model_a": 3.0, "model_b": 3.5, "model_c": 2.5, "model_d": 3.2},
    "rain": {"model_a": 0.50, "model_b": 0.60, "model_c": 0.40, "model_d": 0.55},
}
# fractional sd growth per forecast day
GROWTH = {
    "temp": {"model_a": 0.25, "model_b": 0.45, "model_c": 0.65, "model_d": 0.08},
    "wind": {"model_a": 0.25, "model_b": 0.40, "model_c": 0.60, "model_d": 0.10},
    "rain": {"model_a": 0.30, "model_b": 0.30, "model_c": 0.55, "model_d": 0.10},
}
# sd multiplier by (observed) regime at valid time
REGIME_MULT = {
    "model_a": {"CONVECTIVE": 1.5, "HEAVY_RAIN": 1.6, "HEAT": 0.9, "CYCLONIC": 1.4, "HIGH_WIND": 1.1, "DRY": 0.9, "NORMAL": 0.95, "TRANSITION": 1.0},
    "model_b": {"CONVECTIVE": 0.65, "HEAVY_RAIN": 0.75, "HEAT": 1.4, "CYCLONIC": 0.7, "HIGH_WIND": 0.85, "DRY": 1.2, "NORMAL": 1.15, "TRANSITION": 1.0},
    "model_c": {"CONVECTIVE": 1.2, "HEAVY_RAIN": 1.4, "HEAT": 0.8, "CYCLONIC": 1.6, "HIGH_WIND": 1.3, "DRY": 0.8, "NORMAL": 0.9, "TRANSITION": 1.1},
    "model_d": {"CONVECTIVE": 1.0, "HEAVY_RAIN": 1.1, "HEAT": 1.0, "CYCLONIC": 1.3, "HIGH_WIND": 1.1, "DRY": 1.0, "NORMAL": 1.0, "TRANSITION": 1.0},
}
# systematic bias by observed regime (temp degC, wind km/h, rain log-multiplier)
REGIME_BIAS = {
    "rain": {"model_a": {"CONVECTIVE": -0.35, "HEAVY_RAIN": -0.45}, "model_b": {},
             "model_c": {"HEAVY_RAIN": -0.35, "CONVECTIVE": -0.2}, "model_d": {"CONVECTIVE": -0.3, "HEAVY_RAIN": -0.5}},
    "temp": {"model_a": {"HEAT": -0.8}, "model_b": {"HEAT": -1.8}, "model_c": {"HEAT": -0.8}, "model_d": {"HEAT": -1.2}},
    "wind": {"model_a": {"CYCLONIC": -6.0}, "model_b": {"CYCLONIC": -1.0},
             "model_c": {"CYCLONIC": -8.0, "HIGH_WIND": -3.0}, "model_d": {"CYCLONIC": -10.0, "HIGH_WIND": -4.0}},
}
REGION_MULT = {
    "model_a": {"NORTH": 0.75},
    "model_b": {"WEST_COAST": 0.75, "SOUTH": 0.85, "NORTH": 1.25},
    "model_c": {"EAST_COAST": 0.8, "EAST_NE": 1.1},
    "model_d": {"CENTRAL": 0.85},
}
SEASON_MULT = {
    "model_a": {"WINTER": 0.9, "PRE_MONSOON": 0.85, "MONSOON": 1.25, "POST_MONSOON": 1.0},
    "model_b": {"WINTER": 1.2, "PRE_MONSOON": 1.1, "MONSOON": 0.8, "POST_MONSOON": 0.9},
    "model_c": {"WINTER": 0.85, "PRE_MONSOON": 1.0, "MONSOON": 1.2, "POST_MONSOON": 1.0},
    "model_d": {"WINTER": 1.0, "PRE_MONSOON": 1.0, "MONSOON": 1.0, "POST_MONSOON": 1.0},
}
COMMON_RHO = 0.25       # shared (all-model) error correlation
CTX_SD = {"rh": 4.0, "pressure": 0.8}
