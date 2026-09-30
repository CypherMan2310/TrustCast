"""dynamical.org Zarr datasets (AIFS Single, GFS, GEFS, IFS-ENS, AIFS-ENS) -> ``canonical_v1``.

Conventions verified on 2026-09-30 from dataset attributes:
* ``precipitation_surface``: average rate (kg m-2 s-1 = mm/s) since the previous forecast step
  (``step_type: avg``); amount of step i = rate_i * (lead_i - lead_{i-1}).
* ``temperature_2m``: instantaneous (degC). ``maximum_temperature_2m`` (GFS, GEFS): max since the
  previous step.
* All grids are 0.25 deg global with latitude descending; the IMD 0.25 deg points coincide exactly,
  so regridding is identity selection.
"""

from __future__ import annotations

import datetime as dt
import logging
import time
from typing import ClassVar

import numpy as np
import pandas as pd
import xarray as xr

from trustcast.adapters.base import SourceAdapter, SourceUnavailable
from trustcast.config import AdapterConfig, Config, RegionConfig
from trustcast.grid.align import lead_windows, step_intervals
from trustcast.grid.canonical import IntervalSeries, SampleSeries, build_canonical
from trustcast.grid.imd_grid import RegularGrid
from trustcast.grid.regrid import points_coincide
from trustcast.log import event

log = logging.getLogger(__name__)

LICENCE = "CC BY 4.0, dynamical.org (underlying ECMWF / NOAA open data)"
TRUE_INIT = "true init: all values from the single run initialised at init_time"


class DynamicalAdapter(SourceAdapter):
    """One dynamical.org forecast dataset."""

    _datasets: ClassVar[dict[str, xr.Dataset]] = {}

    def __init__(self, name: str, acfg: AdapterConfig, cfg: Config) -> None:
        if not acfg.dataset:
            raise ValueError(f"{name}: dynamical adapter needs `dataset`")
        self.name, self.acfg, self.cfg = name, acfg, cfg
        self.source = acfg.source
        self.licence = LICENCE
        self.grid = RegularGrid.from_config(cfg.grid)
        self.lead_days = cfg.canonical.lead_days

    def _open(self) -> xr.Dataset:
        ds_id = self.acfg.dataset
        if ds_id not in self._datasets:
            import dynamical_catalog

            try:
                self._datasets[ds_id] = dynamical_catalog.open(ds_id)
            except Exception as e:  # catalogue/network errors of any kind
                raise SourceUnavailable(f"{self.name}: cannot open {ds_id}: {e}") from e
        return self._datasets[ds_id]

    def init_times(self) -> np.ndarray:
        """All init times available in the dataset."""
        return self._open()["init_time"].values

    def fetch(self, init_time: dt.datetime, bbox: RegionConfig) -> xr.Dataset:
        """Canonical dataset for one init."""
        ds = self._open()
        init = np.datetime64(pd.Timestamp(init_time).tz_localize(None), "ns")
        if init not in set(ds["init_time"].values):
            raise SourceUnavailable(f"{self.name}: init {init} not in {self.acfg.dataset}")
        lats, lons = self.grid.region_points(bbox)
        if not (
            points_coincide(ds.latitude.values, lats) and points_coincide(ds.longitude.values, lons)
        ):
            raise SourceUnavailable(f"{self.name}: source grid does not contain the IMD points")
        windows = lead_windows(init, self.lead_days)
        max_lead = (windows[-1][1] - init) / np.timedelta64(1, "h")
        run = ds.sel(init_time=init)
        if "ingested_forecast_length" in run.coords:
            # per member for GEFS; NaT = not recorded (data may still be present -> NaN windows)
            ing = np.atleast_1d(run["ingested_forecast_length"].values)
            ing = ing[~np.isnat(ing)]
            if ing.size and (ing / np.timedelta64(1, "h")).min() < max_lead:
                raise SourceUnavailable(f"{self.name}: run {init} ingested only to {ing.min()}")
        variables = ["precipitation_surface", self.acfg.tmax_var or "temperature_2m"]
        t0 = time.monotonic()
        sel = run[variables]
        if self.acfg.member is not None:  # e.g. IFS-ENS control = member 0
            sel = sel.sel(ensemble_member=self.acfg.member)
        try:
            sub = (
                sel
                # one native step beyond the last window end, so a straddling step is included
                .sel(
                    lead_time=slice(np.timedelta64(0, "h"), np.timedelta64(int(max_lead) + 24, "h"))
                )
                .sel(latitude=lats, longitude=lons, method="nearest", tolerance=1e-6)
                .load()
            )
        except (KeyError, ValueError):
            raise
        except Exception as e:  # remote store / network errors: fail this source, not the run
            raise SourceUnavailable(f"{self.name}: read failed for {init}: {e}") from e
        sub = sub.rename({"latitude": "lat", "longitude": "lon"}).assign_coords(lat=lats, lon=lons)
        members = None
        order = ["lead_time", "lat", "lon"]
        if "ensemble_member" in sub.dims:
            members = sub["ensemble_member"].values
            order = ["lead_time", "ensemble_member", "lat", "lon"]
        leads_h = (sub["lead_time"].values / np.timedelta64(1, "h")).astype(int)
        s, e = step_intervals(init, leads_h)
        dt_s = np.diff(leads_h).astype(float) * 3600.0
        rate = sub["precipitation_surface"].transpose(*order).values
        shape = (-1,) + (1,) * (rate.ndim - 1)
        precip = IntervalSeries(rate[1:] * dt_s.reshape(shape), s, e)
        tvals = sub[variables[1]].transpose(*order).values
        if self.acfg.tmax_var:
            tmax: IntervalSeries | SampleSeries = IntervalSeries(tvals[1:], s, e)
        else:
            times = init + leads_h.astype("timedelta64[h]").astype("timedelta64[ns]")
            tmax = SampleSeries(tvals, times)
        attrs = {
            "source": self.source,
            "adapter": self.name,
            "provider": "dynamical.org",
            "model_version": (
                f"{self.acfg.dataset} (dataset_version {ds.attrs.get('dataset_version', '?')})"
            ),
            "licence": self.licence,
            "fetched_at": dt.datetime.now(dt.UTC).isoformat(),
            "regrid_method": "identity: 0.25 deg source grid contains the IMD points",
            "init_semantics": TRUE_INIT,
            "tmax_method": (
                f"max of {self.acfg.tmax_var} over overlapping steps"
                if self.acfg.tmax_var
                else f"max of instantaneous temperature_2m at native steps "
                f"({int(np.median(np.diff(leads_h)))} h)"
            ),
        }
        out = build_canonical(init, self.lead_days, lats, lons, precip, tmax, attrs, members)
        event(
            log,
            logging.INFO,
            "fetch ok",
            source=self.source,
            adapter=self.name,
            region=bbox.name,
            bbox=[*bbox.lat, *bbox.lon],
            init_time=str(init)[:16],
            duration_s=round(time.monotonic() - t0, 2),
            status="ok",
        )
        return out
