"""LIVE smoke test against the real Open-Meteo API. Run with: pytest -m live"""

import datetime as dt

import numpy as np
import pytest

from trustcast.adapters.openmeteo import OpenMeteoSingleRuns
from trustcast.archive.cycles import floor_cycle
from trustcast.config import load_config
from trustcast.grid.schema import validate_archive

pytestmark = pytest.mark.live


def test_live_ifs_single_point():
    cfg = load_config()
    src = next(s for s in cfg.openmeteo.sources if s.source == "ecmwf_ifs")
    client = OpenMeteoSingleRuns(cfg.openmeteo, 48, cfg.archiver.hourly_variables)
    last = client.latest_init(src)
    assert (dt.datetime.now(dt.UTC).replace(tzinfo=None) - last).days < 2
    _, ds = client.fetch_run(
        src, floor_cycle(last, [0, 12]), np.array([10.0]), np.array([76.0]), "live_test"
    )
    validate_archive(ds)
    assert np.isfinite(ds.t2m_c.values).mean() > 0.95
