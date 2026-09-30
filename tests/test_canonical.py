"""Canonical builder, schema and the Previous Runs mapping (SYNTHETIC inputs)."""

import datetime as dt

import numpy as np
import pandas as pd
import pytest
import xarray as xr

from trustcast.adapters.openmeteo_adapters import (
    _half_month_blocks,
    archive_to_canonical,
    previous_runs_run_time,
)
from trustcast.grid.align import hourly_intervals, lead_windows, step_intervals
from trustcast.grid.canonical import IntervalSeries, SampleSeries, build_canonical
from trustcast.grid.schema import SchemaError, validate_canonical

ATTRS = {
    "source": "synthetic",
    "model_version": "synthetic",
    "licence": "synthetic",
    "fetched_at": "2025-01-01T00:00:00",
    "regrid_method": "none",
    "init_semantics": "test",
}
LATS, LONS = np.array([10.0, 10.25]), np.array([76.0])
INIT = np.datetime64("2025-10-20T00:00")


def _hourly(hours=6 * 24, value=1.0):
    ends = INIT + np.arange(1, hours + 1).astype("timedelta64[h]")
    s, e = hourly_intervals(ends)
    return IntervalSeries(np.full((hours, 2, 1), value, np.float32), s, e), SampleSeries(
        (20 + (np.arange(hours) % 24)).astype(np.float32)[:, None, None] * np.ones((1, 2, 1)), ends
    )


def test_deterministic_windows_values_and_coords():
    p, t = _hourly()
    ds = build_canonical(INIT, 5, LATS, LONS, p, t, ATTRS)
    validate_canonical(ds)
    assert ds.lead_h.values.tolist() == [27, 51, 75, 99, 123]
    assert [str(d)[:10] for d in ds.valid_day.values[0]] == [
        "2025-10-21",
        "2025-10-22",
        "2025-10-23",
        "2025-10-24",
        "2025-10-25",
    ]
    assert np.allclose(ds.precip_24h_mm.values, 24.0)
    assert np.allclose(ds.tmax_c.values, 43.0)  # 20 + 23


def test_ensemble_dims_and_member_order():
    s, e = step_intervals(INIT, np.arange(0, 130, 6))
    vals = (
        np.ones((s.size, 3, 2, 1), np.float32)
        * np.array([1, 2, 3], np.float32)[None, :, None, None]
    )
    times = INIT + np.arange(0, 130, 6).astype("timedelta64[h]")
    temps = np.ones((times.size, 3, 2, 1), np.float32) * 30
    ds = build_canonical(
        INIT,
        5,
        LATS,
        LONS,
        IntervalSeries(vals, s, e),
        SampleSeries(temps, times),
        ATTRS,
        members=np.arange(3),
    )
    validate_canonical(ds)
    assert ds.precip_24h_mm.dims == ("init_time", "member", "lead_h", "lat", "lon")
    assert np.allclose(ds.precip_24h_mm.isel(member=2).values, 12.0)  # 4 x 6-h steps x rate 3


def test_per_lead_series_are_used_for_their_own_lead():
    series = []
    for k in range(1, 6):
        p, _ = _hourly(value=float(k))
        series.append(p)
    _, t = _hourly()
    ds = build_canonical(INIT, 5, LATS, LONS, series, t, ATTRS)
    assert ds.precip_24h_mm.values[0, :, 0, 0].tolist() == [24, 48, 72, 96, 120]


def test_short_series_gives_nan_for_uncovered_leads():
    p, t = _hourly(hours=3 * 24)
    ds = build_canonical(INIT, 5, LATS, LONS, p, t, ATTRS)
    assert np.isfinite(ds.precip_24h_mm.values[0, :2]).all()
    assert np.isnan(ds.precip_24h_mm.values[0, 3:]).all()
    assert np.isnan(ds.tmax_c.values[0, 3:]).all()


def test_schema_rejects_inconsistent_valid_day():
    p, t = _hourly()
    ds = build_canonical(INIT, 5, LATS, LONS, p, t, ATTRS)
    ds = ds.assign_coords(valid_day=ds.valid_day + np.timedelta64(1, "D"))
    with pytest.raises(SchemaError, match="valid_day"):
        validate_canonical(ds)


def test_schema_requires_init_semantics():
    p, t = _hourly()
    ds = build_canonical(
        INIT, 5, LATS, LONS, p, t, {k: v for k, v in ATTRS.items() if k != "init_semantics"}
    )
    with pytest.raises(SchemaError, match="init_semantics"):
        validate_canonical(ds)


@pytest.mark.parametrize("init", ["2025-10-20T00:00", "2024-02-28T00:00", "2025-12-31T00:00"])
def test_previous_runs_never_uses_a_run_after_nominal_init(init):
    """Leakage property of the verified Previous Runs mapping, for every hour of every lead."""
    i = pd.Timestamp(init)
    for k, (w0, w1) in enumerate(lead_windows(i.to_datetime64(), 5), start=1):
        hours = pd.date_range(pd.Timestamp(w0) + pd.Timedelta(hours=1), pd.Timestamp(w1), freq="h")
        runs = [previous_runs_run_time(h, k) for h in hours]
        assert max(runs) <= i
        assert min(runs) >= i - pd.Timedelta(days=1)


def test_previous_runs_mapping_matches_observation():
    # 2026-09-20 03Z, previous_day1 matched run 2026-09-19 00Z (20 locations, WORK.md)
    assert previous_runs_run_time(pd.Timestamp("2026-09-20T03:00"), 1) == pd.Timestamp(
        "2026-09-19T00:00"
    )
    assert previous_runs_run_time(pd.Timestamp("2026-09-20T21:00"), 2) == pd.Timestamp(
        "2026-09-18T18:00"
    )


def test_half_month_blocks():
    b = _half_month_blocks(
        [pd.Timestamp("2025-10-13"), pd.Timestamp("2025-10-20"), pd.Timestamp("2025-11-01")]
    )
    assert b == [
        (pd.Timestamp("2025-10-01"), pd.Timestamp("2025-10-14")),
        (pd.Timestamp("2025-10-15"), pd.Timestamp("2025-10-31")),
        (pd.Timestamp("2025-11-01"), pd.Timestamp("2025-11-14")),
    ]


def test_archive_to_canonical_hourly_run():
    from tests.fixtures.synthetic_openmeteo import fake_location
    from trustcast.adapters.openmeteo import responses_to_dataset
    from trustcast.grid.imd_grid import flatten_points

    init = dt.datetime(2026, 9, 30, 0)
    la, lo = flatten_points(LATS, LONS)
    locs = [fake_location(a, b, init, 168) for a, b in zip(la, lo, strict=True)]
    arch = responses_to_dataset(
        locs,
        LATS,
        LONS,
        init,
        168,
        ["precipitation", "temperature_2m"],
        {k: ATTRS[k] for k in ATTRS if k != "init_semantics"} | {"provider": "t"},
    )
    ds = archive_to_canonical(arch, 5, "test")
    validate_canonical(ds)
    hourly = arch.precip_1h_mm.values[0, :, 0, 0]
    assert ds.precip_24h_mm.values[0, 0, 0, 0] == pytest.approx(hourly[4:28].sum(), rel=1e-5)
    assert ds.attrs["init_semantics"].startswith("true init")
    assert isinstance(ds, xr.Dataset)
