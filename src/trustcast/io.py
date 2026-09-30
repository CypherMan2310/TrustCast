"""Filesystem helpers that behave on Windows (transient locks from scanners/indexers)."""

from __future__ import annotations

import os
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


class AlreadyRunning(RuntimeError):
    """Another process holds the named lock."""


class single_instance:  # noqa: N801  (context manager used like a function)
    """Exclusive OS-level file lock; released automatically when the process exits or dies.

    Used so scheduled jobs (Task Scheduler / cron) never overlap with a run already in progress.
    """

    def __init__(self, path: Path) -> None:
        self.path = path
        self._fh = None

    def __enter__(self) -> single_instance:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._fh = open(self.path, "a+")
        try:
            if os.name == "nt":
                import msvcrt

                self._fh.seek(0)
                msvcrt.locking(self._fh.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl

                fcntl.flock(self._fh.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError as e:
            self._fh.close()
            raise AlreadyRunning(f"{self.path.name} is held by another process") from e
        return self

    def __exit__(self, *exc) -> None:
        try:
            if os.name == "nt":
                import msvcrt

                self._fh.seek(0)
                msvcrt.locking(self._fh.fileno(), msvcrt.LK_UNLCK, 1)
        except OSError:
            pass
        self._fh.close()
