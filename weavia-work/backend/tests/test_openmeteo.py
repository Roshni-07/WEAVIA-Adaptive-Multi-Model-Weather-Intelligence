"""Open-Meteo provider against a deterministic fake of the documented API shape.
These tests prove OUR parsing, aggregation and error handling. They cannot prove the real service behaves as
documented: `python -m weavia.live check` does that on a machine with internet access."""
import numpy as np
import pandas as pd
import pytest

from fake_openmeteo import NOW, FakeOpenMeteo, base_value, make_client
from weavia.locations import LOCATIONS
from weavia.providers.base import FetchSpec
from weavia.providers.openmeteo import (OpenMeteoArchiveObservations, OpenMeteoError, OpenMeteoModelProvider,
                                         check_models, floor_to_cycle, to_grid)

LOCS = LOCATIONS[:3]


def test_to_grid_instant_and_summed():
    idx = pd.date_range("2026-01-01T00:00Z", periods=24, freq="h")
    inst = to_grid(pd.Series(np.arange(24.0), index=idx), summed=False)
    assert list(inst.index.hour) == [0, 6, 12, 18] and list(inst.values) == [0, 6, 12, 18]
    summed = to_grid(pd.Series(np.ones(24), index=idx), summed=True)
    assert (summed.values == 6.0).all() and 0 not in summed.index.hour[:1].tolist()   # first grid hour has no 6 h history


def test_to_grid_drops_incomplete_precip_windows():
    idx = pd.date_range("2026-01-01T00:00Z", periods=24, freq="h")
    s = pd.Series(np.ones(24), index=idx)
    s.iloc[8] = np.nan                                   # inside the window ending 12:00
    out = to_grid(s, summed=True)
    assert pd.Timestamp("2026-01-01T12:00Z") not in out.index and pd.Timestamp("2026-01-01T18:00Z") in out.index


def test_live_fetch_leads_units_and_validation():
    client, fake = make_client()
    p = OpenMeteoModelProvider("ifs", "live", client=client, issue_time=NOW)
    df, rep = p.get_forecasts(FetchSpec(LOCS, leads=(6, 12, 24, 48, 72)))
    assert rep.ok, rep.issues
    assert set(df.lead_h) == {6, 12, 24, 48, 72} and set(df.location_id) == {l.id for l in LOCS}
    assert (df.issue_time == floor_to_cycle(NOW)).all()
    v = df[(df.variable == "rain") & (df.lead_h == 24) & (df.location_id == LOCS[0].id)].value.iloc[0]
    assert v == pytest.approx(6 * base_value("precipitation", LOCS[0].lat, NOW))      # 6 h sum, mm/6h
    t = df[(df.variable == "temp") & (df.lead_h == 24) & (df.location_id == LOCS[1].id)].value.iloc[0]
    valid = floor_to_cycle(NOW) + pd.Timedelta(hours=24)
    assert t == pytest.approx(base_value("temperature_2m", LOCS[1].lat, valid))        # instant, sampled at valid hour
    assert len(fake.requests) == 1                                                     # one call for all locations
    assert fake.requests[0].url.params["models"] == "ecmwf_ifs025"


def test_previous_runs_issue_time_lead_and_chunking():
    client, fake = make_client()
    p = OpenMeteoModelProvider("gfs", "previous_runs", client=client, issue_time=NOW, chunk_days=10)
    start, end = pd.Timestamp("2026-09-01T00:00Z"), pd.Timestamp("2026-09-25T00:00Z")
    df, rep = p.get_forecasts(FetchSpec(LOCS, start=start, end=end, leads=(6, 24, 48, 72)))
    assert rep.ok, rep.issues
    assert set(df.lead_h) == {24, 48, 72} and p.skipped_leads == [6]                   # 6 h cannot come from day offsets
    assert len(fake.requests) == 3                                                     # 25 days in 10-day chunks
    assert ((df.valid_time - df.issue_time) == pd.to_timedelta(df.lead_h, unit="h")).all()
    assert set(df.issue_time.dt.hour) == {0, 6, 12, 18}
    r = df[(df.variable == "pressure") & (df.lead_h == 48)].value.iloc[0]
    assert r == pytest.approx(base_value("pressure_msl", 0, NOW, k=2))                 # previous_day2 -> 48 h lead
    assert not df.duplicated(["issue_time", "valid_time", "location_id", "variable"]).any()


def test_archive_truth_is_canonical_and_labelled():
    client, _ = make_client()
    spec = FetchSpec(LOCS, start=pd.Timestamp("2026-09-01T00:00Z"), end=pd.Timestamp("2026-09-03T00:00Z"))
    obs = OpenMeteoArchiveObservations(client).fetch(spec)
    assert set(obs.variable) == {"temp", "rain", "wind", "rh", "pressure"}
    assert str(obs.timestamp.dt.tz) == "UTC" and set(obs.timestamp.dt.hour) <= {0, 6, 12, 18}
    assert obs.timestamp.min() >= spec.start and obs.timestamp.max() <= spec.end
    assert obs.source.str.contains("reanalysis").all()                                 # never presented as station data
    rain = obs[(obs.variable == "rain") & (obs.location_id == LOCS[0].id)].value
    assert len(rain) > 0 and np.allclose(rain, 6 * 0.5)


def test_client_retries_transient_failures_then_succeeds():
    client, fake = make_client(FakeOpenMeteo(fail_first=2, fail_status=500))
    p = OpenMeteoModelProvider("icon", "live", client=client, issue_time=NOW)
    assert len(p.fetch(FetchSpec(LOCS[:1], leads=(24,)))) > 0 and client.calls == 3


def test_client_honours_429_and_gives_up_after_retries():
    client, _ = make_client(FakeOpenMeteo(fail_first=99, fail_status=429), retries=2)
    with pytest.raises(OpenMeteoError, match="gave up after 3 attempts"):
        OpenMeteoModelProvider("icon", "live", client=client, issue_time=NOW).fetch(FetchSpec(LOCS[:1], leads=(24,)))


def test_bad_model_id_fails_loudly_with_the_apis_reason():
    client, _ = make_client(FakeOpenMeteo(bad_models={"ecmwf_aifs025_single"}))
    with pytest.raises(OpenMeteoError, match="invalid String value ecmwf_aifs025_single"):
        OpenMeteoModelProvider("aifs", "live", client=client, issue_time=NOW).fetch(FetchSpec(LOCS[:1], leads=(24,)))
    assert client.calls == 1                                                           # 400 is not retried


def test_missing_variable_and_wrong_location_count_are_errors_not_silence():
    client, _ = make_client(FakeOpenMeteo(drop_var="precipitation"))
    with pytest.raises(OpenMeteoError, match="lacks 'precipitation'"):
        OpenMeteoModelProvider("gfs", "live", client=client, issue_time=NOW).fetch(FetchSpec(LOCS, leads=(24,)))
    client, _ = make_client(FakeOpenMeteo(wrong_count=True))
    with pytest.raises(OpenMeteoError, match="asked for 3 locations, got 2"):
        OpenMeteoModelProvider("gfs", "live", client=client, issue_time=NOW).fetch(FetchSpec(LOCS, leads=(24,)))


def test_check_models_reports_ok_and_names_the_failure():
    client, _ = make_client()
    rep = check_models(client=client, now=NOW)
    assert set(rep) >= {"ifs:live", "ifs:previous_runs", "aifs:live", "gfs:previous_runs", "icon:live", "archive", "archive:normals"}
    assert all(v == "ok" for v in rep.values()), rep
    client, _ = make_client(FakeOpenMeteo(bad_models={"icon_global"}))
    rep = check_models(client=client, now=NOW)
    assert rep["ifs:live"] == "ok" and "invalid String value icon_global" in rep["icon:live"]


def test_unknown_model_key_and_mode_rejected():
    with pytest.raises(KeyError):
        OpenMeteoModelProvider("nope")
    with pytest.raises(ValueError):
        OpenMeteoModelProvider("ifs", "bogus")
