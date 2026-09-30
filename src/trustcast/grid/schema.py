"""Dataset contracts (xarray schemas).

Two schemas exist:

``archive_hourly_v1``
    What the Phase 0 archiver stores: native hourly model output, exactly as delivered,
    at the IMD 0.25 deg points of a pilot region. No accumulation or regridding beyond the
    provider's nearest-cell lookup.

    dims      init_time (UTC), lead_h (0..N-1 hours), lat, lon
    vars      precip_1h_mm  float32  precipitation in the hour ENDING at valid_time
              t2m_c         float32  2 m air temperature at valid_time
    coords    valid_time(init_time, lead_h), model_lat(lat, lon), model_lon(lat, lon)

``canonical_v1`` (Phase 1 target, contract fixed now)
    dims      init_time (UTC), lead_h, lat, lon   on the IMD 0.25 deg grid
    vars      precip_24h_mm  float32  accumulation over the IMD day window
                                      (03:00 UTC -> 03:00 UTC = 08:30 -> 08:30 IST)
              tmax_c         float32  max 2 m temperature over the same window
    lead_h    hours from init_time to the END of the 24 h window (e.g. 00Z init -> 27, 51, ...)

Both carry the attributes in ``REQUIRED_ATTRS``.
"""

from __future__ import annotations

import numpy as np
import xarray as xr

ARCHIVE_SCHEMA = "archive_hourly_v1"
CANONICAL_SCHEMA = "canonical_v1"

REQUIRED_ATTRS = ("schema", "source", "model_version", "licence", "fetched_at", "regrid_method")
DIMS = ("init_time", "lead_h", "lat", "lon")

ARCHIVE_VARS = {"precip_1h_mm": (-0.001, 1000.0), "t2m_c": (-90.0, 65.0)}
CANONICAL_VARS = {"precip_24h_mm": (-0.001, 5000.0), "tmax_c": (-90.0, 65.0)}

# IMD rain day ends at 08:30 IST = 03:00 UTC
IMD_DAY_END_UTC_HOUR = 3


class SchemaError(ValueError):
    """A dataset does not satisfy its contract."""


def _check(ds: xr.Dataset, schema: str, variables: dict[str, tuple[float, float]]) -> None:
    problems: list[str] = []
    if ds.attrs.get("schema") != schema:
        problems.append(f"attrs.schema={ds.attrs.get('schema')!r}, expected {schema!r}")
    problems += [f"missing attr {a!r}" for a in REQUIRED_ATTRS if not ds.attrs.get(a)]
    for v, (lo, hi) in variables.items():
        if v not in ds.data_vars:
            problems.append(f"missing variable {v!r}")
            continue
        da = ds[v]
        if tuple(da.dims) != DIMS:
            problems.append(f"{v} dims {da.dims} != {DIMS}")
        if da.dtype != np.float32:
            problems.append(f"{v} dtype {da.dtype} != float32")
        vals = da.values
        finite = vals[np.isfinite(vals)]
        if finite.size and (finite.min() < lo or finite.max() > hi):
            problems.append(
                f"{v} outside plausible range [{lo}, {hi}]: {finite.min():.3f}..{finite.max():.3f}"
            )
    for d in DIMS:
        if d not in ds.coords:
            problems.append(f"missing coordinate {d!r}")
    if "init_time" in ds.coords and not np.issubdtype(ds["init_time"].dtype, np.datetime64):
        problems.append("init_time is not datetime64")
    for c in ("lat", "lon"):
        if c in ds.coords and ds[c].size > 1 and not np.all(np.diff(ds[c].values) > 0):
            problems.append(f"{c} not strictly ascending")
    if problems:
        raise SchemaError(f"{schema}: " + "; ".join(problems))


def validate_archive(ds: xr.Dataset) -> None:
    """Raise :class:`SchemaError` unless ``ds`` satisfies ``archive_hourly_v1``."""
    _check(ds, ARCHIVE_SCHEMA, ARCHIVE_VARS)
    if "valid_time" not in ds.coords:
        raise SchemaError(f"{ARCHIVE_SCHEMA}: missing coordinate 'valid_time'")


def validate_canonical(ds: xr.Dataset) -> None:
    """Raise :class:`SchemaError` unless ``ds`` satisfies ``canonical_v1``."""
    _check(ds, CANONICAL_SCHEMA, CANONICAL_VARS)
