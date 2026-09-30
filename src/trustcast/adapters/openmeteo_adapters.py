"""Open-Meteo adapters producing ``canonical_v1``.

Previous Runs (evaluation history, Jan 2024 -> today)
    ``<var>_previous_day{k}`` at valid hour t comes from the run initialised at
    floor_6h(t) - k days (verified 2026-09-30 by matching 20 locations against Single Runs, see
    WORK.md). For a nominal 00Z init I, lead day k (window ending I + k days 03Z) is built from
    ``previous_day{k}``; every run used is initialised in [I - 1 day, I], so nothing after I is
    used. The effective lead of each hour is 24k..24k+5 h, i.e. a mix of four runs per day, not a
    single forecast. This is recorded in the ``init_semantics`` attribute.

Single Runs (live, true init; rolling ~180-day provider retention)
    Reads the run from our own archive (``archive_hourly_v1``), fetching and archiving it first
    if needed, then aggregates to IMD-day windows.

Live
    The newest 00/12Z run only, served via Single Runs, because /v1/forecast does not say which
    init it returned.
"""

from __future__ import annotations

import datetime as dt
import gzip
import json
import logging
import math
import time
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
import xarray as xr

from trustcast.adapters.base import SourceAdapter, SourceUnavailable
from trustcast.adapters.openmeteo import (
    LICENCE,
    MAX_POINT_OFFSET_DEG,
    OpenMeteoSingleRuns,
    _to_utc_naive,
)
from trustcast.archive.cycles import floor_cycle
from trustcast.archive.manifest import write_raw
from trustcast.archive.runner import ArchivePaths, archive_one
from trustcast.config import AdapterConfig, Config, RegionConfig
from trustcast.grid.align import hourly_intervals
from trustcast.grid.canonical import IntervalSeries, SampleSeries, build_canonical
from trustcast.grid.imd_grid import RegularGrid, flatten_points
from trustcast.log import event

log = logging.getLogger(__name__)

PREV_VARS = ("precipitation", "temperature_2m")
PREV_SEMANTICS = (
    "nominal init: lead day k uses Open-Meteo previous_day{k}; value at hour t comes from the run "
    "initialised floor_6h(t) - k days; all runs used are initialised in [init - 1 day, init]; "
    "effective lead 24k..24k+5 h (mix of 00/06/12/18Z runs)"
)
TRUE_INIT = "true init: all values from the single run initialised at init_time"


def previous_runs_run_time(valid_hour: pd.Timestamp, k: int) -> pd.Timestamp:
    """Init time of the run supplying ``previous_day{k}`` at ``valid_hour`` (verified mapping)."""
    return pd.Timestamp(valid_hour).floor("6h") - pd.Timedelta(days=k)


def _half_month_blocks(dates: list[pd.Timestamp]) -> list[tuple[pd.Timestamp, pd.Timestamp]]:
    """Fixed cache blocks: days 1-14 and 15-end of each month, covering ``dates``."""
    blocks = set()
    for d in dates:
        d = pd.Timestamp(d).normalize()
        if d.day <= 14:
            blocks.add((d.replace(day=1), d.replace(day=14)))
        else:
            blocks.add((d.replace(day=15), d + pd.offsets.MonthEnd(0)))
    return sorted(blocks)


def locations_to_arrays(
    locations: list[dict[str, Any]],
    lats: np.ndarray,
    lons: np.ndarray,
    keys: list[str],
    points: np.ndarray | None = None,
) -> tuple[np.ndarray, dict[str, np.ndarray]]:
    """Per-location JSON -> (times, {key: array(time, lat, lon)}). Nulls become NaN.

    ``points`` = flat row-major indices of the requested grid points (default: all). Grid points
    that were not requested stay NaN.
    """
    all_lat, all_lon = flatten_points(lats, lons)
    points = np.arange(all_lat.size) if points is None else np.asarray(points)
    req_lat, req_lon = all_lat[points], all_lon[points]
    if len(locations) != req_lat.size:
        raise SourceUnavailable(f"expected {req_lat.size} locations, got {len(locations)}")
    times = pd.to_datetime(locations[0]["hourly"]["time"]).values
    out = {k: np.full((times.size, lats.size, lons.size), np.nan, np.float32) for k in keys}
    for n, loc in enumerate(locations):
        off = max(abs(loc["latitude"] - req_lat[n]), abs(loc["longitude"] - req_lon[n]))
        if off > MAX_POINT_OFFSET_DEG:
            raise SourceUnavailable(f"location {n} is {off:.2f} deg from the requested point")
        if loc["hourly"]["time"] != locations[0]["hourly"]["time"]:
            raise SourceUnavailable(f"location {n} has a different time axis")
        i, j = divmod(int(points[n]), lons.size)
        for k in keys:
            out[k][:, i, j] = np.array(
                [np.nan if x is None else x for x in loc["hourly"][k]], np.float32
            )
    return times, out


class OpenMeteoPreviousRunsAdapter(SourceAdapter):
    """Lead-stratified history from the Previous Runs API (see module docstring)."""

    def __init__(
        self, name: str, acfg: AdapterConfig, cfg: Config, client: OpenMeteoSingleRuns, root: Path
    ) -> None:
        if not acfg.model or not cfg.previous_runs:
            raise ValueError(f"{name}: previous-runs adapter needs `model` and `previous_runs.url`")
        self.name, self.acfg, self.cfg, self.client, self.root = name, acfg, cfg, client, root
        self.source = acfg.source
        self.licence = LICENCE
        self.lead_days = cfg.canonical.lead_days
        self.keys = [
            f"{v}_previous_day{k}" for v in PREV_VARS for k in range(1, self.lead_days + 1)
        ]
        self.grid = RegularGrid.from_config(cfg.grid)
        self.land_only = cfg.previous_runs.land_only
        self._points: dict[str, np.ndarray] = {}

    def points(self, bbox: RegionConfig) -> np.ndarray | None:
        """Flat indices of the grid points to request (IMD land cells if ``land_only``)."""
        if not self.land_only:
            return None
        if bbox.name not in self._points:
            from trustcast.truth.build import imd_land_mask

            mask = imd_land_mask(self.root, bbox).values
            self._points[bbox.name] = np.flatnonzero(mask.ravel())
        return self._points[bbox.name]

    def _cache_path(self, region: str, b0: pd.Timestamp) -> Path:
        tag = ("a" if b0.day == 1 else "b") + ("_land" if self.land_only else "")
        return (
            self.root
            / "raw"
            / "openmeteo_prev"
            / self.acfg.model
            / region
            / f"{b0:%Y%m}{tag}_L{self.lead_days}.json.gz"
        )

    def _fetch_block(
        self, bbox: RegionConfig, b0: pd.Timestamp, b1: pd.Timestamp
    ) -> tuple[np.ndarray, dict[str, np.ndarray], str]:
        lats, lons = self.grid.region_points(bbox)
        today = pd.Timestamp.now(tz="UTC").tz_localize(None).normalize()
        cacheable = b1 <= today - pd.Timedelta(days=self.lead_days + 2)
        path = self._cache_path(bbox.name or "adhoc", b0)
        pts = self.points(bbox)
        if cacheable and path.exists():
            with gzip.open(path, "rb") as f:
                payload = json.loads(f.read())
        else:
            req_lat, req_lon = flatten_points(lats, lons)
            if pts is not None:
                req_lat, req_lon = req_lat[pts], req_lon[pts]
            n = self.cfg.openmeteo.max_locations_per_request
            ndays = (b1 - b0).days + 1
            weight = max(1.0, len(self.keys) / 10) * max(1.0, ndays / 14)
            t0 = time.monotonic()
            batches = []
            for s in range(0, req_lat.size, n):
                params = {
                    "latitude": ",".join(f"{x:.2f}" for x in req_lat[s : s + n]),
                    "longitude": ",".join(f"{x:.2f}" for x in req_lon[s : s + n]),
                    "hourly": ",".join(self.keys),
                    "models": self.acfg.model,
                    "start_date": f"{b0:%Y-%m-%d}",
                    "end_date": f"{b1:%Y-%m-%d}",
                    "cell_selection": "nearest",
                    "timezone": "UTC",
                }
                units = math.ceil(min(n, req_lat.size - s) * weight)
                batches.append(
                    {
                        "params": params,
                        "response": self.client._get(params, units, self.cfg.previous_runs.url),
                    }
                )
            payload = {
                "provider": "open-meteo previous-runs",
                "model": self.acfg.model,
                "fetched_at": dt.datetime.now(dt.UTC).isoformat(),
                "url": self.cfg.previous_runs.url,
                "batches": batches,
                "points": None if pts is None else pts.tolist(),
            }
            event(
                log,
                logging.INFO,
                "fetch ok",
                source=self.source,
                adapter=self.name,
                region=bbox.name,
                bbox=[*bbox.lat, *bbox.lon],
                block=f"{b0:%Y-%m-%d}..{b1:%Y-%m-%d}",
                duration_s=round(time.monotonic() - t0, 2),
                status="ok",
                cached=False,
            )
            if cacheable:
                write_raw(payload, path)
        locations = [loc for b in payload["batches"] for loc in b["response"]]
        used = payload.get("points")  # points the block was fetched for
        used = None if used is None else np.asarray(used, dtype=int)
        times, arrays = locations_to_arrays(locations, lats, lons, self.keys, used)
        return times, arrays, payload["fetched_at"]

    def fetch_many(self, inits: list[dt.datetime], bbox: RegionConfig) -> xr.Dataset:
        """Canonical dataset for several nominal inits (00Z), sharing cached blocks."""
        inits = sorted(pd.Timestamp(_to_utc_naive(pd.Timestamp(i).to_pydatetime())) for i in inits)
        for i in inits:
            if i.hour != 0 or i.minute:
                raise ValueError(f"previous-runs adapter supports 00Z nominal inits only, got {i}")
        dates = [i + pd.Timedelta(days=d) for i in inits for d in range(self.lead_days + 1)]
        parts, fetched = [], []
        for b0, b1 in _half_month_blocks(dates):
            parts.append(self._fetch_block(bbox, b0, b1))
            fetched.append(parts[-1][2])
        times = np.concatenate([p[0] for p in parts])
        arrays = {k: np.concatenate([p[1][k] for p in parts]) for k in self.keys}
        order = np.argsort(times)
        times = times[order]
        arrays = {k: v[order] for k, v in arrays.items()}
        lats, lons = self.grid.region_points(bbox)
        s, e = hourly_intervals(times)
        attrs = {
            "source": self.source,
            "adapter": self.name,
            "provider": "open-meteo previous-runs",
            "model_version": f"open-meteo:{self.acfg.model} (provider does not expose model cycle)",
            "licence": self.licence,
            "fetched_at": min(fetched),
            "regrid_method": (
                "provider nearest model cell (cell_selection=nearest) at IMD 0.25 deg points"
            ),
            "init_semantics": PREV_SEMANTICS,
        }
        out = []
        for init in inits:
            p = [
                IntervalSeries(arrays[f"precipitation_previous_day{k}"], s, e)
                for k in range(1, self.lead_days + 1)
            ]
            t = [
                SampleSeries(arrays[f"temperature_2m_previous_day{k}"], times)
                for k in range(1, self.lead_days + 1)
            ]
            out.append(build_canonical(init, self.lead_days, lats, lons, p, t, attrs))
        return xr.concat(out, dim="init_time", combine_attrs="override")

    def fetch(self, init_time: dt.datetime, bbox: RegionConfig) -> xr.Dataset:
        """Canonical dataset for one nominal 00Z init."""
        return self.fetch_many([init_time], bbox)


def archive_to_canonical(ds: xr.Dataset, lead_days: int, adapter: str) -> xr.Dataset:
    """Aggregate an ``archive_hourly_v1`` run into ``canonical_v1``."""
    init = ds["init_time"].values[0]
    valid = ds["valid_time"].values[0]
    s, e = hourly_intervals(valid)
    p = ds["precip_1h_mm"].values[0]
    t = ds["t2m_c"].values[0]
    attrs = {
        k: ds.attrs[k]
        for k in ("source", "provider", "model_version", "licence", "fetched_at", "regrid_method")
    }
    attrs.update(adapter=adapter, init_semantics=TRUE_INIT)
    return build_canonical(
        init,
        lead_days,
        ds.lat.values,
        ds.lon.values,
        IntervalSeries(p, s, e),
        SampleSeries(t, valid),
        attrs,
    )


class OpenMeteoSingleRunsAdapter(SourceAdapter):
    """True-init runs via our archive (fetching and archiving on demand)."""

    def __init__(
        self, name: str, acfg: AdapterConfig, cfg: Config, client: OpenMeteoSingleRuns, root: Path
    ) -> None:
        if not acfg.archive_source:
            raise ValueError(f"{name}: needs `archive_source`")
        self.name, self.acfg, self.cfg, self.client = name, acfg, cfg, client
        self.paths = ArchivePaths(root)
        self.source = acfg.source
        self.licence = LICENCE

    def fetch(self, init_time: dt.datetime, bbox: RegionConfig) -> xr.Dataset:
        """Canonical dataset for one true init (00Z or 12Z)."""
        if not bbox.name or bbox.name not in self.cfg.regions:
            raise ValueError("single-runs adapter needs a configured region (archive key)")
        init = _to_utc_naive(pd.Timestamp(init_time).to_pydatetime())
        res = archive_one(
            self.client, self.cfg, self.paths, self.acfg.archive_source, bbox.name, init
        )
        if res.status not in ("ok", "exists"):
            raise SourceUnavailable(f"{self.name}: {res.detail}")
        with xr.open_zarr(
            self.paths.zarr(self.acfg.archive_source, bbox.name, init), consolidated=False
        ) as ds:
            return archive_to_canonical(ds.load(), self.cfg.canonical.lead_days, self.name)


class OpenMeteoLiveAdapter(OpenMeteoSingleRunsAdapter):
    """Only the newest available 00/12Z run of the source."""

    def latest_cycle(self) -> dt.datetime:
        """Newest 00/12Z cycle the provider has published."""
        src = next(s for s in self.cfg.openmeteo.sources if s.source == self.acfg.archive_source)
        return floor_cycle(self.client.latest_init(src), self.cfg.archiver.cycles_utc)

    def fetch(self, init_time: dt.datetime, bbox: RegionConfig) -> xr.Dataset:
        latest = self.latest_cycle()
        if _to_utc_naive(pd.Timestamp(init_time).to_pydatetime()) != latest:
            raise SourceUnavailable(
                f"{self.name}: live adapter serves only the latest run {latest}"
            )
        return super().fetch(latest, bbox)
