from __future__ import annotations


def close_quietly(obj: object) -> None:
    """``obj``에 호출 가능한 ``close``가 있으면 호출한다.

    requests의 Response/Session처럼 ``close()``를 제공하는 객체를 정리할 때
    쓴다. ``close`` 속성이 없거나 호출 불가능하면 아무 일도 하지 않으며,
    ``close()`` 자체가 던지는 예외는 그대로 전파한다.
    """

    close = getattr(obj, "close", None)
    if callable(close):
        close()


__all__ = ["close_quietly"]
