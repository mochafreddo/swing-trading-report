"""One monotonic budget shared by every research phase."""

from __future__ import annotations

import math
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field

DEFAULT_RESEARCH_BUDGET_SECONDS = 45.0
MIN_RESEARCH_BUDGET_SECONDS = 0.01
MAX_RESEARCH_BUDGET_SECONDS = 45.0


class DeadlineError(RuntimeError):
    """Base class for typed deadline failures."""


class DeadlineExpiredError(DeadlineError):
    """The shared research budget has been exhausted."""


class DeadlineInvariantError(DeadlineError):
    """The injected monotonic clock violated its contract."""


type MonotonicClock = Callable[[], float]
type AsyncSleeper = Callable[[float], Awaitable[None]]


@dataclass(frozen=True, slots=True)
class Deadline:
    """A fixed end point derived from exactly one monotonic start reading."""

    started_at: float
    expires_at: float
    _monotonic: MonotonicClock = field(repr=False, compare=False)
    _last_observed: list[float] = field(repr=False, compare=False)

    @classmethod
    def start(
        cls,
        budget_seconds: float = DEFAULT_RESEARCH_BUDGET_SECONDS,
        *,
        monotonic: MonotonicClock = time.monotonic,
    ) -> Deadline:
        if (
            isinstance(budget_seconds, bool)
            or not isinstance(budget_seconds, (int, float))
            or not math.isfinite(budget_seconds)
            or not MIN_RESEARCH_BUDGET_SECONDS
            <= budget_seconds
            <= MAX_RESEARCH_BUDGET_SECONDS
        ):
            raise DeadlineInvariantError(
                "research budget must be within the positive safe range"
            )
        started_at = monotonic()
        if not math.isfinite(started_at):
            raise DeadlineInvariantError("monotonic clock returned a non-finite value")
        return cls(
            started_at=started_at,
            expires_at=started_at + float(budget_seconds),
            _monotonic=monotonic,
            _last_observed=[started_at],
        )

    def remaining(self) -> float:
        now = self._monotonic()
        if not math.isfinite(now):
            raise DeadlineInvariantError("monotonic clock returned a non-finite value")
        if now < self._last_observed[0]:
            raise DeadlineInvariantError("monotonic clock moved backwards")
        self._last_observed[0] = now
        remaining = self.expires_at - now
        if remaining <= 0:
            raise DeadlineExpiredError("research deadline expired")
        return remaining

    def child_timeout(self, limit_seconds: float | None = None) -> float:
        remaining = self.remaining()
        if limit_seconds is None:
            return remaining
        if (
            isinstance(limit_seconds, bool)
            or not isinstance(limit_seconds, (int, float))
            or not math.isfinite(limit_seconds)
            or limit_seconds <= 0
        ):
            raise DeadlineInvariantError("child timeout limit must be positive")
        return min(float(limit_seconds), remaining)

    async def sleep(
        self,
        seconds: float,
        *,
        sleeper: AsyncSleeper,
    ) -> None:
        if (
            isinstance(seconds, bool)
            or not isinstance(seconds, (int, float))
            or not math.isfinite(seconds)
            or seconds < 0
        ):
            raise DeadlineInvariantError("sleep duration must be non-negative")
        if seconds == 0:
            self.remaining()
            return
        await sleeper(min(float(seconds), self.remaining()))
        self.remaining()


__all__ = [
    "DEFAULT_RESEARCH_BUDGET_SECONDS",
    "MAX_RESEARCH_BUDGET_SECONDS",
    "MIN_RESEARCH_BUDGET_SECONDS",
    "Deadline",
    "DeadlineError",
    "DeadlineExpiredError",
    "DeadlineInvariantError",
]
