"""Open-Meteo JSON -> archive_hourly_v1 conversion (SYNTHETIC fixtures)."""

import datetime as dt

import numpy as np
import pytest

from tests.fixtures.synthetic_openmeteo import fake_location
from trustcast.adapters.base import SourceUnavailable
from trustcast.adapters.openmeteo import responses_to_dataset
from trustcast.grid.imd_grid import flatten_points
from trustcast.grid.schema import SchemaError, validate_archive

INIT = dt.datetime(2026, 9, 30, 12)
LATS = np.array([10.0, 10.25])
LONS = np.array([76.0, 76.25, 76.5])
ATTRS = {
    "source": "test",
    "model_version": "synthetic",
    "licence": "synthetic",
    "fetched_at": "2026-09-30T00:00:00",
    "regrid_method": "none",
}
VARS = ["precipitation", "temperature_2m"]


def _locs(hours=24, **kw):
    la, lo = flatten_points(LATS, LONS)
    return [fake_location(a, b, INIT, hours, **kw) for a, b in zip(la, lo, strict=True)]


def test_shape_dims_and_schema():
    ds = responses_to_dataset(_locs(), LATS, LONS, INIT, 24, VARS, ATTRS)
    validate_archive(ds)
    assert dict(ds.sizes) == {"init_time": 1, "lead_h": 24, "lat": 2, "lon": 3}
    assert ds.lead_h.values.tolist() == list(range(24))
    assert str(ds.valid_time.values[0, 5])[:16] == "2026-09-30T17:00"


def test_values_land_in_the_right_cell():
    locs = _locs()
    ds = responses_to_dataset(locs, LATS, LONS, INIT, 24, VARS, ATTRS)
    # location index 4 = (lat 10.25, lon 76.25) in row-major order
    assert ds.t2m_c.values[0, 3, 1, 1] == pytest.approx(locs[4]["hourly"]["temperature_2m"][3])
    expected = locs[2]["hourly"]["precipitation"][7]
    assert ds.precip_1h_mm.values[0, 7, 0, 2] == pytest.approx(expected)


def test_null_becomes_nan_not_zero():
    ds = responses_to_dataset(_locs(), LATS, LONS, INIT, 24, VARS, ATTRS)
    assert np.isnan(ds.precip_1h_mm.values[0, 0]).all()
    assert np.isfinite(ds.precip_1h_mm.values[0, 1:]).all()


def test_short_response_leaves_nan_leads():
    ds = responses_to_dataset(_locs(hours=20), LATS, LONS, INIT, 24, VARS, ATTRS)
    assert np.isnan(ds.t2m_c.values[0, 20:]).all()
    assert np.isfinite(ds.t2m_c.values[0, :20]).all()


def test_all_null_variable_raises():
    with pytest.raises(SourceUnavailable, match="entirely missing"):
        responses_to_dataset(_locs(all_null="precipitation"), LATS, LONS, INIT, 24, VARS, ATTRS)


def test_location_count_mismatch_raises():
    with pytest.raises(SourceUnavailable, match="expected 6"):
        responses_to_dataset(_locs()[:5], LATS, LONS, INIT, 24, VARS, ATTRS)


def test_misordered_locations_raise():
    locs = _locs()
    locs[0], locs[5] = locs[5], locs[0]
    locs[0]["latitude"] = 11.5  # far from requested 10.0
    with pytest.raises(SourceUnavailable, match="too far"):
        responses_to_dataset(locs, LATS, LONS, INIT, 24, VARS, ATTRS)


def test_schema_rejects_missing_attrs():
    ds = responses_to_dataset(_locs(), LATS, LONS, INIT, 24, VARS, ATTRS)
    del ds.attrs["licence"]
    with pytest.raises(SchemaError, match="licence"):
        validate_archive(ds)


def test_schema_rejects_implausible_values():
    ds = responses_to_dataset(_locs(), LATS, LONS, INIT, 24, VARS, ATTRS)
    ds["t2m_c"].values[0, 0, 0, 0] = 150.0
    with pytest.raises(SchemaError, match="plausible"):
        validate_archive(ds)
