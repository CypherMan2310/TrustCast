"""ECMWF open data (IFS HRES 0.25 deg GRIB2) fallback adapter.

Verified 2026-09-30: ``ecmwf-opendata`` retrieves the latest few days of runs; ``tp`` is
precipitation accumulated from init (m), so IMD-window totals are exact differences at 03 UTC
boundary steps;
``mx2t3`` is the 2 m maximum temperature over the preceding 3 h (K). Licence CC BY 4.0 (attribute
ECMWF). GRIB files are kept under ``data/raw/ecmwf_opendata/<init>/`` (immutable).
"""

from __future__ import annotations

import datetime as dt
import logging
import time
from pathlib import Path

import numpy as np
import pandas as pd
import xarray as xr

from trustcast.adapters.base import SourceAdapter, SourceUnavailable
from trustcast.config import AdapterConfig, Config, RegionConfig
from trustcast.grid.align import lead_windows
from trustcast.grid.canonical import IntervalSeries, build_canonical
from trustcast.grid.imd_grid import RegularGrid
from trustcast.log import event

log = logging.getLogger(__name__)
LICENCE = "CC BY 4.0, ECMWF open data"


class EcmwfOpenDataAdapter(SourceAdapter):
    """IFS HRES from ECMWF open data (recent runs only)."""

    def __init__(self, name: str, acfg: AdapterConfig, cfg: Config, root: Path) -> None:
        self.name, self.acfg, self.cfg, self.root = name, acfg, cfg, root
        self.source = acfg.source
        self.licence = LICENCE
        self.grid = RegularGrid.from_config(cfg.grid)
        self.lead_days = cfg.canonical.lead_days

    def _retrieve(self, init: pd.Timestamp, param: str, steps: list[int]) -> Path:
        target = self.root / "raw" / "ecmwf_opendata" / f"{init:%Y%m%dT%H}" / f"{param}.grib2"
        if target.exists() and target.stat().st_size > 0:
            return target
        from ecmwf.opendata import Client

        target.parent.mkdir(parents=True, exist_ok=True)
        tmp = target.with_suffix(".part")
        try:
            Client(source="ecmwf", model="ifs", resol="0p25").retrieve(
                date=init.strftime("%Y%m%d"),
                time=init.hour,
                type="fc",
                stream="oper",
                step=steps,
                param=[param],
                target=str(tmp),
            )
        except Exception as e:  # client raises plain exceptions for missing runs
            tmp.unlink(missing_ok=True)
            raise SourceUnavailable(f"{self.name}: {param} {init} unavailable: {e}") from e
        tmp.rename(target)
        return target

    def _open(self, path: Path, lats: np.ndarray, lons: np.ndarray) -> xr.DataArray:
        ds = xr.open_dataset(path, engine="cfgrib", indexpath="")
        da = ds[next(iter(ds.data_vars))]
        da = da.sel(latitude=lats, longitude=lons, method="nearest", tolerance=1e-6).load()
        return da.rename({"latitude": "lat", "longitude": "lon"}).assign_coords(lat=lats, lon=lons)

    def fetch(self, init_time: dt.datetime, bbox: RegionConfig) -> xr.Dataset:
        """Canonical dataset for one recent 00Z/12Z run."""
        init = pd.Timestamp(init_time).tz_localize(None)
        lats, lons = self.grid.region_points(bbox)
        windows = lead_windows(init.to_datetime64(), self.lead_days)
        hours = lambda t: int((t - init.to_datetime64()) / np.timedelta64(1, "h"))  # noqa: E731
        bounds = sorted({hours(w0) for w0, _ in windows} | {hours(w1) for _, w1 in windows})
        if any(b % 3 for b in bounds):
            raise SourceUnavailable(f"{self.name}: window boundaries {bounds} not on 3 h steps")
        t0 = time.monotonic()
        tp = self._open(self._retrieve(init, "tp", bounds), lats, lons)
        mx_steps = list(range(bounds[0] + 3, bounds[-1] + 1, 3))
        mx = self._open(self._retrieve(init, "mx2t3", mx_steps), lats, lons)

        tp_h = (tp["step"].values / np.timedelta64(1, "h")).astype(int)
        acc = tp.values * 1000.0  # m -> mm, accumulated from init
        base = init.to_datetime64().astype("datetime64[ns]")
        to_t = lambda h: base + np.timedelta64(int(h), "h")  # noqa: E731
        precip = IntervalSeries(
            np.diff(acc, axis=0),
            np.array([to_t(h) for h in tp_h[:-1]]),
            np.array([to_t(h) for h in tp_h[1:]]),
        )
        mx_h = (mx["step"].values / np.timedelta64(1, "h")).astype(int)
        tmax = IntervalSeries(
            mx.values - 273.15,
            np.array([to_t(h - 3) for h in mx_h]),
            np.array([to_t(h) for h in mx_h]),
        )
        attrs = {
            "source": self.source,
            "adapter": self.name,
            "provider": "ECMWF open data",
            "model_version": "IFS HRES oper 0.25 deg (open data)",
            "licence": self.licence,
            "fetched_at": dt.datetime.now(dt.UTC).isoformat(),
            "regrid_method": "identity: 0.25 deg source grid contains the IMD points",
            "init_semantics": "true init: all values from the single run initialised at init_time",
            "tmax_method": "max of mx2t3 (3-hourly maxima) over the window",
        }
        out = build_canonical(init, self.lead_days, lats, lons, precip, tmax, attrs)
        event(
            log,
            logging.INFO,
            "fetch ok",
            source=self.source,
            adapter=self.name,
            region=bbox.name,
            init_time=str(init),
            duration_s=round(time.monotonic() - t0, 2),
            status="ok",
        )
        return out
