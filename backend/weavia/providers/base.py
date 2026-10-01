from __future__ import annotations
from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Sequence

import pandas as pd

from ..config import LEADS
from ..harmonize import SCHEMA, ValidationReport, to_canonical, validate_frame
from ..locations import Location


@dataclass
class FetchSpec:
    locations: Sequence[Location]
    start: pd.Timestamp | None = None
    end: pd.Timestamp | None = None
    leads: Sequence[int] = tuple(LEADS)


@dataclass
class ModelMeta:
    model_id: str
    name: str
    kind: str            # NWP | AI | ENSEMBLE
    label: str
    resolution_deg: float
    provider: str
    synthetic: bool


class ForecastProvider(ABC):
    """fetch() -> raw native frame; normalize() -> canonical schema; validate() -> report.

    Raw frame columns (native names / units / local naive time):
        run_time, valid_time, location_id, native_var, value
    """
    meta: ModelMeta
    var_map: dict          # native_var -> (canonical variable, native unit)
    tz_offset_hours: float = 0.0

    @abstractmethod
    def fetch(self, spec: FetchSpec) -> pd.DataFrame: ...

    def normalize(self, raw: pd.DataFrame) -> pd.DataFrame:
        raw = raw[raw.native_var.isin(self.var_map)].copy()
        shift = pd.Timedelta(hours=self.tz_offset_hours)
        run = (pd.to_datetime(raw["run_time"]) - shift).dt.tz_localize("UTC")
        valid = (pd.to_datetime(raw["valid_time"]) - shift).dt.tz_localize("UTC")
        out = pd.DataFrame({
            "model_id": self.meta.model_id,
            "issue_time": run.values,
            "valid_time": valid.values,
            "location_id": raw["location_id"].values,
        })
        out["issue_time"] = pd.to_datetime(out["issue_time"], utc=True)
        out["valid_time"] = pd.to_datetime(out["valid_time"], utc=True)
        out["lead_h"] = ((out["valid_time"] - out["issue_time"]).dt.total_seconds() // 3600).astype(int)
        variable, value = [], raw["value"].to_numpy(dtype=float).copy()
        nv = raw["native_var"].to_numpy()
        for nvar, (cvar, unit) in self.var_map.items():
            m = nv == nvar
            if m.any():
                value[m] = to_canonical(value[m], unit)
        variable = [self.var_map[x][0] for x in nv]
        out["variable"] = variable
        out["value"] = value
        return out[SCHEMA]

    def validate(self, df: pd.DataFrame) -> ValidationReport:
        return validate_frame(df, self.meta.model_id)

    def get_forecasts(self, spec: FetchSpec):
        raw = self.fetch(spec)
        df = self.normalize(raw)
        return df, self.validate(df)


class ObservationProvider(ABC):
    @abstractmethod
    def fetch(self, spec: FetchSpec) -> pd.DataFrame:
        """Return canonical long frame: timestamp(UTC), location_id, variable, value, source."""
