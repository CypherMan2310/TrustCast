"""L1 bias correction: empirical quantile mapping, fitted with a rolling origin.

Maps are fitted per source x lead day x season, pooled over the cells of a region (the region is
the "subdivision" level: with ~2 years of history, per-cell maps would have ~30 cases per season).
For a target month, training cases are those with valid day before the month's first init
(leak-free), restricted to the target month's season when that season has at least
``min_cases`` training cases, otherwise all seasons.

Mapping x -> y: piecewise-linear between forecast quantiles fq and observed quantiles oq at levels
0.01..0.99; beyond the top quantile rain scales multiplicatively (y = oq_top * x / fq_top) and
temperature shifts additively; below the bottom quantile y = oq_bottom (+ shift for temperature).
Rain values of 0 stay 0 (no drizzle is created from dry forecasts). Ensembles: the map fitted on
member values is applied to every member.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import xarray as xr

from trustcast.verify.data import season_of

LEVELS = np.linspace(0.01, 0.99, 99)


def fit_map(fc: np.ndarray, obs: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """Forecast and observed quantiles at LEVELS (inputs: paired finite samples)."""
    return np.quantile(fc, LEVELS), np.quantile(obs, LEVELS)


def apply_map(x: np.ndarray, fq: np.ndarray, oq: np.ndarray, kind: str) -> np.ndarray:
    """Apply a quantile map (``kind``: "rain" or "temp"); NaN stays NaN."""
    x = np.asarray(x, dtype=np.float64)
    # collapse ties in fq (e.g. many zero-rain quantiles) to keep np.interp well defined
    ufq, idx = np.unique(fq, return_index=True)
    uoq = np.maximum.accumulate(oq[idx])
    y = np.interp(x, ufq, uoq)
    top, bot = ufq[-1], ufq[0]
    if kind == "rain":
        hi = x > top
        y[hi] = uoq[-1] * x[hi] / top if top > 0 else uoq[-1] + (x[hi] - top)
        y[x <= 0] = 0.0
        y = np.maximum(y, 0.0)
    else:
        y[x > top] = uoq[-1] + (x[x > top] - top)
        y[x < bot] = uoq[0] + (x[x < bot] - bot)
    y[~np.isfinite(x)] = np.nan
    return y


def rolling_qm(
    fc: xr.DataArray, obs: xr.DataArray, kind: str, min_cases: int = 1500
) -> xr.DataArray:
    """Leak-free, monthly-refitted quantile mapping of ``fc``.

    ``fc`` dims: init_time, [member], lead_h, lat, lon. Months without enough training data are
    left uncorrected (identity).
    """
    has_m = "member" in fc.dims
    f = fc.transpose("init_time", *(["member"] if has_m else []), "lead_h", "lat", "lon")
    fv = f.values.astype(np.float64)
    ov = obs.transpose("init_time", "lead_h", "lat", "lon").values
    out = fv.copy()
    inits = pd.DatetimeIndex(f.init_time.values)
    vd = fc["valid_day"].values
    months = inits.to_period("M")
    for li in range(f.sizes["lead_h"]):
        vdl = pd.DatetimeIndex(vd[:, li])
        seas = season_of(vd[:, li])
        for m in months.unique():
            tgt = np.flatnonzero(months == m)
            first = inits[tgt[0]]
            train_all = np.flatnonzero(vdl < first)
            if train_all.size == 0:
                continue
            tseason = season_of(np.array([first.to_datetime64()]))[0]
            train = train_all[seas[train_all] == tseason]
            if not _enough(fv, ov, train, li, has_m, min_cases):
                train = train_all
                if not _enough(fv, ov, train, li, has_m, min_cases):
                    continue
            xs, ys = _pairs(fv, ov, train, li, has_m)
            fq, oq = fit_map(xs, ys)
            if has_m:
                out[tgt, :, li] = apply_map(fv[tgt, :, li], fq, oq, kind)
            else:
                out[tgt, li] = apply_map(fv[tgt, li], fq, oq, kind)
    res = f.copy(data=out.astype(np.float32))
    return res.transpose(*fc.dims)


def _pairs(fv, ov, idx, li, has_m):
    if has_m:
        x = fv[idx, :, li]  # (n, member, lat, lon)
        y = np.broadcast_to(ov[idx, li][:, None], x.shape)
    else:
        x, y = fv[idx, li], ov[idx, li]
    ok = np.isfinite(x) & np.isfinite(y)
    return x[ok], y[ok]


def _enough(fv, ov, idx, li, has_m, min_cases) -> bool:
    if idx.size == 0:
        return False
    x, _ = _pairs(fv, ov, idx, li, has_m)
    n = x.size / (fv.shape[1] if has_m else 1)
    return n >= min_cases
