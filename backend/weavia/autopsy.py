"""Forecast Autopsy: forensic comparison of a forecast with what happened, plus the skill-memory
update that followed. All diagnosis sentences are generated from stored numbers."""
from __future__ import annotations

import numpy as np
import pandas as pd

from .config import CANON_UNIT, EVENT_THRESH, MODELS, REGIMES, VAR_LABEL
from .explain import explain
from .locations import LOC_BY_ID
from .store import Store

AUTOPSY_LEADS = (24, 48, 72)


def list_events(store: Store, variable: str | None = None, limit: int = 40) -> list[dict]:
    ev = store.events
    if variable:
        ev = ev[ev.variable == variable]
    out = []
    for _, r in ev.head(limit).iterrows():
        out.append({"event_id": r.event_id, "location_id": r.location_id, "location": LOC_BY_ID[r.location_id].name,
                    "variable": r.variable, "event_type": r.event_type, "kind": r.kind, "unit": CANON_UNIT[r.variable],
                    "valid_time": r.valid_time.isoformat(), "observed_value": round(float(r.observed_value), 2),
                    "severity": round(float(r.severity), 2)})
    return out


def autopsy(store: Store, event_id: str, lead: int = 24) -> dict:
    if lead not in AUTOPSY_LEADS:
        raise ValueError(f"lead must be one of {AUTOPSY_LEADS}")
    ev = store.events[store.events.event_id == event_id]
    if ev.empty:
        raise KeyError(event_id)
    ev = ev.iloc[0]
    loc_id, var = ev.location_id, ev.variable
    valid = ev.valid_time
    issue = valid - pd.Timedelta(hours=lead)
    ex = explain(store, loc_id, var, issue, lead)
    b = store.row(loc_id, var, issue, lead)
    unit = CANON_UNIT[var]
    obs = float(b["obs"])
    blend, p10, p90 = float(b["blend"]), float(b["p10"]), float(b["p90"])
    err = blend - obs
    regime_obs = str(b["regime_obs"])
    regime_pred = ex["regime"]["label"]

    per_model = []
    for d in ex["models"]:
        e = d["forecast"] - obs
        per_model.append({"model_id": d["model_id"], "name": d["name"], "forecast": d["forecast"], "error": round(e, 3),
                          "abs_error": round(abs(e), 3), "weight": d["weight"],
                          "verdict": "close" if abs(e) <= max(0.15 * abs(obs), 1.0 if var != "rain" else 2.0) else ("under" if e < 0 else "over")})
    closest = min(per_model, key=lambda d: d["abs_error"])
    all_under = all(d["error"] < 0 for d in per_model)
    all_over = all(d["error"] > 0 for d in per_model)

    if obs > p90:
        primary = f"Observed {VAR_LABEL[var].lower()} exceeded the upper forecast range (P90 {p90:.1f} {unit})."
        direction = "underestimated"
    elif obs < p10:
        primary = f"Observed {VAR_LABEL[var].lower()} fell below the lower forecast range (P10 {p10:.1f} {unit})."
        direction = "overestimated"
    else:
        primary = f"Observed value stayed inside the WEAVIA P10–P90 range ({p10:.1f}–{p90:.1f} {unit})."
        direction = "within range"

    findings = []
    findings.append({"step": 1, "title": "Regime classification",
                     "text": (f"WEAVIA classified the atmosphere as {regime_pred.replace('_',' ')} "
                              f"({ex['regime']['confidence']*100:.0f}%); the observed regime was {regime_obs.replace('_',' ')}."
                              + ("" if regime_pred == regime_obs else " The regime was MISSED by the detector."))})
    findings.append({"step": 2, "title": "Model behaviour",
                     "text": "; ".join(f"{d['name']} {d['forecast']:.1f} ({d['verdict']})" for d in per_model) + f"; observed {obs:.1f} {unit}."})
    if all_under or all_over:
        findings.append({"step": 3, "title": "Shared bias",
                         "text": f"All four models {'under' if all_under else 'over'}estimated — a common-mode error that weighting alone cannot remove."})
    else:
        w_close = closest["weight"]
        findings.append({"step": 3, "title": "Weight allocation",
                         "text": (f"{closest['name']} was closest ({closest['abs_error']:.1f} {unit}) and held {w_close*100:.0f}% of the trust"
                                  + (" — under-weighted relative to its accuracy on this event." if w_close < 0.25 else "."))})
    findings.append({"step": 4, "title": "Disagreement & confidence",
                     "text": f"Model disagreement was {ex['disagreement']['level']}; WEAVIA confidence {ex['forecast']['confidence']*100:.0f}% ({ex['forecast']['confidence_definition']})."})
    findings.append({"step": 5, "title": "Outcome vs range", "text": primary})

    # forecast evolution for the same valid time
    evolution = []
    for L in AUTOPSY_LEADS:
        try:
            r = store.row(loc_id, var, valid - pd.Timedelta(hours=L), L)
            evolution.append({"lead_h": L, "issue_time": (valid - pd.Timedelta(hours=L)).isoformat(),
                              "blend": round(float(r["blend"]), 3), "p10": round(float(r["p10"]), 3), "p90": round(float(r["p90"]), 3),
                              "equal": round(float(r["blend_equal"]), 3),
                              "models": {m: round(float(r[f"f_{m}"]), 3) for m in MODELS},
                              "top_model": MODELS[int(np.argmax([r[f"w_{m}"] for m in MODELS]))]})
        except KeyError:
            pass

    # skill-memory update: same loc/var/lead, first issue at the valid time (error now verified)
    memory = None
    try:
        nxt = store.row(loc_id, var, valid, lead)
        memory = {
            "next_issue_time": valid.isoformat(),
            "models": [{"model_id": m, "name": store.model_meta(m)["name"],
                        "recent_mae_before": _r(b[f"rec_{m}"]), "recent_mae_after": _r(nxt[f"rec_{m}"]),
                        "weight_before": _r(b[f"w_{m}"]), "weight_after": _r(nxt[f"w_{m}"])} for m in MODELS],
        }
        shifts = sorted(memory["models"], key=lambda d: abs((d["weight_after"] or 0) - (d["weight_before"] or 0)), reverse=True)
        s = shifts[0]
        lesson = (f"After this event was verified, {s['name']}'s recent error moved {s['recent_mae_before']} → {s['recent_mae_after']} "
                  f"and its trust at the next +{lead}h forecast for {LOC_BY_ID[loc_id].name} moved "
                  f"{(s['weight_before'] or 0)*100:.0f}% → {(s['weight_after'] or 0)*100:.0f}%.")
    except KeyError:
        lesson = "No subsequent forecast available to show the skill-memory update."
    if all_under or all_over:
        lesson += " A shared bias suggests adding a bias-correction stage for this regime; it cannot be fixed by reweighting."
    return {
        "event": {"event_id": event_id, "location": LOC_BY_ID[loc_id].name, "location_id": loc_id, "variable": var,
                  "event_type": ev.event_type, "unit": unit, "valid_time": valid.isoformat(), "lead_h": lead,
                  "issue_time": issue.isoformat()},
        "summary": {"observed": round(obs, 3), "weavia": round(blend, 3), "error": round(err, 3),
                    "p10": round(p10, 3), "p90": round(p90, 3), "direction": direction,
                    "equal_weight": round(float(b["blend_equal"]), 3),
                    "threshold": EVENT_THRESH[var], "exceeded_threshold": bool(obs >= EVENT_THRESH[var]),
                    "event_probability": ex["forecast"]["event_probability"]},
        "regime": {"predicted": regime_pred, "observed": regime_obs, "confidence": ex["regime"]["confidence"]},
        "models": per_model, "findings": findings, "evolution": evolution,
        "skill_memory": memory, "lesson": lesson, "explanation": ex,
    }


def _r(x):
    return None if x is None or (isinstance(x, float) and np.isnan(x)) else round(float(x), 4)
