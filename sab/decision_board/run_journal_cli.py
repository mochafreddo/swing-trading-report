"""Sanitized CLI seams for the local Decision Board RunJournalV0."""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from sab.report.decision_board import (
    ParsedDecisionBoardStorageKey,
    parse_decision_board_storage_key,
)

from .results import DecisionRunIssueCodeV0
from .run_journal import (
    ExpectedRunV0,
    RunJournalStatusV0,
    RunJournalStoreV0,
    serialize_run_journal_v0,
)
from .runner import RunKindV0
from .shadow_gate import (
    load_shadow_gate_manifest_v0,
    validate_shadow_gate_runtime_v0,
)

_REPORT_FILE_PATTERN = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,255}\Z")
_RUNNER_INVALID = {
    "status": "FAILED",
    "exit_code": 2,
    "issue_code": "JOURNAL_RUNNER_INVALID",
}


def parse_utc_rfc3339_v0(value: object, *, field: str) -> datetime:
    if type(value) is not str or not value.endswith("Z"):
        raise ValueError(f"{field} must be UTC RFC3339")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError(f"{field} must be UTC RFC3339") from exc
    offset = parsed.utcoffset()
    if parsed.tzinfo is None or offset is None:
        raise ValueError(f"{field} must be UTC RFC3339")
    if offset.total_seconds() != 0:
        raise ValueError(f"{field} must be UTC RFC3339")
    canonical = parsed.astimezone(UTC).isoformat().replace("+00:00", "Z")
    if canonical != value:
        raise ValueError(f"{field} must be canonical UTC RFC3339")
    return parsed.astimezone(UTC)


def parse_bounded_int_v0(
    value: object, *, field: str, minimum: int, maximum: int
) -> int:
    if type(value) is not str or not value.isascii() or not value.isdecimal():
        raise ValueError(f"{field} must be a bounded integer")
    parsed = int(value)
    if parsed < minimum or parsed > maximum:
        raise ValueError(f"{field} must be a bounded integer")
    return parsed


def public_records_v0(records: tuple[object, ...]) -> dict[str, object]:
    public = [serialize_run_journal_v0(record) for record in records]
    return {"count": len(public), "records": public}


@dataclass(frozen=True, slots=True)
class JournalShadowProcessConfigV0:
    run_kind: RunKindV0
    expected_at: datetime
    run_id: str
    journal_dir: Path
    grace_seconds: int
    stale_seconds: int
    runner_args: tuple[str, ...]
    dry_run: bool
    gate_manifest: Path | None
    gate_manifest_sha256: str | None

    @classmethod
    def from_strings(
        cls,
        *,
        run_kind: object,
        expected_at: object,
        run_id: object,
        journal_dir: object,
        grace_seconds: object,
        stale_seconds: object,
        runner_args: object,
        dry_run: object,
        gate_manifest: object = None,
        gate_manifest_sha256: object = None,
    ) -> JournalShadowProcessConfigV0:
        if type(run_kind) is not str:
            raise TypeError("run_kind must be a string")
        kind = RunKindV0(run_kind.upper())
        expected = ExpectedRunV0.create(
            run_kind=kind,
            expected_at=parse_utc_rfc3339_v0(expected_at, field="expected_at"),
            run_id=run_id,  # type: ignore[arg-type]
        )
        if type(journal_dir) is not str or not journal_dir:
            raise ValueError("journal_dir must be a path")
        if type(runner_args) is not list or any(
            type(arg) is not str for arg in runner_args
        ):
            raise TypeError("runner arguments must be exact strings")
        args = list(runner_args)
        if args and args[0] == "--":
            args.pop(0)
        if not args or not args[0]:
            raise ValueError("runner arguments are required")
        if type(dry_run) is not bool:
            raise TypeError("dry_run must be a boolean")
        if (gate_manifest is None) != (gate_manifest_sha256 is None):
            raise ValueError("gate manifest identity must be complete")
        manifest_path: Path | None = None
        manifest_hash: str | None = None
        if gate_manifest is not None:
            if type(gate_manifest) is not str or not gate_manifest:
                raise ValueError("gate manifest path is invalid")
            if (
                type(gate_manifest_sha256) is not str
                or re.fullmatch(r"sha256:[0-9a-f]{64}", gate_manifest_sha256) is None
            ):
                raise ValueError("gate manifest hash is invalid")
            manifest_path = Path(gate_manifest)
            manifest_hash = gate_manifest_sha256
        return cls(
            run_kind=expected.run_kind,
            expected_at=expected.expected_at,
            run_id=expected.run_id,
            journal_dir=Path(journal_dir),
            grace_seconds=parse_bounded_int_v0(
                grace_seconds,
                field="grace_seconds",
                minimum=0,
                maximum=604800,
            ),
            stale_seconds=parse_bounded_int_v0(
                stale_seconds,
                field="stale_seconds",
                minimum=1,
                maximum=604800,
            ),
            runner_args=tuple(args),
            dry_run=dry_run,
            gate_manifest=manifest_path,
            gate_manifest_sha256=manifest_hash,
        )

    def dry_run_public_dict(self) -> dict[str, object]:
        public: dict[str, object] = {
            "dry_run": True,
            "run_kind": self.run_kind.value,
            "expected_at": self.expected_at.isoformat().replace("+00:00", "Z"),
            "run_id": self.run_id,
            "grace_seconds": self.grace_seconds,
            "stale_seconds": self.stale_seconds,
            "runner_arg_count": len(self.runner_args),
        }
        if self.gate_manifest_sha256 is not None:
            public["gate_manifest_sha256"] = self.gate_manifest_sha256
        return public


def _valid_report_file(value: object) -> bool:
    return (
        type(value) is str
        and _REPORT_FILE_PATTERN.fullmatch(value) is not None
        and Path(value).name == value
    )


def _parse_t7_report_basename(
    value: object,
) -> ParsedDecisionBoardStorageKey | None:
    if not _valid_report_file(value):
        return None
    assert isinstance(value, str)
    if len(value) < 10:
        return None
    parsed = parse_decision_board_storage_key(f"{value[:4]}/{value[5:7]}/{value}")
    if parsed is None or parsed.basename != value:
        return None
    return parsed


def _parse_runner_terminal_v0(
    stdout: str,
    stderr: str,
    *,
    returncode: int,
    expected_run_kind: RunKindV0,
    expected_run_id: str,
) -> dict[str, object] | None:
    streams = [stream.strip() for stream in (stdout, stderr) if stream.strip()]
    if len(streams) != 1:
        return None
    try:
        value = json.loads(streams[0])
    except json.JSONDecodeError:
        return None
    allowed_issue_codes = {code.value for code in DecisionRunIssueCodeV0}
    if type(value) is not dict or type(value.get("status")) is not str:
        return None
    status = value["status"]
    if status == "FAILED":
        base = {"status", "exit_code", "issue_code"}
        issue_code = value.get("issue_code")
        expected_fields = (
            base | {"report_file"}
            if issue_code == DecisionRunIssueCodeV0.UPLOAD_FAILED.value
            else base
        )
        if set(value) != expected_fields:
            return None
        if (
            type(value["exit_code"]) is not int
            or value["exit_code"] != 2
            or returncode != 2
            or type(issue_code) is not str
            or issue_code not in allowed_issue_codes
        ):
            return None
        if "report_file" in value:
            parsed_report = _parse_t7_report_basename(value["report_file"])
            if (
                parsed_report is None
                or parsed_report.run_kind != expected_run_kind.value
                or parsed_report.run_id != expected_run_id
            ):
                return None
        return value
    if status not in {"PUBLISHED", "BLOCKED"}:
        return None
    required = {
        "status",
        "exit_code",
        "report_file",
        "storage_key",
        "degraded",
    }
    allowed = required | {"upload_issue"}
    if not required <= set(value) <= allowed:
        return None
    if (
        type(value["exit_code"]) is not int
        or value["exit_code"] != 0
        or returncode != 0
        or type(value["degraded"]) is not bool
    ):
        return None
    parsed_report = _parse_t7_report_basename(value["report_file"])
    if (
        parsed_report is None
        or parsed_report.run_kind != expected_run_kind.value
        or parsed_report.run_id != expected_run_id
    ):
        return None
    degraded = value["degraded"]
    storage_key = value["storage_key"]
    upload_issue = value.get("upload_issue")
    if degraded:
        if upload_issue != "UPLOAD_FAILED" or storage_key is not None:
            return None
    elif upload_issue is not None:
        return None
    if storage_key is not None:
        if type(storage_key) is not str:
            return None
        parsed = parse_decision_board_storage_key(storage_key)
        if parsed is None or parsed != parsed_report:
            return None
    return value


def _emit_public_result(value: dict[str, object]) -> None:
    stream = sys.stderr if value["status"] == "FAILED" else sys.stdout
    print(json.dumps(value, sort_keys=True), file=stream)


def execute_journal_shadow_process_v0(config: JournalShadowProcessConfigV0) -> int:
    if type(config) is not JournalShadowProcessConfigV0:
        raise TypeError("shadow process config must use the exact type")
    _validate_gate_binding_v0(config)
    if config.dry_run:
        print(json.dumps(config.dry_run_public_dict(), sort_keys=True))
        return 0

    store = RunJournalStoreV0(config.journal_dir)
    observed_at = datetime.now(UTC)
    started, should_run = store.claim(
        run_kind=config.run_kind,
        expected_at=config.expected_at,
        run_id=config.run_id,
        observed_at=observed_at,
        grace_seconds=config.grace_seconds,
        stale_seconds=config.stale_seconds,
    )
    if not should_run:
        print(
            json.dumps(serialize_run_journal_v0(started), sort_keys=True),
            file=sys.stderr,
        )
        return 2
    completed = subprocess.run(
        config.runner_args,
        capture_output=True,
        text=True,
        check=False,
    )
    terminal = _parse_runner_terminal_v0(
        completed.stdout,
        completed.stderr,
        returncode=completed.returncode,
        expected_run_kind=config.run_kind,
        expected_run_id=config.run_id,
    )
    if terminal is None:
        _emit_public_result(_RUNNER_INVALID)
        return 2
    issue_codes: tuple[str, ...] = ()
    if terminal.get("issue_code") is not None:
        issue_codes = (str(terminal["issue_code"]),)
    elif terminal.get("upload_issue") is not None:
        issue_codes = (str(terminal["upload_issue"]),)
    store.finish(
        started,
        status=RunJournalStatusV0(str(terminal["status"])),
        terminal_at=datetime.now(UTC),
        issue_codes=issue_codes,
        report_file=terminal.get("report_file"),  # type: ignore[arg-type]
    )
    _emit_public_result(terminal)
    return completed.returncode


def _validate_gate_binding_v0(config: JournalShadowProcessConfigV0) -> None:
    if config.gate_manifest is None:
        if "--gate-manifest-sha256" in config.runner_args:
            raise ValueError("runner gate manifest identity is unbound")
        return
    assert config.gate_manifest_sha256 is not None
    manifest = load_shadow_gate_manifest_v0(
        config.gate_manifest,
        require_approved=not config.dry_run,
    )
    if manifest.manifest_sha256 != config.gate_manifest_sha256:
        raise ValueError("gate manifest hash does not match")
    matching_slots = tuple(
        slot
        for slot in manifest.slots
        if slot.run_kind is config.run_kind
        and slot.expected_at == config.expected_at
        and slot.run_id == config.run_id
    )
    if len(matching_slots) != 1:
        raise ValueError("gate manifest slot does not match")
    flag_positions = tuple(
        index
        for index, arg in enumerate(config.runner_args)
        if arg == "--gate-manifest-sha256"
    )
    if (
        len(flag_positions) != 1
        or flag_positions[0] + 1 >= len(config.runner_args)
        or config.runner_args[flag_positions[0] + 1] != manifest.manifest_sha256
    ):
        raise ValueError("runner gate manifest hash does not match")
    if not config.dry_run:
        model = str(
            os.getenv("DECISION_BOARD_OPENAI_MODEL")
            or os.getenv("OPENAI_AI_BRIEF_MODEL")
            or ""
        ).strip()
        if not model:
            raise ValueError("gate runtime claim model is unavailable")
        validate_shadow_gate_runtime_v0(
            manifest,
            repo_root=Path.cwd(),
            claim_model=model,
        )


__all__ = [
    "JournalShadowProcessConfigV0",
    "execute_journal_shadow_process_v0",
    "parse_bounded_int_v0",
    "parse_utc_rfc3339_v0",
    "public_records_v0",
]
