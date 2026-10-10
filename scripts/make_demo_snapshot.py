"""Trim a full synthetic run into a small, committable demo dataset for hosting.

    python scripts/make_demo_snapshot.py backend/data demo_data --issues 60

Keeps the last N test-slice issues (chosen so the landing day is wet and the window contains forecast-miss events),
every row those issues need, the full skill table, models and verification. The banner text is extended to say it is
a snapshot. verification.json is copied untouched: it summarises the FULL run, not the snapshot.
The Lab back-test and the Skill atlas recompute from the kept rows, so they are noisier than the full-run figures."""
from __future__ import annotations

import argparse
import json
import shutil
from pathlib import Path

import numpy as np
import pandas as pd


def make(src: str, dst: str, n_issues: int = 60) -> dict:
    s, d = Path(src), Path(dst)
    meta = json.loads((s / "meta.json").read_text())
    if meta.get("data_mode") != "synthetic":
        raise SystemExit("snapshot is meant for the synthetic benchmark; real-data demos are built by weavia.live")
    blend = pd.read_parquet(s / "blend.parquet")
    cases = pd.read_parquet(s / "cases.parquet")
    events = pd.read_parquet(s / "events.parquet")
    naive = lambda x: pd.to_datetime(x, utc=True).dt.tz_localize(None)       # one clock for every comparison (UTC, no tz)
    blend["_iss"], cases["_iss"], ev_t = naive(blend.issue_time), naive(cases.issue_time), naive(events.valid_time)
    test = blend[blend.split == "test"]
    issues = np.sort(test._iss.unique())
    rain24 = test[(test.variable == "rain") & (test.lead_h == 24)].groupby("_iss").blend.mean()
    best, best_score = None, -1.0
    for i in range(n_issues - 1, len(issues)):
        a, b = issues[i - n_issues + 1], issues[i]
        ok = ((ev_t >= a + np.timedelta64(72, "h")) & (ev_t <= b)).sum()
        score = 10 * int(ok) + float(rain24.get(pd.Timestamp(b), 0.0))
        if score > best_score:
            best, best_score = (a, b), score
    a, b = best
    kb = blend[(blend.split == "test") & (blend._iss >= a) & (blend._iss <= b)].drop(columns="_iss")
    kc = cases[(cases.split == "test") & (cases._iss >= a) & (cases._iss <= b)].drop(columns="_iss")
    ids = set(kc.case_id)
    proba = pd.read_parquet(s / "regime_proba.parquet")
    ke = events[(ev_t >= a + np.timedelta64(72, "h")) & (ev_t <= b)]
    d.mkdir(parents=True, exist_ok=True)
    for name, df in (("blend", kb), ("cases", kc), ("regime_proba", proba[proba.case_id.isin(ids)]), ("events", ke)):
        df.reset_index(drop=True).to_parquet(d / f"{name}.parquet", compression="zstd")
    for f in ("skill.parquet", "models.joblib", "verification.json"):
        shutil.copy2(s / f, d / f)
    tr = blend[blend.split == "train"]            # the API derives spread terciles from TRAIN rows, which the snapshot drops
    sq = {f"{v}|{int(l)}": [float(g.spread.quantile(0.50)), float(g.spread.quantile(0.85))] for (v, l), g in tr.groupby(["variable", "lead_h"])}
    (d / "spread_q.json").write_text(json.dumps(sq))
    t = pd.read_parquet(s / "truth.parquet")
    tt = pd.to_datetime(t.time, utc=True)
    t[(tt >= pd.Timestamp(a, tz="UTC") - pd.Timedelta(days=3)) & (tt <= pd.Timestamp(b, tz="UTC") + pd.Timedelta(days=4))].to_parquet(d / "truth.parquet", compression="zstd")
    meta["data_notice"] = (meta["data_notice"] + f" DEMO SNAPSHOT: {len(np.unique(kb.issue_time))} issues "
                           f"({pd.Timestamp(a):%d %b %Y} to {pd.Timestamp(b):%d %b %Y}) of the full run. Verification figures "
                           "summarise the full run, not this window.")
    meta["demo_snapshot"] = {"issues": int(len(np.unique(kb.issue_time))), "from": str(pd.Timestamp(a)), "to": str(pd.Timestamp(b)),
                             "events": int(len(ke))}
    (d / "meta.json").write_text(json.dumps(meta, indent=2, default=str))
    return {"dir": str(d), "bytes": sum(p.stat().st_size for p in d.iterdir()), **meta["demo_snapshot"]}


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("src")
    ap.add_argument("dst")
    ap.add_argument("--issues", type=int, default=60)
    a = ap.parse_args()
    r = make(a.src, a.dst, a.issues)
    print(json.dumps(r, indent=2), f"\n{r['bytes'] / 1e6:.1f} MB")
