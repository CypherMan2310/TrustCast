"""Assemble ``truth_v1`` for a region and a list of IMD days.

Rain: IMD gauge grid where the day exists in the local IMD files (``provisional=False``); otherwise
IMERG Late remapped to the IMD grid (``provisional=True``). If neither is available the day is NaN.
Tmax: IMD 1 deg -> 0.25 deg only; there is no satellite substitute, so missing IMD Tmax stays NaN.
Everything is masked to IMD land cells (cells where IMD rain is ever finite).
"""

from __future__ import annotations

import datetime as dt
import logging
from pathlib import Path

import numpy as np
import pandas as pd
import xarray as xr

from trustcast.adapters.base import SourceUnavailable
from trustcast.config import RegionConfig
from trustcast.grid.imd_grid import IMD_RAIN_0P25
from trustcast.grid.schema import TRUTH_SCHEMA
from trustcast.log import event
from trustcast.truth import imd, imerg

log = logging.getLogger(__name__)


def imd_land_mask(root: Path, region: RegionConfig) -> xr.DataArray:
    """Boolean (lat, lon): IMD rain cell has data (from the first local IMD rain file)."""
    for year in range(2024, dt.date.today().year + 1):
        p = imd.grd_path(root, "rain", year)
        if p is not None:
            da = imd.rain_on_region(imd.read_grd(p, "rain", year), region)
            return np.isfinite(da).any("time")
    raise FileNotFoundError("no IMD rain file to derive the land mask from (data/truth/rain)")


def build_truth(
    root: Path, days: pd.DatetimeIndex, region: RegionConfig, imerg_product: str = "late"
) -> xr.Dataset:
    """Truth dataset for ``days`` on the region's IMD 0.25 deg points."""
    days = pd.DatetimeIndex(days).normalize()
    lats, lons = IMD_RAIN_0P25.region_points(region)
    mask = imd_land_mask(root, region)
    shape = (days.size, lats.size, lons.size)
    rain = xr.DataArray(
        np.full(shape, np.nan, np.float32),
        dims=("time", "lat", "lon"),
        coords={"time": days, "lat": lats, "lon": lons},
    )
    tmax = rain.copy()
    provisional = np.zeros(days.size, dtype=bool)

    imd_rain = imd.load_imd(root, "rain", days)
    have_imd = [
        d
        for d in days
        if d in set(pd.DatetimeIndex(imd_rain.time.values))
        and np.isfinite(imd_rain.sel(time=d).values).any()
    ]
    if have_imd:
        rain.loc[{"time": have_imd}] = imd.rain_on_region(
            imd_rain.sel(time=have_imd), region
        ).values
    missing = days.difference(pd.DatetimeIndex(have_imd))
    sources = ["IMD gridded rainfall 0.25 deg"]
    if missing.size:
        try:
            sat = imerg.imerg_daily(missing, region, imerg_product)
            rain.loc[{"time": missing}] = sat.values
            filled = np.isfinite(sat.values).any(axis=(1, 2))
            provisional[days.isin(missing[filled])] = True
            sources.append(f"NASA GPM IMERG V07 {imerg_product} (provisional days)")
        except SourceUnavailable as e:
            event(
                log,
                logging.ERROR,
                "imerg unavailable; days left NaN",
                region=region.name,
                n_days=int(missing.size),
                error=str(e),
            )

    imd_t = imd.load_imd(root, "tmax", days)
    if imd_t.sizes["time"]:
        t_days = pd.DatetimeIndex(imd_t.time.values)
        tmax.loc[{"time": t_days}] = imd.tmax_on_region(imd_t, region).values
        sources.append("IMD gridded Tmax 1.0 deg")

    ds = xr.Dataset(
        {
            "rain_mm": rain.where(mask).astype(np.float32),
            "tmax_c": tmax.where(mask).astype(np.float32),
            "provisional": ("time", provisional),
        },
        attrs={
            "schema": TRUTH_SCHEMA,
            "region": region.name,
            "sources": "; ".join(sources),
            "licence": f"{imd.LICENCE}; {imerg.LICENCE}",
            "created_at": dt.datetime.now(dt.UTC).isoformat(),
            "tmax_regrid_method": "IMD 1 deg: one-ring neighbour fill at coast, then bilinear; "
            "masked to IMD rain land cells",
            "rain_window": "24 h ending 03 UTC (08:30 IST) on `time`",
        },
    )
    ds["rain_mm"].attrs = {"units": "mm"}
    ds["tmax_c"].attrs = {"units": "degC"}
    return ds
