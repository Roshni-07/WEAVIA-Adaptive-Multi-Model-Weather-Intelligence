"""'Why this forecast?' — every number comes from stored artifacts; text is template-generated
from those numbers (no LLM involved, nothing invented)."""
from __future__ import annotations

import numpy as np
import pandas as pd

from .config import BLEND_VARS, CANON_UNIT, MODELS, REGIMES, SPREAD_FLOOR, VAR_LABEL, tolerance
from .locations import LOC_BY_ID, REGION_LIST
from .store import Store
from .trust import BASE_FEATS

M = len(MODELS)
HUMAN = {
    "hist": "verified historical error", "rec": "recent 7-day error", "histb": "historical bias",
    "recb": "recent bias", "dev": "deviation from consensus", "abs_dev": "distance from consensus",
    "spread": "model spread", "rel_spread": "relative model spread", "f": "own forecast value",
    "ens": "ensemble-mean value", "lead_h": "lead time", "regime_code": "predicted regime",
    "regime_conf": "regime confidence", "model_idx": "model identity", "lat": "latitude", "lon": "longitude",
    "m_sin": "season", "m_cos": "season", "region_code": "region", "dT": "temperature tendency",
    "dP": "pressure tendency", "ens_temp": "temperature", "ens_rh": "humidity", "ens_pressure": "pressure",
    "ens_wind": "wind", "ens_rain": "rainfall signal",
}


def _f(x, nd=4):
    return None if x is None or (isinstance(x, float) and np.isnan(x)) else round(float(x), nd)


def feat_label(k: str) -> str:
    if k.startswith("p_"):
        return f"{k[2:].replace('_', ' ').lower()}-regime probability"
    return HUMAN.get(k, k)


def rebuild_long(store: Store, loc_id: str, var: str, issue, lead: int):
    """Re-create the exact meta-model feature rows for one case (must equal the training pipeline)."""
    b = store.row(loc_id, var, issue, lead)
    c = store.case_row(loc_id, issue, lead)
    loc = LOC_BY_ID[loc_id]
    proba = store.proba_row(int(c["case_id"]))
    F = np.array([b[f"f_{m}"] for m in MODELS], dtype=float)
    ens, spread = F.mean(), F.std()
    others = (F.sum() - F) / (M - 1)
    rows = []
    for j, m in enumerate(MODELS):
        d = {"model_idx": j, "f": F[j], "ens": ens, "dev": F[j] - others[j], "abs_dev": abs(F[j] - others[j]),
             "spread": spread, "rel_spread": spread / (abs(ens) + SPREAD_FLOOR[var]),
             "ens_temp": c["ens_temp"], "ens_rh": c["ens_rh"], "ens_pressure": c["ens_pressure"],
             "ens_wind": c["ens_wind"], "ens_rain": c["ens_rain"], "dT": c["dT"], "dP": c["dP"],
             "lat": loc.lat, "lon": loc.lon, "m_sin": np.sin(2 * np.pi * c["month"] / 12),
             "m_cos": np.cos(2 * np.pi * c["month"] / 12), "lead_h": lead,
             "region_code": REGION_LIST.index(loc.region), "regime_code": int(proba.argmax()),
             "regime_conf": float(proba.max()), "hist": b[f"hist_{m}"], "rec": b[f"rec_{m}"],
             "histb": b[f"histb_{m}"], "recb": b[f"recb_{m}"]}
        for k, r in enumerate(REGIMES):
            d[f"p_{r}"] = proba[k]
        rows.append(d)
    return pd.DataFrame(rows)[BASE_FEATS], b, c, proba


def skill_agg(store: Store, var: str, lead: int, *, regime: str | None = None, region: str | None = None,
              loc: str | None = None) -> dict:
    sk = store.skill
    q = sk[(sk.variable == var) & (sk.lead_h == lead)]
    if regime is not None:
        q = q[q.regime == regime]
    if loc is not None:
        q = q[q.location_id == loc]
    elif region is not None:
        ids = [l.id for l in LOC_BY_ID.values() if l.region == region]
        q = q[q.location_id.isin(ids)]
    out = {}
    for m in MODELS:
        g = q[q.model_id == m]
        n = g.n.sum()
        out[m] = {"mae": float(g.sae.sum() / n) if n else None, "rmse": float(np.sqrt(g.sse.sum() / n)) if n else None,
                  "bias": float(g.sum_err.sum() / n) if n else None, "n": int(n)}
    return out


def _rank(values: dict, lower_better=True) -> dict:
    items = [(k, v) for k, v in values.items() if v is not None and not (isinstance(v, float) and np.isnan(v))]
    items.sort(key=lambda kv: kv[1], reverse=not lower_better)
    return {k: i + 1 for i, (k, _) in enumerate(items)}


def explain(store: Store, loc_id: str, var: str, issue, lead: int) -> dict:
    L, b, c, proba = rebuild_long(store, loc_id, var, issue, lead)
    trust = store.models["trust"]
    contrib = trust.contribs(var, L)
    loc = LOC_BY_ID[loc_id]
    unit = CANON_UNIT[var]
    regime = REGIMES[int(proba.argmax())]
    rconf = float(proba.max())
    order = np.argsort(-proba)
    alt = [{"regime": REGIMES[i], "probability": _f(proba[i])} for i in order[:3]]
    w = {m: float(b[f"w_{m}"]) for m in MODELS}
    wi = {m: float(b[f"wi_{m}"]) for m in MODELS}
    F = {m: float(b[f"f_{m}"]) for m in MODELS}
    reg_sk = skill_agg(store, var, lead, regime=regime, region=loc.region)
    loc_sk = skill_agg(store, var, lead, loc=loc_id)
    if any(v["n"] < 30 for v in reg_sk.values()):       # too sparse -> fall back to all regimes in region
        reg_sk = skill_agg(store, var, lead, region=loc.region)
        reg_label = f"{loc.region.replace('_', ' ').title()} region (all regimes)"
    else:
        reg_label = f"{regime.replace('_', ' ').lower()} regime in {loc.region.replace('_', ' ').title()} region"
    hist = {m: _f(b[f"hist_{m}"]) for m in MODELS}
    rec = {m: _f(b[f"rec_{m}"]) for m in MODELS}
    absdev = {m: float(L.loc[j, "abs_dev"]) for j, m in enumerate(MODELS)}
    r_reg = _rank({m: reg_sk[m]["mae"] for m in MODELS})
    r_hist = _rank(hist)
    r_rec = _rank(rec)
    r_dev = _rank(absdev)
    mean_reg = np.nanmean([reg_sk[m]["mae"] for m in MODELS if reg_sk[m]["mae"] is not None])
    models = []
    w_rank = _rank(w, lower_better=False)
    for j, m in enumerate(MODELS):
        mm = store.model_meta(m)
        pe = float(np.expm1(b[f"pe_{m}"]))
        cc = contrib.iloc[j].drop(["bias", "model_idx"]).sort_values(key=np.abs, ascending=False)
        drivers = [{"feature": k, "label": feat_label(k), "effect": _f(v, 3),
                    "direction": "raises trust" if v < 0 else "lowers trust"} for k, v in cc.head(3).items()]
        reasons = []
        if r_reg.get(m) == 1 and reg_sk[m]["mae"] is not None:
            reasons.append(f"lowest historical MAE in {reg_label} at +{lead}h ({reg_sk[m]['mae']:.2f} {unit} vs {mean_reg:.2f} model average)")
        elif r_reg.get(m) == M and reg_sk[m]["mae"] is not None:
            reasons.append(f"highest historical MAE in {reg_label} at +{lead}h ({reg_sk[m]['mae']:.2f} {unit} vs {mean_reg:.2f} average)")
        if r_rec.get(m) == 1:
            reasons.append(f"smallest verified error over the last 7 days ({rec[m]:.2f} {unit})")
        elif r_rec.get(m) == M and rec[m] is not None:
            reasons.append(f"largest verified error over the last 7 days ({rec[m]:.2f} {unit})")
        if r_dev.get(m) == 1:
            reasons.append("forecast sits closest to the multi-model consensus")
        elif r_dev.get(m) == M:
            reasons.append(f"outlier: {absdev[m]:.2f} {unit} away from the other models' mean")
        if not reasons:
            reasons.append("mid-ranked on regime skill, recent error and consensus distance")
        models.append({
            "model_id": m, "name": mm["name"], "kind": mm["kind"], "label": mm["label"],
            "forecast": _f(F[m]), "weight": _f(w[m]), "weight_rank": w_rank[m],
            "equal_weight": 1 / M, "inverse_error_weight": _f(wi[m]),
            "contribution": _f(w[m] * F[m]), "predicted_error": _f(pe),
            "regime_skill_mae": _f(reg_sk[m]["mae"]), "regime_skill_bias": _f(reg_sk[m]["bias"]),
            "regime_skill_n": reg_sk[m]["n"], "location_skill_mae": _f(loc_sk[m]["mae"]),
            "verified_hist_mae": hist[m], "recent_mae": rec[m], "recent_bias": _f(b[f"recb_{m}"]),
            "ranks": {"regime_skill": r_reg.get(m), "verified_hist": r_hist.get(m), "recent": r_rec.get(m), "consensus": r_dev.get(m)},
            "reasons": reasons, "drivers": drivers,
        })
    models.sort(key=lambda d: -d["weight"])

    blend = float(b["blend"])
    spread = float(b["spread"])
    level = store.disagreement_level(var, lead, spread)
    tol = float(tolerance(var, blend))
    p10, p50, p90 = float(b["p10"]), float(b["p50"]), float(b["p90"])
    top = models[0]
    lead_txt = f"+{lead}h"
    terms = " + ".join(f"{d['weight']:.2f}×{d['forecast']:.1f}" for d in models)
    chain = [
        {"key": "forecast", "title": "Forecast", "value": f"{blend:.1f} {unit}",
         "detail": f"{VAR_LABEL[var]} at {loc.name}, valid {pd.Timestamp(b['valid_time']):%d %b %H:%M} UTC, {lead_txt}"},
        {"key": "region", "title": "Region", "value": loc.region.replace("_", " ").title(),
         "detail": f"{loc.name} ({loc.lat:.2f}°N, {loc.lon:.2f}°E){' · coastal' if loc.coastal else ''}"},
        {"key": "season", "title": "Season", "value": str(b["season"]).replace("_", " ").title(),
         "detail": "model skill is estimated per season; seasonal shifts change which model is reliable"},
        {"key": "lead", "title": "Lead time", "value": lead_txt,
         "detail": "errors of AI and NWP systems grow at different rates with lead time"},
        {"key": "regime", "title": "Weather regime", "value": regime.replace("_", " "),
         "detail": f"{rconf*100:.0f}% probability; alternatives: " + ", ".join(f"{a['regime'].replace('_',' ')} {a['probability']*100:.0f}%" for a in alt[1:])},
        {"key": "skill", "title": "Historical model skill",
         "value": next((d["name"] for d in sorted(models, key=lambda d: (d["ranks"]["regime_skill"] or 9))), "—"),
         "detail": f"best verified MAE in {reg_label} at {lead_txt}: " + ", ".join(
             f"{d['name']} {d['regime_skill_mae']:.2f}" for d in sorted(models, key=lambda d: (d["ranks"]["regime_skill"] or 9)) if d["regime_skill_mae"] is not None)},
        {"key": "recent", "title": "Recent error",
         "value": next((d["name"] for d in sorted(models, key=lambda d: (d["ranks"]["recent"] or 9))), "—"),
         "detail": "verified 7-day MAE: " + ", ".join(f"{d['name']} {d['recent_mae']:.2f}" for d in models if d["recent_mae"] is not None)},
        {"key": "trust", "title": "Model trust", "value": f"{top['name']} {top['weight']*100:.0f}%",
         "detail": " · ".join(f"{d['name']} {d['weight']*100:.0f}%" for d in models)},
        {"key": "blend", "title": "Blending", "value": f"{blend:.1f} {unit}", "detail": f"Σ wᵢ·Fᵢ = {terms}"},
        {"key": "uncertainty", "title": "Uncertainty", "value": f"P10–P90 {p10:.1f}–{p90:.1f} {unit}",
         "detail": f"model disagreement {level}; confidence = P(|error| ≤ {tol:.1f} {unit}) = {float(b['confidence'])*100:.0f}%"},
    ]
    if level == "HIGH":
        tail = "Model disagreement is high, so the uncertainty range is widened and confidence is reduced."
    elif level == "LOW":
        tail = "The models agree closely, so the uncertainty range is narrow."
    else:
        tail = "Model disagreement is moderate."
    pos = [r for r in top["reasons"] if r.startswith(("lowest", "smallest", "forecast sits closest"))]
    if pos:
        r0 = pos[0]
        why = ("it had the " + r0) if r0.startswith(("lowest", "smallest")) else ("its " + r0)
        why_txt = f"because {why}"
    else:
        why_txt = "but no model stands out on regime skill, recent error or consensus, so weights stay close to equal"
    narrative = (f"The atmosphere at {loc.name} is classified as {regime.replace('_',' ').lower()} ({rconf*100:.0f}% probability) "
                 f"in {str(b['season']).replace('_',' ').lower()} at {lead_txt}. {top['name']} receives the largest weight "
                 f"({top['weight']*100:.0f}%) {why_txt}. {tail}")
    ep = b.get("event_prob")
    return {
        "case": {"location_id": loc_id, "location": loc.name, "region": loc.region, "variable": var, "unit": unit,
                 "issue_time": pd.Timestamp(issue).isoformat(), "valid_time": pd.Timestamp(b["valid_time"]).isoformat(),
                 "lead_h": lead, "season": str(b["season"]), "split": str(b["split"]),
                 "in_sample_for_meta_model": str(b["split"]) == "train"},
        "forecast": {"value": _f(blend), "p10": _f(p10), "p50": _f(p50), "p90": _f(p90),
                     "confidence": _f(b["confidence"]), "confidence_definition": f"P(|error| ≤ {tol:.1f} {unit})",
                     "equal_weight_value": _f(b["blend_equal"]), "inverse_error_value": _f(b["blend_inv"]),
                     "event_probability": _f(ep), "event_probability_residual": _f(b["event_prob_resid"])},
        "disagreement": {"spread": _f(spread), "unweighted_spread": _f(b["model_spread"]), "level": level,
                         "min": _f(min(F.values())), "max": _f(max(F.values()))},
        "regime": {"label": regime, "confidence": _f(rconf), "alternatives": alt,
                   "probabilities": {r: _f(proba[i]) for i, r in enumerate(REGIMES)}},
        "models": models, "chain": chain, "narrative": narrative, "meta_model_tau": store.meta["tau"][var],
        "provenance": {"model_version": store.meta["model_version"], "data_mode": store.meta["data_mode"],
                       "generated_at": store.meta["generated_at"], "inputs": F},
    }
