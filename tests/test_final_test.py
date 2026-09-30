"""The Phase 8 runner refuses to run twice (lock) and never scores in dry-run mode."""

import json
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
LOCK = REPO / "reports" / "phase8" / "FINAL_LOCK.json"


def _run(*args):
    return subprocess.run(
        [sys.executable, str(REPO / "scripts" / "run_final_test.py"), *args],
        capture_output=True,
        text=True,
        cwd=REPO,
        timeout=600,
    )


def test_refuses_when_lock_exists():
    if LOCK.exists():
        r = _run("--dry-run")
        assert r.returncode == 2 and "REFUSED" in r.stdout
        return
    LOCK.parent.mkdir(parents=True, exist_ok=True)
    LOCK.write_text(json.dumps({"test": "SYNTHETIC lock for the unit test"}))
    try:
        r = _run()
        assert r.returncode == 2 and "REFUSED" in r.stdout
    finally:
        LOCK.unlink()


def test_dry_run_never_locks():
    if LOCK.exists():
        return
    r = _run("--dry-run")
    assert r.returncode == 0 and "nothing scored" in r.stdout
    assert not LOCK.exists()
