from __future__ import annotations

import logging
from collections.abc import Callable, Iterator

import pytest


@pytest.fixture
def isolated_root_logger() -> Iterator[logging.Logger]:
    root = logging.getLogger()
    old_handlers = list(root.handlers)
    old_level = root.level

    for handler in old_handlers:
        root.removeHandler(handler)

    try:
        yield root
    finally:
        for handler in list(root.handlers):
            root.removeHandler(handler)
        root.setLevel(old_level)
        for handler in old_handlers:
            root.addHandler(handler)


@pytest.fixture
def make_log_record() -> Callable[..., logging.LogRecord]:
    def _make(
        *,
        name: str = "sab.test",
        level: int = logging.INFO,
        msg: str = "hello",
        created: float | None = None,
    ) -> logging.LogRecord:
        record = logging.LogRecord(
            name=name,
            level=level,
            pathname=__file__,
            lineno=1,
            msg=msg,
            args=(),
            exc_info=None,
        )
        if created is not None:
            record.created = created
            record.msecs = (created - int(created)) * 1000.0
        return record

    return _make
