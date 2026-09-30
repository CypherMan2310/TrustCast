"""Build ``canonical_v1`` datasets from interval / sample series of one init.

Adapters reduce each source to:

* precipitation as interval amounts (mm) with (start, end] bounds, and
* temperature as either interval maxima (e.g. GFS ``maximum_temperature_2m``, ECMWF ``mx2t3``)
  or instantaneous samples (e.g. hourly or 6-hourly ``temperature_2m``),

on the target IMD points (already regridded). This module turns them into IMD-day windows.
"""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass

import numpy as np
import pandas as pd
import xarray as xr

from trustcast.grid.align import (
    lead_windows,
    window_amount,
    window_max_intervals,
    window_max_samples,
)
from trustcast.grid.schema import CANONICAL_SCHEMA, IMD_DAY_END_UTC_HOUR


@dataclass
class IntervalSeries:
    """Values on the interval axis (axis 0) with (start, end] bounds."""

    values: np.ndarray
    starts: np.ndarray
    ends: np.ndarray


@dataclass
class SampleSeries:
    """Instantaneous values on the time axis (axis 0)."""

    values: np.ndarray
    times: np.ndarray


def build_canonical(
    init: np.datetime64 | dt.datetime,
    lead_days: int,
    lats: np.ndarray,
    lons: np.ndarray,
    precip: IntervalSeries | list[IntervalSeries],
    tmax: IntervalSeries | SampleSeries | list[IntervalSeries] | list[SampleSeries],
    attrs: dict[str, str],
    members: np.ndarray | None = None,
) -> xr.Dataset:
    """Aggregate one init's series into IMD-day windows.

    Value arrays are shaped (step, lat, lon) or, for ensembles, (step, member, lat, lon).
    ``precip``/``tmax`` may be a list with one series per lead day (e.g. Open-Meteo Previous
    Runs, where lead day k comes from the ``previous_day{k}`` column).
    Windows not fully covered by valid data are NaN.
    """
    init64 = np.datetime64(pd.Timestamp(init).to_datetime64(), "ns")
    windows = lead_windows(init64, lead_days)
    p_list = precip if isinstance(precip, list) else [precip] * lead_days
    t_list = tmax if isinstance(tmax, list) else [tmax] * lead_days
    if len(p_list) != lead_days or len(t_list) != lead_days:
        raise ValueError("per-lead series lists must have one entry per lead day")
    p_out, t_out = [], []
    for (w0, w1), ps, ts in zip(windows, p_list, t_list, strict=True):
        p_out.append(window_amount(ps.values, ps.starts, ps.ends, w0, w1))
        if isinstance(ts, IntervalSeries):
            t_out.append(window_max_intervals(ts.values, ts.starts, ts.ends, w0, w1))
        else:
            times = np.asarray(ts.times, dtype="datetime64[ns]")
            inside = (times > w0) & (times <= w1)
            n_expected = int(inside.sum())
            step = np.median(np.diff(times)) if times.size > 1 else np.timedelta64(24, "h")
            spans = times.size > 0 and times.max() >= w1 and times[inside].min() <= w0 + step
            if n_expected == 0 or not spans:
                shape = ts.values.shape[1:]
                t_out.append(np.full(shape, np.nan, dtype=np.float32))
            else:
                t_out.append(window_max_samples(ts.values, times, w0, w1, n_expected))
    lead_h = np.array([(w1 - init64) / np.timedelta64(1, "h") for _, w1 in windows], dtype=np.int16)
    valid_day = np.array(
        [w1 - np.timedelta64(IMD_DAY_END_UTC_HOUR, "h") for _, w1 in windows],
        dtype="datetime64[ns]",
    )

    p = np.stack(p_out)[None]  # (1, lead, [member], lat, lon)
    t = np.stack(t_out)[None]
    if members is not None:
        p, t = np.moveaxis(p, 2, 1), np.moveaxis(t, 2, 1)  # (1, member, lead, lat, lon)
        dims = ("init_time", "member", "lead_h", "lat", "lon")
    else:
        dims = ("init_time", "lead_h", "lat", "lon")
    coords: dict = {
        "init_time": [init64],
        "lead_h": lead_h,
        "lat": np.asarray(lats, dtype=np.float64),
        "lon": np.asarray(lons, dtype=np.float64),
        "valid_day": (("init_time", "lead_h"), valid_day[None]),
    }
    if members is not None:
        coords["member"] = np.asarray(members)
    ds = xr.Dataset(
        {
            "precip_24h_mm": (dims, p.astype(np.float32)),
            "tmax_c": (dims, t.astype(np.float32)),
        },
        coords=coords,
        attrs={"schema": CANONICAL_SCHEMA, **attrs},
    )
    # tiny negative rain from interpolation/rounding in providers is clipped, NaN preserved
    ds["precip_24h_mm"] = ds["precip_24h_mm"].clip(min=0.0)
    ds["precip_24h_mm"].attrs = {"units": "mm", "window": "03 UTC to 03 UTC, ending on valid_day"}
    ds["tmax_c"].attrs = {"units": "degC", "window": "03 UTC to 03 UTC, ending on valid_day"}
    return ds
