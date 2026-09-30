"""API contract tests on a SYNTHETIC product built by the real pipeline in a temp data root."""

import json

import numpy as np
import pandas as pd
import pytest
from fastapi.testclient import TestClient

from tests.test_pipeline import _bundle
from trustcast import DISCLAIMER
from trustcast.pipeline import PipelineConfig, run_pipeline
from trustcast.products import write_products


@pytest.fixture(scope="module")
def client(tmp_path_factory):
    root = tmp_path_factory.mktemp("data")
    reports = tmp_path_factory.mktemp("reports")
    b = _bundle()
    b.region = "rain_pilot"  # real region name, SYNTHETIC values
    res = run_pipeline(
        b, PipelineConfig(learn_start=pd.Timestamp("2024-07-01"), min_train_rows=2000)
    )
    lat, lon = b.like.lat.values, b.like.lon.values
    table = pd.DataFrame(
        {
            "district_id": ["kerala-testdistrict"] * 4,
            "district": ["Testdistrict"] * 4,
            "state": ["Kerala"] * 4,
            "lat": [lat[1], lat[1], lat[2], lat[2]],
            "lon": [lon[1], lon[2], lon[1], lon[2]],
            "weight": [1.0] * 4,
            "coverage": [1.0] * 4,
        }
    )
    last = pd.Timestamp(b.like.init_time.values[-1])
    write_products(
        res,
        b,
        [last - pd.Timedelta(days=1), last],
        table,
        root,
        gate_on=True,
        meta={"gate": True, "synthetic": True},
    )
    (root / "replays").mkdir()
    (root / "replays" / "test_event.json").write_text(
        json.dumps(
            {
                "event_id": "test_event",
                "title": "SYNTHETIC event",
                "region": "rain_pilot",
                "variable": "precip",
                "district_id": "kerala-testdistrict",
                "focus_day": "2024-07-30",
                "observed": {"2024-07-30": 120.0},
                "series": [
                    {"forecast": "trustcast", "lead_day": 1, "values": {"2024-07-30": 95.0}}
                ],
            }
        )
    )
    (reports / "phase2").mkdir()
    pd.DataFrame(
        [
            {
                "sample": "main",
                "region": "rain_pilot",
                "variable": "precip",
                "season": "all",
                "forecast": "ncep_gfs",
                "kind": "source",
                "lead_day": 1,
                "rmse": 10.0,
                "rmse_lo": 9.0,
                "rmse_hi": 11.0,
                "crps": 5.0,
                "ets_64.5": 0.2,
                "n_cases": 100,
            }
        ]
    ).to_csv(reports / "phase2" / "scoreboard_full.csv", index=False)
    import os

    os.environ["TRUSTCAST_DATA_DIR"] = str(root)
    os.environ["TRUSTCAST_REPORTS_DIR"] = str(reports)
    from trustcast.api.app import app

    with TestClient(app) as c:
        yield c, last
    os.environ.pop("TRUSTCAST_DATA_DIR")
    os.environ.pop("TRUSTCAST_REPORTS_DIR")


def test_openapi_and_disclaimer_everywhere(client):
    c, _ = client
    spec = c.get("/openapi.json").json()
    for path in (
        "/v1/health",
        "/v1/sources",
        "/v1/forecast/blend",
        "/v1/forecast/grid",
        "/v1/skill/map",
        "/v1/skill/leaderboard",
        "/v1/verification/summary",
        "/v1/alerts/district",
        "/v1/explain/{district_id}",
        "/v1/bulletin/{district_id}",
        "/v1/replay/{event_id}",
        "/v1/feedback/override",
    ):
        assert path in spec["paths"], path
    for url in (
        "/v1/health",
        "/v1/sources",
        "/v1/verification/summary",
        "/v1/replay/test_event",
        "/v1/forecast/grid?region=rain_pilot&variable=precip",
    ):
        r = c.get(url)
        assert r.status_code == 200, (url, r.text[:200])
        assert r.json()["disclaimer"] == DISCLAIMER


def test_grid_and_point(client):
    c, last = client
    g = c.get(
        "/v1/forecast/grid", params={"region": "rain_pilot", "lead_day": 2, "layer": "prob_ge_64.5"}
    ).json()
    assert len(g["values"]) == len(g["lats"]) and len(g["values"][0]) == len(g["lons"])
    assert g["units"] == "probability" and "source:good" in g["available_layers"]
    assert g["init_time"].startswith(str(last.date()))
    p = c.get(
        "/v1/forecast/blend", params={"lat": 10.0, "lon": 76.0}
    ).json()  # (10, 76) is sea -> nearest land
    assert (p["cell_lat"], p["cell_lon"]) != (10.0, 76.0)
    assert len(p["leads"]) == 2 and abs(sum(p["leads"][0]["weights"].values()) - 1) < 1e-3
    assert c.get("/v1/forecast/grid", params={"region": "nowhere"}).status_code == 404
    assert (
        c.get("/v1/forecast/grid", params={"region": "rain_pilot", "layer": "bogus"}).status_code
        == 404
    )
    assert c.get("/v1/forecast/blend", params={"lat": 30.0, "lon": 90.0}).status_code == 404
    assert (
        c.get("/v1/forecast/grid", params={"region": "heat_pilot"}).status_code == 503
    )  # no products


def test_skill_endpoints(client):
    c, _ = client
    sm = c.get("/v1/skill/map", params={"region": "rain_pilot"}).json()
    assert sm["cells"] and all(
        cell["best_source"] in ("good", "bad", "ens", None) for cell in sm["cells"]
    )
    lb = c.get("/v1/skill/leaderboard", params={"region": "rain_pilot"}).json()
    assert lb["rows"][0]["rmse"] == 10.0


def test_alerts_explain_bulletin_cap(client):
    c, _ = client
    a = c.get("/v1/alerts/district", params={"region": "rain_pilot", "min_level": "none"}).json()
    assert a["alerts"] and {x["level"] for x in a["alerts"]} <= {"none", "yellow", "orange", "red"}
    e = c.get("/v1/explain/kerala-testdistrict").json()
    assert e["top_features"] and "Not an official warning" in e["sentence"]
    for lang in ("en", "hi"):
        bl = c.get(f"/v1/bulletin/kerala-testdistrict?lang={lang}").json()
        assert bl["validated"] and bl["validation_errors"] == []
    cap = c.get("/v1/alerts/cap/kerala-testdistrict")
    assert cap.status_code == 200 and cap.headers["content-type"].startswith("application/xml")
    assert "<status>Draft</status>" in cap.text
    assert c.get("/v1/explain/nobody").status_code == 404


def test_override_roundtrip(client):
    c, _ = client
    body = {
        "district_id": "kerala-testdistrict",
        "variable": "precip",
        "valid_day": "2024-07-30",
        "value": 150.0,
        "distrust_sources": ["bad"],
        "reason": "orographic enhancement missed",
        "author": "forecaster-1",
    }
    r = c.post("/v1/feedback/override", json=body)
    assert r.status_code == 200 and r.json()["id"] >= 1 and "penalised" in r.json()["effect"]
    bl = c.get("/v1/bulletin/kerala-testdistrict").json()
    assert "orographic enhancement missed" in bl["text"] and bl["validated"]
    assert c.post("/v1/feedback/override", json={**body, "reason": "no"}).status_code == 422
    assert np.isfinite(r.json()["stored"]["value"])


def test_district_and_products_index(client):
    c, last = client
    d = c.get("/v1/district/kerala-testdistrict").json()
    assert d["district"]["district"] == "Testdistrict" and len(d["district"]["leads"]) == 2
    idx = c.get("/v1/products").json()["products"]["rain_pilot/precip"]
    assert idx[0] == f"{last:%Y%m%d}" and len(idx) == 2
