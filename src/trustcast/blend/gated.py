"""L3B gated blender B: LightGBM predicts each source's expected absolute error; weights are a
softmax over sources of the negative predicted errors with a tuned temperature.

    w_s = exp(-(e_s - min_s e) / (T * mean_s e)) / sum(...)

(errors scaled by their per-case mean so that T is comparable between dry and very wet cases).
Cases where the gate has no trained model yet fall back to blender A's weights. Missing sources
are dropped and weights renormalised.
"""

from __future__ import annotations

import warnings

import lightgbm as lgb
import numpy as np
import pandas as pd
import xarray as xr

from trustcast.blend.features import ORDER, CaseGrid, gate_table
from trustcast.blend.rolling import LGBM_REG, rolling_fit_predict


def fit_gate(X: pd.DataFrame, y: np.ndarray) -> lgb.LGBMRegressor:
    """Small, regularised LightGBM regressor of absolute error."""
    m = lgb.LGBMRegressor(objective="regression", **LGBM_REG)
    m.fit(X, y)
    return m


def predict_gate(model: lgb.LGBMRegressor, X: pd.DataFrame) -> np.ndarray:
    """Predicted absolute error (clipped to >= 0)."""
    return np.maximum(model.predict(X), 0.0)


def softmax_weights(pred_err: np.ndarray, temperature: float) -> np.ndarray:
    """Weights (S, n) from predicted errors (S, n); NaN (missing source) -> weight 0."""
    have = np.isfinite(pred_err)
    with np.errstate(all="ignore"), warnings.catch_warnings():
        warnings.simplefilter("ignore", RuntimeWarning)
        e_min = np.nanmin(np.where(have, pred_err, np.nan), axis=0)
        e_mean = np.nanmean(np.where(have, pred_err, np.nan), axis=0)
        z = -(pred_err - e_min) / (temperature * np.maximum(e_mean, 1e-3))
        w = np.where(have, np.exp(np.where(have, z, -np.inf)), 0.0)
        tot = w.sum(axis=0)
        return np.where(tot > 0, w / tot, 0.0)


class GatePredictions:
    """Out-of-sample predicted errors per (source, case) from quarterly refits."""

    def __init__(
        self,
        grid: CaseGrid,
        dets: dict[str, xr.DataArray],
        dmse: dict[str, xr.DataArray],
        obs: xr.DataArray,
        start: pd.Timestamp,
        member_std: dict[str, xr.DataArray] | None = None,
        use_regime: bool = True,
        min_train_rows: int = 20_000,
    ) -> None:
        self.names = list(dets)
        X, cidx, sidx = gate_table(grid, dets, dmse, member_std, use_regime)
        o = obs.transpose(*ORDER).values.ravel()
        y = np.abs(X["fc"].to_numpy() - o[cidx])
        inits = np.broadcast_to(
            dets[self.names[0]].transpose(*ORDER).init_time.values[:, None, None, None], grid.shape
        ).ravel()
        pred, self.models = rolling_fit_predict(
            X, y, inits[cidx], grid.valid_day[cidx], fit_gate, predict_gate, start, min_train_rows
        )
        self.pred = np.full((len(self.names), grid.n), np.nan, dtype=np.float64)
        self.pred[sidx, cidx] = pred
        self.X, self.cidx, self.sidx = X, cidx, sidx
        self.grid = grid

    def weights(
        self, temperature: float, fallback: np.ndarray, available: np.ndarray
    ) -> np.ndarray:
        """Gate weights (S, n); cases without gate predictions use ``fallback`` weights."""
        w = softmax_weights(np.where(available, self.pred, np.nan), temperature)
        no_gate = ~np.isfinite(np.where(available, self.pred, np.nan)).any(axis=0)
        w[:, no_gate] = fallback[:, no_gate]
        return w


def apply_weights(x: np.ndarray, w: np.ndarray, like: xr.DataArray) -> xr.DataArray:
    """Weighted sum of sources (x, w: (S, n)) back on the case grid of ``like``."""
    blended = np.where(np.isfinite(x).any(axis=0), (np.nan_to_num(x) * w).sum(axis=0), np.nan)
    like = like.transpose(*ORDER)
    coords = {k: like.coords[k] for k in (*ORDER, "valid_day") if k in like.coords}
    return xr.DataArray(blended.reshape(like.shape).astype(np.float32), dims=ORDER, coords=coords)
