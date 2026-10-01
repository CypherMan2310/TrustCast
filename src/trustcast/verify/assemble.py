"""Assemble forecasts, observations and baselines for one region and variable.

Shared by verification (Phase 2), blending (Phases 3-5) and the replay/product code.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

import numpy as np
import pandas as pd
import xarray as xr

from trustcast.blend.baselines import (
    build_climatology,
    clim_for,
    equal_mean,
    persistence,
    superensemble,
)
from trustcast.config import Config
from trustcast.verify.data import (
    TRUTH_DAY_OFFSET,
    VAR_PAIRS,
    load_canonical,
    load_truth,
    obs_like,
)
from trustcast.verify.scoreboard import THRESHOLDS, Forecast


@dataclass
class Bundle:
    """Sources on a common (init_time, lead_h, lat, lon) grid plus observations."""

    region: str
    variable: str
    forecasts: list[Forecast]
    obs: xr.DataArray
    truth: xr.DataArray
    coverage: list[dict] = field(default_factory=list)

    @property
    def like(self) -> xr.DataArray:
        """Template array with the common coordinates (incl. valid_day)."""
        return self.forecasts[0].det

    def get(self, name: str) -> Forecast:
        """Forecast by name."""
        return next(f for f in self.forecasts if f.name == name)


def valid_day_array(inits: pd.DatetimeIndex, lead_h: np.ndarray) -> np.ndarray:
    """IMD day label per (init, lead): init + lead_h - 3 h."""
    return (
        inits.values[:, None] + (lead_h.astype("timedelta64[h]") - np.timedelta64(3, "h"))[None, :]
    )


def assemble(
    cfg: Config,
    root: Path,
    region: str,
    variable: str,
    allow_test: bool = False,
    sources: list[str] | None = None,
) -> Bundle | None:
    """Load every eval source (monthly stores) on a common init axis, plus the observations."""
    fc_var, truth_var = VAR_PAIRS[variable]
    raw = {}
    for name, a in cfg.adapters.items():
        if a.use != "eval" or a.type == "ncum" or not a.enabled:
            continue
        if sources and a.source not in sources:
            continue
        ds = load_canonical(root, name, region, allow_test=allow_test)
        if ds is not None and ds.sizes["init_time"]:
            raw[a.source] = ds[fc_var]
    if not raw:
        return None
    inits = pd.DatetimeIndex(
        sorted(set().union(*[set(pd.DatetimeIndex(d.init_time.values)) for d in raw.values()]))
    )
    lead_h = next(iter(raw.values())).lead_h.values
    vd = valid_day_array(inits, lead_h)
    coverage, forecasts = [], []
    for src, da in raw.items():
        da = (
            da.reindex(init_time=inits)
            .assign_coords(valid_day=(("init_time", "lead_h"), vd))
            .load()
        )
        ens = da if "member" in da.dims else None
        det = da.mean("member") if ens is not None else da
        forecasts.append(Forecast(src, "source", det, ens))
        have = inits[np.isfinite(det.values).any(axis=(1, 2, 3))]
        coverage.append(
            {
                "region": region,
                "variable": variable,
                "forecast": src,
                "first_init": have.min() if len(have) else None,
                "last_init": have.max() if len(have) else None,
                "n_inits": len(have),
                "members": int(da.sizes.get("member", 1)),
            }
        )
    truth = load_truth(root, region, allow_test=allow_test)[truth_var]
    grid = forecasts[0].det
    truth = truth.sel(lat=grid.lat, lon=grid.lon)
    obs = obs_like(grid.to_dataset(name="x"), truth, TRUTH_DAY_OFFSET[variable]).assign_coords(
        valid_day=(("init_time", "lead_h"), vd)
    )
    return Bundle(region, variable, forecasts, obs, truth, coverage)


DEV_EVAL = ("2024-04-01", "2025-12-26")  # dev inits whose 5 lead days all fall in the dev split
MIN_SOURCE_COVERAGE = 0.8
MIN_SOURCE_DAYS = 150


def source_coverage(
    cfg: Config, root: Path, region: str, span: tuple[str, str] = DEV_EVAL
) -> list[dict]:
    """Per eval source: share of daily 00Z inits present in ``span``, counted from the later of the
    span start and the source's own first init (so a source the provider started mid-span, such as
    AIFS-ENS on 2025-07-02, is judged on its own period). Dev split only; test data are not read."""
    rows = []
    for name, a in cfg.adapters.items():
        if a.use != "eval" or a.type == "ncum" or not a.enabled:
            continue
        ds = load_canonical(root, name, region)
        have = pd.DatetimeIndex([]) if ds is None else pd.DatetimeIndex(ds.init_time.values)
        have = have[(have >= span[0]) & (have <= span[1])]
        start = max(pd.Timestamp(span[0]), have.min()) if len(have) else pd.Timestamp(span[0])
        want = pd.date_range(start, span[1], freq="D")
        frac = float(np.isin(want, have).mean()) if len(have) else 0.0
        rows.append(
            {
                "adapter": name,
                "source": a.source,
                "first_init": str(start.date()) if len(have) else None,
                "n_inits": len(have),
                "coverage": round(frac, 3),
                # and its period must be long enough to learn from (>= MIN_SOURCE_DAYS)
                "eligible": bool(frac >= MIN_SOURCE_COVERAGE and len(want) >= MIN_SOURCE_DAYS),
            }
        )
    return rows


def frozen_sources(region: str, variable: str, path: Path | None = None) -> list[str] | None:
    """Source set frozen in ``config/model_selection.yaml`` for region/variable (None if absent)."""
    import yaml

    from trustcast.config import REPO_ROOT

    p = Path(path) if path else REPO_ROOT / "config" / "model_selection.yaml"
    if not p.exists():
        return None
    sel = (yaml.safe_load(p.read_text()) or {}).get("models", {}).get(f"{region}_{variable}") or {}
    return sel.get("sources")


def climatology(cfg: Config, root: Path, region: str, variable: str) -> xr.Dataset | None:
    """IMD 1991-2020 day-of-year climatology for the region (cached as NetCDF)."""
    cache = root / "processed" / "climatology" / f"{region}_{variable}.nc"
    if cache.exists():
        return xr.open_dataset(cache).load()
    clim = build_climatology(
        root, "rain" if variable == "precip" else "tmax", cfg.regions[region], THRESHOLDS[variable]
    )
    if clim is not None:
        cache.parent.mkdir(parents=True, exist_ok=True)
        clim.to_netcdf(cache)
    return clim


def baselines(cfg: Config, root: Path, b: Bundle) -> tuple[list[Forecast], dict | None]:
    """Equal mean, superensemble, persistence and (if available) climatology + BSS reference."""
    dets = {f.name: f.det for f in b.forecasts}
    like = b.like
    out = [
        Forecast(
            "equal_mean", "baseline", equal_mean(dets).assign_coords(valid_day=like.valid_day)
        ),
        Forecast("superensemble", "baseline", superensemble(dets, b.obs)),
        Forecast(
            "persistence",
            "baseline",
            persistence(b.truth, like).assign_coords(valid_day=like.valid_day),
        ),
    ]
    clim = climatology(cfg, root, b.region, b.variable)
    ref_prob = None
    if clim is not None:
        out.append(
            Forecast(
                "climatology",
                "baseline",
                clim_for(clim, "mean", like, TRUTH_DAY_OFFSET[b.variable]).assign_coords(
                    valid_day=like.valid_day
                ),
            )
        )
        ref_prob = {
            t: clim_for(clim, f"p_ge_{t}", like, TRUTH_DAY_OFFSET[b.variable])
            for t in THRESHOLDS[b.variable]
        }
    return out, ref_prob
