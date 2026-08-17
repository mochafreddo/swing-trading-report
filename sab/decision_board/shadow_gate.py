"""Strict immutable gate manifest for Decision Board shadow evaluation."""

from __future__ import annotations

import hashlib
import json
import re
import stat
import subprocess
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
    "horizon",
    "approval",
    "market",
    "calendar",
    "start_session",
    "end_session",
    "minimum_sessions",
    "sessions",
    "lanes",
    "policy_versions",
    "runtime_contract",
    "evaluation_ledger",
    "schedule_policy",
    "expected_slots",
    "allowed_diff_reasons",
    "allowed_diff_reason_by_rule_id",
    "metric_definitions",
    "approved_thresholds",
}
_POLICY_FIELDS = {"compiler", "researcher", "verifier", "instrument_registry"}
_EXPECTED_POLICY_VERSIONS = {
    "compiler": "decision-policy.v0",
    "researcher": "evidence-researcher.v0",
    "verifier": "decision-board-claim-verifier-v0",
    "instrument_registry": "us-instrument-registry.v0",
}
_RUNTIME_FIELDS = {
    "code_revision",
    "artifact_digests",
    "source_provider_chain",
    "claim_model",
}
_ARTIFACT_FIELDS = frozenset(_POLICY_FIELDS)
_LEDGER_FIELDS = {
    "input_ledger_sha256",
    "expected_action_ledger_sha256",
    "case_count",
}
_EXPECTED_PROVIDER_CHAIN = ("finnhub", "polygon-news", "benzinga-news")
_EXPECTED_METRIC_DEFINITIONS = {
    "provider_failure_rate": {
        "numerator": "provider_failed_attempts",
        "denominator": "provider_attempts",
        "zero_denominator": "NOT_APPLICABLE",
    },
    "research_coverage_rate": {
        "numerator": "eligible_items_with_verified_evidence",
        "denominator": "eligible_items",
        "zero_denominator": "NOT_APPLICABLE",
    },
    "fresh_source_rate": {
        "numerator": "fresh_verified_sources",
        "denominator": "verified_sources",
        "zero_denominator": "NOT_APPLICABLE",
    },
}
_HASH_PATTERN = re.compile(r"sha256:[0-9a-f]{64}\Z")
_CODE_REVISION_PATTERN = re.compile(r"git:[0-9a-f]{40}\Z")
_ARTIFACT_PATHS = {
    "compiler": (
        "sab/decision_board/compiler.py",
        "sab/decision_board/contracts.py",
        "sab/decision_board/policy.py",
        "sab/decision_board/runner.py",
    ),
    "researcher": (
        "sab/decision_board/batch_evidence.py",
        "sab/research/contracts.py",
        "sab/research/live_adapters.py",
        "sab/research/orchestrator.py",
        "sab/research/source_safety.py",
    ),
    "verifier": (
        "sab/decision_board/claim_responses.py",
        "sab/decision_board/claims.py",
        "sab/decision_board/live_adapters.py",
    ),
    "instrument_registry": (
        "sab/decision_board/instruments.py",
        "sab/decision_board/supabase_request.py",
    ),
}
_MAX_ARTIFACT_BYTES = 2_097_152
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
    horizon: Literal["SWING"]
    approval_state: Literal["PENDING", "APPROVED"]
    approval_signature_sha256: str | None
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
    source_provider_chain: tuple[str, ...]
    claim_model: str
    code_revision: str | None
    artifact_digests: tuple[tuple[str, str | None], ...]
    input_ledger_sha256: str | None
    expected_action_ledger_sha256: str | None
    expected_action_case_count: int
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
    input_ledger_path: str | Path | None = None,
    expected_action_ledger_path: str | Path | None = None,
) -> ShadowGateManifestV0:
    try:
        raw_bytes = Path(path).read_bytes()
        if len(raw_bytes) > _MAX_MANIFEST_BYTES:
            raise ShadowGateManifestError("manifest exceeds the safe bound")
        raw = json.loads(
            raw_bytes.decode("utf-8"),
            object_pairs_hook=_unique_object,
            parse_constant=lambda _value: (_ for _ in ()).throw(
                ValueError("non-finite JSON is invalid")
            ),
        )
    except ShadowGateManifestError:
        raise
    except OSError, UnicodeDecodeError, json.JSONDecodeError, ValueError:
        raise ShadowGateManifestError(
            "manifest input is unavailable or invalid"
        ) from None
    manifest = validate_shadow_gate_manifest_v0(raw)
    if require_approved:
        if manifest.approval_state != "APPROVED":
            raise ShadowGateManifestError(
                "manifest approval is required",
                code="APPROVAL_REQUIRED",
            )
        if input_ledger_path is None or expected_action_ledger_path is None:
            raise ShadowGateManifestError(
                "approved manifest ledgers are required",
                code="APPROVAL_REQUIRED",
            )
        from .shadow_ledger import (
            ShadowEvaluationLedgerError,
            load_shadow_evaluation_ledgers_v0,
        )

        try:
            load_shadow_evaluation_ledgers_v0(
                manifest,
                input_ledger_path=input_ledger_path,
                expected_action_ledger_path=expected_action_ledger_path,
            )
        except ShadowEvaluationLedgerError:
            raise ShadowGateManifestError(
                "approved manifest ledgers are invalid",
                code="APPROVAL_REQUIRED",
            ) from None
    return manifest


def validate_shadow_gate_manifest_v0(
    raw: object,
    *,
    require_approved: bool = False,
    input_ledger: object = None,
    expected_action_ledger: object = None,
) -> ShadowGateManifestV0:
    if type(raw) is not dict or set(raw) != _ROOT_FIELDS:
        raise ShadowGateManifestError("manifest root fields are invalid")
    if raw["schema_version"] != "decision-board-shadow-gate.v0":
        raise ShadowGateManifestError("manifest schema version is invalid")
    gate_version = _require_version(raw["gate_version"], "gate version")
    approval_state, approved_at, approval_signature = _validate_approval(
        raw["approval"]
    )
    if require_approved and approval_state != "APPROVED":
        raise ShadowGateManifestError(
            "manifest approval is required",
            code="APPROVAL_REQUIRED",
        )
    if raw["market"] != "US" or raw["calendar"] != "XNYS":
        raise ShadowGateManifestError("manifest market calendar is invalid")
    if raw["horizon"] != "SWING":
        raise ShadowGateManifestError("manifest horizon is invalid")
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
    runtime = _validate_runtime_contract(raw["runtime_contract"])
    ledger = _validate_evaluation_ledger(raw["evaluation_ledger"])
    schedule = _validate_schedule(raw["schedule_policy"])
    slots = _validate_slots(raw["expected_slots"], sessions=sessions, schedule=schedule)
    if (
        approval_state == "APPROVED"
        and approved_at is not None
        and approved_at >= min(slot.expected_at for slot in slots)
    ):
        raise ShadowGateManifestError(
            "manifest approval must precede the evaluation window"
        )
    if raw["allowed_diff_reasons"] != list(_DIFF_REASONS):
        raise ShadowGateManifestError("manifest diff reasons are invalid")
    _validate_rule_diff_allowlist(raw["allowed_diff_reason_by_rule_id"])
    if raw["metric_definitions"] != _EXPECTED_METRIC_DEFINITIONS:
        raise ShadowGateManifestError("manifest metric definitions are invalid")
    _validate_thresholds(raw["approved_thresholds"])
    if approval_state == "APPROVED" and not _freeze_inputs_complete(runtime, ledger):
        raise ShadowGateManifestError("manifest approval freeze inputs are incomplete")
    if (
        approval_state == "APPROVED"
        and approval_signature != shadow_gate_approval_signature_v0(raw)
    ):
        raise ShadowGateManifestError("manifest approval signature does not match")
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
        ("horizon", "SWING"),
        ("approval_state", approval_state),
        ("approval_signature_sha256", approval_signature),
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
        ("source_provider_chain", runtime[2]),
        ("claim_model", runtime[3]),
        ("code_revision", runtime[0]),
        ("artifact_digests", runtime[1]),
        ("input_ledger_sha256", ledger[0]),
        ("expected_action_ledger_sha256", ledger[1]),
        ("expected_action_case_count", ledger[2]),
        ("manifest_sha256", f"sha256:{digest}"),
    ):
        object.__setattr__(value, field, field_value)
    if require_approved:
        if input_ledger is None or expected_action_ledger is None:
            raise ShadowGateManifestError(
                "approved manifest ledgers are required",
                code="APPROVAL_REQUIRED",
            )
        from .shadow_ledger import (
            ShadowEvaluationLedgerError,
            validate_shadow_evaluation_ledgers_v0,
        )

        try:
            validate_shadow_evaluation_ledgers_v0(
                value,
                input_ledger=input_ledger,
                expected_action_ledger=expected_action_ledger,
            )
        except ShadowEvaluationLedgerError:
            raise ShadowGateManifestError(
                "approved manifest ledgers are invalid",
                code="APPROVAL_REQUIRED",
            ) from None
    return value


def current_shadow_gate_runtime_contract_v0(
    repo_root: str | Path,
    *,
    claim_model: str,
) -> dict[str, object]:
    root = _runtime_root(repo_root)
    model = _require_version(claim_model, "claim model")
    return {
        "code_revision": _git_revision(root),
        "artifact_digests": _artifact_digests(root),
        "source_provider_chain": list(_EXPECTED_PROVIDER_CHAIN),
        "claim_model": model,
    }


def validate_shadow_gate_runtime_v0(
    manifest: ShadowGateManifestV0,
    *,
    repo_root: str | Path,
    claim_model: str,
) -> None:
    if type(manifest) is not ShadowGateManifestV0:
        raise TypeError("shadow gate runtime requires an exact manifest")
    root = _runtime_root(repo_root)
    _require_clean_git_worktree(root)
    model = _require_version(claim_model, "claim model")
    if manifest.code_revision != _git_revision(root):
        raise ShadowGateManifestError("manifest runtime code revision does not match")
    if dict(manifest.artifact_digests) != _artifact_digests(root):
        raise ShadowGateManifestError("manifest runtime artifacts do not match")
    if manifest.source_provider_chain != _EXPECTED_PROVIDER_CHAIN:
        raise ShadowGateManifestError("manifest runtime provider chain does not match")
    if manifest.claim_model != model:
        raise ShadowGateManifestError("manifest runtime claim model does not match")


def _runtime_root(value: str | Path) -> Path:
    try:
        root = Path(value).resolve(strict=True)
        identity = root.lstat()
    except OSError, TypeError:
        raise ShadowGateManifestError("manifest runtime root is invalid") from None
    if not stat.S_ISDIR(identity.st_mode) or root.is_symlink():
        raise ShadowGateManifestError("manifest runtime root is invalid")
    return root


def _git_revision(root: Path) -> str:
    try:
        completed = subprocess.run(
            ["git", "-C", str(root), "rev-parse", "--verify", "HEAD"],
            capture_output=True,
            text=True,
            check=False,
            timeout=5,
        )
    except OSError, subprocess.SubprocessError:
        raise ShadowGateManifestError(
            "manifest runtime revision is unavailable"
        ) from None
    revision = completed.stdout.strip()
    value = f"git:{revision}"
    if completed.returncode != 0 or _CODE_REVISION_PATTERN.fullmatch(value) is None:
        raise ShadowGateManifestError("manifest runtime revision is unavailable")
    return value


def _require_clean_git_worktree(root: Path) -> None:
    try:
        completed = subprocess.run(
            [
                "git",
                "-C",
                str(root),
                "status",
                "--porcelain=v1",
                "--untracked-files=all",
            ],
            capture_output=True,
            text=True,
            check=False,
            timeout=5,
        )
    except OSError, subprocess.SubprocessError:
        raise ShadowGateManifestError(
            "manifest runtime worktree is unavailable"
        ) from None
    if completed.returncode != 0 or completed.stdout:
        raise ShadowGateManifestError("manifest runtime worktree is not clean")


def _artifact_digests(root: Path) -> dict[str, str]:
    result: dict[str, str] = {}
    for name in sorted(_ARTIFACT_PATHS):
        digest = hashlib.sha256()
        for relative in _ARTIFACT_PATHS[name]:
            path = root / relative
            try:
                identity = path.lstat()
                if (
                    not stat.S_ISREG(identity.st_mode)
                    or path.is_symlink()
                    or identity.st_size > _MAX_ARTIFACT_BYTES
                ):
                    raise OSError
                content = path.read_bytes()
            except OSError:
                raise ShadowGateManifestError(
                    "manifest runtime artifact is unavailable"
                ) from None
            digest.update(relative.encode("utf-8"))
            digest.update(b"\0")
            digest.update(hashlib.sha256(content).digest())
        result[name] = f"sha256:{digest.hexdigest()}"
    return result


def _validate_approval(
    value: object,
) -> tuple[Literal["PENDING", "APPROVED"], datetime | None, str | None]:
    if type(value) is not dict or set(value) != {
        "state",
        "approved_by",
        "approved_at",
        "approval_signature_sha256",
    }:
        raise ShadowGateManifestError("manifest approval fields are invalid")
    state = value["state"]
    approved_by = value["approved_by"]
    approved_at = value["approved_at"]
    approval_signature = value["approval_signature_sha256"]
    if (
        state == "PENDING"
        and approved_by is None
        and approved_at is None
        and approval_signature is None
    ):
        return "PENDING", None, None
    if state != "APPROVED":
        raise ShadowGateManifestError("manifest approval state is invalid")
    if approved_by != "user":
        raise ShadowGateManifestError("manifest approval identity must be user")
    approved_at_value = _parse_utc_datetime(approved_at, "approval timestamp")
    if approved_at_value.microsecond != 0:
        raise ShadowGateManifestError("manifest approval timestamp is invalid")
    if (
        type(approval_signature) is not str
        or _HASH_PATTERN.fullmatch(approval_signature) is None
    ):
        raise ShadowGateManifestError("manifest approval signature is invalid")
    return "APPROVED", approved_at_value, approval_signature


def shadow_gate_approval_signature_v0(raw: object) -> str:
    """Hash the complete approved contract with only its signature slot cleared."""

    if type(raw) is not dict or type(raw.get("approval")) is not dict:
        raise ShadowGateManifestError("manifest approval signature input is invalid")
    approval = dict(raw["approval"])
    if set(approval) != {
        "state",
        "approved_by",
        "approved_at",
        "approval_signature_sha256",
    }:
        raise ShadowGateManifestError("manifest approval signature input is invalid")
    approval["approval_signature_sha256"] = None
    unsigned = dict(raw)
    unsigned["approval"] = approval
    digest = hashlib.sha256(
        json.dumps(
            unsigned,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    ).hexdigest()
    return f"sha256:{digest}"


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
    if value != _EXPECTED_POLICY_VERSIONS:
        raise ShadowGateManifestError("manifest policy versions do not match runtime")


def _validate_runtime_contract(
    value: object,
) -> tuple[
    str | None,
    tuple[tuple[str, str | None], ...],
    tuple[str, ...],
    str,
]:
    if type(value) is not dict or set(value) != _RUNTIME_FIELDS:
        raise ShadowGateManifestError("manifest runtime contract is invalid")
    revision = value["code_revision"]
    if revision is not None and (
        type(revision) is not str or _CODE_REVISION_PATTERN.fullmatch(revision) is None
    ):
        raise ShadowGateManifestError("manifest runtime contract is invalid")
    raw_digests = value["artifact_digests"]
    if type(raw_digests) is not dict or set(raw_digests) != _ARTIFACT_FIELDS:
        raise ShadowGateManifestError("manifest runtime contract is invalid")
    digests: list[tuple[str, str | None]] = []
    for name in sorted(_ARTIFACT_FIELDS):
        digest = raw_digests[name]
        if digest is not None and (
            type(digest) is not str or _HASH_PATTERN.fullmatch(digest) is None
        ):
            raise ShadowGateManifestError("manifest runtime contract is invalid")
        digests.append((name, digest))
    chain = value["source_provider_chain"]
    if chain != list(_EXPECTED_PROVIDER_CHAIN):
        raise ShadowGateManifestError("manifest runtime contract is invalid")
    model = _require_version(value["claim_model"], "claim model")
    return revision, tuple(digests), _EXPECTED_PROVIDER_CHAIN, model


def _validate_evaluation_ledger(
    value: object,
) -> tuple[str | None, str | None, int]:
    if type(value) is not dict or set(value) != _LEDGER_FIELDS:
        raise ShadowGateManifestError("manifest evaluation ledger is invalid")
    hashes: list[str | None] = []
    for name in ("input_ledger_sha256", "expected_action_ledger_sha256"):
        digest = value[name]
        if digest is not None and (
            type(digest) is not str or _HASH_PATTERN.fullmatch(digest) is None
        ):
            raise ShadowGateManifestError("manifest evaluation ledger is invalid")
        hashes.append(digest)
    case_count = value["case_count"]
    if type(case_count) is not int or not 0 <= case_count <= 100_000:
        raise ShadowGateManifestError("manifest evaluation ledger is invalid")
    return hashes[0], hashes[1], case_count


def _validate_rule_diff_allowlist(value: object) -> None:
    if type(value) is not dict:
        raise ShadowGateManifestError("manifest rule diff allowlist is invalid")
    for rule_id, reasons in value.items():
        _require_version(rule_id, "rule id")
        if reasons != ["EXPECTED_POLICY_CHANGE"]:
            raise ShadowGateManifestError("manifest rule diff allowlist is invalid")


def _freeze_inputs_complete(
    runtime: tuple[
        str | None,
        tuple[tuple[str, str | None], ...],
        tuple[str, ...],
        str,
    ],
    ledger: tuple[str | None, str | None, int],
) -> bool:
    revision, digests, _chain, _model = runtime
    input_hash, expected_hash, case_count = ledger
    return (
        revision is not None
        and all(digest is not None for _name, digest in digests)
        and input_hash is not None
        and expected_hash is not None
        and case_count > 0
    )


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


def _unique_object(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate JSON key")
        result[key] = value
    return result


__all__ = [
    "ShadowGateManifestError",
    "ShadowGateManifestV0",
    "ShadowGateSlotV0",
    "current_shadow_gate_runtime_contract_v0",
    "load_shadow_gate_manifest_v0",
    "shadow_gate_approval_signature_v0",
    "validate_shadow_gate_manifest_v0",
    "validate_shadow_gate_runtime_v0",
]
