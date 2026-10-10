"""Read-only access to pipeline artifacts. The API never recomputes science on request; it reads
traceable, versioned artifacts produced by pipeline.run()."""
from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path

import joblib
import numpy as np
import pandas as pd

from .config import LEADS, MODELS, REGIMES
from .locations import LOCATIONS, LOC_BY_ID


class Store:
    def __init__(self, data_dir: str | Path = "data"):
        d = Path(data_dir)
        self.dir = d
        self._sig = self.signature()            # what we are about to load; compared by the API to detect new cycles
        self.meta = json.loads((d / "meta.json").read_text())
        if self.meta.get("model_ids"):           # real-data runs use real model ids and leads: align process-wide config
            from . import config
            config.MODELS[:] = self.meta["model_ids"]
            config.LEADS[:] = self.meta["leads"]
        self.live = json.loads((d / "live_status.json").read_text()) if (d / "live_status.json").exists() else None
        self.verification = json.loads((d / "verification.json").read_text())
        dx = d / "daily_extremes.parquet"       # present only after a real-data fit
        self.daily = None
        if dx.exists():
            self.daily = pd.read_parquet(dx)
            self.daily["issue_time"] = pd.to_datetime(self.daily["issue_time"], utc=True)
            self.daily["valid_day"] = pd.to_datetime(self.daily["valid_day"])
        dv = d / "daily_verification.json"
        self.daily_verification = json.loads(dv.read_text()) if dv.exists() else None
        blend = pd.read_parquet(d / "blend.parquet")
        blend["issue_time"] = pd.to_datetime(blend["issue_time"], utc=True)
        blend["valid_time"] = pd.to_datetime(blend["valid_time"], utc=True)
        self.blend = blend.set_index(["location_id", "variable", "issue_time", "lead_h"]).sort_index()
        cases = pd.read_parquet(d / "cases.parquet")
        cases["issue_time"] = pd.to_datetime(cases["issue_time"], utc=True)
        cases["valid_time"] = pd.to_datetime(cases["valid_time"], utc=True)
        self.cases = cases.set_index(["location_id", "issue_time", "lead_h"]).sort_index()
        proba = pd.read_parquet(d / "regime_proba.parquet").set_index("case_id")
        self.proba = proba
        self.skill = pd.read_parquet(d / "skill.parquet")
        ev = pd.read_parquet(d / "events.parquet")
        ev["valid_time"] = pd.to_datetime(ev["valid_time"], utc=True)
        self.events = ev
        self.models = joblib.load(d / "models.joblib")
        self._truth = None
        self._issues = sorted(self.cases[self.cases.split.isin(["test", "live"])].index.get_level_values("issue_time").unique())
        self._spread_q = None

    # ---------------------------------------------------------------- lookups
    @property
    def issues(self) -> list[pd.Timestamp]:
        return self._issues

    @property
    def latest_issue(self) -> pd.Timestamp:
        return self._issues[-1]

    def fmt_issue(self, t: pd.Timestamp) -> str:
        """Daily synthetic issues print as dates. Real-data issues are 6-hourly, so they carry the hour."""
        return f"{t:%Y-%m-%dT%H:%MZ}" if self.meta.get("data_mode") == "real" else f"{t:%Y-%m-%d}"

    def parse_issue(self, s: str | None) -> pd.Timestamp:
        if not s:
            return self.latest_issue
        t = pd.Timestamp(s)
        t = t.tz_localize("UTC") if t.tzinfo is None else t.tz_convert("UTC")
        if "T" in s or " " in s.strip():          # explicit time: exact
            return t
        day = t.normalize()                         # date only: that day's issue (the last one if several)
        same = [i for i in self._issues if i.normalize() == day]
        return same[-1] if same else day

    def signature(self) -> tuple:
        """Changes whenever a live cycle rewrites artifacts, so a long-running API can reload."""
        return tuple((self.dir / f).stat().st_mtime_ns if (self.dir / f).exists() else 0
                     for f in ("blend.parquet", "cases.parquet", "live_status.json", "meta.json", "daily_extremes.parquet", "daily_verification.json"))

    def nearest_location(self, lat: float, lon: float):
        best = min(LOCATIONS, key=lambda l: (l.lat - lat) ** 2 + ((l.lon - lon) * np.cos(np.radians(lat))) ** 2)
        dist_km = 111.0 * float(np.hypot(best.lat - lat, (best.lon - lon) * np.cos(np.radians(lat))))
        return best, dist_km

    def row(self, loc: str, var: str, issue: pd.Timestamp, lead: int) -> pd.Series:
        try:
            return self.blend.loc[(loc, var, issue, lead)]
        except KeyError as e:
            raise KeyError(f"no forecast for {loc}/{var}/{issue:%Y-%m-%d}/+{lead}h") from e

    def case_row(self, loc: str, issue: pd.Timestamp, lead: int) -> pd.Series:
        return self.cases.loc[(loc, issue, lead)]

    def proba_row(self, case_id: int) -> np.ndarray:
        return self.proba.loc[case_id].values.astype(float)

    def timeline(self, loc: str, var: str, issue: pd.Timestamp) -> pd.DataFrame:
        return self.blend.loc[(loc, var, issue)].sort_index()

    # ---------------------------------------------------------------- derived
    def spread_quantiles(self, var: str, lead: int) -> tuple[float, float]:
        """Terciles-ish thresholds of weighted model spread on TRAIN rows (LOW/MODERATE/HIGH)."""
        if self._spread_q is None and (self.dir / "spread_q.json").exists():     # demo snapshots ship these precomputed
            raw = json.loads((self.dir / "spread_q.json").read_text())
            self._spread_q = {(k.split("|")[0], int(k.split("|")[1])): tuple(v) for k, v in raw.items()}
        if self._spread_q is None:
            b = self.blend.reset_index()
            tr = b[b.split == "train"]
            self._spread_q = {k: (float(g.spread.quantile(0.50)), float(g.spread.quantile(0.85)))
                              for k, g in tr.groupby(["variable", "lead_h"])}
        return self._spread_q[(var, lead)]

    def disagreement_level(self, var: str, lead: int, spread: float) -> str:
        lo, hi = self.spread_quantiles(var, lead)
        return "LOW" if spread < lo else ("MODERATE" if spread < hi else "HIGH")

    def truth(self) -> pd.DataFrame:
        if self._truth is None:
            t = pd.read_parquet(self.dir / "truth.parquet")
            t["time"] = pd.to_datetime(t["time"], utc=True)
            self._truth = t
        return self._truth

    def test_slice(self, var: str, lead: int) -> pd.DataFrame:
        key = (var, lead)
        if not hasattr(self, "_ts"):
            self._ts = {}
        if key not in self._ts:
            b = self.blend.xs(var, level="variable").reset_index()
            self._ts[key] = b[(b.split == "test") & (b.lead_h == lead)].reset_index(drop=True)
        return self._ts[key]

    def model_meta(self, mid: str) -> dict:
        return self.meta["models"][mid]


@lru_cache(maxsize=1)
def get_store(data_dir: str = "data") -> Store:
    return Store(data_dir)
