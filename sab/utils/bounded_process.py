"""Run blocking network adapters in killable child processes with one hard budget."""

from __future__ import annotations

import asyncio
import math
import multiprocessing
import os
import time
from collections.abc import Callable
from multiprocessing.connection import Connection
from multiprocessing.process import BaseProcess
from typing import Any, Protocol


class AsyncBoundedProcessRunnerV0(Protocol):
    async def __call__(
        self,
        operation: Callable[..., Any],
        args: tuple[object, ...],
        *,
        timeout: float,
        kwargs: dict[str, object] | None = None,
    ) -> object: ...


class SyncBoundedProcessRunnerV0(Protocol):
    def __call__(
        self,
        operation: Callable[..., Any],
        args: tuple[object, ...],
        *,
        timeout: float,
        kwargs: dict[str, object] | None = None,
    ) -> object: ...


class BoundedProcessTimeoutError(TimeoutError):
    """The child process exceeded its monotonic wall-clock budget."""


def run_sync_in_bounded_process_v0(
    operation: Callable[..., Any],
    args: tuple[object, ...],
    *,
    timeout: float,
    kwargs: dict[str, object] | None = None,
) -> object:
    if (
        not callable(operation)
        or type(args) is not tuple
        or (kwargs is not None and type(kwargs) is not dict)
        or isinstance(timeout, bool)
        or not isinstance(timeout, (int, float))
        or not math.isfinite(timeout)
        or timeout <= 0
    ):
        raise ValueError("bounded process request is invalid")
    expires_at = time.monotonic() + float(timeout)
    context = multiprocessing.get_context("spawn")
    receiver, sender = context.Pipe(duplex=False)
    process = context.Process(
        target=_bounded_process_worker,
        args=(sender, operation, args, {} if kwargs is None else kwargs),
        daemon=True,
    )
    try:
        process.start()
        sender.close()
        remaining = expires_at - time.monotonic()
        if remaining <= 0 or not receiver.poll(remaining):
            _stop_process(process)
            raise BoundedProcessTimeoutError("bounded process timed out")
        try:
            status, payload = receiver.recv()
        except EOFError:
            raise RuntimeError("bounded process returned no result") from None
        process.join(timeout=max(0.0, expires_at - time.monotonic()))
        if process.is_alive():
            _stop_process(process)
            raise BoundedProcessTimeoutError("bounded process timed out")
        if status == "ok":
            return payload
        if status == "error" and isinstance(payload, Exception):
            raise payload
        raise RuntimeError("bounded process returned an invalid result")
    finally:
        receiver.close()
        sender.close()
        if process.is_alive():
            _stop_process(process)
        process.close()


async def run_sync_in_bounded_process_async_v0(
    operation: Callable[..., Any],
    args: tuple[object, ...],
    *,
    timeout: float,
    kwargs: dict[str, object] | None = None,
) -> object:
    if (
        isinstance(timeout, bool)
        or not isinstance(timeout, (int, float))
        or not math.isfinite(timeout)
        or timeout <= 0
    ):
        raise ValueError("bounded process request is invalid")
    expires_at = time.monotonic() + float(timeout)
    return await asyncio.to_thread(
        _run_sync_before_deadline,
        operation,
        args,
        expires_at,
        kwargs,
    )


def _run_sync_before_deadline(
    operation: Callable[..., Any],
    args: tuple[object, ...],
    expires_at: float,
    kwargs: dict[str, object] | None,
) -> object:
    remaining = expires_at - time.monotonic()
    if remaining <= 0:
        raise BoundedProcessTimeoutError("bounded process timed out")
    return run_sync_in_bounded_process_v0(
        operation,
        args,
        timeout=remaining,
        kwargs=kwargs,
    )


def _bounded_process_worker(
    sender: Connection,
    operation: Callable[..., Any],
    args: tuple[object, ...],
    kwargs: dict[str, object],
) -> None:
    try:
        os.environ.clear()
        try:
            sender.send(("ok", operation(*args, **kwargs)))
        except BaseException as exc:
            try:
                sender.send(("error", exc))
            except BaseException:
                sender.send(("invalid", None))
    finally:
        sender.close()


def _stop_process(process: BaseProcess) -> None:
    if process.is_alive():
        process.terminate()
        process.join(timeout=0.5)
    if process.is_alive():
        process.kill()
        process.join(timeout=0.5)


__all__ = [
    "AsyncBoundedProcessRunnerV0",
    "BoundedProcessTimeoutError",
    "SyncBoundedProcessRunnerV0",
    "run_sync_in_bounded_process_async_v0",
    "run_sync_in_bounded_process_v0",
]
