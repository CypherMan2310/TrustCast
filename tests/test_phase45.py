"""Gate, regimes, extremes, conformal uncertainty, defer flag, explanations (SYNTHETIC data)."""

import numpy as np
import pandas as pd
import pytest
import xarray as xr

from trustcast.blend.decayed import blend_a
from trustcast.blend.explain import defer_flags, explanation_sentence, top_features
from trustcast.blend.features import case_grid, case_table
from trustcast.blend.gated import GatePredictions, apply_weights, softmax_weights
from trustcast.blend.regime import label_regimes
from trustcast.blend.rolling import rolling_fit_predict
from trustcast.extremes.classifier import exceedance_probabilities
from trustcast.skill.tracker import decayed_mse
from trustcast.uncertainty.cqr import conformalize, coverage

INITS = pd.date_range("2024-01-01", periods=420, freq="D")
LEADS = np.array([27, 51], dtype=np.int16)
LAT, LON = np.arange(10.0, 12.0, 0.25), np.arange(76.0, 77.5, 0.25)


def _da(values):
    vd = INITS.values[:, None] + (LEADS.astype("timedelta64[h]") - np.timedelta64(3, "h"))[None, :]
    return xr.DataArray(
        np.asarray(values, np.float32),
        dims=("init_time", "lead_h", "lat", "lon"),
        coords={
            "init_time": INITS,
            "lead_h": LEADS,
            "lat": LAT,
            "lon": LON,
            "valid_day": (("init_time", "lead_h"), vd),
        },
    )


SHAPE = (INITS.size, 2, LAT.size, LON.size)


def test_rolling_trainer_never_sees_the_future():
    n = 5000
    rng = np.random.default_rng(0)
    inits = np.sort(rng.choice(pd.date_range("2024-01-01", "2024-12-31").values, n))
    valid = inits + np.timedelta64(2, "D")
    X = pd.DataFrame({"v": pd.DatetimeIndex(valid).asi8.astype(float)})
    seen = {}

    def fit(Xt, yt):
        return float(Xt["v"].max())

    pred, models = rolling_fit_predict(
        X,
        np.ones(n),
        inits,
        valid,
        fit,
        lambda m, Xp: np.full(len(Xp), m),
        pd.Timestamp("2024-04-01"),
        min_train_rows=10,
    )
    for q0, max_seen in models.items():
        seen[q0] = max_seen
        assert pd.Timestamp(int(max_seen)) < q0
    assert np.isnan(pred[pd.DatetimeIndex(inits) < pd.Timestamp("2024-04-01")]).all()
    assert len(seen) == 3


def test_softmax_weights():
    e = np.array([[1.0, 5.0], [2.0, np.nan], [4.0, 1.0]])
    w = softmax_weights(e, temperature=0.5)
    assert np.allclose(w.sum(axis=0), 1.0)
    assert w[1, 1] == 0 and w[0, 0] > w[1, 0] > w[2, 0]
    sharp = softmax_weights(e, temperature=0.01)
    assert sharp[0, 0] == pytest.approx(1.0) and sharp[2, 1] == pytest.approx(1.0)


def test_gate_learns_which_source_to_trust_per_lead():
    rng = np.random.default_rng(1)
    truth = rng.gamma(0.8, 10, SHAPE)
    noise_a = np.where(np.arange(2)[None, :, None, None] == 0, 1.0, 8.0)  # a good at lead 1
    noise_b = np.where(np.arange(2)[None, :, None, None] == 0, 8.0, 1.0)  # b good at lead 2
    obs = _da(truth)
    dets = {
        "a": _da(truth + rng.normal(0, 1, SHAPE) * noise_a),
        "b": _da(truth + rng.normal(0, 1, SHAPE) * noise_b),
    }
    # tracker deliberately uninformative (region scope, huge half-life): only the gate can tell
    dm = {k: decayed_mse(v, obs, 1e6, scope="region", min_eff=1) for k, v in dets.items()}
    grid = case_grid(obs, None, None)
    gp = GatePredictions(grid, dets, dm, obs, pd.Timestamp("2024-07-01"))
    x = np.stack([dets[k].values.ravel() for k in dets])
    avail = np.isfinite(x)
    _, wa = blend_a(dets, dm, p=1)
    w = gp.weights(0.3, wa.values.reshape(2, -1), avail)
    late = np.broadcast_to(
        (pd.Timestamp("2024-10-01") <= INITS)[:, None, None, None], SHAPE
    ).ravel()
    lead1 = np.broadcast_to((np.arange(2) == 0)[None, :, None, None], SHAPE).ravel()
    assert w[0, late & lead1].mean() > 0.7 and w[1, late & ~lead1].mean() > 0.7
    gated = apply_weights(x, w, obs)
    rmse = lambda f: float(np.sqrt(np.nanmean(((f - obs).values.ravel()[late]) ** 2)))  # noqa: E731
    eq = _da((dets["a"].values + dets["b"].values) / 2)
    assert rmse(gated) < 0.8 * rmse(eq)


def test_regimes_rules():
    cons = _da(np.zeros(SHAPE))
    cons.values[:, 0] = 20.0
    cons.values[:, 1] = 0.2
    clim = _da(np.full(SHAPE, 10.0))
    r = label_regimes(cons, "precip", clim)
    july = pd.DatetimeIndex(INITS).month == 7
    jan = pd.DatetimeIndex(INITS).month == 1
    assert set(r.values[july, 0]) == {"monsoon_active"} and set(r.values[july, 1]) == {
        "monsoon_break"
    }
    assert set(r.values[jan, 1]) == {"dry"}
    hot = label_regimes(_da(np.full(SHAPE, 41.0)), "tmax")
    assert set(hot.values.ravel()) == {"heat"}


def test_exceedance_classifier_is_calibrated_and_skilful():
    rng = np.random.default_rng(2)
    truth = rng.gamma(0.6, 20, SHAPE)
    obs = _da(truth)
    dets = {
        "a": _da(truth * rng.lognormal(0, 0.4, SHAPE)),
        "b": _da(truth * rng.lognormal(0, 0.6, SHAPE)),
    }
    grid = case_grid(obs, None, None)
    blend = _da((dets["a"].values + dets["b"].values) / 2)
    X = case_table(grid, dets, blend, None, (64.5,))
    init = np.broadcast_to(INITS.values[:, None, None, None], SHAPE).ravel()
    probs = exceedance_probabilities(
        X, obs.values.ravel(), init, grid.valid_day, (64.5,), pd.Timestamp("2024-07-01")
    )[64.5]
    ok = np.isfinite(probs)
    ev = obs.values.ravel()[ok] >= 64.5
    assert ok.mean() > 0.3
    assert abs(probs[ok].mean() - ev.mean()) < 0.03  # calibrated in the mean
    from sklearn.metrics import roc_auc_score

    assert roc_auc_score(ev, probs[ok]) > 0.85


def test_conformal_reaches_nominal_coverage():
    rng = np.random.default_rng(3)
    n_days, per = 400, 300
    days = np.repeat(pd.date_range("2024-01-01", periods=n_days).values, per)
    sigma = np.repeat(rng.uniform(1, 3, n_days), per)
    y = rng.normal(0, sigma)
    lo, hi = np.full(y.shape, -1.0), np.full(y.shape, 1.0)  # badly calibrated
    lead = np.ones(y.shape, int)
    clo, chi = conformalize(lo, hi, y, days - np.timedelta64(2, "D"), days, lead, alpha=0.1)
    raw_cov, _ = coverage(lo, hi, y)
    cov, n = coverage(clo, chi, y)
    assert raw_cov < 0.6 and 0.85 < cov < 0.95 and n > 0.8 * y.size


def test_defer_thresholds_use_previous_quarter_only():
    rng = np.random.default_rng(4)
    n = 40000
    init = np.sort(rng.choice(pd.date_range("2024-01-01", "2024-12-31").values, n))
    err, spread = rng.gamma(2, 1, n), rng.gamma(2, 1, n)
    f1 = defer_flags(err, spread, init)
    q = pd.DatetimeIndex(init).to_period("Q")
    err2 = err.copy()
    err2[q == pd.Period("2024Q4")] *= 10  # change the future quarter
    f2 = defer_flags(err2, spread, init)
    assert np.array_equal(f1[q == pd.Period("2024Q3")], f2[q == pd.Period("2024Q3")])
    assert not f1[q == pd.Period("2024Q1")].any()  # no previous quarter
    assert 0.01 < f1[q == pd.Period("2024Q2")].mean() < 0.1


def test_explanation_sentence_is_grounded_in_its_inputs():
    s = explanation_sentence(
        "Wayanad",
        "precip",
        2,
        87.34,
        {"ecmwf_aifs": 0.46, "ncep_gfs": 0.3, "dwd_icon": 0.24},
        "monsoon_active",
        top_features(np.array([[1.0, 0.2], [0.5, 0.1]]), ["rel_dmse", "spread"]),
        defer=True,
        p_heavy=0.62,
    )
    for token in (
        "87.3 mm",
        "46 %",
        "30 %",
        "62 %",
        "monsoon active",
        "forecaster review",
        "Not an official warning",
    ):
        assert token in s


def test_explanation_sentence_says_equal_weights_when_blender_disabled():
    s = explanation_sentence(
        "Kottayam",
        "precip",
        1,
        12.0,
        {"ecmwf_aifs": 0.2, "ncep_gfs": 0.2, "ecmwf_ifs_ens": 0.2, "a": 0.2, "b": 0.2},
        "monsoon_break",
        [],
        defer=False,
    )
    assert "weighted equally" in s and "leans most" not in s
