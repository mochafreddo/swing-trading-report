from __future__ import annotations

import json
import os
import tempfile
import threading
from collections.abc import Callable, Iterator
from contextlib import contextmanager, suppress
from typing import Any, TextIO

_fcntl: Any
try:
    import fcntl as _fcntl
except ImportError:  # pragma: no cover - non-POSIX fallback
    _fcntl = None


_LOCKS_GUARD = threading.Lock()
_PATH_LOCKS: dict[str, threading.Lock] = {}


def _get_path_lock(path: str) -> threading.Lock:
    normalized = os.path.abspath(path)
    with _LOCKS_GUARD:
        lock = _PATH_LOCKS.get(normalized)
        if lock is None:
            lock = threading.Lock()
            _PATH_LOCKS[normalized] = lock
        return lock


def _atomic_write(
    path: str, writer: Callable[[TextIO], None], *, encoding: str
) -> None:
    directory = os.path.dirname(path) or "."
    os.makedirs(directory, exist_ok=True)

    basename = os.path.basename(path)
    fd, tmp_path = tempfile.mkstemp(
        dir=directory,
        prefix=f".{basename}.",
        suffix=".tmp",
    )

    try:
        file_obj: TextIO
        try:
            file_obj = os.fdopen(fd, "w", encoding=encoding)
        except Exception:
            os.close(fd)
            raise
        with file_obj as fp:
            writer(fp)
            fp.flush()
            os.fsync(fp.fileno())
        os.replace(tmp_path, path)
        tmp_path = ""
    finally:
        if tmp_path:
            with suppress(FileNotFoundError):
                os.remove(tmp_path)


def atomic_write_text(path: str, content: str, *, encoding: str = "utf-8") -> None:
    def _write(fp: TextIO) -> None:
        fp.write(content)

    _atomic_write(path, _write, encoding=encoding)


def atomic_write_json(
    path: str,
    obj: Any,
    *,
    ensure_ascii: bool = False,
    indent: int | None = None,
    encoding: str = "utf-8",
) -> None:
    def _write(fp: TextIO) -> None:
        json.dump(obj, fp, ensure_ascii=ensure_ascii, indent=indent)

    _atomic_write(path, _write, encoding=encoding)


@contextmanager
def advisory_path_lock(lock_path: str) -> Iterator[None]:
    directory = os.path.dirname(lock_path) or "."
    os.makedirs(directory, exist_ok=True)

    thread_lock = _get_path_lock(lock_path)
    with thread_lock, open(lock_path, "a+", encoding="utf-8") as fp:
        if _fcntl is not None:  # pragma: no branch - platform dependent
            _fcntl.flock(fp.fileno(), _fcntl.LOCK_EX)
        try:
            yield
        finally:
            if _fcntl is not None:  # pragma: no branch - platform dependent
                _fcntl.flock(fp.fileno(), _fcntl.LOCK_UN)


__all__ = [
    "advisory_path_lock",
    "atomic_write_json",
    "atomic_write_text",
]
