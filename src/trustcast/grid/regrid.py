"""Regridding onto the IMD 0.25 deg grid.

Methods (recorded in the ``regrid_method`` attribute of every canonical dataset):

``identity``     source grid points coincide with the target points (all 0.25 deg global models:
                 IFS, AIFS, GFS, GEFS, IFS-ENS, AIFS-ENS). Pure selection, no interpolation.
``conservative`` area-weighted remapping for amounts (rain), separable on regular lat/lon grids
                 with exact spherical cell areas (sin(lat) weights). Used for IMERG 0.1 deg.
``bilinear``     for intensive fields (temperature) from coarser grids (IMD Tmax 1.0 deg).

xesmf was not used: it needs ESMF (conda-only on Windows). A separable conservative scheme is exact
for regular lat/lon grids and is unit-tested against hand-computed cases.
"""

from __future__ import annotations

import numpy as np
import xarray as xr

_TOL = 1e-6


def cell_edges(centres: np.ndarray, step: float | None = None) -> np.ndarray:
    """Edges of a regular 1-D grid given ascending cell centres (``step`` needed for one centre)."""
    c = np.asarray(centres, dtype=float)
    if c.size < 2:
        if step is None:
            raise ValueError("need two centres or an explicit step to infer cell edges")
        return np.array([c[0] - step / 2, c[0] + step / 2])
    d = np.diff(c)
    if not np.allclose(d, d[0], atol=1e-6) or d[0] <= 0:
        raise ValueError("centres must be regular and ascending")
    if step is not None and abs(step - d[0]) > 1e-6:
        raise ValueError(f"step {step} disagrees with centre spacing {d[0]}")
    h = d[0] / 2
    return np.concatenate([c - h, [c[-1] + h]])


def overlap_weights(src_edges: np.ndarray, dst_edges: np.ndarray, spherical: bool) -> np.ndarray:
    """Matrix W (n_dst, n_src): W[i, j] = measure(dst_i ∩ src_j) / measure(dst_i).

    ``spherical=True`` measures latitude bands by sin(lat) (exact spherical area).
    """
    f = (lambda x: np.sin(np.deg2rad(x))) if spherical else (lambda x: np.asarray(x, float))
    lo = np.maximum(dst_edges[:-1, None], src_edges[None, :-1])
    hi = np.minimum(dst_edges[1:, None], src_edges[None, 1:])
    inter = np.where(hi > lo, f(hi) - f(lo), 0.0)
    size = f(dst_edges[1:]) - f(dst_edges[:-1])
    return inter / size[:, None]


def conservative(
    da: xr.DataArray,
    dst_lat: np.ndarray,
    dst_lon: np.ndarray,
    lat: str = "lat",
    lon: str = "lon",
    min_coverage: float = 0.5,
    dst_step: float = 0.25,
) -> xr.DataArray:
    """Area-weighted remap of ``da`` (dims ... lat, lon; ascending) onto target centres.

    Missing source cells are excluded and the remaining weights renormalised; a target cell is NaN
    if less than ``min_coverage`` of its area has valid source data or lies inside the source grid.
    """
    src_lat = da[lat].values
    src_lon = da[lon].values
    wy = overlap_weights(cell_edges(src_lat), cell_edges(dst_lat, dst_step), spherical=True)
    wx = overlap_weights(cell_edges(src_lon), cell_edges(dst_lon, dst_step), spherical=False)
    x = da.transpose(..., lat, lon).values.astype(np.float64)
    valid = np.isfinite(x)
    xz = np.where(valid, x, 0.0)
    num = np.einsum("il,...lm,jm->...ij", wy, xz, wx, optimize=True)
    cov = np.einsum("il,...lm,jm->...ij", wy, valid.astype(float), wx, optimize=True)
    with np.errstate(invalid="ignore", divide="ignore"):
        out = np.where(cov >= min_coverage, num / cov, np.nan)
    dims = [d for d in da.dims if d not in (lat, lon)] + [lat, lon]
    coords = {d: da[d] for d in dims if d not in (lat, lon) and d in da.coords}
    coords.update({lat: dst_lat, lon: dst_lon})
    return xr.DataArray(out.astype(np.float32), dims=dims, coords=coords, attrs=da.attrs)


def identity(
    da: xr.DataArray, dst_lat: np.ndarray, dst_lon: np.ndarray, lat: str = "lat", lon: str = "lon"
) -> xr.DataArray:
    """Select target points that must exist exactly on the source grid (raises otherwise)."""
    out = da.sel({lat: dst_lat, lon: dst_lon}, method="nearest", tolerance=_TOL)
    return out.assign_coords({lat: dst_lat, lon: dst_lon})


def bilinear(
    da: xr.DataArray, dst_lat: np.ndarray, dst_lon: np.ndarray, lat: str = "lat", lon: str = "lon"
) -> xr.DataArray:
    """Bilinear interpolation (NaN outside the source grid's cell-centre hull)."""
    return da.interp({lat: dst_lat, lon: dst_lon}, method="linear").astype(np.float32)


def points_coincide(src: np.ndarray, dst: np.ndarray) -> bool:
    """True if every target coordinate is (within 1e-6) a source coordinate."""
    src = np.asarray(src, float)
    return bool(
        np.all(np.min(np.abs(src[None, :] - np.asarray(dst, float)[:, None]), axis=1) < _TOL)
    )
