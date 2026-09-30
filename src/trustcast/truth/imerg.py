"""NASA GPM IMERG (V07) from dynamical.org -> IMD-day rainfall on the IMD 0.25 deg grid.

Verified 2026-09-30: ``precipitation_surface`` is the mean rate (mm/s) over the half hour
STARTING at the time label; 0.1 deg grid, latitude descending; Late run ~14 h latency
(gauge-adjusted where
available), Early run ~4 h. IMD day D = (D-1 03Z, D 03Z] = the 48 half-hours starting
D-1 03:00 ... D 02:30. A day needs all 48 half-hours valid, else NaN. Remapped conservatively.
Used only as *provisional* truth where IMD gauge data is not (yet) available.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import xarray as xr

from trustcast.adapters.base import SourceUnavailable
from trustcast.config import RegionConfig
from trustcast.grid.imd_grid import IMD_RAIN_0P25
from trustcast.grid.regrid import conservative

DATASETS = {"late": "nasa-imerg-analysis-late", "early": "nasa-imerg-analysis-early"}
LICENCE = "CC BY 4.0, NASA GPM IMERG V07 via dynamical.org"
_MARGIN = 0.3


def imerg_daily(
    days: pd.DatetimeIndex, region: RegionConfig, product: str = "late"
) -> xr.DataArray:
    """IMD-day rain (mm) from IMERG on the region's IMD points, dims (time, lat, lon)."""
    import dynamical_catalog

    try:
        ds = dynamical_catalog.open(DATASETS[product])
    except Exception as e:  # network / catalogue failure
        raise SourceUnavailable(f"imerg {product}: {e}") from e
    lats, lons = IMD_RAIN_0P25.region_points(region)
    days = pd.DatetimeIndex(days).normalize()
    t0 = days.min() - pd.Timedelta(hours=21)  # D-1 03:00
    t1 = days.max() + pd.Timedelta(hours=2, minutes=30)  # D 02:30 (last half-hour start)
    sub = (
        ds["precipitation_surface"]
        .sel(
            time=slice(t0, t1),
            latitude=slice(lats.max() + _MARGIN, lats.min() - _MARGIN),
            longitude=slice(lons.min() - _MARGIN, lons.max() + _MARGIN),
        )
        .load()
    )
    sub = sub.rename({"latitude": "lat", "longitude": "lon"}).sortby("lat")
    have = pd.DatetimeIndex(sub.time.values)
    out = []
    for d in days:
        starts = pd.date_range(d - pd.Timedelta(hours=21), periods=48, freq="30min")
        if not starts.isin(have).all():
            out.append(np.full((sub.lat.size, sub.lon.size), np.nan, np.float32))
            continue
        x = sub.sel(time=starts).values * 1800.0  # mm per half hour
        total = x.sum(axis=0)
        total[~np.isfinite(x).all(axis=0)] = np.nan
        out.append(total.astype(np.float32))
    daily = xr.DataArray(
        np.stack(out),
        dims=("time", "lat", "lon"),
        coords={"time": days, "lat": sub.lat.values, "lon": sub.lon.values},
    )
    return conservative(daily, lats, lons, dst_step=IMD_RAIN_0P25.step)
