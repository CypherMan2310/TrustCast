"""End-to-end archiver on a mocked HTTP transport (SYNTHETIC responses), plus manifests."""

import datetime as dt
import json

import httpx
import numpy as np
import xarray as xr

from tests.conftest import NOW
from tests.fixtures.synthetic_openmeteo import make_transport
from trustcast.adapters.openmeteo import OpenMeteoSingleRuns
from trustcast.adapters.ratelimit import RollingLimiter
from trustcast.archive.manifest import verify_manifest
from trustcast.archive.runner import ArchivePaths, archive_all

D = dt.datetime
FRESH = D(2026, 9, 30, 0)
LAST_INITS = {
    "ecmwf_ifs025": FRESH,
    "ecmwf_aifs025_single": FRESH,
    "ncep_gfs025": FRESH,
    "dwd_icon": D(2026, 9, 30, 6),
    "cmc_gem_gdps": D(2026, 5, 26, 0),
}


def _client(cfg, broken=None):
    http = httpx.Client(transport=make_transport(LAST_INITS, cfg.archiver.forecast_hours, broken))
    return OpenMeteoSingleRuns(
        cfg.openmeteo,
        cfg.archiver.forecast_hours,
        cfg.archiver.hourly_variables,
        client=http,
        limiter=RollingLimiter(10_000),
        sleep=lambda s: None,
        hourly_limiter=RollingLimiter(10_000, 3600, blocking=False),
    )


def _run(cfg, tmp_path, broken=None, **kw):
    cfg.archiver.lookback_cycles = 1
    return archive_all(cfg, tmp_path, _client(cfg, broken), now=NOW, **kw)


def test_archive_writes_verified_runs(cfg, tmp_path):
    res = _run(cfg, tmp_path)
    by = {(r.source, r.region): r for r in res}
    for s in ["ecmwf_ifs", "ecmwf_aifs", "ncep_gfs", "dwd_icon"]:
        for region in ["rain_pilot", "heat_pilot"]:
            r = by[(s, region)]
            assert r.status == "ok", r
            assert r.init_time == "2026-09-30T00:00:00"
    assert {r.status for r in res if r.source == "cmc_gem"} == {"stale"}

    paths = ArchivePaths(tmp_path)
    m = paths.manifest("ecmwf_ifs", "rain_pilot", FRESH)
    assert verify_manifest(m, tmp_path) == []
    man = json.loads(m.read_text())
    assert man["processed"]["dims"] == {"init_time": 1, "lead_h": 24, "lat": 3, "lon": 2}
    assert man["request"]["n_requests"] == 2  # 6 points, 4 per request
    ds = xr.open_zarr(tmp_path / man["processed"]["path"], consolidated=False)
    assert ds.attrs["source"] == "ecmwf_ifs" and ds.attrs["licence"]
    assert np.isfinite(ds.t2m_c.values).all()

    log_lines = (tmp_path / "processed/archive/runs.jsonl").read_text().splitlines()
    assert len(log_lines) == len(res)


def test_rerun_is_idempotent(cfg, tmp_path):
    _run(cfg, tmp_path)
    res2 = _run(cfg, tmp_path)
    assert {r.status for r in res2 if r.source != "cmc_gem"} == {"exists"}


def test_failed_source_does_not_block_others(cfg, tmp_path):
    res = _run(
        cfg,
        tmp_path,
        broken={"gfs_global": "empty", "icon_global": "all_null", "ecmwf_aifs025_single": "400"},
    )
    st = {r.source: r.status for r in res}
    assert st["ecmwf_ifs"] == "ok"
    assert st["ncep_gfs"] == st["dwd_icon"] == st["ecmwf_aifs"] == "failed"
    # nothing written for failed sources
    assert not (tmp_path / "processed/archive/ncep_gfs").exists()
    assert not (tmp_path / "raw/openmeteo/dwd_icon").exists()


def test_tampered_raw_detected(cfg, tmp_path):
    _run(cfg, tmp_path, sources=["ecmwf_ifs"], regions=["rain_pilot"])
    paths = ArchivePaths(tmp_path)
    raw = paths.raw("ecmwf_ifs", "rain_pilot", FRESH)
    raw.write_bytes(raw.read_bytes() + b"x")
    problems = verify_manifest(paths.manifest("ecmwf_ifs", "rain_pilot", FRESH), tmp_path)
    assert any("raw sha256" in p for p in problems)


def test_tampered_zarr_detected_and_repaired(cfg, tmp_path):
    _run(cfg, tmp_path, sources=["ecmwf_ifs"], regions=["rain_pilot"])
    paths = ArchivePaths(tmp_path)
    zp = paths.zarr("ecmwf_ifs", "rain_pilot", FRESH)
    ds = xr.open_zarr(zp, consolidated=False).load()
    ds["t2m_c"].values[0, 0, 0, 0] += 1.0
    ds.to_zarr(zp, mode="w", consolidated=False)
    mpath = paths.manifest("ecmwf_ifs", "rain_pilot", FRESH)
    assert any("digest mismatch" in p for p in verify_manifest(mpath, tmp_path))
    # the next archiver run notices the corrupt run and re-fetches it
    res = _run(cfg, tmp_path, sources=["ecmwf_ifs"], regions=["rain_pilot"])
    assert res[0].status == "ok"
    assert verify_manifest(mpath, tmp_path) == []
