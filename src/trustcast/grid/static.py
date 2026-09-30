"""Static cell features for gating: elevation, slope and distance to the coast.

Elevation comes from the ``elevation`` field that Open-Meteo returns for every requested point
(Copernicus DEM GLO-90, per Open-Meteo documentation), read from our own archived raw responses,
so no extra request is needed. Slope is the magnitude of the elevation gradient on the 0.25 deg
grid (m/km).
Distance to coast is the great-circle distance (km) to the nearest cell without IMD land data.
"""

from __future__ import annotations

import gzip
import json
from pathlib import Path

import numpy as np
import xarray as xr

from trustcast.config import Config
from trustcast.grid.imd_grid import IMD_RAIN_0P25, flatten_points

_KM_PER_DEG = 111.2


def elevation_from_archive(
    root: Path, region: str, lats: np.ndarray, lons: np.ndarray
) -> np.ndarray:
    """(lat, lon) elevation in metres from the first archived IFS raw response of the region."""
    files = sorted((root / "raw" / "openmeteo" / "ecmwf_ifs" / region).glob("*.json.gz"))
    if not files:
        raise FileNotFoundError(
            f"no archived raw responses for {region}; run scripts/archive_run.py"
        )
    with gzip.open(files[0], "rb") as f:
        payload = json.loads(f.read())
    locs = [loc for b in payload["batches"] for loc in b["response"]]
    if len(locs) != flatten_points(lats, lons)[0].size:
        raise ValueError("archived response does not match the region grid")
    return np.array([float(loc.get("elevation", np.nan)) for loc in locs]).reshape(
        lats.size, lons.size
    )


def static_features(cfg: Config, root: Path, region: str, land: np.ndarray) -> xr.Dataset:
    """Elevation, slope and distance to coast on the region's IMD points (cached)."""
    cache = root / "processed" / "static" / f"{region}.nc"
    if cache.exists():
        return xr.open_dataset(cache).load()
    lats, lons = IMD_RAIN_0P25.region_points(cfg.regions[region])
    elev = elevation_from_archive(root, region, lats, lons)
    dy = 0.25 * _KM_PER_DEG
    dx = 0.25 * _KM_PER_DEG * np.cos(np.deg2rad(lats))[:, None]
    gy, gx = np.gradient(elev)
    slope = np.hypot(gy / dy, gx / dx)
    la, lo = np.meshgrid(lats, lons, indexing="ij")
    sea = ~land
    if sea.any():
        sl, so = np.deg2rad(la[sea]), np.deg2rad(lo[sea])
        p1, p2 = np.deg2rad(la.ravel())[:, None], np.deg2rad(lo.ravel())[:, None]
        a = np.sin((sl - p1) / 2) ** 2 + np.cos(p1) * np.cos(sl) * np.sin((so - p2) / 2) ** 2
        dist = (2 * 6371 * np.arcsin(np.sqrt(a))).min(axis=1).reshape(la.shape)
    else:
        dist = np.full(la.shape, 999.0)
    ds = xr.Dataset(
        {
            "elevation_m": (("lat", "lon"), elev),
            "slope_m_per_km": (("lat", "lon"), slope),
            "dist_coast_km": (("lat", "lon"), dist),
        },
        coords={"lat": lats, "lon": lons},
        attrs={"elevation_source": "Open-Meteo point elevation (Copernicus DEM GLO-90)"},
    )
    cache.parent.mkdir(parents=True, exist_ok=True)
    ds.to_netcdf(cache)
    return ds
