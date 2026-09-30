"""Alignment diagnostics (sanity checks, not verification scores)."""

from __future__ import annotations

import numpy as np
import pandas as pd
import xarray as xr


def lag_correlation(
    forecast: xr.DataArray,
    truth: xr.DataArray,
    lead_index: int = 0,
    shifts: tuple[int, ...] = (-1, 0, 1),
) -> dict[int, float]:
    """Pearson r between forecast day D (one lead) and truth day D + shift, pooled over cells.

    ``forecast``: canonical ``precip_24h_mm`` (init_time, [member], lead_h, lat, lon) with
    ``valid_day``; ensembles are reduced to their mean. ``truth``: (time, lat, lon).
    If the day labels are aligned, shift 0 gives the highest correlation.
    """
    f = forecast.isel(lead_h=lead_index)
    if "member" in f.dims:
        f = f.mean("member")
    days = pd.DatetimeIndex(f["valid_day"].values)
    out: dict[int, float] = {}
    for s in shifts:
        xs, ys = [], []
        for i, d in enumerate(days):
            t = d + pd.Timedelta(days=s)
            if t not in set(pd.DatetimeIndex(truth.time.values)):
                continue
            a = f.isel(init_time=i).values.ravel()
            b = truth.sel(time=t).values.ravel()
            ok = np.isfinite(a) & np.isfinite(b)
            xs.append(a[ok])
            ys.append(b[ok])
        if xs and sum(x.size for x in xs) > 2:
            x, y = np.concatenate(xs), np.concatenate(ys)
            out[s] = float(np.corrcoef(x, y)[0, 1])
        else:
            out[s] = float("nan")
    return out
