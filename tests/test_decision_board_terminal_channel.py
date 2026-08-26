from __future__ import annotations

import json
import os

import pytest
from sab.decision_board.terminal_channel import (
    MAX_TERMINAL_BYTES,
    TERMINAL_FD_ENV,
    claim_terminal_fd_v0,
    write_terminal_result_v0,
)


@pytest.mark.parametrize("value", ["", "-1", "2", "3x", "٣"])
def test_terminal_channel_rejects_invalid_inherited_fd(
    monkeypatch: pytest.MonkeyPatch, value: str
) -> None:
    monkeypatch.setenv(TERMINAL_FD_ENV, value)

    assert claim_terminal_fd_v0() is None
    assert TERMINAL_FD_ENV not in os.environ


def test_terminal_channel_rejects_closed_inherited_fd(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    read_fd, write_fd = os.pipe()
    os.close(write_fd)
    try:
        monkeypatch.setenv(TERMINAL_FD_ENV, str(write_fd))

        assert claim_terminal_fd_v0() is None
        assert TERMINAL_FD_ENV not in os.environ
    finally:
        os.close(read_fd)


def test_terminal_channel_claim_is_non_inheritable_and_consumes_env(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    read_fd, write_fd = os.pipe()
    try:
        os.set_inheritable(write_fd, True)
        monkeypatch.setenv(TERMINAL_FD_ENV, str(write_fd))

        claimed_fd = claim_terminal_fd_v0()

        assert claimed_fd is not None
        assert TERMINAL_FD_ENV not in os.environ
        assert not os.get_inheritable(write_fd)
        assert not os.get_inheritable(claimed_fd)
        os.close(claimed_fd)
    finally:
        os.close(write_fd)
        os.close(read_fd)


def test_terminal_channel_rejects_oversized_result_and_closes_fd() -> None:
    read_fd, write_fd = os.pipe()
    value: dict[str, object] = {
        "status": "FAILED",
        "detail": "x" * MAX_TERMINAL_BYTES,
    }
    try:
        assert not write_terminal_result_v0(write_fd, value)
        with pytest.raises(OSError):
            os.fstat(write_fd)
    finally:
        os.close(read_fd)


def test_terminal_channel_retries_partial_writes_and_closes_fd(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    written = bytearray()
    closed: list[int] = []

    def partial_write(fd: int, payload: memoryview) -> int:
        assert fd == 97
        count = min(3, len(payload))
        written.extend(payload[:count])
        return count

    monkeypatch.setattr(os, "write", partial_write)
    monkeypatch.setattr(os, "close", closed.append)
    value = {"status": "FAILED", "exit_code": 2, "issue_code": "CONFIG_UNAVAILABLE"}

    assert write_terminal_result_v0(97, value)
    assert bytes(written) == json.dumps(value, sort_keys=True).encode() + b"\n"
    assert closed == [97]


def test_terminal_channel_write_error_fails_closed_and_closes_fd(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    closed: list[int] = []

    def fail_write(_fd: int, _payload: memoryview) -> int:
        raise OSError("write failed")

    monkeypatch.setattr(os, "write", fail_write)
    monkeypatch.setattr(os, "close", closed.append)

    assert not write_terminal_result_v0(98, {"status": "FAILED"})
    assert closed == [98]
