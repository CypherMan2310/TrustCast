"""Forecaster overrides: stored in SQLite and fed back into skill tracking.

An override records a forecaster's corrected value for a district and day, and (optionally) which
sources they distrust, with a reason. Effect on the system:

* the district product shows the override next to the blend (and bulletins use it, marked as such);
* for every distrusted source, the skill tracker's DMSE in that district's cells is multiplied by
  ``1 + PENALTY * 0.5 ** (age / HALF_LIFE)`` for inits after the override was created, so the
  blender down-weights that source there for the following days (decaying back to normal).
"""

from __future__ import annotations

import datetime as dt
import json
import sqlite3
from pathlib import Path

import numpy as np
import pandas as pd
import xarray as xr

PENALTY = 1.0
HALF_LIFE_DAYS = 7.0

SCHEMA = """
CREATE TABLE IF NOT EXISTS overrides (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    created_at TEXT NOT NULL,
    district_id TEXT NOT NULL,
    variable TEXT NOT NULL,
    valid_day TEXT NOT NULL,
    value REAL,
    distrust_sources TEXT NOT NULL,
    reason TEXT NOT NULL,
    author TEXT NOT NULL
)"""


def connect(path: Path) -> sqlite3.Connection:
    """Open (and create) the override database."""
    path.parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(path)
    con.execute(SCHEMA)
    return con


def add_override(
    con: sqlite3.Connection,
    district_id: str,
    variable: str,
    valid_day: dt.date,
    value: float | None,
    distrust_sources: list[str],
    reason: str,
    author: str,
    created_at: dt.datetime | None = None,
) -> int:
    """Insert an override and return its id."""
    created = (created_at or dt.datetime.now(dt.UTC)).replace(tzinfo=None).isoformat()
    cur = con.execute(
        "INSERT INTO overrides (created_at, district_id, variable, valid_day, value,"
        " distrust_sources, reason, author) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
        (
            created,
            district_id,
            variable,
            str(valid_day),
            value,
            json.dumps(distrust_sources),
            reason,
            author,
        ),
    )
    con.commit()
    return int(cur.lastrowid)


def load_overrides(con: sqlite3.Connection, variable: str | None = None) -> pd.DataFrame:
    """All overrides (optionally for one variable)."""
    q = "SELECT * FROM overrides" + (" WHERE variable = ?" if variable else "")
    df = pd.read_sql_query(q, con, params=(variable,) if variable else ())
    if len(df):
        df["distrust_sources"] = df["distrust_sources"].map(json.loads)
        df["created_at"] = pd.to_datetime(df["created_at"])
    return df


def penalty_factors(
    overrides: pd.DataFrame, districts: pd.DataFrame, like: xr.DataArray, sources: list[str]
) -> dict[str, xr.DataArray]:
    """Multiplicative DMSE penalty per source on the (init_time, lead_h, lat, lon) grid (1 = none).

    Only overrides created at or before an init affect it (no look-ahead).
    """
    order = ("init_time", "lead_h", "lat", "lon")
    like = like.transpose(*order)
    inits = pd.DatetimeIndex(like.init_time.values)
    lat, lon = like.lat.values, like.lon.values
    out = {s: np.ones(like.shape, dtype=np.float32) for s in sources}
    for ov in overrides.itertuples():
        cells = districts[districts.district_id == ov.district_id]
        if cells.empty:
            continue
        ii = np.searchsorted(lat, cells.lat.to_numpy())
        jj = np.searchsorted(lon, cells.lon.to_numpy())
        age = (inits - ov.created_at).total_seconds().to_numpy() / 86400.0
        f = np.where(age >= 0, 1.0 + PENALTY * 0.5 ** (np.clip(age, 0, None) / HALF_LIFE_DAYS), 1.0)
        for s in ov.distrust_sources:
            if s in out:
                out[s][:, :, ii, jj] *= f[:, None, None].astype(np.float32)
    return {
        s: xr.DataArray(v, dims=order, coords={k: like.coords[k] for k in order})
        for s, v in out.items()
    }
