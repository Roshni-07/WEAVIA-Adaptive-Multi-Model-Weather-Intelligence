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
        self.meta = json.loads((d / "meta.json").read_text())
        self.verification = json.loads((d / "verification.json").read_text())
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
        self._issues = sorted(self.cases[self.cases.split == "test"].index.get_level_values("issue_time").unique())
        self._spread_q = None

    # ---------------------------------------------------------------- lookups
    @property
    def issues(self) -> list[pd.Timestamp]:
        return self._issues

    @property
    def latest_issue(self) -> pd.Timestamp:
        return self._issues[-1]

    def parse_issue(self, s: str | None) -> pd.Timestamp:
        if not s:
            return self.latest_issue
        t = pd.Timestamp(s)
        t = t.tz_localize("UTC") if t.tzinfo is None else t.tz_convert("UTC")
        return t.normalize()

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
