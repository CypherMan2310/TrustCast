"""Shared test fixtures."""

from __future__ import annotations

import datetime as dt
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT))

from trustcast.config import Config, load_config  # noqa: E402

NOW = dt.datetime(2026, 9, 30, 10, 0)


@pytest.fixture
def cfg() -> Config:
    """Real pilot config, shrunk to tiny regions so tests stay fast."""
    c = load_config()
    c.regions["rain_pilot"].lat = (10.0, 10.5)
    c.regions["rain_pilot"].lon = (76.0, 76.25)
    c.regions["heat_pilot"].lat = (20.0, 20.25)
    c.regions["heat_pilot"].lon = (78.0, 78.0)
    c.archiver.forecast_hours = 24
    c.openmeteo.max_locations_per_request = 4
    return c
