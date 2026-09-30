"""Archive every configured source's recent 00/12Z runs for every pilot region.

Layout under the data root::

    raw/openmeteo/<source>/<region>/<YYYYmmddTHH>.json.gz        immutable raw responses
    processed/archive/<source>/<region>/<YYYYmmddTHH>.zarr        archive_hourly_v1 store
    processed/archive/manifests/<source>__<region>__<YYYYmmddTHH>.json
    processed/archive/runs.jsonl                                   one line per attempt

A run is complete only when its manifest exists and verifies. Failures and stale sources
are recorded, never replaced with other data.
"""

from __future__ import annotations

import datetime as dt
import json
import logging
import shutil
import time
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Literal

from trustcast.adapters.base import SourceError, SourceUnavailable
from trustcast.adapters.openmeteo import OpenMeteoSingleRuns
from trustcast.archive.cycles import candidate_cycles
from trustcast.archive.manifest import build_manifest, verify_manifest, write_raw
from trustcast.config import Config
from trustcast.grid.imd_grid import RegularGrid
from trustcast.log import event

log = logging.getLogger(__name__)

Status = Literal["ok", "exists", "failed", "stale"]


@dataclass
class RunResult:
    """Outcome of one (source, region, init_time) attempt."""

    source: str
    region: str
    init_time: str | None
    status: Status
    detail: str = ""
    manifest: str | None = None


def _stamp(t: dt.datetime) -> str:
    return t.strftime("%Y%m%dT%H")


class ArchivePaths:
    """Resolve on-disk locations for archived runs."""

    def __init__(self, root: Path) -> None:
        self.root = root
        self.archive = root / "processed" / "archive"
        self.manifests = self.archive / "manifests"
        self.runs_log = self.archive / "runs.jsonl"

    def raw(self, source: str, region: str, init: dt.datetime) -> Path:
        return self.root / "raw" / "openmeteo" / source / region / f"{_stamp(init)}.json.gz"

    def zarr(self, source: str, region: str, init: dt.datetime) -> Path:
        return self.archive / source / region / f"{_stamp(init)}.zarr"

    def manifest(self, source: str, region: str, init: dt.datetime) -> Path:
        return self.manifests / f"{source}__{region}__{_stamp(init)}.json"


def _record(paths: ArchivePaths, res: RunResult) -> RunResult:
    paths.runs_log.parent.mkdir(parents=True, exist_ok=True)
    line = {"logged_at": dt.datetime.now(dt.UTC).isoformat(), **asdict(res)}
    with paths.runs_log.open("a", encoding="utf-8") as f:
        f.write(json.dumps(line) + "\n")
    return res


def archive_one(
    client: OpenMeteoSingleRuns,
    cfg: Config,
    paths: ArchivePaths,
    src_name: str,
    region: str,
    init: dt.datetime,
) -> RunResult:
    """Fetch, store, manifest and verify a single run. Idempotent."""
    src = next(s for s in cfg.openmeteo.sources if s.source == src_name)
    mpath = paths.manifest(src.source, region, init)
    if mpath.exists() and not verify_manifest(mpath, paths.root):
        return RunResult(src.source, region, init.isoformat(), "exists", manifest=str(mpath))

    raw_p, zarr_p = paths.raw(src.source, region, init), paths.zarr(src.source, region, init)
    if mpath.exists() or raw_p.exists() or zarr_p.exists():
        event(
            log,
            logging.WARNING,
            "removing incomplete or corrupt previous attempt",
            source=src.source,
            region=region,
            init_time=init.isoformat(),
        )
        mpath.unlink(missing_ok=True)
        raw_p.unlink(missing_ok=True)
        shutil.rmtree(zarr_p, ignore_errors=True)

    grid = RegularGrid.from_config(cfg.grid)
    lats, lons = grid.region_points(cfg.regions[region])
    t0 = time.monotonic()
    try:
        raw, ds = client.fetch_run(src, init, lats, lons, region)
    except SourceError as e:
        return RunResult(src.source, region, init.isoformat(), "failed", str(e))

    write_raw(raw, raw_p)
    tmp = zarr_p.with_name(zarr_p.name + ".tmp")
    shutil.rmtree(tmp, ignore_errors=True)
    tmp.parent.mkdir(parents=True, exist_ok=True)
    ds.to_zarr(tmp, mode="w", consolidated=False)
    tmp.rename(zarr_p)

    request = {
        "url": raw["url"],
        "model": src.model,
        "n_points": int(lats.size * lons.size),
        "n_requests": len(raw["batches"]),
        "forecast_hours": client.forecast_hours,
        "variables": client.variables,
    }
    manifest = build_manifest(
        ds=ds,
        raw_path=raw_p,
        zarr_path=zarr_p,
        data_root=paths.root,
        request=request,
        duration_s=time.monotonic() - t0,
    )
    mpath.parent.mkdir(parents=True, exist_ok=True)
    mpath.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    problems = verify_manifest(mpath, paths.root)
    if problems:
        return RunResult(
            src.source,
            region,
            init.isoformat(),
            "failed",
            "manifest verification: " + "; ".join(problems),
            str(mpath),
        )
    return RunResult(src.source, region, init.isoformat(), "ok", manifest=str(mpath))


def archive_all(
    cfg: Config,
    data_root: Path,
    client: OpenMeteoSingleRuns,
    now: dt.datetime | None = None,
    sources: list[str] | None = None,
    regions: list[str] | None = None,
) -> list[RunResult]:
    """Archive the recent 00/12Z cycles of every enabled source for every region."""
    now = now or dt.datetime.now(dt.UTC).replace(tzinfo=None)
    paths = ArchivePaths(data_root)
    a = cfg.archiver
    regions = regions or list(cfg.regions)
    results: list[RunResult] = []
    for src in cfg.openmeteo.sources:
        if not src.enabled or (sources and src.source not in sources):
            continue
        try:
            last = client.latest_init(src)
        except SourceUnavailable as e:
            for r in regions:
                results.append(_record(paths, RunResult(src.source, r, None, "failed", str(e))))
            continue
        cycles = candidate_cycles(last, now, a.cycles_utc, a.lookback_cycles, a.max_run_age_hours)
        if not cycles:
            detail = f"newest run {last.isoformat()} older than {a.max_run_age_hours} h"
            event(
                log,
                logging.ERROR,
                "source stale",
                source=src.source,
                last_init=last.isoformat(),
                status="stale",
            )
            for r in regions:
                results.append(_record(paths, RunResult(src.source, r, None, "stale", detail)))
            continue
        for init in cycles:
            for r in regions:
                res = archive_one(client, cfg, paths, src.source, r, init)
                if res.status != "exists":
                    _record(paths, res)
                results.append(res)
    return results
