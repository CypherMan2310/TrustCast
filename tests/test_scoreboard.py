"""Scoreboard and skill table on SYNTHETIC forecasts."""

import numpy as np
import pandas as pd
import pyarrow.parquet as pq
import pytest
import xarray as xr

from trustcast.verify.scoreboard import Forecast, reliability, scoreboard, write_skill_table

INITS = pd.date_range("2024-06-01", periods=120, freq="D")
LEADS = np.array([27, 51], dtype=np.int16)


def _da(values):
    vd = INITS.values[:, None] + (LEADS.astype("timedelta64[h]") - np.timedelta64(3, "h"))[None, :]
    return xr.DataArray(
        values.astype(np.float32),
        dims=("init_time", "lead_h", "lat", "lon"),
        coords={
            "init_time": INITS,
            "lead_h": LEADS,
            "lat": [10.0, 10.25, 10.5],
            "lon": [76.0, 76.25],
            "valid_day": (("init_time", "lead_h"), vd),
        },
    )


@pytest.fixture
def setup():
    rng = np.random.default_rng(0)  # SYNTHETIC
    obs = _da(rng.gamma(0.5, 30, (120, 2, 3, 2)))
    perfect = Forecast("perfect", "source", obs.copy())
    noisy = Forecast("noisy", "source", _da(obs.values + rng.normal(0, 15, obs.shape)))
    members = obs.values[:, None] + rng.normal(0, 10, (120, 11, 2, 3, 2))
    ens_da = xr.DataArray(
        members.astype(np.float32),
        dims=("init_time", "member", "lead_h", "lat", "lon"),
        coords={
            **{k: obs.coords[k] for k in ("init_time", "lead_h", "lat", "lon")},
            "valid_day": obs.valid_day,
        },
    )
    ens = Forecast("ens", "source", ens_da.mean("member"), ens_da)
    return obs, [perfect, noisy, ens]


def test_scoreboard_scores_and_paired_diffs(setup):
    obs, fcs = setup
    sb = scoreboard(fcs, obs, "precip", "test", reference="noisy", n_boot=200)
    allp = sb[(sb.season == "all") & (sb.lead_day == 1)].set_index("forecast")
    assert allp.loc["perfect", "rmse"] == pytest.approx(0.0, abs=1e-5)
    assert allp.loc["perfect", "ets_64.5"] == pytest.approx(1.0)
    assert allp.loc["noisy", "rmse"] == pytest.approx(15, rel=0.1)
    assert allp.loc["noisy", "rmse_lo"] < allp.loc["noisy", "rmse"] < allp.loc["noisy", "rmse_hi"]
    # perfect is significantly better than the reference; the reference has no diff with itself
    assert allp.loc["perfect", "d_rmse_hi"] < 0
    assert pd.isna(allp.loc["noisy"].get("d_rmse_vs_ref", np.nan))
    # ensemble CRPS uses members (smaller than its own MAE)
    assert allp.loc["ens", "crps"] < allp.loc["ens", "mae"] + 1e-6
    # seasons present: June-September inits -> monsoon and post-monsoon strata
    assert {"all", "monsoon_JJAS"} <= set(sb.season)


def test_scoreboard_common_sample_makes_rows_comparable(setup):
    obs, fcs = setup
    gap = Forecast("gappy", "source", fcs[1].det.where(fcs[1].det.init_time > INITS[60]))

    def n(sb, name):
        return sb[(sb.forecast == name) & (sb.season == "all") & (sb.lead_day == 1)].iloc[0].n_cases

    common = scoreboard([*fcs, gap], obs, "precip", "test", reference="noisy", n_boot=100)
    assert n(common, "gappy") == n(common, "noisy") == n(common, "perfect") == 59 * 6
    own = scoreboard(
        [*fcs, gap], obs, "precip", "test", reference="noisy", n_boot=100, common=False
    )
    assert n(own, "gappy") == 59 * 6 and n(own, "noisy") == 120 * 6


def test_scoreboard_window_restricts_valid_days(setup):
    obs, fcs = setup
    sb = scoreboard(
        fcs,
        obs,
        "precip",
        "test",
        reference="noisy",
        n_boot=50,
        window=(pd.Timestamp("2024-08-01"), None),
    )
    row = sb[(sb.forecast == "noisy") & (sb.season == "all") & (sb.lead_day == 1)].iloc[0]
    vd = pd.DatetimeIndex(obs.valid_day.isel(lead_h=0).values)
    assert row.n_cases == int((vd >= pd.Timestamp("2024-08-01")).sum()) * 6


def test_reliability_only_for_ensembles(setup):
    obs, fcs = setup
    rel = reliability(fcs, obs, 64.5, 0)
    assert set(rel.forecast) == {"ens"} and rel.n.sum() > 0


def test_skill_table_contract(setup, tmp_path):
    obs, fcs = setup
    paths = write_skill_table(fcs[:2], obs, "precip", "test", tmp_path)
    t = pq.read_table(paths[0]).to_pandas()
    for col in (
        "source",
        "variable",
        "cell_or_subdivision",
        "lead_bucket",
        "season",
        "valid_time",
        "error",
        "abs_error",
        "sq_error",
        "event_hit_flags",
        "regime",
    ):
        assert col in t.columns
    assert len(t) == 120 * 2 * 6
    heavy_obs = (t.observed >= 64.5).to_numpy()
    assert np.array_equal((t.event_hit_flags.to_numpy() >> 1) & 1, heavy_obs.astype(int))


def test_regime_strata(setup):
    obs, fcs = setup
    labels = np.where(np.arange(120)[:, None] % 2 == 0, "monsoon_active", "monsoon_break")
    regimes = xr.DataArray(
        np.broadcast_to(labels, (120, 2)),
        dims=("init_time", "lead_h"),
        coords={"init_time": INITS, "lead_h": LEADS},
    )
    sb = scoreboard(fcs, obs, "precip", "test", reference="noisy", n_boot=50, regimes=regimes)
    r = sb[(sb.forecast == "noisy") & (sb.lead_day == 1)].set_index(["season", "regime"]).n_cases
    assert r[("all", "monsoon_active")] + r[("all", "monsoon_break")] == r[("all", "all")]
    from trustcast.verify.scoreboard import overall

    assert set(overall(sb).regime) == {"all"} and set(overall(sb).season) == {"all"}
