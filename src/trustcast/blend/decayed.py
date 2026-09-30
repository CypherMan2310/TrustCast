"""L3A adaptive blender A: weights proportional to 1 / DMSE^p, per cell and lead.

Missing sources are dropped and the weights renormalised (graceful degradation). A source with a
forecast but no skill history yet gets the median DMSE of the other available sources (neutral
prior); if no source has history, the weights are equal.
"""

from __future__ import annotations

import warnings

import numpy as np
import pandas as pd
import xarray as xr


def weights_from_dmse(fcs: np.ndarray, dmse: np.ndarray, p: float) -> np.ndarray:
    """Weights (S, ...) from forecasts and DMSE of S sources; zero where a forecast is missing."""
    have = np.isfinite(fcs)
    d = np.where(have, dmse, np.nan)
    with np.errstate(all="ignore"), warnings.catch_warnings():
        warnings.simplefilter("ignore", RuntimeWarning)  # all-NaN cells -> equal weights
        prior = np.nanmedian(d, axis=0)
    prior = np.where(np.isfinite(prior), prior, 1.0)
    d = np.where(have & ~np.isfinite(d), prior[None], d)
    d = np.maximum(d, 1e-6)
    w = np.where(have, d ** (-p), 0.0)
    tot = w.sum(axis=0)
    with np.errstate(all="ignore"):
        return np.where(tot > 0, w / tot, 0.0)


def blend_a(
    dets: dict[str, xr.DataArray], dmse: dict[str, xr.DataArray], p: float
) -> tuple[xr.DataArray, xr.DataArray]:
    """Blended forecast and weights (source, init_time, lead_h, lat, lon)."""
    names = list(dets)
    order = ("init_time", "lead_h", "lat", "lon")
    x = np.stack([dets[n].transpose(*order).values for n in names]).astype(np.float64)
    d = np.stack([dmse[n].transpose(*order).values for n in names]).astype(np.float64)
    w = weights_from_dmse(x, d, p)
    blended = np.where(np.isfinite(x).any(axis=0), (np.nan_to_num(x) * w).sum(axis=0), np.nan)
    like = dets[names[0]].transpose(*order)
    coords = {k: like.coords[k] for k in (*order, "valid_day") if k in like.coords}
    out = xr.DataArray(blended.astype(np.float32), dims=order, coords=coords)
    wts = xr.DataArray(
        w.astype(np.float32),
        dims=("source", *order),
        coords={"source": pd.Index(names), **{k: like.coords[k] for k in order}},
    )
    return out, wts
