from __future__ import annotations

from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]


def _read(relative_path: str) -> str:
    return (REPO_ROOT / relative_path).read_text(encoding="utf-8")


def test_decision_board_reference_is_linked_and_states_current_boundary() -> None:
    reference = _read("docs/decision-board.md")
    for index_path in ("README.md", "docs/README.md", "docs/runbook.md"):
        assert "decision-board.md" in _read(index_path)

    assert "US SWING" in reference
    assert "CONFIG_UNAVAILABLE" in reference
    assert "exit 2" in reference
    assert "DecisionBoardProductionComponentsV0" in reference
    assert "sab decision-board-shadow-live" in reference
    assert "content-addressed Supabase Storage input snapshot" in reference
    assert "launchd template과 shadow gate manifest는 여전히 비활성" in reference
    assert "기존 `sab decision-board`" in reference
    assert "계속 환경변수나" in reference and "credential을 읽지 않으며" in reference
    assert "raw loader, preparer, enricher를" in reference
    assert "batch owner" in reference and "OpenAI Responses claim verifier" in reference
    assert "--gate-manifest" in reference
    assert "--input-ledger" in reference
    assert "--expected-action-ledger" in reference
    assert "attempts/failures/timeouts" in reference
    assert "사용자가 모든 매수·매도를 직접 실행" in reference
    assert "주문 생성·수정·취소" in reference
    assert "<64-lowercase-hex>" not in reference
    assert "<64-lowercase-hex>" not in _read("docs/runbook.md")


def test_shadow_evaluation_freezes_the_approved_graduation_contract() -> None:
    evaluation = _read("docs/decision-board-shadow-evaluation.md")
    for index_path in ("README.md", "docs/README.md", "docs/runbook.md"):
        assert "decision-board-shadow-evaluation.md" in _read(index_path)

    assert 'minimum_sessions": 20' in evaluation
    assert "최소 20개의 **US 거래 session**" in evaluation
    for reason in (
        "EXPECTED_POLICY_CHANGE",
        "INPUT_GAP",
        "SOURCE_GAP",
        "BUG",
        "UNEXPLAINED",
    ):
        assert reason in evaluation
    assert "`UNEXPLAINED` count | 0" in evaluation
    assert "통과는 자동 활성화가 아닙니다" in evaluation
    assert "approval_signature_sha256" in evaluation
    assert "case_id/run_kind/sealed_input_hash/item_id" in evaluation
    assert "주문 실행은 그 이후에도 사용자 수동" in evaluation
    assert "<64-lowercase-hex>" not in evaluation


def test_decision_board_docs_do_not_claim_default_production_activation() -> None:
    current_state_docs = (
        "README.md",
        "docs/overview.md",
        "docs/PRD.md",
        "docs/STRATEGY.md",
        "docs/ARCHITECTURE.md",
        "docs/deployment.md",
        "docs/operations.md",
        "docs/api.md",
    )
    for path in current_state_docs:
        text = _read(path)
        assert "Decision Board" in text, path

    readme = _read("README.md")
    assert "explicit live-shadow adapter" in readme
    assert "schedule은 비활성" in readme
    assert "실제 launchd schedule은 비활성" in _read("docs/deployment.md")
    assert "explicit live-shadow command" in _read("docs/deployment.md")
    operations = _read("docs/operations.md")
    assert "explicit live-shadow composition은 구현되어 있지만" in operations
    assert "schedule과 승인 manifest는 비활성" in operations
    assert "decision-board-shadow-live" in _read("docs/api.md")
    assert "explicit live-shadow adapter가 구현됐지만" in _read("docs/overview.md")
    assert "recorded/live 비교와 별도 manifest 승인 뒤" in _read("docs/runbook.md")


def test_documented_journal_configuration_matches_compose_defaults() -> None:
    configuration = _read("docs/configuration.md")
    compose = _read("docker-compose.yml")
    expected_defaults = {
        "DECISION_BOARD_JOURNAL_LIMIT": "20",
        "DECISION_BOARD_JOURNAL_SCAN_LIMIT": "200",
        "DECISION_BOARD_JOURNAL_MAX_RECORD_BYTES": "65536",
        "DECISION_BOARD_JOURNAL_MAX_OUTPUT_BYTES": "262144",
        "DECISION_BOARD_JOURNAL_TIMEOUT_MS": "1500",
    }
    for name, value in expected_defaults.items():
        assert f"`{name}`" in configuration
        assert f"${{{name}:-{value}}}" in compose
