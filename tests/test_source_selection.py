"""Frozen source set: eligibility rule (SYNTHETIC init lists, no data values)."""

from types import SimpleNamespace

import pandas as pd
import xarray as xr

from trustcast.verify import assemble as asm


def _cfg():
    a = dict(use="eval", type="dynamical", enabled=True)
    return SimpleNamespace(
        adapters={
            "full": SimpleNamespace(source="full", **a),
            "late": SimpleNamespace(source="late", **a),
            "partial": SimpleNamespace(source="partial", **a),
            "short": SimpleNamespace(source="short", **a),
        }
    )


INITS = {
    "full": pd.date_range("2024-01-01", "2025-12-26"),
    "late": pd.date_range("2025-07-02", "2025-12-26"),  # provider started mid-split
    "partial": pd.date_range("2024-04-01", "2024-06-30").append(
        pd.date_range("2025-10-20", "2025-10-26")
    ),  # incomplete backfill
    "short": pd.date_range("2025-11-01", "2025-12-26"),  # too short to learn from
}


def test_eligibility(monkeypatch):
    def fake_load(root, name, region, allow_test=False):
        return xr.Dataset(coords={"init_time": INITS[name]})

    monkeypatch.setattr(asm, "load_canonical", fake_load)
    rows = {r["source"]: r for r in asm.source_coverage(_cfg(), None, "r")}
    assert rows["full"]["eligible"] and rows["full"]["coverage"] == 1.0
    assert rows["late"]["eligible"] and rows["late"]["first_init"] == "2025-07-02"
    assert not rows["partial"]["eligible"]
    assert not rows["short"]["eligible"]
    # test-period inits are never counted
    assert rows["full"]["n_inits"] == len(pd.date_range("2024-04-01", "2025-12-26"))
