"""Bias correction, leak-free skill tracker and blender A (SYNTHETIC data)."""

import numpy as np
import pandas as pd
import pytest
import xarray as xr

from trustcast.bias.qm import apply_map, fit_map, rolling_qm
from trustcast.blend.decayed import blend_a, weights_from_dmse
from trustcast.skill.tracker import decayed_mse

INITS = pd.date_range("2024-01-01", periods=200, freq="D")
LEADS = np.array([27, 51], dtype=np.int16)


def _da(values, members=None):
    vd = INITS.values[:, None] + (LEADS.astype("timedelta64[h]") - np.timedelta64(3, "h"))[None, :]
    dims = ("init_time", "lead_h", "lat", "lon")
    coords = {
        "init_time": INITS,
        "lead_h": LEADS,
        "lat": [10.0, 10.25],
        "lon": [76.0],
        "valid_day": (("init_time", "lead_h"), vd),
    }
    if members:
        dims = ("init_time", "member", "lead_h", "lat", "lon")
        coords["member"] = np.arange(members)
    return xr.DataArray(np.asarray(values, np.float32), dims=dims, coords=coords)


# ---------------------------------------------------------------- skill tracker


def test_tracker_hand_computed_constant_error():
    obs = _da(np.zeros((200, 2, 2, 1)))
    fc = _da(np.full((200, 2, 2, 1), 2.0))  # error^2 = 4 everywhere
    d = decayed_mse(fc, obs, half_life_days=10, min_eff=1)
    assert np.allclose(d.values[10:], 4.0)
    # init 2024-01-02: lead-1 case of init 01-01 has valid day 01-02 (not yet ended) -> NaN
    assert np.isnan(d.values[1, 0]).all()
    # init 2024-01-03: exactly one verified lead-1 case (valid 01-02) -> 4
    assert np.allclose(d.values[2, 0], 4.0)


def test_tracker_decay_weights_recent_errors_more():
    e = np.zeros((200, 2, 2, 1))
    e[:100] = 1.0
    e[100:] = 3.0
    d = decayed_mse(_da(e), _da(np.zeros_like(e)), half_life_days=5, min_eff=1)
    later = d.values[130, 0, 0, 0]
    # init idx 130 uses verification days up to idx 130; the last 30 cases have error^2 = 9,
    # older ones 1 with total weight share 0.5 ** (30 / 5) (geometric decay, half-life 5 days)
    share_old = 0.5 ** (30 / 5)
    assert later == pytest.approx(9 * (1 - share_old) + 1 * share_old, rel=1e-2)
    slow = decayed_mse(_da(e), _da(np.zeros_like(e)), half_life_days=200, min_eff=1)
    assert slow.values[130, 0, 0, 0] < later


def test_tracker_never_uses_verification_after_issue_time():
    """MANDATORY leakage test: changing any observation whose IMD window ends after init t
    must not change the tracker output at t."""
    rng = np.random.default_rng(0)  # SYNTHETIC
    fc = _da(rng.gamma(1, 5, (200, 2, 2, 1)))
    obs = _da(rng.gamma(1, 5, (200, 2, 2, 1)))
    base = decayed_mse(fc, obs, half_life_days=15, min_eff=1)
    for t_idx in (20, 77, 150):
        t = INITS[t_idx]
        obs2 = obs.copy()
        vd = (
            pd.DatetimeIndex(obs2.valid_day.values.ravel()).to_numpy().reshape(obs2.valid_day.shape)
        )
        future = vd + np.timedelta64(3, "h") > np.datetime64(t)  # window ends after t
        obs2.values[future] = 1e6
        new = decayed_mse(fc, obs2, half_life_days=15, min_eff=1)
        assert np.allclose(new.values[t_idx], base.values[t_idx], equal_nan=True)
        assert np.allclose(new.values[: t_idx + 1], base.values[: t_idx + 1], equal_nan=True)


def test_tracker_region_scope_pools_cells():
    e = np.zeros((200, 2, 2, 1))
    e[:, :, 0] = 1.0
    e[:, :, 1] = 3.0
    d = decayed_mse(_da(e), _da(np.zeros_like(e)), 10, scope="region", min_eff=1)
    assert np.allclose(d.values[50], 5.0)  # (1 + 9) / 2


# ---------------------------------------------------------------- quantile mapping


def test_quantile_map_removes_multiplicative_bias_and_keeps_zeros():
    rng = np.random.default_rng(1)
    obs = rng.gamma(0.7, 10, 20000) * (rng.uniform(size=20000) > 0.4)
    fc = obs * 1.8
    fq, oq = fit_map(fc, obs)
    y = apply_map(fc, fq, oq, "rain")
    assert np.mean(y) == pytest.approx(np.mean(obs), rel=0.05)
    assert (y[fc == 0] == 0).all()
    assert np.isnan(apply_map(np.array([np.nan]), fq, oq, "rain"))[0]
    # tail beyond the training range scales multiplicatively
    assert apply_map(np.array([fq[-1] * 2]), fq, oq, "rain")[0] == pytest.approx(oq[-1] * 2)


def test_quantile_map_temperature_shift():
    rng = np.random.default_rng(2)
    obs = rng.normal(35, 3, 5000)
    fq, oq = fit_map(obs - 2.5, obs)
    assert apply_map(np.array([30.0]), fq, oq, "temp")[0] == pytest.approx(32.5, abs=0.2)
    assert apply_map(np.array([100.0]), fq, oq, "temp")[0] == pytest.approx(102.5, abs=0.3)


def test_rolling_qm_is_leak_free_and_corrects_bias():
    rng = np.random.default_rng(3)
    o = rng.normal(30, 2, (200, 2, 2, 1))
    obs, fc = _da(o), _da(o - 3 + rng.normal(0, 0.5, o.shape))
    out = rolling_qm(fc, obs, "temp", min_cases=100)
    assert np.allclose(out.values[:31], fc.values[:31], equal_nan=True)  # Jan: no training yet
    late = slice(120, None)
    assert (
        abs(float((out[late] - obs[late]).mean())) < 0.3 < abs(float((fc[late] - obs[late]).mean()))
    )
    obs2 = obs.copy()
    vd = pd.DatetimeIndex(obs2.valid_day.values.ravel()).to_numpy().reshape(obs2.valid_day.shape)
    obs2.values[vd >= np.datetime64("2024-05-01")] += 50  # corrupt May onwards
    out2 = rolling_qm(fc, obs2, "temp", min_cases=100)
    may = pd.DatetimeIndex(INITS).month == 5
    assert np.allclose(out.values[may], out2.values[may])


def test_rolling_qm_ensemble_members():
    rng = np.random.default_rng(4)
    o = rng.gamma(1, 5, (200, 2, 2, 1))
    fc = _da(o[:, None] * 2 + rng.gamma(1, 1, (200, 5, 2, 2, 1)), members=5)
    out = rolling_qm(fc, _da(o), "rain", min_cases=100)
    assert out.dims == fc.dims and float(out[150:].mean()) < float(fc[150:].mean())


# ---------------------------------------------------------------- blender A


def test_weights_inverse_mse_and_renormalised_when_missing():
    x = np.array([[1.0], [2.0], [np.nan]])
    d = np.array([[1.0], [4.0], [0.5]])
    w = weights_from_dmse(x, d, p=1)
    assert w[:, 0].tolist() == pytest.approx([0.8, 0.2, 0.0])
    w2 = weights_from_dmse(x, np.array([[np.nan], [4.0], [0.5]]), p=1)  # no history -> median prior
    assert w2[0, 0] == pytest.approx(0.5)


def test_blend_graceful_degradation_each_source_removed():
    rng = np.random.default_rng(5)
    o = rng.gamma(1, 5, (200, 2, 2, 1))
    obs = _da(o)
    dets = {s: _da(o + rng.normal(0, k, o.shape)) for s, k in (("a", 1), ("b", 2), ("c", 4))}
    dm = {s: decayed_mse(v, obs, 15, min_eff=1) for s, v in dets.items()}
    _, w = blend_a(dets, dm, p=1)
    assert np.allclose(w.sum("source").values, 1.0)
    assert float(w.sel(source="a").isel(init_time=150).mean()) > float(
        w.sel(source="c").isel(init_time=150).mean()
    )
    for drop in dets:
        sub = {k: v for k, v in dets.items() if k != drop}
        part, wp = blend_a(sub, {k: dm[k] for k in sub}, p=1)
        assert np.isfinite(part.values).all() and np.allclose(wp.sum("source").values, 1.0)
    # a source missing for some inits only: still finite, weights renormalised
    gap = dict(dets)
    gap["a"] = dets["a"].where(dets["a"].init_time > INITS[100])
    part, wp = blend_a(gap, dm, p=1)
    assert np.isfinite(part.values).all()
    assert np.allclose(wp.sel(source="a").isel(init_time=50).values, 0.0)


def test_decayed_bias_correction_removes_cell_specific_bias_without_leakage():
    from trustcast.bias.decayed import decayed_bias_correction

    rng = np.random.default_rng(6)  # SYNTHETIC: cell 0 is 3 C too warm, cell 1 is 2 C too cold
    o = rng.normal(32, 1.5, (200, 2, 2, 1))
    f = o + np.array([3.0, -2.0])[None, None, :, None] + rng.normal(0, 0.5, o.shape)
    obs, fc = _da(o), _da(f)
    out = decayed_bias_correction(fc, obs, half_life_days=20)
    late = slice(100, None)
    for cell in (0, 1):
        assert abs(float((out[late, :, cell] - obs[late, :, cell]).mean())) < 0.2
    obs2 = obs.copy()
    obs2.values[150:] += 50  # corrupt later observations
    out2 = decayed_bias_correction(fc, obs2, half_life_days=20)
    assert np.allclose(out.values[:150], out2.values[:150])  # earlier corrections unchanged
