"""Baselines on SYNTHETIC data, including the superensemble leakage test."""

import numpy as np
import pandas as pd
import pytest
import xarray as xr

from trustcast.blend.baselines import (
    build_climatology,
    clim_for,
    equal_mean,
    persistence,
    superensemble,
)
from trustcast.verify.data import deterministic, exceed_prob, obs_like, season_of

INITS = pd.date_range("2024-01-01", periods=240, freq="D")
LEADS = np.array([27, 51], dtype=np.int16)


def _fc(values, name="x"):
    vd = INITS.values[:, None] + (LEADS.astype("timedelta64[h]") - np.timedelta64(3, "h"))[None, :]
    return xr.DataArray(
        values.astype(np.float32),
        dims=("init_time", "lead_h", "lat", "lon"),
        coords={
            "init_time": INITS,
            "lead_h": LEADS,
            "lat": [10.0, 10.25],
            "lon": [76.0],
            "valid_day": (("init_time", "lead_h"), vd),
        },
        name=name,
    )


def _synthetic(seed=0):
    rng = np.random.default_rng(seed)  # SYNTHETIC
    truth = rng.gamma(0.8, 8, (INITS.size, 2, 2, 1))
    a = truth * 1.5 + rng.normal(0, 1, truth.shape)  # biased high
    b = truth * 0.5 + rng.normal(0, 1, truth.shape)  # biased low
    return _fc(truth), _fc(a, "a"), _fc(b, "b")


def test_equal_mean_drops_missing_sources():
    _, a, b = _synthetic()
    b2 = b.copy()
    b2[:5] = np.nan
    m = equal_mean({"a": a, "b": b2})
    assert np.allclose(m[:5], a[:5])
    assert np.allclose(m[5:], (a[5:] + b2[5:]) / 2)


def test_superensemble_learns_and_starts_after_training_period():
    obs, a, b = _synthetic()
    se = superensemble({"a": a, "b": b}, obs, min_train_days=60)
    first = pd.DatetimeIndex(se.init_time.values)[np.isfinite(se.values).any(axis=(1, 2, 3))][0]
    assert first >= pd.Timestamp("2024-03-01")  # needs >= 60 training days
    late = slice(150, None)
    rmse = lambda f: float(np.sqrt(np.nanmean((f[late] - obs[late]) ** 2)))  # noqa: E731
    assert rmse(se) < 0.5 * min(rmse(a), rmse(b))


def test_superensemble_has_no_leakage():
    """Changing observations of a target month must not change that month's predictions."""
    obs, a, b = _synthetic()
    se1 = superensemble({"a": a, "b": b}, obs, min_train_days=60)
    month = pd.DatetimeIndex(INITS).to_period("M") == pd.Period("2024-06")
    obs2 = obs.copy()
    # corrupt every observation whose valid day is on/after the first June init
    vd = pd.DatetimeIndex(obs2.valid_day.values.ravel()).to_numpy().reshape(obs2.valid_day.shape)
    obs2.values[vd >= np.datetime64("2024-06-01")] = 999.0
    se2 = superensemble({"a": a, "b": b}, obs2, min_train_days=60)
    assert np.allclose(se1.values[month], se2.values[month], equal_nan=True)


def test_persistence_uses_previous_day():
    truth = xr.DataArray(
        np.arange(10, dtype=float)[:, None, None] * np.ones((1, 2, 1)),
        dims=("time", "lat", "lon"),
        coords={
            "time": pd.date_range("2024-01-01", periods=10),
            "lat": [10.0, 10.25],
            "lon": [76.0],
        },
    )
    like = _fc(np.zeros((INITS.size, 2, 2, 1)))
    p = persistence(truth, like)
    assert p.values[3, 0, 0, 0] == 2.0 and p.values[3, 1, 0, 0] == 2.0  # init Jan 4 -> Jan 3
    assert np.isnan(p.values[0]).all()  # no Dec 31 obs


def test_obs_like_and_helpers():
    t = pd.date_range("2024-01-01", periods=300)
    truth = xr.DataArray(
        np.arange(300, dtype=float)[:, None, None] * np.ones((1, 2, 1)),
        dims=("time", "lat", "lon"),
        coords={"time": t, "lat": [10.0, 10.25], "lon": [76.0]},
    )
    fc = _fc(np.zeros((INITS.size, 2, 2, 1))).to_dataset(name="precip_24h_mm")
    o = obs_like(fc, truth)
    assert o.values[0, 0, 0, 0] == 1.0 and o.values[0, 1, 0, 0] == 2.0  # Jan 2, Jan 3
    ens = xr.DataArray(np.array([[0.0, 70.0, 80.0, 10.0]]), dims=("x", "member"))
    assert float(exceed_prob(ens, 64.5)[0]) == 0.5
    assert float(deterministic(ens)[0]) == 40.0
    assert season_of(np.array(["2024-07-01", "2024-01-15"], dtype="datetime64[ns]")).tolist() == [
        "monsoon_JJAS",
        "winter_JF",
    ]


def test_climatology_needs_full_normal_and_is_correct(tmp_path, cfg):
    from trustcast.grid.imd_grid import IMD_TEMP_1P0 as G

    region = cfg.regions["rain_pilot"]
    assert build_climatology(tmp_path, "tmax", region) is None  # no files -> no climatology
    (tmp_path / "truth" / "tmax").mkdir(parents=True)
    for y in range(1991, 2021):  # SYNTHETIC: value = 30 + year offset
        n = 366 if y % 4 == 0 else 365
        np.full((n, G.nlat, G.nlon), 30.0 + (y - 1991) * 0.1, "<f4").tofile(
            tmp_path / "truth" / "tmax" / f"{y}.GRD"
        )
    clim = build_climatology(tmp_path, "tmax", region, thresholds=(31.0,))
    assert clim["mean"].values[100, 0, 0] == pytest.approx(30 + 0.1 * 14.5, abs=1e-3)
    assert clim["p_ge_31.0"].values[100, 0, 0] == pytest.approx(20 / 30, abs=1e-6)  # 2001..2020
    base = _fc(np.zeros((INITS.size, 2, 2, 1)))
    like = xr.DataArray(
        np.zeros((INITS.size, 2, clim.lat.size, clim.lon.size)),
        dims=base.dims,
        coords={
            "init_time": base.init_time,
            "lead_h": base.lead_h,
            "lat": clim.lat,
            "lon": clim.lon,
            "valid_day": base.valid_day,
        },
    )
    c = clim_for(clim, "mean", like)
    assert c.shape == like.shape and np.isfinite(c.values).all()


def test_tmax_pairs_with_previous_imd_day():
    """IMD Tmax of day D is D's daytime maximum -> it pairs with the window labelled D + 1."""
    t = pd.date_range("2024-01-01", periods=300)
    truth = xr.DataArray(
        np.arange(300, dtype=float)[:, None, None] * np.ones((1, 2, 1)),
        dims=("time", "lat", "lon"),
        coords={"time": t, "lat": [10.0, 10.25], "lon": [76.0]},
    )
    fc = _fc(np.zeros((INITS.size, 2, 2, 1))).to_dataset(name="tmax_c")
    rain = obs_like(fc, truth, 0)
    tmax = obs_like(fc, truth, -1)
    assert rain.values[0, 0, 0, 0] == 1.0  # window labelled Jan 2 -> IMD rain of Jan 2
    assert tmax.values[0, 0, 0, 0] == 0.0  # window labelled Jan 2 -> IMD Tmax of Jan 1
