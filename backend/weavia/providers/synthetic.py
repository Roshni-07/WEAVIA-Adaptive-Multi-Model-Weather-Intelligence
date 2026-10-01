"""Synthetic providers. They expose *native* names, units and time zones so the
normalisation / harmonisation code is exercised exactly as it would be for real sources."""
from __future__ import annotations

import pandas as pd

from ..harmonize import from_canonical
from ..synthetic.model_specs import MODEL_META
from ..synthetic.world import SyntheticWorld
from .base import FetchSpec, ForecastProvider, ModelMeta, ObservationProvider


class SyntheticModelProvider(ForecastProvider):
    def __init__(self, model_id: str, world: SyntheticWorld):
        m = MODEL_META[model_id]
        self.world = world
        self.model_id = model_id
        self.var_map = m["vars"]
        self.tz_offset_hours = m["tz_offset"]
        self.meta = ModelMeta(model_id, m["name"], m["kind"], m["label"], m["res_deg"], "synthetic", True)

    def fetch(self, spec: FetchSpec) -> pd.DataFrame:
        canon = self.world.forecasts[self.model_id]
        ids = {l.id for l in spec.locations}
        canon = canon[canon.location_id.isin(ids) & canon.lead_h.isin(list(spec.leads))]
        if spec.start is not None:
            canon = canon[canon.issue_time >= spec.start]
        if spec.end is not None:
            canon = canon[canon.issue_time <= spec.end]
        inv = {cvar: (nvar, unit) for nvar, (cvar, unit) in self.var_map.items()}
        shift = pd.Timedelta(hours=self.tz_offset_hours)
        parts = []
        for cvar, (nvar, unit) in inv.items():
            d = canon[canon.variable == cvar]
            parts.append(pd.DataFrame({
                "run_time": (d.issue_time.dt.tz_localize(None) + shift).values,      # native local naive time
                "valid_time": (d.valid_time.dt.tz_localize(None) + shift).values,
                "location_id": d.location_id.values,
                "native_var": nvar,
                "value": from_canonical(d.value.values, unit),
            }))
        return pd.concat(parts, ignore_index=True)


class SyntheticObservationProvider(ObservationProvider):
    def __init__(self, world: SyntheticWorld):
        self.world = world

    def fetch(self, spec: FetchSpec) -> pd.DataFrame:
        o = self.world.observations()
        return o[o.location_id.isin({l.id for l in spec.locations})].reset_index(drop=True)
