"""Build canonical forecasts for every eval adapter plus truth for a run of 00Z inits.

    python scripts/build_canonical.py --region rain_pilot --start 2025-10-20 --days 7
    python scripts/build_canonical.py --region heat_pilot --start 2025-10-20 --days 7 --adapters aifs_dyn

Writes (under the data root):
    processed/canonical/<adapter>/<region>/<start>_<end>.zarr     canonical_v1
    processed/truth/<region>/<first>_<last>.zarr                    truth_v1
    processed/reports/alignment_<region>_<start>_<end>.md           sanity report (not verification)

A failing adapter is logged and reported; the others continue (graceful degradation).
Refuses to touch the frozen test period (2026-01-01 .. 2026-09-30) unless --allow-test is given.
"""

from __future__ import annotations

import argparse
import datetime as dt
import logging
import sys
import time
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from trustcast.adapters.base import SourceError
from trustcast.adapters.openmeteo_adapters import OpenMeteoPreviousRunsAdapter
from trustcast.adapters.registry import build_adapters
from trustcast.config import data_root, load_config
from trustcast.grid.diagnostics import lag_correlation
from trustcast.grid.schema import validate_canonical, validate_truth
from trustcast.io import write_zarr_atomic
from trustcast.log import event, setup_logging
from trustcast.truth.build import build_truth

log = logging.getLogger("build_canonical")
TEST_START, TEST_END = pd.Timestamp("2026-01-01"), pd.Timestamp("2026-09-30")


def _write(ds, path: Path) -> None:
    write_zarr_atomic(ds, path)


def main() -> int:
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    ap.add_argument("--region", default="rain_pilot")
    ap.add_argument("--start", required=True, help="first 00Z init date, YYYY-MM-DD")
    ap.add_argument("--days", type=int, default=7)
    ap.add_argument("--adapters", nargs="+", default=None)
    ap.add_argument("--allow-test", action="store_true", help="permit dates in the frozen test set")
    args = ap.parse_args()

    cfg = load_config()
    root = data_root()
    setup_logging(root / "logs" / "build_canonical.jsonl")
    region = cfg.regions[args.region]
    inits = pd.date_range(args.start, periods=args.days, freq="D")
    lead_days = cfg.canonical.lead_days
    valid_days = pd.date_range(
        inits[0] + pd.Timedelta(days=1), inits[-1] + pd.Timedelta(days=lead_days)
    )
    touches_test = (valid_days >= TEST_START).any() and (inits <= TEST_END).any()
    if touches_test and not args.allow_test:
        print(
            "refusing: these dates overlap the frozen test period (use --allow-test only in Phase 8)"
        )
        return 2
    tag = f"{inits[0]:%Y%m%d}_{inits[-1]:%Y%m%d}"

    adapters = build_adapters(cfg, root, use="eval")
    if args.adapters:
        adapters = {k: v for k, v in adapters.items() if k in args.adapters}

    t0 = time.monotonic()
    truth = build_truth(root, valid_days, region)
    validate_truth(truth)
    _write(
        truth,
        root
        / "processed"
        / "truth"
        / args.region
        / f"{valid_days[0]:%Y%m%d}_{valid_days[-1]:%Y%m%d}.zarr",
    )
    print(
        f"truth: {truth.sizes['time']} days, provisional={int(truth.provisional.sum())} ({time.monotonic() - t0:.0f}s)"
    )

    rows = []
    for name, ad in adapters.items():
        t0 = time.monotonic()
        try:
            if isinstance(ad, OpenMeteoPreviousRunsAdapter):
                ds = ad.fetch_many(list(inits), region)
            else:
                import xarray as xr

                ds = xr.concat(
                    [ad.fetch(i, region) for i in inits], dim="init_time", combine_attrs="override"
                )
            validate_canonical(ds)
        except SourceError as e:
            event(log, logging.ERROR, "adapter failed", adapter=name, error=str(e))
            rows.append(
                {
                    "adapter": name,
                    "source": getattr(ad, "source", "?"),
                    "status": f"FAILED: {e}"[:160],
                }
            )
            print(f"{name:12s} FAILED {str(e)[:120]}")
            continue
        _write(ds, root / "processed" / "canonical" / name / args.region / f"{tag}.zarr")
        p = ds["precip_24h_mm"]
        # evaluate on IMD land cells only
        land = np.isfinite(truth["rain_mm"]).any("time")
        pl = p.where(land)
        red = [d for d in pl.dims if d not in ("lead_h",)]
        lag = lag_correlation(pl, truth["rain_mm"])
        rows.append(
            {
                "adapter": name,
                "source": ds.attrs["source"],
                "status": "ok",
                "members": int(ds.sizes.get("member", 1)),
                "nan_frac_precip": round(float(pl.isnull().where(land).mean()), 4),
                "nan_frac_tmax": round(
                    float(ds["tmax_c"].where(land).isnull().where(land).mean()), 4
                ),
                "mean_precip_by_lead": [round(float(v), 1) for v in pl.mean(red).values],
                "lag_r(-1,0,+1)": [round(lag[s], 3) for s in (-1, 0, 1)],
                "seconds": round(time.monotonic() - t0, 1),
            }
        )
        print(f"{name:12s} ok  lag r(-1,0,+1)={rows[-1]['lag_r(-1,0,+1)']}  {rows[-1]['seconds']}s")

    truth_mean = float(truth["rain_mm"].mean())
    report = root / "processed" / "reports" / f"alignment_{args.region}_{tag}.md"
    report.parent.mkdir(parents=True, exist_ok=True)
    lines = [
        f"# Alignment report: {args.region}, 00Z inits {inits[0]:%Y-%m-%d} .. {inits[-1]:%Y-%m-%d}",
        "",
        f"Generated {dt.datetime.now(dt.UTC):%Y-%m-%d %H:%M} UTC. Sanity checks only: NOT verification scores.",
        f"Truth: {truth.sizes['time']} IMD days {valid_days[0]:%Y-%m-%d}..{valid_days[-1]:%Y-%m-%d}, "
        f"provisional days: {int(truth.provisional.sum())}, mean rain over land cells {truth_mean:.1f} mm.",
        "lag_r = Pearson r of lead-day-1 rain (ensemble mean) vs truth on day D-1, D, D+1 (pooled land cells).",
        "Aligned day labels => the middle value is the largest.",
        "",
        pd.DataFrame(rows).to_markdown(index=False),
        "",
        "Decision-support tool. Not an official warning.",
    ]
    report.write_text("\n".join(lines), encoding="utf-8")
    print(f"report -> {report}")
    return 1 if any(r["status"] != "ok" and r["source"] != "ncmrwf_ncum" for r in rows) else 0


if __name__ == "__main__":
    sys.exit(main())
