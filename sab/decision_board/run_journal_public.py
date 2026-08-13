"""Stdlib-only, descriptor-relative public reader for RunJournalV0."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import stat
import sys
from collections.abc import Iterable
from contextlib import suppress
from datetime import datetime
from pathlib import Path
from typing import Any

_NAME = re.compile(
    r"^(entry|holding)-(\d{8}T\d{6}Z)-([A-Za-z0-9][A-Za-z0-9_-]{0,127})-([0-9a-f]{16})\.json\Z"
)
_RUN_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9_-]{0,127}\Z")
_REPORT_FILE = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,255}\Z")
_FIELDS = {
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
_WARNINGS = {"MISSED_EXPECTED", "STALE_INCOMPLETE"}
_STATUSES = _WARNINGS | {"STARTED", "PUBLISHED", "BLOCKED", "FAILED"}
_DECISION_ISSUES = {
    "COMPILER_CONTRACT_INVALID",
    "CONFIG_UNAVAILABLE",
    "IDEMPOTENCY_CONFLICT",
    "INTERNAL_ERROR",
    "ITEM_ENRICHMENT_INVALID",
    "LOCAL_PERSISTENCE_FAILED",
    "PREPARATION_INVALID",
    "SHARED_PREFLIGHT_UNAVAILABLE",
    "UPLOAD_FAILED",
}
_ISSUE_CODES = _WARNINGS | _DECISION_ISSUES
_MESSAGES = {
    "MISSED_EXPECTED": "Expected run did not start before its grace deadline.",
    "STALE_INCOMPLETE": "Started run did not reach a terminal state before its TTL.",
}
_DEFAULT_MAX_RECORD_BYTES = 64 * 1024


class PublicJournalReadError(RuntimeError):
    """A sanitized public journal read failure."""


def _bound(value: object, name: str, maximum: int) -> int:
    if type(value) is not int or value < 1 or value > maximum:
        raise PublicJournalReadError(f"{name} is invalid")
    return value


def _no_duplicates(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    value: dict[str, Any] = {}
    for key, item in pairs:
        if key in value:
            raise ValueError("duplicate key")
        value[key] = item
    return value


def _timestamp(value: object) -> str:
    if type(value) is not str or not value.endswith("Z"):
        raise ValueError("timestamp")
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.isoformat().replace("+00:00", "Z") != value:
        raise ValueError("timestamp")
    return value


def _canonical_record(value: object, name: str) -> dict[str, Any]:
    if type(value) is not dict or set(value) != _FIELDS:
        raise ValueError("fields")
    record = value
    run_id = record["run_id"]
    run_kind = record["run_kind"]
    status_value = record["status"]
    if (
        record["schema_version"] != "decision-board.v0"
        or type(record["schema_version"]) is not str
        or type(run_id) is not str
        or _RUN_ID.fullmatch(run_id) is None
        or run_kind not in {"ENTRY", "HOLDING"}
        or status_value not in _STATUSES
    ):
        raise ValueError("identity")
    expected_at = _timestamp(record["expected_at"])
    for key in ("started_at", "terminal_at"):
        if record[key] is not None:
            _timestamp(record[key])
    if (
        type(record["grace_seconds"]) is not int
        or not 0 <= record["grace_seconds"] <= 604800
        or type(record["stale_seconds"]) is not int
        or not 1 <= record["stale_seconds"] <= 604800
        or type(record["issues"]) is not list
    ):
        raise ValueError("policy")
    report_file = record["report_file"]
    if report_file is not None and (
        type(report_file) is not str
        or _REPORT_FILE.fullmatch(report_file) is None
        or Path(report_file).name != report_file
    ):
        raise ValueError("report file")
    for issue in record["issues"]:
        if type(issue) is not dict or set(issue) != {"code", "message"}:
            raise ValueError("issue")
        code = issue["code"]
        message = issue["message"]
        expected_message = _MESSAGES.get(
            code, f"Run reported sanitized issue code {code}."
        )
        if (
            type(code) is not str
            or code not in _ISSUE_CODES
            or re.fullmatch(r"[A-Z][A-Z0-9_]{0,127}", code) is None
            or message != expected_message
        ):
            raise ValueError("issue")
    stamp = expected_at[:19].replace("-", "").replace(":", "") + "Z"
    identity = f"{run_kind}\0{expected_at}\0{run_id}".encode("ascii")
    expected_name = (
        f"{str(run_kind).lower()}-{stamp}-{run_id}-"
        f"{hashlib.sha256(identity).hexdigest()[:16]}.json"
    )
    if name != expected_name or _NAME.fullmatch(name) is None:
        raise ValueError("name")
    return record


def _read_record(directory_fd: int, name: str, max_bytes: int) -> dict[str, Any]:
    flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0)
    fd = os.open(name, flags, dir_fd=directory_fd)
    try:
        before = os.fstat(fd)
        if (
            not stat.S_ISREG(before.st_mode)
            or before.st_nlink != 1
            or before.st_uid != os.geteuid()
            or stat.S_IMODE(before.st_mode) != 0o600
            or before.st_size < 2
            or before.st_size > max_bytes
        ):
            raise PublicJournalReadError("journal record is unsafe")
        remaining = before.st_size + 1
        chunks: list[bytes] = []
        while remaining:
            chunk = os.read(fd, min(remaining, 64 * 1024))
            if not chunk:
                break
            chunks.append(chunk)
            remaining -= len(chunk)
        payload = b"".join(chunks)
        after = os.fstat(fd)
        current = os.stat(name, dir_fd=directory_fd, follow_symlinks=False)
        identity = (before.st_dev, before.st_ino, before.st_size, before.st_mtime_ns)
        if (
            len(payload) != before.st_size
            or identity
            != (after.st_dev, after.st_ino, after.st_size, after.st_mtime_ns)
            or (current.st_dev, current.st_ino) != (before.st_dev, before.st_ino)
        ):
            raise PublicJournalReadError("journal record changed")
        text = payload.decode("utf-8", errors="strict")
        value = json.loads(
            text,
            object_pairs_hook=_no_duplicates,
            parse_constant=lambda _value: (_ for _ in ()).throw(ValueError("constant")),
        )
        record = _canonical_record(value, name)
        canonical = (
            json.dumps(
                record,
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
                allow_nan=False,
            ).encode("utf-8")
            + b"\n"
        )
        if canonical != payload:
            raise PublicJournalReadError("journal record is noncanonical")
        return record
    except PublicJournalReadError:
        raise
    except (OSError, UnicodeError, ValueError, TypeError) as exc:
        raise PublicJournalReadError("journal record is invalid") from exc
    finally:
        os.close(fd)


def _open_root(path: str) -> tuple[int, list[tuple[int, str, tuple[int, int]]]]:
    absolute = os.path.abspath(path)
    if absolute == os.path.sep:
        raise PublicJournalReadError("journal root is invalid")
    anchor = os.open(
        os.path.sep,
        os.O_RDONLY | getattr(os, "O_DIRECTORY", 0) | getattr(os, "O_NOFOLLOW", 0),
    )
    nodes: list[tuple[int, str, tuple[int, int]]] = []
    parent = anchor
    try:
        for component in Path(absolute).parts[1:]:
            fd = os.open(
                component,
                os.O_RDONLY
                | getattr(os, "O_DIRECTORY", 0)
                | getattr(os, "O_NOFOLLOW", 0),
                dir_fd=parent,
            )
            info = os.fstat(fd)
            if not stat.S_ISDIR(info.st_mode):
                os.close(fd)
                raise PublicJournalReadError("journal root is invalid")
            nodes.append((fd, component, (info.st_dev, info.st_ino)))
            parent = fd
        final = os.fstat(parent)
        if final.st_uid != os.geteuid() or stat.S_IMODE(final.st_mode) != 0o700:
            raise PublicJournalReadError("journal root is not private")
        return anchor, nodes
    except BaseException:
        for fd, _name, _identity in reversed(nodes):
            with suppress(OSError):
                os.close(fd)
        with suppress(OSError):
            os.close(anchor)
        raise


def _assert_path(anchor: int, nodes: list[tuple[int, str, tuple[int, int]]]) -> None:
    parent = anchor
    for fd, name, identity in nodes:
        current = os.stat(name, dir_fd=parent, follow_symlinks=False)
        opened = os.fstat(fd)
        if (
            not stat.S_ISDIR(current.st_mode)
            or (current.st_dev, current.st_ino) != identity
            or (opened.st_dev, opened.st_ino) != identity
        ):
            raise PublicJournalReadError("journal root changed")
        parent = fd


def read_public_journal_status_v0(
    root: str,
    *,
    limit: int,
    statuses: Iterable[str] = _WARNINGS,
    scan_limit: int = 200,
    max_record_bytes: int = _DEFAULT_MAX_RECORD_BYTES,
    max_output_bytes: int = 256 * 1024,
) -> dict[str, object]:
    """Read a bounded sanitized status envelope without mutating the journal."""

    bounded_limit = _bound(limit, "limit", 1000)
    bounded_scan = _bound(scan_limit, "scan limit", 1000)
    bounded_record = _bound(max_record_bytes, "record bytes", 1024 * 1024)
    bounded_output = _bound(max_output_bytes, "output bytes", 1024 * 1024)
    allowed = frozenset(statuses)
    if not allowed or not allowed <= _STATUSES:
        raise PublicJournalReadError("status filter is invalid")
    anchor, nodes = _open_root(root)
    directory_fd = nodes[-1][0]
    try:
        records: list[dict[str, Any]] = []
        with os.scandir(directory_fd) as entries:
            for index, entry in enumerate(entries, start=1):
                if index > bounded_scan:
                    raise PublicJournalReadError("journal scan bound exceeded")
                if not entry.name.endswith(".json"):
                    continue
                _assert_path(anchor, nodes)
                records.append(_read_record(directory_fd, entry.name, bounded_record))
        _assert_path(anchor, nodes)
        selected = sorted(
            (record for record in records if record["status"] in allowed),
            key=lambda record: (
                record["expected_at"],
                record["run_kind"],
                record["run_id"],
            ),
            reverse=True,
        )[:bounded_limit]
        envelope: dict[str, object] = {"count": len(selected), "records": selected}
        if len(_output_bytes(envelope)) > bounded_output:
            raise PublicJournalReadError("journal output bound exceeded")
        return envelope
    except PublicJournalReadError:
        raise
    except (OSError, ValueError, TypeError) as exc:
        raise PublicJournalReadError("journal could not be read safely") from exc
    finally:
        for fd, _name, _identity in reversed(nodes):
            with suppress(OSError):
                os.close(fd)
        with suppress(OSError):
            os.close(anchor)


def _output_bytes(value: object) -> bytes:
    return (
        json.dumps(value, sort_keys=True, separators=(",", ":")).encode("utf-8") + b"\n"
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(add_help=False)
    parser.add_argument("--journal-dir", required=True)
    parser.add_argument("--limit", type=int, required=True)
    parser.add_argument("--scan-limit", type=int, required=True)
    parser.add_argument("--max-record-bytes", type=int, required=True)
    parser.add_argument("--max-output-bytes", type=int, required=True)
    parser.add_argument("--status", action="append", required=True)
    try:
        ns = parser.parse_args(argv)
        envelope = read_public_journal_status_v0(
            ns.journal_dir,
            limit=ns.limit,
            statuses=ns.status,
            scan_limit=ns.scan_limit,
            max_record_bytes=ns.max_record_bytes,
            max_output_bytes=ns.max_output_bytes,
        )
        sys.stdout.buffer.write(_output_bytes(envelope))
        return 0
    except OSError, PublicJournalReadError, TypeError, ValueError:
        return 2


if __name__ == "__main__":
    raise SystemExit(main())


__all__ = ["PublicJournalReadError", "main", "read_public_journal_status_v0"]
