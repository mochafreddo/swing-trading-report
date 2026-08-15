from __future__ import annotations

import copy
import json
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator  # type: ignore[import-untyped]
from sab.__main__ import _build_parser, _dispatch_command
from sab.decision_board.shadow_gate import (
    ShadowGateManifestError,
    load_shadow_gate_manifest_v0,
    validate_shadow_gate_manifest_v0,
)

ROOT = Path(__file__).resolve().parents[1]
MANIFEST = ROOT / "config" / "decision-board-shadow-gate.proposed.json"
SCHEMA = ROOT / "schemas" / "decision-board-shadow-gate.v0.schema.json"


def _raw_manifest() -> dict[str, object]:
    value = json.loads(MANIFEST.read_text(encoding="utf-8"))
    assert type(value) is dict
    return value


def test_proposed_gate_is_schema_valid_and_covers_twenty_xnys_sessions() -> None:
    raw = _raw_manifest()
    schema = json.loads(SCHEMA.read_text(encoding="utf-8"))
    Draft202012Validator.check_schema(schema)
    Draft202012Validator(schema).validate(raw)

    validated = load_shadow_gate_manifest_v0(MANIFEST)

    assert validated.to_public_dict() == {
        "status": "VALID_PROPOSAL",
        "gate_version": "us-swing-shadow-v1-20260817",
        "approval_state": "PENDING",
        "market": "US",
        "calendar": "XNYS",
        "start_session": "2026-08-17",
        "end_session": "2026-09-14",
        "session_count": 20,
        "slot_count": 40,
        "lanes": ["ENTRY", "HOLDING"],
        "manifest_sha256": validated.manifest_sha256,
    }
    assert validated.manifest_sha256.startswith("sha256:")
    assert len(validated.manifest_sha256) == 71


@pytest.mark.parametrize(
    ("mutation", "message"),
    [
        ("holiday", "trading session"),
        ("missing-slot", "expected slots"),
        ("duplicate-slot", "expected slots"),
        ("hard-threshold", "hard thresholds"),
        ("run-id", "slot identity"),
    ],
)
def test_gate_validator_rejects_schedule_and_threshold_mutation(
    mutation: str,
    message: str,
) -> None:
    raw = copy.deepcopy(_raw_manifest())
    sessions = raw["sessions"]
    slots = raw["expected_slots"]
    hard_thresholds = raw["approved_thresholds"]["hard_failures"]  # type: ignore[index]
    assert type(sessions) is list
    assert type(slots) is list
    assert type(hard_thresholds) is dict
    if mutation == "holiday":
        sessions[15] = "2026-09-07"
    elif mutation == "missing-slot":
        slots.pop()
    elif mutation == "duplicate-slot":
        slots[-1] = copy.deepcopy(slots[0])
    elif mutation == "hard-threshold":
        hard_thresholds["unexplained"] = 1
    else:
        slots[0]["run_id"] = "entry-shadow-mutated"  # type: ignore[index]

    with pytest.raises(ShadowGateManifestError, match=message):
        validate_shadow_gate_manifest_v0(raw)


def test_gate_requires_detached_operator_approval_before_shadow_counting() -> None:
    proposed = load_shadow_gate_manifest_v0(MANIFEST)
    assert proposed.approval_state == "PENDING"

    with pytest.raises(ShadowGateManifestError, match="approval is required"):
        load_shadow_gate_manifest_v0(MANIFEST, require_approved=True)


def test_gate_cli_returns_sanitized_proposal_and_approval_required(
    capsys: pytest.CaptureFixture[str],
) -> None:
    parser = _build_parser()
    proposed = parser.parse_args(
        ["decision-board-shadow-gate-validate", "--manifest", str(MANIFEST)]
    )
    assert _dispatch_command(proposed, parser) == 0
    public = json.loads(capsys.readouterr().out)
    assert public["status"] == "VALID_PROPOSAL"
    assert str(MANIFEST) not in json.dumps(public)

    approved = parser.parse_args(
        [
            "decision-board-shadow-gate-validate",
            "--manifest",
            str(MANIFEST),
            "--require-approved",
        ]
    )
    assert _dispatch_command(approved, parser) == 2
    captured = capsys.readouterr()
    assert captured.out == ""
    assert json.loads(captured.err) == {
        "status": "INVALID",
        "exit_code": 2,
        "issue_code": "APPROVAL_REQUIRED",
    }
    assert str(MANIFEST) not in captured.err
