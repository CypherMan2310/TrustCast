"""Truth readers and schema (SYNTHETIC files, plus a local-real-data check when files exist)."""

import numpy as np
import pandas as pd
import pytest
import xarray as xr

from trustcast.config import data_root
from trustcast.grid.diagnostics import lag_correlation
from trustcast.grid.schema import SchemaError, validate_truth
from trustcast.truth import imd


def _write_grd(tmp_path, var, year, days):
    """SYNTHETIC IMD-format file: value = day index + lat index * 0.01; one missing cell per day."""
    g = imd.GRIDS[var]
    arr = np.zeros((days, g.nlat, g.nlon), "<f4")
    arr += np.arange(days)[:, None, None] + 0.01 * np.arange(g.nlat)[None, :, None]
    arr[:, 0, 0] = -999.0 if var == "rain" else 99.9
    p = tmp_path / "truth" / var / f"{year}.grd"
    p.parent.mkdir(parents=True)
    arr.tofile(p)
    return p


@pytest.mark.parametrize("var", ["rain", "tmax"])
def test_read_grd_layout_and_missing_codes(tmp_path, var):
    _write_grd(tmp_path, var, 2025, 3)
    da = imd.read_grd(imd.grd_path(tmp_path, var, 2025), var, 2025)
    g = imd.GRIDS[var]
    assert da.shape == (3, g.nlat, g.nlon)
    assert np.isnan(da.values[:, 0, 0]).all()
    assert da.values[2, 5, 7] == pytest.approx(2.05)  # day 2, lat index 5
    assert da.lat.values[0] == g.lat0 and da.time.values[0] == np.datetime64("2025-01-01")


def test_partial_year_file(tmp_path):
    _write_grd(tmp_path, "rain", 2026, 40)
    da = imd.read_grd(imd.grd_path(tmp_path, "rain", 2026), "rain", 2026)
    assert da.sizes["time"] == 40 and str(da.time.values[-1])[:10] == "2026-02-09"


def test_raw_reader_matches_imdlib_on_real_file():
    root = data_root()
    if imd.grd_path(root, "rain", 2024) is None:
        pytest.skip("real IMD 2024 rain file not present")
    import imdlib

    ref = imdlib.open_data("rain", 2024, 2024, "yearwise", str(root / "truth")).get_xarray()
    r = ref[next(iter(ref.data_vars))]
    r = r.where(r > -100).transpose("time", "lat", "lon").values
    mine = imd.read_grd(imd.grd_path(root, "rain", 2024), "rain", 2024).values
    assert np.allclose(mine, r, equal_nan=True, atol=1e-4)


def _truth(provisional_dtype=bool):
    t = pd.date_range("2025-10-21", periods=3)
    lat, lon = np.array([10.0, 10.25]), np.array([76.0])
    z = np.zeros((3, 2, 1), np.float32)
    return xr.Dataset(
        {
            "rain_mm": (("time", "lat", "lon"), z),
            "tmax_c": (("time", "lat", "lon"), z + 30),
            "provisional": ("time", np.zeros(3, provisional_dtype)),
        },
        coords={"time": t, "lat": lat, "lon": lon},
        attrs={
            "schema": "truth_v1",
            "sources": "synthetic",
            "licence": "synthetic",
            "created_at": "x",
            "tmax_regrid_method": "x",
        },
    )


def test_truth_schema():
    validate_truth(_truth())
    with pytest.raises(SchemaError, match="provisional"):
        validate_truth(_truth(provisional_dtype=int))


def test_lag_correlation_peaks_at_zero_for_aligned_labels():
    rng = np.random.default_rng(1)  # SYNTHETIC
    days = pd.date_range("2025-10-01", periods=30)
    field = rng.gamma(0.6, 10, (30, 4, 5)).astype(np.float32)
    truth = xr.DataArray(field, dims=("time", "lat", "lon"), coords={"time": days})
    fc = xr.DataArray(
        field[1:-1, None] + rng.normal(0, 1, (28, 1, 4, 5)),
        dims=("init_time", "lead_h", "lat", "lon"),
        coords={"valid_day": (("init_time", "lead_h"), days[1:-1].values[:, None])},
    )
    r = lag_correlation(fc, truth)
    assert r[0] > 0.9 and r[0] > r[-1] and r[0] > r[1]
