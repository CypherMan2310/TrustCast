"""Choose which 00/12Z cycles to archive."""

from __future__ import annotations

import datetime as dt


def floor_cycle(t: dt.datetime, cycles_utc: list[int]) -> dt.datetime:
    """Latest time <= ``t`` whose hour is one of ``cycles_utc`` (minutes zeroed)."""
    hours = sorted(set(cycles_utc))
    base = t.replace(minute=0, second=0, microsecond=0)
    for back in range(0, 49):
        c = base - dt.timedelta(hours=back)
        if c.hour in hours and c <= t:
            return c
    raise ValueError(f"no cycle in {cycles_utc} within 48 h of {t}")


def candidate_cycles(
    last_init: dt.datetime,
    now: dt.datetime,
    cycles_utc: list[int],
    lookback: int,
    max_age_hours: float,
) -> list[dt.datetime]:
    """Return up to ``lookback`` archived-cycle candidates, oldest first.

    Candidates are the newest 00/12Z cycle at or before the provider's ``last_init`` and the
    cycles before it, dropping any older than ``max_age_hours`` relative to ``now``.
    An empty list means the source is stale.
    """
    newest = floor_cycle(min(last_init, now), cycles_utc)
    out: list[dt.datetime] = []
    c = newest
    while len(out) < lookback:
        if (now - c).total_seconds() / 3600 > max_age_hours:
            break
        out.append(c)
        c = floor_cycle(c - dt.timedelta(hours=1), cycles_utc)
    return sorted(out)
