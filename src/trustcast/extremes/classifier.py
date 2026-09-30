"""L5 extreme-event layer.

1. Tail-preserving mapping: the blended rain is quantile-mapped (rolling origin, leak-free) onto the
   observed distribution, so blending does not shrink the upper tail (see ``bias.qm.rolling_qm``).
2. Event classifiers: LightGBM P(rain >= 64.5 mm), P(rain >= 115.6 mm), P(Tmax >= 40 C), trained
   with balanced class weights, then Platt-calibrated on the most recent 20 % (by time) of each
   quarter's training rows (the classifier itself is fitted on the older 80 %).
"""

from __future__ import annotations

from dataclasses import dataclass

import lightgbm as lgb
import numpy as np
import pandas as pd
from sklearn.linear_model import LogisticRegression

from trustcast.blend.rolling import LGBM_REG, rolling_fit_predict

CLF_PARAMS = {**LGBM_REG, "class_weight": "balanced"}


@dataclass
class CalibratedClassifier:
    """LightGBM classifier + Platt scaling on its logit output."""

    model: lgb.LGBMClassifier | None
    platt: LogisticRegression | None
    constant: float | None = None  # all training labels identical

    def predict_proba(self, X: pd.DataFrame) -> np.ndarray:
        if self.constant is not None:
            return np.full(len(X), self.constant)
        raw = self.model.predict_proba(X)[:, 1]
        z = np.log(np.clip(raw, 1e-6, 1 - 1e-6) / np.clip(1 - raw, 1e-6, 1))
        return self.platt.predict_proba(z[:, None])[:, 1]


def fit_calibrated(X: pd.DataFrame, y: np.ndarray, order: np.ndarray) -> CalibratedClassifier:
    """Fit on the oldest 80 % of rows (by ``order``), Platt-calibrate on the newest 20 %."""
    y = y.astype(int)
    if y.min() == y.max() or y.sum() < 20:
        return CalibratedClassifier(None, None, constant=float(y.mean()))
    idx = np.argsort(order, kind="stable")
    cut = int(0.8 * len(idx))
    fit_i, cal_i = idx[:cut], idx[cut:]
    if y[fit_i].min() == y[fit_i].max() or y[cal_i].min() == y[cal_i].max():
        fit_i = cal_i = idx
    m = lgb.LGBMClassifier(objective="binary", **CLF_PARAMS)
    m.fit(X.iloc[fit_i], y[fit_i])
    raw = m.predict_proba(X.iloc[cal_i])[:, 1]
    z = np.log(np.clip(raw, 1e-6, 1 - 1e-6) / np.clip(1 - raw, 1e-6, 1))
    platt = LogisticRegression(C=1.0).fit(z[:, None], y[cal_i])
    return CalibratedClassifier(m, platt)


def exceedance_probabilities(
    X: pd.DataFrame,
    obs_flat: np.ndarray,
    row_init: np.ndarray,
    row_valid: np.ndarray,
    thresholds: tuple[float, ...],
    start: pd.Timestamp,
    min_train_rows: int = 20_000,
) -> dict[float, np.ndarray]:
    """Out-of-sample P(obs >= t) per case for each threshold (quarterly refits)."""
    out = {}
    order_all = pd.DatetimeIndex(row_valid).asi8
    for t in thresholds:
        y = np.where(np.isfinite(obs_flat), (obs_flat >= t).astype(float), np.nan)

        def fit(Xt, yt):
            # X has a RangeIndex, so the training rows' index gives their valid-time order
            return fit_calibrated(Xt, yt, order_all[Xt.index.to_numpy()])

        p, _ = rolling_fit_predict(
            X,
            y,
            row_init,
            row_valid,
            fit,
            lambda m, Xp: m.predict_proba(Xp),
            start,
            min_train_rows=min_train_rows,
        )
        out[t] = p
    return out
