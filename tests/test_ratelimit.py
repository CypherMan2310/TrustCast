"""Rolling-window limiter with a fake clock."""

import pytest

from trustcast.adapters.ratelimit import BudgetExhausted, RollingLimiter


class FakeClock:
    def __init__(self) -> None:
        self.t = 0.0

    def __call__(self) -> float:
        return self.t

    def sleep(self, s: float) -> None:
        self.t += s


def test_limiter_blocks_until_window_frees():
    c = FakeClock()
    lim = RollingLimiter(400, 60, clock=c, sleep=c.sleep)
    assert lim.acquire(150) == 0
    assert lim.acquire(150) == 0
    waited = lim.acquire(150)  # 450 > 400 -> must wait for first event to expire
    assert waited == pytest.approx(60.01)
    assert c.t == pytest.approx(60.01)


def test_limiter_never_exceeds_budget_in_any_window():
    c = FakeClock()
    lim = RollingLimiter(400, 60, clock=c, sleep=c.sleep)
    log = []
    for _ in range(20):
        lim.acquire(150)
        log.append(c.t)
        c.t += 1
    for t in log:
        assert sum(150 for u in log if t <= u < t + 60) <= 400


def test_non_blocking_limiter_raises_instead_of_sleeping():
    c = FakeClock()
    lim = RollingLimiter(300, 3600, clock=c, sleep=c.sleep, blocking=False)
    lim.acquire(200)
    with pytest.raises(BudgetExhausted):
        lim.acquire(200)
    assert c.t == 0


def test_oversized_request_rejected():
    with pytest.raises(ValueError):
        RollingLimiter(100).acquire(101)
