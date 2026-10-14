import json

from weavia.report import report


def _ver(sig_oracle: bool, imp=-4.0, ci=(-9.0, 1.0)):
    vs = lambda i, c, s: {"ref_mae": 1.0, "weavia_mae": 0.9, "improvement_pct": i, "ci95_pct": list(c), "significant": s}
    m = {"a": {"mae": 1.0}, "b": {"mae": 0.8}, "equal": {"mae": 0.95}, "inverse_error": {"mae": 0.9}, "weavia": {"mae": 0.85},
         "best_single_train": {"mae": 1.0}, "best_single_oracle": {"mae": 0.8}}
    pooled = [{"variable": "rain", "lead_h": "all", "n": 100, "methods": m,
               "vs": {"equal": vs(10.5, (7.0, 14.0), True), "inverse_error": vs(5.0, (1.0, 9.0), True),
                      "best_single_train": vs(15.0, (10.0, 20.0), True),
                      "best_single_oracle": vs(6.0, (2.0, 10.0), True) if sig_oracle else vs(imp, ci, False)}}]
    return {"n_test_rows": 100, "regime": {"accuracy": 0.8, "majority_baseline": 0.78, "majority_class": "NORMAL"},
            "headline": [{"variable": "rain"}], "pooled": pooled,
            "coverage": [{"variable": "rain", "lead_h": 24, "inside_p10_p90": 0.9, "inside_p10_p90_nondry": 0.78}],
            "events": [{"variable": "rain", "threshold": 20.0, "n_obs_events": 10, "methods": {}}]}


def _write(tmp_path, ver, mode="real"):
    (tmp_path / "verification.json").write_text(json.dumps(ver))
    (tmp_path / "meta.json").write_text(json.dumps({"data_mode": mode, "truth_source": "reanalysis", "models": {"a": {"label": "IFS"}, "b": {"label": "AIFS"}}}))
    return report(tmp_path)


def test_report_names_the_best_individual_model_and_calls_hindsight_wins_only_when_ci_excludes_zero(tmp_path):
    t = _write(tmp_path, _ver(True))
    assert "best individual model on these days: AIFS (0.800)" in t
    assert "vs best model picked WITH hindsight: WEAVIA better by 6.0%" in t and "beats it" in t


def test_report_says_no_claim_when_the_interval_includes_zero(tmp_path):
    t = _write(tmp_path, _ver(False))
    assert "vs best model picked WITH hindsight: -4.0% (95% CI -9.0 to 1.0): CI includes 0, NO CLAIM" in t


def test_report_flags_a_clear_loss(tmp_path):
    t = _write(tmp_path, _ver(False, imp=-8.0, ci=(-12.0, -4.0)))
    assert "WEAVIA WORSE by 8.0%" in t


def test_report_states_caveats_and_event_limits(tmp_path):
    t = _write(tmp_path, _ver(True))
    assert "Truth is reanalysis" in t and "one season" in t and "too few for any claim" in t
    assert "non-dry forecasts" in t and "78%" in t
    assert "Synthetic data" in _write(tmp_path, _ver(True), mode="synthetic")
