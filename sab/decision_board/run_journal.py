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

import fcntl
import hashlib
import json
import os
import re
import secrets
import stat
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
        "issues",
        "report_file",
    }
)


class RunJournalError(RuntimeError):
    """Base sanitized RunJournal failure."""


class RunJournalConflictError(RunJournalError):
    """The durable identity already contains a different state."""


class RunJournalStorageError(RunJournalError):
    """The local journal could not be read or written safely."""


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


@dataclass(frozen=True, slots=True, init=False)
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
    issues: tuple[RunJournalIssueV0, ...],
    report_file: str | None,
) -> None:
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
    issues = _make_issues(issue_codes)
    basename = _require_report_file(report_file)
    _validate_state(
        status=status,
        expected_at=expected,
        started_at=started,
        terminal_at=terminal,
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


def _atomic_write_bytes(path: str, payload: bytes) -> None:
    target = Path(path)
    directory_fd = os.open(target.parent, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0))
    temp_name = f".{target.name}.{secrets.token_hex(12)}.tmp"
    temp_fd = -1
    try:
        temp_fd = os.open(
            temp_name,
            os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0),
            0o600,
            dir_fd=directory_fd,
        )
        view = memoryview(payload)
        while view:
            written = os.write(temp_fd, view)
            view = view[written:]
        os.fsync(temp_fd)
        os.close(temp_fd)
        temp_fd = -1
        os.replace(
            temp_name, target.name, src_dir_fd=directory_fd, dst_dir_fd=directory_fd
        )
        os.fsync(directory_fd)
        temp_name = ""
    finally:
        if temp_fd >= 0:
            os.close(temp_fd)
        if temp_name:
            with suppress(FileNotFoundError):
                os.unlink(temp_name, dir_fd=directory_fd)
        os.close(directory_fd)


class RunJournalStoreV0:
    def __init__(self, root: str | Path) -> None:
        if type(root) is str:
            path = Path(root)
        elif isinstance(root, Path):
            path = root
        else:
            raise TypeError("journal root must be a path string or exact Path")
        self._root = path

    def _ensure_root(self) -> None:
        try:
            self._root.mkdir(mode=0o700, parents=True, exist_ok=True)
            info = self._root.lstat()
            if not stat.S_ISDIR(info.st_mode) or self._root.is_symlink():
                raise RunJournalStorageError("journal root is not a safe directory")
        except RunJournalStorageError:
            raise
        except OSError as exc:
            raise RunJournalStorageError("journal root is unavailable") from exc

    @contextmanager
    def _locked(self) -> Iterator[None]:
        self._ensure_root()
        lock_path = self._root / ".run-journal-v0.lock"
        flags = os.O_RDWR | os.O_CREAT | getattr(os, "O_NOFOLLOW", 0)
        try:
            fd = os.open(lock_path, flags, 0o600)
            info = os.fstat(fd)
            if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1:
                raise RunJournalStorageError("journal lock is not a private file")
            fcntl.flock(fd, fcntl.LOCK_EX)
        except RunJournalStorageError:
            if "fd" in locals():
                os.close(fd)
            raise
        except OSError as exc:
            if "fd" in locals():
                os.close(fd)
            raise RunJournalStorageError("journal lock is unavailable") from exc
        try:
            yield
        finally:
            try:
                fcntl.flock(fd, fcntl.LOCK_UN)
            finally:
                os.close(fd)

    def _path(self, record: RunJournalV0 | ExpectedRunV0) -> Path:
        return self._root / _journal_basename(
            record.run_kind, record.expected_at, record.run_id
        )

    def _read_path(self, path: Path) -> tuple[RunJournalV0, bytes]:
        try:
            if path.is_symlink():
                raise RunJournalStorageError("journal record is not a regular file")
            payload = path.read_bytes()
            raw = json.loads(payload)
            record = parse_run_journal_v0(raw)
            canonical = canonical_run_journal_bytes_v0(record)
            if payload != canonical:
                raise RunJournalStorageError("journal record bytes are not canonical")
            return record, canonical
        except RunJournalStorageError:
            raise
        except (
            OSError,
            UnicodeError,
            json.JSONDecodeError,
            TypeError,
            ValueError,
        ) as exc:
            raise RunJournalStorageError("journal record is invalid") from exc

    def _write(self, path: Path, record: RunJournalV0) -> None:
        try:
            _atomic_write_bytes(str(path), canonical_run_journal_bytes_v0(record))
        except OSError as exc:
            raise RunJournalStorageError("journal record write failed") from exc

    def start(
        self,
        *,
        run_kind: RunKindV0,
        expected_at: datetime,
        run_id: str,
        started_at: datetime,
    ) -> RunJournalV0:
        desired = create_run_journal_v0(
            run_kind=run_kind,
            expected_at=expected_at,
            run_id=run_id,
            status=RunJournalStatusV0.STARTED,
            started_at=started_at,
            terminal_at=None,
        )
        path = self._path(desired)
        desired_bytes = canonical_run_journal_bytes_v0(desired)
        with self._locked():
            if path.exists():
                current, current_bytes = self._read_path(path)
                if current_bytes == desired_bytes:
                    return current
                raise RunJournalConflictError(
                    "run identity already has different state"
                )
            self._write(path, desired)
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
            issue_codes=issue_codes,
            report_file=report_file,
        )
        path = self._path(original)
        original_bytes = canonical_run_journal_bytes_v0(original)
        desired_bytes = canonical_run_journal_bytes_v0(desired)
        with self._locked():
            if not path.exists():
                raise RunJournalConflictError("STARTED record is missing")
            current, current_bytes = self._read_path(path)
            if current_bytes == desired_bytes:
                return current
            if current_bytes != original_bytes:
                raise RunJournalConflictError("journal compare-and-set conflict")
            self._write(path, desired)
        return desired

    def _read_all_locked(self) -> list[RunJournalV0]:
        records = [self._read_path(path)[0] for path in self._root.glob("*.json")]
        records.sort(
            key=lambda record: (
                record.expected_at,
                record.run_kind.value,
                record.run_id,
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
        with self._locked():
            records = self._read_all_locked()
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
        slots = tuple(expected)
        if any(type(slot) is not ExpectedRunV0 for slot in slots):
            raise TypeError("expected slots require exact ExpectedRunV0 values")
        identities = {(slot.run_kind, slot.expected_at, slot.run_id) for slot in slots}
        if len(identities) != len(slots):
            raise ValueError("expected slots must be unique")

        with self._locked():
            current = self._read_all_locked()
            by_identity = {
                (record.run_kind, record.expected_at, record.run_id): record
                for record in current
            }
            for record in current:
                if (
                    record.status is RunJournalStatusV0.STARTED
                    and record.started_at is not None
                    and (observed_at - record.started_at).total_seconds()
                    >= stale_seconds
                ):
                    stale = create_run_journal_v0(
                        run_kind=record.run_kind,
                        expected_at=record.expected_at,
                        run_id=record.run_id,
                        status=RunJournalStatusV0.STALE_INCOMPLETE,
                        started_at=record.started_at,
                        terminal_at=observed_at,
                        issue_codes=(RunJournalStatusV0.STALE_INCOMPLETE.value,),
                    )
                    self._write(self._path(record), stale)
                    by_identity[
                        (record.run_kind, record.expected_at, record.run_id)
                    ] = stale
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
                    issue_codes=(RunJournalStatusV0.MISSED_EXPECTED.value,),
                )
                self._write(self._path(slot), missed)
                by_identity[identity] = missed
            records = sorted(
                by_identity.values(),
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
