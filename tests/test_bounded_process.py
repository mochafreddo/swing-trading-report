from __future__ import annotations

import asyncio
import os
import time
from typing import cast

import pytest
from sab.utils.bounded_process import (
    BoundedProcessTimeoutError,
    run_sync_in_bounded_process_async_v0,
    run_sync_in_bounded_process_v0,
)


def _sleep_then_return(delay: float, value: str) -> str:
    time.sleep(delay)
    return value


def _read_parent_sentinel_and_explicit_secret(secret: str) -> tuple[str | None, str]:
    return os.getenv("PRIVATE_BOUNDED_PARENT_SENTINEL"), secret


def test_bounded_process_returns_picklable_result() -> None:
    assert (
        run_sync_in_bounded_process_v0(
            _sleep_then_return,
            (0.0, "completed"),
            timeout=2.0,
        )
        == "completed"
    )


def test_bounded_process_does_not_inherit_parent_env_and_accepts_explicit_secret(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("PRIVATE_BOUNDED_PARENT_SENTINEL", "must-not-cross")

    observed_parent, observed_secret = cast(
        tuple[str | None, str],
        run_sync_in_bounded_process_v0(
            _read_parent_sentinel_and_explicit_secret,
            ("explicit-secret",),
            timeout=2.0,
        ),
    )

    assert observed_parent is None
    assert observed_secret == "explicit-secret"


def test_bounded_process_enforces_hard_wall_clock_timeout() -> None:
    started_at = time.monotonic()

    with pytest.raises(BoundedProcessTimeoutError, match="timed out"):
        asyncio.run(
            run_sync_in_bounded_process_async_v0(
                _sleep_then_return,
                (2.0, "too-late"),
                timeout=0.1,
            )
        )

    assert time.monotonic() - started_at < 1.0


def test_async_bounded_process_budget_includes_executor_queue_delay(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    original_to_thread = asyncio.to_thread

    async def delayed_to_thread(function, /, *args, **kwargs):
        await asyncio.sleep(0.1)
        return await original_to_thread(function, *args, **kwargs)

    monkeypatch.setattr(asyncio, "to_thread", delayed_to_thread)
    started_at = time.monotonic()

    with pytest.raises(BoundedProcessTimeoutError, match="timed out"):
        asyncio.run(
            run_sync_in_bounded_process_async_v0(
                _sleep_then_return,
                (0.0, "must-not-start"),
                timeout=0.05,
            )
        )

    assert time.monotonic() - started_at < 0.3
