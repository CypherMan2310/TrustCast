"""Download IMD real-time daily grids (rain 0.25 deg, Tmax 0.5 deg) for days without IMD final data.

    python scripts/download_imd_realtime.py --start 2026-01-01            # up to yesterday
    python scripts/download_imd_realtime.py --start 2026-06-01 --end 2026-06-30 --vars rain

Polite: one request at a time with a pause; days already on disk are skipped; failures are listed,
never filled with anything else.
"""

from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from trustcast.config import data_root
from trustcast.io import AlreadyRunning, single_instance
from trustcast.truth import imd

PAUSE_S = 3


def main() -> int:
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    ap.add_argument("--start", required=True)
    ap.add_argument("--end", default=None)
    ap.add_argument("--vars", nargs="+", default=["rain", "tmax"])
    args = ap.parse_args()
    root = data_root()
    end = (
        pd.Timestamp(args.end)
        if args.end
        else pd.Timestamp.now(tz="UTC").tz_localize(None).normalize() - pd.Timedelta(days=1)
    )
    days = pd.date_range(args.start, end)
    try:
        with single_instance(root / "logs" / "download_imd_realtime.lock"):
            failed = []
            for var in args.vars:
                final = set(imd.available_days(root, var, sorted({d.year for d in days})))
                todo = [
                    d
                    for d in days
                    if d not in final and not imd.realtime_path(root, var, d).exists()
                ]
                print(f"{var}: {len(todo)} days to fetch", flush=True)
                for d in todo:
                    p = imd.download_realtime(root, var, d)
                    if p is None:
                        failed.append(f"{var} {d:%Y-%m-%d}")
                    time.sleep(PAUSE_S)
            print(f"failed ({len(failed)}):", failed[:20], flush=True)
    except AlreadyRunning as e:
        print(f"skipped: {e}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
