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
from ..explain import explain as run_explain, skill_agg
from ..lab import simulate
from ..locations import LOC_BY_ID, LOCATIONS
from ..store import Store

DATA_DIR = os.environ.get("WEAVIA_DATA", "data")
app = FastAPI(title="WEAVIA API", version="0.1.0")
app.add_middleware(CORSMiddleware, allow_origins=os.environ.get("WEAVIA_CORS", "*").split(","),
                   allow_methods=["*"], allow_headers=["*"])
_store: Store | None = None


def S() -> Store:
    global _store
    if _store is None:
        try:
            _store = Store(DATA_DIR)
        except FileNotFoundError as e:
            raise HTTPException(503, f"artifacts missing in '{DATA_DIR}': run the pipeline first ({e})")
    return _store


def _f(x, nd=3):
    try:
        x = float(x)
    except (TypeError, ValueError):
        return None
    return None if np.isnan(x) else round(x, nd)


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
        raise HTTPException(404, f"issue {t:%Y-%m-%d} not in served (test-slice) range {st.issues[0]:%Y-%m-%d}..{st.issues[-1]:%Y-%m-%d}")
    return st, t


# ------------------------------------------------------------------ response models
class Provenance(BaseModel):
    data_mode: str
    data_notice: str
    model_version: str
    generated_at: str


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
        return {"status": "ok", "model_version": st.meta["model_version"], "data_mode": st.meta["data_mode"]}
    except HTTPException as e:
        return {"status": "no_artifacts", "detail": e.detail}


@app.get("/api/v1/meta", response_model=Meta)
def meta():
    st = S()
    m = st.meta
    return {
        "provenance": {k: str(m[k]) for k in ("data_mode", "data_notice", "model_version", "generated_at")},
        "issues": [f"{t:%Y-%m-%d}" for t in st.issues], "latest_issue": f"{st.latest_issue:%Y-%m-%d}",
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
            "observed_regime": str(st.row(location_id, "temp", t, lead)["regime_obs"]),
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
