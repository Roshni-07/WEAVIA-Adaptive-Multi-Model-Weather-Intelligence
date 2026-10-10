"""The hosted demo is built from a trimmed snapshot. It must serve every route, say it is a snapshot, and stay small.
Needs a full synthetic run in backend/data (skipped otherwise)."""
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))
needs_data = pytest.mark.skipif(not os.path.exists("data/blend.parquet"), reason="full synthetic run missing")

SWEEP = r'''
import json
from fastapi.testclient import TestClient
import weavia.api.main as api
c = TestClient(api.app); bad = []; n = 0
def chk(path, method="get", **kw):
    global n; n += 1
    r = getattr(c, method)(path, **kw)
    if r.status_code != 200: bad.append((path, r.status_code, r.text[:100]))
    return r
for lead in (6, 24, 72):
    chk(f"/api/v1/map?lead={lead}"); chk(f"/api/v1/overview?lead={lead}"); chk(f"/api/v1/regime?location_id=bom&lead={lead}")
    for var in ("rain", "temp", "wind"):
        for route in ("forecast", "trust", "explain"): chk(f"/api/v1/{route}?location_id=bom&variable={var}&lead={lead}")
chk("/api/v1/timeline?location_id=del&variable=temp"); chk("/api/v1/skill-atlas?variable=rain&lead=24"); chk("/api/v1/verification")
evs = chk("/api/v1/events").json()
for e in evs[:10]:
    for lead in (24, 72): chk(f"/api/v1/autopsy/{e['event_id']}?lead={lead}")
chk("/api/v1/lab/simulate", "post", json={"location_id": "bom", "variable": "rain", "lead": 24, "weights": {"model_a": 1, "model_b": 1, "model_c": 1, "model_d": 1}})
m = c.get("/api/v1/meta").json()
print(json.dumps({"n": n, "bad": bad, "events": len(evs), "snapshot": "DEMO SNAPSHOT" in m["provenance"]["data_notice"], "issues": len(m["issues"])}))
'''


@needs_data
def test_snapshot_is_small_honest_and_serves_every_route(tmp_path):
    from make_demo_snapshot import make
    info = make("data", str(tmp_path / "demo"), n_issues=30)
    assert info["bytes"] < 40e6 and info["events"] > 0
    env = {**os.environ, "WEAVIA_DATA": str(tmp_path / "demo"), "WEAVIA_RATE_LIMIT": "0", "WEAVIA_LAB_RATE_LIMIT": "0"}
    out = subprocess.run([sys.executable, "-W", "ignore", "-c", SWEEP], env=env, capture_output=True, text=True, timeout=300)
    assert out.returncode == 0, out.stderr[-600:]
    r = json.loads(out.stdout.strip().splitlines()[-1])
    assert r["bad"] == [] and r["snapshot"] and r["issues"] == 30 and r["n"] > 40


@needs_data
def test_snapshot_refuses_real_data_runs(tmp_path):
    from make_demo_snapshot import make
    src = tmp_path / "real"
    src.mkdir()
    (src / "meta.json").write_text(json.dumps({"data_mode": "real"}))
    with pytest.raises(SystemExit):
        make(str(src), str(tmp_path / "out"))
