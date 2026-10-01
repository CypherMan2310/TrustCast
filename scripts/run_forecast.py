"""Produce live TRUSTCAST products for the newest 00Z runs.

    python scripts/run_forecast.py                 # all regions/variables, newest 3 inits
    python scripts/run_forecast.py --inits 1 --regions rain_pilot --variables precip

The live product runs the same walk-forward pipeline as the evaluation, with hyperparameters and layer
choices frozen in config/model_selection.yaml (development split only). It uses operationally collected
recent data (2026) for the skill tracker and quarterly refits, but nothing here scores or tunes on the
frozen test period. Forecaster overrides (SQLite) feed the skill state via DMSE penalties.
Output: data/products/<region>/<variable>/<YYYYmmdd>.{nc,json} and latest.json.
"""

from __future__ import annotations

import argparse
import datetime as dt
import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from trustcast.config import data_root, load_config
from trustcast.grid.districts import district_table
from trustcast.grid.static import static_features
from trustcast.io import AlreadyRunning, single_instance
from trustcast.log import setup_logging
from trustcast.pipeline import config_from_selection, run_pipeline
from trustcast.products import write_products
from trustcast.skill.overrides import connect, load_overrides, penalty_factors
from trustcast.verify.assemble import assemble, climatology, frozen_sources


def produce(cfg, root, region: str, variable: str, n_inits: int) -> str:
    b = assemble(
        cfg, root, region, variable, allow_test=True, sources=frozen_sources(region, variable)
    )
    if b is None:
        return "no data"
    land = np.isfinite(b.truth).any("time")
    pc, provenance = config_from_selection(region, variable)
    table, _ = district_table(cfg, root, region)
    ov = load_overrides(connect(root / "app" / "overrides.sqlite"), variable)
    pen = penalty_factors(ov, table, b.like, [f.name for f in b.forecasts]) if len(ov) else None
    res = run_pipeline(
        b,
        pc,
        climatology(cfg, root, region, variable),
        static_features(cfg, root, region, land.values),
        pen,
    )
    have = np.isfinite(res.final_det).any(("lead_h", "lat", "lon")).values
    inits = [pd.Timestamp(t) for t in res.final_det.init_time.values[have]][-n_inits:]
    if not inits:
        return "no init with a blended forecast"
    avail = {
        pd.Timestamp(t).strftime("%Y-%m-%d"): [
            f.name for f in b.forecasts if np.isfinite(f.det.sel(init_time=t)).any()
        ]
        for t in inits
    }
    meta = {
        "gate": pc.gate,
        "config": pc.__dict__ | {"learn_start": str(pc.learn_start)},
        "config_provenance": provenance,
        "sources_available": avail,
        "generated_at": dt.datetime.now(dt.UTC).isoformat(),
        "truth_note": "skill tracker uses IMD where available, else IMERG (provisional)",
        "overrides_applied": len(ov),
    }
    write_products(res, b, inits, table, root, gate_on=pc.gate, meta=meta)
    return f"wrote {len(inits)} inits, latest {inits[-1]:%Y-%m-%d} ({provenance})"


def main() -> int:
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    ap.add_argument("--regions", nargs="+", default=None)
    ap.add_argument("--variables", nargs="+", default=["precip", "tmax"])
    ap.add_argument("--inits", type=int, default=3)
    args = ap.parse_args()
    cfg = load_config()
    root = data_root()
    setup_logging(root / "logs" / "run_forecast.jsonl")
    try:
        with single_instance(root / "logs" / "run_forecast.lock"):
            for region in args.regions or list(cfg.regions):
                for var in args.variables:
                    print(
                        f"{region} {var}: {produce(cfg, root, region, var, args.inits)}", flush=True
                    )
    except AlreadyRunning as e:
        print(f"skipped: {e}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
