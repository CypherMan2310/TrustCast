"""IMD gridded rainfall (0.25 deg) and maximum temperature (1.0 deg).

Files are IMD yearly binary ``.grd`` grids downloaded with ``imdlib`` (imdpune.gov.in) into
``data/truth/{rain,tmax}/<year>.grd|GRD``. Layout: float32, little-endian, (day, lat, lon) with lon
varying fastest and latitude ascending. Missing codes: rain -999 (mask < -100), Tmax 99.9
(mask >= 60). The raw reader is checked against ``imdlib.open_data`` in ``tests/test_truth.py``.

Day labels: IMD value for date D is the 24 h ending 08:30 IST (03 UTC) on D (confirmed on real data,
WORK.md 2026-09-30).
"""

from __future__ import annotations

import contextlib
import datetime as dt
import shutil
import time
from pathlib import Path

import numpy as np
import pandas as pd
import xarray as xr

from trustcast.config import RegionConfig
from trustcast.grid.imd_grid import IMD_RAIN_0P25, IMD_TEMP_1P0, RegularGrid

GRIDS: dict[str, RegularGrid] = {"rain": IMD_RAIN_0P25, "tmax": IMD_TEMP_1P0}
LICENCE = "India Meteorological Department gridded data (imdpune.gov.in); attribute IMD"


def grd_path(root: Path, var: str, year: int) -> Path | None:
    """Existing non-empty yearly file for ``var`` (rain|tmax), or None."""
    folder = root / "truth" / var
    for name in (f"{year}.grd", f"{year}.GRD"):
        p = folder / name
        if p.exists() and p.stat().st_size > 0:
            return p
    return None


def read_grd(path: Path, var: str, year: int) -> xr.DataArray:
    """Read a (possibly partial-year) IMD .grd file with missing codes masked to NaN."""
    g = GRIDS[var]
    cell = g.nlat * g.nlon
    raw = np.fromfile(path, dtype="<f4")
    n = raw.size // cell
    if n == 0:
        raise ValueError(f"{path} holds no complete day")
    arr = raw[: n * cell].reshape(n, g.nlat, g.nlon).astype(np.float32)
    arr[arr < -100] = np.nan
    if var == "tmax":
        arr[arr >= 60] = np.nan
    return xr.DataArray(
        arr,
        dims=("time", "lat", "lon"),
        coords={"time": pd.date_range(f"{year}-01-01", periods=n), "lat": g.lats, "lon": g.lons},
        name=var,
    )


def download_year(root: Path, var: str, year: int, tries: int = 3) -> Path | None:
    """Download one year with imdlib into a staging dir, then move it into place if non-empty.

    imdpune.gov.in is often slow; failures return None and never clobber an existing file.
    """
    import imdlib

    staging = root / "truth" / "_staging"
    for attempt in range(tries):
        # imdlib may raise after writing the file; the file itself is checked below
        with contextlib.suppress(Exception):
            imdlib.get_data(var, year, year, fn_format="yearwise", file_dir=str(staging))
        hits = [
            h
            for h in staging.rglob("*")
            if h.is_file() and h.stem == str(year) and h.parent.name == var and h.stat().st_size > 0
        ]
        if hits:
            dest = root / "truth" / var / hits[0].name
            dest.parent.mkdir(parents=True, exist_ok=True)
            if not dest.exists() or dest.stat().st_size <= hits[0].stat().st_size:
                shutil.copy2(hits[0], dest)
            hits[0].unlink()
            return dest
        time.sleep(10 * (attempt + 1))
    return None


def load_imd(root: Path, var: str, days: pd.DatetimeIndex) -> xr.DataArray:
    """IMD field on its native grid for the requested days (days missing from files are absent)."""
    parts = []
    for year in sorted({d.year for d in days}):
        p = grd_path(root, var, year)
        if p is None:
            continue
        da = read_grd(p, var, year)
        parts.append(da.sel(time=da.time.isin(days)))
    if not parts:
        g = GRIDS[var]
        return xr.DataArray(
            np.empty((0, g.nlat, g.nlon), np.float32),
            dims=("time", "lat", "lon"),
            coords={"time": pd.DatetimeIndex([]), "lat": g.lats, "lon": g.lons},
        )
    return xr.concat(parts, dim="time")


def rain_on_region(da: xr.DataArray, region: RegionConfig) -> xr.DataArray:
    """IMD rain on the region's 0.25 deg points (identity: same grid)."""
    lats, lons = IMD_RAIN_0P25.region_points(region)
    return da.sel(lat=lats, lon=lons, method="nearest", tolerance=1e-6).assign_coords(
        lat=lats, lon=lons
    )


def tmax_on_region(da: xr.DataArray, region: RegionConfig) -> xr.DataArray:
    """IMD 1 deg Tmax onto the region's 0.25 deg points.

    Missing 1 deg cells adjacent to valid ones (coast) are first filled with the mean of their
    valid 3x3 neighbours (one ring only), then values are bilinearly interpolated. The truth
    builder masks the result to IMD land cells. Coarse by construction (plan reality check #5).
    """
    lats, lons = IMD_RAIN_0P25.region_points(region)
    ring = da.rolling(lat=3, lon=3, center=True, min_periods=1).mean()
    filled = da.fillna(ring)
    return filled.interp(lat=lats, lon=lons, method="linear").astype(np.float32)


def available_days(root: Path, var: str, years: list[int]) -> pd.DatetimeIndex:
    """Days present (at least one finite value) in the local IMD files."""
    out = []
    for y in years:
        p = grd_path(root, var, y)
        if p is None:
            continue
        da = read_grd(p, var, y)
        ok = np.isfinite(da.values).any(axis=(1, 2))
        out.extend(pd.DatetimeIndex(da.time.values)[ok])
    return pd.DatetimeIndex(out)


def today_utc() -> dt.date:
    """Current UTC date (separate function for testability)."""
    return dt.datetime.now(dt.UTC).date()


# ----------------------------------------------------------------------------- real-time grids
# IMD real-time daily grids (imdpune.gov.in/cmpg/Realtimedata, via imdlib.get_real_data), verified
# 2026-09-30: rain 0.25 deg on the same 129 x 135 grid; Tmax 0.5 deg, 61 x 61 from 7.5 N / 67.5 E.
# One day per file: float32 little-endian, lon fastest, latitude ascending; missing codes as above.
IMD_TEMP_0P5 = RegularGrid("imd_rt_0p5", 7.5, 67.5, 0.5, 61, 61)
RT_GRIDS: dict[str, RegularGrid] = {"rain": IMD_RAIN_0P25, "tmax": IMD_TEMP_0P5}


def realtime_path(root: Path, var: str, day: pd.Timestamp) -> Path:
    """Where the real-time file of ``var`` for ``day`` is stored."""
    return root / "truth" / "realtime" / var / f"{pd.Timestamp(day):%Y%m%d}.grd"


def read_realtime(path: Path, var: str, day: pd.Timestamp) -> xr.DataArray:
    """One real-time IMD day with missing codes masked."""
    g = RT_GRIDS[var]
    arr = np.fromfile(path, dtype="<f4")
    if arr.size != g.nlat * g.nlon:
        raise ValueError(f"{path}: {arr.size} values, expected {g.nlat * g.nlon}")
    arr = arr.reshape(1, g.nlat, g.nlon).astype(np.float32)
    arr[arr < -100] = np.nan
    if var == "tmax":
        arr[arr >= 60] = np.nan
    return xr.DataArray(
        arr,
        dims=("time", "lat", "lon"),
        coords={"time": [pd.Timestamp(day).normalize()], "lat": g.lats, "lon": g.lons},
    )


def load_realtime(root: Path, var: str, days: pd.DatetimeIndex) -> xr.DataArray | None:
    """Real-time IMD days available locally among ``days`` (None if none)."""
    parts = [
        read_realtime(realtime_path(root, var, d), var, d)
        for d in days
        if realtime_path(root, var, d).exists() and realtime_path(root, var, d).stat().st_size > 0
    ]
    return xr.concat(parts, dim="time") if parts else None


def download_realtime(root: Path, var: str, day: pd.Timestamp) -> Path | None:
    """Fetch one real-time day via imdlib into staging and move it into place (None on failure)."""
    import imdlib

    staging = root / "truth" / "_staging_rt" / var
    staging.mkdir(parents=True, exist_ok=True)
    before = set(staging.glob("*"))
    with contextlib.suppress(Exception):
        imdlib.get_real_data(
            var,
            f"{pd.Timestamp(day):%Y-%m-%d}",
            f"{pd.Timestamp(day):%Y-%m-%d}",
            file_dir=str(staging),
        )
    new = [p for p in staging.rglob("*.grd") if p not in before and p.stat().st_size > 0]
    if not new:
        return None
    dest = realtime_path(root, var, day)
    dest.parent.mkdir(parents=True, exist_ok=True)
    shutil.move(str(new[0]), dest)
    try:
        read_realtime(dest, var, day)
    except ValueError:
        dest.unlink()
        return None
    return dest
