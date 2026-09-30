"""Verification metrics.

All scores are computed from *sufficient statistics* (sums and counts) so that the paired block
bootstrap can resample blocks by summing their statistics instead of recomputing from raw cases.

Definitions
-----------
RMSE, MAE, bias (forecast - observation).
CRPS for an ensemble uses the *fair* estimator (Ferro 2014), which is unbiased for the ensemble size
and so comparable between 31- and 51-member ensembles:
    CRPS_fair = mean_i |x_i - y| - 1 / (2 m (m - 1)) * sum_{i,j} |x_i - x_j|
For a deterministic forecast CRPS = |x - y| (= MAE).
Brier score BS = mean (p - o)^2 for event probability p and outcome o in {0, 1};
BSS = 1 - BS / BS_ref.
Contingency (hits a, false alarms b, misses c, correct negatives d):
    POD = a/(a+c), FAR = b/(a+b), CSI = a/(a+b+c), frequency bias = (a+b)/(a+c),
    ETS = (a - a_r)/(a+b+c - a_r), a_r = (a+b)(a+c)/n.
"""

from __future__ import annotations

import numpy as np

# IMD rainfall categories (mm/day): heavy >= 64.5, very heavy >= 115.6
RAIN_THRESHOLDS = (64.5, 115.6)
HEAT_THRESHOLD_C = 40.0


def crps_fair(members: np.ndarray, obs: np.ndarray) -> np.ndarray:
    """Fair CRPS per case. ``members`` shape (n, m) with m >= 2; ``obs`` shape (n,)."""
    x = np.sort(np.asarray(members, dtype=np.float64), axis=1)
    y = np.asarray(obs, dtype=np.float64)
    m = x.shape[1]
    if m < 2:
        return np.abs(x[:, 0] - y)
    term1 = np.abs(x - y[:, None]).mean(axis=1)
    # sum_{i,j} |x_i - x_j| = 2 * sum_i (2i - m - 1) x_(i) for sorted x (i = 1..m)
    w = 2 * np.arange(1, m + 1) - m - 1
    pair_sum = 2.0 * (x * w).sum(axis=1)
    return term1 - pair_sum / (2.0 * m * (m - 1))


def continuous_stats(
    fc: np.ndarray, obs: np.ndarray, crps: np.ndarray | None = None
) -> dict[str, float]:
    """Sufficient statistics for RMSE/MAE/bias/CRPS over finite pairs."""
    ok = np.isfinite(fc) & np.isfinite(obs)
    if crps is not None:
        ok &= np.isfinite(crps)
    e = fc[ok] - obs[ok]
    return {
        "n": float(ok.sum()),
        "sum_err": float(e.sum()),
        "sum_abs": float(np.abs(e).sum()),
        "sum_sq": float((e * e).sum()),
        "sum_crps": float((crps[ok] if crps is not None else np.abs(e)).sum()),
    }


def contingency_stats(
    fc_event: np.ndarray, obs_event: np.ndarray, valid: np.ndarray
) -> dict[str, float]:
    """Counts a (hits), b (false alarms), c (misses), d (correct negatives)."""
    f, o = fc_event[valid].astype(bool), obs_event[valid].astype(bool)
    return {
        "a": float((f & o).sum()),
        "b": float((f & ~o).sum()),
        "c": float((~f & o).sum()),
        "d": float((~f & ~o).sum()),
    }


def brier_stats(
    prob: np.ndarray, obs_event: np.ndarray, ref_prob: np.ndarray, valid: np.ndarray
) -> dict[str, float]:
    """Sufficient statistics for the Brier score and skill score against ``ref_prob``."""
    p, o, r = prob[valid], obs_event[valid].astype(float), ref_prob[valid]
    return {
        "nb": float(valid.sum()),
        "sum_bs": float(((p - o) ** 2).sum()),
        "sum_bs_ref": float(((r - o) ** 2).sum()),
    }


def _div(a, b):
    """a / b, NaN where b <= 0. Works on scalars (returns float) and arrays."""
    a = np.asarray(a, dtype=float)
    b = np.asarray(b, dtype=float)
    with np.errstate(invalid="ignore", divide="ignore"):
        out = np.where(b > 0, a / np.where(b > 0, b, 1.0), np.nan)
    return float(out) if out.ndim == 0 else out


def scores_from_stats(s: dict) -> dict:
    """Turn (summed) sufficient statistics into scores. Missing inputs give NaN.

    Values may be scalars or equal-length arrays (bootstrap replicates); the result follows suit.
    """
    out: dict = {}
    if "n" in s:
        n = s["n"]
        out.update(
            n=n,
            bias=_div(s["sum_err"], n),
            mae=_div(s["sum_abs"], n),
            rmse=np.sqrt(_div(s["sum_sq"], n)),
            crps=_div(s["sum_crps"], n),
        )
    if "a" in s:
        a, b, c, d = s["a"], s["b"], s["c"], s["d"]
        n = a + b + c + d
        ar = _div((a + b) * (a + c), n)
        out.update(
            n_obs_events=a + c,
            pod=_div(a, a + c),
            far=_div(b, a + b),
            csi=_div(a, a + b + c),
            freq_bias=_div(a + b, a + c),
            ets=_div(a - ar, a + b + c - ar),
        )
    if "nb" in s:
        bs = _div(s["sum_bs"], s["nb"])
        out.update(brier=bs, bss=1 - _div(s["sum_bs"], s["sum_bs_ref"]))
    return out


def reliability_table(
    prob: np.ndarray, obs_event: np.ndarray, bins: int = 10
) -> list[dict[str, float]]:
    """Reliability diagram data: per probability bin, mean forecast prob, observed freq, count."""
    ok = np.isfinite(prob)
    p, o = prob[ok], obs_event[ok].astype(float)
    edges = np.linspace(0, 1, bins + 1)
    idx = np.clip(np.digitize(p, edges[1:-1]), 0, bins - 1)
    rows = []
    for k in range(bins):
        m = idx == k
        rows.append(
            {
                "bin_lo": float(edges[k]),
                "bin_hi": float(edges[k + 1]),
                "n": float(m.sum()),
                "mean_prob": float(p[m].mean()) if m.any() else float("nan"),
                "obs_freq": float(o[m].mean()) if m.any() else float("nan"),
            }
        )
    return rows
