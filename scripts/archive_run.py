"""Snapshot the latest 00/12Z runs of every configured source for the pilot regions.

    python scripts/archive_run.py                       # all sources, all regions
    python scripts/archive_run.py --sources ecmwf_ifs --regions rain_pilot
    python scripts/archive_run.py --config config/pilot.yaml --data-dir D:/trustcast-data

Exit code: 0 if every attempted run is ok or already archived (stale sources are logged
as errors but do not fail the job), 1 if any fetch or verification failed.
"""

from __future__ import annotations

import argparse
import collections
import logging
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from trustcast.adapters.ledger import QuotaLedger
from trustcast.adapters.openmeteo import OpenMeteoSingleRuns
from trustcast.archive.runner import archive_all
from trustcast.config import data_root, load_config
from trustcast.log import event, setup_logging

log = logging.getLogger("archive_run")


def main() -> int:
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    ap.add_argument("--config", default=None)
    ap.add_argument("--data-dir", default=None)
    ap.add_argument("--sources", nargs="+", default=None)
    ap.add_argument("--regions", nargs="+", default=None)
    args = ap.parse_args()

    cfg = load_config(args.config)
    root = Path(args.data_dir) if args.data_dir else data_root()
    setup_logging(root / "logs" / "archiver.jsonl")
    a = cfg.archiver
    om = cfg.openmeteo
    ledger = QuotaLedger(root / om.ledger, om.archiver_daily_cap, who="archiver")
    client = OpenMeteoSingleRuns(om, a.forecast_hours, a.hourly_variables, ledger=ledger)
    results = archive_all(cfg, root, client, sources=args.sources, regions=args.regions)

    counts = collections.Counter(r.status for r in results)
    for r in results:
        when = r.init_time or "-"
        print(f"{r.status:7s} {r.source:11s} {r.region:11s} {when:19s} {r.detail[:120]}")
    event(log, logging.INFO, "archive run finished", **dict(counts))
    print("summary:", dict(counts))
    return 1 if counts.get("failed") else 0


if __name__ == "__main__":
    sys.exit(main())
