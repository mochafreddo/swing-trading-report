"""Strict immutable gate manifest for Decision Board shadow evaluation."""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from datetime import UTC, date, datetime, time
from pathlib import Path
from typing import Literal

from sab.data.trading_sessions import is_trading_session

from .runner import RunKindV0

_MAX_MANIFEST_BYTES = 1_048_576
_VERSION_PATTERN = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,127}\Z")
_PRIVATE_VERSION_SEGMENTS = frozenset(
    {"account", "credential", "password", "private", "secret", "token"}
)
_ROOT_FIELDS = {
    "schema_version",
    "gate_version",
    "approval",
    "market",
    "calendar",
    "start_session",
    "end_session",
    "minimum_sessions",
    "sessions",
    "lanes",
    "policy_versions",
    "schedule_policy",
    "expected_slots",
    "allowed_diff_reasons",
    "approved_thresholds",
}
_POLICY_FIELDS = {"compiler", "researcher", "verifier", "instrument_registry"}
_SCHEDULE_FIELDS = {
    "timezone",
    "entry_expected_time",
    "holding_expected_time",
    "grace_seconds",
    "stale_seconds",
}
_SLOT_FIELDS = {"session", "run_kind", "expected_at", "run_id"}
_HARD_THRESHOLD_FIELDS = {
    "unexplained",
    "privacy_leaks",
    "order_or_notification_accesses",
    "payload_replay_mismatches",
    "uncovered_eligible_holdings",
    "hard_sell_regressions",
    "invalid_publications",
    "existing_pipeline_impacts",
}
_QUALITY_THRESHOLD_FIELDS = {
    "provider_failure_rate_max",
    "research_coverage_rate_min",
    "fresh_source_rate_min",
}
_DIFF_REASONS = (
    "EXPECTED_POLICY_CHANGE",
    "INPUT_GAP",
    "SOURCE_GAP",
    "BUG",
    "UNEXPLAINED",
)


class ShadowGateManifestError(ValueError):
    """One sanitized gate validation failure."""

    def __init__(
        self,
        message: str,
        *,
        code: Literal["MANIFEST_INVALID", "APPROVAL_REQUIRED"] = "MANIFEST_INVALID",
    ) -> None:
        super().__init__(message)
        self.code = code


@dataclass(frozen=True, slots=True)
class ShadowGateSlotV0:
    session: date
    run_kind: RunKindV0
    expected_at: datetime
    run_id: str


@dataclass(frozen=True, slots=True, init=False)
class ShadowGateManifestV0:
    gate_version: str
    approval_state: Literal["PENDING", "APPROVED"]
    market: str
    calendar: str
    start_session: date
    end_session: date
    sessions: tuple[date, ...]
    lanes: tuple[RunKindV0, ...]
    slots: tuple[ShadowGateSlotV0, ...]
    entry_expected_time: time
    holding_expected_time: time
    grace_seconds: int
    stale_seconds: int
    manifest_sha256: str

    def __new__(cls) -> ShadowGateManifestV0:
        del cls
        raise TypeError("shadow gate manifests require validation")

    def to_public_dict(self) -> dict[str, object]:
        return {
            "status": (
                "VALID_APPROVED"
                if self.approval_state == "APPROVED"
                else "VALID_PROPOSAL"
            ),
            "gate_version": self.gate_version,
            "approval_state": self.approval_state,
            "market": self.market,
            "calendar": self.calendar,
            "start_session": self.start_session.isoformat(),
            "end_session": self.end_session.isoformat(),
            "session_count": len(self.sessions),
            "slot_count": len(self.slots),
            "lanes": [lane.value for lane in self.lanes],
            "manifest_sha256": self.manifest_sha256,
        }


def load_shadow_gate_manifest_v0(
    path: str | Path,
    *,
    require_approved: bool = False,
) -> ShadowGateManifestV0:
    try:
        raw_bytes = Path(path).read_bytes()
        if len(raw_bytes) > _MAX_MANIFEST_BYTES:
            raise ShadowGateManifestError("manifest exceeds the safe bound")
        raw = json.loads(raw_bytes.decode("utf-8"))
    except ShadowGateManifestError:
        raise
    except OSError, UnicodeDecodeError, json.JSONDecodeError:
        raise ShadowGateManifestError(
            "manifest input is unavailable or invalid"
        ) from None
    return validate_shadow_gate_manifest_v0(raw, require_approved=require_approved)


def validate_shadow_gate_manifest_v0(
    raw: object,
    *,
    require_approved: bool = False,
) -> ShadowGateManifestV0:
    if type(raw) is not dict or set(raw) != _ROOT_FIELDS:
        raise ShadowGateManifestError("manifest root fields are invalid")
    if raw["schema_version"] != "decision-board-shadow-gate.v0":
        raise ShadowGateManifestError("manifest schema version is invalid")
    gate_version = _require_version(raw["gate_version"], "gate version")
    approval_state = _validate_approval(raw["approval"])
    if require_approved and approval_state != "APPROVED":
        raise ShadowGateManifestError(
            "manifest approval is required",
            code="APPROVAL_REQUIRED",
        )
    if raw["market"] != "US" or raw["calendar"] != "XNYS":
        raise ShadowGateManifestError("manifest market calendar is invalid")
    minimum_sessions = raw["minimum_sessions"]
    if type(minimum_sessions) is not int or minimum_sessions != 20:
        raise ShadowGateManifestError("manifest minimum sessions must be 20")
    sessions = _validate_sessions(raw["sessions"], minimum=minimum_sessions)
    start_session = _parse_date(raw["start_session"], "start session")
    end_session = _parse_date(raw["end_session"], "end session")
    if start_session != sessions[0] or end_session != sessions[-1]:
        raise ShadowGateManifestError("manifest session bounds are invalid")
    if raw["lanes"] != ["ENTRY", "HOLDING"]:
        raise ShadowGateManifestError("manifest lanes are invalid")
    _validate_policy_versions(raw["policy_versions"])
    schedule = _validate_schedule(raw["schedule_policy"])
    slots = _validate_slots(raw["expected_slots"], sessions=sessions, schedule=schedule)
    if raw["allowed_diff_reasons"] != list(_DIFF_REASONS):
        raise ShadowGateManifestError("manifest diff reasons are invalid")
    _validate_thresholds(raw["approved_thresholds"])
    digest = hashlib.sha256(
        json.dumps(
            raw,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    ).hexdigest()
    value = object.__new__(ShadowGateManifestV0)
    for field, field_value in (
        ("gate_version", gate_version),
        ("approval_state", approval_state),
        ("market", "US"),
        ("calendar", "XNYS"),
        ("start_session", start_session),
        ("end_session", end_session),
        ("sessions", sessions),
        ("lanes", (RunKindV0.ENTRY, RunKindV0.HOLDING)),
        ("slots", slots),
        ("entry_expected_time", schedule[0]),
        ("holding_expected_time", schedule[1]),
        ("grace_seconds", schedule[2]),
        ("stale_seconds", schedule[3]),
        ("manifest_sha256", f"sha256:{digest}"),
    ):
        object.__setattr__(value, field, field_value)
    return value


def _validate_approval(value: object) -> Literal["PENDING", "APPROVED"]:
    if type(value) is not dict or set(value) != {
        "state",
        "approved_by",
        "approved_at",
    }:
        raise ShadowGateManifestError("manifest approval fields are invalid")
    state = value["state"]
    approved_by = value["approved_by"]
    approved_at = value["approved_at"]
    if state == "PENDING" and approved_by is None and approved_at is None:
        return "PENDING"
    if state != "APPROVED":
        raise ShadowGateManifestError("manifest approval state is invalid")
    _require_version(approved_by, "approval identity")
    approved_at_value = _parse_utc_datetime(approved_at, "approval timestamp")
    if approved_at_value.microsecond != 0:
        raise ShadowGateManifestError("manifest approval timestamp is invalid")
    return "APPROVED"


def _validate_sessions(value: object, *, minimum: int) -> tuple[date, ...]:
    if type(value) is not list or len(value) < minimum:
        raise ShadowGateManifestError("manifest sessions are invalid")
    sessions = tuple(_parse_date(item, "trading session") for item in value)
    if sessions != tuple(sorted(set(sessions))):
        raise ShadowGateManifestError(
            "manifest trading sessions are not unique and ordered"
        )
    for session in sessions:
        if not is_trading_session(session, market="US"):
            raise ShadowGateManifestError("manifest trading session is closed")
    return sessions


def _validate_policy_versions(value: object) -> None:
    if type(value) is not dict or set(value) != _POLICY_FIELDS:
        raise ShadowGateManifestError("manifest policy versions are invalid")
    for name in sorted(_POLICY_FIELDS):
        _require_version(value[name], f"{name} policy version")


def _validate_schedule(value: object) -> tuple[time, time, int, int]:
    if type(value) is not dict or set(value) != _SCHEDULE_FIELDS:
        raise ShadowGateManifestError("manifest schedule policy is invalid")
    if value["timezone"] != "UTC":
        raise ShadowGateManifestError("manifest schedule timezone is invalid")
    entry_time = _parse_utc_time(value["entry_expected_time"])
    holding_time = _parse_utc_time(value["holding_expected_time"])
    grace = value["grace_seconds"]
    stale = value["stale_seconds"]
    if (
        type(grace) is not int
        or not 1 <= grace <= 3600
        or type(stale) is not int
        or not 1 <= stale <= 86400
        or stale <= grace
    ):
        raise ShadowGateManifestError("manifest schedule bounds are invalid")
    return entry_time, holding_time, grace, stale


def _validate_slots(
    value: object,
    *,
    sessions: tuple[date, ...],
    schedule: tuple[time, time, int, int],
) -> tuple[ShadowGateSlotV0, ...]:
    if type(value) is not list or len(value) != len(sessions) * 2:
        raise ShadowGateManifestError("manifest expected slots are incomplete")
    entry_time, holding_time, _grace, _stale = schedule
    slots: list[ShadowGateSlotV0] = []
    identities: set[tuple[date, RunKindV0]] = set()
    for raw_slot in value:
        if type(raw_slot) is not dict or set(raw_slot) != _SLOT_FIELDS:
            raise ShadowGateManifestError("manifest expected slots are invalid")
        session = _parse_date(raw_slot["session"], "slot session")
        try:
            run_kind = RunKindV0(raw_slot["run_kind"])
        except TypeError, ValueError:
            raise ShadowGateManifestError("manifest slot lane is invalid") from None
        expected_at = _parse_utc_datetime(raw_slot["expected_at"], "slot expected time")
        run_id = raw_slot["run_id"]
        expected_time = entry_time if run_kind is RunKindV0.ENTRY else holding_time
        expected_run_id = f"{run_kind.value.lower()}-shadow-{session:%Y%m%d}"
        if (
            session not in sessions
            or expected_at.date() != session
            or expected_at.timetz().replace(tzinfo=None) != expected_time
            or run_id != expected_run_id
        ):
            raise ShadowGateManifestError("manifest slot identity is invalid")
        identity = (session, run_kind)
        if identity in identities:
            raise ShadowGateManifestError("manifest expected slots contain duplicates")
        identities.add(identity)
        slots.append(
            ShadowGateSlotV0(
                session=session,
                run_kind=run_kind,
                expected_at=expected_at,
                run_id=run_id,
            )
        )
    expected_identities = {
        (session, run_kind)
        for session in sessions
        for run_kind in (RunKindV0.ENTRY, RunKindV0.HOLDING)
    }
    if identities != expected_identities:
        raise ShadowGateManifestError("manifest expected slots are incomplete")
    return tuple(slots)


def _validate_thresholds(value: object) -> None:
    if type(value) is not dict or set(value) != {"hard_failures", "quality"}:
        raise ShadowGateManifestError("manifest approved thresholds are invalid")
    hard = value["hard_failures"]
    quality = value["quality"]
    if type(hard) is not dict or set(hard) != _HARD_THRESHOLD_FIELDS:
        raise ShadowGateManifestError("manifest hard thresholds are invalid")
    if any(type(item) is not int or item != 0 for item in hard.values()):
        raise ShadowGateManifestError("manifest hard thresholds must remain zero")
    if type(quality) is not dict or set(quality) != _QUALITY_THRESHOLD_FIELDS:
        raise ShadowGateManifestError("manifest quality thresholds are invalid")
    values = quality
    if any(
        type(values[name]) not in {int, float} or not 0 <= values[name] <= 1
        for name in _QUALITY_THRESHOLD_FIELDS
    ):
        raise ShadowGateManifestError("manifest quality thresholds are invalid")
    if (
        values["provider_failure_rate_max"] > 0.05
        or values["research_coverage_rate_min"] < 0.9
        or values["fresh_source_rate_min"] < 0.9
    ):
        raise ShadowGateManifestError("manifest quality thresholds are too weak")


def _require_version(value: object, label: str) -> str:
    if type(value) is not str or _VERSION_PATTERN.fullmatch(value) is None:
        raise ShadowGateManifestError(f"manifest {label} is invalid")
    segments = {segment.casefold() for segment in re.split(r"[._-]+", value)}
    if segments & _PRIVATE_VERSION_SEGMENTS:
        raise ShadowGateManifestError(f"manifest {label} is invalid")
    return value


def _parse_date(value: object, label: str) -> date:
    if type(value) is not str:
        raise ShadowGateManifestError(f"manifest {label} is invalid")
    try:
        parsed = date.fromisoformat(value)
    except ValueError:
        raise ShadowGateManifestError(f"manifest {label} is invalid") from None
    if parsed.isoformat() != value:
        raise ShadowGateManifestError(f"manifest {label} is invalid")
    return parsed


def _parse_utc_datetime(value: object, label: str) -> datetime:
    if type(value) is not str or not value.endswith("Z"):
        raise ShadowGateManifestError(f"manifest {label} is invalid")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        raise ShadowGateManifestError(f"manifest {label} is invalid") from None
    if parsed.tzinfo is None or parsed.utcoffset() != UTC.utcoffset(parsed):
        raise ShadowGateManifestError(f"manifest {label} is invalid")
    if parsed.isoformat().replace("+00:00", "Z") != value:
        raise ShadowGateManifestError(f"manifest {label} is invalid")
    return parsed


def _parse_utc_time(value: object) -> time:
    if type(value) is not str or not re.fullmatch(
        r"[0-2][0-9]:[0-5][0-9]:[0-5][0-9]Z", value
    ):
        raise ShadowGateManifestError("manifest schedule time is invalid")
    try:
        parsed = time.fromisoformat(value[:-1])
    except ValueError:
        raise ShadowGateManifestError("manifest schedule time is invalid") from None
    if parsed.microsecond != 0:
        raise ShadowGateManifestError("manifest schedule time is invalid")
    return parsed


__all__ = [
    "ShadowGateManifestError",
    "ShadowGateManifestV0",
    "ShadowGateSlotV0",
    "load_shadow_gate_manifest_v0",
    "validate_shadow_gate_manifest_v0",
]
