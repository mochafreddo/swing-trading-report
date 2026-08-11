"""Durable local-only journal for Decision Board V0 shadow runs.

The journal owns only local observation state and cannot authorize a decision or
perform external side effects.

Transition contract::

    EXPECTED -- grace elapsed, no STARTED --> MISSED_EXPECTED
       |
       v
    STARTED -----------------------------> PUBLISHED | BLOCKED | FAILED
       |
       +-- terminal TTL elapsed ---------> STALE_INCOMPLETE

MISSED_EXPECTED and STALE_INCOMPLETE are immutable historical observations. A
later schedule identity starts independently and can complete normally.
"""

from __future__ import annotations

import errno
import fcntl
import hashlib
import json
import logging
import os
import re
import secrets
import signal
import stat
import sys
import threading
import weakref
from collections.abc import Callable, Iterable, Iterator
from contextlib import contextmanager, suppress
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum
from pathlib import Path

from .results import (
    DecisionRunIssueCodeV0,
    DecisionRunResultV0,
    serialize_decision_run_result_v0,
)
from .runner import RunKindV0

_RUN_ID_PATTERN = re.compile(r"[A-Za-z0-9][A-Za-z0-9_-]{0,127}\Z")
_ISSUE_CODE_PATTERN = re.compile(r"[A-Z][A-Z0-9_]{0,127}\Z")
_REPORT_FILE_PATTERN = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,255}\Z")
_ORPHAN_BACKUP_PATTERN = re.compile(
    r"^\.[A-Za-z0-9][A-Za-z0-9._-]{0,511}\.json\.[0-9a-f]{24}\.backup\Z"
)
_NORMAL_TERMINAL = frozenset({"PUBLISHED", "BLOCKED", "FAILED"})
_SANITIZED_ISSUE_CODES = frozenset(code.value for code in DecisionRunIssueCodeV0) | {
    "MISSED_EXPECTED",
    "STALE_INCOMPLETE",
}
_ALL_FIELDS = frozenset(
    {
        "schema_version",
        "run_id",
        "run_kind",
        "status",
        "expected_at",
        "started_at",
        "terminal_at",
        "grace_seconds",
        "stale_seconds",
        "issues",
        "report_file",
    }
)
_LOGGER = logging.getLogger(__name__)
_OWNED_OPEN_SIGNALS = frozenset(
    signal.valid_signals() - {signal.SIGKILL, signal.SIGSTOP}
)
_DIRECTORY_READ_FLAGS = (
    os.O_RDONLY | getattr(os, "O_DIRECTORY", 0) | getattr(os, "O_NOFOLLOW", 0)
)
_DIRECTORY_SEARCH_FLAGS = (
    getattr(os, "O_SEARCH", getattr(os, "O_PATH", os.O_RDONLY))
    | getattr(os, "O_DIRECTORY", 0)
    | getattr(os, "O_NOFOLLOW", 0)
)


class RunJournalError(RuntimeError):
    """Base sanitized RunJournal failure."""


class RunJournalConflictError(RunJournalError):
    """The durable identity already contains a different state."""


class RunJournalStorageError(RunJournalError):
    """The local journal could not be read or written safely."""


class RunJournalCommittedCleanupError(RunJournalStorageError):
    """A durable record committed, but owned-resource cleanup was incomplete."""

    def __init__(self, record: RunJournalV0) -> None:
        self.run_id = record.run_id
        self.run_kind = record.run_kind.value
        self.status = record.status.value
        expected_at = _format_timestamp(record.expected_at)
        assert expected_at is not None
        self.expected_at = expected_at
        super().__init__("journal committed but resource cleanup was incomplete")


class RunJournalStatusV0(StrEnum):
    STARTED = "STARTED"
    PUBLISHED = "PUBLISHED"
    BLOCKED = "BLOCKED"
    FAILED = "FAILED"
    MISSED_EXPECTED = "MISSED_EXPECTED"
    STALE_INCOMPLETE = "STALE_INCOMPLETE"


@dataclass(frozen=True, slots=True)
class RunJournalIssueV0:
    code: str
    message: str

    def to_public_dict(self) -> dict[str, str]:
        if type(self) is not RunJournalIssueV0:
            raise TypeError("journal issue must use the exact type")
        _validate_issue(self.code, self.message)
        return {"code": self.code, "message": self.message}


@dataclass(frozen=True, slots=True, init=False, weakref_slot=True)
class ExpectedRunV0:
    run_kind: RunKindV0
    expected_at: datetime
    run_id: str

    def __new__(cls) -> ExpectedRunV0:
        del cls
        raise TypeError("expected runs require the trusted factory")

    @classmethod
    def create(
        cls,
        *,
        run_kind: RunKindV0,
        expected_at: datetime,
        run_id: str,
    ) -> ExpectedRunV0:
        del cls
        kind = _require_run_kind(run_kind)
        expected = _require_utc(expected_at, "expected_at")
        identity = _require_run_id(run_id)
        value = object.__new__(ExpectedRunV0)
        object.__setattr__(value, "run_kind", kind)
        object.__setattr__(value, "expected_at", expected)
        object.__setattr__(value, "run_id", identity)
        _register_expected_run(value)
        return value


type _ExpectedSnapshot = tuple[RunKindV0, datetime, str]
_EXPECTED_RUNS: dict[
    int, tuple[weakref.ReferenceType[ExpectedRunV0], _ExpectedSnapshot]
] = {}


def _expected_snapshot(value: ExpectedRunV0) -> _ExpectedSnapshot:
    return value.run_kind, value.expected_at, value.run_id


def _register_expected_run(value: ExpectedRunV0) -> None:
    snapshot = _expected_snapshot(value)
    value_id = id(value)

    def discard(reference: weakref.ReferenceType[ExpectedRunV0]) -> None:
        current = _EXPECTED_RUNS.get(value_id)
        if current is not None and current[0] is reference:
            _EXPECTED_RUNS.pop(value_id, None)

    reference = weakref.ref(value, discard)
    _EXPECTED_RUNS[value_id] = reference, snapshot


def _require_expected_run(value: object) -> ExpectedRunV0:
    if type(value) is not ExpectedRunV0:
        raise TypeError("expected slot must use the exact ExpectedRunV0 type")
    record = _EXPECTED_RUNS.get(id(value))
    try:
        snapshot = _expected_snapshot(value)
    except Exception as exc:
        raise TypeError("expected slot is not an unchanged issued value") from exc
    if record is None or record[0]() is not value or record[1] != snapshot:
        raise TypeError("expected slot is not an unchanged issued value")
    _require_run_kind(value.run_kind)
    _require_utc(value.expected_at, "expected_at")
    _require_run_id(value.run_id)
    return value


@dataclass(frozen=True, slots=True, init=False, weakref_slot=True)
class RunJournalV0:
    schema_version: str
    run_id: str
    run_kind: RunKindV0
    status: RunJournalStatusV0
    expected_at: datetime
    started_at: datetime | None
    terminal_at: datetime | None
    grace_seconds: int
    stale_seconds: int
    issues: tuple[RunJournalIssueV0, ...]
    report_file: str | None

    def __new__(cls) -> RunJournalV0:
        del cls
        raise TypeError("RunJournal records require the trusted factory")

    def to_public_dict(self) -> dict[str, object]:
        return serialize_run_journal_v0(self)


type _Snapshot = tuple[object, ...]
_RECORDS: dict[int, tuple[weakref.ReferenceType[RunJournalV0], _Snapshot]] = {}


def _require_run_kind(value: object) -> RunKindV0:
    if type(value) is not RunKindV0:
        raise TypeError("run_kind must be an exact RunKindV0")
    return value


def _require_utc(value: object, field: str) -> datetime:
    if type(value) is not datetime:
        raise TypeError(f"{field} must be an exact datetime")
    offset = value.utcoffset()
    if value.tzinfo is None or offset is None or offset.total_seconds() != 0:
        raise ValueError(f"{field} must be UTC")
    return value.astimezone(UTC)


def _require_optional_utc(value: object, field: str) -> datetime | None:
    if value is None:
        return None
    return _require_utc(value, field)


def _require_run_id(value: object) -> str:
    if type(value) is not str or _RUN_ID_PATTERN.fullmatch(value) is None:
        raise ValueError("run_id must be conservative ASCII")
    return value


def _require_report_file(value: object) -> str | None:
    if value is None:
        return None
    if (
        type(value) is not str
        or _REPORT_FILE_PATTERN.fullmatch(value) is None
        or Path(value).name != value
    ):
        raise ValueError("report_file must be a conservative basename")
    return value


def _require_policy_seconds(value: object, field: str, *, minimum: int) -> int:
    if type(value) is not int or value < minimum or value > 604800:
        raise ValueError(f"{field} must be a bounded integer")
    return value


def _validate_issue(code: object, message: object) -> tuple[str, str]:
    if type(code) is not str or _ISSUE_CODE_PATTERN.fullmatch(code) is None:
        raise ValueError("journal issue code is invalid")
    if type(message) is not str or not message or not message.isascii():
        raise ValueError("journal issue message must be nonempty ASCII")
    return code, message


def _issue_message(code: str) -> str:
    if code == RunJournalStatusV0.MISSED_EXPECTED.value:
        return "Expected run did not start before its grace deadline."
    if code == RunJournalStatusV0.STALE_INCOMPLETE.value:
        return "Started run did not reach a terminal state before its TTL."
    return f"Run reported sanitized issue code {code}."


def _make_issues(issue_codes: Iterable[str]) -> tuple[RunJournalIssueV0, ...]:
    codes: list[str] = []
    for code in issue_codes:
        valid, _ = _validate_issue(code, _issue_message(code))
        if valid not in _SANITIZED_ISSUE_CODES:
            raise ValueError("journal issue code is not sanitized")
        if valid not in codes:
            codes.append(valid)
    return tuple(
        RunJournalIssueV0(code, _issue_message(code)) for code in sorted(codes)
    )


def _validate_state(
    *,
    status: RunJournalStatusV0,
    expected_at: datetime,
    started_at: datetime | None,
    terminal_at: datetime | None,
    grace_seconds: int,
    stale_seconds: int,
    issues: tuple[RunJournalIssueV0, ...],
    report_file: str | None,
) -> None:
    _require_policy_seconds(grace_seconds, "grace_seconds", minimum=0)
    _require_policy_seconds(stale_seconds, "stale_seconds", minimum=1)
    if status is RunJournalStatusV0.STARTED:
        if started_at is None or terminal_at is not None or issues or report_file:
            raise ValueError("STARTED has only a started timestamp")
    elif status is RunJournalStatusV0.MISSED_EXPECTED:
        if started_at is not None or terminal_at is None or report_file is not None:
            raise ValueError("MISSED_EXPECTED has no started run or report")
        if tuple(issue.code for issue in issues) != (status.value,):
            raise ValueError("MISSED_EXPECTED requires its sanitized issue")
    elif status is RunJournalStatusV0.STALE_INCOMPLETE:
        if started_at is None or terminal_at is None or report_file is not None:
            raise ValueError("STALE_INCOMPLETE requires one abandoned start")
        if tuple(issue.code for issue in issues) != (status.value,):
            raise ValueError("STALE_INCOMPLETE requires its sanitized issue")
    else:
        if status.value not in _NORMAL_TERMINAL:
            raise ValueError("journal status is unsupported")
        if started_at is None or terminal_at is None:
            raise ValueError("normal terminal states require start and terminal times")
        issue_codes = tuple(issue.code for issue in issues)
        if status in {
            RunJournalStatusV0.PUBLISHED,
            RunJournalStatusV0.BLOCKED,
        }:
            if issue_codes not in {(), (DecisionRunIssueCodeV0.UPLOAD_FAILED.value,)}:
                raise ValueError("stored terminal state has invalid issues")
            if report_file is None:
                raise ValueError("stored terminal state requires report_file")
        elif status is RunJournalStatusV0.FAILED:
            decision_codes = frozenset(code.value for code in DecisionRunIssueCodeV0)
            if len(issue_codes) != 1 or issue_codes[0] not in decision_codes:
                raise ValueError("FAILED requires one sanitized decision issue")
            if (issue_codes[0] == DecisionRunIssueCodeV0.UPLOAD_FAILED.value) != (
                report_file is not None
            ):
                raise ValueError("FAILED report_file must match UPLOAD_FAILED")
    if started_at is not None and started_at < expected_at:
        raise ValueError("started_at cannot precede expected_at")
    if terminal_at is not None:
        lower_bound = started_at if started_at is not None else expected_at
        if terminal_at < lower_bound:
            raise ValueError("terminal_at cannot precede the observed state")
    for issue in issues:
        if type(issue) is not RunJournalIssueV0:
            raise TypeError("issues require exact RunJournalIssueV0 values")
        issue.to_public_dict()


def create_run_journal_v0(
    *,
    run_kind: RunKindV0,
    expected_at: datetime,
    run_id: str,
    status: RunJournalStatusV0,
    started_at: datetime | None,
    terminal_at: datetime | None,
    grace_seconds: int,
    stale_seconds: int,
    issue_codes: Iterable[str] = (),
    report_file: str | None = None,
) -> RunJournalV0:
    kind = _require_run_kind(run_kind)
    expected = _require_utc(expected_at, "expected_at")
    identity = _require_run_id(run_id)
    if type(status) is not RunJournalStatusV0:
        raise TypeError("status must be an exact RunJournalStatusV0")
    started = _require_optional_utc(started_at, "started_at")
    terminal = _require_optional_utc(terminal_at, "terminal_at")
    grace = _require_policy_seconds(grace_seconds, "grace_seconds", minimum=0)
    stale = _require_policy_seconds(stale_seconds, "stale_seconds", minimum=1)
    issues = _make_issues(issue_codes)
    basename = _require_report_file(report_file)
    _validate_state(
        status=status,
        expected_at=expected,
        started_at=started,
        terminal_at=terminal,
        grace_seconds=grace,
        stale_seconds=stale,
        issues=issues,
        report_file=basename,
    )
    value = object.__new__(RunJournalV0)
    object.__setattr__(value, "schema_version", "decision-board.v0")
    object.__setattr__(value, "run_id", identity)
    object.__setattr__(value, "run_kind", kind)
    object.__setattr__(value, "status", status)
    object.__setattr__(value, "expected_at", expected)
    object.__setattr__(value, "started_at", started)
    object.__setattr__(value, "terminal_at", terminal)
    object.__setattr__(value, "grace_seconds", grace)
    object.__setattr__(value, "stale_seconds", stale)
    object.__setattr__(value, "issues", issues)
    object.__setattr__(value, "report_file", basename)
    _register(value)
    return value


def _snapshot(value: RunJournalV0) -> _Snapshot:
    return (
        value.schema_version,
        value.run_id,
        value.run_kind,
        value.status,
        value.expected_at,
        value.started_at,
        value.terminal_at,
        value.grace_seconds,
        value.stale_seconds,
        value.issues,
        value.report_file,
    )


def _register(value: RunJournalV0) -> None:
    snapshot = _snapshot(value)
    value_id = id(value)

    def discard(reference: weakref.ReferenceType[RunJournalV0]) -> None:
        current = _RECORDS.get(value_id)
        if current is not None and current[0] is reference:
            _RECORDS.pop(value_id, None)

    reference = weakref.ref(value, discard)
    _RECORDS[value_id] = reference, snapshot


def _require_record(value: object) -> RunJournalV0:
    if type(value) is not RunJournalV0:
        raise TypeError("journal record must use the exact RunJournalV0 type")
    record = _RECORDS.get(id(value))
    try:
        snapshot = _snapshot(value)
    except Exception as exc:
        raise TypeError("journal record is not an unchanged issued value") from exc
    if record is None or record[0]() is not value or record[1] != snapshot:
        raise TypeError("journal record is not an unchanged issued value")
    _validate_state(
        status=value.status,
        expected_at=value.expected_at,
        started_at=value.started_at,
        terminal_at=value.terminal_at,
        grace_seconds=value.grace_seconds,
        stale_seconds=value.stale_seconds,
        issues=value.issues,
        report_file=value.report_file,
    )
    return value


def _format_timestamp(value: datetime | None) -> str | None:
    if value is None:
        return None
    return value.isoformat().replace("+00:00", "Z")


def serialize_run_journal_v0(value: object) -> dict[str, object]:
    record = _require_record(value)
    return {
        "schema_version": record.schema_version,
        "run_id": record.run_id,
        "run_kind": record.run_kind.value,
        "status": record.status.value,
        "expected_at": _format_timestamp(record.expected_at),
        "started_at": _format_timestamp(record.started_at),
        "terminal_at": _format_timestamp(record.terminal_at),
        "grace_seconds": record.grace_seconds,
        "stale_seconds": record.stale_seconds,
        "issues": [issue.to_public_dict() for issue in record.issues],
        "report_file": record.report_file,
    }


def canonical_run_journal_bytes_v0(value: object) -> bytes:
    return (
        json.dumps(
            serialize_run_journal_v0(value),
            ensure_ascii=True,
            separators=(",", ":"),
            sort_keys=True,
        )
        + "\n"
    ).encode("ascii")


def _parse_timestamp(value: object, field: str) -> datetime | None:
    if value is None:
        return None
    if type(value) is not str or not value.endswith("Z"):
        raise ValueError(f"{field} must be an exact UTC RFC3339 string")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError(f"{field} is invalid") from exc
    if _format_timestamp(parsed) != value:
        raise ValueError(f"{field} is not canonical")
    return _require_utc(parsed, field)


def parse_run_journal_v0(value: object) -> RunJournalV0:
    if type(value) is not dict or frozenset(value) != _ALL_FIELDS:
        raise ValueError("journal payload must contain the exact field set")
    if value["schema_version"] != "decision-board.v0":
        raise ValueError("journal schema_version is invalid")
    if type(value["run_kind"]) is not str or type(value["status"]) is not str:
        raise TypeError("journal enum fields must be strings")
    raw_issues = value["issues"]
    if type(raw_issues) is not list:
        raise TypeError("journal issues must be an exact list")
    issue_codes: list[str] = []
    for raw in raw_issues:
        if type(raw) is not dict or frozenset(raw) != {"code", "message"}:
            raise ValueError("journal issue must contain the exact field set")
        code, message = _validate_issue(raw["code"], raw["message"])
        if message != _issue_message(code):
            raise ValueError("journal issue message is not canonical")
        issue_codes.append(code)
    record = create_run_journal_v0(
        run_kind=RunKindV0(value["run_kind"]),
        expected_at=_parse_timestamp(value["expected_at"], "expected_at"),  # type: ignore[arg-type]
        run_id=value["run_id"],  # type: ignore[arg-type]
        status=RunJournalStatusV0(value["status"]),
        started_at=_parse_timestamp(value["started_at"], "started_at"),
        terminal_at=_parse_timestamp(value["terminal_at"], "terminal_at"),
        grace_seconds=value["grace_seconds"],  # type: ignore[arg-type]
        stale_seconds=value["stale_seconds"],  # type: ignore[arg-type]
        issue_codes=issue_codes,
        report_file=value["report_file"],  # type: ignore[arg-type]
    )
    if serialize_run_journal_v0(record) != value:
        raise ValueError("journal payload is not canonical")
    return record


def _identity_key(run_kind: RunKindV0, expected_at: datetime, run_id: str) -> bytes:
    return (f"{run_kind.value}\0{_format_timestamp(expected_at)}\0{run_id}").encode(
        "ascii"
    )


def _journal_basename(run_kind: RunKindV0, expected_at: datetime, run_id: str) -> str:
    stamp = expected_at.strftime("%Y%m%dT%H%M%SZ")
    digest = hashlib.sha256(_identity_key(run_kind, expected_at, run_id)).hexdigest()[
        :16
    ]
    return f"{run_kind.value.lower()}-{stamp}-{run_id}-{digest}.json"


@dataclass(frozen=True, slots=True)
class _JournalLock:
    fd: int
    name: str
    device: int
    inode: int


@dataclass(frozen=True, slots=True)
class _PathNode:
    fd: int
    name: str
    device: int
    inode: int


@dataclass(frozen=True, slots=True)
class _RootGuard:
    anchor_fd: int
    anchor_device: int
    anchor_inode: int
    nodes: tuple[_PathNode, ...]

    @property
    def directory_fd(self) -> int:
        return self.nodes[-1].fd


@dataclass(slots=True)
class _PendingWrite:
    basename: str
    replacement: os.stat_result
    previous: os.stat_result | None
    backup_name: str | None
    backup_info: os.stat_result | None


@dataclass(slots=True)
class _LockedJournal:
    directory_fd: int
    lock: _JournalLock
    root: _RootGuard
    pending: list[tuple[_PendingWrite, RunJournalV0]]
    committed: tuple[RunJournalV0, ...] = ()


def _close_fd(fd: int) -> None:
    os.close(fd)


def _require_single_threaded() -> None:
    if threading.active_count() != 1:
        raise RunJournalStorageError(
            "journal operations require a single-threaded process"
        )


def _query_signal_mask() -> frozenset[int | signal.Signals]:
    return frozenset(signal.pthread_sigmask(signal.SIG_BLOCK, frozenset()))


def _restore_signal_mask(
    previous_mask: frozenset[int | signal.Signals],
) -> BaseException | None:
    """Restore a known mask, returning any recovered post-effect exception."""

    try:
        signal.pthread_sigmask(signal.SIG_SETMASK, previous_mask)
        return None
    except BaseException as first:
        with suppress(BaseException):
            signal.pthread_sigmask(signal.SIG_SETMASK, previous_mask)
        try:
            current_mask = _query_signal_mask()
        except BaseException as verify_error:
            raise first from verify_error
        if current_mask != previous_mask:
            verification_error = RunJournalStorageError(
                "journal signal mask restoration could not be verified"
            )
            raise first from verification_error
        return first


def _owned_open(
    path: str | Path,
    flags: int,
    mode: int = 0o777,
    *,
    dir_fd: int | None = None,
) -> int:
    """Open one FD while blockable signals cannot split ownership."""

    _require_single_threaded()
    resolved_path = os.fspath(path)
    previous_mask = _query_signal_mask()
    try:
        signal.pthread_sigmask(signal.SIG_BLOCK, _OWNED_OPEN_SIGNALS)
    except BaseException as block_error:
        try:
            recovery_error = _restore_signal_mask(previous_mask)
        except BaseException as recovery_failure:
            raise block_error from recovery_failure
        if recovery_error is not None:
            raise block_error from recovery_error
        raise
    fd: int | None = None
    operation_error: BaseException | None = None
    try:
        fd = os.open(resolved_path, flags, mode, dir_fd=dir_fd)
    except BaseException as exc:
        operation_error = exc
    try:
        restore_error = _restore_signal_mask(previous_mask)
    except BaseException as restore_failure:
        if fd is not None:
            with suppress(BaseException):
                os.close(fd)
        if operation_error is not None:
            raise operation_error from restore_failure
        raise
    if restore_error is not None:
        if operation_error is not None:
            raise operation_error from restore_error
        assert fd is not None
        with suppress(BaseException):
            os.close(fd)
        raise restore_error
    if operation_error is not None:
        raise operation_error
    assert fd is not None
    return fd


def _open_journal_directory(root: Path) -> int:
    """Compatibility helper used by focused acquisition-failure probes."""

    absolute = Path(os.path.abspath(root))
    try:
        directory_fd = _owned_open(absolute, _DIRECTORY_READ_FLAGS)
    except OSError as exc:
        raise RunJournalStorageError("journal root could not be opened safely") from exc
    try:
        opened = os.fstat(directory_fd)
        if not stat.S_ISDIR(opened.st_mode):
            raise RunJournalStorageError("journal root is not a safe directory")
    except BaseException:
        with suppress(BaseException):
            _close_fd(directory_fd)
        raise
    return directory_fd


def _open_root_guard(root: Path) -> _RootGuard:
    absolute = Path(os.path.abspath(root))
    components = absolute.parts[1:]
    if not components:
        raise RunJournalStorageError("journal root must not be the filesystem root")
    try:
        anchor_fd = _owned_open("/", _DIRECTORY_READ_FLAGS)
    except OSError as exc:
        raise RunJournalStorageError("journal path anchor is unavailable") from exc
    nodes: list[_PathNode] = []
    try:
        anchor_info = os.fstat(anchor_fd)
        if not stat.S_ISDIR(anchor_info.st_mode):
            raise RunJournalStorageError("journal path anchor is not a directory")
        # All local RunJournal processes share this stable, short critical section.
        fcntl.flock(anchor_fd, fcntl.LOCK_EX)
        parent_fd = anchor_fd
        for index, component in enumerate(components):
            flags = (
                _DIRECTORY_READ_FLAGS
                if index == len(components) - 1
                else _DIRECTORY_SEARCH_FLAGS
            )
            try:
                child_fd = _owned_open(component, flags, dir_fd=parent_fd)
            except FileNotFoundError:
                try:
                    os.mkdir(component, mode=0o700, dir_fd=parent_fd)
                except FileExistsError:
                    pass
                except OSError as exc:
                    raise RunJournalStorageError(
                        "journal path component could not be created"
                    ) from exc
                try:
                    child_fd = _owned_open(component, flags, dir_fd=parent_fd)
                except OSError as exc:
                    raise RunJournalStorageError(
                        "journal path component could not be opened safely"
                    ) from exc
            except OSError as exc:
                raise RunJournalStorageError(
                    "journal path component could not be opened safely"
                ) from exc
            try:
                child_info = os.fstat(child_fd)
                if not stat.S_ISDIR(child_info.st_mode):
                    raise RunJournalStorageError(
                        "journal path component is not a directory"
                    )
            except BaseException:
                with suppress(BaseException):
                    _close_fd(child_fd)
                raise
            nodes.append(
                _PathNode(
                    child_fd,
                    component,
                    child_info.st_dev,
                    child_info.st_ino,
                )
            )
            parent_fd = child_fd
        guard = _RootGuard(
            anchor_fd,
            anchor_info.st_dev,
            anchor_info.st_ino,
            tuple(nodes),
        )
        _assert_root_unchanged(guard)
        return guard
    except BaseException:
        for node in reversed(nodes):
            with suppress(BaseException):
                _close_fd(node.fd)
        with suppress(BaseException):
            fcntl.flock(anchor_fd, fcntl.LOCK_UN)
        with suppress(BaseException):
            _close_fd(anchor_fd)
        raise


def _assert_root_unchanged(root: _RootGuard) -> None:
    try:
        anchor_opened = os.fstat(root.anchor_fd)
        anchor_current = os.stat("/", follow_symlinks=False)
    except OSError as exc:
        raise RunJournalStorageError("journal path changed") from exc
    anchor_expected = (root.anchor_device, root.anchor_inode)
    if (
        not stat.S_ISDIR(anchor_opened.st_mode)
        or (anchor_opened.st_dev, anchor_opened.st_ino) != anchor_expected
        or not stat.S_ISDIR(anchor_current.st_mode)
        or (anchor_current.st_dev, anchor_current.st_ino) != anchor_expected
    ):
        raise RunJournalStorageError("journal path changed")
    parent_fd = root.anchor_fd
    for node in root.nodes:
        try:
            opened = os.fstat(node.fd)
            current = os.stat(node.name, dir_fd=parent_fd, follow_symlinks=False)
        except OSError as exc:
            raise RunJournalStorageError("journal path changed") from exc
        expected = (node.device, node.inode)
        if (
            not stat.S_ISDIR(opened.st_mode)
            or (opened.st_dev, opened.st_ino) != expected
            or not stat.S_ISDIR(current.st_mode)
            or (current.st_dev, current.st_ino) != expected
        ):
            raise RunJournalStorageError("journal path changed")
        parent_fd = node.fd


def _assert_journal_lock(directory_fd: int, lock: _JournalLock) -> None:
    try:
        opened = os.fstat(lock.fd)
        current = os.stat(lock.name, dir_fd=directory_fd, follow_symlinks=False)
    except OSError as exc:
        raise RunJournalStorageError("journal lock changed") from exc
    expected = (lock.device, lock.inode)
    if (
        not stat.S_ISREG(opened.st_mode)
        or opened.st_nlink != 1
        or (opened.st_dev, opened.st_ino) != expected
        or not stat.S_ISREG(current.st_mode)
        or current.st_nlink != 1
        or (current.st_dev, current.st_ino) != expected
    ):
        raise RunJournalStorageError("journal lock changed")


def _open_journal_lock(directory_fd: int) -> _JournalLock:
    name = ".run-journal-v0.lock"
    nofollow = getattr(os, "O_NOFOLLOW", 0)
    try:
        try:
            created_fd = _owned_open(
                name,
                os.O_WRONLY | os.O_CREAT | os.O_EXCL | nofollow,
                0o600,
                dir_fd=directory_fd,
            )
        except FileExistsError:
            pass
        else:
            _close_fd(created_fd)
        lock_fd = _owned_open(name, os.O_RDWR | nofollow, dir_fd=directory_fd)
    except OSError as exc:
        raise RunJournalStorageError("journal lock could not be opened safely") from exc
    directory_locked = False
    target_locked = False
    try:
        info = os.fstat(lock_fd)
        if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1:
            raise RunJournalStorageError("journal lock is not a private file")
        fcntl.flock(directory_fd, fcntl.LOCK_EX)
        directory_locked = True
        fcntl.flock(lock_fd, fcntl.LOCK_EX)
        target_locked = True
        lock = _JournalLock(lock_fd, name, info.st_dev, info.st_ino)
        _assert_journal_lock(directory_fd, lock)
        return lock
    except BaseException as exc:
        if target_locked:
            try:
                fcntl.flock(lock_fd, fcntl.LOCK_UN)
            except BaseException:
                with suppress(BaseException):
                    fcntl.flock(lock_fd, fcntl.LOCK_UN)
        if directory_locked:
            try:
                fcntl.flock(directory_fd, fcntl.LOCK_UN)
            except BaseException:
                with suppress(BaseException):
                    fcntl.flock(directory_fd, fcntl.LOCK_UN)
        with suppress(BaseException):
            _close_fd(lock_fd)
        if isinstance(exc, RunJournalStorageError):
            raise
        if isinstance(exc, OSError):
            raise RunJournalStorageError("journal lock is unavailable") from exc
        raise


def _read_record(
    directory_fd: int, basename: str
) -> tuple[RunJournalV0, bytes, os.stat_result]:
    flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0)
    try:
        target_fd = _owned_open(basename, flags, dir_fd=directory_fd)
    except FileNotFoundError:
        raise
    except OSError as exc:
        raise RunJournalStorageError(
            "journal record could not be opened safely"
        ) from exc
    try:
        opened = os.fstat(target_fd)
        if not stat.S_ISREG(opened.st_mode) or opened.st_nlink != 1:
            raise RunJournalStorageError("journal record is not a private file")
        chunks: list[bytes] = []
        while chunk := os.read(target_fd, 1024 * 1024):
            chunks.append(chunk)
        current = os.stat(basename, dir_fd=directory_fd, follow_symlinks=False)
        if (
            not stat.S_ISREG(current.st_mode)
            or current.st_nlink != 1
            or (current.st_dev, current.st_ino) != (opened.st_dev, opened.st_ino)
        ):
            raise RunJournalStorageError("journal record changed during read")
        payload = b"".join(chunks)
        raw = json.loads(payload)
        record = parse_run_journal_v0(raw)
        canonical = canonical_run_journal_bytes_v0(record)
        if payload != canonical:
            raise RunJournalStorageError("journal record bytes are not canonical")
        return record, canonical, opened
    except RunJournalStorageError:
        raise
    except (OSError, UnicodeError, json.JSONDecodeError, TypeError, ValueError) as exc:
        raise RunJournalStorageError("journal record is invalid") from exc
    finally:
        primary = sys.exception()
        try:
            _close_fd(target_fd)
        except BaseException:
            if primary is None:
                raise


def _target_matches(directory_fd: int, basename: str, expected: os.stat_result) -> bool:
    try:
        current = os.stat(basename, dir_fd=directory_fd, follow_symlinks=False)
    except FileNotFoundError:
        return False
    return (
        stat.S_ISREG(current.st_mode)
        and current.st_nlink == 1
        and (
            current.st_dev,
            current.st_ino,
        )
        == (expected.st_dev, expected.st_ino)
    )


def _unlink_if_matches(
    directory_fd: int,
    basename: str,
    expected: os.stat_result,
    *,
    expected_links: frozenset[int] = frozenset({1}),
) -> bool:
    try:
        current = os.stat(basename, dir_fd=directory_fd, follow_symlinks=False)
    except FileNotFoundError:
        return False
    if (
        not stat.S_ISREG(current.st_mode)
        or current.st_nlink not in expected_links
        or (current.st_dev, current.st_ino) != (expected.st_dev, expected.st_ino)
    ):
        return False
    os.unlink(basename, dir_fd=directory_fd)
    return True


def _write_private_temp(
    directory_fd: int, basename: str, payload: bytes
) -> tuple[str, os.stat_result]:
    for _ in range(32):
        name = f".{basename}.{secrets.token_hex(12)}.tmp"
        try:
            fd = _owned_open(
                name,
                os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0),
                0o600,
                dir_fd=directory_fd,
            )
        except FileExistsError:
            continue
        except BaseException:
            with suppress(BaseException):
                current = os.stat(name, dir_fd=directory_fd, follow_symlinks=False)
                if stat.S_ISREG(current.st_mode) and current.st_nlink == 1:
                    os.unlink(name, dir_fd=directory_fd)
            raise
        info: os.stat_result | None = None
        try:
            info = os.fstat(fd)
            view = memoryview(payload)
            while view:
                written = os.write(fd, view)
                if written < 1:
                    raise OSError("journal temporary write made no progress")
                view = view[written:]
            os.fsync(fd)
            assert info is not None
            return name, info
        except BaseException:
            with suppress(BaseException):
                if info is None:
                    current = os.stat(name, dir_fd=directory_fd, follow_symlinks=False)
                    if stat.S_ISREG(current.st_mode) and current.st_nlink == 1:
                        os.unlink(name, dir_fd=directory_fd)
                else:
                    _unlink_if_matches(directory_fd, name, info)
            raise
        finally:
            primary = sys.exception()
            try:
                _close_fd(fd)
            except BaseException:
                if primary is None:
                    with suppress(BaseException):
                        if info is not None:
                            _unlink_if_matches(directory_fd, name, info)
                    raise
    raise RunJournalStorageError("journal temporary file could not be allocated")


def _atomic_replace_record(
    directory_fd: int,
    lock: _JournalLock,
    root: _RootGuard,
    basename: str,
    payload: bytes,
    *,
    expected: os.stat_result | None,
) -> _PendingWrite:
    temp_name, temp_info = _write_private_temp(directory_fd, basename, payload)
    backup_name: str | None = None
    backup_info: os.stat_result | None = None
    try:
        _assert_journal_lock(directory_fd, lock)
        if expected is None:
            try:
                os.stat(basename, dir_fd=directory_fd, follow_symlinks=False)
            except FileNotFoundError:
                pass
            else:
                raise RunJournalConflictError("run identity appeared during write")
        else:
            if not _target_matches(directory_fd, basename, expected):
                raise RunJournalConflictError("journal compare-and-set conflict")
            backup_name = f".{basename}.{secrets.token_hex(12)}.backup"
            os.link(
                basename,
                backup_name,
                src_dir_fd=directory_fd,
                dst_dir_fd=directory_fd,
                follow_symlinks=False,
            )
            backup_info = os.stat(
                backup_name, dir_fd=directory_fd, follow_symlinks=False
            )
            if (
                not stat.S_ISREG(backup_info.st_mode)
                or backup_info.st_nlink != 2
                or (backup_info.st_dev, backup_info.st_ino)
                != (expected.st_dev, expected.st_ino)
            ):
                raise RunJournalStorageError("journal backup identity changed")
            os.fsync(directory_fd)
        _assert_journal_lock(directory_fd, lock)
        _assert_root_unchanged(root)
        try:
            os.replace(
                temp_name,
                basename,
                src_dir_fd=directory_fd,
                dst_dir_fd=directory_fd,
            )
            if not _target_matches(directory_fd, basename, temp_info):
                raise RunJournalStorageError("journal replacement identity changed")
            _assert_journal_lock(directory_fd, lock)
            _assert_root_unchanged(root)
            os.fsync(directory_fd)
            _assert_journal_lock(directory_fd, lock)
            _assert_root_unchanged(root)
        except BaseException as primary:
            pending = _PendingWrite(
                basename, temp_info, expected, backup_name, backup_info
            )
            try:
                _rollback_pending_write(directory_fd, pending)
            except BaseException as rollback_error:
                raise primary from rollback_error
            raise
        temp_name = ""
        return _PendingWrite(basename, temp_info, expected, backup_name, backup_info)
    except BaseException as primary:
        if backup_name is not None and backup_info is not None:
            try:
                _unlink_if_matches(
                    directory_fd,
                    backup_name,
                    backup_info,
                    expected_links=frozenset({1, 2}),
                )
            except BaseException as cleanup_error:
                raise primary from cleanup_error
        raise
    finally:
        if temp_name:
            with suppress(BaseException):
                _unlink_if_matches(directory_fd, temp_name, temp_info)


def _rollback_pending_write(directory_fd: int, pending: _PendingWrite) -> None:
    if not _target_matches(directory_fd, pending.basename, pending.replacement):
        if pending.previous is not None and _target_matches(
            directory_fd, pending.basename, pending.previous
        ):
            return
        raise RunJournalStorageError("journal rollback target identity changed")
    if pending.previous is None:
        if not _unlink_if_matches(directory_fd, pending.basename, pending.replacement):
            raise RunJournalStorageError("journal rollback target identity changed")
    else:
        if pending.backup_name is None or pending.backup_info is None:
            raise RunJournalStorageError("journal rollback backup is unavailable")
        current_backup = os.stat(
            pending.backup_name,
            dir_fd=directory_fd,
            follow_symlinks=False,
        )
        if (
            not stat.S_ISREG(current_backup.st_mode)
            or current_backup.st_nlink != 1
            or (current_backup.st_dev, current_backup.st_ino)
            != (pending.previous.st_dev, pending.previous.st_ino)
        ):
            raise RunJournalStorageError("journal rollback identity changed")
        try:
            os.replace(
                pending.backup_name,
                pending.basename,
                src_dir_fd=directory_fd,
                dst_dir_fd=directory_fd,
            )
        except BaseException:
            if not _target_matches(directory_fd, pending.basename, pending.previous):
                raise
        if not _target_matches(directory_fd, pending.basename, pending.previous):
            raise RunJournalStorageError("journal rollback target identity changed")
        pending.backup_name = None
    os.fsync(directory_fd)


def _cleanup_committed_backup(directory_fd: int, pending: _PendingWrite) -> None:
    if pending.backup_name is None or pending.backup_info is None:
        return
    try:
        cleaned = _unlink_if_matches(
            directory_fd,
            pending.backup_name,
            pending.backup_info,
            expected_links=frozenset({1}),
        )
    except BaseException:
        try:
            os.stat(
                pending.backup_name,
                dir_fd=directory_fd,
                follow_symlinks=False,
            )
        except FileNotFoundError:
            pending.backup_name = None
            return
        raise
    if not cleaned:
        raise RunJournalStorageError("journal committed backup cleanup was unsafe")
    pending.backup_name = None
    os.fsync(directory_fd)


def _sweep_orphan_backups(directory_fd: int) -> int:
    try:
        names = os.listdir(directory_fd)
    except OSError as exc:
        raise RunJournalStorageError("journal directory could not be listed") from exc
    swept = 0
    for name in names:
        if type(name) is not str or _ORPHAN_BACKUP_PATTERN.fullmatch(name) is None:
            continue
        try:
            info = os.stat(name, dir_fd=directory_fd, follow_symlinks=False)
        except FileNotFoundError:
            continue
        if not stat.S_ISREG(info.st_mode) or info.st_nlink not in {1, 2}:
            raise RunJournalStorageError("journal orphan backup is unsafe")
        if _unlink_if_matches(
            directory_fd,
            name,
            info,
            expected_links=frozenset({1, 2}),
        ):
            swept += 1
    if swept:
        os.fsync(directory_fd)
        _LOGGER.info("swept %d orphan RunJournal backup(s)", swept)
    return swept


def _cleanup_close_fd(fd: int) -> tuple[BaseException | None, bool]:
    try:
        os.close(fd)
        return None, True
    except BaseException as first:
        try:
            fcntl.fcntl(fd, fcntl.F_GETFD)
        except OSError as probe_error:
            if probe_error.errno == errno.EBADF:
                return first, True
        except BaseException:
            pass
        return first, False


class RunJournalStoreV0:
    def __init__(self, root: str | Path) -> None:
        if type(root) is str:
            path = Path(root)
        elif isinstance(root, Path):
            path = root
        else:
            raise TypeError("journal root must be a path string or exact Path")
        self._root = Path(os.path.abspath(path))

    @contextmanager
    def _locked(self) -> Iterator[_LockedJournal]:
        _require_single_threaded()
        root = _open_root_guard(self._root)
        directory_fd = root.directory_fd
        lock: _JournalLock | None = None
        session: _LockedJournal | None = None
        try:
            lock = _open_journal_lock(directory_fd)
            _assert_root_unchanged(root)
            _sweep_orphan_backups(directory_fd)
            session = _LockedJournal(directory_fd, lock, root, [])
            yield session
            _assert_root_unchanged(root)
            _assert_journal_lock(directory_fd, lock)
            for pending, _record in session.pending:
                if not _target_matches(
                    directory_fd, pending.basename, pending.replacement
                ):
                    raise RunJournalStorageError(
                        "journal target changed before durable commit"
                    )
            # Durable commit point: replacement directory fsync has completed,
            # and the full absolute path, lock, and target inode still match.
            session.committed = tuple(record for _pending, record in session.pending)
            committed_cleanup_error: tuple[RunJournalV0, BaseException] | None = None
            for pending, record in session.pending:
                try:
                    _cleanup_committed_backup(directory_fd, pending)
                except BaseException as cleanup_error:
                    if committed_cleanup_error is None:
                        committed_cleanup_error = record, cleanup_error
            if committed_cleanup_error is not None:
                record, committed_error = committed_cleanup_error
                raise RunJournalCommittedCleanupError(record) from committed_error
        except BaseException as exc:
            if session is not None and not session.committed:
                rollback_error: BaseException | None = None
                for pending, _record in reversed(session.pending):
                    try:
                        _rollback_pending_write(directory_fd, pending)
                    except BaseException as candidate:
                        if rollback_error is None:
                            rollback_error = candidate
                if rollback_error is not None:
                    raise exc from rollback_error
            raise
        finally:
            primary = sys.exception()
            cleanup_errors: list[BaseException] = []
            incomplete = False

            def attempt_cleanup(operation: Callable[[], None]) -> None:
                try:
                    operation()
                except BaseException as exc:
                    cleanup_errors.append(exc)

            def attempt_close(fd: int) -> None:
                nonlocal incomplete
                error, closed = _cleanup_close_fd(fd)
                if error is not None:
                    cleanup_errors.append(error)
                if not closed:
                    incomplete = True

            if lock is not None:
                try:
                    _assert_journal_lock(directory_fd, lock)
                except BaseException as exc:
                    cleanup_errors.append(exc)
                try:
                    attempt_cleanup(lambda: fcntl.flock(lock.fd, fcntl.LOCK_UN))
                finally:
                    try:
                        attempt_close(lock.fd)
                    finally:
                        try:
                            attempt_cleanup(
                                lambda: fcntl.flock(directory_fd, fcntl.LOCK_UN)
                            )
                        finally:
                            for node in reversed(root.nodes):
                                attempt_close(node.fd)
            else:
                for node in reversed(root.nodes):
                    attempt_close(node.fd)
            try:
                attempt_cleanup(lambda: fcntl.flock(root.anchor_fd, fcntl.LOCK_UN))
            finally:
                attempt_close(root.anchor_fd)
            if primary is None and cleanup_errors:
                committed = () if session is None else session.committed
                if committed:
                    if incomplete:
                        raise RunJournalCommittedCleanupError(
                            committed[-1]
                        ) from cleanup_errors[0]
                    # Post-effect cleanup errors are recovered only after every
                    # owned descriptor is verified closed.
                elif isinstance(cleanup_errors[0], RunJournalStorageError):
                    raise cleanup_errors[0]
                elif isinstance(cleanup_errors[0], OSError):
                    raise RunJournalStorageError(
                        "journal cleanup failed"
                    ) from cleanup_errors[0]
                else:
                    raise cleanup_errors[0]

    @staticmethod
    def _write(
        session: _LockedJournal,
        basename: str,
        record: RunJournalV0,
        *,
        expected: os.stat_result | None,
    ) -> None:
        try:
            pending = _atomic_replace_record(
                session.directory_fd,
                session.lock,
                session.root,
                basename,
                canonical_run_journal_bytes_v0(record),
                expected=expected,
            )
            session.pending.append((pending, record))
        except RunJournalError:
            raise
        except OSError as exc:
            raise RunJournalStorageError("journal record write failed") from exc

    def start(
        self,
        *,
        run_kind: RunKindV0,
        expected_at: datetime,
        run_id: str,
        started_at: datetime,
        grace_seconds: int,
        stale_seconds: int,
    ) -> RunJournalV0:
        desired = create_run_journal_v0(
            run_kind=run_kind,
            expected_at=expected_at,
            run_id=run_id,
            status=RunJournalStatusV0.STARTED,
            started_at=started_at,
            terminal_at=None,
            grace_seconds=grace_seconds,
            stale_seconds=stale_seconds,
        )
        basename = _journal_basename(
            desired.run_kind, desired.expected_at, desired.run_id
        )
        desired_bytes = canonical_run_journal_bytes_v0(desired)
        with self._locked() as session:
            directory_fd = session.directory_fd
            try:
                current, current_bytes, _ = _read_record(directory_fd, basename)
            except FileNotFoundError:
                self._write(
                    session,
                    basename,
                    desired,
                    expected=None,
                )
            else:
                if current_bytes == desired_bytes:
                    return current
                raise RunJournalConflictError(
                    "run identity already has different state"
                )
        return desired

    def finish(
        self,
        started: object,
        *,
        status: RunJournalStatusV0,
        terminal_at: datetime,
        issue_codes: Iterable[str] = (),
        report_file: str | None = None,
    ) -> RunJournalV0:
        original = _require_record(started)
        if original.status is not RunJournalStatusV0.STARTED:
            raise RunJournalConflictError("only STARTED can reach a terminal state")
        if status.value not in _NORMAL_TERMINAL:
            raise RunJournalConflictError("requested transition is not terminal")
        desired = create_run_journal_v0(
            run_kind=original.run_kind,
            expected_at=original.expected_at,
            run_id=original.run_id,
            status=status,
            started_at=original.started_at,
            terminal_at=terminal_at,
            grace_seconds=original.grace_seconds,
            stale_seconds=original.stale_seconds,
            issue_codes=issue_codes,
            report_file=report_file,
        )
        basename = _journal_basename(
            original.run_kind, original.expected_at, original.run_id
        )
        original_bytes = canonical_run_journal_bytes_v0(original)
        desired_bytes = canonical_run_journal_bytes_v0(desired)
        with self._locked() as session:
            directory_fd = session.directory_fd
            try:
                current, current_bytes, current_info = _read_record(
                    directory_fd, basename
                )
            except FileNotFoundError:
                raise RunJournalConflictError("STARTED record is missing") from None
            if current_bytes == desired_bytes:
                return current
            if current_bytes != original_bytes:
                raise RunJournalConflictError("journal compare-and-set conflict")
            self._write(
                session,
                basename,
                desired,
                expected=current_info,
            )
        return desired

    def claim(
        self,
        *,
        run_kind: RunKindV0,
        expected_at: datetime,
        run_id: str,
        observed_at: datetime,
        grace_seconds: int,
        stale_seconds: int,
    ) -> tuple[RunJournalV0, bool]:
        observed = _require_utc(observed_at, "observed_at")
        expected = _require_utc(expected_at, "expected_at")
        grace = _require_policy_seconds(grace_seconds, "grace_seconds", minimum=0)
        stale = _require_policy_seconds(stale_seconds, "stale_seconds", minimum=1)
        missed = (observed - expected).total_seconds() >= grace
        desired = create_run_journal_v0(
            run_kind=run_kind,
            expected_at=expected,
            run_id=run_id,
            status=(
                RunJournalStatusV0.MISSED_EXPECTED
                if missed
                else RunJournalStatusV0.STARTED
            ),
            started_at=None if missed else observed,
            terminal_at=observed if missed else None,
            grace_seconds=grace,
            stale_seconds=stale,
            issue_codes=((RunJournalStatusV0.MISSED_EXPECTED.value,) if missed else ()),
        )
        basename = _journal_basename(
            desired.run_kind, desired.expected_at, desired.run_id
        )
        with self._locked() as session:
            directory_fd = session.directory_fd
            try:
                current, _, _ = _read_record(directory_fd, basename)
            except FileNotFoundError:
                self._write(
                    session,
                    basename,
                    desired,
                    expected=None,
                )
            else:
                if current.grace_seconds != grace or current.stale_seconds != stale:
                    raise RunJournalConflictError(
                        "journal schedule policy does not match durable provenance"
                    )
                return current, False
        return desired, desired.status is RunJournalStatusV0.STARTED

    @staticmethod
    def _read_all_locked(
        directory_fd: int,
    ) -> list[tuple[RunJournalV0, os.stat_result]]:
        records: list[tuple[RunJournalV0, os.stat_result]] = []
        try:
            names = os.listdir(directory_fd)
        except OSError as exc:
            raise RunJournalStorageError(
                "journal directory could not be listed"
            ) from exc
        for name in names:
            if type(name) is not str or not name.endswith(".json"):
                continue
            record, _, record_info = _read_record(directory_fd, name)
            expected_name = _journal_basename(
                record.run_kind, record.expected_at, record.run_id
            )
            if name != expected_name:
                raise RunJournalStorageError("journal record name is not canonical")
            records.append((record, record_info))
        records.sort(
            key=lambda item: (
                item[0].expected_at,
                item[0].run_kind.value,
                item[0].run_id,
            ),
            reverse=True,
        )
        return records

    @staticmethod
    def _require_limit(limit: object) -> int:
        if type(limit) is not int or limit < 1 or limit > 1000:
            raise ValueError("journal limit must be between 1 and 1000")
        return limit

    def status(
        self,
        *,
        limit: int,
        statuses: Iterable[RunJournalStatusV0] | None = None,
    ) -> tuple[RunJournalV0, ...]:
        bounded = self._require_limit(limit)
        allowed = None if statuses is None else tuple(statuses)
        if allowed is not None and any(
            type(status) is not RunJournalStatusV0 for status in allowed
        ):
            raise TypeError("status filter requires exact journal statuses")
        with self._locked() as session:
            directory_fd = session.directory_fd
            records = [record for record, _ in self._read_all_locked(directory_fd)]
        if allowed is not None:
            records = [record for record in records if record.status in allowed]
        return tuple(records[:bounded])

    def reconcile(
        self,
        *,
        expected: Iterable[ExpectedRunV0],
        now: datetime,
        grace_seconds: int,
        stale_seconds: int,
        limit: int,
    ) -> tuple[RunJournalV0, ...]:
        observed_at = _require_utc(now, "now")
        bounded = self._require_limit(limit)
        if type(grace_seconds) is not int or grace_seconds < 0:
            raise ValueError("grace_seconds must be a nonnegative integer")
        if type(stale_seconds) is not int or stale_seconds < 1:
            raise ValueError("stale_seconds must be a positive integer")
        slots = tuple(_require_expected_run(slot) for slot in expected)
        identities = {(slot.run_kind, slot.expected_at, slot.run_id) for slot in slots}
        if len(identities) != len(slots):
            raise ValueError("expected slots must be unique")

        with self._locked() as session:
            directory_fd = session.directory_fd
            current = self._read_all_locked(directory_fd)
            by_identity = {
                (record.run_kind, record.expected_at, record.run_id): (
                    record,
                    record_info,
                )
                for record, record_info in current
            }
            for record, record_info in current:
                identity = (record.run_kind, record.expected_at, record.run_id)
                if identity in identities and (
                    record.grace_seconds != grace_seconds
                    or record.stale_seconds != stale_seconds
                ):
                    raise RunJournalConflictError(
                        "journal schedule policy does not match durable provenance"
                    )
                if (
                    identity in identities
                    and record.status is RunJournalStatusV0.STARTED
                    and record.started_at is not None
                    and (observed_at - record.started_at).total_seconds()
                    >= record.stale_seconds
                ):
                    stale = create_run_journal_v0(
                        run_kind=record.run_kind,
                        expected_at=record.expected_at,
                        run_id=record.run_id,
                        status=RunJournalStatusV0.STALE_INCOMPLETE,
                        started_at=record.started_at,
                        terminal_at=observed_at,
                        grace_seconds=record.grace_seconds,
                        stale_seconds=record.stale_seconds,
                        issue_codes=(RunJournalStatusV0.STALE_INCOMPLETE.value,),
                    )
                    basename = _journal_basename(*identity)
                    self._write(
                        session,
                        basename,
                        stale,
                        expected=record_info,
                    )
                    _, _, stale_info = _read_record(directory_fd, basename)
                    by_identity[identity] = stale, stale_info
            for slot in slots:
                identity = (slot.run_kind, slot.expected_at, slot.run_id)
                if identity in by_identity:
                    continue
                if (observed_at - slot.expected_at).total_seconds() < grace_seconds:
                    continue
                missed = create_run_journal_v0(
                    run_kind=slot.run_kind,
                    expected_at=slot.expected_at,
                    run_id=slot.run_id,
                    status=RunJournalStatusV0.MISSED_EXPECTED,
                    started_at=None,
                    terminal_at=observed_at,
                    grace_seconds=grace_seconds,
                    stale_seconds=stale_seconds,
                    issue_codes=(RunJournalStatusV0.MISSED_EXPECTED.value,),
                )
                basename = _journal_basename(*identity)
                self._write(
                    session,
                    basename,
                    missed,
                    expected=None,
                )
                _, _, missed_info = _read_record(directory_fd, basename)
                by_identity[identity] = missed, missed_info
            records = sorted(
                (
                    by_identity[identity][0]
                    for identity in identities
                    if identity in by_identity
                ),
                key=lambda record: (
                    record.expected_at,
                    record.run_kind.value,
                    record.run_id,
                ),
                reverse=True,
            )
        return tuple(records[:bounded])


def journal_decision_run_v0(
    *,
    store: RunJournalStoreV0,
    run_kind: RunKindV0,
    expected_at: datetime,
    run_id: str,
    started_at: datetime,
    grace_seconds: int,
    stale_seconds: int,
    terminal_at: Callable[[], datetime],
    run_once: Callable[[], DecisionRunResultV0],
) -> tuple[RunJournalV0, DecisionRunResultV0]:
    if type(store) is not RunJournalStoreV0:
        raise TypeError("store must be an exact RunJournalStoreV0")
    started = store.start(
        run_kind=run_kind,
        expected_at=expected_at,
        run_id=run_id,
        started_at=started_at,
        grace_seconds=grace_seconds,
        stale_seconds=stale_seconds,
    )
    result = run_once()
    public = serialize_decision_run_result_v0(result)
    status = RunJournalStatusV0(public["status"])  # type: ignore[arg-type]
    issue_codes: tuple[str, ...] = ()
    if public.get("issue_code") is not None:
        issue_codes = (str(public["issue_code"]),)
    elif public.get("upload_issue") is not None:
        issue_codes = (str(public["upload_issue"]),)
    report_file = public.get("report_file")
    if report_file is not None and type(report_file) is not str:
        raise TypeError("runner report_file is invalid")
    trusted_report_file: str | None = report_file
    terminal = store.finish(
        started,
        status=status,
        terminal_at=terminal_at(),
        issue_codes=issue_codes,
        report_file=trusted_report_file,
    )
    return terminal, result


__all__ = [
    "ExpectedRunV0",
    "RunJournalCommittedCleanupError",
    "RunJournalConflictError",
    "RunJournalError",
    "RunJournalIssueV0",
    "RunJournalStatusV0",
    "RunJournalStorageError",
    "RunJournalStoreV0",
    "RunJournalV0",
    "canonical_run_journal_bytes_v0",
    "create_run_journal_v0",
    "journal_decision_run_v0",
    "parse_run_journal_v0",
    "serialize_run_journal_v0",
]
