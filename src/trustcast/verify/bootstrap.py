"""Paired block bootstrap for score differences.

Cases (cell x day) are grouped into blocks of ``block_days`` consecutive valid days (all cells of
those days together), which preserves spatial correlation and short-range temporal correlation.
Each block carries additive sufficient statistics for forecast A and forecast B, computed on the
*same* cases (paired). A bootstrap replicate draws blocks with replacement and sums their
statistics; the score difference is recomputed from the sums.

Returned interval: percentile 95 % CI. p-value: two-sided, 2 * min(P(diff <= 0), P(diff >= 0)).
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

import numpy as np
import pandas as pd

Stats = dict[str, np.ndarray]  # name -> per-block values (n_blocks,)


@dataclass
class BootResult:
    """Point estimate and interval of score(A) - score(B), plus the individual scores."""

    score_a: float
    score_b: float
    diff: float
    ci_low: float
    ci_high: float
    p_value: float
    n_blocks: int

    @property
    def significant(self) -> bool:
        """True if the 95 % interval excludes zero."""
        return bool(np.isfinite(self.ci_low) and (self.ci_low > 0 or self.ci_high < 0))


def block_ids(days: np.ndarray, block_days: int = 5) -> np.ndarray:
    """Block index per case from its valid day: consecutive ``block_days``-day windows."""
    d = pd.DatetimeIndex(np.asarray(days, dtype="datetime64[ns]")).normalize()
    return ((d - pd.Timestamp("2000-01-01")).days // block_days).to_numpy()


def aggregate_blocks(ids: np.ndarray, per_case: dict[str, np.ndarray]) -> tuple[np.ndarray, Stats]:
    """Sum per-case statistics into per-block statistics. Returns (unique block ids, stats)."""
    uniq, inv = np.unique(ids, return_inverse=True)
    return uniq, {k: np.bincount(inv, weights=v, minlength=uniq.size) for k, v in per_case.items()}


def _resample_counts(n_blocks: int, n_boot: int, seed: int) -> np.ndarray:
    """(n_boot, n_blocks) multinomial counts: how often each block is drawn per replicate."""
    rng = np.random.default_rng(seed)
    return rng.multinomial(n_blocks, np.full(n_blocks, 1.0 / n_blocks), size=n_boot)


def _replicate_scores(stats: Stats, counts: np.ndarray, score: Callable) -> np.ndarray:
    """Score of every replicate at once (``score`` must accept arrays of summed statistics)."""
    summed = {k: counts @ v for k, v in stats.items()}
    return np.asarray(score(summed), dtype=float)


def paired_block_bootstrap(
    stats_a: Stats,
    stats_b: Stats,
    score: Callable[[dict[str, float]], float],
    n_boot: int = 1000,
    seed: int = 0,
) -> BootResult:
    """Bootstrap score(A) - score(B) from per-block sufficient statistics (same blocks for both)."""
    n = len(next(iter(stats_a.values())))
    nan = float("nan")
    if n == 0:
        return BootResult(nan, nan, nan, nan, nan, nan, 0)
    full_a = score({k: float(v.sum()) for k, v in stats_a.items()})
    full_b = score({k: float(v.sum()) for k, v in stats_b.items()})
    counts = _resample_counts(n, n_boot, seed)
    diffs = _replicate_scores(stats_a, counts, score) - _replicate_scores(stats_b, counts, score)
    diffs = diffs[np.isfinite(diffs)]
    if diffs.size == 0:
        return BootResult(full_a, full_b, full_a - full_b, nan, nan, nan, n)
    lo, hi = np.percentile(diffs, [2.5, 97.5])
    p = 2 * min((diffs <= 0).mean(), (diffs >= 0).mean())
    return BootResult(full_a, full_b, full_a - full_b, float(lo), float(hi), float(min(p, 1.0)), n)


def bootstrap_ci(
    stats: Stats, score: Callable[[dict[str, float]], float], n_boot: int = 1000, seed: int = 0
) -> tuple[float, float, float]:
    """(estimate, 95 % low, 95 % high) of one score by block bootstrap."""
    n = len(next(iter(stats.values())))
    est = score({k: float(v.sum()) for k, v in stats.items()})
    if n == 0:
        return est, float("nan"), float("nan")
    vals = _replicate_scores(stats, _resample_counts(n, n_boot, seed), score)
    vals = vals[np.isfinite(vals)]
    if vals.size == 0:
        return est, float("nan"), float("nan")
    lo, hi = np.percentile(vals, [2.5, 97.5])
    return est, float(lo), float(hi)
