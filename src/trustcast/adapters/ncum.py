"""NCMRWF NCUM / NEPS adapter slot.

NCUM (deterministic) and NEPS (ensemble) are not publicly available. This stub keeps the slot in the
adapter registry so that, once NCMRWF provides data (e.g. via the problem statement's dataset link),
only this file needs an implementation.
"""

from __future__ import annotations

import datetime as dt

import xarray as xr

from trustcast.adapters.base import NotConfigured, SourceAdapter
from trustcast.config import AdapterConfig, RegionConfig


class NcumAdapter(SourceAdapter):
    """Placeholder that always raises :class:`NotConfigured`."""

    licence = "NCMRWF (terms to be confirmed when data is provided)"

    def __init__(self, name: str, acfg: AdapterConfig) -> None:
        self.name = name
        self.source = acfg.source

    def fetch(self, init_time: dt.datetime, bbox: RegionConfig) -> xr.Dataset:
        raise NotConfigured(
            "NCUM/NEPS data access is not configured: NCMRWF model output is not public. "
            "Provide files or an endpoint and implement NcumAdapter.fetch."
        )
