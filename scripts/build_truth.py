"""Build monthly truth_v1 stores for the pilot regions.

    python scripts/build_truth.py --start 2024-01 --end 2025-12
    python scripts/build_truth.py --start 2026-01 --end 2026-09 --allow-test    # Phase 8 only

Output: data/processed/truth/<region>/<YYYYMM>.zarr (IMD day labels of that month).
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from trustcast.config import data_root, load_config
from trustcast.grid.schema import validate_truth
from trustcast.io import write_zarr_atomic
from trustcast.log import setup_logging
from trustcast.truth.build import build_truth

TEST_START = pd.Timestamp("2026-01-01")


def main() -> int:
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    ap.add_argument("--start", default="2024-01")
    ap.add_argument("--end", default="2025-12")
    ap.add_argument("--regions", nargs="+", default=None)
    ap.add_argument("--overwrite", action="store_true")
    ap.add_argument("--allow-test", action="store_true")
    args = ap.parse_args()
    cfg = load_config()
    root = data_root()
    setup_logging(root / "logs" / "build_truth.jsonl")
    for month in pd.period_range(args.start, args.end, freq="M"):
        if month.start_time >= TEST_START and not args.allow_test:
            print(f"refusing {month}: frozen test period (use --allow-test only in Phase 8)")
            return 2
        days = pd.date_range(month.start_time, month.end_time.normalize(), freq="D")
        for rname in args.regions or list(cfg.regions):
            out = root / "processed" / "truth" / rname / f"{month.strftime('%Y%m')}.zarr"
            if out.exists() and not args.overwrite:
                continue
            ds = build_truth(root, days, cfg.regions[rname])
            validate_truth(ds)
            write_zarr_atomic(ds, out)
            print(
                f"{month} {rname:10s} days={ds.sizes['time']} provisional={int(ds.provisional.sum())} "
                f"rain_nan={float(ds.rain_mm.isnull().mean()):.3f}",
                flush=True,
            )
    return 0


if __name__ == "__main__":
    sys.exit(main())
