"""The trust, explain and blending code must work for any number of sources (3 or more), not just four."""
import json

import numpy as np
import pandas as pd
import pytest

from weavia import config
from weavia.pipeline import run


@pytest.fixture()
def three_models():
    saved = list(config.MODELS)
    config.MODELS[:] = ["model_a", "model_c", "model_d"]
    yield list(config.MODELS)
    config.MODELS[:] = saved


def test_pipeline_runs_with_three_models(three_models, tmp_path, monkeypatch):
    ver = run(str(tmp_path), days=400, log=lambda *_: None)
    meta = json.loads((tmp_path / "meta.json").read_text())
    assert meta["model_ids"] == three_models
    blend = pd.read_parquet(tmp_path / "blend.parquet")
    w = blend[[f"w_{m}" for m in three_models]].values
    assert np.allclose(w.sum(1), 1) and (w >= 0).all()
    assert "w_model_b" not in blend.columns                       # no ghost fourth model
    assert {h["variable"] for h in ver["headline"]} == {"rain", "temp", "wind"}
    assert set(ver["headline"][0]) >= {"vs_equal", "vs_inverse_error"}
    assert np.isfinite(blend.blend).all() and (blend.confidence.between(0, 1)).all()
    # the explanation and trust views must also cope with three sources
    import weavia.api.main as api
    from fastapi.testclient import TestClient
    monkeypatch.setattr(api, "DATA_DIR", str(tmp_path))
    monkeypatch.setattr(api, "_store", None)
    c = TestClient(api.app)
    loc = c.get("/api/v1/meta").json()["locations"][0]["id"]
    for route in ("explain", "trust"):
        r = c.get(f"/api/v1/{route}?location_id={loc}&variable=rain&lead=24")
        assert r.status_code == 200, (route, r.text[:200])
    assert len(c.get(f"/api/v1/trust?location_id={loc}&variable=temp&lead=24").json()["models"]) == 3
