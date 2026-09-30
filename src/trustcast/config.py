"""Typed configuration loaded from ``config/pilot.yaml``.

The YAML file is the single place for grid, region, archiver and source settings.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Literal

import yaml
from pydantic import BaseModel, Field, model_validator

REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_CONFIG = REPO_ROOT / "config" / "pilot.yaml"


class GridConfig(BaseModel):
    """A regular lat/lon grid defined by origin, step and size."""

    name: str
    lat0: float
    lon0: float
    step: float
    nlat: int
    nlon: int


class RegionConfig(BaseModel):
    """An inclusive lat/lon bounding box that must lie on the grid."""

    label: str
    lat: tuple[float, float]
    lon: tuple[float, float]

    @model_validator(mode="after")
    def _ordered(self) -> RegionConfig:
        if self.lat[0] > self.lat[1] or self.lon[0] > self.lon[1]:
            raise ValueError(f"region bounds must be (min, max): {self.lat}, {self.lon}")
        return self


class ArchiverConfig(BaseModel):
    """Settings for the 00/12Z snapshot archiver."""

    cycles_utc: list[int] = Field(default_factory=lambda: [0, 12])
    lookback_cycles: int = 4
    forecast_hours: int = 168
    max_run_age_hours: int = 48
    hourly_variables: list[str] = Field(default_factory=lambda: ["precipitation", "temperature_2m"])


class OpenMeteoSource(BaseModel):
    """One Open-Meteo model exposed as a TRUSTCAST source."""

    source: str
    model: str
    meta_id: str
    kind: Literal["nwp", "ai", "ens"]
    enabled: bool = True


class OpenMeteoConfig(BaseModel):
    """Open-Meteo endpoints, fair-use throttling and source list."""

    single_runs_url: str
    meta_url: str
    max_locations_per_minute: int = 400
    max_locations_per_hour: int = 4000
    max_locations_per_request: int = 150
    timeout_s: float = 120
    retries: int = 3
    sources: list[OpenMeteoSource]


class Config(BaseModel):
    """Root configuration object."""

    grid: GridConfig
    regions: dict[str, RegionConfig]
    archiver: ArchiverConfig
    openmeteo: OpenMeteoConfig


def load_config(path: Path | str | None = None) -> Config:
    """Load and validate the YAML configuration (defaults to ``config/pilot.yaml``)."""
    p = Path(path) if path else DEFAULT_CONFIG
    with p.open(encoding="utf-8") as f:
        return Config.model_validate(yaml.safe_load(f))


def data_root() -> Path:
    """Return the data directory: ``$TRUSTCAST_DATA_DIR`` if set, else ``<repo>/data``."""
    env = os.environ.get("TRUSTCAST_DATA_DIR", "").strip()
    return Path(env) if env else REPO_ROOT / "data"
