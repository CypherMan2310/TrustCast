"""Source adapter interface and the errors every adapter raises.

Adapters never substitute synthetic values: a failure raises one of the errors below
and the caller decides how to degrade (drop the source and re-normalise).
"""

from __future__ import annotations

import datetime as dt
from abc import ABC, abstractmethod

import xarray as xr

from trustcast.config import RegionConfig


class SourceError(RuntimeError):
    """Base class for source failures."""


class SourceUnavailable(SourceError):
    """The source could not be reached or returned unusable data."""


class QuotaExhausted(SourceUnavailable):
    """A provider quota (ours or theirs) is used up; retry later, the source itself is fine."""


class StaleSource(SourceError):
    """The newest run offered by the source is older than the allowed age."""


class NotConfigured(SourceError):
    """The adapter exists but has no data access configured (e.g. NCUM)."""


class SourceAdapter(ABC):
    """One forecast source (a model from one provider)."""

    source: str
    licence: str

    @abstractmethod
    def fetch(self, init_time: dt.datetime, bbox: RegionConfig) -> xr.Dataset:
        """Return the run initialised at ``init_time`` for ``bbox`` in the canonical schema."""
