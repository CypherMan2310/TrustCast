"""SYNTHETIC TEST FIXTURE: fake Open-Meteo responses for unit tests only.

Never used by the pipeline, the API or the UI. Values are deterministic and meaningless.
"""

from __future__ import annotations

import datetime as dt
import json
from typing import Any

import httpx
import numpy as np
import pandas as pd

SYNTHETIC_LABEL = "SYNTHETIC TEST FIXTURE: not real data"


def fake_location(
    lat: float,
    lon: float,
    init: dt.datetime,
    hours: int,
    null_first_precip: bool = True,
    all_null: str | None = None,
) -> dict[str, Any]:
    """One location's Single Runs JSON object with synthetic hourly values."""
    times = pd.date_range(init, periods=hours, freq="h").strftime("%Y-%m-%dT%H:%M").tolist()
    precip = [round(0.1 * ((h + int(lat * 4)) % 7), 2) for h in range(hours)]
    temp = [round(25 + 0.1 * lat + 3 * np.sin(2 * np.pi * h / 24), 2) for h in range(hours)]
    if null_first_precip:
        precip[0] = None
    if all_null == "precipitation":
        precip = [None] * hours
    if all_null == "temperature_2m":
        temp = [None] * hours
    return {
        "latitude": lat,
        "longitude": lon,
        "_label": SYNTHETIC_LABEL,
        "hourly": {"time": times, "precipitation": precip, "temperature_2m": temp},
    }


def meta_json(last_init: dt.datetime) -> dict[str, Any]:
    """Synthetic meta.json body."""
    ts = int(last_init.replace(tzinfo=dt.UTC).timestamp())
    return {"last_run_initialisation_time": ts, "_label": SYNTHETIC_LABEL}


def make_transport(
    last_inits: dict[str, dt.datetime], hours: int, broken_models: dict[str, str] | None = None
) -> httpx.MockTransport:
    """A MockTransport serving meta.json and single-runs requests.

    ``broken_models`` maps a model id to a failure mode: "empty", "400", "all_null".
    """
    broken = broken_models or {}

    def handler(request: httpx.Request) -> httpx.Response:
        url = str(request.url)
        if url.endswith("meta.json"):
            meta_id = request.url.path.split("/")[2]
            return httpx.Response(200, json=meta_json(last_inits[meta_id]))
        q = request.url.params
        model = q["models"]
        mode = broken.get(model)
        if mode == "empty":
            return httpx.Response(200, content=b"")
        if mode == "400":
            return httpx.Response(400, json={"error": True, "reason": "run not available"})
        init = dt.datetime.fromisoformat(q["run"])
        lats = [float(x) for x in q["latitude"].split(",")]
        lons = [float(x) for x in q["longitude"].split(",")]
        locs = [
            fake_location(
                a,
                b,
                init,
                int(q["forecast_hours"]),
                all_null="precipitation" if mode == "all_null" else None,
            )
            for a, b in zip(lats, lons, strict=True)
        ]
        body = locs if len(locs) > 1 else locs[0]
        return httpx.Response(200, content=json.dumps(body).encode())

    return httpx.MockTransport(handler)
