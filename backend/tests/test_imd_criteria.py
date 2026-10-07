import numpy as np
import pandas as pd
import pytest

from weavia.imd_criteria import (declare_heat_wave, heat_wave_class, heat_wave_threshold, rain_class, definitions)
from weavia.locations import LOCATIONS, LOC_BY_ID


@pytest.mark.parametrize("mm,name", [
    (0.0, "no_rain"), (0.1, "very_light"), (2.4, "very_light"), (2.5, "light"), (15.5, "light"), (15.6, "moderate"),
    (64.4, "moderate"), (64.5, "heavy"), (115.5, "heavy"), (115.6, "very_heavy"), (204.4, "very_heavy"),
    (204.5, "extremely_heavy"), (600.0, "extremely_heavy")])
def test_rain_class_boundaries_match_imd(mm, name):
    assert rain_class(mm)[0] == name


@pytest.mark.parametrize("tmax,normal,terrain,expected", [
    (40.0, 35.4, "plains", 1),        # at the gate with departure 4.6
    (39.9, 33.0, "plains", 0),        # departure 6.9 but below the 40 C gate: not considered
    (41.0, 38.0, "plains", 0),        # above the gate, departure only 3
    (45.0, 42.5, "plains", 1),        # 45 C absolute, irrespective of departure
    (47.0, 44.0, "plains", 2),        # 47 C absolute is severe
    (42.0, 35.0, "plains", 2),        # departure 7.0 (> 6.4) at/above the gate
    (37.2, 32.6, "coastal", 1),       # coastal: departure 4.6 and max >= 37
    (36.9, 30.0, "coastal", 0),       # coastal: huge departure but max below 37
    (30.5, 25.9, "hilly", 1),         # hilly gate is 30 C
    (31.0, 24.0, "hilly", 2),         # hilly: departure 7.0
    (29.9, 20.0, "hilly", 0),
    (44.9, 40.3, "plains", 1),        # departure 4.6, just below 45
])
def test_heat_wave_class_cases(tmax, normal, terrain, expected):
    assert heat_wave_class(tmax, normal, terrain)[0] == expected


def test_threshold_is_equivalent_to_the_class():
    rng = np.random.default_rng(0)
    n = 4000
    terrain = rng.choice(["plains", "coastal", "hilly"], n)
    normal = rng.uniform(15, 44, n)
    tmax = rng.uniform(20, 50, n)
    cls = heat_wave_class(tmax, normal, terrain)
    assert ((tmax >= heat_wave_threshold(normal, terrain)) == (cls >= 1)).all()
    assert ((tmax > heat_wave_threshold(normal, terrain, severe=True) - 1e-12) >= (cls == 2)).all()
    sev_hit = tmax >= heat_wave_threshold(normal, terrain, severe=True) + 1e-9
    assert (sev_hit == (cls == 2)).all()


def test_unknown_terrain_is_an_error():
    with pytest.raises(ValueError):
        heat_wave_class(41, 35, "mountains")


def _days(rows):
    return pd.DataFrame(rows, columns=["date", "station", "group", "cls"])


def test_declared_on_second_consecutive_day_with_two_stations():
    d = _days([("2026-05-01", "a", "N", 1), ("2026-05-01", "b", "N", 1),
               ("2026-05-02", "a", "N", 1), ("2026-05-02", "b", "N", 2)])
    r = declare_heat_wave(d).set_index("date")
    assert not r.loc["2026-05-01", "declared"] and r.loc["2026-05-02", "declared"]
    assert not r.loc["2026-05-02", "severe_declared"]              # severe needs 2 stations x 2 days of severe


def test_one_station_or_a_gap_day_is_not_enough():
    one = _days([("2026-05-01", "a", "N", 1), ("2026-05-02", "a", "N", 1)])
    assert not declare_heat_wave(one).declared.any()
    gap = _days([("2026-05-01", "a", "N", 1), ("2026-05-01", "b", "N", 1),
                 ("2026-05-03", "a", "N", 1), ("2026-05-03", "b", "N", 1)])
    assert not declare_heat_wave(gap).declared.any()


def test_groups_are_independent_and_input_order_does_not_matter():
    rows = [("2026-05-02", "a", "N", 1), ("2026-05-01", "b", "N", 1), ("2026-05-01", "a", "N", 1), ("2026-05-02", "b", "N", 1),
            ("2026-05-01", "c", "S", 1), ("2026-05-02", "c", "S", 1)]
    r = declare_heat_wave(_days(rows))
    assert r[(r.group == "N") & r.declared].shape[0] == 1 and not r[r.group == "S"].declared.any()
    r2 = declare_heat_wave(_days(rows[::-1]))
    assert r.sort_values(["group", "date"]).declared.tolist() == r2.sort_values(["group", "date"]).declared.tolist()


def test_severe_declaration_and_longer_persistence_setting():
    d = _days([(f"2026-05-0{i}", s, "N", 2) for i in (1, 2, 3) for s in ("a", "b")])
    r = declare_heat_wave(d)
    assert r.severe_declared.tolist() == [False, True, True]
    assert declare_heat_wave(d, min_days=3).declared.tolist() == [False, False, True]


def test_every_station_has_a_valid_terrain_class():
    assert {l.terrain for l in LOCATIONS} <= {"plains", "coastal", "hilly"}
    assert LOC_BY_ID["sxr"].terrain == "hilly" and LOC_BY_ID["bom"].terrain == "coastal" and LOC_BY_ID["del"].terrain == "plains"


def test_definitions_state_it_is_an_indicator():
    d = definitions()
    assert "not an IMD declaration" in d["heat_wave"]["status"] and "Proxy" in d["high_wind_kmh"]["note"]
