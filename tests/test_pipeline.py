"""End-to-end pipeline on a SYNTHETIC bundle (all layers enabled)."""

import numpy as np
import pandas as pd
import xarray as xr

from trustcast.pipeline import PipelineConfig, run_pipeline
from trustcast.verify.assemble import Bundle
from trustcast.verify.scoreboard import Forecast

INITS = pd.date_range("2024-01-01", periods=400, freq="D")
LEADS = np.array([27, 51], dtype=np.int16)
LAT, LON = np.arange(10.0, 11.5, 0.25), np.arange(76.0, 77.0, 0.25)
SHAPE = (INITS.size, 2, LAT.size, LON.size)


def _coords():
    vd = INITS.values[:, None] + (LEADS.astype("timedelta64[h]") - np.timedelta64(3, "h"))[None, :]
    return {
        "init_time": INITS,
        "lead_h": LEADS,
        "lat": LAT,
        "lon": LON,
        "valid_day": (("init_time", "lead_h"), vd),
    }


def _da(v):
    return xr.DataArray(
        np.asarray(v, np.float32), dims=("init_time", "lead_h", "lat", "lon"), coords=_coords()
    )


def _bundle(seed=0):
    rng = np.random.default_rng(seed)
    truth = rng.gamma(0.6, 20, SHAPE)
    truth[:, :, 0, 0] = np.nan  # one sea cell
    ens = truth[:, None] * rng.lognormal(0, 0.5, (INITS.size, 7, *SHAPE[1:]))
    ens_da = xr.DataArray(
        ens.astype(np.float32),
        dims=("init_time", "member", "lead_h", "lat", "lon"),
        coords={**_coords(), "member": np.arange(7)},
    )
    fcs = [
        Forecast("good", "source", _da(np.nan_to_num(truth) * 1.3 + rng.normal(0, 3, SHAPE))),
        Forecast("bad", "source", _da(np.nan_to_num(truth) * 0.5 + rng.normal(0, 15, SHAPE))),
        Forecast("ens", "source", ens_da.mean("member"), ens_da),
    ]
    days = pd.date_range("2024-01-02", periods=INITS.size + 2)
    tvals = np.full((days.size, LAT.size, LON.size), np.nan, np.float32)
    obs = _da(truth)
    vd = pd.DatetimeIndex(obs.valid_day.values[:, 0])
    tvals[np.searchsorted(days, vd)] = truth[:, 0]
    tr = xr.DataArray(
        tvals, dims=("time", "lat", "lon"), coords={"time": days, "lat": LAT, "lon": LON}
    )
    return Bundle("test", "precip", fcs, obs, tr)


def test_full_pipeline_runs_and_improves_on_the_worst_source():
    b = _bundle()
    res = run_pipeline(
        b, PipelineConfig(learn_start=pd.Timestamp("2024-07-01"), min_train_rows=2000)
    )
    late = res.final_det.init_time >= np.datetime64("2024-10-01")
    err = lambda f: float(np.sqrt(((f - b.obs).where(late) ** 2).mean()))  # noqa: E731
    assert err(res.final_det) < err(b.get("bad").det)
    assert np.isnan(res.final_det.values[:, :, 0, 0]).all()  # sea cell masked
    assert np.allclose(
        res.weights.sum("source")
        .where(res.weights.sum("source") > 0)
        .dropna("init_time", how="all")
        .values[
            np.isfinite(res.weights.sum("source").values) & (res.weights.sum("source").values > 0)
        ],
        1.0,
        atol=1e-4,
    )
    w = res.weights.where(late).mean(("init_time", "lead_h", "lat", "lon"))
    assert float(w.sel(source="good")) > float(w.sel(source="bad"))
    p = res.probs[64.5].where(late)
    assert np.isfinite(p).sum() > 0 and float(p.max()) <= 1 and float(p.min()) >= 0
    cov = ((b.obs >= res.lo) & (b.obs <= res.hi)).where(np.isfinite(res.lo) & np.isfinite(b.obs))
    assert 0.8 < float(cov.mean()) < 0.97
    assert res.defer.dtype == bool and res.regimes.shape == (INITS.size, 2)


def test_pipeline_ablation_switches():
    b = _bundle(1)
    lean = run_pipeline(
        b,
        PipelineConfig(
            qm=False, gate=False, extremes=False, uncertainty=False, exclude_sources=("bad",)
        ),
    )
    assert lean.gate is None and not lean.probs and lean.lo is None
    assert list(lean.weights.source.values) == ["good", "ens"]
