"""A deterministic fake of the Open-Meteo HTTP API (httpx.MockTransport) shaped like the documented responses:
a dict for one location, a list of dicts for several, `hourly.time` + one array per requested variable,
previous-runs variables named `<var>_previous_dayK`, 400 + {"error": true, "reason": ...} on bad input."""
from __future__ import annotations

import re

import httpx
import numpy as np
import pandas as pd

NOW = pd.Timestamp("2026-10-02T09:00:00Z")
GOOD_MODELS = {"ecmwf_ifs025", "ecmwf_aifs025_single", "gfs_global", "icon_global"}


def base_value(var: str, lat: float, t: pd.Timestamp, k: int = 0) -> float:
    if var == "temperature_2m":
        return round(20 + lat / 10 + t.hour / 10 + 0.1 * k, 3)
    if var == "precipitation":
        return round(0.5 + 0.1 * k, 3)           # every hour: a 6 h sum is 6 * this
    if var == "wind_speed_10m":
        return round(10 + 0.1 * k + lat / 100, 3)
    if var == "relative_humidity_2m":
        return 60.0
    if var == "pressure_msl":
        return round(1005 + 0.1 * k, 3)
    raise KeyError(var)


class FakeOpenMeteo:
    def __init__(self, fail_first: int = 0, fail_status: int = 500, bad_models=(), drop_var: str | None = None,
                 wrong_count: bool = False):
        self.requests: list[httpx.Request] = []
        self.fail_first, self.fail_status = fail_first, fail_status
        self.bad_models, self.drop_var, self.wrong_count = set(bad_models), drop_var, wrong_count

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        if self.fail_first > 0:
            self.fail_first -= 1
            return httpx.Response(self.fail_status, json={"error": True, "reason": "temporary"}, headers={"Retry-After": "0"} if self.fail_status == 429 else {})
        q = dict(request.url.params)
        if q.get("models") and (q["models"] in self.bad_models or q["models"] not in GOOD_MODELS):
            return httpx.Response(400, json={"error": True, "reason": f"Cannot initialize Model from invalid String value {q['models']}"})
        lats = [float(x) for x in q["latitude"].split(",")]
        if "daily" in q:                                   # archive daily aggregates (used for normals)
            days = pd.date_range(q["start_date"], q["end_date"], freq="D")
            doy = days.dayofyear.to_numpy()
            out = [{"daily": {"time": [d.strftime("%Y-%m-%d") for d in days],
                              q["daily"]: [round(30 + 5 * np.sin(2 * np.pi * x / 365.25) + lat / 10, 3) for x in doy]}} for lat in lats]
            return httpx.Response(200, json=out if len(out) > 1 else out[0])
        hourly = q["hourly"].split(",")
        host = request.url.host
        if "start_date" in q:
            t0 = pd.Timestamp(q["start_date"], tz="UTC")
            t1 = pd.Timestamp(q["end_date"], tz="UTC") + pd.Timedelta(hours=23)
        else:
            t0 = NOW.normalize()
            t1 = t0 + pd.Timedelta(days=int(q.get("forecast_days", 7))) - pd.Timedelta(hours=1)
        times = pd.date_range(t0, t1, freq="h")
        out = []
        for lat in lats:
            h = {"time": [t.strftime("%Y-%m-%dT%H:%M") for t in times]}
            for key in hourly:
                m = re.match(r"(.+?)_previous_day(\d+)$", key)
                var, k = (m.group(1), int(m.group(2))) if m else (key, 0)
                if var == self.drop_var:
                    continue
                h[key] = [base_value(var, lat, t, k) for t in times]
            out.append({"latitude": lat, "longitude": 0.0, "hourly": h, "hourly_units": {}})
        if self.wrong_count and len(out) > 1:
            out = out[:-1]
        return httpx.Response(200, json=out if len(out) > 1 else out[0])


def make_client(fake: FakeOpenMeteo | None = None, **kw):
    from weavia.providers.openmeteo import OpenMeteoClient
    fake = fake or FakeOpenMeteo()
    return OpenMeteoClient(client=httpx.Client(transport=httpx.MockTransport(fake)), sleep=lambda s: None, **kw), fake
