"""Private inherited channel for one sanitized Decision Board terminal result."""

from __future__ import annotations

import json
import os
from contextlib import suppress

TERMINAL_FD_ENV = "SAB_DECISION_BOARD_TERMINAL_FD"
MAX_TERMINAL_BYTES = 8192


def claim_terminal_fd_v0() -> int | None:
    """Claim a journal-owned descriptor without forwarding it to provider children."""

    raw_fd = os.environ.pop(TERMINAL_FD_ENV, None)
    if raw_fd is None:
        return None
    if not raw_fd.isascii() or not raw_fd.isdecimal():
        return None
    inherited_fd = int(raw_fd)
    if inherited_fd < 3:
        return None
    claimed_fd: int | None = None
    try:
        os.fstat(inherited_fd)
        os.set_inheritable(inherited_fd, False)
        claimed_fd = os.dup(inherited_fd)
        os.set_inheritable(claimed_fd, False)
    except OSError:
        if claimed_fd is not None:
            with suppress(OSError):
                os.close(claimed_fd)
        return None
    return claimed_fd


def write_terminal_result_v0(fd: int, value: dict[str, object]) -> bool:
    """Write one bounded canonical JSON result and consume the claimed descriptor."""

    try:
        payload = json.dumps(value, sort_keys=True).encode("utf-8") + b"\n"
        if len(payload) > MAX_TERMINAL_BYTES:
            return False
        view = memoryview(payload)
        while view:
            written = os.write(fd, view)
            if written <= 0:
                return False
            view = view[written:]
        return True
    except OSError:
        return False
    finally:
        with suppress(OSError):
            os.close(fd)


__all__ = [
    "MAX_TERMINAL_BYTES",
    "TERMINAL_FD_ENV",
    "claim_terminal_fd_v0",
    "write_terminal_result_v0",
]
