"""Rolling-window rate limiter measured in provider "units" (Open-Meteo: locations)."""

from __future__ import annotations

import time
from collections import deque
from collections.abc import Callable


class BudgetExhausted(RuntimeError):
    """A non-blocking limiter has no room left in its window."""


class RollingLimiter:
    """Allow at most ``max_units`` within any ``window_s`` seconds.

    A blocking limiter sleeps until the request fits; a non-blocking one raises
    :class:`BudgetExhausted` instead (used for the hourly quota, where waiting is pointless).
    """

    def __init__(
        self,
        max_units: int,
        window_s: float = 60.0,
        clock: Callable[[], float] = time.monotonic,
        sleep: Callable[[float], None] = time.sleep,
        blocking: bool = True,
    ) -> None:
        if max_units <= 0:
            raise ValueError("max_units must be positive")
        self.max_units = max_units
        self.window_s = window_s
        self._clock = clock
        self._sleep = sleep
        self.blocking = blocking
        self._events: deque[tuple[float, int]] = deque()

    def _used(self, now: float) -> int:
        while self._events and now - self._events[0][0] >= self.window_s:
            self._events.popleft()
        return sum(u for _, u in self._events)

    def acquire(self, units: int) -> float:
        """Block until ``units`` fit in the window, record them, return seconds waited."""
        if units > self.max_units:
            raise ValueError(f"request of {units} units exceeds limit {self.max_units}")
        waited = 0.0
        while True:
            now = self._clock()
            if self._used(now) + units <= self.max_units:
                self._events.append((now, units))
                return waited
            if not self.blocking:
                raise BudgetExhausted(
                    f"{units} units would exceed {self.max_units} per {self.window_s:.0f} s"
                )
            pause = self.window_s - (now - self._events[0][0]) + 0.01
            self._sleep(pause)
            waited += pause
