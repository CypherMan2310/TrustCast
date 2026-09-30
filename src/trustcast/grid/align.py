"""Accumulation-window alignment to the IMD rain day.

IMD day ``D`` = the 24 h ending 08:30 IST on ``D`` = the interval (D-1 03:00 UTC, D 03:00 UTC].
Verified on real data (WORK.md 2026-09-30): forecast/IMD correlation peaks for windows ending at
03 UTC on the labelled date and is clearly lower for UTC calendar days.

Every source is reduced to *intervals* ``(start, end]`` carrying either an accumulated amount
(mm) or a maximum. Windows are filled by overlap:

* amounts: a partially overlapping interval contributes ``amount * overlap / length``
  (uniform rate within the interval; exact whenever interval edges fall on 03 UTC);
* maxima: any interval overlapping the window contributes its maximum;
* instantaneous samples (e.g. hourly/6-hourly t2m): samples with time in ``(start, end]``.

A window is NaN unless it is fully covered by non-missing intervals (amounts) or has the
minimum number of valid samples (maxima). Missing data is never treated as zero.
"""

from __future__ import annotations

import datetime as dt

import numpy as np
import pandas as pd

from trustcast.grid.schema import IMD_DAY_END_UTC_HOUR

_H = np.timedelta64(1, "h")


def imd_window(day: dt.date | pd.Timestamp) -> tuple[np.datetime64, np.datetime64]:
    """(start, end] of IMD day ``day`` in UTC: (D-1 03Z, D 03Z]."""
    d = pd.Timestamp(day).normalize()
    end = d + pd.Timedelta(hours=IMD_DAY_END_UTC_HOUR)
    return (end - pd.Timedelta(days=1)).to_datetime64(), end.to_datetime64()


def imd_day_of_window_end(end: np.datetime64) -> pd.Timestamp:
    """IMD day label for a window ending at ``end`` (must be 03 UTC)."""
    t = pd.Timestamp(end)
    if t.hour != IMD_DAY_END_UTC_HOUR or t.minute or t.second:
        raise ValueError(f"{t} is not an IMD window end (03:00 UTC)")
    return t.normalize()


def lead_windows(
    init: np.datetime64 | dt.datetime, lead_days: int
) -> list[tuple[np.datetime64, np.datetime64]]:
    """The first ``lead_days`` complete IMD windows starting at or after ``init``.

    For a 00Z init the windows end at init + 27 h, 51 h, ...; for 12Z at +39 h, +63 h, ...
    """
    t0 = pd.Timestamp(init)
    first_end = t0.normalize() + pd.Timedelta(hours=IMD_DAY_END_UTC_HOUR)
    while first_end - pd.Timedelta(days=1) < t0:
        first_end += pd.Timedelta(days=1)
    ends = [first_end + pd.Timedelta(days=k) for k in range(lead_days)]
    return [((e - pd.Timedelta(days=1)).to_datetime64(), e.to_datetime64()) for e in ends]


def window_amount(
    amounts: np.ndarray,
    starts: np.ndarray,
    ends: np.ndarray,
    w_start: np.datetime64,
    w_end: np.datetime64,
) -> np.ndarray:
    """Accumulate interval amounts over ``(w_start, w_end]``.

    ``amounts`` has the interval axis first: shape (n_intervals, ...). ``starts``/``ends`` are
    datetime64 arrays of length n_intervals. Returns shape ``amounts.shape[1:]``; NaN where any
    overlapping interval is missing or the window is not fully covered.
    """
    starts = np.asarray(starts, dtype="datetime64[ns]")
    ends = np.asarray(ends, dtype="datetime64[ns]")
    w_start, w_end = np.datetime64(w_start, "ns"), np.datetime64(w_end, "ns")
    lo = np.maximum(starts, w_start)
    hi = np.minimum(ends, w_end)
    overlap_h = np.clip((hi - lo) / _H, 0, None)
    length_h = (ends - starts) / _H
    if np.any(length_h <= 0):
        raise ValueError("intervals must have positive length")
    use = overlap_h > 0
    covered_h = overlap_h[use].sum()
    window_h = (w_end - w_start) / _H
    out_shape = amounts.shape[1:]
    if covered_h + 1e-9 < window_h:
        return np.full(out_shape, np.nan, dtype=np.float32)
    frac = (overlap_h[use] / length_h[use]).reshape((-1,) + (1,) * len(out_shape))
    sel = amounts[use].astype(np.float64)
    total = (sel * frac).sum(axis=0)  # NaN propagates: any missing piece -> NaN
    return total.astype(np.float32)


def window_max_intervals(
    maxima: np.ndarray,
    starts: np.ndarray,
    ends: np.ndarray,
    w_start: np.datetime64,
    w_end: np.datetime64,
) -> np.ndarray:
    """Maximum over intervals overlapping ``(w_start, w_end]``.

    NaN if the window is not fully covered or any overlapping interval is missing.
    """
    starts = np.asarray(starts, dtype="datetime64[ns]")
    ends = np.asarray(ends, dtype="datetime64[ns]")
    w_start, w_end = np.datetime64(w_start, "ns"), np.datetime64(w_end, "ns")
    overlap_h = np.clip((np.minimum(ends, w_end) - np.maximum(starts, w_start)) / _H, 0, None)
    use = overlap_h > 0
    if overlap_h[use].sum() + 1e-9 < (w_end - w_start) / _H:
        return np.full(maxima.shape[1:], np.nan, dtype=np.float32)
    sel = maxima[use].astype(np.float64)
    out = sel.max(axis=0)
    out[np.isnan(sel).any(axis=0)] = np.nan
    return out.astype(np.float32)


def window_max_samples(
    samples: np.ndarray,
    times: np.ndarray,
    w_start: np.datetime64,
    w_end: np.datetime64,
    min_samples: int,
) -> np.ndarray:
    """Maximum of instantaneous samples with time in ``(w_start, w_end]``.

    NaN unless at least ``min_samples`` valid samples fall in the window. Coarse sampling
    (e.g. 6-hourly) underestimates the true daily maximum; bias correction handles the
    systematic part.
    """
    times = np.asarray(times, dtype="datetime64[ns]")
    use = (times > np.datetime64(w_start, "ns")) & (times <= np.datetime64(w_end, "ns"))
    sel = samples[use].astype(np.float64)
    n_valid = np.isfinite(sel).sum(axis=0)
    with np.errstate(all="ignore"):
        out = (
            np.nanmax(np.where(np.isfinite(sel), sel, -np.inf), axis=0)
            if sel.shape[0]
            else (np.full(samples.shape[1:], np.nan))
        )
    out = np.where(n_valid >= min_samples, out, np.nan)
    return out.astype(np.float32)


def hourly_intervals(valid_times: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """Intervals for 'amount in the hour ending at valid_time'."""
    ends = np.asarray(valid_times, dtype="datetime64[ns]")
    return ends - np.timedelta64(1, "h"), ends


def step_intervals(init: np.datetime64, leads_h: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """Intervals (lead[i-1], lead[i]] for 'average since previous step' variables.

    Returned arrays have length ``len(leads_h) - 1`` (the lead-0 step has no interval).
    """
    base = np.datetime64(init, "ns")
    t = base + np.asarray(leads_h, dtype="int64").astype("timedelta64[h]").astype("timedelta64[ns]")
    return t[:-1], t[1:]
