"""L5 event gate (ETS, paired block bootstrap). SYNTHETIC data."""

import numpy as np
import pandas as pd
import xarray as xr

from trustcast.verify.compare import event_verdict


def _da(v, inits, leads):
    vd = inits.values[:, None] + (leads.astype("timedelta64[h]") - np.timedelta64(3, "h"))[None, :]
    return xr.DataArray(
        v,
        dims=("init_time", "lead_h", "lat", "lon"),
        coords={
            "init_time": inits,
            "lead_h": leads,
            "lat": [10.0, 10.25],
            "lon": [76.0, 76.25],
            "valid_day": (("init_time", "lead_h"), vd),
        },
    )


def test_event_gate_rewards_event_skill_not_rmse():
    rng = np.random.default_rng(0)
    inits = pd.date_range("2025-01-01", periods=300)
    leads = np.array([27, 51, 75, 99, 123])
    shape = (inits.size, leads.size, 2, 2)
    obs = rng.gamma(0.5, 30.0, shape)
    sharp = obs * rng.uniform(0.8, 1.2, shape)  # catches heavy days
    smooth = np.minimum(obs, 60.0)  # never reaches 64.5 mm
    mask = xr.DataArray(np.ones((inits.size, leads.size), bool), dims=("init_time", "lead_h"))
    v = event_verdict(
        _da(sharp, inits, leads), _da(smooth, inits, leads), _da(obs, inits, leads), 64.5, mask, 200
    )
    assert v["passes"] and v["leads_significantly_better"] == 5
    v2 = event_verdict(
        _da(smooth, inits, leads), _da(sharp, inits, leads), _da(obs, inits, leads), 64.5, mask, 200
    )
    assert not v2["passes"] and v2["leads_significantly_worse"] == 5
