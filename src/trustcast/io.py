"""Filesystem helpers that behave on Windows (transient locks from scanners/indexers)."""

from __future__ import annotations

import shutil
import time
import uuid
from pathlib import Path

import xarray as xr


def _retry(fn, attempts: int = 8, delay_s: float = 0.25) -> None:
    for i in range(attempts):
        try:
            fn()
            return
        except PermissionError:
            if i == attempts - 1:
                raise
            time.sleep(delay_s * (i + 1))


def replace_dir(src: Path, dest: Path) -> None:
    """Move directory ``src`` to ``dest``, replacing any existing ``dest``.

    The old ``dest`` is renamed aside first (a rename succeeds where a recursive delete may be
    blocked by a transient lock), then removed best-effort.
    """
    old = None
    if dest.exists():
        old = dest.with_name(f"{dest.name}.old-{uuid.uuid4().hex[:8]}")
        _retry(lambda: dest.rename(old))
    _retry(lambda: src.rename(dest))
    if old is not None:
        shutil.rmtree(old, ignore_errors=True)


def write_zarr_atomic(ds: xr.Dataset, dest: Path) -> None:
    """Write ``ds`` to a temporary store next to ``dest`` and swap it into place."""
    tmp = dest.with_name(f"{dest.name}.tmp-{uuid.uuid4().hex[:8]}")
    tmp.parent.mkdir(parents=True, exist_ok=True)
    ds.to_zarr(tmp, mode="w", consolidated=False)
    replace_dir(tmp, dest)
