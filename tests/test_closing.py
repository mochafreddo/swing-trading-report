from __future__ import annotations

import pytest
from sab.utils.closing import close_quietly


class _Closeable:
    def __init__(self) -> None:
        self.closed = False

    def close(self) -> None:
        self.closed = True


def test_calls_close_when_present() -> None:
    obj = _Closeable()
    close_quietly(obj)
    assert obj.closed is True


def test_ignores_object_without_close() -> None:
    close_quietly(object())  # 예외가 발생하지 않아야 한다.


def test_ignores_non_callable_close_attribute() -> None:
    class _NotCallable:
        close = "not callable"

    close_quietly(_NotCallable())  # 호출하지 않고 조용히 통과한다.


def test_propagates_errors_raised_by_close() -> None:
    class _Boom:
        def close(self) -> None:
            raise RuntimeError("boom")

    with pytest.raises(RuntimeError, match="boom"):
        close_quietly(_Boom())
