"""Plain-language verification report from verification.json.

    python -m weavia.report data_live2
    python -m weavia.live report --out data_live2

Reads what the pipeline already measured and states, per variable, whether WEAVIA beat each baseline, each
individual model and the best individual model chosen WITH hindsight on the test days (the strictest fair
comparison). A comparison is called a win only when its 95% interval excludes zero. Otherwise it says "no claim"."""
from __future__ import annotations

import json
import sys
from pathlib import Path

VAR = {"rain": "Rainfall", "temp": "Temperature", "wind": "Wind"}


def _verdict(v: dict) -> str:
    lo, hi = v["ci95_pct"]
    if v["significant"]:
        return f"WEAVIA better by {v['improvement_pct']:.1f}% (95% CI {lo:.1f} to {hi:.1f}): beats it"
    if v["improvement_pct"] < 0 and hi < 0:
        return f"WEAVIA WORSE by {-v['improvement_pct']:.1f}% (95% CI {lo:.1f} to {hi:.1f})"
    return f"{v['improvement_pct']:+.1f}% (95% CI {lo:.1f} to {hi:.1f}): CI includes 0, NO CLAIM"


def report(out_dir: str | Path) -> str:
    d = Path(out_dir)
    ver = json.loads((d / "verification.json").read_text())
    meta = json.loads((d / "meta.json").read_text()) if (d / "meta.json").exists() else {}
    names = {m: (info.get("label") or m) for m, info in (meta.get("models") or {}).items()}
    out = [f"WEAVIA verification report: {d}", f"data mode: {meta.get('data_mode', ver.get('data_mode', '?'))}"]
    if meta.get("truth_source"):
        out.append(f"truth: {meta['truth_source']}")
    out.append(f"held-out test rows: {ver.get('n_test_rows', '?')}")
    r = ver.get("regime") or {}
    if r:
        out.append(f"regime classifier accuracy {r['accuracy']:.3f} against {r['majority_baseline']:.3f} for always guessing '{r.get('majority_class')}'")
    out.append("")
    for h in ver["headline"]:
        v = h["variable"]
        P = next((p for p in ver.get("pooled", []) if p["variable"] == v and p["lead_h"] == "all"), None)
        out.append(f"== {VAR.get(v, v)} (MAE, held-out days, all leads) ==")
        if P:
            m = P["methods"]
            singles = [k for k in m if k not in ("equal", "inverse_error", "weavia", "best_single_train", "best_single_oracle")]
            out.append("  individual models: " + ", ".join(f"{names.get(k, k)} {m[k]['mae']:.3f}" for k in singles))
            out.append(f"  equal average {m['equal']['mae']:.3f} | inverse-error {m['inverse_error']['mae']:.3f} | WEAVIA {m['weavia']['mae']:.3f}")
            best = min(singles, key=lambda k: m[k]["mae"])
            out.append(f"  best individual model on these days: {names.get(best, best)} ({m[best]['mae']:.3f})")
            for key, label in (("equal", "vs equal average"), ("inverse_error", "vs inverse-error weights"),
                               ("best_single_train", "vs best model picked on training data"),
                               ("best_single_oracle", "vs best model picked WITH hindsight")):
                if key in P["vs"]:
                    out.append(f"  {label}: {_verdict(P['vs'][key])}")
        else:
            out.append("  (no pooled metrics in this file)")
        out.append("")
    out.append("== Interval coverage (P10 to P90, nominal 80%) ==")
    for v in VAR:
        rows = [c for c in ver.get("coverage", []) if c["variable"] == v]
        if rows:
            key = "inside_p10_p90_nondry" if v == "rain" and rows[0].get("inside_p10_p90_nondry") is not None else "inside_p10_p90"
            out.append(f"  {VAR[v]}{' (non-dry forecasts)' if key.endswith('nondry') else ''}: " +
                       ", ".join(f"+{c['lead_h']}h {100 * c[key]:.0f}%" for c in rows))
    out.append("")
    out.append("== Extreme events (test slice) ==")
    for e in ver.get("events", []):
        w = (e.get("methods") or {}).get("weavia_event_model")
        few = e["n_obs_events"] < 30
        out.append(f"  {VAR.get(e['variable'], e['variable'])} >= {e['threshold']}: {e['n_obs_events']} observed events"
                   + (" (too few for any claim)" if few else (f", WEAVIA event model F1 {w['f1']:.2f} (no confidence interval, so no claim of significance)" if w and w.get("f1") is not None else "")))
    out.append("")
    out.append("Read with care:")
    if meta.get("data_mode") == "synthetic":
        out.append("  - Synthetic data: validates the machinery, not real-world skill.")
    else:
        out.append("  - Truth is reanalysis, which is not independent of the forecast models.")
        out.append("  - A short real history covers one season, so results may not carry to other seasons.")
    out.append("  - Only comparisons marked 'beats it' have a 95% interval that excludes zero.")
    return "\n".join(out)


def main(argv=None):
    a = sys.argv[1:] if argv is None else argv
    print(report(a[0] if a else "data"))


if __name__ == "__main__":
    main()
