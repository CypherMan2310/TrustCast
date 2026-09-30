"""Expanding-window, quarterly-refitted training shared by all learned layers.

For target rows whose init falls in quarter Q = [q0, q1), the model is trained only on rows whose
IMD window ended before q0 (valid_day < q0 as dates, since windows end at 03 UTC and inits are
00Z). This is the same leak-free rule as the skill tracker.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

import numpy as np
import pandas as pd

LGBM_REG = dict(
    n_estimators=300,
    learning_rate=0.05,
    num_leaves=15,
    min_child_samples=200,
    reg_lambda=10.0,
    subsample=0.8,
    subsample_freq=1,
    colsample_bytree=0.8,
    random_state=0,
    verbose=-1,
    deterministic=True,
    force_row_wise=True,
    n_jobs=4,
)
MAX_TRAIN_ROWS = 600_000


def quarter_starts(inits: pd.DatetimeIndex, start: pd.Timestamp) -> list[pd.Timestamp]:
    """Quarter starts from ``start`` covering all ``inits``."""
    q = pd.Timestamp(start).to_period("Q").start_time
    out = []
    while q <= inits.max():
        out.append(q)
        q = q + pd.offsets.QuarterBegin(startingMonth=1)
    return out


def rolling_fit_predict(
    X: pd.DataFrame,
    y: np.ndarray,
    row_init: np.ndarray,
    row_valid: np.ndarray,
    fit: Callable[[pd.DataFrame, np.ndarray], Any],
    predict: Callable[[Any, pd.DataFrame], np.ndarray],
    start: pd.Timestamp,
    min_train_rows: int = 20_000,
    seed: int = 0,
    n_out: int = 1,
) -> tuple[np.ndarray, dict[pd.Timestamp, Any]]:
    """Predictions for every row with init >= ``start`` (NaN where no model could be trained)."""
    inits = pd.DatetimeIndex(row_init)
    valid = pd.DatetimeIndex(row_valid)
    shape = (len(X),) if n_out == 1 else (len(X), n_out)
    pred = np.full(shape, np.nan, dtype=np.float64)
    models: dict[pd.Timestamp, Any] = {}
    rng = np.random.default_rng(seed)
    qs = quarter_starts(inits, start)
    for k, q0 in enumerate(qs):
        q1 = qs[k + 1] if k + 1 < len(qs) else pd.Timestamp.max
        tgt = np.flatnonzero((inits >= q0) & (inits < q1))
        if tgt.size == 0:
            continue
        tr = np.flatnonzero((valid < q0) & np.isfinite(y))
        if tr.size < min_train_rows:
            continue
        if tr.size > MAX_TRAIN_ROWS:
            tr = np.sort(rng.choice(tr, MAX_TRAIN_ROWS, replace=False))
        model = fit(X.iloc[tr], y[tr])
        models[q0] = model
        pred[tgt] = predict(model, X.iloc[tgt])
    return pred, models
