"""Load canonical forecasts and truth, and pair them by IMD day.

Only monthly stores (``<YYYYMM>.zarr``) are read. By default everything with a valid day inside the
frozen test period (>= 2026-01-01) is dropped; ``allow_test=True`` is reserved for Phase 8.
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd
import xarray as xr

TEST_START = pd.Timestamp("2026-01-01")
VAR_PAIRS = {"precip": ("precip_24h_mm", "rain_mm"), "tmax": ("tmax_c", "tmax_c")}
# IMD day of the observation paired with a forecast window whose label (valid_day) is L:
# rain: L (24 h ending 03 UTC on L). Tmax: L - 1, because IMD Tmax of day D is D's daytime maximum,
# which lies in the window (D 03Z, D+1 03Z] labelled D+1. Verified on real data 2026-09-30:
# day-to-day changes of forecast Tmax correlate with IMD Tmax at shift -1 (r 0.31-0.64),
# ~0 at shift 0.
TRUTH_DAY_OFFSET = {"precip": 0, "tmax": -1}


def _monthly(folder: Path) -> list[Path]:
    return sorted(p for p in folder.glob("*.zarr") if p.stem.isdigit() and len(p.stem) == 6)


def load_canonical(
    root: Path, adapter: str, region: str, allow_test: bool = False
) -> xr.Dataset | None:
    """All monthly canonical stores of one adapter/region, concatenated on init_time (or None)."""
    files = _monthly(root / "processed" / "canonical" / adapter / region)
    if not files:
        return None
    parts = [xr.open_zarr(f, consolidated=False) for f in files]
    ds = xr.concat(parts, dim="init_time", combine_attrs="override", join="outer")
    ds = ds.sortby("init_time")
    if not allow_test:
        keep = pd.DatetimeIndex(ds["valid_day"].max("lead_h").values) < TEST_START
        ds = ds.isel(init_time=np.flatnonzero(keep))
    return ds


def load_truth(root: Path, region: str, allow_test: bool = False) -> xr.Dataset:
    """All monthly truth stores of a region, concatenated on time."""
    files = _monthly(root / "processed" / "truth" / region)
    if not files:
        raise FileNotFoundError(f"no truth stores for {region}; run scripts/build_truth.py")
    ds = xr.concat([xr.open_zarr(f, consolidated=False) for f in files], dim="time").sortby("time")
    if not allow_test:
        ds = ds.sel(time=ds.time < np.datetime64(TEST_START))
    return ds.load()


def obs_like(fc: xr.Dataset, truth: xr.DataArray, offset_days: int = 0) -> xr.DataArray:
    """Observations arranged like the forecast: (init_time, lead_h, lat, lon) via ``valid_day``.

    ``offset_days``: IMD day of the observation relative to the window label (see TRUTH_DAY_OFFSET).
    """
    vd = fc["valid_day"].values
    t = truth.reindex(time=pd.DatetimeIndex(vd.ravel()) + pd.Timedelta(days=offset_days))
    arr = t.values.reshape(vd.shape + t.shape[1:])
    return xr.DataArray(
        arr,
        dims=("init_time", "lead_h", "lat", "lon"),
        coords={"init_time": fc.init_time, "lead_h": fc.lead_h, "lat": truth.lat, "lon": truth.lon},
    )


def deterministic(da: xr.DataArray) -> xr.DataArray:
    """Ensemble mean for ensembles, the field itself otherwise."""
    return da.mean("member") if "member" in da.dims else da


def exceed_prob(da: xr.DataArray, threshold: float) -> xr.DataArray:
    """P(value >= threshold): member fraction for ensembles, 0/1 for deterministic (NaN kept)."""
    ok = np.isfinite(da)
    ev = (da >= threshold).astype(float).where(ok)
    return ev.mean("member") if "member" in ev.dims else ev


def season_of(days: np.ndarray) -> np.ndarray:
    """IMD seasons: JF winter, MAM pre-monsoon, JJAS monsoon, OND post-monsoon."""
    m = pd.DatetimeIndex(np.asarray(days).ravel()).month.to_numpy()
    out = np.empty(m.shape, dtype=object)
    out[np.isin(m, [1, 2])] = "winter_JF"
    out[np.isin(m, [3, 4, 5])] = "premonsoon_MAM"
    out[np.isin(m, [6, 7, 8, 9])] = "monsoon_JJAS"
    out[np.isin(m, [10, 11, 12])] = "postmonsoon_OND"
    return out.reshape(np.asarray(days).shape)
