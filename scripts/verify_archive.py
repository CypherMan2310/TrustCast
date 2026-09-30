"""Re-verify every archive manifest against the files on disk.

    python scripts/verify_archive.py

Exit code 1 if any manifest fails.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from trustcast.archive.manifest import verify_manifest
from trustcast.config import data_root


def main() -> int:
    root = data_root()
    manifests = sorted((root / "processed" / "archive" / "manifests").glob("*.json"))
    if not manifests:
        print("no manifests found")
        return 1
    bad = 0
    for m in manifests:
        problems = verify_manifest(m, root)
        print(f"{'OK  ' if not problems else 'FAIL'} {m.name} {'; '.join(problems)}")
        bad += bool(problems)
    print(f"{len(manifests) - bad}/{len(manifests)} manifests verified")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
