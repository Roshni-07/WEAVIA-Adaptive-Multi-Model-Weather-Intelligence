"""WEAVIA API v1. Reads pipeline artifacts through Store only; no science is recomputed here."""
from __future__ import annotations

import os
from typing import Any

import numpy as np
import pandas as pd
from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

from ..autopsy import AUTOPSY_LEADS, autopsy as run_autopsy, list_events
from ..config import BLEND_VARS, CANON_UNIT, EVENT_THRESH, LEADS, MODELS, REGIMES, VAR_LABEL
from .. import imd_criteria
from ..explain import explain as run_explain, skill_agg
from ..extremes import jsonable, regional_outlook
from ..lab import simulate
from .ratelimit import RateLimitMiddleware
from ..locations import LOC_BY_ID, LOCATIONS
from ..store import Store

DATA_DIR = os.environ.get("WEAVIA_DATA", "data")
app = FastAPI(title="WEAVIA API", version="0.1.0")
app.add_middleware(CORSMiddleware, allow_origins=os.environ.get("WEAVIA_CORS", "*").split(","),
                   allow_methods=["*"], allow_headers=["*"])
app.add_middleware(RateLimitMiddleware)     # added last = outermost: 429s still carry CORS headers
_store: Store | None = None


def S() -> Store:
    """The current Store. Reloads when a live cycle has rewritten the artifacts (cheap stat check per request)."""
    global _store
    if _store is not None and _store._sig != _store_sig():
        _store = None
    if _store is None:
        try:
            _store = Store(DATA_DIR)
        except FileNotFoundError as e:
            raise HTTPException(503, f"artifacts missing in '{DATA_DIR}': run the pipeline first ({e})")
    return _store


def _store_sig() -> tuple:
    from pathlib import Path
    d = Path(DATA_DIR)
    return tuple((d / f).stat().st_mtime_ns if (d / f).exists() else 0
                 for f in ("blend.parquet", "cases.parquet", "live_status.json", "meta.json", "daily_extremes.parquet", "daily_verification.json"))


STALE_AFTER_MIN = 9 * 60          # one 6 h cycle plus 3 h grace


def live_block(st: Store) -> dict | None:
    """Freshness of the live product, computed at request time. None for synthetic or never-cycled data."""
    if st.live is None:
        return None
    out = dict(st.live)
    try:
        fetched = pd.Timestamp(out["fetched_at"])
        age = (pd.Timestamp.now(tz="UTC") - fetched).total_seconds() / 60
        out["age_minutes"] = round(age, 1)
        out["stale"] = bool(age > STALE_AFTER_MIN) or out.get("state") == "failed"
    except Exception:                                   # noqa: BLE001 - never let a bad status file break the API
        out["age_minutes"], out["stale"] = None, True
    return out

def _f(x, nd=3):
    try:
        x = float(x)
    except (TypeError, ValueError):
        return None
    return None if np.isnan(x) else round(x, nd)


def _regime_or_none(x):
    return None if x is None or (isinstance(x, float) and np.isnan(x)) else str(x)


def _ctx(issue: str | None, lead: int, var: str | None = None, loc: str | None = None):
    st = S()
    if lead not in LEADS:
        raise HTTPException(422, f"lead must be one of {LEADS}")
    if var is not None and var not in BLEND_VARS:
        raise HTTPException(422, f"variable must be one of {BLEND_VARS}")
    if loc is not None and loc not in LOC_BY_ID:
        raise HTTPException(404, f"unknown location {loc}")
    t = st.parse_issue(issue)
    if t not in set(st.issues):
        raise HTTPException(404, f"issue {st.fmt_issue(t)} not in served range {st.fmt_issue(st.issues[0])}..{st.fmt_issue(st.issues[-1])}")
    return st, t


# ------------------------------------------------------------------ response models
class Provenance(BaseModel):
    data_mode: str
    data_notice: str
    model_version: str
    generated_at: str
    truth_source: str | None = None
    live: dict[str, Any] | None = None


class Meta(BaseModel):
    provenance: Provenance
    issues: list[str]
    latest_issue: str
    leads: list[int]
    variables: dict[str, dict[str, Any]]
    models: list[dict[str, Any]]
    regimes: list[str]
    locations: list[dict[str, Any]]


class MapPoint(BaseModel):
    location_id: str
    name: str
    lat: float
    lon: float
    region: str
    regime: str
    regime_confidence: float | None
    risk: float = Field(description="max calibrated event probability across variables, 0..1")
    risk_variable: str | None
    top_model: dict[str, Any]
    weights: dict[str, float]
    vars: dict[str, dict[str, float | None]]


class MapOut(BaseModel):
    issue_time: str
    lead_h: int
    valid_time: str
    units: dict[str, str]
    points: list[MapPoint]
    weight_flow: dict[str, float] = Field(description="mean weight per model across locations, rain/temp/wind averaged")


# ------------------------------------------------------------------ endpoints
@app.get("/api/v1/health")
def health():
    try:
        st = S()
        live = live_block(st)
        status = "ok" if not (live and live["stale"]) else "stale"
        return {"status": status, "model_version": st.meta["model_version"], "data_mode": st.meta["data_mode"], "live": live}
    except HTTPException as e:
        return {"status": "no_artifacts", "detail": e.detail}


@app.get("/api/v1/meta", response_model=Meta)
def meta():
    st = S()
    m = st.meta
    return {
        "provenance": {**{k: str(m[k]) for k in ("data_mode", "data_notice", "model_version", "generated_at")},
                       "truth_source": m.get("truth_source"), "live": live_block(st)},
        "issues": [st.fmt_issue(t) for t in st.issues], "latest_issue": st.fmt_issue(st.latest_issue),
        "leads": LEADS,
        "variables": {v: {"label": VAR_LABEL[v], "unit": CANON_UNIT[v], "event_threshold": EVENT_THRESH[v]} for v in BLEND_VARS},
        "models": [{"model_id": k, **v} for k, v in m["models"].items()],
        "regimes": REGIMES,
        "locations": [{"id": l.id, "name": l.name, "lat": l.lat, "lon": l.lon, "region": l.region, "coastal": l.coastal} for l in LOCATIONS],
    }


@app.get("/api/v1/map", response_model=MapOut)
def map_layer(issue: str | None = None, lead: int = 24):
    """All-location snapshot that drives every globe layer (fields, hotspots, weight flow)."""
    st, t = _ctx(issue, lead)
    sl = st.blend.xs((t, lead), level=("issue_time", "lead_h"))
    pts, wsum, valid = [], np.zeros(len(MODELS)), None
    for l in LOCATIONS:
        vv, risk, rvar, wv = {}, 0.0, None, np.zeros(len(MODELS))
        for v in BLEND_VARS:
            r = sl.loc[(l.id, v)]
            valid = r["valid_time"]
            w = np.array([r[f"w_{m}"] for m in MODELS], float)
            wv += w / len(BLEND_VARS)
            ep = _f(r.get("event_prob"))
            vv[v] = {"value": _f(r["blend"]), "p10": _f(r["p10"]), "p90": _f(r["p90"]), "confidence": _f(r["confidence"]),
                     "spread": _f(r["spread"]), "event_prob": ep}
            if ep is not None and ep > risk:
                risk, rvar = ep, v
        r0 = sl.loc[(l.id, "temp")]
        top = int(np.argmax(wv))
        wsum += wv
        pts.append({"location_id": l.id, "name": l.name, "lat": l.lat, "lon": l.lon, "region": l.region,
                    "regime": str(r0["regime_pred"]), "regime_confidence": _f(r0["regime_conf"]), "risk": round(risk, 4),
                    "risk_variable": rvar, "top_model": {"model_id": MODELS[top], "name": st.model_meta(MODELS[top])["name"], "weight": round(float(wv[top]), 3)},
                    "weights": {m: round(float(x), 4) for m, x in zip(MODELS, wv)}, "vars": vv})
    wsum /= len(LOCATIONS)
    return {"issue_time": t.isoformat(), "lead_h": lead, "valid_time": pd.Timestamp(valid).isoformat(), "units": CANON_UNIT,
            "points": pts, "weight_flow": {m: round(float(x), 4) for m, x in zip(MODELS, wsum)}}


@app.get("/api/v1/overview")
def overview(issue: str | None = None, lead: int = 24):
    """National headline: alerts ranked by calibrated event probability + verification verdicts."""
    mp = map_layer(issue, lead)
    st = S()
    alerts = []
    for p in mp["points"]:
        for v in BLEND_VARS:
            ep = p["vars"][v]["event_prob"]
            if ep is not None:
                alerts.append({"location_id": p["location_id"], "name": p["name"], "variable": v, "event_prob": ep,
                               "forecast": p["vars"][v]["value"], "unit": CANON_UNIT[v], "threshold": EVENT_THRESH[v],
                               "above_alert_threshold": ep >= st.meta["alert_thr"].get(v, 1.1)})
    alerts.sort(key=lambda a: -a["event_prob"])
    return {"issue_time": mp["issue_time"], "lead_h": lead, "alerts": alerts[:12], "alert_thresholds": st.meta["alert_thr"],
            "weight_flow": mp["weight_flow"], "provenance": meta()["provenance"]}


@app.get("/api/v1/forecast")
def forecast(location_id: str, variable: str = "rain", issue: str | None = None, lead: int = 24):
    st, t = _ctx(issue, lead, variable, location_id)
    ex = run_explain(st, location_id, variable, t, lead)
    return {k: ex[k] for k in ("case", "forecast", "disagreement", "regime", "provenance")}


@app.get("/api/v1/timeline")
def timeline(location_id: str, variable: str = "rain", issue: str | None = None):
    """Forecast across all leads for one issue, with P10-P90 band and (verification-only) observed value."""
    st, t = _ctx(issue, 24, variable, location_id)
    tl = st.timeline(location_id, variable, t).reset_index()
    rows = []
    for _, r in tl.iterrows():
        rows.append({"lead_h": int(r.lead_h), "valid_time": pd.Timestamp(r.valid_time).isoformat(), "blend": _f(r.blend),
                     "p10": _f(r.p10), "p90": _f(r.p90), "equal": _f(r.blend_equal), "observed": _f(r.obs),
                     "confidence": _f(r.confidence), "event_prob": _f(r.get("event_prob")),
                     "models": {m: _f(r[f"f_{m}"]) for m in MODELS}, "weights": {m: _f(r[f"w_{m}"], 4) for m in MODELS}})
    return {"location_id": location_id, "variable": variable, "unit": CANON_UNIT[variable], "issue_time": t.isoformat(), "series": rows}


@app.get("/api/v1/trust")
def trust(location_id: str, variable: str = "rain", issue: str | None = None, lead: int = 24):
    st, t = _ctx(issue, lead, variable, location_id)
    ex = run_explain(st, location_id, variable, t, lead)
    return {"case": ex["case"], "models": ex["models"], "meta_model_tau": ex["meta_model_tau"]}


@app.get("/api/v1/regime")
def regime(location_id: str, issue: str | None = None, lead: int = 24):
    st, t = _ctx(issue, lead, None, location_id)
    cr = st.case_row(location_id, t, lead)
    pr = st.proba_row(int(cr["case_id"]))
    order = np.argsort(-pr)
    reg = st.verification.get("regime")
    return {"location_id": location_id, "issue_time": t.isoformat(), "lead_h": lead, "label": REGIMES[int(order[0])],
            "confidence": _f(pr[order[0]]), "probabilities": {r: _f(pr[i], 4) for i, r in enumerate(REGIMES)},
            "observed_regime": _regime_or_none(st.row(location_id, "temp", t, lead)["regime_obs"]),
            "classifier_verification": reg}


@app.get("/api/v1/explain")
def explain(location_id: str, variable: str = "rain", issue: str | None = None, lead: int = 24):
    st, t = _ctx(issue, lead, variable, location_id)
    return run_explain(st, location_id, variable, t, lead)


@app.get("/api/v1/skill-atlas")
def skill_atlas(variable: str = "rain", lead: int = 24):
    """Historical verified MAE per model x regime (and per region), computed from training-period error memory."""
    st, _ = _ctx(None, lead, variable)
    sk = st.skill
    sk = sk[(sk.variable == variable) & (sk.lead_h == lead)]
    cells = []
    for (reg, mid), g in sk.groupby(["regime", "model_id"]):
        n = g.n.sum()
        if n:
            cells.append({"regime": reg, "model_id": mid, "mae": _f(g.sae.sum() / n), "bias": _f(g.sum_err.sum() / n), "n": int(n)})
    regions = {}
    for rg in sorted({l.region for l in LOCATIONS}):
        regions[rg] = {m: v["mae"] for m, v in skill_agg(st, variable, lead, region=rg).items()}
    return {"variable": variable, "unit": CANON_UNIT[variable], "lead_h": lead, "cells": cells, "by_region": regions,
            "models": [{"model_id": k, **v} for k, v in st.meta["models"].items()], "regimes": REGIMES}


@app.get("/api/v1/verification")
def verification():
    st = S()
    return {"provenance": meta()["provenance"], "verification": st.verification, "splits": st.meta["splits"]}


EXTREME_NOTE = ("Indicator, not an IMD declaration. Normals are reanalysis-based. Regions are WEAVIA's coarse groups, "
                "not IMD sub-divisions.")


def _no_extremes():
    return HTTPException(404, "No daily extremes in this dataset. They are built by `python -m weavia.live fit` "
                              "(real-data mode). Synthetic runs do not produce them.")


@app.get("/api/v1/extremes")
def extremes_view(issue: str | None = None, lead_day: int = Query(1, ge=1, le=3)):
    """IMD-aligned daily guidance for one issue and lead day: heat-wave indicator per station (daily maximum vs the
    station's normal and terrain class), 24 h rainfall class and heavy-rain probability, and a regional heat-wave
    outlook across the issue's lead days."""
    st = S()
    if st.daily is None:
        raise _no_extremes()
    d = st.daily
    live = d[d.split == "live"]
    t = st.parse_issue(issue) if issue else (live.issue_time.max() if len(live) else st.latest_issue)
    rows = d[d.issue_time == t]
    if rows.empty and issue is None and len(live):
        rows = live[live.issue_time == live.issue_time.max()]
    if rows.empty:
        raise HTTPException(404, f"no daily extremes for issue {st.fmt_issue(t)}")
    models = list(MODELS)
    day_rows = rows[rows.lead_day == lead_day]
    stations = []
    for lid, g in day_rows.groupby("location_id"):
        loc = LOC_BY_ID[lid]
        tm, rn = g[g.variable == "tmax"], g[g.variable == "rain24"]
        item: dict[str, Any] = {"location_id": lid, "name": loc.name, "region": loc.region, "terrain": loc.terrain}
        if len(tm):
            r = tm.iloc[0]
            item["tmax"] = {"blend": _f(r.blend, 1), "p10": _f(r.p10, 1), "p90": _f(r.p90, 1), "normal": _f(r.normal, 1),
                            "departure": _f(r.blend - r.normal, 1) if pd.notna(r.normal) else None,
                            "heat_wave_class": None if pd.isna(r.cls_blend) else int(r.cls_blend),
                            "p_heat_wave": _f(r.p_event), "p_severe": _f(r.p_severe),
                            "models": {m: _f(r[f"f_{m}"], 1) for m in models}, "equal": _f(r.equal, 1)}
        if len(rn):
            r = rn.iloc[0]
            item["rain24"] = {"blend": _f(r.blend, 1), "p10": _f(r.p10, 1), "p90": _f(r.p90, 1), "imd_class": r.rain_class,
                              "p_heavy": _f(r.p_event), "p_very_heavy": _f(r.p_severe),
                              "models": {m: _f(r[f"f_{m}"], 1) for m in models}}
        stations.append(item)
    stations.sort(key=lambda x: -(x.get("tmax", {}).get("p_heat_wave") or 0))
    valid = day_rows.valid_day.min() if len(day_rows) else None
    return {"issue_time": st.fmt_issue(t), "lead_day": lead_day, "valid_day": None if valid is None else f"{valid:%Y-%m-%d}",
            "available_lead_days": sorted(int(x) for x in rows.lead_day.unique()), "status": EXTREME_NOTE,
            "stations": stations, "regional_outlook": regional_outlook(rows),
            "definitions": imd_criteria.definitions(), "provenance": meta()["provenance"]}


@app.get("/api/v1/extremes/verification")
def extremes_verification():
    """Held-out verification of the daily products with date-block bootstrap CIs. Event results say
    insufficient_events when there are too few observed events for any claim."""
    st = S()
    if st.daily_verification is None:
        raise _no_extremes()
    return {"verification": jsonable(st.daily_verification), "status": EXTREME_NOTE, "definitions": imd_criteria.definitions(),
            "provenance": meta()["provenance"]}


@app.get("/api/v1/events")
def events(variable: str | None = None, limit: int = 40):
    return list_events(S(), variable, limit)


@app.get("/api/v1/autopsy/{event_id}")
def autopsy_route(event_id: str, lead: int = 24):
    if lead not in AUTOPSY_LEADS:
        raise HTTPException(422, f"lead must be one of {list(AUTOPSY_LEADS)}")
    try:
        return run_autopsy(S(), event_id, lead)
    except KeyError:
        raise HTTPException(404, f"unknown event {event_id}")


class LabIn(BaseModel):
    location_id: str
    variable: str = "rain"
    issue: str | None = None
    lead: int = 24
    weights: dict[str, float]
    scope: str = Field("global", pattern="^(global|region|location)$")
    same_regime: bool = False


@app.post("/api/v1/lab/simulate")
def lab_simulate(b: LabIn):
    st, t = _ctx(b.issue, b.lead, b.variable, b.location_id)
    try:
        return simulate(st, b.location_id, b.variable, t, b.lead, b.weights, b.scope, b.same_regime)
    except ValueError as e:
        raise HTTPException(422, str(e))
