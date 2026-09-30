"""Build adapter instances from the ``adapters:`` block of the config."""

from __future__ import annotations

from pathlib import Path

from trustcast.adapters.base import SourceAdapter
from trustcast.adapters.dynamical import DynamicalAdapter
from trustcast.adapters.ecmwf_opendata import EcmwfOpenDataAdapter
from trustcast.adapters.ncum import NcumAdapter
from trustcast.adapters.openmeteo import OpenMeteoSingleRuns
from trustcast.adapters.openmeteo_adapters import (
    OpenMeteoLiveAdapter,
    OpenMeteoPreviousRunsAdapter,
    OpenMeteoSingleRunsAdapter,
)
from trustcast.config import Config


def build_adapters(
    cfg: Config, root: Path, client: OpenMeteoSingleRuns | None = None, use: str | None = None
) -> dict[str, SourceAdapter]:
    """Instantiate every enabled adapter (optionally only those with ``use``)."""
    client = client or OpenMeteoSingleRuns(
        cfg.openmeteo, cfg.archiver.forecast_hours, cfg.archiver.hourly_variables
    )
    out: dict[str, SourceAdapter] = {}
    for name, a in cfg.adapters.items():
        if not a.enabled or (use and a.use != use):
            continue
        match a.type:
            case "openmeteo_previous_runs":
                out[name] = OpenMeteoPreviousRunsAdapter(name, a, cfg, client, root)
            case "openmeteo_single_runs":
                out[name] = OpenMeteoSingleRunsAdapter(name, a, cfg, client, root)
            case "openmeteo_live":
                out[name] = OpenMeteoLiveAdapter(name, a, cfg, client, root)
            case "dynamical":
                out[name] = DynamicalAdapter(name, a, cfg)
            case "ecmwf_opendata":
                out[name] = EcmwfOpenDataAdapter(name, a, cfg, root)
            case "ncum":
                out[name] = NcumAdapter(name, a)
    return out
