"""IMD-day window alignment against hand-computed cases."""

import numpy as np
import pandas as pd
import pytest

from trustcast.grid.align import (
    hourly_intervals,
    imd_day_of_window_end,
    imd_window,
    lead_windows,
    step_intervals,
    window_amount,
    window_max_intervals,
    window_max_samples,
)

T = np.datetime64


def test_imd_window_is_03z_to_03z_ending_on_label_day():
    s, e = imd_window(pd.Timestamp("2024-07-30"))
    assert s == T("2024-07-29T03:00") and e == T("2024-07-30T03:00")
    assert imd_day_of_window_end(e) == pd.Timestamp("2024-07-30")
    with pytest.raises(ValueError):
        imd_day_of_window_end(T("2024-07-30T00:00"))


def test_lead_windows_00z_and_12z():
    w = lead_windows(T("2024-07-29T00:00"), 3)
    assert [e for _, e in w] == [T("2024-07-30T03"), T("2024-07-31T03"), T("2024-08-01T03")]
    assert w[0][0] == T("2024-07-29T03")  # lead_h 27 for 00Z
    w12 = lead_windows(T("2024-07-29T12:00"), 1)
    assert w12[0] == (T("2024-07-30T03"), T("2024-07-31T03"))  # first complete window, lead_h 39


def test_hourly_amount_exact_sum():
    # 1 mm in every hour from 00Z day1 to 06Z day2: window (day1 03Z, day2 03Z] = 24 hours
    ends = pd.date_range("2024-07-29T01:00", "2024-07-30T06:00", freq="h").values
    s, e = hourly_intervals(ends)
    amt = np.ones((ends.size, 1), dtype=np.float32)
    amt[ends == T("2024-07-29T03:00")] = 100.0  # hour ending 03Z is OUTSIDE the window
    amt[ends == T("2024-07-30T03:00")] = 5.0  # hour ending 03Z next day is INSIDE
    out = window_amount(amt, s, e, *imd_window(pd.Timestamp("2024-07-30")))
    assert out[0] == pytest.approx(23 + 5)


def test_six_hourly_straddling_interval_split_by_overlap():
    # AIFS-like: rate intervals (00,06], (06,12], (12,18], (18,00], (00,06] ...
    init = T("2024-07-29T00:00")
    s, e = step_intervals(init, np.arange(0, 49, 6))
    amt = np.array([6, 12, 18, 24, 30, 36, 42, 48], dtype=np.float32)[:, None]
    out = window_amount(amt, s, e, T("2024-07-29T03:00"), T("2024-07-30T03:00"))
    # (00,06]: half of 6 = 3; full 12,18,24; (00,06] next day: half of 30 = 15
    assert out[0] == pytest.approx(3 + 12 + 18 + 24 + 15)


def test_three_hourly_is_exact_at_03z():
    s, e = step_intervals(T("2024-07-29T00:00"), np.arange(0, 31, 3))
    amt = np.arange(1, 11, dtype=np.float32)[:, None]  # intervals (0,3]=1, (3,6]=2, ...
    out = window_amount(amt, s, e, T("2024-07-29T03:00"), T("2024-07-30T03:00"))
    assert out[0] == pytest.approx(sum(range(2, 10)))  # (3,6]..(24,27] = 2..9


def test_missing_piece_gives_nan_not_zero():
    ends = pd.date_range("2024-07-29T04:00", periods=24, freq="h").values
    s, e = hourly_intervals(ends)
    amt = np.ones((24, 2), dtype=np.float32)
    amt[5, 1] = np.nan
    out = window_amount(amt, s, e, T("2024-07-29T03:00"), T("2024-07-30T03:00"))
    assert out[0] == 24 and np.isnan(out[1])


def test_uncovered_window_gives_nan():
    ends = pd.date_range("2024-07-29T04:00", periods=20, freq="h").values  # ends 23Z, 4 h short
    s, e = hourly_intervals(ends)
    out = window_amount(np.ones((20, 1), np.float32), s, e, T("2024-07-29T03"), T("2024-07-30T03"))
    assert np.isnan(out[0])


def test_window_max_intervals_uses_overlapping_steps():
    s, e = step_intervals(T("2024-07-29T00:00"), np.arange(0, 31, 3))
    mx = np.array([50, 30, 31, 32, 33, 34, 35, 36, 37, 60], dtype=np.float32)[:, None]
    out = window_max_intervals(mx, s, e, T("2024-07-29T03"), T("2024-07-30T03"))
    assert out[0] == 37  # (0,3]=50 and (27,30]=60 are outside


def test_window_max_samples_excludes_start_includes_end_and_needs_min_samples():
    times = pd.date_range("2024-07-29T00:00", periods=6, freq="6h").values  # 00,06,12,18,00,06
    x = np.array([99, 30, 38, 29, 25, 99], dtype=np.float32)[:, None]
    out = window_max_samples(x, times, T("2024-07-29T00:00"), T("2024-07-30T00:00"), 4)
    assert out[0] == 38
    x2 = x.copy()
    x2[2] = np.nan
    assert np.isnan(window_max_samples(x2, times, T("2024-07-29T00"), T("2024-07-30T00"), 4)[0])
