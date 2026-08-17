from __future__ import annotations

import json
from types import SimpleNamespace

import pytest
import sab.decision_board.live_runtime as live_runtime
from sab.__main__ import _build_parser, _dispatch_command
from sab.decision_board.cli import (
    DecisionBoardCliConfigV0,
    execute_decision_board_shadow_live_cli_v0,
)
from sab.decision_board.results import (
    DecisionRunFailedV0,
    DecisionRunIssueCodeV0,
    create_decision_run_failed_v0,
)


def test_decision_board_cli_parses_safe_boundary_and_failed_exit(
    monkeypatch, capsys, tmp_path
) -> None:
    seen: list[DecisionBoardCliConfigV0] = []

    def execute(config: DecisionBoardCliConfigV0):
        seen.append(config)
        return create_decision_run_failed_v0(
            issue_code=DecisionRunIssueCodeV0.CONFIG_UNAVAILABLE
        )

    monkeypatch.setattr("sab.__main__.execute_decision_board_cli_v0", execute)
    parser = _build_parser()
    ns = parser.parse_args(
        [
            "decision-board",
            "--run-kind",
            "entry",
            "--run-id",
            "entry-cli-001",
            "--idempotency-key",
            "sha256:" + "1" * 64,
            "--created-at",
            "2026-08-09T12:00:00Z",
            "--sealed-input-hash",
            "sha256:" + "2" * 64,
            "--upload-mode",
            "optional",
            "--report-dir",
            str(tmp_path),
        ]
    )
    assert _dispatch_command(ns, parser) == 2
    assert len(seen) == 1
    assert seen[0].to_public_dict() == {
        "run_kind": "ENTRY",
        "run_id": "entry-cli-001",
        "idempotency_key": "sha256:" + "1" * 64,
        "created_at": "2026-08-09T12:00:00Z",
        "sealed_input_hash": "sha256:" + "2" * 64,
        "upload_mode": "OPTIONAL",
    }
    assert str(tmp_path) not in repr(seen[0].to_public_dict())
    captured = capsys.readouterr()
    assert captured.out == ""
    assert json.loads(captured.err) == {
        "status": "FAILED",
        "exit_code": 2,
        "issue_code": "CONFIG_UNAVAILABLE",
    }


def test_decision_board_cli_defaults_to_local_shadow_and_unconfigured_fails_closed(
    capsys, tmp_path
) -> None:
    parser = _build_parser()
    ns = parser.parse_args(
        [
            "decision-board",
            "--run-kind",
            "holding",
            "--run-id",
            "holding-cli-001",
            "--idempotency-key",
            "sha256:" + "3" * 64,
            "--created-at",
            "2026-08-09T12:00:00Z",
            "--sealed-input-hash",
            "sha256:" + "4" * 64,
            "--report-dir",
            str(tmp_path),
        ]
    )
    assert ns.upload_mode == "disabled"
    assert _dispatch_command(ns, parser) == 2
    assert json.loads(capsys.readouterr().err)["issue_code"] == "CONFIG_UNAVAILABLE"
    assert list(tmp_path.iterdir()) == []


def test_decision_board_shadow_live_stays_fail_closed_without_runtime_config(
    monkeypatch, capsys, tmp_path
) -> None:
    for name in (
        "SUPABASE_URL",
        "SUPABASE_SECRET_KEY",
        "SUPABASE_SERVICE_ROLE_KEY",
        "FINNHUB_API_KEY",
        "POLYGON_API_KEY",
        "BENZINGA_API_TOKEN",
        "OPENAI_API_KEY",
        "DECISION_BOARD_OPENAI_MODEL",
        "OPENAI_AI_BRIEF_MODEL",
    ):
        monkeypatch.delenv(name, raising=False)
    parser = _build_parser()
    ns = parser.parse_args(
        [
            "decision-board-shadow-live",
            "--run-kind",
            "entry",
            "--run-id",
            "entry-live-unconfigured",
            "--idempotency-key",
            "sha256:" + "5" * 64,
            "--created-at",
            "2026-08-09T12:00:00Z",
            "--sealed-input-hash",
            "sha256:" + "6" * 64,
            "--gate-manifest",
            str(tmp_path / "gate.json"),
            "--gate-manifest-sha256",
            "sha256:" + "7" * 64,
            "--input-ledger",
            str(tmp_path / "input-ledger.json"),
            "--expected-action-ledger",
            str(tmp_path / "expected-action-ledger.json"),
            "--report-dir",
            str(tmp_path),
        ]
    )

    assert _dispatch_command(ns, parser) == 2
    captured = capsys.readouterr()
    assert captured.out == ""
    assert json.loads(captured.err) == {
        "status": "FAILED",
        "exit_code": 2,
        "issue_code": "CONFIG_UNAVAILABLE",
    }
    assert list(tmp_path.iterdir()) == []


def test_shadow_live_rejects_gate_before_composing_credentialed_adapter(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path,
) -> None:
    composed: list[bool] = []
    monkeypatch.setattr(
        live_runtime,
        "decision_board_live_claim_model_from_env_v0",
        lambda: "recorded-model",
    )
    monkeypatch.setattr(
        live_runtime,
        "build_decision_board_live_adapter_from_env_v0",
        lambda: composed.append(True),
    )
    config = DecisionBoardCliConfigV0.from_strings(
        run_kind="ENTRY",
        run_id="entry-shadow-20260817",
        idempotency_key="sha256:" + "1" * 64,
        created_at="2026-08-17T12:30:00Z",
        sealed_input_hash="sha256:" + "2" * 64,
        upload_mode="DISABLED",
        report_dir=str(tmp_path),
        gate_manifest_sha256="sha256:" + "3" * 64,
        gate_manifest=str(tmp_path / "missing-gate.json"),
        input_ledger=str(tmp_path / "missing-input-ledger.json"),
        expected_action_ledger=str(tmp_path / "missing-expected-ledger.json"),
    )

    result = execute_decision_board_shadow_live_cli_v0(config)

    assert type(result) is DecisionRunFailedV0
    assert result.issue_code is DecisionRunIssueCodeV0.PREPARATION_INVALID
    assert composed == []


def test_shadow_live_composes_and_executes_when_claim_model_matches(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path,
) -> None:
    executed: list[DecisionBoardCliConfigV0] = []
    sentinel = create_decision_run_failed_v0(
        issue_code=DecisionRunIssueCodeV0.CONFIG_UNAVAILABLE
    )

    def execute(
        config: DecisionBoardCliConfigV0,
        *,
        binding: object,
    ) -> DecisionRunFailedV0:
        del binding
        executed.append(config)
        return sentinel

    adapter = SimpleNamespace(
        evidence_builder=SimpleNamespace(
            claim_verifier=SimpleNamespace(model="recorded-model")
        ),
        execute=execute,
    )
    monkeypatch.setattr(
        live_runtime,
        "decision_board_live_claim_model_from_env_v0",
        lambda: "recorded-model",
    )
    monkeypatch.setattr(
        live_runtime,
        "build_decision_board_live_adapter_from_env_v0",
        lambda: adapter,
    )
    monkeypatch.setattr(
        "sab.decision_board.shadow_execution.load_shadow_gate_execution_binding_v0",
        lambda config, *, repo_root, claim_model: object(),
    )
    config = DecisionBoardCliConfigV0.from_strings(
        run_kind="ENTRY",
        run_id="entry-shadow-model-match",
        idempotency_key="sha256:" + "1" * 64,
        created_at="2026-08-17T12:30:00Z",
        sealed_input_hash="sha256:" + "2" * 64,
        upload_mode="DISABLED",
        report_dir=str(tmp_path),
        gate_manifest_sha256="sha256:" + "3" * 64,
        gate_manifest=str(tmp_path / "gate.json"),
        input_ledger=str(tmp_path / "input.json"),
        expected_action_ledger=str(tmp_path / "expected.json"),
    )

    result = execute_decision_board_shadow_live_cli_v0(config)

    assert result is sentinel
    assert executed == [config]


def test_shadow_live_rejects_claim_model_drift_before_execution(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path,
) -> None:
    executed: list[bool] = []

    def execute(config: object, *, binding: object) -> None:
        del config, binding
        executed.append(True)

    adapter = SimpleNamespace(
        evidence_builder=SimpleNamespace(
            claim_verifier=SimpleNamespace(model="drifted-model")
        ),
        execute=execute,
    )
    monkeypatch.setattr(
        live_runtime,
        "decision_board_live_claim_model_from_env_v0",
        lambda: "recorded-model",
    )
    monkeypatch.setattr(
        live_runtime,
        "build_decision_board_live_adapter_from_env_v0",
        lambda: adapter,
    )
    monkeypatch.setattr(
        "sab.decision_board.shadow_execution.load_shadow_gate_execution_binding_v0",
        lambda config, *, repo_root, claim_model: object(),
    )
    config = DecisionBoardCliConfigV0.from_strings(
        run_kind="ENTRY",
        run_id="entry-shadow-model-drift",
        idempotency_key="sha256:" + "4" * 64,
        created_at="2026-08-17T12:30:00Z",
        sealed_input_hash="sha256:" + "5" * 64,
        upload_mode="DISABLED",
        report_dir=str(tmp_path),
        gate_manifest_sha256="sha256:" + "6" * 64,
        gate_manifest=str(tmp_path / "gate.json"),
        input_ledger=str(tmp_path / "input.json"),
        expected_action_ledger=str(tmp_path / "expected.json"),
    )

    result = execute_decision_board_shadow_live_cli_v0(config)

    assert type(result) is DecisionRunFailedV0
    assert result.issue_code is DecisionRunIssueCodeV0.INTERNAL_ERROR
    assert executed == []


def test_decision_board_cli_rejects_invalid_trigger_identity_before_executor(
    monkeypatch, capsys, tmp_path
) -> None:
    calls: list[object] = []
    monkeypatch.setattr(
        "sab.__main__.execute_decision_board_cli_v0",
        lambda config: calls.append(config),
    )
    parser = _build_parser()
    ns = parser.parse_args(
        [
            "decision-board",
            "--run-kind",
            "entry",
            "--run-id",
            "../private-path",
            "--idempotency-key",
            "not-a-hash",
            "--created-at",
            "2026-08-09T12:00:00Z",
            "--sealed-input-hash",
            "sha256:" + "4" * 64,
            "--report-dir",
            str(tmp_path),
        ]
    )
    assert _dispatch_command(ns, parser) == 2
    assert calls == []
    assert json.loads(capsys.readouterr().err)["issue_code"] == "PREPARATION_INVALID"


def test_decision_board_cli_contains_executor_error_without_private_output(
    monkeypatch, capsys, tmp_path
) -> None:
    def failed_executor(config: DecisionBoardCliConfigV0):
        del config
        raise RuntimeError("PRIVATE-SENTINEL executor failure")

    monkeypatch.setattr(
        "sab.__main__.execute_decision_board_cli_v0",
        failed_executor,
    )
    parser = _build_parser()
    ns = parser.parse_args(
        [
            "decision-board",
            "--run-kind",
            "entry",
            "--run-id",
            "entry-cli-internal",
            "--idempotency-key",
            "sha256:" + "5" * 64,
            "--created-at",
            "2026-08-09T12:00:00Z",
            "--sealed-input-hash",
            "sha256:" + "6" * 64,
            "--report-dir",
            str(tmp_path),
        ]
    )

    assert _dispatch_command(ns, parser) == 2
    captured = capsys.readouterr()
    assert captured.out == ""
    assert json.loads(captured.err)["issue_code"] == "INTERNAL_ERROR"
    assert "PRIVATE-SENTINEL" not in captured.err


@pytest.mark.parametrize("invalid_field", ["run-kind", "upload-mode"])
def test_decision_board_cli_does_not_echo_invalid_choice_value(
    invalid_field, capsys, tmp_path
) -> None:
    parser = _build_parser()
    run_kind = "PRIVATE-SENTINEL" if invalid_field == "run-kind" else "entry"
    upload_mode = "PRIVATE-SENTINEL" if invalid_field == "upload-mode" else "disabled"
    ns = parser.parse_args(
        [
            "decision-board",
            "--run-kind",
            run_kind,
            "--run-id",
            "entry-cli-invalid-choice",
            "--idempotency-key",
            "sha256:" + "7" * 64,
            "--created-at",
            "2026-08-09T12:00:00Z",
            "--sealed-input-hash",
            "sha256:" + "8" * 64,
            "--upload-mode",
            upload_mode,
            "--report-dir",
            str(tmp_path),
        ]
    )

    assert _dispatch_command(ns, parser) == 2
    captured = capsys.readouterr()
    assert captured.out == ""
    assert json.loads(captured.err)["issue_code"] == "PREPARATION_INVALID"
    assert "PRIVATE-SENTINEL" not in captured.err
