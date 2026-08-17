from __future__ import annotations

import copy
import json
import subprocess
from pathlib import Path

import pytest
import sab.decision_board.shadow_gate as shadow_gate
from jsonschema import Draft202012Validator  # type: ignore[import-untyped]
from sab.__main__ import _build_parser, _dispatch_command
from sab.decision_board.shadow_gate import (
    ShadowGateManifestError,
    current_shadow_gate_runtime_contract_v0,
    load_shadow_gate_manifest_v0,
    validate_shadow_gate_manifest_v0,
    validate_shadow_gate_runtime_v0,
)

ROOT = Path(__file__).resolve().parents[1]
MANIFEST = ROOT / "config" / "decision-board-shadow-gate.proposed.json"
SCHEMA = ROOT / "schemas" / "decision-board-shadow-gate.v0.schema.json"
APPROVED_LOCAL = ROOT / "config" / "decision-board-shadow-gate.approved.local.json"


def _raw_manifest() -> dict[str, object]:
    value = json.loads(MANIFEST.read_text(encoding="utf-8"))
    assert type(value) is dict
    return value


def _mutate_contract(raw: dict[str, object], mutation: str) -> None:
    approval = raw["approval"]
    policy = raw["policy_versions"]
    schedule = raw["schedule_policy"]
    slots = raw["expected_slots"]
    thresholds = raw["approved_thresholds"]
    assert type(approval) is dict
    assert type(policy) is dict
    assert type(schedule) is dict
    assert type(slots) is list
    assert type(thresholds) is dict
    quality = thresholds["quality"]
    assert type(quality) is dict
    first_slot = slots[0]
    assert type(first_slot) is dict

    if mutation == "root-field":
        raw["unexpected"] = True
    elif mutation == "schema-version":
        raw["schema_version"] = "decision-board-shadow-gate.v1"
    elif mutation == "market":
        raw["market"] = "KR"
    elif mutation == "minimum-sessions":
        raw["minimum_sessions"] = 21
    elif mutation == "session-bounds":
        raw["start_session"] = raw["end_session"]
    elif mutation == "lanes":
        raw["lanes"] = ["HOLDING", "ENTRY"]
    elif mutation == "diff-reasons":
        raw["allowed_diff_reasons"] = ["UNEXPLAINED"]
    elif mutation == "approval":
        approval["state"] = "APPROVED"
    elif mutation == "policy-fields":
        policy.pop("compiler")
    elif mutation == "private-version":
        policy["compiler"] = "secret"
    elif mutation == "schedule-timezone":
        schedule["timezone"] = "Asia/Seoul"
    elif mutation == "schedule-bounds":
        schedule["grace_seconds"] = schedule["stale_seconds"]
    elif mutation == "slot-fields":
        first_slot["unexpected"] = True
    elif mutation == "slot-lane":
        first_slot["run_kind"] = "OTHER"
    elif mutation == "quality-shape":
        quality["provider_failure_rate_max"] = "0.05"
    elif mutation == "quality-too-weak":
        quality["provider_failure_rate_max"] = 0.06
    elif mutation == "runtime-provider-chain":
        runtime = raw["runtime_contract"]
        assert type(runtime) is dict
        runtime["source_provider_chain"] = ["benzinga-news"]
    elif mutation == "metric-denominator":
        metrics = raw["metric_definitions"]
        assert type(metrics) is dict
        coverage = metrics["research_coverage_rate"]
        assert type(coverage) is dict
        coverage["denominator"] = "published_items"
    else:  # pragma: no cover - parameter table is closed below
        raise AssertionError(f"unknown mutation: {mutation}")


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
    assert validated.horizon == "SWING"
    assert validated.source_provider_chain == (
        "finnhub",
        "polygon-news",
        "benzinga-news",
    )
    assert validated.claim_model == "gpt-5.6-sol"
    assert (
        subprocess.run(
            ["git", "check-ignore", "--quiet", str(APPROVED_LOCAL)],
            cwd=ROOT,
            check=False,
        ).returncode
        == 0
    )


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


@pytest.mark.parametrize(
    ("mutation", "message"),
    [
        ("root-field", "root fields"),
        ("schema-version", "schema version"),
        ("market", "market calendar"),
        ("minimum-sessions", "minimum sessions"),
        ("session-bounds", "session bounds"),
        ("lanes", "lanes"),
        ("diff-reasons", "diff reasons"),
        ("approval", "approval identity"),
        ("policy-fields", "policy versions"),
        ("private-version", "policy version"),
        ("schedule-timezone", "schedule timezone"),
        ("schedule-bounds", "schedule bounds"),
        ("slot-fields", "expected slots"),
        ("slot-lane", "slot lane"),
        ("quality-shape", "quality thresholds"),
        ("quality-too-weak", "too weak"),
        ("runtime-provider-chain", "runtime contract"),
        ("metric-denominator", "metric definitions"),
    ],
)
def test_gate_validator_rejects_contract_mutations(
    mutation: str,
    message: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    raw = copy.deepcopy(_raw_manifest())
    _mutate_contract(raw, mutation)
    monkeypatch.setattr(
        shadow_gate, "is_trading_session", lambda *_args, **_kwargs: True
    )

    with pytest.raises(ShadowGateManifestError, match=message):
        validate_shadow_gate_manifest_v0(raw)


def test_gate_requires_detached_operator_approval_before_shadow_counting() -> None:
    proposed = load_shadow_gate_manifest_v0(MANIFEST)
    assert proposed.approval_state == "PENDING"

    with pytest.raises(ShadowGateManifestError, match="approval is required"):
        load_shadow_gate_manifest_v0(MANIFEST, require_approved=True)


def test_approved_gate_requires_all_freeze_inputs_before_shadow_counting() -> None:
    raw = copy.deepcopy(_raw_manifest())
    approval = raw["approval"]
    assert type(approval) is dict
    approval.update(
        {
            "state": "APPROVED",
            "approved_by": "user",
            "approved_at": "2026-08-17T09:00:00Z",
        }
    )

    with pytest.raises(ShadowGateManifestError, match="freeze inputs"):
        validate_shadow_gate_manifest_v0(raw, require_approved=True)

    runtime = raw["runtime_contract"]
    ledger = raw["evaluation_ledger"]
    assert type(runtime) is dict
    assert type(ledger) is dict
    runtime["code_revision"] = "git:" + "1" * 40
    artifact_digests = runtime["artifact_digests"]
    assert type(artifact_digests) is dict
    for name in artifact_digests:
        artifact_digests[name] = "sha256:" + "2" * 64
    ledger.update(
        {
            "input_ledger_sha256": "sha256:" + "3" * 64,
            "expected_action_ledger_sha256": "sha256:" + "4" * 64,
            "case_count": 1,
        }
    )

    validated = validate_shadow_gate_manifest_v0(raw, require_approved=True)
    assert validated.approval_state == "APPROVED"


def test_approved_gate_runtime_contract_matches_executed_artifacts(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    raw = copy.deepcopy(_raw_manifest())
    approval = raw["approval"]
    ledger = raw["evaluation_ledger"]
    assert type(approval) is dict
    assert type(ledger) is dict
    approval.update(
        {
            "state": "APPROVED",
            "approved_by": "user",
            "approved_at": "2026-08-17T09:00:00Z",
        }
    )
    raw["runtime_contract"] = current_shadow_gate_runtime_contract_v0(
        ROOT,
        claim_model="gpt-5.6-sol",
    )
    ledger.update(
        {
            "input_ledger_sha256": "sha256:" + "3" * 64,
            "expected_action_ledger_sha256": "sha256:" + "4" * 64,
            "case_count": 1,
        }
    )
    manifest = validate_shadow_gate_manifest_v0(raw, require_approved=True)
    monkeypatch.setattr(shadow_gate, "_require_clean_git_worktree", lambda _root: None)

    validate_shadow_gate_runtime_v0(
        manifest,
        repo_root=ROOT,
        claim_model="gpt-5.6-sol",
    )
    with pytest.raises(ShadowGateManifestError, match="claim model"):
        validate_shadow_gate_runtime_v0(
            manifest,
            repo_root=ROOT,
            claim_model="different-model",
        )


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
