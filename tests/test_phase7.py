"""Overrides, bulletins, CAP and district aggregation (SYNTHETIC data)."""

import datetime as dt

import numpy as np
import pandas as pd
import pytest
import xarray as xr

from trustcast.alerts.bulletin import bulletin_numbers, render, validate
from trustcast.alerts.cap import alert_level, build_cap, check_cap
from trustcast.blend.decayed import blend_a
from trustcast.grid.districts import district_means
from trustcast.skill.overrides import add_override, connect, load_overrides, penalty_factors

INITS = pd.date_range("2024-07-01", periods=30, freq="D")
LEADS = np.array([27, 51], dtype=np.int16)
LAT, LON = np.array([11.5, 11.75]), np.array([76.0, 76.25])


def _da(v):
    vd = INITS.values[:, None] + (LEADS.astype("timedelta64[h]") - np.timedelta64(3, "h"))[None, :]
    return xr.DataArray(
        np.asarray(v, np.float32),
        dims=("init_time", "lead_h", "lat", "lon"),
        coords={
            "init_time": INITS,
            "lead_h": LEADS,
            "lat": LAT,
            "lon": LON,
            "valid_day": (("init_time", "lead_h"), vd),
        },
    )


DISTRICTS = pd.DataFrame(
    {
        "district_id": ["kerala-wayanad"] * 2 + ["kerala-kozhikode"] * 2,
        "district": ["Wayanad"] * 2 + ["Kozhikode"] * 2,
        "state": ["Kerala"] * 4,
        "lat": [11.5, 11.75, 11.5, 11.75],
        "lon": [76.0, 76.0, 76.25, 76.25],
        "weight": [1.0, 3.0, 1.0, 1.0],
        "coverage": [1.0] * 4,
    }
)


def test_override_penalty_changes_later_weights_only(tmp_path):
    con = connect(tmp_path / "ov.sqlite")
    oid = add_override(
        con,
        "kerala-wayanad",
        "precip",
        dt.date(2024, 7, 16),
        120.0,
        ["a"],
        "IFS missed the orographic enhancement",
        "forecaster-1",
        created_at=dt.datetime(2024, 7, 15, 6),
    )
    ov = load_overrides(con, "precip")
    assert oid == 1 and ov.distrust_sources.iloc[0] == ["a"]
    like = _da(np.zeros((30, 2, 2, 2)))
    pen = penalty_factors(ov, DISTRICTS, like, ["a", "b"])
    before = pen["a"].sel(init_time="2024-07-15").values  # 00Z, before the override
    after = pen["a"].sel(init_time="2024-07-16").values
    assert np.allclose(before, 1.0) and np.allclose(pen["b"].values, 1.0)
    assert np.allclose(
        after[:, :, 0], 1 + 0.5 ** (18 / 24 / 7), atol=1e-4
    )  # Wayanad cells (lon 76.0)
    assert np.allclose(after[:, :, 1], 1.0)  # Kozhikode untouched
    dm = {"a": _da(np.full((30, 2, 2, 2), 4.0)), "b": _da(np.full((30, 2, 2, 2), 4.0))}
    x = {"a": _da(np.ones((30, 2, 2, 2))), "b": _da(np.ones((30, 2, 2, 2)))}
    _, w0 = blend_a(x, dm, 1)
    _, w1 = blend_a(x, {k: v * pen[k] for k, v in dm.items()}, 1)
    assert float(w1.sel(source="a").isel(init_time=20, lat=0, lon=0, lead_h=0)) < 0.5
    assert float(w1.sel(source="a").isel(init_time=5, lat=0, lon=0, lead_h=0)) == pytest.approx(
        float(w0.sel(source="a").isel(init_time=5, lat=0, lon=0, lead_h=0))
    )


def _payload():
    def lead(k, v, p):
        return {
            "lead_day": k,
            "valid_day": f"2024-07-{29 + k}",
            "value": v,
            "lo90": v * 0.4,
            "hi90": v * 1.9,
            "probabilities": {"64.5": p, "115.6": p / 2},
            "weights": {"ecmwf_aifs": 0.5, "ncep_gfs": 0.3, "dwd_icon": 0.2},
            "defer": k == 2,
            "regime": "monsoon_active",
        }

    return {
        "district": "Wayanad",
        "state": "Kerala",
        "leads": [lead(1, 142.6, 0.81), lead(2, 88.0, 0.55), lead(3, 30.2, 0.12)],
    }


@pytest.mark.parametrize("lang", ["en", "hi"])
def test_bulletin_numbers_all_come_from_the_payload(lang):
    d = _payload()
    text = render(d, "precip", lang)
    nums = bulletin_numbers(d, "precip")
    assert validate(text, nums) == []
    assert ("142.6" in text) and ("81 %" in text)
    assert ("Not an official warning" in text) if lang == "en" else ("आधिकारिक चेतावनी नहीं" in text)
    assert validate(text + " Expected 999.9 mm tomorrow.", nums) == ["999.9"]


def test_cap_is_valid_draft_and_levels():
    xml = build_cap(
        "Wayanad",
        "Kerala",
        "Heavy rain (decision support)",
        "red",
        0.81,
        dt.datetime(2024, 7, 29, 3, tzinfo=dt.UTC),
        dt.datetime(2024, 7, 30, 3, tzinfo=dt.UTC),
        [(11.5, 76.0), (11.9, 76.0), (11.9, 76.4)],
        "Heavy rain likely",
        "IMD day 2024-07-30.",
    )
    assert check_cap(xml) == []
    assert "<status>Draft</status>" in xml and "Not an official warning" in xml
    assert check_cap(xml.replace("Draft", "Actual")) == [
        "status must be Draft for decision-support output"
    ]
    assert [alert_level(p) for p in (None, 0.1, 0.25, 0.5, 0.9)] == [
        "none",
        "none",
        "yellow",
        "orange",
        "red",
    ]


def test_district_means_area_weighted():
    f = xr.DataArray(
        np.array([[[10.0, 1.0], [30.0, np.nan]]]),
        dims=("t", "lat", "lon"),
        coords={"t": [0], "lat": LAT, "lon": LON},
    )
    m = district_means(f, DISTRICTS).set_index("district_id").value
    assert m["kerala-wayanad"] == pytest.approx((10 * 1 + 30 * 3) / 4)
    assert m["kerala-kozhikode"] == pytest.approx(1.0)  # NaN cell ignored
