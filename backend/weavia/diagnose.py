"""Why is interval coverage off? Compare calibration choices on the artifacts you already have.

    python -W ignore -m weavia.diagnose data_live2 temp

For one variable it scores, on the held-out test rows, the P10 to P90 coverage and mean width of:
  current     quantiles of the normalised residual from train + validation (what the pipeline does)
  val only    validation rows only (those residuals are out-of-sample for the trust model)
  train only  training rows only (in-sample for the trust model, so likely too optimistic)
  rolling N   only the last N days of VERIFIED errors (valid time before the issue), refreshed for every issue,
              which is what a live system can do and what adapts when the season changes
Nothing is refitted and nothing is written. It only reads blend.parquet."""
from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

from .config import SPREAD_FLOOR


def coverage_options(out_dir: str | Path, var: str = "temp", windows=(14, 28, 56), q=(0.1, 0.9)) -> pd.DataFrame:
    d = Path(out_dir)
    b = pd.read_parquet(d / "blend.parquet", columns=["variable", "lead_h", "blend", "spread", "obs", "split", "issue_time", "valid_time"])
    b = b[(b.variable == var) & b.obs.notna()].copy()
    c = SPREAD_FLOOR[var]
    b["scale"] = b.spread + c
    b["z"] = (b.obs - b.blend) / b.scale
    b["iss"] = pd.to_datetime(b.issue_time, utc=True)
    b["val"] = pd.to_datetime(b.valid_time, utc=True)
    test = b[b.split == "test"].copy()
    leads = sorted(test.lead_h.unique())
    rows = []

    def score(name, lo, hi):
        t = test.assign(lo=test.blend + lo * test.scale, hi=test.blend + hi * test.scale)
        for L in leads:
            x = t[t.lead_h == L]
            rows.append({"option": name, "lead_h": int(L), "coverage": float(((x.obs >= x.lo) & (x.obs <= x.hi)).mean()),
                         "width": float((x.hi - x.lo).mean()), "n": int(len(x))})

    def static(name, mask):
        qs = {L: np.quantile(b[mask & (b.lead_h == L)].z, q) for L in leads if (mask & (b.lead_h == L)).sum() >= 30}
        lo = test.lead_h.map(lambda L: qs[L][0] if L in qs else np.nan)
        hi = test.lead_h.map(lambda L: qs[L][1] if L in qs else np.nan)
        score(name, lo, hi)

    static("current (train+val)", b.split.isin(["train", "val"]))
    static("val only", b.split == "val")
    static("train only", b.split == "train")
    for W in windows:
        lo = pd.Series(np.nan, index=test.index)
        hi = pd.Series(np.nan, index=test.index)
        for it, g in test.groupby("iss"):
            m = (b.val <= it) & (b.val > it - pd.Timedelta(days=W))
            for L, gg in g.groupby("lead_h"):
                z = b[m & (b.lead_h == L)].z
                if len(z) >= 30:
                    lo[gg.index], hi[gg.index] = np.quantile(z, q[0]), np.quantile(z, q[1])
        score(f"rolling {W} days", lo, hi)
    out = pd.DataFrame(rows)
    return out


def format_table(df: pd.DataFrame, var: str) -> str:
    pv = df.pivot(index="option", columns="lead_h", values="coverage")
    wd = df.groupby("option").width.mean()
    order = list(dict.fromkeys(df.option))
    lines = [f"P10 to P90 coverage on held-out rows, {var} (nominal 80%)", "option".ljust(22) + "".join(f"+{L}h".rjust(8) for L in pv.columns) + "  mean width"]
    for o in order:
        lines.append(o.ljust(22) + "".join((f"{100 * pv.loc[o, L]:.0f}%" if pd.notna(pv.loc[o, L]) else "n/a").rjust(8) for L in pv.columns) + f"  {wd[o]:.2f}")
    lines.append("Closest to 80% without a much wider interval is the better calibration. 'n/a' means too little verified history.")
    return "\n".join(lines)


def main(argv=None):
    a = sys.argv[1:] if argv is None else argv
    out_dir, var = (a + ["data", "temp"])[:2] if len(a) < 2 else a[:2]
    print(format_table(coverage_options(out_dir, var), var))


if __name__ == "__main__":
    main()
