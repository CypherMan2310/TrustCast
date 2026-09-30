"""L6 uncertainty: LightGBM quantile models + split-conformal (CQR) calibration on a rolling window.

Quantile models (q05, q50, q95) are refitted quarterly (leak-free). For an init t, the conformal
correction for lead l is the (1 - alpha)(1 + 1/n) empirical quantile of the conformity scores
    E_i = max(q_lo_i - y_i, y_i - q_hi_i)
over already-verified cases of lead l with valid day in [t - window, t - 1 day]
(Romano et al. 2019).
The calibrated interval is [q_lo - Q, q_hi + Q] (rain lower bound clipped at 0).
"""

from __future__ import annotations

import lightgbm as lgb
import numpy as np
import pandas as pd

from trustcast.blend.rolling import LGBM_REG, rolling_fit_predict

QUANTILES = (0.05, 0.5, 0.95)


def quantile_predictions(
    X: pd.DataFrame,
    y: np.ndarray,
    row_init: np.ndarray,
    row_valid: np.ndarray,
    start: pd.Timestamp,
    min_train_rows: int = 20_000,
) -> dict[float, np.ndarray]:
    """Out-of-sample quantile predictions per case for QUANTILES."""
    out = {}
    for q in QUANTILES:

        def fit(Xt, yt, _q=q):
            m = lgb.LGBMRegressor(objective="quantile", alpha=_q, **LGBM_REG)
            return m.fit(Xt, yt)

        out[q], _ = rolling_fit_predict(
            X, y, row_init, row_valid, fit, lambda m, Xp: m.predict(Xp), start, min_train_rows
        )
    # enforce monotone quantiles
    lo, mid, hi = out[QUANTILES[0]], out[QUANTILES[1]], out[QUANTILES[2]]
    stacked = np.sort(np.vstack([lo, mid, hi]), axis=0)
    return dict(zip(QUANTILES, stacked, strict=True))


def conformalize(
    q_lo: np.ndarray,
    q_hi: np.ndarray,
    y: np.ndarray,
    row_init: np.ndarray,
    row_valid: np.ndarray,
    row_lead: np.ndarray,
    alpha: float = 0.1,
    window_days: int = 60,
    min_scores: int = 200,
) -> tuple[np.ndarray, np.ndarray]:
    """Rolling split-conformal adjustment; returns calibrated (lo, hi). NaN where uncalibrated."""
    inits = pd.DatetimeIndex(row_init).normalize()
    valid = pd.DatetimeIndex(row_valid).normalize()
    score = np.maximum(q_lo - y, y - q_hi)
    lo_out = np.full(q_lo.shape, np.nan)
    hi_out = np.full(q_hi.shape, np.nan)
    for lead in np.unique(row_lead):
        m = row_lead == lead
        ok = m & np.isfinite(score)
        vdays = valid[ok].to_numpy()
        sc = score[ok]
        order = np.argsort(vdays)
        vdays, sc = vdays[order], sc[order]
        for t in inits[m].unique():
            lo_d = np.datetime64(t - pd.Timedelta(days=window_days))
            hi_d = np.datetime64(t - pd.Timedelta(days=1))
            a, b = np.searchsorted(vdays, lo_d, "left"), np.searchsorted(vdays, hi_d, "right")
            s = sc[a:b]
            if s.size < min_scores:
                continue
            level = min(1.0, (1 - alpha) * (1 + 1 / s.size))
            qhat = np.quantile(s, level)
            rows = m & (inits == t)
            lo_out[rows] = q_lo[rows] - qhat
            hi_out[rows] = q_hi[rows] + qhat
    return lo_out, hi_out


def coverage(lo: np.ndarray, hi: np.ndarray, y: np.ndarray) -> tuple[float, int]:
    """Empirical coverage and number of evaluated cases."""
    ok = np.isfinite(lo) & np.isfinite(hi) & np.isfinite(y)
    if not ok.any():
        return float("nan"), 0
    return float(((y[ok] >= lo[ok]) & (y[ok] <= hi[ok])).mean()), int(ok.sum())
