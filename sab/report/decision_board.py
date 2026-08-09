"""Fail-closed local and Storage identity for Decision Board V0 reports."""

from __future__ import annotations

import errno
import fcntl
import hashlib
import os
import re
import secrets
import stat
from contextlib import suppress
from dataclasses import dataclass
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any

from sab.decision_board.contracts import (
    canonical_json_bytes,
    validate_decision_board_report,
)

_RUN_ID_PATTERN = re.compile(r"[A-Za-z0-9][A-Za-z0-9_-]{0,127}\Z")
_KEY_PATTERN = re.compile(
    r"(?P<year>\d{4})/(?P<month>\d{2})/"
    r"(?P<date>\d{4}-\d{2}-\d{2})\.decision-board\."
    r"(?P<kind>entry|holding)\."
    r"(?P<run_id>[A-Za-z0-9][A-Za-z0-9_-]{0,127})\."
    r"(?P<digest>[0-9a-f]{64})\.json\Z"
)


class DecisionBoardStorageError(RuntimeError):
    """A Decision Board report could not be persisted safely."""


class DecisionBoardStoragePathError(DecisionBoardStorageError):
    """A report directory or target changed into an unsafe path."""


class DecisionBoardIdempotencyConflictError(DecisionBoardStorageError):
    """The deterministic identity already contains different bytes."""


@dataclass(frozen=True)
class ParsedDecisionBoardStorageKey:
    key: str
    report_date: date
    run_kind: str
    run_id: str
    idempotency_key: str
    basename: str


def _report_created_at_utc(report: dict[str, Any]) -> datetime:
    value = report["created_at"]
    assert isinstance(value, str)
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError("created_at must include a UTC offset")
    return parsed.astimezone(UTC)


def _validated_run_id(value: object) -> str:
    if not isinstance(value, str) or not _RUN_ID_PATTERN.fullmatch(value):
        raise ValueError(
            "run_id must be 1-128 ASCII letters, digits, underscores, or hyphens"
        )
    return value


def build_decision_board_storage_key(report: object) -> str:
    """Build the deterministic public-safe Storage key from a validated envelope."""

    validated = validate_decision_board_report(report)
    run_id = _validated_run_id(validated["run_id"])
    created_at = _report_created_at_utc(validated)
    run_kind = validated["run_kind"]
    assert isinstance(run_kind, str)
    kind = run_kind.lower()
    idempotency_key = validated["idempotency_key"]
    assert isinstance(idempotency_key, str)
    digest = idempotency_key.removeprefix("sha256:")
    basename = (
        f"{created_at.date().isoformat()}.decision-board.{kind}.{run_id}.{digest}.json"
    )
    return f"{created_at:%Y/%m}/{basename}"


def parse_decision_board_storage_key(
    key: str,
    *,
    report: object | None = None,
) -> ParsedDecisionBoardStorageKey | None:
    """Parse one strict key, optionally requiring exact envelope identity parity."""

    if not isinstance(key, str) or key != key.strip():
        return None
    match = _KEY_PATTERN.fullmatch(key)
    if match is None:
        return None
    try:
        report_date = date.fromisoformat(match.group("date"))
    except ValueError:
        return None
    if f"{report_date.year:04d}" != match.group(
        "year"
    ) or f"{report_date.month:02d}" != match.group("month"):
        return None
    parsed = ParsedDecisionBoardStorageKey(
        key=key,
        report_date=report_date,
        run_kind=match.group("kind").upper(),
        run_id=match.group("run_id"),
        idempotency_key=f"sha256:{match.group('digest')}",
        basename=key.rsplit("/", 1)[-1],
    )
    if report is not None:
        try:
            expected = build_decision_board_storage_key(report)
        except TypeError, ValueError:
            return None
        if expected != key:
            return None
    return parsed


def _open_report_directory(report_dir: Path) -> int:
    try:
        before = report_dir.lstat()
    except OSError as exc:
        raise DecisionBoardStoragePathError(
            f"report directory is unavailable: {report_dir}"
        ) from exc
    if stat.S_ISLNK(before.st_mode) or not stat.S_ISDIR(before.st_mode):
        raise DecisionBoardStoragePathError(
            f"report directory must be a real directory: {report_dir}"
        )
    flags = os.O_RDONLY | getattr(os, "O_DIRECTORY", 0) | getattr(os, "O_NOFOLLOW", 0)
    try:
        directory_fd = os.open(report_dir, flags)
    except OSError as exc:
        raise DecisionBoardStoragePathError(
            f"report directory could not be opened safely: {report_dir}"
        ) from exc
    after = os.fstat(directory_fd)
    if (before.st_dev, before.st_ino) != (after.st_dev, after.st_ino):
        os.close(directory_fd)
        raise DecisionBoardStoragePathError(
            "report directory changed during validation"
        )
    return directory_fd


def _open_lock(directory_fd: int, basename: str) -> int:
    digest = hashlib.sha256(basename.encode("ascii")).hexdigest()
    lock_name = f".decision-board-{digest}.lock"
    nofollow = getattr(os, "O_NOFOLLOW", 0)
    try:
        try:
            created_fd = os.open(
                lock_name,
                os.O_WRONLY | os.O_CREAT | os.O_EXCL | nofollow,
                0o600,
                dir_fd=directory_fd,
            )
        except FileExistsError:
            pass
        else:
            os.close(created_fd)
        lock_fd = os.open(lock_name, os.O_RDWR | nofollow, dir_fd=directory_fd)
    except OSError as exc:
        raise DecisionBoardStoragePathError(
            "target lock could not be opened safely"
        ) from exc
    info = os.fstat(lock_fd)
    if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1:
        os.close(lock_fd)
        raise DecisionBoardStoragePathError("target lock is not a private regular file")
    fcntl.flock(lock_fd, fcntl.LOCK_EX)
    return lock_fd


def _read_existing(directory_fd: int, basename: str) -> bytes:
    flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0)
    try:
        target_fd = os.open(basename, flags, dir_fd=directory_fd)
    except OSError as exc:
        raise DecisionBoardStoragePathError(
            "existing target could not be opened safely"
        ) from exc
    try:
        opened = os.fstat(target_fd)
        if not stat.S_ISREG(opened.st_mode) or opened.st_nlink != 1:
            raise DecisionBoardStoragePathError("existing target is not a regular file")
        chunks: list[bytes] = []
        while chunk := os.read(target_fd, 1024 * 1024):
            chunks.append(chunk)
        current = os.stat(basename, dir_fd=directory_fd, follow_symlinks=False)
        if not stat.S_ISREG(current.st_mode) or (
            current.st_dev,
            current.st_ino,
        ) != (opened.st_dev, opened.st_ino):
            raise DecisionBoardStoragePathError(
                "existing target changed during comparison"
            )
        return b"".join(chunks)
    finally:
        os.close(target_fd)


def _write_temp(directory_fd: int, basename: str, payload: bytes) -> str:
    for _ in range(32):
        temp_name = f".{basename}.{secrets.token_hex(12)}.tmp"
        flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0)
        try:
            temp_fd = os.open(temp_name, flags, 0o600, dir_fd=directory_fd)
        except FileExistsError:
            continue
        try:
            view = memoryview(payload)
            while view:
                written = os.write(temp_fd, view)
                view = view[written:]
            os.fsync(temp_fd)
        except BaseException:
            os.close(temp_fd)
            os.unlink(temp_name, dir_fd=directory_fd)
            raise
        os.close(temp_fd)
        return temp_name
    raise DecisionBoardStorageError("could not allocate a private temporary file")


def _target_matches(
    directory_fd: int,
    basename: str,
    expected: os.stat_result,
) -> bool:
    try:
        current = os.stat(basename, dir_fd=directory_fd, follow_symlinks=False)
    except FileNotFoundError:
        return False
    return stat.S_ISREG(current.st_mode) and (
        current.st_dev,
        current.st_ino,
    ) == (expected.st_dev, expected.st_ino)


def write_decision_board_report(
    report: object,
    *,
    report_dir: str | Path,
) -> Path:
    """Atomically create or idempotently confirm one Decision Board report."""

    validated = validate_decision_board_report(report)
    key = build_decision_board_storage_key(validated)
    parsed = parse_decision_board_storage_key(key, report=validated)
    assert parsed is not None
    payload = canonical_json_bytes(validated)
    directory = Path(report_dir)
    directory_fd = _open_report_directory(directory)
    lock_fd: int | None = None
    temp_name: str | None = None
    created_target: os.stat_result | None = None
    try:
        lock_fd = _open_lock(directory_fd, parsed.basename)
        temp_name = _write_temp(directory_fd, parsed.basename, payload)
        temp_info = os.stat(temp_name, dir_fd=directory_fd, follow_symlinks=False)
        try:
            os.link(
                temp_name,
                parsed.basename,
                src_dir_fd=directory_fd,
                dst_dir_fd=directory_fd,
                follow_symlinks=False,
            )
            created_target = temp_info
            if not _target_matches(directory_fd, parsed.basename, temp_info):
                raise DecisionBoardStoragePathError(
                    "new target changed during atomic creation"
                )
        except FileExistsError:
            existing = _read_existing(directory_fd, parsed.basename)
            if existing != payload:
                raise DecisionBoardIdempotencyConflictError(
                    "Decision Board identity already contains different bytes"
                ) from None
        except OSError as exc:
            if exc.errno in {errno.ELOOP, errno.ENOTDIR, errno.EISDIR}:
                raise DecisionBoardStoragePathError(
                    "target became unsafe during atomic creation"
                ) from exc
            raise
        if created_target is not None:
            try:
                os.fsync(directory_fd)
            except OSError:
                if _target_matches(directory_fd, parsed.basename, created_target):
                    os.unlink(parsed.basename, dir_fd=directory_fd)
                raise
        return directory / parsed.basename
    finally:
        if temp_name is not None:
            with suppress(FileNotFoundError):
                os.unlink(temp_name, dir_fd=directory_fd)
        if lock_fd is not None:
            fcntl.flock(lock_fd, fcntl.LOCK_UN)
            os.close(lock_fd)
        os.close(directory_fd)


__all__ = [
    "DecisionBoardIdempotencyConflictError",
    "DecisionBoardStorageError",
    "DecisionBoardStoragePathError",
    "ParsedDecisionBoardStorageKey",
    "build_decision_board_storage_key",
    "parse_decision_board_storage_key",
    "write_decision_board_report",
]
