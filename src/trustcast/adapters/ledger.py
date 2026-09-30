"""Cross-process Open-Meteo quota ledger.

The archiver and the backfill run as separate processes but share one provider quota (10,000
location-calls/day on the free tier). Every request appends ``{"ts", "units", "who"}`` to a JSONL
ledger; before a request, a process checks the rolling-24 h total against its own cap:

* archiver: high cap (it must never be starved; ~1,800 units per 00/12Z cycle)
* backfill: lower cap, so the archiver always keeps headroom
"""

from __future__ import annotations

import json
import time
from collections.abc import Callable
from pathlib import Path

from trustcast.adapters.ratelimit import BudgetExhausted


class QuotaLedger:
    """Rolling-window usage ledger shared through a file."""

    def __init__(
        self,
        path: Path,
        cap: int,
        who: str,
        window_s: float = 86_400.0,
        clock: Callable[[], float] = time.time,
    ) -> None:
        self.path, self.cap, self.who, self.window_s, self.clock = path, cap, who, window_s, clock
        self.path.parent.mkdir(parents=True, exist_ok=True)

    def used(self) -> int:
        """Units recorded by all processes within the window."""
        if not self.path.exists():
            return 0
        cutoff = self.clock() - self.window_s
        total = 0
        with self.path.open(encoding="utf-8") as f:
            for line in f:
                try:
                    rec = json.loads(line)
                except ValueError:
                    continue
                if rec.get("ts", 0) >= cutoff:
                    total += int(rec.get("units", 0))
        return total

    def reserve(self, units: int) -> None:
        """Record ``units`` or raise :class:`BudgetExhausted` if the cap would be exceeded."""
        used = self.used()
        if used + units > self.cap:
            raise BudgetExhausted(
                f"{self.who}: 24 h Open-Meteo usage {used} + {units} would exceed cap {self.cap}"
            )
        with self.path.open("a", encoding="utf-8") as f:
            f.write(json.dumps({"ts": self.clock(), "units": units, "who": self.who}) + "\n")
