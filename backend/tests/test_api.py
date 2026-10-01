"""API contract tests. Need artifacts: run `python -m weavia.pipeline` first (skipped otherwise)."""
import os, pytest
from fastapi.testclient import TestClient

pytestmark = pytest.mark.skipif(not os.path.exists("data/meta.json"), reason="pipeline artifacts missing")
from weavia.api.main import app  # noqa: E402
c = TestClient(app)
M = ["model_a", "model_b", "model_c", "model_d"]


def test_meta_and_map():
    m = c.get("/api/v1/meta").json()
    assert m["provenance"]["data_mode"] and len(m["locations"]) == 20
    mp = c.get("/api/v1/map?lead=24").json()
    assert len(mp["points"]) == 20
    for p in mp["points"]:
        assert abs(sum(p["weights"].values()) - 1) < 1e-3          # weights sum to 1
        assert 0 <= p["risk"] <= 1


def test_forecast_band_ordered():
    f = c.get("/api/v1/forecast?location_id=maa&variable=temp&lead=24").json()["forecast"]
    assert f["p10"] <= f["p50"] <= f["p90"]


def test_explain_weights_sum_to_one():
    e = c.get("/api/v1/explain?location_id=bom&variable=rain&lead=48").json()
    assert abs(sum(m["weight"] for m in e["models"]) - 1) < 1e-3 and len(e["chain"]) == 10


def test_validation_errors():
    assert c.get("/api/v1/forecast?location_id=maa&variable=snow").status_code == 422
    assert c.get("/api/v1/forecast?location_id=zzz&variable=rain").status_code == 404
    assert c.get("/api/v1/map?lead=5").status_code == 422
    assert c.get("/api/v1/map?issue=1999-01-01").status_code == 404


def test_lab_identity_weights_match_weavia():
    w = {m["model_id"]: m["weight"] for m in c.get("/api/v1/trust?location_id=maa&variable=wind").json()["models"]}
    r = c.post("/api/v1/lab/simulate", json={"location_id": "maa", "variable": "wind", "lead": 24, "weights": w}).json()
    assert abs(r["forecast"]["change"]) < 0.05
    assert c.post("/api/v1/lab/simulate", json={"location_id": "maa", "weights": {m: 0 for m in M}}).status_code == 422


def test_autopsy_roundtrip():
    ev = c.get("/api/v1/events?limit=1").json()[0]
    assert c.get(f"/api/v1/autopsy/{ev['event_id']}").status_code == 200
    assert c.get("/api/v1/autopsy/nope").status_code == 404
