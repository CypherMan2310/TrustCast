"""The full TRUSTCAST forecast pipeline for one region and variable.

    sources -> L1 quantile mapping -> L2 skill tracker -> L3A blender A
            -> (L4 regimes + L3B gate, if enabled) -> L5 tail mapping + event classifiers
            -> L6 quantiles + conformal intervals -> L7 defer flag

Every learned component is leak-free (rolling origin / quarterly refits / tracker uses only verified
windows). The same function serves the development experiments, the frozen test, live products
and event replays; ``PipelineConfig`` switches layers on/off for ablations.
"""

from __future__ import annotations

from dataclasses import dataclass, field, replace

import numpy as np
import pandas as pd
import xarray as xr

from trustcast.bias.qm import rolling_qm
from trustcast.blend.baselines import clim_for
from trustcast.blend.decayed import blend_a
from trustcast.blend.explain import defer_flags
from trustcast.blend.features import (
    ORDER,
    CaseGrid,
    case_grid,
    case_table,
    consensus_stats,
    stack_sources,
)
from trustcast.blend.gated import GatePredictions, apply_weights
from trustcast.blend.regime import label_regimes
from trustcast.extremes.classifier import exceedance_probabilities
from trustcast.skill.tracker import decayed_mse
from trustcast.uncertainty.cqr import QUANTILES, conformalize, quantile_predictions
from trustcast.verify.assemble import Bundle
from trustcast.verify.data import TRUTH_DAY_OFFSET
from trustcast.verify.scoreboard import THRESHOLDS, Forecast

AI_SOURCES = ("ecmwf_aifs", "ecmwf_aifs_ens")


@dataclass
class PipelineConfig:
    """Layer switches and hyperparameters (tuned values live in config/model_selection.yaml)."""

    qm: bool = True
    half_life: float = 30.0
    p: float = 2.0
    scope: str = "cell"
    gate: bool = True
    temperature: float = 0.3
    regime_features: bool = True
    extremes: bool = True
    uncertainty: bool = True
    exclude_sources: tuple[str, ...] = ()
    learn_start: pd.Timestamp = field(default_factory=lambda: pd.Timestamp("2024-10-01"))
    alpha: float = 0.1
    min_train_rows: int = 20_000

    def but(self, **kw) -> PipelineConfig:
        """Copy with some fields changed (for ablations)."""
        return replace(self, **kw)


@dataclass
class PipelineResult:
    """All intermediate and final products on the common case grid."""

    names: list[str]
    dets: dict[str, xr.DataArray]
    dmse: dict[str, xr.DataArray]
    blend_a: xr.DataArray
    weights_a: xr.DataArray
    regimes: xr.DataArray
    grid: CaseGrid
    final_det: xr.DataArray
    weights: xr.DataArray
    gate: GatePredictions | None = None
    blend_b: xr.DataArray | None = None
    probs: dict[float, xr.DataArray] = field(default_factory=dict)
    quantiles: dict[float, xr.DataArray] = field(default_factory=dict)
    lo: xr.DataArray | None = None
    hi: xr.DataArray | None = None
    defer: xr.DataArray | None = None
    pred_err: xr.DataArray | None = None

    def forecast(self, name: str = "trustcast") -> Forecast:
        """The final deterministic product as a scoreboard Forecast."""
        return Forecast(name, "blend", self.final_det)


def _grid_da(values: np.ndarray, like: xr.DataArray) -> xr.DataArray:
    like = like.transpose(*ORDER)
    coords = {k: like.coords[k] for k in (*ORDER, "valid_day") if k in like.coords}
    return xr.DataArray(
        np.asarray(values, np.float32).reshape(like.shape), dims=ORDER, coords=coords
    )


def run_pipeline(
    b: Bundle,
    cfg: PipelineConfig,
    clim: xr.Dataset | None = None,
    static: xr.Dataset | None = None,
    penalties: dict[str, xr.DataArray] | None = None,
) -> PipelineResult:
    """Run every enabled layer for bundle ``b``.

    ``penalties``: optional multiplicative DMSE factors per source from forecaster overrides
    (``skill.overrides.penalty_factors``); they change subsequent skill state and hence weights.
    """
    kind = "rain" if b.variable == "precip" else "temp"
    land = np.isfinite(b.truth).any("time")
    srcs = [f for f in b.forecasts if f.name not in cfg.exclude_sources]
    raw = {f.name: f.det.where(land) for f in srcs}
    members = {f.name: f.ens.where(land) for f in srcs if f.ens is not None}
    obs = b.obs.where(land)
    dets = {n: rolling_qm(d, obs, kind) if cfg.qm else d for n, d in raw.items()}
    dmse = {n: decayed_mse(d, obs, cfg.half_life, cfg.scope) for n, d in dets.items()}
    if penalties:
        dmse = {n: d * penalties[n] if n in penalties else d for n, d in dmse.items()}
    ba, wa = blend_a(dets, dmse, cfg.p)
    like = b.like
    off = TRUTH_DAY_OFFSET[b.variable]
    clim_mean = clim_for(clim, "mean", like, off) if clim is not None else None
    consensus = (
        xr.concat(list(raw.values()), dim="s")
        .mean("s", skipna=True)
        .assign_coords(valid_day=like.valid_day)
    )
    regimes = label_regimes(consensus, b.variable, clim_mean)
    grid = case_grid(like, regimes, static)
    names, x = stack_sources(dets)
    avail = np.isfinite(x)
    w_a = wa.transpose("source", *ORDER).values.reshape(len(names), -1)
    res = PipelineResult(names, dets, dmse, ba, wa, regimes, grid, ba, wa)
    w_final = w_a
    if cfg.gate:
        mstd = {n: m.std("member") for n, m in members.items() if n in dets}
        gp = GatePredictions(
            grid, dets, dmse, obs, cfg.learn_start, mstd, cfg.regime_features, cfg.min_train_rows
        )
        w_final = gp.weights(cfg.temperature, w_a, avail)
        res.gate = gp
        res.blend_b = apply_weights(x, w_final, like)
        res.final_det = res.blend_b
        pred_err = np.nansum(np.where(avail, gp.pred, 0.0) * w_final, axis=0)
        pred_err[~np.isfinite(gp.pred).any(axis=0)] = np.nan
    else:
        d = np.stack([dmse[n].transpose(*ORDER).values.ravel() for n in names])
        pred_err = np.nansum(np.where(avail, np.sqrt(d), 0.0) * w_final, axis=0)
        pred_err[~np.isfinite(d).any(axis=0)] = np.nan
    res.weights = xr.DataArray(
        w_final.reshape((len(names), *like.transpose(*ORDER).shape)).astype(np.float32),
        dims=("source", *ORDER),
        coords={"source": names, **{k: like.coords[k] for k in ORDER}},
    )
    res.pred_err = _grid_da(pred_err, like)
    spread = consensus_stats(x)["spread"]
    init_flat = np.broadcast_to(
        like.transpose(*ORDER).init_time.values[:, None, None, None], grid.shape
    ).ravel()
    res.defer = _grid_da(defer_flags(pred_err, spread, init_flat), like).astype(bool)
    if cfg.extremes:
        res.final_det = rolling_qm(res.final_det, obs, kind).where(land)
        feats = case_table(grid, dets, res.final_det, members, THRESHOLDS[b.variable])
        probs = exceedance_probabilities(
            feats,
            obs.transpose(*ORDER).values.ravel(),
            init_flat,
            grid.valid_day,
            THRESHOLDS[b.variable],
            cfg.learn_start,
            cfg.min_train_rows,
        )
        res.probs = {t: _grid_da(p, like).where(land) for t, p in probs.items()}
    if cfg.uncertainty:
        feats = case_table(grid, dets, res.final_det, members, THRESHOLDS[b.variable])
        y = obs.transpose(*ORDER).values.ravel()
        q = quantile_predictions(
            feats, y, init_flat, grid.valid_day, cfg.learn_start, cfg.min_train_rows
        )
        lead_flat = feats["lead_day"].to_numpy()
        lo, hi = conformalize(
            q[QUANTILES[0]],
            q[QUANTILES[-1]],
            y,
            init_flat,
            grid.valid_day,
            lead_flat,
            alpha=cfg.alpha,
        )
        if kind == "rain":
            lo = np.maximum(lo, 0.0)
        res.quantiles = {k: _grid_da(v, like).where(land) for k, v in q.items()}
        res.lo, res.hi = _grid_da(lo, like).where(land), _grid_da(hi, like).where(land)
    return res
