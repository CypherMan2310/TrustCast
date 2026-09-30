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

``canonical_v1`` (Phase 1)
    dims      init_time (UTC), lead_h, lat, lon   on the IMD 0.25 deg grid
              ensemble sources: init_time, member, lead_h, lat, lon
    vars      precip_24h_mm  float32  accumulation over the IMD day window
                                      (03:00 UTC -> 03:00 UTC = 08:30 -> 08:30 IST)
              tmax_c         float32  max 2 m temperature over the same window
    lead_h    hours from init_time to the END of the 24 h window (e.g. 00Z init -> 27, 51, ...)
    coords    valid_day(init_time, lead_h): IMD day label of the window (date at window end)
    attrs     REQUIRED_ATTRS + ``init_semantics`` (how init_time relates to the runs used)

``truth_v1`` (Phase 1)
    dims      time (IMD day label, 00:00 of the day), lat, lon   on the IMD 0.25 deg grid
    vars      rain_mm float32 (24 h ending 03 UTC on ``time``), tmax_c float32,
              provisional bool(time): rain for that day is satellite (IMERG), not IMD gauge data
    attrs     schema, sources, licence, created_at, tmax_regrid_method

All carry the attributes in ``REQUIRED_ATTRS`` except truth_v1 (see ``TRUTH_ATTRS``).
"""

from __future__ import annotations

import numpy as np
import xarray as xr

ARCHIVE_SCHEMA = "archive_hourly_v1"
CANONICAL_SCHEMA = "canonical_v1"
TRUTH_SCHEMA = "truth_v1"

REQUIRED_ATTRS = ("schema", "source", "model_version", "licence", "fetched_at", "regrid_method")
DIMS = ("init_time", "lead_h", "lat", "lon")
ENS_DIMS = ("init_time", "member", "lead_h", "lat", "lon")
TRUTH_DIMS = ("time", "lat", "lon")
TRUTH_ATTRS = ("schema", "sources", "licence", "created_at", "tmax_regrid_method")

ARCHIVE_VARS = {"precip_1h_mm": (-0.001, 1000.0), "t2m_c": (-90.0, 65.0)}
CANONICAL_VARS = {"precip_24h_mm": (-0.001, 5000.0), "tmax_c": (-90.0, 65.0)}

# IMD rain day ends at 08:30 IST = 03:00 UTC
IMD_DAY_END_UTC_HOUR = 3


class SchemaError(ValueError):
    """A dataset does not satisfy its contract."""


def _check(
    ds: xr.Dataset,
    schema: str,
    variables: dict[str, tuple[float, float]],
    allowed_dims: tuple[tuple[str, ...], ...] = (DIMS,),
    attrs: tuple[str, ...] = REQUIRED_ATTRS,
) -> None:
    problems: list[str] = []
    if ds.attrs.get("schema") != schema:
        problems.append(f"attrs.schema={ds.attrs.get('schema')!r}, expected {schema!r}")
    problems += [f"missing attr {a!r}" for a in attrs if not ds.attrs.get(a)]
    for v, (lo, hi) in variables.items():
        if v not in ds.data_vars:
            problems.append(f"missing variable {v!r}")
            continue
        da = ds[v]
        if tuple(da.dims) not in allowed_dims:
            problems.append(f"{v} dims {da.dims} not in {allowed_dims}")
        if da.dtype != np.float32:
            problems.append(f"{v} dtype {da.dtype} != float32")
        vals = da.values
        finite = vals[np.isfinite(vals)]
        if finite.size and (finite.min() < lo or finite.max() > hi):
            problems.append(
                f"{v} outside plausible range [{lo}, {hi}]: {finite.min():.3f}..{finite.max():.3f}"
            )
    for d in allowed_dims[0]:
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
    _check(
        ds,
        CANONICAL_SCHEMA,
        CANONICAL_VARS,
        allowed_dims=(DIMS, ENS_DIMS),
        attrs=(*REQUIRED_ATTRS, "init_semantics"),
    )
    if "valid_day" not in ds.coords:
        raise SchemaError(f"{CANONICAL_SCHEMA}: missing coordinate 'valid_day'")
    vd = ds["valid_day"].values
    expect = (
        ds["init_time"].values[:, None]
        + ds["lead_h"].values[None, :].astype("timedelta64[h]")
        - np.timedelta64(IMD_DAY_END_UTC_HOUR, "h")
    )
    if not np.array_equal(vd.astype("datetime64[h]"), expect.astype("datetime64[h]")):
        raise SchemaError(f"{CANONICAL_SCHEMA}: valid_day inconsistent with init_time + lead_h")


def validate_truth(ds: xr.Dataset) -> None:
    """Raise :class:`SchemaError` unless ``ds`` satisfies ``truth_v1``."""
    _check(
        ds,
        TRUTH_SCHEMA,
        {"rain_mm": (-0.001, 5000.0), "tmax_c": (-90.0, 65.0)},
        allowed_dims=(TRUTH_DIMS,),
        attrs=TRUTH_ATTRS,
    )
    if (
        "provisional" not in ds
        or ds["provisional"].dims != ("time",)
        or ds["provisional"].dtype != bool
    ):
        raise SchemaError(f"{TRUTH_SCHEMA}: 'provisional' must be bool over (time,)")
