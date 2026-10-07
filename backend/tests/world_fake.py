"""Open-Meteo fake backed by the synthetic world, so the whole real-data chain (provider -> harmonize -> fit ->
cycle -> store -> API) runs end to end offline. It proves plumbing and no-hindsight behaviour, not real skill."""
from __future__ import annotations

import re

import httpx
import numpy as np
import pandas as pd

from weavia.locations import LOCATIONS

API_TO_SYN = {"ecmwf_ifs025": "model_a", "ecmwf_aifs025_single": "model_b", "gfs_global": "model_c", "icon_global": "model_d"}
NATIVE_TO_CANON = {"temperature_2m": "temp", "precipitation": "rain", "wind_speed_10m": "wind",
                   "relative_humidity_2m": "rh", "pressure_msl": "pressure"}
LAT_TO_LOC = {round(l.lat, 4): l.id for l in LOCATIONS}


class WorldFake:
    def __init__(self, world, live_issue: pd.Timestamp, down_models=(), all_down=False):
        self.world, self.live_issue = world, pd.Timestamp(live_issue)
        self.down_models, self.all_down = set(down_models), all_down
        t = world.truth
        self.t0 = pd.Timestamp(t.time.min()).tz_convert("UTC").normalize() - pd.Timedelta(days=2)
        self.t1 = pd.Timestamp(t.time.max()).tz_convert("UTC").normalize() + pd.Timedelta(days=5)
        self.hours = pd.date_range(self.t0, self.t1 + pd.Timedelta(hours=23), freq="h", tz="UTC")
        self.pos = pd.Series(np.arange(len(self.hours)), index=self.hours)
        self._cache: dict = {}
        self.requests: list[httpx.Request] = []
        self._fc = {m: df.set_index(["location_id", "variable", "lead_h", "valid_time"]).value for m, df in world.forecasts.items()}
        self._fc_issue = {m: df.set_index(["location_id", "variable", "issue_time", "lead_h"]).value for m, df in world.forecasts.items()}
        self._truth = t.set_index(["location_id", "time"])

    def _fill(self, pairs, rain: bool) -> np.ndarray:
        a = np.full(len(self.hours), np.nan)
        for v, val in pairs:
            i = self.pos.get(v)
            if i is None or np.isnan(val):
                continue
            a[max(i - 5, 0): i + 1] = val / 6.0 if rain else val       # six preceding hours, summing back to the 6 h value
        return a

    def _series(self, kind, key):
        if key in self._cache:
            return self._cache[key]
        if kind == "prev":
            _, mkey, loc, var, lead = key
            s = self._fc[mkey]
            try:
                x = s.loc[(loc, var, lead)]
                pairs = [(pd.Timestamp(v).tz_convert("UTC") if pd.Timestamp(v).tzinfo else pd.Timestamp(v, tz="UTC"), val) for v, val in x.items()]
            except KeyError:
                pairs = []
        elif kind == "truth":
            _, loc, var = key
            x = self._truth.loc[loc][var]
            pairs = [(pd.Timestamp(v).tz_convert("UTC") if pd.Timestamp(v).tzinfo else pd.Timestamp(v, tz="UTC"), val) for v, val in x.items()]
        else:
            _, mkey, loc, var = key
            pairs = []
            for lead in (6, 12, 24, 48, 72):
                try:
                    val = self._fc_issue[mkey].loc[(loc, var, self.live_issue, lead)]
                except KeyError:
                    continue
                pairs.append((self.live_issue + pd.Timedelta(hours=lead), float(val)))
        a = self._fill(pairs, var == "rain")
        if kind in ("prev", "live"):          # the synthetic world has sparse valid steps: fill so full days exist
            a = pd.Series(a).ffill().bfill().to_numpy()
        self._cache[key] = a
        return a

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        q = dict(request.url.params)
        host = request.url.host
        if self.all_down:
            return httpx.Response(503, json={"error": True, "reason": "down"})
        mkey = API_TO_SYN.get(q.get("models", ""))
        if "models" in q and (mkey is None or mkey in self.down_models):
            return httpx.Response(400, json={"error": True, "reason": f"invalid model {q['models']}"})
        locs = [LAT_TO_LOC[round(float(x), 4)] for x in q["latitude"].split(",")]
        if "daily" in q:                       # archive daily maxima for normals
            days = pd.date_range(q["start_date"], q["end_date"], freq="D")
            doy = days.dayofyear.to_numpy()
            out = [{"daily": {"time": [d.strftime("%Y-%m-%d") for d in days],
                              q["daily"]: [round(28 + 6 * np.sin(2 * np.pi * x / 365.25), 3) for x in doy]}} for _ in locs]
            return httpx.Response(200, json=out if len(out) > 1 else out[0])
        keys = q["hourly"].split(",")
        if "start_date" in q:
            t0 = pd.Timestamp(q["start_date"], tz="UTC")
            t1 = pd.Timestamp(q["end_date"], tz="UTC") + pd.Timedelta(hours=23)
        else:
            t0 = self.live_issue.normalize()
            t1 = t0 + pd.Timedelta(days=int(q["forecast_days"])) - pd.Timedelta(hours=1)
        i0, i1 = self.pos[t0], self.pos[min(t1, self.hours[-1])]
        times = [t.strftime("%Y-%m-%dT%H:%M") for t in self.hours[i0:i1 + 1]]
        out = []
        for loc in locs:
            h = {"time": times}
            for key in keys:
                m = re.match(r"(.+?)_previous_day(\d+)$", key)
                nvar, k = (m.group(1), int(m.group(2))) if m else (key, 0)
                var = NATIVE_TO_CANON[nvar]
                if "archive" in host:
                    arr = self._series("truth", ("truth", loc, var))
                elif "previous" in host:
                    arr = self._series("prev", ("prev", mkey, loc, var, 24 * k))
                else:
                    arr = self._series("live", ("live", mkey, loc, var))
                h[key] = [None if np.isnan(x) else float(x) for x in arr[i0:i1 + 1]]
            out.append({"hourly": h, "hourly_units": {}})
        return httpx.Response(200, json=out if len(out) > 1 else out[0])


def make_client(fake):
    from weavia.providers.openmeteo import OpenMeteoClient
    return OpenMeteoClient(client=httpx.Client(transport=httpx.MockTransport(fake)), sleep=lambda s: None, retries=1)
