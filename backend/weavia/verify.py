"""Objective verification on the held-out TEST slice.

WEAVIA is compared against every individual model, the equal-weight ensemble, inverse-error
weighting, the best single model selected on TRAIN data, and (conservatively) the best single
model selected ON the test data (an oracle no real system could use). Uncertainty is verified by
realised coverage. Improvements are reported with paired, date-block bootstrap confidence intervals;
the headline only claims improvement when the interval excludes zero.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from .config import BLEND_VARS, EVENT_THRESH, LEADS, MODELS, REGIMES, VAR_LABEL, tolerance

SINGLE = {m: f"f_{m}" for m in MODELS}
COLS = {**SINGLE, "equal": "blend_equal", "inverse_error": "blend_inv", "weavia": "blend"}
METHODS = list(COLS)


def regime_metrics(cx_test: pd.DataFrame, proba: np.ndarray) -> dict:
    y = cx_test["obs_regime"].values
    pred = np.array(REGIMES)[proba.argmax(1)]
    acc = float((y == pred).mean())
    maj = pd.Series(y).value_counts(normalize=True)
    recall = {r: (float((pred[y == r] == r).mean()) if (y == r).any() else None) for r in REGIMES}
    support = {r: int((y == r).sum()) for r in REGIMES}
    conf = pd.crosstab(pd.Series(y, name="observed"), pd.Series(pred, name="predicted")).reindex(
        index=REGIMES, columns=REGIMES, fill_value=0)
    top_conf = proba.max(1)
    bins = [0, .5, .7, .9, 1.0001]
    rel = []
    for lo, hi in zip(bins[:-1], bins[1:]):
        m = (top_conf >= lo) & (top_conf < hi)
        if m.sum():
            rel.append({"conf_lo": lo, "conf_hi": min(hi, 1.0), "n": int(m.sum()),
                        "mean_conf": float(top_conf[m].mean()), "accuracy": float((y[m] == pred[m]).mean())})
    return {"accuracy": acc, "majority_baseline": float(maj.iloc[0]), "majority_class": str(maj.index[0]),
            "recall": recall, "support": support, "confusion": conf.values.tolist(), "reliability": rel}


def _err_frame(d: pd.DataFrame) -> pd.DataFrame:
    e = pd.DataFrame({m: (d[c] - d["obs"]) for m, c in COLS.items()})
    return e


def _bootstrap(sums: np.ndarray, counts: np.ndarray, B: int = 2000, seed: int = 0) -> np.ndarray:
    rng = np.random.default_rng(seed)
    D = len(counts)
    idx = rng.integers(0, D, (B, D))
    return sums[idx].sum(1) / counts[idx].sum(1)[:, None]


def _best_single(train: pd.DataFrame, var: str, lead: int | None) -> str:
    d = train[(train.variable == var)] if lead is None else train[(train.variable == var) & (train.lead_h == lead)]
    return min(SINGLE, key=lambda m: float((d[SINGLE[m]] - d["obs"]).abs().mean()))


def evaluate(blend: pd.DataFrame, skill: pd.DataFrame, regime_m: dict, alert_thr: dict | None = None) -> dict:
    alert_thr = alert_thr or {}
    train = blend[blend.split == "train"]
    test = blend[blend.split == "test"]
    result: dict = {"n_test_rows": int(len(test)), "regime": regime_m, "metrics": [], "pooled": [], "headline": [],
                    "events": [], "coverage": [], "confidence_reliability": [], "best_single_train": {}}
    for var in BLEND_VARS:
        dv = test[test.variable == var].copy()
        # per-row best-single (train-selected per lead / oracle per lead)
        bt = {L: _best_single(train, var, L) for L in LEADS}
        result["best_single_train"][var] = {str(L): m for L, m in bt.items()}
        E = _err_frame(dv)
        AE = E.abs()
        AE["best_single_train"] = [AE.at[i, bt[L]] for i, L in zip(AE.index, dv.lead_h.values)]
        oracle = {L: min(SINGLE, key=lambda m: float(AE.loc[dv.lead_h.values == L, m].mean())) for L in LEADS}
        AE["best_single_oracle"] = [AE.at[i, oracle[L]] for i, L in zip(AE.index, dv.lead_h.values)]
        SE = E**2
        dates = pd.factorize(dv["issue_time"])[0]

        def boot_for(mask, ref_cols):
            cols = ["weavia"] + ref_cols
            sums = np.zeros((dates.max() + 1, len(cols)))
            cnt = np.zeros(dates.max() + 1)
            for k, c in enumerate(cols):
                np.add.at(sums[:, k], dates[mask], AE.loc[mask, c].values)
            np.add.at(cnt, dates[mask], 1.0)
            keep = cnt > 0
            draws = _bootstrap(sums[keep], cnt[keep])
            point = sums[keep].sum(0) / cnt[keep].sum()
            out = {}
            for k, ref in enumerate(ref_cols, start=1):
                diff = draws[:, 0] - draws[:, k]             # negative = WEAVIA better
                rel = -diff / draws[:, k]
                out[ref] = {"ref_mae": float(point[k]), "weavia_mae": float(point[0]),
                            "improvement_pct": float(100 * (1 - point[0] / point[k])),
                            "ci95_pct": [float(100 * np.quantile(rel, 0.025)), float(100 * np.quantile(rel, 0.975))],
                            "significant": bool(np.quantile(rel, 0.025) > 0)}
            return out

        refs = ["equal", "inverse_error", "best_single_train", "best_single_oracle"]
        for L in [None] + LEADS:
            mask = np.ones(len(dv), bool) if L is None else (dv.lead_h.values == L)
            row = {"variable": var, "lead_h": "all" if L is None else L, "n": int(mask.sum()), "methods": {}}
            for m in METHODS:
                row["methods"][m] = {"mae": float(AE.loc[mask, m].mean()), "rmse": float(np.sqrt(SE.loc[mask, m].mean())),
                                     "bias": float(E.loc[mask, m].mean())}
            row["methods"]["best_single_train"] = {"mae": float(AE.loc[mask, "best_single_train"].mean())}
            row["methods"]["best_single_oracle"] = {"mae": float(AE.loc[mask, "best_single_oracle"].mean())}
            row["vs"] = boot_for(mask, refs)
            (result["pooled"] if L is None else result["metrics"]).append(row)

        eq = row_all = next(r for r in result["pooled"] if r["variable"] == var)
        v = eq["vs"]
        w_ = eq["methods"]["weavia"]["mae"]
        best_model = min(SINGLE, key=lambda m: eq["methods"][m]["mae"])
        result["headline"].append({
            "variable": var, "label": VAR_LABEL[var], "weavia_mae": w_,
            "equal_mae": v["equal"]["ref_mae"], "best_single_model": best_model,
            "best_single_mae": eq["methods"][best_model]["mae"],
            "vs_equal": v["equal"], "vs_inverse_error": v["inverse_error"],
            "vs_best_single_train": v["best_single_train"], "vs_best_single_oracle": v["best_single_oracle"],
            "verdict": _verdict(var, v),
        })

        # event skill
        thr = EVENT_THRESH[var]
        obs_ev = dv["obs"].values >= thr
        base_rate = float((train[train.variable == var]["obs"] >= thr).mean())
        ev = {"variable": var, "threshold": thr, "n_obs_events": int(obs_ev.sum()), "n": int(len(dv)),
              "base_rate_train": base_rate, "methods": {}}
        for m, c in {**SINGLE, "equal": "blend_equal", "weavia_deterministic": "blend"}.items():
            ev["methods"][m] = _prf(dv[c].values >= thr, obs_ev)
        at = float(alert_thr.get(var, 0.5))
        ev["alert_threshold_val"] = at
        ev["methods"]["weavia_event_model"] = _prf(dv["event_prob"].values >= at, obs_ev)
        ev["methods"]["weavia_residual_prob>=0.5"] = _prf(dv["event_prob_resid"].values >= 0.5, obs_ev)
        p = dv["event_prob"].values
        if obs_ev.sum() < 20 or np.isnan(p).any():
            ev["brier"] = ev["brier_climatology"] = ev["brier_skill_score"] = None
            ev["insufficient_events"] = True
        else:
            bs = float(np.mean((p - obs_ev) ** 2))
            bs_ref = float(np.mean((base_rate - obs_ev) ** 2))
            ev["brier"], ev["brier_climatology"] = bs, bs_ref
            ev["brier_skill_score"] = float(1 - bs / bs_ref) if bs_ref > 0 else None
            ev["insufficient_events"] = False
        result["events"].append(ev)

        # interval coverage + confidence reliability
        for L in LEADS:
            m = dv.lead_h.values == L
            o, lo, hi = dv.obs.values[m], dv.p10.values[m], dv.p90.values[m]
            result["coverage"].append({
                "variable": var, "lead_h": L, "nominal": 0.8, "inside_p10_p90": float(((o >= lo) & (o <= hi)).mean()),
                "below_p10": float((o < lo).mean()), "above_p90": float((o > hi).mean()),
                "mean_interval_width": float((hi - lo).mean())})
        conf = dv.confidence.values
        hit = (np.abs(dv.obs.values - dv.blend.values) <= tolerance(var, dv.blend.values))
        bins = np.linspace(0, 1, 6)
        for lo_, hi_ in zip(bins[:-1], bins[1:]):
            m = (conf >= lo_) & (conf < hi_ + (1e-9 if hi_ == 1 else 0))
            if m.sum() >= 20:
                result["confidence_reliability"].append({
                    "variable": var, "conf_lo": float(lo_), "conf_hi": float(hi_), "n": int(m.sum()),
                    "mean_confidence": float(conf[m].mean()), "realised": float(hit[m].mean())})
    result["data_mode"] = "synthetic"
    return result


def _prf(pred: np.ndarray, obs: np.ndarray) -> dict:
    tp = int((pred & obs).sum())
    fp = int((pred & ~obs).sum())
    fn = int((~pred & obs).sum())
    prec = tp / (tp + fp) if tp + fp else None
    rec = tp / (tp + fn) if tp + fn else None
    f1 = 2 * prec * rec / (prec + rec) if prec and rec else (0.0 if (tp + fp + fn) else None)
    return {"tp": tp, "fp": fp, "fn": fn, "precision": prec, "recall": rec, "f1": f1}


def _verdict(var: str, v: dict) -> str:
    eq, inv, bs, orc = v["equal"], v["inverse_error"], v["best_single_train"], v["best_single_oracle"]
    parts = []
    for name, r in (("equal-weight ensemble", eq), ("inverse-error weighting", inv), ("train-selected best model", bs)):
        lo, hi = r["ci95_pct"]
        if r["significant"]:
            parts.append(f"MAE {r['improvement_pct']:.1f}% lower than {name} (95% CI {lo:.1f}–{hi:.1f}%)")
        elif hi < 0:
            parts.append(f"MAE {-r['improvement_pct']:.1f}% HIGHER than {name} (95% CI {lo:.1f}–{hi:.1f}%)")
        else:
            parts.append(f"no significant MAE difference vs {name} ({r['improvement_pct']:+.1f}%, 95% CI {lo:.1f}–{hi:.1f}%)")
    tail = ("; does not beat the test-selected oracle best model" if not orc["significant"] and orc["improvement_pct"] < 0
            else ("; also beats the test-selected oracle best model" if orc["significant"] else ""))
    return "; ".join(parts) + tail
