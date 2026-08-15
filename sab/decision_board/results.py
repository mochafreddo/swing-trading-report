"""Factory-owned terminal results for Decision Board V0 runs."""

from __future__ import annotations

import json
import weakref
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path
from typing import Any, Literal, cast

from .contracts import canonical_json_bytes, validate_decision_board_report

DECISION_RUN_FAILED_EXIT_CODE = 2


class DecisionRunIssueCodeV0(StrEnum):
    COMPILER_CONTRACT_INVALID = "COMPILER_CONTRACT_INVALID"
    CONFIG_UNAVAILABLE = "CONFIG_UNAVAILABLE"
    IDEMPOTENCY_CONFLICT = "IDEMPOTENCY_CONFLICT"
    INTERNAL_ERROR = "INTERNAL_ERROR"
    ITEM_ENRICHMENT_INVALID = "ITEM_ENRICHMENT_INVALID"
    LOCAL_PERSISTENCE_FAILED = "LOCAL_PERSISTENCE_FAILED"
    PREPARATION_INVALID = "PREPARATION_INVALID"
    SHARED_PREFLIGHT_UNAVAILABLE = "SHARED_PREFLIGHT_UNAVAILABLE"
    UPLOAD_FAILED = "UPLOAD_FAILED"


@dataclass(frozen=True, slots=True, init=False, weakref_slot=True)
class DecisionRunPublishedV0:
    envelope: dict[str, Any]
    local_path: Path
    storage_key: str | None
    upload_issue: DecisionRunIssueCodeV0 | None
    status: Literal["PUBLISHED"]

    def __new__(cls) -> DecisionRunPublishedV0:
        del cls
        raise TypeError("published run results require the trusted factory")


@dataclass(frozen=True, slots=True, init=False, weakref_slot=True)
class DecisionRunBlockedV0:
    envelope: dict[str, Any]
    local_path: Path
    storage_key: str | None
    upload_issue: DecisionRunIssueCodeV0 | None
    status: Literal["BLOCKED"]

    def __new__(cls) -> DecisionRunBlockedV0:
        del cls
        raise TypeError("blocked run results require the trusted factory")


@dataclass(frozen=True, slots=True, init=False, weakref_slot=True)
class DecisionRunFailedV0:
    issue_code: DecisionRunIssueCodeV0
    local_path: Path | None
    status: Literal["FAILED"]

    def __new__(cls) -> DecisionRunFailedV0:
        del cls
        raise TypeError("failed run results require the trusted factory")


type DecisionRunResultV0 = (
    DecisionRunPublishedV0 | DecisionRunBlockedV0 | DecisionRunFailedV0
)
type _FailedSnapshot = tuple[DecisionRunIssueCodeV0, str | None, str, bytes | None]
type _StoredSnapshot = tuple[bytes, str, str | None, DecisionRunIssueCodeV0 | None, str]

_FAILED_RESULTS: dict[
    int, tuple[weakref.ReferenceType[DecisionRunFailedV0], _FailedSnapshot]
] = {}
_STORED_RESULTS: dict[
    int,
    tuple[
        weakref.ReferenceType[DecisionRunPublishedV0 | DecisionRunBlockedV0],
        _StoredSnapshot,
    ],
] = {}


def create_decision_run_published_v0(
    *,
    envelope: object,
    local_path: str | Path,
    storage_key: str | None = None,
    upload_issue: DecisionRunIssueCodeV0 | None = None,
) -> DecisionRunPublishedV0:
    return _allocate_stored(
        DecisionRunPublishedV0,
        envelope=envelope,
        local_path=local_path,
        storage_key=storage_key,
        upload_issue=upload_issue,
        expected_status="PUBLISHED",
    )


def create_decision_run_blocked_v0(
    *,
    envelope: object,
    local_path: str | Path,
    storage_key: str | None = None,
    upload_issue: DecisionRunIssueCodeV0 | None = None,
) -> DecisionRunBlockedV0:
    return _allocate_stored(
        DecisionRunBlockedV0,
        envelope=envelope,
        local_path=local_path,
        storage_key=storage_key,
        upload_issue=upload_issue,
        expected_status="BLOCKED",
    )


def create_decision_run_failed_v0(
    *,
    issue_code: DecisionRunIssueCodeV0,
    local_path: str | Path | None = None,
    retained_envelope: object | None = None,
) -> DecisionRunFailedV0:
    if type(issue_code) is not DecisionRunIssueCodeV0:
        raise TypeError("issue_code must be an exact DecisionRunIssueCodeV0")
    retained_payload: bytes | None = None
    if issue_code is DecisionRunIssueCodeV0.UPLOAD_FAILED:
        if local_path is None or retained_envelope is None:
            raise ValueError("upload failure requires one retained stored envelope")
        retained_payload = canonical_json_bytes(retained_envelope)
        trusted_envelope = validate_decision_board_report(json.loads(retained_payload))
        retained_payload = canonical_json_bytes(trusted_envelope)
        trusted_path, _ = _validated_retained_identity(
            retained_payload,
            trusted_envelope,
            local_path,
        )
    else:
        if local_path is not None or retained_envelope is not None:
            raise ValueError("only upload failure may retain a local report")
        trusted_path = None
    value = object.__new__(DecisionRunFailedV0)
    object.__setattr__(value, "issue_code", issue_code)
    object.__setattr__(value, "local_path", trusted_path)
    object.__setattr__(value, "status", "FAILED")
    _register_failed(value, retained_payload)
    return value


def decision_run_exit_code_v0(value: object) -> int:
    if type(value) in {DecisionRunPublishedV0, DecisionRunBlockedV0}:
        _require_stored(value)
        return 0
    _require_failed(value)
    return DECISION_RUN_FAILED_EXIT_CODE


def serialize_decision_run_result_v0(value: object) -> dict[str, object]:
    if type(value) in {DecisionRunPublishedV0, DecisionRunBlockedV0}:
        stored = _require_stored(value)
        return {
            "status": stored.status,
            "exit_code": 0,
            "report_file": stored.local_path.name,
            "storage_key": stored.storage_key,
            "degraded": stored.upload_issue is not None,
            **(
                {"upload_issue": stored.upload_issue.value}
                if stored.upload_issue is not None
                else {}
            ),
        }
    failed = _require_failed(value)
    public: dict[str, object] = {
        "status": "FAILED",
        "exit_code": DECISION_RUN_FAILED_EXIT_CODE,
        "issue_code": failed.issue_code.value,
    }
    if failed.local_path is not None:
        public["report_file"] = failed.local_path.name
    return public


def _allocate_stored[T: (DecisionRunPublishedV0, DecisionRunBlockedV0)](
    result_type: type[T],
    *,
    envelope: object,
    local_path: str | Path,
    storage_key: str | None,
    upload_issue: DecisionRunIssueCodeV0 | None,
    expected_status: str,
) -> T:
    payload = canonical_json_bytes(envelope)
    trusted_envelope = validate_decision_board_report(json.loads(payload))
    payload = canonical_json_bytes(trusted_envelope)
    if trusted_envelope["status"] != expected_status:
        raise ValueError("terminal result status does not match its envelope")
    if type(storage_key) not in {str, type(None)}:
        raise TypeError("storage_key must be a string or None")
    if type(upload_issue) not in {DecisionRunIssueCodeV0, type(None)}:
        raise TypeError("upload_issue must be an exact issue code or None")
    if upload_issue not in {None, DecisionRunIssueCodeV0.UPLOAD_FAILED}:
        raise ValueError("stored terminal results accept only the safe upload issue")
    trusted_path, expected_key = _validated_retained_identity(
        payload,
        trusted_envelope,
        local_path,
    )
    if storage_key is not None and storage_key != expected_key:
        raise ValueError("storage_key does not match the exact T7 envelope identity")
    if storage_key is not None and upload_issue is not None:
        raise ValueError("upload success and upload failure are mutually exclusive")
    value = object.__new__(result_type)
    object.__setattr__(value, "envelope", trusted_envelope)
    object.__setattr__(value, "local_path", trusted_path)
    object.__setattr__(value, "storage_key", storage_key)
    object.__setattr__(value, "upload_issue", upload_issue)
    object.__setattr__(value, "status", expected_status)
    _register_stored(value)
    return value


def _stored_snapshot(
    value: DecisionRunPublishedV0 | DecisionRunBlockedV0,
) -> _StoredSnapshot | None:
    try:
        payload = canonical_json_bytes(value.envelope)
        local_path: object = value.local_path
        storage_key: object = value.storage_key
        upload_issue: object = value.upload_issue
        status: object = value.status
    except Exception:
        return None
    if not isinstance(local_path, Path) or type(storage_key) not in {str, type(None)}:
        return None
    if upload_issue is not None and type(upload_issue) is not DecisionRunIssueCodeV0:
        return None
    if type(status) is not str or status not in {"PUBLISHED", "BLOCKED"}:
        return None
    try:
        validated = validate_decision_board_report(json.loads(payload))
    except Exception:
        return None
    if validated["status"] != status:
        return None
    payload = canonical_json_bytes(validated)
    try:
        _, expected_key = _validated_retained_identity(
            payload,
            validated,
            local_path,
        )
    except Exception:
        return None
    if storage_key is not None and storage_key != expected_key:
        return None
    if storage_key is not None and upload_issue is not None:
        return None
    return payload, str(local_path), storage_key, upload_issue, status


def _validated_retained_identity(
    payload: bytes,
    envelope: dict[str, Any],
    local_path: str | Path,
) -> tuple[Path, str]:
    from sab.report.decision_board import (
        build_decision_board_storage_key,
        parse_decision_board_storage_key,
    )

    if type(local_path) is str:
        trusted_path = Path(local_path)
    elif isinstance(local_path, Path):
        trusted_path = local_path
    else:
        raise TypeError("local_path must be a path string or Path")
    expected_key = build_decision_board_storage_key(envelope)
    parsed = parse_decision_board_storage_key(expected_key, report=envelope)
    if parsed is None:
        raise ValueError("envelope has no exact T7 storage identity")
    if (
        trusted_path.name != parsed.basename
        or trusted_path.is_symlink()
        or not trusted_path.is_file()
        or trusted_path.read_bytes() != payload
    ):
        raise ValueError("local report does not match the exact T7 envelope identity")
    return trusted_path, expected_key


def _register_stored(
    value: DecisionRunPublishedV0 | DecisionRunBlockedV0,
) -> None:
    snapshot = _stored_snapshot(value)
    assert snapshot is not None
    value_id = id(value)

    def discard(
        reference: weakref.ReferenceType[DecisionRunPublishedV0 | DecisionRunBlockedV0],
    ) -> None:
        current = _STORED_RESULTS.get(value_id)
        if current is not None and current[0] is reference:
            _STORED_RESULTS.pop(value_id, None)

    reference = weakref.ref(value, discard)
    _STORED_RESULTS[value_id] = reference, snapshot


def _require_stored(
    value: object,
) -> DecisionRunPublishedV0 | DecisionRunBlockedV0:
    if type(value) not in {DecisionRunPublishedV0, DecisionRunBlockedV0}:
        raise TypeError("Decision Board result is not an issued exact variant")
    typed = cast(DecisionRunPublishedV0 | DecisionRunBlockedV0, value)
    record = _STORED_RESULTS.get(id(typed))
    snapshot = _stored_snapshot(typed)
    if record is None or record[0]() is not typed:
        raise TypeError("Decision Board result is not issued")
    if snapshot is None or snapshot != record[1]:
        raise TypeError("Decision Board result is not an unchanged issued value")
    return typed


def _failed_snapshot(
    value: DecisionRunFailedV0,
    retained_payload: bytes | None,
) -> _FailedSnapshot | None:
    try:
        issue_code: object = value.issue_code
        local_path: object = value.local_path
        status: object = value.status
    except Exception:
        return None
    if type(issue_code) is not DecisionRunIssueCodeV0:
        return None
    if local_path is not None and not isinstance(local_path, Path):
        return None
    if type(status) is not str or status != "FAILED":
        return None
    if retained_payload is None:
        if issue_code is DecisionRunIssueCodeV0.UPLOAD_FAILED or local_path is not None:
            return None
    else:
        if issue_code is not DecisionRunIssueCodeV0.UPLOAD_FAILED or local_path is None:
            return None
        try:
            envelope = validate_decision_board_report(json.loads(retained_payload))
            _validated_retained_identity(
                canonical_json_bytes(envelope),
                envelope,
                local_path,
            )
        except Exception:
            return None
    return (
        cast(DecisionRunIssueCodeV0, issue_code),
        None if local_path is None else str(local_path),
        cast(str, status),
        retained_payload,
    )


def _register_failed(
    value: DecisionRunFailedV0, retained_payload: bytes | None
) -> None:
    snapshot = _failed_snapshot(value, retained_payload)
    assert snapshot is not None
    value_id = id(value)

    def discard(reference: weakref.ReferenceType[DecisionRunFailedV0]) -> None:
        current = _FAILED_RESULTS.get(value_id)
        if current is not None and current[0] is reference:
            _FAILED_RESULTS.pop(value_id, None)

    reference = weakref.ref(value, discard)
    _FAILED_RESULTS[value_id] = reference, snapshot


def _require_failed(value: object) -> DecisionRunFailedV0:
    if type(value) is not DecisionRunFailedV0:
        raise TypeError("Decision Board result is not an issued exact variant")
    record = _FAILED_RESULTS.get(id(value))
    if record is None or record[0]() is not value:
        raise TypeError("Decision Board result is not issued")
    snapshot = _failed_snapshot(value, record[1][3])
    if snapshot is None or snapshot != record[1]:
        raise TypeError("Decision Board result is not an unchanged issued value")
    return value


__all__ = [
    "DECISION_RUN_FAILED_EXIT_CODE",
    "DecisionRunBlockedV0",
    "DecisionRunFailedV0",
    "DecisionRunIssueCodeV0",
    "DecisionRunPublishedV0",
    "DecisionRunResultV0",
    "create_decision_run_blocked_v0",
    "create_decision_run_failed_v0",
    "create_decision_run_published_v0",
    "decision_run_exit_code_v0",
    "serialize_decision_run_result_v0",
]
