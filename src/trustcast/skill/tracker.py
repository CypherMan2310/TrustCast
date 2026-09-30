"""L2 leak-free skill tracker: exponentially decayed squared error.

For a forecast issued at init t (00Z), only cases whose IMD window has ended by t may be used:
window end = valid_day + 03 UTC <= t  <=>  valid_day <= t - 1 day (as dates, for 00Z inits).
The decayed mean squared error of a source at init t is

    DMSE(t) = sum_d w_d S_d / sum_d w_d N_d,  w_d = 0.5 ** ((t_day - 1 - d) / half_life),
    over verification days d <= t_day - 1

where S_d, N_d are the sum of squared errors and the case count of verification day d (per lead,
and per cell or pooled over the region). Computed recursively over days. ``penalty`` (optional,
e.g. from forecaster overrides) multiplies DMSE.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import xarray as xr


def decayed_mse(
    fc: xr.DataArray,
    obs: xr.DataArray,
    half_life_days: float,
    scope: str = "cell",
    min_eff: float = 3.0,
) -> xr.DataArray:
    """DMSE available at each init, dims (init_time, lead_h, lat, lon). NaN until ``min_eff``
    effective cases have been verified. ``scope``: "cell" (per grid cell) or "region" (pooled)."""
    return decayed_stat(fc, obs, half_life_days, scope, min_eff, squared=True)


def decayed_bias(
    fc: xr.DataArray,
    obs: xr.DataArray,
    half_life_days: float,
    scope: str = "cell",
    min_eff: float = 3.0,
) -> xr.DataArray:
    """Decayed mean error (forecast - observation) available at each init; same leak-free rule."""
    return decayed_stat(fc, obs, half_life_days, scope, min_eff, squared=False)


def decayed_stat(
    fc: xr.DataArray,
    obs: xr.DataArray,
    half_life_days: float,
    scope: str = "cell",
    min_eff: float = 3.0,
    squared: bool = True,
) -> xr.DataArray:
    """Exponentially decayed mean of the (squared) error, leak-free (see module docstring)."""
    if scope not in ("cell", "region"):
        raise ValueError("scope must be 'cell' or 'region'")
    f = fc.transpose("init_time", "lead_h", "lat", "lon")
    err = (f - obs.transpose("init_time", "lead_h", "lat", "lon")).values
    err2 = err**2 if squared else err
    inits = pd.DatetimeIndex(f.init_time.values).normalize()
    vd = (
        pd.DatetimeIndex(f["valid_day"].values.ravel())
        .normalize()
        .to_numpy()
        .reshape(f["valid_day"].shape)
    )
    day0 = min(inits.min(), pd.Timestamp(vd.min()))
    ndays = int((max(inits.max(), pd.Timestamp(vd.max())) - day0).days) + 2
    decay = 0.5 ** (1.0 / half_life_days)
    nlat, nlon = f.sizes["lat"], f.sizes["lon"]
    out = np.full(err2.shape, np.nan, dtype=np.float32)
    for li in range(f.sizes["lead_h"]):
        s_day = np.zeros((ndays, nlat, nlon))  # per verification day
        n_day = np.zeros((ndays, nlat, nlon))
        d_idx = ((pd.DatetimeIndex(vd[:, li]) - day0).days).to_numpy()
        e = err2[:, li]
        ok = np.isfinite(e)
        np.add.at(s_day, d_idx, np.where(ok, e, 0.0))
        np.add.at(n_day, d_idx, ok.astype(float))
        if scope == "region":
            s_day[:] = s_day.sum(axis=(1, 2), keepdims=True)
            n_day[:] = n_day.sum(axis=(1, 2), keepdims=True) / (
                nlat * nlon
            )  # effective per-cell count
            s_day /= nlat * nlon
        acc_s = np.zeros_like(s_day)  # decayed sums up to day d
        acc_n = np.zeros_like(n_day)
        a = np.zeros((nlat, nlon))
        b = np.zeros((nlat, nlon))
        for d in range(ndays):
            a = a * decay + s_day[d]
            b = b * decay + n_day[d]
            acc_s[d], acc_n[d] = a, b
        t_idx = ((inits - day0).days).to_numpy() - 1  # last usable verification day: t - 1
        valid_t = t_idx >= 0
        with np.errstate(invalid="ignore", divide="ignore"):
            dmse = np.where(
                acc_n[t_idx.clip(0)] >= min_eff, acc_s[t_idx.clip(0)] / acc_n[t_idx.clip(0)], np.nan
            )
        dmse[~valid_t] = np.nan
        out[:, li] = dmse
    return xr.DataArray(
        out,
        dims=("init_time", "lead_h", "lat", "lon"),
        coords={k: f.coords[k] for k in ("init_time", "lead_h", "lat", "lon")},
    )
