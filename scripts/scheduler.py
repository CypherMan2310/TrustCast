"""Local job runner: run the archiver after each 00Z and 12Z cycle becomes available.

    python scripts/scheduler.py            # blocks; Ctrl+C to stop

Runs at 09:30 and 21:30 UTC (IFS 00Z appeared at ~08:00 UTC on 2026-09-30; GFS ~09:05)
and once more at 03:30 / 15:30 UTC as a catch-up. The archiver is idempotent and back-fills
the last few cycles, so extra or missed runs are harmless.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

from apscheduler.schedulers.blocking import BlockingScheduler

REPO = Path(__file__).resolve().parents[1]


def run_archiver() -> None:
    """Invoke the archiver in a subprocess so one crash never kills the scheduler."""
    script = REPO / "scripts" / "archive_run.py"
    subprocess.run([sys.executable, str(script)], cwd=REPO, check=False)


def main() -> None:
    sched = BlockingScheduler(timezone="UTC")
    sched.add_job(
        run_archiver,
        "cron",
        hour="3,9,15,21",
        minute=30,
        misfire_grace_time=3600,
        coalesce=True,
        max_instances=1,
    )
    print("scheduler started: archiver at 03:30, 09:30, 15:30, 21:30 UTC")
    sched.start()


if __name__ == "__main__":
    main()
