"""Adapters on SYNTHETIC in-memory datasets / mocked HTTP (no network)."""

import datetime as dt

import httpx
import numpy as np
import pandas as pd
import pytest
import xarray as xr

from trustcast.adapters.base import NotConfigured, SourceUnavailable
from trustcast.adapters.dynamical import DynamicalAdapter
from trustcast.adapters.openmeteo import OpenMeteoSingleRuns
from trustcast.adapters.openmeteo_adapters import OpenMeteoPreviousRunsAdapter
from trustcast.adapters.ratelimit import RollingLimiter
from trustcast.adapters.registry import build_adapters
from trustcast.grid.schema import validate_canonical

INIT = np.datetime64("2025-10-20T00:00", "ns")


def _fake_dynamical(members: int | None, step_h: int, with_max: bool) -> xr.Dataset:
    """SYNTHETIC stand-in for a dynamical.org forecast dataset (lat descending, 0.25 deg)."""
    lat = np.arange(14.0, 7.0 - 0.01, -0.25)
    lon = np.arange(74.0, 78.01, 0.25)
    leads = np.arange(0, 241, step_h).astype("timedelta64[h]").astype("timedelta64[ns]")
    dims = ["init_time", "lead_time", "latitude", "longitude"]
    shape = [1, leads.size, lat.size, lon.size]
    if members:
        dims.insert(1, "ensemble_member")
        shape.insert(1, members)
    rate = np.full(shape, 1.0 / 3600.0, np.float32)  # 1 mm/h everywhere
    temp = np.full(shape, 25.0, np.float32)
    data = {"precipitation_surface": (dims, rate), "temperature_2m": (dims, temp)}
    if with_max:
        data["maximum_temperature_2m"] = (dims, temp + 5)
    coords = {"init_time": [INIT], "lead_time": leads, "latitude": lat, "longitude": lon}
    if members:
        coords["ensemble_member"] = np.arange(members)
    return xr.Dataset(data, coords=coords, attrs={"dataset_version": "synthetic"})


@pytest.mark.parametrize(
    ("members", "step", "tmax_var", "expect_t"),
    [(None, 6, None, 25.0), (None, 1, "maximum_temperature_2m", 30.0), (5, 3, None, 25.0)],
)
def test_dynamical_adapter_windows(cfg, members, step, tmax_var, expect_t):
    name = f"fake_{members}_{step}"
    DynamicalAdapter._datasets[name] = _fake_dynamical(members, step, tmax_var is not None)
    acfg = cfg.adapters["aifs_dyn"].model_copy(update={"dataset": name, "tmax_var": tmax_var})
    ds = DynamicalAdapter("fake", acfg, cfg).fetch(pd.Timestamp(INIT), cfg.regions["rain_pilot"])
    validate_canonical(ds)
    assert np.allclose(ds.precip_24h_mm.values, 24.0)  # 1 mm/h x 24 h, every lead incl. 5
    assert np.allclose(ds.tmax_c.values, expect_t)
    assert ("member" in ds.dims) == bool(members)


def test_dynamical_member_selection_gives_deterministic_output(cfg):
    DynamicalAdapter._datasets["fake_ens"] = _fake_dynamical(5, 3, False)
    acfg = cfg.adapters["ifsctrl_dyn"].model_copy(update={"dataset": "fake_ens"})
    ds = DynamicalAdapter("ctrl", acfg, cfg).fetch(pd.Timestamp(INIT), cfg.regions["rain_pilot"])
    validate_canonical(ds)
    assert "member" not in ds.dims and acfg.member == 0


def test_dynamical_read_failure_becomes_source_unavailable(cfg, monkeypatch):
    DynamicalAdapter._datasets["fake_broken"] = _fake_dynamical(None, 6, False)
    acfg = cfg.adapters["aifs_dyn"].model_copy(update={"dataset": "fake_broken"})

    def boom(self, *a, **k):
        raise OSError("SYNTHETIC network failure")

    monkeypatch.setattr(xr.Dataset, "load", boom)
    with pytest.raises(SourceUnavailable, match="read failed"):
        DynamicalAdapter("fake", acfg, cfg).fetch(pd.Timestamp(INIT), cfg.regions["rain_pilot"])


def test_dynamical_missing_init_raises(cfg):
    DynamicalAdapter._datasets["fake_missing"] = _fake_dynamical(None, 6, False)
    acfg = cfg.adapters["aifs_dyn"].model_copy(update={"dataset": "fake_missing"})
    with pytest.raises(SourceUnavailable, match="not in"):
        DynamicalAdapter("fake", acfg, cfg).fetch(
            dt.datetime(2025, 10, 21), cfg.regions["rain_pilot"]
        )


def _prev_transport(lead_days: int, broken: bool = False) -> httpx.MockTransport:
    """SYNTHETIC previous-runs responses: value of previous_day{k} = k mm per hour."""

    def handler(request: httpx.Request) -> httpx.Response:
        if broken:
            return httpx.Response(200, content=b"")
        q = request.url.params
        times = (
            pd.date_range(
                q["start_date"], pd.Timestamp(q["end_date"]) + pd.Timedelta(hours=23), freq="h"
            )
            .strftime("%Y-%m-%dT%H:%M")
            .tolist()
        )
        locs = []
        for a, b in zip(q["latitude"].split(","), q["longitude"].split(","), strict=True):
            hourly = {"time": times}
            for key in q["hourly"].split(","):
                k = int(key.rsplit("day", 1)[1])
                hourly[key] = (
                    [float(k)] * len(times) if key.startswith("precip") else [30.0 + k] * len(times)
                )
            locs.append({"latitude": float(a), "longitude": float(b), "hourly": hourly})
        return httpx.Response(200, json=locs if len(locs) > 1 else locs[0])

    return httpx.MockTransport(handler)


def _prev_adapter(cfg, tmp_path, broken=False):
    client = OpenMeteoSingleRuns(
        cfg.openmeteo,
        24,
        ["precipitation", "temperature_2m"],
        client=httpx.Client(transport=_prev_transport(cfg.canonical.lead_days, broken)),
        limiter=RollingLimiter(10_000),
        hourly_limiter=RollingLimiter(10_000, 3600, blocking=False),
        sleep=lambda s: None,
    )
    return OpenMeteoPreviousRunsAdapter("ifs_prev", cfg.adapters["ifs_prev"], cfg, client, tmp_path)


def test_previous_runs_adapter_uses_day_k_for_lead_k(cfg, tmp_path):
    ad = _prev_adapter(cfg, tmp_path)
    ds = ad.fetch_many(
        [dt.datetime(2025, 10, 20), dt.datetime(2025, 10, 21)], cfg.regions["rain_pilot"]
    )
    validate_canonical(ds)
    assert ds.sizes["init_time"] == 2
    assert ds.precip_24h_mm.values[0, :, 0, 0].tolist() == [24, 48, 72, 96, 120]
    assert ds.tmax_c.values[1, :, 0, 0].tolist() == [31, 32, 33, 34, 35]
    assert "floor_6h" in ds.attrs["init_semantics"]
    # the completed half-month block was cached as raw gzip
    assert list((tmp_path / "raw" / "openmeteo_prev").rglob("*.json.gz"))


def test_previous_runs_land_only_requests_only_land_cells(cfg, tmp_path):
    # SYNTHETIC IMD rain file: every cell valid except lat 10.25 (row 15 of the IMD grid) = sea
    from trustcast.grid.imd_grid import IMD_RAIN_0P25

    g = IMD_RAIN_0P25

    arr = np.zeros((2, g.nlat, g.nlon), "<f4")
    arr[:, 15, :] = -999.0
    p = tmp_path / "truth" / "rain" / "2024.grd"
    p.parent.mkdir(parents=True)
    arr.tofile(p)
    cfg.previous_runs.land_only = True
    ad = _prev_adapter(cfg, tmp_path)
    region = cfg.regions["rain_pilot"]  # lat 10.0..10.5, lon 76.0..76.25
    ds = ad.fetch(dt.datetime(2025, 10, 20), region)
    assert ad.points(region).tolist() == [0, 1, 4, 5]  # row 10.25 skipped
    assert np.isnan(ds.precip_24h_mm.sel(lat=10.25).values).all()
    assert np.isfinite(ds.precip_24h_mm.sel(lat=10.0).values).all()
    assert list((tmp_path / "raw" / "openmeteo_prev").rglob("*_land_L5.json.gz"))


def test_quota_ledger_shared_between_processes(tmp_path):
    from trustcast.adapters.ledger import QuotaLedger
    from trustcast.adapters.ratelimit import BudgetExhausted

    t = [1000.0]
    a = QuotaLedger(tmp_path / "l.jsonl", cap=9500, who="archiver", clock=lambda: t[0])
    b = QuotaLedger(tmp_path / "l.jsonl", cap=8000, who="backfill", clock=lambda: t[0])
    b.reserve(7000)
    with pytest.raises(BudgetExhausted):
        b.reserve(1500)  # backfill capped at 8000
    a.reserve(1500)  # archiver still has headroom
    assert a.used() == 8500
    t[0] += 86_401  # window rolls over
    b.reserve(7000)


def test_previous_runs_rejects_non_00z(cfg, tmp_path):
    with pytest.raises(ValueError, match="00Z"):
        _prev_adapter(cfg, tmp_path).fetch(dt.datetime(2025, 10, 20, 12), cfg.regions["rain_pilot"])


def test_previous_runs_empty_body_fails_loudly(cfg, tmp_path):
    with pytest.raises(SourceUnavailable):
        _prev_adapter(cfg, tmp_path, broken=True).fetch(
            dt.datetime(2025, 10, 20), cfg.regions["rain_pilot"]
        )


def test_ncum_stub_raises_not_configured(cfg, tmp_path):
    ad = build_adapters(cfg, tmp_path)["ncum"]
    with pytest.raises(NotConfigured):
        ad.fetch(dt.datetime(2025, 10, 20), cfg.regions["rain_pilot"])


def test_registry_filters_by_use(cfg, tmp_path):
    ev = build_adapters(cfg, tmp_path, use="eval")
    assert "ifs_prev" in ev and "ifs_single" not in ev
    assert {a.source for a in ev.values()} >= {
        "ecmwf_ifs",
        "ecmwf_aifs",
        "ncep_gfs",
        "ncep_gefs",
        "ecmwf_ifs_ens",
        "ecmwf_aifs_ens",
        "dwd_icon",
    }
