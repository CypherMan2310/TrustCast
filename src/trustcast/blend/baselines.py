"""L0 baselines: benchmarks every later layer must beat.

* single source: each source as-is (ensembles: mean for deterministic scores, members for CRPS
  and probabilities)
* equal-weight mean: mean of all sources available for that case (missing sources dropped)
* static superensemble: per-lead ridge regression on the sources, fitted with rolling origin
  (expanding window, refitted monthly) using only cases whose valid day is before the target
  month's first init: leak-free by construction
* climatology: IMD 1991-2020 day-of-year mean (+/- 15 days) per cell; also climatological
  exceedance frequencies (reference for Brier skill)
* persistence: the latest observed IMD day available at init (label init - 1 day) for all leads
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd
import xarray as xr

from trustcast.truth import imd

CLIM_YEARS = (1991, 2020)
CLIM_HALF_WINDOW = 15


def align_sources(dets: dict[str, xr.DataArray]) -> xr.DataArray:
    """Stack deterministic fields of several sources on a new ``source`` dim (outer join, NaN)."""
    names = list(dets)
    stacked = xr.concat([dets[n] for n in names], dim=pd.Index(names, name="source"), join="outer")
    return stacked


def equal_mean(dets: dict[str, xr.DataArray]) -> xr.DataArray:
    """Equal-weight mean over sources available per case (NaN only if all are missing)."""
    return align_sources(dets).mean("source", skipna=True)


def superensemble(
    dets: dict[str, xr.DataArray], obs: xr.DataArray, ridge: float = 1.0, min_train_days: int = 90
) -> xr.DataArray:
    """Rolling-origin, per-lead ridge regression y = a + sum_s b_s x_s (pooled over cells).

    For each target month, sources with >= ``min_train_days`` of training days *and* data in the
    target month are used; training cases have valid_day < first init of the month; rows with any
    missing selected source are dropped. Predictions need all selected sources (else NaN).
    """
    xs = align_sources(dets).transpose("source", "init_time", "lead_h", "lat", "lon")
    y = obs.reindex_like(xs.isel(source=0)).values
    xv = xs.values
    inits = pd.DatetimeIndex(xs.init_time.values)
    vday = xs["valid_day"].values if "valid_day" in xs.coords else None
    if vday is None:
        raise ValueError("forecasts need a valid_day coordinate")
    out = np.full(y.shape, np.nan, dtype=np.float32)
    months = inits.to_period("M").unique()
    for li in range(xs.sizes["lead_h"]):
        for m in months:
            tgt = np.flatnonzero(inits.to_period("M") == m)
            t0 = inits[tgt[0]]
            train = np.flatnonzero(pd.DatetimeIndex(vday[:, li]) < t0)
            if train.size < min_train_days:
                continue
            xs_tr = xv[:, train, li]  # (S, n_tr, lat, lon)
            xs_tg = xv[:, tgt, li]
            has_tr = np.array(
                [
                    np.isfinite(xs_tr[s]).any(axis=(1, 2)).sum() >= min_train_days
                    for s in range(xv.shape[0])
                ]
            )
            has_tg = np.isfinite(xs_tg).any(axis=(1, 2, 3))
            use = has_tr & has_tg
            if not use.any():
                continue
            a_tr = xs_tr[use].reshape(use.sum(), -1).T
            b = y[train, li].ravel()
            ok = np.isfinite(a_tr).all(axis=1) & np.isfinite(b)
            if ok.sum() < 50:
                continue
            a_tr, b = a_tr[ok], b[ok]
            mu, sd = a_tr.mean(0), a_tr.std(0) + 1e-6
            z = np.column_stack([np.ones(len(a_tr)), (a_tr - mu) / sd])
            reg = ridge * np.eye(z.shape[1])
            reg[0, 0] = 0.0
            coef = np.linalg.solve(z.T @ z + reg, z.T @ b)
            p_tg = xs_tg[use].reshape(use.sum(), -1).T
            pred = coef[0] + ((p_tg - mu) / sd) @ coef[1:]
            out[tgt, li] = pred.reshape(len(tgt), *y.shape[2:]).astype(np.float32)
    res = xr.DataArray(
        out,
        dims=("init_time", "lead_h", "lat", "lon"),
        coords={k: xs.coords[k] for k in ("init_time", "lead_h", "lat", "lon")},
    )
    return res.assign_coords(valid_day=xs["valid_day"])


def persistence(truth: xr.DataArray, like: xr.DataArray) -> xr.DataArray:
    """Latest observed IMD day at init (label init - 1 day), repeated for every lead."""
    inits = pd.DatetimeIndex(like.init_time.values)
    last_obs = truth.reindex(time=inits.normalize() - pd.Timedelta(days=1)).values
    arr = np.repeat(last_obs[:, None], like.sizes["lead_h"], axis=1)
    return xr.DataArray(
        arr.astype(np.float32),
        dims=("init_time", "lead_h", "lat", "lon"),
        coords={k: like.coords[k] for k in ("init_time", "lead_h", "lat", "lon")},
    )


def climatology_available(root: Path) -> dict[str, list[int]]:
    """Years of the 1991-2020 normal present on disk, per variable."""
    return {
        v: [y for y in range(CLIM_YEARS[0], CLIM_YEARS[1] + 1) if imd.grd_path(root, v, y)]
        for v in ("rain", "tmax")
    }


def build_climatology(
    root: Path, var: str, region, thresholds: tuple[float, ...] = ()
) -> xr.Dataset | None:
    """Day-of-year climatology (mean and exceedance frequencies) on the region's IMD points.

    Returns None unless all 30 years of the normal are on disk (no partial normals).
    """
    years = climatology_available(root)[var]
    if len(years) < CLIM_YEARS[1] - CLIM_YEARS[0] + 1:
        return None
    fields = []
    for y in years:
        da = imd.read_grd(imd.grd_path(root, var, y), var, y)
        da = imd.rain_on_region(da, region) if var == "rain" else imd.tmax_on_region(da, region)
        fields.append(da)
    allf = xr.concat(fields, dim="time")
    doy = allf.time.dt.dayofyear.values
    doy = np.where(doy == 366, 365, doy)  # fold 29 Feb onto 28 Feb's neighbour
    vals = allf.values
    mean = np.full((365, *vals.shape[1:]), np.nan, np.float32)
    freqs = {t: np.full_like(mean, np.nan) for t in thresholds}
    for d in range(1, 366):
        dist = np.minimum(np.abs(doy - d), 365 - np.abs(doy - d))
        sel = vals[dist <= CLIM_HALF_WINDOW]
        with np.errstate(all="ignore"):
            mean[d - 1] = np.nanmean(sel, axis=0)
            for t in thresholds:
                ok = np.isfinite(sel)
                hits = (np.where(ok, sel, -np.inf) >= t).sum(0)
                freqs[t][d - 1] = np.where(ok.any(0), hits / np.maximum(ok.sum(0), 1), np.nan)
    ds = xr.Dataset(
        {"mean": (("doy", "lat", "lon"), mean)},
        coords={"doy": np.arange(1, 366), "lat": allf.lat, "lon": allf.lon},
        attrs={"years": f"{years[0]}-{years[-1]}", "window_days": 2 * CLIM_HALF_WINDOW + 1},
    )
    for t in thresholds:
        ds[f"p_ge_{t}"] = (("doy", "lat", "lon"), freqs[t])
    return ds


def clim_for(clim: xr.Dataset, var: str, like: xr.DataArray) -> xr.DataArray:
    """Climatology field ``var`` arranged like a forecast via its ``valid_day``."""
    vd = pd.DatetimeIndex(like["valid_day"].values.ravel())
    doy = np.minimum(vd.dayofyear.to_numpy(), 365)
    arr = clim[var].values[doy - 1].reshape(like["valid_day"].shape + clim[var].shape[1:])
    return xr.DataArray(
        arr,
        dims=("init_time", "lead_h", "lat", "lon"),
        coords={k: like.coords[k] for k in ("init_time", "lead_h", "lat", "lon")},
    )
