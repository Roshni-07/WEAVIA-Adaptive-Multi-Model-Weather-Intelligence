import numpy as np
import pandas as pd

from weavia.diagnose import coverage_options, format_table


def _write(tmp_path, shift: bool, seed=0):
    """Calibration period is calm, test period has larger errors (a season change), like the real temperature case."""
    rng = np.random.default_rng(seed)
    rows = []
    days = pd.date_range("2026-07-01", periods=100, freq="D", tz="UTC")
    for i, d in enumerate(days):
        split = "train" if i < 60 else "val" if i < 75 else "test"
        sd = 1.0 if (i < 75 or not shift) else 2.2
        for _ in range(40):
            blend = 30 + rng.normal(0, 3)
            rows.append(dict(variable="temp", lead_h=24, blend=blend, spread=0.5, obs=blend + rng.normal(0, sd), split=split,
                             issue_time=d, valid_time=d + pd.Timedelta(hours=24)))
    pd.DataFrame(rows).to_parquet(tmp_path / "blend.parquet")


def test_rolling_window_adapts_when_the_season_changes_and_static_does_not(tmp_path):
    _write(tmp_path, shift=True)
    df = coverage_options(tmp_path, "temp", windows=(7,))
    cov = df.set_index("option").coverage
    assert cov["current (train+val)"] < 0.65                      # calm calibration, rougher test: too narrow
    assert cov["rolling 7 days"] > cov["current (train+val)"] + 0.08
    assert abs(cov["rolling 7 days"] - 0.8) < 0.1


def test_no_shift_means_every_option_is_near_nominal(tmp_path):
    _write(tmp_path, shift=False)
    cov = coverage_options(tmp_path, "temp", windows=(14,)).set_index("option").coverage
    assert all(abs(v - 0.8) < 0.07 for v in cov)


def test_table_is_readable(tmp_path):
    _write(tmp_path, shift=True)
    t = format_table(coverage_options(tmp_path, "temp", windows=(7,)), "temp")
    assert "nominal 80%" in t and "rolling 7 days" in t and "current (train+val)" in t
