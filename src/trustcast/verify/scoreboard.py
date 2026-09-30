"""Stratified scoreboard with block-bootstrap intervals and paired differences.

All forecasts are first put on one common init axis (outer join), so case i means the same
(init, lead, cell) for every forecast. Scores are pooled over cells; bootstrap blocks are 5
consecutive valid days (all cells together). Blocks without any valid case in the stratum are
dropped before resampling so that empty blocks cannot shrink the variance.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

import numpy as np
import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq
import xarray as xr

from trustcast.verify.bootstrap import (
    aggregate_blocks,
    block_ids,
    bootstrap_ci,
    paired_block_bootstrap,
)
from trustcast.verify.data import season_of
from trustcast.verify.metrics import (
    HEAT_THRESHOLD_C,
    RAIN_THRESHOLDS,
    crps_fair,
    reliability_table,
    scores_from_stats,
)

THRESHOLDS = {"precip": RAIN_THRESHOLDS, "tmax": (HEAT_THRESHOLD_C,)}
SEASONS = ("all", "winter_JF", "premonsoon_MAM", "monsoon_JJAS", "postmonsoon_OND")


@dataclass
class Forecast:
    """One forecast on the common case grid. ``det`` (init, lead, lat, lon); ``ens`` adds member."""

    name: str
    kind: str  # "source" or "baseline"
    det: xr.DataArray
    ens: xr.DataArray | None = None


@dataclass
class Cases:
    """Flattened per-case arrays for one forecast at one lead (cases = init x lat x lon)."""

    fc: np.ndarray
    obs: np.ndarray
    crps: np.ndarray
    prob: dict[float, np.ndarray]
    days: np.ndarray
    season: np.ndarray
    valid: np.ndarray = field(init=False)

    def __post_init__(self) -> None:
        self.valid = np.isfinite(self.fc) & np.isfinite(self.obs) & np.isfinite(self.crps)


def overall(sb: pd.DataFrame) -> pd.DataFrame:
    """Rows of the unstratified result (season "all" and regime "all")."""
    if sb.empty:
        return sb
    m = sb["season"] == "all"
    if "regime" in sb:
        m &= sb["regime"] == "all"
    return sb[m]


def make_cases(f: Forecast, obs: xr.DataArray, li: int, thresholds: tuple[float, ...]) -> Cases:
    """Per-case arrays of forecast ``f`` at lead index ``li``."""
    det = f.det.isel(lead_h=li).transpose("init_time", "lat", "lon").values.ravel()
    ob = obs.isel(lead_h=li).transpose("init_time", "lat", "lon").values.ravel()
    ncell = f.det.sizes["lat"] * f.det.sizes["lon"]
    vd = f.det["valid_day"].isel(lead_h=li).values
    days = np.repeat(vd, ncell)
    if f.ens is not None:
        m = f.ens.isel(lead_h=li).transpose("init_time", "lat", "lon", "member").values
        m = m.reshape(-1, m.shape[-1])
        full = np.isfinite(m).all(axis=1) & np.isfinite(ob)
        crps = np.full(ob.shape, np.nan)
        crps[full] = crps_fair(m[full], ob[full])
        prob = {
            t: np.where(np.isfinite(m).all(axis=1), (m >= t).mean(axis=1), np.nan)
            for t in thresholds
        }
    else:
        crps = np.abs(det - ob)
        prob = {t: np.where(np.isfinite(det), (det >= t).astype(float), np.nan) for t in thresholds}
    return Cases(det, ob, crps, prob, days, season_of(days))


def _per_case(
    c: Cases, mask: np.ndarray, thresholds, ref_prob: dict | None
) -> dict[str, np.ndarray]:
    w = mask.astype(float)
    e = np.where(mask, c.fc - c.obs, 0.0)
    out = {
        "n": w,
        "sum_err": e,
        "sum_abs": np.abs(e),
        "sum_sq": e * e,
        "sum_crps": np.where(mask, c.crps, 0.0),
    }
    for t in thresholds:
        fe, oe = c.fc >= t, c.obs >= t
        out[f"a_{t}"] = (fe & oe & mask).astype(float)
        out[f"b_{t}"] = (fe & ~oe & mask).astype(float)
        out[f"c_{t}"] = (~fe & oe & mask).astype(float)
        out[f"d_{t}"] = (~fe & ~oe & mask).astype(float)
        p = np.where(mask, c.prob[t], 0.0)
        out[f"nb_{t}"] = w
        out[f"sum_bs_{t}"] = np.where(mask, (p - oe) ** 2, 0.0)
        if ref_prob is not None:
            r = np.where(mask, np.nan_to_num(ref_prob[t]), 0.0)
            out[f"sum_bs_ref_{t}"] = np.where(mask, (r - oe) ** 2, 0.0)
    return out


def _cont(t: float, name: str):
    return lambda s: scores_from_stats({k: s[f"{k}_{t}"] for k in "abcd"})[name]


def _bss(t: float):
    return lambda s: scores_from_stats(
        {"nb": s[f"nb_{t}"], "sum_bs": s[f"sum_bs_{t}"], "sum_bs_ref": s[f"sum_bs_ref_{t}"]}
    )["bss"]


def _brier(t: float):
    return lambda s: scores_from_stats(
        {"nb": s[f"nb_{t}"], "sum_bs": s[f"sum_bs_{t}"], "sum_bs_ref": s[f"sum_bs_{t}"]}
    )["brier"]


def _score(name: str):
    return lambda s: scores_from_stats(s)[name]


def _blocks(days: np.ndarray, per_case: dict[str, np.ndarray], keep: np.ndarray | None = None):
    _, st = aggregate_blocks(block_ids(days), per_case)
    nonempty = st["n"] > 0 if keep is None else keep
    return {k: v[nonempty] for k, v in st.items()}, nonempty


def scoreboard(
    forecasts: list[Forecast],
    obs: xr.DataArray,
    variable: str,
    region: str,
    reference: str,
    ref_prob: dict[float, xr.DataArray] | None = None,
    n_boot: int = 1000,
    seed: int = 0,
    sample: str = "common",
    window: tuple[pd.Timestamp | None, pd.Timestamp | None] = (None, None),
    common: bool = True,
    regimes: xr.DataArray | None = None,
) -> pd.DataFrame:
    """One row per (forecast, lead, stratum): scores, 95 % CIs and paired diffs vs ``reference``.

    Strata: every season (regime "all") and, if ``regimes`` (init_time, lead_h labels) is given,
    every regime (season "all").

    With ``common=True`` (default) every row of a lead is scored on the same cases: those where
    *all* forecasts in ``forecasts`` and the observation are valid, restricted to valid days in
    ``window``. Rows are then directly comparable. ``common=False`` scores each forecast on its own
    available cases (not comparable across rows; diagnostics only).
    """
    thr = THRESHOLDS[variable]
    lead_h = obs.lead_h.values
    ref_f = next((f for f in forecasts if f.name == reference), None)
    rows = []
    for li, lh in enumerate(lead_h):
        rp = None
        if ref_prob is not None:
            rp = {
                t: ref_prob[t].isel(lead_h=li).transpose("init_time", "lat", "lon").values.ravel()
                for t in thr
            }
        cases = {f.name: make_cases(f, obs, li, thr) for f in forecasts}
        any_c = next(iter(cases.values()))
        in_window = np.ones(any_c.valid.shape, bool)
        days = pd.DatetimeIndex(any_c.days)
        if window[0] is not None:
            in_window &= days >= window[0]
        if window[1] is not None:
            in_window &= days <= window[1]
        shared = np.logical_and.reduce([c.valid for c in cases.values()]) if common else None
        strata = [(s, "all") for s in SEASONS]
        case_regime = None
        if regimes is not None:
            ncell = obs.sizes["lat"] * obs.sizes["lon"]
            reg = regimes.reindex(init_time=obs.init_time).isel(lead_h=li).values.astype(str)
            case_regime = np.repeat(reg, ncell)
            strata += [("all", r) for r in sorted(set(reg)) if r not in ("nan", "unknown")]
        for season, regime in strata:
            for f in forecasts:
                c = cases[f.name]
                smask = np.ones(c.valid.shape, bool) if season == "all" else (c.season == season)
                if regime != "all":
                    smask = smask & (case_regime == regime)
                mask = (shared if common else c.valid) & smask & in_window
                if mask.sum() == 0:
                    continue
                st, _ = _blocks(c.days, _per_case(c, mask, thr, rp))
                tot = {k: float(v.sum()) for k, v in st.items()}
                base = scores_from_stats(
                    {k: tot[k] for k in ("n", "sum_err", "sum_abs", "sum_sq", "sum_crps")}
                )
                row = {
                    "sample": sample,
                    "region": region,
                    "variable": variable,
                    "lead_day": li + 1,
                    "lead_h": int(lh),
                    "season": season,
                    "regime": regime,
                    "forecast": f.name,
                    "kind": f.kind,
                    "ensemble": f.ens is not None,
                    "n_cases": int(base["n"]),
                    "n_blocks": len(st["n"]),
                    "bias": base["bias"],
                    "mae": base["mae"],
                }
                for name in ("rmse", "crps"):
                    est, lo, hi = bootstrap_ci(st, _score(name), n_boot, seed)
                    row.update({name: est, f"{name}_lo": lo, f"{name}_hi": hi})
                for t in thr:
                    cs = scores_from_stats({k: tot[f"{k}_{t}"] for k in "abcd"})
                    row.update(
                        {
                            f"n_obs_ev_{t}": cs["n_obs_events"],
                            f"pod_{t}": cs["pod"],
                            f"far_{t}": cs["far"],
                            f"csi_{t}": cs["csi"],
                            f"fbias_{t}": cs["freq_bias"],
                        }
                    )
                    est, lo, hi = bootstrap_ci(st, _cont(t, "ets"), n_boot, seed)
                    row.update({f"ets_{t}": est, f"ets_{t}_lo": lo, f"ets_{t}_hi": hi})
                    row[f"brier_{t}"] = _brier(t)(tot)
                    if rp is not None:
                        est, lo, hi = bootstrap_ci(st, _bss(t), n_boot, seed)
                        row.update({f"bss_{t}": est, f"bss_{t}_lo": lo, f"bss_{t}_hi": hi})
                if ref_f is not None and f.name != reference:
                    rc = cases[reference]
                    pm = mask & rc.valid & in_window
                    if pm.sum():
                        sa, keep = _blocks(c.days, _per_case(c, pm, thr, rp))
                        sb, _ = _blocks(rc.days, _per_case(rc, pm, thr, rp), keep)
                        for name, fn in (
                            ("rmse", _score("rmse")),
                            ("crps", _score("crps")),
                            (f"ets_{thr[0]}", _cont(thr[0], "ets")),
                        ):
                            r = paired_block_bootstrap(sa, sb, fn, n_boot, seed)
                            row.update(
                                {
                                    f"d_{name}_vs_ref": r.diff,
                                    f"d_{name}_lo": r.ci_low,
                                    f"d_{name}_hi": r.ci_high,
                                    f"d_{name}_p": r.p_value,
                                }
                            )
                rows.append(row)
    return pd.DataFrame(rows)


def reliability(
    forecasts: list[Forecast], obs: xr.DataArray, threshold: float, lead_index: int
) -> pd.DataFrame:
    """Reliability-diagram data for every ensemble forecast at one threshold and lead."""
    rows = []
    for f in forecasts:
        if f.ens is None:
            continue
        c = make_cases(f, obs, lead_index, (threshold,))
        ok = np.isfinite(c.prob[threshold]) & np.isfinite(c.obs)
        for r in reliability_table(c.prob[threshold][ok], c.obs[ok] >= threshold, bins=10):
            rows.append(
                {"forecast": f.name, "threshold": threshold, "lead_day": lead_index + 1, **r}
            )
    return pd.DataFrame(rows)


def write_skill_table(
    forecasts: list[Forecast], obs: xr.DataArray, variable: str, region: str, out_dir: Path
) -> list[Path]:
    """Per-case skill table (CLAUDE.md contract), one Parquet file per forecast."""
    thr = THRESHOLDS[variable]
    paths = []
    lat, lon = obs.lat.values, obs.lon.values
    cell = np.array([f"{a:.2f}_{b:.2f}" for a in lat for b in lon])
    for f in forecasts:
        frames = []
        for li in range(obs.sizes["lead_h"]):
            c = make_cases(f, obs, li, thr)
            ninit = f.det.sizes["init_time"]
            init = np.repeat(f.det.init_time.values, cell.size)
            cells = np.tile(cell, ninit)
            ok = c.valid
            flags = np.zeros(ok.sum(), np.int8)
            for k, t in enumerate(thr):
                flags |= (c.fc[ok] >= t).astype(np.int8) << (2 * k)
                flags |= (c.obs[ok] >= t).astype(np.int8) << (2 * k + 1)
            e = (c.fc - c.obs)[ok]
            frames.append(
                pd.DataFrame(
                    {
                        "source": f.name,
                        "variable": variable,
                        "cell_or_subdivision": cells[ok],
                        "lead_bucket": np.int8(li + 1),
                        "season": c.season[ok].astype(str),
                        "valid_time": c.days[ok],
                        "init_time": init[ok],
                        "forecast": c.fc[ok].astype(np.float32),
                        "observed": c.obs[ok].astype(np.float32),
                        "error": e.astype(np.float32),
                        "abs_error": np.abs(e).astype(np.float32),
                        "sq_error": (e * e).astype(np.float32),
                        "event_hit_flags": flags,
                        "regime": "all",
                    }
                )
            )
        df = pd.concat(frames, ignore_index=True)
        p = out_dir / region / variable / f"{f.name}.parquet"
        p.parent.mkdir(parents=True, exist_ok=True)
        table = pa.Table.from_pandas(df, preserve_index=False)
        table = table.replace_schema_metadata(
            {
                b"event_hit_flags": (
                    "bit 2k: forecast >= threshold k, bit 2k+1: observed >= threshold k; "
                    f"thresholds {thr}"
                ).encode(),
                b"region": region.encode(),
            }
        )
        pq.write_table(table, p)
        paths.append(p)
    return paths
