"""Open-Meteo providers behind the same ForecastProvider / ObservationProvider interfaces as the synthetic ones.

Endpoints (https://open-meteo.com/en/docs):
  live            api.open-meteo.com/v1/forecast                  latest run of one model
  previous_runs   previous-runs-api.open-meteo.com/v1/forecast    `<var>_previous_dayK` = value predicted 24*K h
                                                                  before valid time (most models since Jan 2024)
  archive         archive-api.open-meteo.com/v1/archive           reanalysis-based history, used as TRUTH

Read before trusting any number produced from this module:
  * The archive is reanalysis-based, not independent station observations. Every artifact built on it says so.
  * Previous Runs gives day offsets only, so back-test leads are 24/48/72 h (not 6/12 h).
  * Live issue time is the 6-hourly fetch cycle (the forecast API does not return the model run's init time).
    That is the time WE observed the forecast, so it is free of hindsight.
  * Model API ids below follow Open-Meteo naming conventions and are NOT yet confirmed against the live service
    from the development sandbox (no outbound access). Run `python -m weavia.live check` first. A wrong id fails
    loudly, it never silently produces data.
  * The same check exercises start_date/end_date support on the previous-runs endpoint.
"""
from __future__ import annotations

import math
import time

import httpx
import numpy as np
import pandas as pd

from ..harmonize import to_canonical
from ..locations import Location
from .base import FetchSpec, ForecastProvider, ModelMeta, ObservationProvider

FORECAST_URL = "https://api.open-meteo.com/v1/forecast"
PREVIOUS_URL = "https://previous-runs-api.open-meteo.com/v1/forecast"
ARCHIVE_URL = "https://archive-api.open-meteo.com/v1/archive"
USER_AGENT = "WEAVIA/0.2 (SIH26081 research prototype)"

# native hourly variable -> (canonical variable, native unit AFTER our 6-hour aggregation)
HOURLY = {
    "temperature_2m": ("temp", "degC"),
    "precipitation": ("rain", "mm/6h"),          # hourly "preceding hour" sums are summed over 6 h
    "wind_speed_10m": ("wind", "km/h"),
    "relative_humidity_2m": ("rh", "%"),
    "pressure_msl": ("pressure", "hPa"),
}
SUM_VARS = {"precipitation"}
GRID_HOURS = (0, 6, 12, 18)

# key -> Open-Meteo model id and metadata. Keys become the model ids used throughout WEAVIA.
MODEL_CATALOG = {
    "ifs": dict(api_id="ecmwf_ifs025", name="ECMWF IFS 0.25°", kind="NWP", label="IFS", res=0.25, provider="ECMWF"),
    "aifs": dict(api_id="ecmwf_aifs025_single", name="ECMWF AIFS 0.25° (AI)", kind="AI", label="AIFS", res=0.25, provider="ECMWF"),
    "gfs": dict(api_id="gfs_global", name="NOAA GFS", kind="NWP", label="GFS", res=0.25, provider="NOAA"),
    "icon": dict(api_id="icon_global", name="DWD ICON Global", kind="NWP", label="ICON", res=0.125, provider="DWD"),
}
DEFAULT_MODELS = tuple(MODEL_CATALOG)


class OpenMeteoError(RuntimeError):
    pass


class OpenMeteoClient:
    """Small resilient HTTP client: retries 429/5xx/transport errors with backoff, turns 400s into clear errors."""

    def __init__(self, client: httpx.Client | None = None, retries: int = 4, backoff: float = 2.0,
                 timeout: float = 30.0, sleep=time.sleep):
        self.client = client or httpx.Client(headers={"User-Agent": USER_AGENT})
        self.retries, self.backoff, self.timeout, self.sleep = retries, backoff, timeout, sleep
        self.calls = 0

    def get_json(self, url: str, params: dict):
        last = "no attempt"
        for attempt in range(self.retries + 1):
            self.calls += 1
            try:
                r = self.client.get(url, params=params, timeout=self.timeout)
            except httpx.TransportError as e:
                last = f"transport error: {type(e).__name__}"
            else:
                if r.status_code == 200:
                    return r.json()
                if r.status_code == 400:
                    reason = ""
                    try:
                        reason = r.json().get("reason", "")
                    except ValueError:
                        pass
                    raise OpenMeteoError(f"400 from {url}: {reason or r.text[:200]}")
                if r.status_code == 429 or r.status_code >= 500:
                    last = f"HTTP {r.status_code}"
                    ra = r.headers.get("Retry-After")
                    if ra and ra.isdigit() and attempt < self.retries:
                        self.sleep(min(int(ra), 120))
                        continue
                else:
                    raise OpenMeteoError(f"HTTP {r.status_code} from {url}")
            if attempt < self.retries:
                self.sleep(self.backoff * (2 ** attempt))
        raise OpenMeteoError(f"gave up after {self.retries + 1} attempts ({last}) on {url}")


# --------------------------------------------------------------------------------------------- helpers
def floor_to_cycle(ts: pd.Timestamp, hours: int = 6) -> pd.Timestamp:
    ts = pd.Timestamp(ts)
    ts = ts.tz_localize("UTC") if ts.tzinfo is None else ts.tz_convert("UTC")
    return ts.floor(f"{hours}h")


def _as_list(payload) -> list[dict]:
    return payload if isinstance(payload, list) else [payload]


def _series(hourly: dict, key: str) -> pd.Series:
    t = pd.to_datetime(hourly["time"], utc=True)
    s = pd.Series(pd.to_numeric(pd.Series(hourly[key], dtype="object"), errors="coerce").to_numpy(dtype=float), index=t)
    return s[~s.index.duplicated()]


def to_grid(s: pd.Series, summed: bool) -> pd.Series:
    """Hourly series -> 6-hourly canonical grid (00/06/12/18 UTC).

    Instant variables are sampled at the grid hour. Precipitation, an hourly 'preceding hour' sum, becomes the
    sum of the six hours ending at the grid hour, and is dropped unless all six hours are present."""
    s = s.sort_index()
    grid = s.index[s.index.hour.isin(GRID_HOURS)]
    if not summed:
        return s.loc[grid].dropna()
    roll = s.rolling("6h", closed="right").agg(["sum", "count"])
    out = roll["sum"].where(roll["count"] == 6)
    return out.loc[grid].dropna()


IST = pd.Timedelta(hours=5, minutes=30)
DAILY_COLS = ["model_id", "valid_day", "lead_day", "location_id", "variable", "value"]


def daily_tmax_ist(s: pd.Series) -> pd.Series:
    """Maximum over each complete IST calendar day (all 24 hourly values present), indexed by the IST date."""
    s = s.sort_index().dropna()
    ist = pd.Series(s.values, index=(s.index + IST).tz_localize(None))
    g = ist.groupby(ist.index.normalize())
    out = g.max()[g.count() == 24]
    out.index.name = None
    return out


def daily_rain_imd(s: pd.Series) -> pd.Series:
    """IMD-day rainfall: the 24 hours ending 03:00 UTC (08:30 IST), labelled by that date. Needs all 24 hours."""
    s = s.sort_index()
    roll = s.rolling("24h", closed="right").agg(["sum", "count"])
    out = roll["sum"].where(roll["count"] == 24)
    out = out[out.index.hour == 3].dropna()
    out.index = out.index.tz_localize(None).normalize()
    return out


def _daily_for(nvar: str, ser: pd.Series) -> tuple[str, pd.Series] | None:
    if nvar == "temperature_2m":
        return "tmax", daily_tmax_ist(ser)
    if nvar == "precipitation":
        return "rain24", daily_rain_imd(ser)
    return None


def _chunks(start: pd.Timestamp, end: pd.Timestamp, days: int):
    cur = start.normalize()
    while cur <= end:
        nxt = min(cur + pd.Timedelta(days=days - 1), end.normalize())
        yield cur.strftime("%Y-%m-%d"), nxt.strftime("%Y-%m-%d")
        cur = nxt + pd.Timedelta(days=1)


def _coords(locs) -> dict:
    return {"latitude": ",".join(f"{l.lat:.4f}" for l in locs), "longitude": ",".join(f"{l.lon:.4f}" for l in locs)}


def _utc(ts) -> pd.Timestamp:
    ts = pd.Timestamp(ts)
    return ts.tz_localize("UTC") if ts.tzinfo is None else ts.tz_convert("UTC")


# --------------------------------------------------------------------------------------------- forecasts
class OpenMeteoModelProvider(ForecastProvider):
    """One Open-Meteo model. mode='live' uses the Forecast API; mode='previous_runs' the Previous Runs API."""

    def __init__(self, model_key: str, mode: str = "live", client: OpenMeteoClient | None = None,
                 issue_time: pd.Timestamp | None = None, chunk_days: int = 30):
        if model_key not in MODEL_CATALOG:
            raise KeyError(f"unknown model {model_key!r}; known: {sorted(MODEL_CATALOG)}")
        if mode not in ("live", "previous_runs"):
            raise ValueError("mode must be 'live' or 'previous_runs'")
        m = MODEL_CATALOG[model_key]
        self.model_key, self.api_id, self.mode = model_key, m["api_id"], mode
        self.client = client or OpenMeteoClient()
        self.issue_time = floor_to_cycle(issue_time if issue_time is not None else pd.Timestamp.now(tz="UTC"))
        self.chunk_days = chunk_days
        self.var_map = dict(HOURLY)
        self.tz_offset_hours = 0.0
        self.skipped_leads: list[int] = []
        self._daily: list[tuple] = []
        self.meta = ModelMeta(model_key, m["name"], m["kind"], m["label"], m["res"], m["provider"], False)

    def fetch(self, spec: FetchSpec) -> pd.DataFrame:
        self._daily = []
        return self._fetch_live(spec) if self.mode == "live" else self._fetch_previous(spec)

    @property
    def daily(self) -> pd.DataFrame:
        """Daily products from the SAME hourly responses as the last fetch: IST-day maximum temperature ('tmax')
        and IMD-day rainfall ('rain24'), per valid day and lead day. Empty before a fetch."""
        df = pd.DataFrame(self._daily, columns=DAILY_COLS)
        return df.drop_duplicates(["valid_day", "lead_day", "location_id", "variable"]).reset_index(drop=True)

    def _fetch_live(self, spec: FetchSpec) -> pd.DataFrame:
        leads = sorted(int(l) for l in spec.leads)
        days = math.ceil((max(leads) + 24) / 24) + 1
        params = {**_coords(spec.locations), "hourly": ",".join(HOURLY), "models": self.api_id,
                  "forecast_days": min(days, 16), "timezone": "GMT", "wind_speed_unit": "kmh", "precipitation_unit": "mm"}
        payload = _as_list(self.client.get_json(FORECAST_URL, params))
        if len(payload) != len(spec.locations):
            raise OpenMeteoError(f"{self.model_key}: asked for {len(spec.locations)} locations, got {len(payload)}")
        rows = []
        for loc, item in zip(spec.locations, payload):
            hourly = item.get("hourly") or {}
            for nvar in HOURLY:
                if nvar not in hourly:
                    raise OpenMeteoError(f"{self.model_key}: response lacks {nvar!r} (keys: {sorted(hourly)[:8]})")
                ser = _series(hourly, nvar)
                g = to_grid(ser, nvar in SUM_VARS)
                dd = _daily_for(nvar, ser)
                if dd is not None:
                    issue_day = self.issue_time.tz_localize(None).normalize()
                    wanted = {l // 24 for l in leads if l % 24 == 0}
                    for day, val in dd[1].items():
                        k = (day - issue_day).days
                        if k in wanted:
                            self._daily.append((self.model_key, day, k, loc.id, dd[0], float(val)))
                for lead in leads:
                    v = self.issue_time + pd.Timedelta(hours=lead)
                    if v in g.index:
                        rows.append((self.issue_time, v, loc.id, nvar, float(g.loc[v])))
        return self._frame(rows)

    def _fetch_previous(self, spec: FetchSpec) -> pd.DataFrame:
        usable = sorted(int(l) for l in spec.leads if int(l) % 24 == 0 and 24 <= int(l) <= 168)
        self.skipped_leads = sorted(set(int(l) for l in spec.leads) - set(usable))
        if not usable:
            raise OpenMeteoError("previous_runs needs leads that are multiples of 24 h (24, 48, ...)")
        ks = [l // 24 for l in usable]
        v0 = _utc(spec.start) if spec.start is not None else self.issue_time - pd.Timedelta(days=90)
        v1 = _utc(spec.end) if spec.end is not None else self.issue_time
        hourly = ",".join(f"{v}_previous_day{k}" for v in HOURLY for k in ks)
        rows = []
        for a, b in _chunks(v0, v1, self.chunk_days):
            params = {**_coords(spec.locations), "hourly": hourly, "models": self.api_id, "start_date": a,
                      "end_date": b, "timezone": "GMT", "wind_speed_unit": "kmh", "precipitation_unit": "mm"}
            payload = _as_list(self.client.get_json(PREVIOUS_URL, params))
            if len(payload) != len(spec.locations):
                raise OpenMeteoError(f"{self.model_key}: asked for {len(spec.locations)} locations, got {len(payload)}")
            for loc, item in zip(spec.locations, payload):
                h = item.get("hourly") or {}
                for nvar in HOURLY:
                    for k in ks:
                        key = f"{nvar}_previous_day{k}"
                        if key not in h:
                            raise OpenMeteoError(f"{self.model_key}: response lacks {key!r} (keys: {sorted(h)[:8]})")
                        ser = _series(h, key)
                        g = to_grid(ser, nvar in SUM_VARS)
                        dd = _daily_for(nvar, ser)
                        if dd is not None:
                            for day, val in dd[1].items():
                                self._daily.append((self.model_key, day, k, loc.id, dd[0], float(val)))
                        for v, val in g.items():
                            rows.append((v - pd.Timedelta(hours=24 * k), v, loc.id, nvar, float(val)))
        return self._frame(rows)

    @staticmethod
    def _frame(rows) -> pd.DataFrame:
        df = pd.DataFrame(rows, columns=["run_time", "valid_time", "location_id", "native_var", "value"])
        for c in ("run_time", "valid_time"):          # base.normalize expects naive UTC (tz_offset 0)
            df[c] = pd.to_datetime(df[c], utc=True).dt.tz_localize(None)
        return df.drop_duplicates(["run_time", "valid_time", "location_id", "native_var"]).reset_index(drop=True)


# --------------------------------------------------------------------------------------------- truth
class OpenMeteoArchiveObservations(ObservationProvider):
    """Reanalysis-based truth from the Open-Meteo archive. NOT independent of the forecast models."""
    SOURCE = "open-meteo-archive (reanalysis)"

    def __init__(self, client: OpenMeteoClient | None = None, chunk_days: int = 120):
        self.client, self.chunk_days = client or OpenMeteoClient(), chunk_days
        self._daily: list[tuple] = []

    @property
    def daily(self) -> pd.DataFrame:
        """Daily truth (IST-day tmax, IMD-day rain24) from the hourly archive of the last fetch."""
        df = pd.DataFrame(self._daily, columns=["valid_day", "location_id", "variable", "value"])
        return df.drop_duplicates(["valid_day", "location_id", "variable"]).reset_index(drop=True)

    def fetch_normals(self, locations, start_year: int = 1991, end_year: int = 2020, window_days: int = 7) -> pd.DataFrame:
        """Per-station normal daily maximum temperature by day of year: the mean of the daily maximum over
        start_year..end_year, within +/- window_days of the calendar day. REANALYSIS-based, so it is not IMD's
        own gridded normal. Returns location_id, doy (1..366), normal_tmax."""
        rows = []
        for a, b in _chunks(pd.Timestamp(f"{start_year}-01-01", tz="UTC"), pd.Timestamp(f"{end_year}-12-31", tz="UTC"), 3653):
            params = {**_coords(locations), "daily": "temperature_2m_max", "start_date": a, "end_date": b, "timezone": "Asia/Kolkata"}
            payload = _as_list(self.client.get_json(ARCHIVE_URL, params))
            if len(payload) != len(locations):
                raise OpenMeteoError(f"normals: asked for {len(locations)} locations, got {len(payload)}")
            for loc, item in zip(locations, payload):
                d = item.get("daily") or {}
                if "temperature_2m_max" not in d:
                    raise OpenMeteoError("normals response lacks 'temperature_2m_max'")
                t = pd.to_datetime(d["time"])
                v = pd.to_numeric(pd.Series(d["temperature_2m_max"], dtype="object"), errors="coerce").to_numpy(dtype=float)
                rows.append(pd.DataFrame({"location_id": loc.id, "doy": t.dayofyear, "tmax": v}))
        raw = pd.concat(rows, ignore_index=True).dropna()
        out = []
        for lid, g in raw.groupby("location_id"):
            by_doy = g.groupby("doy").tmax.mean().reindex(range(1, 367))
            ext = pd.concat([by_doy.iloc[-window_days:], by_doy, by_doy.iloc[:window_days]])
            sm = ext.rolling(2 * window_days + 1, center=True, min_periods=1).mean().iloc[window_days:-window_days]
            out.append(pd.DataFrame({"location_id": lid, "doy": range(1, 367), "normal_tmax": sm.values}))
        return pd.concat(out, ignore_index=True)

    def fetch(self, spec: FetchSpec) -> pd.DataFrame:
        v0, v1 = _utc(spec.start), _utc(spec.end)
        self._daily = []
        parts = []
        for a, b in _chunks(v0, v1, self.chunk_days):
            params = {**_coords(spec.locations), "hourly": ",".join(HOURLY), "start_date": a, "end_date": b,
                      "timezone": "GMT", "wind_speed_unit": "kmh", "precipitation_unit": "mm"}
            payload = _as_list(self.client.get_json(ARCHIVE_URL, params))
            if len(payload) != len(spec.locations):
                raise OpenMeteoError(f"archive: asked for {len(spec.locations)} locations, got {len(payload)}")
            for loc, item in zip(spec.locations, payload):
                h = item.get("hourly") or {}
                for nvar, (cvar, unit) in HOURLY.items():
                    if nvar not in h:
                        raise OpenMeteoError(f"archive response lacks {nvar!r}")
                    ser = _series(h, nvar)
                    dd = _daily_for(nvar, ser)
                    if dd is not None:
                        for day, val in dd[1].items():
                            self._daily.append((day, loc.id, dd[0], float(val)))
                    g = to_grid(ser, nvar in SUM_VARS)
                    parts.append(pd.DataFrame({"timestamp": g.index, "location_id": loc.id, "variable": cvar,
                                               "value": to_canonical(g.values, unit), "source": self.SOURCE}))
        cols = ["timestamp", "location_id", "variable", "value", "source"]
        out = pd.concat(parts, ignore_index=True) if parts else pd.DataFrame(columns=cols)
        out["timestamp"] = pd.to_datetime(out["timestamp"], utc=True)
        out = out[(out.timestamp >= v0) & (out.timestamp <= v1)]
        return out.drop_duplicates(["timestamp", "location_id", "variable"]).reset_index(drop=True)


# --------------------------------------------------------------------------------------------- self-check
def check_models(models=DEFAULT_MODELS, client: OpenMeteoClient | None = None, location: Location | None = None,
                 now: pd.Timestamp | None = None) -> dict:
    """Probe each model on one location through both endpoints, plus the archive. Returns {name: 'ok' | reason}.
    This confirms model ids and endpoint parameters before any real run."""
    from ..locations import LOCATIONS
    client = client or OpenMeteoClient(retries=1, sleep=lambda s: None)
    loc = location or LOCATIONS[0]
    now = _utc(now) if now is not None else pd.Timestamp.now(tz="UTC")
    report = {}
    for key in models:
        for mode in ("live", "previous_runs"):
            name = f"{key}:{mode}"
            try:
                p = OpenMeteoModelProvider(key, mode, client=client, issue_time=now)
                spec = FetchSpec([loc], start=now - pd.Timedelta(days=10), end=now - pd.Timedelta(days=8), leads=(24, 48, 72))
                df = p.fetch(spec)
                report[name] = "ok" if len(df) else "empty response (model may not cover this period)"
            except Exception as e:                      # noqa: BLE001 - report every failure kind
                report[name] = f"{type(e).__name__}: {e}"
    try:
        spec = FetchSpec([loc], start=now - pd.Timedelta(days=20), end=now - pd.Timedelta(days=15))
        df = OpenMeteoArchiveObservations(client).fetch(spec)
        report["archive"] = "ok" if len(df) else "empty response"
    except Exception as e:                              # noqa: BLE001
        report["archive"] = f"{type(e).__name__}: {e}"
    try:                                                # daily aggregates in the archive (heat-wave normals)
        n = OpenMeteoArchiveObservations(client).fetch_normals([loc], 2019, 2019)
        report["archive:normals"] = "ok" if len(n) else "empty response"
    except Exception as e:                              # noqa: BLE001
        report["archive:normals"] = f"{type(e).__name__}: {e}"
    return report
