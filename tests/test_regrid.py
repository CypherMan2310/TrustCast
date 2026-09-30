"""Regridding against hand-computed cases."""

import numpy as np
import pytest
import xarray as xr

from trustcast.grid.regrid import (
    bilinear,
    cell_edges,
    conservative,
    identity,
    overlap_weights,
    points_coincide,
)


def _da(values, lat, lon):
    return xr.DataArray(
        np.asarray(values, float), dims=("lat", "lon"), coords={"lat": lat, "lon": lon}
    )


def test_cell_edges():
    assert cell_edges(np.array([0.05, 0.15, 0.25])).tolist() == pytest.approx([0.0, 0.1, 0.2, 0.3])


def test_overlap_weights_planar_hand_case():
    # dst cell [-0.125, 0.125] against 0.1 cells [-0.2,-0.1],[-0.1,0],[0,0.1],[0.1,0.2]
    w = overlap_weights(np.array([-0.2, -0.1, 0.0, 0.1, 0.2]), np.array([-0.125, 0.125]), False)
    assert w[0].tolist() == pytest.approx([0.1, 0.4, 0.4, 0.1])


def test_two_by_two_block_average_near_equator():
    src = _da([[1, 2], [3, 4]], [0.125, 0.375], [10.125, 10.375])
    out = conservative(
        src, np.array([0.25, 0.75]), np.array([10.25, 10.75]), min_coverage=0.2, dst_step=0.5
    )
    # target (0.25, 10.25) spans [0,0.5]x[10,10.5] = all four source cells, nearly equal areas
    assert out.values[0, 0] == pytest.approx(2.5, abs=1e-3)


def test_conservative_preserves_constant_and_area_integral():
    lat = np.round(np.arange(8.05, 13.0, 0.1), 2)
    lon = np.round(np.arange(74.05, 78.0, 0.1), 2)
    rng = np.random.default_rng(0)  # SYNTHETIC test field
    src = _da(rng.gamma(0.5, 10, (lat.size, lon.size)), lat, lon)
    dst_lat, dst_lon = np.arange(8.25, 12.76, 0.25), np.arange(74.25, 77.76, 0.25)
    const = conservative(xr.full_like(src, 7.0), dst_lat, dst_lon)
    assert np.allclose(const.values, 7.0)
    out = conservative(src, dst_lat, dst_lon)

    def integral(da, lat_c, lon_c):
        ey, ex = cell_edges(lat_c), cell_edges(lon_c)
        area = np.outer(np.diff(np.sin(np.deg2rad(ey))), np.diff(ex))
        return float((da.values * area).sum())

    # dst box [8.125,12.875]x[74.125,77.875] is covered exactly by the source cells inside it
    inner = src.sel(lat=slice(8.125, 12.875), lon=slice(74.125, 77.875))
    ey, ex = cell_edges(lat), cell_edges(lon)
    area = np.outer(np.diff(np.sin(np.deg2rad(ey))), np.diff(ex))
    wy = overlap_weights(ey, np.array([8.125, 12.875]), True)[0] * (
        np.sin(np.deg2rad(12.875)) - np.sin(np.deg2rad(8.125))
    )
    wx = overlap_weights(ex, np.array([74.125, 77.875]), False)[0] * 3.75
    src_integral = float(np.einsum("l,lm,m->", wy, src.values, wx))
    assert integral(out, dst_lat, dst_lon) == pytest.approx(src_integral, rel=1e-9)
    assert inner.size > 0 and area.shape == src.shape


def test_conservative_nan_renormalises_and_coverage_threshold():
    src = _da([[1, np.nan], [3, np.nan]], [0.125, 0.375], [10.125, 10.375])
    out = conservative(
        src, np.array([0.25, 0.75]), np.array([10.25, 10.75]), min_coverage=0.2, dst_step=0.5
    )
    assert out.values[0, 0] == pytest.approx(2.0, abs=1e-3)  # mean of the valid half
    assert np.isnan(out.values[1, 1])  # outside source grid
    strict = conservative(src, np.array([0.25]), np.array([10.25]), min_coverage=0.6, dst_step=0.5)
    assert np.isnan(strict.values[0, 0])  # only 50% valid


def test_identity_and_coincidence():
    lat = np.arange(5.0, 15.0, 0.25)
    lon = np.arange(70.0, 80.0, 0.25)
    src = _da(np.add.outer(lat, lon), lat, lon)
    out = identity(src, np.array([8.0, 8.25]), np.array([74.5]))
    assert out.values[:, 0].tolist() == [82.5, 82.75]
    assert points_coincide(lat, np.array([6.5, 8.25]))
    assert not points_coincide(np.arange(5.05, 15, 0.1), np.array([8.0]))
    with pytest.raises(KeyError):
        identity(src, np.array([8.1]), np.array([74.5]))


def test_bilinear_hand_case():
    src = _da([[20, 30], [40, 50]], [7.5, 8.5], [67.5, 68.5])
    out = bilinear(src, np.array([8.0]), np.array([67.75]))
    # lat 8.0 = midway between rows; lon 67.75 = quarter of the way: (22.5 + 42.5) / 2
    assert out.values[0, 0] == pytest.approx(32.5)
