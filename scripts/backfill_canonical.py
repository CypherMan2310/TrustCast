"""Backfill monthly canonical stores for the development period (resumable, quota-aware).

    python scripts/backfill_canonical.py --kind prev           # Open-Meteo Previous Runs adapters
    python scripts/backfill_canonical.py --kind dyn            # dynamical.org adapters
    python scripts/backfill_canonical.py --kind dyn --adapters aifs_dyn --regions rain_pilot --start 2024-04 --end 2024-06

Output: data/processed/canonical/<adapter>/<region>/<YYYYMM>.zarr (00Z inits of that month).
A month store is written once complete; existing stores are skipped. Inits whose windows would reach
into the frozen test period (valid day >= 2026-01-01) are never built here.
On quota exhaustion the script sleeps and retries; a single failing init is logged and recorded in
the store's ``missing_inits`` attribute; nothing is substituted.
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import logging
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pandas as pd
import xarray as xr

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from trustcast.adapters.base import QuotaExhausted, SourceError
from trustcast.adapters.dynamical import DynamicalAdapter
from trustcast.adapters.ledger import QuotaLedger
from trustcast.adapters.openmeteo import OpenMeteoSingleRuns
from trustcast.adapters.openmeteo_adapters import OpenMeteoPreviousRunsAdapter
from trustcast.adapters.registry import build_adapters
from trustcast.config import data_root, load_config
from trustcast.grid.schema import validate_canonical
from trustcast.io import write_zarr_atomic
from trustcast.log import event, setup_logging

log = logging.getLogger("backfill")
DEV_LAST_VALID_DAY = pd.Timestamp("2025-12-31")
QUOTA_SLEEP_S = 1200
DYN_WORKERS = 2  # measured: no speed-up beyond this (GEFS reads are bandwidth-bound)


def month_inits(month: pd.Period, lead_days: int, collect_test: bool = False) -> list[pd.Timestamp]:
    """00Z inits of ``month``.

    Default (development): only inits whose last lead window ends by the dev period end.
    ``collect_test``: every init up to today (data *collection* for the frozen test and live
    operation; evaluation scripts still refuse the test period).
    """
    days = pd.date_range(month.start_time, month.end_time.normalize(), freq="D")
    if collect_test:
        today = pd.Timestamp.now(tz="UTC").tz_localize(None).normalize()
        return [d for d in days if d <= today]
    return [d for d in days if d + pd.Timedelta(days=lead_days) <= DEV_LAST_VALID_DAY]


def build_month(ad, inits, region) -> tuple[xr.Dataset | None, list[str]]:
    """Canonical data for all inits of a month; returns (dataset, missing init list)."""
    while True:
        try:
            if isinstance(ad, OpenMeteoPreviousRunsAdapter):
                return ad.fetch_many(inits, region), []
            available = set(pd.DatetimeIndex(ad.init_times()))
            missing = [f"{i:%Y-%m-%d} (not in dataset)" for i in inits if i not in available]
            todo = [i for i in inits if i in available]

            def one(i):
                try:
                    return i, ad.fetch(i, region), None
                except QuotaExhausted:
                    raise
                except SourceError as e:
                    event(
                        log,
                        logging.ERROR,
                        "init failed",
                        adapter=ad.name,
                        init=str(i),
                        error=str(e),
                    )
                    return i, None, f"{i:%Y-%m-%d} ({e})"[:200]

            # remote Zarr reads are I/O bound: a few concurrent inits (modest load on the store)
            with ThreadPoolExecutor(max_workers=DYN_WORKERS) as pool:
                results = sorted(pool.map(one, todo), key=lambda r: r[0])
            parts = [r[1] for r in results if r[1] is not None]
            missing += [r[2] for r in results if r[2] is not None]
            if not parts:
                return None, missing
            return xr.concat(parts, dim="init_time", combine_attrs="override"), missing
        except QuotaExhausted as e:
            sleep_s = QUOTA_SLEEP_S
            if "Daily" in str(e):  # provider daily limit: resets at 00:00 UTC
                now = dt.datetime.now(dt.UTC)
                reset = (now + dt.timedelta(days=1)).replace(
                    hour=0, minute=10, second=0, microsecond=0
                )
                sleep_s = int((reset - now).total_seconds())
            event(
                log,
                logging.WARNING,
                "quota exhausted; sleeping",
                adapter=ad.name,
                sleep_s=sleep_s,
                error=str(e),
            )
            print(
                f"{dt.datetime.now(dt.UTC):%H:%M} quota: sleeping {sleep_s // 60} min ({e})",
                flush=True,
            )
            time.sleep(sleep_s)


def main() -> int:
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    ap.add_argument("--kind", choices=["prev", "dyn"], required=True)
    ap.add_argument("--adapters", nargs="+", default=None)
    ap.add_argument("--regions", nargs="+", default=None)
    ap.add_argument("--start", default="2024-01")
    ap.add_argument("--end", default="2025-12")
    ap.add_argument(
        "--collect-test",
        action="store_true",
        help="collect data in/after the frozen test period (never evaluated here)",
    )
    ap.add_argument(
        "--refresh-current",
        action="store_true",
        help="rebuild the store of the current (incomplete) month",
    )
    args = ap.parse_args()

    cfg = load_config()
    root = data_root()
    setup_logging(root / "logs" / f"backfill_{args.kind}.jsonl")
    om = cfg.openmeteo
    client = OpenMeteoSingleRuns(
        om,
        cfg.archiver.forecast_hours,
        cfg.archiver.hourly_variables,
        ledger=QuotaLedger(root / om.ledger, om.backfill_daily_cap, who="backfill"),
    )
    kind_cls = OpenMeteoPreviousRunsAdapter if args.kind == "prev" else DynamicalAdapter
    adapters = {
        k: v
        for k, v in build_adapters(cfg, root, client=client, use="eval").items()
        if isinstance(v, kind_cls) and (not args.adapters or k in args.adapters)
    }
    regions = args.regions or list(cfg.regions)
    months = pd.period_range(args.start, args.end, freq="M")
    lead_days = cfg.canonical.lead_days
    print(
        f"backfill {args.kind}: {list(adapters)} x {regions} x {months[0]}..{months[-1]}",
        flush=True,
    )

    for month in months:
        inits = month_inits(month, lead_days, args.collect_test)
        current = month == pd.Timestamp.now(tz="UTC").tz_localize(None).to_period("M")
        if not inits:
            continue
        for region_name in regions:
            region = cfg.regions[region_name]
            for name, ad in adapters.items():
                out = (
                    root
                    / "processed"
                    / "canonical"
                    / name
                    / region_name
                    / f"{month.strftime('%Y%m')}.zarr"
                )
                if out.exists() and not (args.refresh_current and current):
                    continue
                t0 = time.monotonic()
                try:
                    ds, missing = build_month(ad, inits, region)
                except SourceError as e:
                    event(
                        log,
                        logging.ERROR,
                        "month failed",
                        adapter=name,
                        region=region_name,
                        month=str(month),
                        error=str(e),
                    )
                    print(f"{month} {region_name:10s} {name:12s} FAILED {str(e)[:100]}", flush=True)
                    continue
                if ds is None:
                    print(
                        f"{month} {region_name:10s} {name:12s} no data ({len(missing)} inits unavailable)",
                        flush=True,
                    )
                    continue
                validate_canonical(ds)
                ds.attrs["missing_inits"] = json.dumps(missing)
                ds.attrs["backfilled_at"] = dt.datetime.now(dt.UTC).isoformat()
                write_zarr_atomic(ds.chunk({"init_time": -1}), out)
                print(
                    f"{month} {region_name:10s} {name:12s} ok  inits={ds.sizes['init_time']:2d} "
                    f"missing={len(missing)} {time.monotonic() - t0:6.1f}s",
                    flush=True,
                )
    print("backfill finished", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
