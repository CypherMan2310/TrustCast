"""Open-Meteo Single Runs client (used by the Phase 0 archiver).

Endpoints were verified against live requests on 2026-09-30 (see DATA_SOURCES.md):

* ``https://single-runs-api.open-meteo.com/v1/forecast?...&models=<id>&run=<ISO init>``
  returns one run by init time; with ``forecast_hours=N`` the hourly axis starts at init.
* ``https://api.open-meteo.com/data/<meta_id>/static/meta.json`` gives
  ``last_run_initialisation_time`` (unix seconds) for staleness checks.

Fair use (free tier): 600 calls/min, 5000/h, 10000/day, each location counting as one
call. Requests are throttled with :class:`RollingLimiter` and every fetch is logged.
"""

from __future__ import annotations

import datetime as dt
import logging
import time
from collections.abc import Callable
from typing import Any

import httpx
import numpy as np
import pandas as pd
import xarray as xr

from trustcast.adapters.base import SourceUnavailable
from trustcast.adapters.ratelimit import BudgetExhausted, RollingLimiter
from trustcast.config import OpenMeteoConfig, OpenMeteoSource
from trustcast.grid.imd_grid import flatten_points
from trustcast.grid.schema import ARCHIVE_SCHEMA
from trustcast.log import event

log = logging.getLogger(__name__)

PROVIDER = "open-meteo single-runs"
LICENCE = "CC BY 4.0, Open-Meteo.com (underlying ECMWF/NOAA/DWD/ECCC open data)"
REGRID_METHOD = (
    "none: provider nearest model grid cell (cell_selection=nearest) at IMD 0.25 deg points"
)
VAR_MAP = {"precipitation": "precip_1h_mm", "temperature_2m": "t2m_c"}
MAX_POINT_OFFSET_DEG = 0.5
HTTP_HEADERS = {"User-Agent": "trustcast-archiver/0.0.1 (SIH26081 research; non-commercial)"}


def _to_utc_naive(t: dt.datetime) -> dt.datetime:
    return t.astimezone(dt.UTC).replace(tzinfo=None) if t.tzinfo else t


def responses_to_dataset(
    locations: list[dict[str, Any]],
    lats: np.ndarray,
    lons: np.ndarray,
    init_time: dt.datetime,
    forecast_hours: int,
    variables: list[str],
    attrs: dict[str, str],
) -> xr.Dataset:
    """Convert Open-Meteo per-location JSON objects into an ``archive_hourly_v1`` dataset.

    ``locations`` must be in the row-major order of :func:`flatten_points`.
    Raises :class:`SourceUnavailable` on count mismatch, misplaced points, or a variable
    that is entirely missing (null) for the whole request.
    """
    req_lat, req_lon = flatten_points(lats, lons)
    if len(locations) != req_lat.size:
        raise SourceUnavailable(f"expected {req_lat.size} locations, got {len(locations)}")
    init = pd.Timestamp(_to_utc_naive(init_time))
    shape = (1, forecast_hours, lats.size, lons.size)
    out = {VAR_MAP[v]: np.full(shape, np.nan, dtype=np.float32) for v in variables}
    model_lat = np.full(req_lat.size, np.nan)
    model_lon = np.full(req_lat.size, np.nan)

    for k, loc in enumerate(locations):
        mlat, mlon = float(loc["latitude"]), float(loc["longitude"])
        off = max(abs(mlat - req_lat[k]), abs(mlon - req_lon[k]))
        if off > MAX_POINT_OFFSET_DEG:
            raise SourceUnavailable(
                f"location {k}: model cell ({mlat},{mlon}) too far from ({req_lat[k]},{req_lon[k]})"
            )
        model_lat[k], model_lon[k] = mlat, mlon
        hourly = loc["hourly"]
        lead = (pd.to_datetime(hourly["time"]) - init) / pd.Timedelta(hours=1)
        lead = np.asarray(lead, dtype=float)
        ok = (lead >= 0) & (lead < forecast_hours) & (lead == np.round(lead))
        li = lead[ok].astype(int)
        i, j = divmod(k, lons.size)
        for v in variables:
            vals = np.array([np.nan if x is None else x for x in hourly[v]], dtype=np.float32)
            out[VAR_MAP[v]][0, li, i, j] = vals[ok]

    for name, arr in out.items():
        if np.isnan(arr).all():
            raise SourceUnavailable(f"variable {name} is entirely missing in the response")

    valid = init + pd.to_timedelta(np.arange(forecast_hours), unit="h")
    ds = xr.Dataset(
        {name: (("init_time", "lead_h", "lat", "lon"), arr) for name, arr in out.items()},
        coords={
            "init_time": [init.to_datetime64()],
            "lead_h": np.arange(forecast_hours, dtype=np.int16),
            "lat": lats.astype(np.float64),
            "lon": lons.astype(np.float64),
            "valid_time": (("init_time", "lead_h"), valid.values[None, :]),
            "model_lat": (("lat", "lon"), model_lat.reshape(lats.size, lons.size)),
            "model_lon": (("lat", "lon"), model_lon.reshape(lats.size, lons.size)),
        },
        attrs={"schema": ARCHIVE_SCHEMA, **attrs},
    )
    ds["precip_1h_mm"].attrs = {
        "units": "mm",
        "long_name": "precipitation in hour ending at valid_time",
    }
    ds["t2m_c"].attrs = {"units": "degC", "long_name": "2 m air temperature"}
    return ds


class OpenMeteoSingleRuns:
    """Fetch complete runs by init time for a set of grid points."""

    def __init__(
        self,
        cfg: OpenMeteoConfig,
        forecast_hours: int,
        variables: list[str],
        client: httpx.Client | None = None,
        limiter: RollingLimiter | None = None,
        hourly_limiter: RollingLimiter | None = None,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        self.cfg = cfg
        self.forecast_hours = forecast_hours
        self.variables = variables
        self.client = client or httpx.Client(timeout=cfg.timeout_s, headers=HTTP_HEADERS)
        self.limiter = limiter or RollingLimiter(cfg.max_locations_per_minute, 60.0)
        self.hourly_limiter = hourly_limiter or RollingLimiter(
            cfg.max_locations_per_hour, 3600.0, blocking=False
        )
        self.sleep = sleep

    def latest_init(self, src: OpenMeteoSource) -> dt.datetime:
        """Newest init time the provider reports for ``src`` (UTC, naive)."""
        url = self.cfg.meta_url.format(meta_id=src.meta_id)
        try:
            r = self.client.get(url)
            r.raise_for_status()
            ts = r.json()["last_run_initialisation_time"]
        except (httpx.HTTPError, KeyError, ValueError) as e:
            raise SourceUnavailable(f"{src.source}: metadata unavailable ({e})") from e
        return dt.datetime.fromtimestamp(ts, dt.UTC).replace(tzinfo=None)

    def _get(self, params: dict[str, Any], units: int) -> list[dict[str, Any]]:
        last_err = "unknown"
        for attempt in range(self.cfg.retries + 1):
            try:
                self.hourly_limiter.acquire(units)
            except BudgetExhausted as e:
                raise SourceUnavailable(
                    f"local hourly budget exhausted, retry next run: {e}"
                ) from e
            self.limiter.acquire(units)
            try:
                r = self.client.get(self.cfg.single_runs_url, params=params)
            except httpx.HTTPError as e:
                last_err = f"{type(e).__name__}: {e}"
                self.sleep(10 * (attempt + 1))
                continue
            if r.status_code == 429:
                reason = r.text[:200]
                if "Minutely" not in reason:  # hourly/daily quota: waiting will not help
                    raise SourceUnavailable(f"HTTP 429 quota exceeded: {reason}")
                last_err = f"HTTP 429: {reason}"
                self.sleep(65)
                continue
            if r.status_code >= 500:
                last_err = f"HTTP {r.status_code}"
                self.sleep(15 * (attempt + 1))
                continue
            if r.status_code >= 400:
                raise SourceUnavailable(f"HTTP {r.status_code}: {r.text[:300]}")
            if not r.content.strip():
                raise SourceUnavailable("HTTP 200 with empty body (run not available)")
            data = r.json()
            return data if isinstance(data, list) else [data]
        raise SourceUnavailable(f"gave up after {self.cfg.retries + 1} attempts: {last_err}")

    def fetch_run(
        self,
        src: OpenMeteoSource,
        init_time: dt.datetime,
        lats: np.ndarray,
        lons: np.ndarray,
        region: str,
    ) -> tuple[dict[str, Any], xr.Dataset]:
        """Fetch one run for all points; return (raw payload, archive dataset)."""
        init = _to_utc_naive(init_time)
        req_lat, req_lon = flatten_points(lats, lons)
        n = self.cfg.max_locations_per_request
        batches: list[dict[str, Any]] = []
        locations: list[dict[str, Any]] = []
        t0 = time.monotonic()
        fetched_at = dt.datetime.now(dt.UTC)
        try:
            for s in range(0, req_lat.size, n):
                params = {
                    "latitude": ",".join(f"{x:.2f}" for x in req_lat[s : s + n]),
                    "longitude": ",".join(f"{x:.2f}" for x in req_lon[s : s + n]),
                    "hourly": ",".join(self.variables),
                    "models": src.model,
                    "run": init.strftime("%Y-%m-%dT%H:%M"),
                    "forecast_hours": self.forecast_hours,
                    "cell_selection": "nearest",
                    "timezone": "UTC",
                }
                resp = self._get(params, units=min(n, req_lat.size - s))
                batches.append({"params": params, "response": resp})
                locations.extend(resp)
            attrs = {
                "source": src.source,
                "provider": PROVIDER,
                "model_id": src.model,
                "model_version": f"open-meteo:{src.model} (provider does not expose model cycle)",
                "licence": LICENCE,
                "fetched_at": fetched_at.isoformat(),
                "regrid_method": REGRID_METHOD,
                "region": region,
                "init_time": init.isoformat(),
            }
            ds = responses_to_dataset(
                locations, lats, lons, init, self.forecast_hours, self.variables, attrs
            )
        except SourceUnavailable as e:
            event(
                log,
                logging.ERROR,
                "fetch failed",
                source=src.source,
                region=region,
                bbox=[float(lats[0]), float(lats[-1]), float(lons[0]), float(lons[-1])],
                init_time=init.isoformat(),
                duration_s=round(time.monotonic() - t0, 2),
                status="failed",
                error=str(e),
            )
            raise
        event(
            log,
            logging.INFO,
            "fetch ok",
            source=src.source,
            region=region,
            bbox=[float(lats[0]), float(lats[-1]), float(lons[0]), float(lons[-1])],
            init_time=init.isoformat(),
            duration_s=round(time.monotonic() - t0, 2),
            status="ok",
            n_points=int(req_lat.size),
            n_requests=len(batches),
        )
        raw = {
            "provider": PROVIDER,
            "source": src.source,
            "model": src.model,
            "init_time": init.isoformat(),
            "fetched_at": fetched_at.isoformat(),
            "url": self.cfg.single_runs_url,
            "batches": batches,
        }
        return raw, ds
