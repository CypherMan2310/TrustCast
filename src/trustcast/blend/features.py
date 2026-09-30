"""Feature tables for the gate (per case x source) and the case-level models (extremes, quantiles).

A *case* is one (init_time, lead_h, lat, lon) point of the common grid. All features are known at
issue time: forecasts, consensus statistics, the leak-free skill tracker, calendar, static terrain,
and the consensus-based regime.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd
import xarray as xr

ORDER = ("init_time", "lead_h", "lat", "lon")


@dataclass
class CaseGrid:
    """Flat indexing of the case grid, with per-case calendar/static/regime columns."""

    shape: tuple[int, int, int, int]
    valid_day: np.ndarray  # (n_cases,) datetime64
    base: pd.DataFrame  # per-case features shared by all sources

    @property
    def n(self) -> int:
        return int(np.prod(self.shape))


def case_grid(
    like: xr.DataArray, regimes: xr.DataArray | None, static: xr.Dataset | None
) -> CaseGrid:
    """Calendar, static and regime features per case."""
    like = like.transpose(*ORDER)
    shape = tuple(like.shape)
    nl = shape[1]
    vd = np.broadcast_to(like["valid_day"].values[:, :, None, None], shape).ravel()
    doy = pd.DatetimeIndex(vd).dayofyear.to_numpy()
    lead_day = np.broadcast_to(np.arange(1, nl + 1)[None, :, None, None], shape).ravel()
    lat = np.broadcast_to(like.lat.values[None, None, :, None], shape).ravel()
    lon = np.broadcast_to(like.lon.values[None, None, None, :], shape).ravel()
    base = pd.DataFrame(
        {
            "lead_day": lead_day.astype(np.int8),
            "doy_sin": np.sin(2 * np.pi * doy / 365.25).astype(np.float32),
            "doy_cos": np.cos(2 * np.pi * doy / 365.25).astype(np.float32),
            "lat": lat.astype(np.float32),
            "lon": lon.astype(np.float32),
        }
    )
    if static is not None:
        for v in static.data_vars:
            base[v] = (
                np.broadcast_to(static[v].values[None, None], shape).ravel().astype(np.float32)
            )
    if regimes is not None:
        r = np.broadcast_to(
            regimes.transpose("init_time", "lead_h").values[:, :, None, None], shape
        )
        base["regime"] = pd.Categorical(r.ravel())
    return CaseGrid(shape, vd, base)


def stack_sources(dets: dict[str, xr.DataArray]) -> tuple[list[str], np.ndarray]:
    """(names, array (S, n_cases)) of source forecasts on the flat case grid."""
    names = list(dets)
    return names, np.stack([dets[n].transpose(*ORDER).values.ravel() for n in names]).astype(
        np.float32
    )


def consensus_stats(x: np.ndarray) -> dict[str, np.ndarray]:
    """Consensus statistics over available sources per case (x: (S, n))."""
    with np.errstate(all="ignore"):
        import warnings

        with warnings.catch_warnings():
            warnings.simplefilter("ignore", RuntimeWarning)
            return {
                "consensus": np.nanmean(x, axis=0),
                "spread": np.nanstd(x, axis=0),
                "src_max": np.nanmax(x, axis=0),
                "src_min": np.nanmin(x, axis=0),
                "n_src": np.isfinite(x).sum(axis=0).astype(np.float32),
            }


def gate_table(
    grid: CaseGrid,
    dets: dict[str, xr.DataArray],
    dmse: dict[str, xr.DataArray],
    member_std: dict[str, xr.DataArray] | None = None,
    use_regime: bool = True,
) -> tuple[pd.DataFrame, np.ndarray, np.ndarray]:
    """Long table (case x source) of gate features; returns (X, case_index, source_index)."""
    names, x = stack_sources(dets)
    cs = consensus_stats(x)
    d = np.stack([dmse[n].transpose(*ORDER).values.ravel() for n in names]).astype(np.float32)
    with np.errstate(all="ignore"):
        import warnings

        with warnings.catch_warnings():
            warnings.simplefilter("ignore", RuntimeWarning)
            med = np.nanmedian(d, axis=0)
    frames, cidx, sidx = [], [], []
    base = grid.base if use_regime else grid.base.drop(columns=["regime"], errors="ignore")
    for s, name in enumerate(names):
        have = np.flatnonzero(np.isfinite(x[s]))
        f = base.iloc[have].reset_index(drop=True).copy()
        f["source"] = s
        f["fc"] = x[s, have]
        for k, v in cs.items():
            f[k] = v[have].astype(np.float32)
        f["dev"] = f["fc"] - f["consensus"]
        f["abs_dev"] = np.abs(f["dev"])
        f["dmse"] = d[s, have]
        f["rel_dmse"] = d[s, have] / med[have]
        ms = member_std.get(name) if member_std else None
        f["member_std"] = (
            ms.transpose(*ORDER).values.ravel()[have].astype(np.float32)
            if ms is not None
            else np.float32(np.nan)
        )
        frames.append(f)
        cidx.append(have)
        sidx.append(np.full(have.size, s))
    X = pd.concat(frames, ignore_index=True)
    X["source"] = pd.Categorical(X["source"], categories=range(len(names)))
    return X, np.concatenate(cidx), np.concatenate(sidx)


def case_table(
    grid: CaseGrid,
    dets: dict[str, xr.DataArray],
    blended: xr.DataArray,
    members: dict[str, xr.DataArray] | None,
    thresholds: tuple[float, ...],
) -> pd.DataFrame:
    """Case-level features for the extreme classifiers and quantile models."""
    _, x = stack_sources(dets)
    cs = consensus_stats(x)
    f = grid.base.copy()
    f["blend"] = blended.transpose(*ORDER).values.ravel().astype(np.float32)
    for k, v in cs.items():
        f[k] = v.astype(np.float32)
    ok_src = np.isfinite(x)
    n_ok = ok_src.sum(axis=0)
    for t in thresholds:
        hits = np.where(ok_src, x >= t, False).sum(axis=0)
        f[f"frac_src_ge_{t}"] = np.where(n_ok > 0, hits / np.maximum(n_ok, 1), np.nan).astype(
            np.float32
        )
    if members:
        allm = [
            m.transpose("init_time", "lead_h", "lat", "lon", "member").values.reshape(grid.n, -1)
            for m in members.values()
        ]
        mm = np.concatenate(allm, axis=1)
        with np.errstate(all="ignore"):
            import warnings

            with warnings.catch_warnings():
                warnings.simplefilter("ignore", RuntimeWarning)
                f["mem_std"] = np.nanstd(mm, axis=1).astype(np.float32)
                f["mem_q90"] = np.nanquantile(mm, 0.9, axis=1).astype(np.float32)
                for t in thresholds:
                    ok = np.isfinite(mm)
                    f[f"mem_frac_ge_{t}"] = (
                        np.where(ok, mm >= t, False).sum(1) / np.maximum(ok.sum(1), 1)
                    ).astype(np.float32)
                    f.loc[ok.sum(1) == 0, f"mem_frac_ge_{t}"] = np.nan
    return f
