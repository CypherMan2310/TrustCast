"""Download historical IMD yearly grids (for the climatology baseline and the 2026 test truth).

    python scripts/download_imd_history.py --start 1991 --end 2023
    python scripts/download_imd_history.py --start 2026 --end 2026        # retry the current year

Skips years already on disk; imdpune.gov.in is slow, so each year is retried with back-off and
failures are reported, never faked. Pauses between downloads to be polite to the server.
"""

from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from trustcast.config import data_root
from trustcast.truth import imd

PAUSE_S = 5


def main() -> int:
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    ap.add_argument("--start", type=int, default=1991)
    ap.add_argument("--end", type=int, default=2023)
    ap.add_argument("--vars", nargs="+", default=["tmax", "rain"])
    args = ap.parse_args()
    root = data_root()
    failed = []
    for var in args.vars:
        for year in range(args.start, args.end + 1):
            if imd.grd_path(root, var, year) is not None:
                continue
            t0 = time.monotonic()
            p = imd.download_year(root, var, year)
            status = f"ok {p.stat().st_size:,} B" if p else "FAILED"
            print(f"{var} {year}: {status} ({time.monotonic() - t0:.0f}s)", flush=True)
            if p is None:
                failed.append(f"{var} {year}")
            time.sleep(PAUSE_S)
    print("failed:", failed or "none", flush=True)
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
