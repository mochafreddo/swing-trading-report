from __future__ import annotations

import asyncio

import pytest
from sab.research.deadline import (
    Deadline,
    DeadlineExpiredError,
    DeadlineInvariantError,
)


class _FakeClock:
    def __init__(self) -> None:
        self.now = 100.0

    def __call__(self) -> float:
        return self.now


def test_deadline_uses_one_start_and_shrinks_child_timeouts() -> None:
    clock = _FakeClock()
    deadline = Deadline.start(45.0, monotonic=clock)

    first = deadline.child_timeout(10.0)
    clock.now += 7.5
    second = deadline.child_timeout(10.0)
    clock.now += 35.0
    final = deadline.child_timeout(10.0)

    assert (first, second, final) == (10.0, 10.0, 2.5)
    assert deadline.started_at == 100.0
    assert deadline.expires_at == 145.0


def test_deadline_rejects_exhaustion_and_negative_clock_movement() -> None:
    clock = _FakeClock()
    deadline = Deadline.start(45.0, monotonic=clock)

    clock.now = 145.0
    with pytest.raises(DeadlineExpiredError):
        deadline.child_timeout()

    clock.now = 99.0
    with pytest.raises(DeadlineInvariantError, match="moved backwards"):
        deadline.remaining()


def test_deadline_sleep_never_exceeds_remaining_budget() -> None:
    clock = _FakeClock()
    sleeps: list[float] = []
    deadline = Deadline.start(45.0, monotonic=clock)
    clock.now += 44.25

    async def fake_sleep(seconds: float) -> None:
        sleeps.append(seconds)
        clock.now += seconds

    with pytest.raises(DeadlineExpiredError):
        asyncio.run(deadline.sleep(5.0, sleeper=fake_sleep))

    assert sleeps == [0.75]
    assert clock.now == 145.0
