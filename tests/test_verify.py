"""Metrics and the paired block bootstrap on SYNTHETIC data (hand-checked values)."""

import numpy as np
import pandas as pd
import pytest

from trustcast.verify.bootstrap import (
    aggregate_blocks,
    block_ids,
    bootstrap_ci,
    paired_block_bootstrap,
)
from trustcast.verify.metrics import (
    brier_stats,
    contingency_stats,
    continuous_stats,
    crps_fair,
    reliability_table,
    scores_from_stats,
)


def test_continuous_scores_hand_case():
    fc = np.array([1.0, 2.0, 3.0, np.nan])
    ob = np.array([0.0, 2.0, 5.0, 1.0])
    s = scores_from_stats(continuous_stats(fc, ob))
    assert s["n"] == 3
    assert s["bias"] == pytest.approx((1 + 0 - 2) / 3)
    assert s["mae"] == pytest.approx(1.0)
    assert s["rmse"] == pytest.approx(np.sqrt(5 / 3))
    assert s["crps"] == pytest.approx(1.0)  # deterministic CRPS = MAE


def test_crps_fair_hand_case_and_limits():
    # members {0, 2}, obs 1: mean|x-y| = 1; pair term = |0-2|*2 / (2*2*1) = 1  -> CRPS = 0
    assert crps_fair(np.array([[0.0, 2.0]]), np.array([1.0]))[0] == pytest.approx(0.0)
    # identical members reduce to absolute error
    assert crps_fair(np.array([[3.0, 3.0, 3.0]]), np.array([1.0]))[0] == pytest.approx(2.0)
    # brute force check on random members (SYNTHETIC)
    rng = np.random.default_rng(0)
    x, y = rng.gamma(1, 5, (50, 7)), rng.gamma(1, 5, 50)
    brute = np.abs(x - y[:, None]).mean(1) - np.abs(x[:, :, None] - x[:, None, :]).sum((1, 2)) / (
        2 * 7 * 6
    )
    assert np.allclose(crps_fair(x, y), brute)


def test_contingency_scores_hand_case():
    # a=2, b=1, c=1, d=6 -> n=10, ar=(3*3)/10=0.9
    f = np.array([1, 1, 1, 0, 0, 0, 0, 0, 0, 0], bool)
    o = np.array([1, 1, 0, 1, 0, 0, 0, 0, 0, 0], bool)
    s = scores_from_stats(contingency_stats(f, o, np.ones(10, bool)))
    assert (s["pod"], s["far"], s["csi"], s["freq_bias"]) == pytest.approx((2 / 3, 1 / 3, 0.5, 1.0))
    assert s["ets"] == pytest.approx((2 - 0.9) / (4 - 0.9))


def test_no_events_gives_nan_not_error():
    s = scores_from_stats(contingency_stats(np.zeros(5, bool), np.zeros(5, bool), np.ones(5, bool)))
    assert np.isnan(s["pod"]) and np.isnan(s["ets"])


def test_brier_and_bss():
    p = np.array([1.0, 0.0, 0.5, 0.5])
    o = np.array([1, 0, 1, 0])
    ref = np.full(4, 0.5)
    s = scores_from_stats(brier_stats(p, o, ref, np.ones(4, bool)))
    assert s["brier"] == pytest.approx(0.125)
    assert s["bss"] == pytest.approx(1 - 0.125 / 0.25)


def test_reliability_perfectly_calibrated():
    rng = np.random.default_rng(3)  # SYNTHETIC
    p = rng.uniform(0, 1, 200_000)
    o = rng.uniform(0, 1, p.size) < p
    for row in reliability_table(p, o, bins=5):
        assert row["obs_freq"] == pytest.approx(row["mean_prob"], abs=0.01)


def test_block_ids_group_five_consecutive_days():
    days = pd.date_range("2025-01-01", periods=12).values
    ids = block_ids(days, 5)
    assert len(set(ids)) in (3, 4)
    assert all(np.diff(ids) >= 0)
    assert pd.Series(ids).value_counts().max() == 5


def _paired_stats(delta, n_days=400, cells=20, seed=0, rho=0.0):
    """SYNTHETIC errors: B has |error| larger by ``delta`` on average."""
    rng = np.random.default_rng(seed)
    days = pd.date_range("2024-01-01", periods=n_days).values
    day_noise = rng.normal(0, 1, n_days)
    ob = np.repeat(day_noise, cells) * rho + rng.normal(0, 1, n_days * cells)
    fa = ob + rng.normal(0, 1.0, ob.size)
    fb = ob + rng.normal(0, 1.0 + delta, ob.size)
    ids = block_ids(np.repeat(days, cells))

    def per_case(fc):
        e = fc - ob
        return {
            "n": np.ones_like(e),
            "sum_err": e,
            "sum_abs": np.abs(e),
            "sum_sq": e * e,
            "sum_crps": np.abs(e),
        }

    _, sa = aggregate_blocks(ids, per_case(fa))
    _, sb = aggregate_blocks(ids, per_case(fb))
    return sa, sb


def rmse(s):
    return scores_from_stats(s)["rmse"]


def test_bootstrap_detects_real_difference():
    sa, sb = _paired_stats(delta=0.3)
    r = paired_block_bootstrap(sa, sb, rmse, n_boot=500, seed=1)
    assert r.diff < 0 and r.ci_high < 0 and r.significant and r.p_value < 0.01


def test_bootstrap_identical_forecasts_give_zero():
    sa, _ = _paired_stats(delta=0.0)
    r = paired_block_bootstrap(sa, sa, rmse, n_boot=200, seed=1)
    assert r.diff == 0 and r.ci_low == 0 and r.ci_high == 0 and not r.significant


def test_bootstrap_null_is_rarely_significant():
    """Under H0 (equal skill) a 95 % interval should exclude 0 in roughly 5 % of trials."""
    sig = [
        paired_block_bootstrap(
            *_paired_stats(0.0, n_days=150, cells=5, seed=s), rmse, n_boot=300, seed=s
        ).significant
        for s in range(60)
    ]
    assert np.mean(sig) <= 0.15


def test_bootstrap_is_deterministic_with_seed():
    sa, sb = _paired_stats(delta=0.1)
    r1 = paired_block_bootstrap(sa, sb, rmse, n_boot=200, seed=7)
    r2 = paired_block_bootstrap(sa, sb, rmse, n_boot=200, seed=7)
    assert (r1.ci_low, r1.ci_high) == (r2.ci_low, r2.ci_high)


def test_bootstrap_ci_contains_estimate_and_ratio_scores_work():
    rng = np.random.default_rng(5)
    f = rng.uniform(size=5000) < 0.1
    o = (rng.uniform(size=5000) < 0.1) | f & (rng.uniform(size=5000) < 0.5)
    ids = block_ids(np.repeat(pd.date_range("2024-01-01", periods=500).values, 10))
    per = {
        "a": (f & o).astype(float),
        "b": (f & ~o).astype(float),
        "c": (~f & o).astype(float),
        "d": (~f & ~o).astype(float),
    }
    _, st = aggregate_blocks(ids, per)
    est, lo, hi = bootstrap_ci(st, lambda s: scores_from_stats(s)["ets"], n_boot=300)
    assert lo <= est <= hi and hi - lo < 0.2
