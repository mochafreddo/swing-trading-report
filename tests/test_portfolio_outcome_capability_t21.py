from __future__ import annotations

import copy
import json
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest
from sab.portfolio_mandate.capability_probe import (
    CapabilityProbeContractError,
    run_recorded_capability_probe_t21,
    validate_capability_probe_package_t21,
)

FIXTURE_PATH = (
    Path(__file__).parent
    / "fixtures"
    / "portfolio_mandate"
    / "portfolio-outcome-capability-t21.recorded.json"
)


def test_default_cli_reports_toss_plan_without_reading_fixture_or_writing_artifact(
    tmp_path: Path,
) -> None:
    script = (
        Path(__file__).resolve().parents[1]
        / "scripts/run_portfolio_outcome_capability_t21.py"
    )
    artifact = tmp_path / "must-not-exist.json"
    result = subprocess.run(
        [
            sys.executable,
            str(script),
            "--fixture",
            "missing.json",
            "--artifact",
            str(artifact),
        ],
        cwd=tmp_path,
        check=True,
        capture_output=True,
        text=True,
    )
    readiness = json.loads(result.stdout)
    assert readiness["execution_history_provider"] == "TOSS_SECURITIES"
    assert readiness["provider_history_state"] == "NOT_EVALUATED"
    assert (
        readiness["websocket_history_recovery"]
        == "UNSUPPORTED_DISCONNECTED_EVENTS_NOT_REPLAYED"
    )
    assert (
        readiness["websocket_execution_granularity"]
        == "ORDER_SNAPSHOT_WITHOUT_FILLED_AT"
    )
    assert readiness["file_import_required"] is False
    assert readiness["history_input_mode"] == "TOSS_API_ORDER_AGGREGATE"
    assert readiness["state"] == "READY_FOR_TOSS_ORDER_AGGREGATE_PROBE_APPROVAL"
    assert readiness["proposed_budgets"] == {
        "max_requests": 5,
        "max_pages": 4,
        "max_response_body_bytes": 1_048_576,
        "max_elapsed_seconds": 30,
        "page_size": 20,
        "max_date_window_days": 30,
    }
    assert (
        readiness["documented_execution_granularity"]
        == "ORDER_AGGREGATE_NOT_INDIVIDUAL_FILL"
    )
    assert (
        readiness["t15_mapping_state"]
        == "BLOCKED_NO_VERIFIED_FILL_ID_OR_CORRECTION_LINK"
    )
    assert readiness["documented_history_reads"] == [
        "GET /api/v1/orders",
        "GET /api/v1/orders/{orderId}",
    ]
    assert readiness["allowed_live_requests"] == []
    assert readiness["credential_usage_authorized"] is False
    assert readiness["kis_probe_approval_applicable"] is False
    assert readiness["holdings_are_execution_evidence"] is False
    assert readiness["provider_calls"] == readiness["order_operations"] == 0
    assert not artifact.exists()


def test_explicit_replay_labels_historical_kis_evidence(tmp_path: Path) -> None:
    script = (
        Path(__file__).resolve().parents[1]
        / "scripts/run_portfolio_outcome_capability_t21.py"
    )
    artifact = tmp_path / "recorded.json"
    result = subprocess.run(
        [
            sys.executable,
            str(script),
            "--recorded-replay",
            "--fixture",
            str(FIXTURE_PATH.resolve()),
            "--artifact",
            str(artifact),
        ],
        cwd=tmp_path,
        check=True,
        capture_output=True,
        text=True,
    )
    summary = json.loads(result.stdout)
    assert summary["evidence_scope"] == "HISTORICAL_KIS_RECORDED_ONLY_NOT_TOSS"
    assert summary["scenario_count"] == 14
    assert summary["provider_calls"] == 0
    assert (
        json.loads(artifact.read_text())["evidence_scope"] == summary["evidence_scope"]
    )


def _fixture() -> dict[str, Any]:
    value = json.loads(FIXTURE_PATH.read_text(encoding="utf-8"))
    assert isinstance(value, dict)
    return value


def test_t21_contract_exposes_only_token_exchange_and_read_only_history_requests() -> (
    None
):
    package = validate_capability_probe_package_t21(_fixture())
    requests = package["probe_contract"]["requests"]

    assert requests == [
        {
            "name": "oauth_token_exchange",
            "method": "POST",
            "endpoint": "https://openapi.koreainvestment.com:9443/oauth2/tokenP",
        },
        {
            "name": "domestic_order_history",
            "method": "GET",
            "endpoint": "https://openapi.koreainvestment.com:9443/uapi/domestic-stock/v1/trading/inquire-daily-ccld",
        },
        {
            "name": "overseas_order_history",
            "method": "GET",
            "endpoint": "https://openapi.koreainvestment.com:9443/uapi/overseas-stock/v1/trading/inquire-ccnl",
        },
    ]
    assert package["provider_history_state"] == "NOT_EVALUATED"
    assert package["probe_contract"]["budgets"] == {
        "max_requests": 8,
        "max_pages": 4,
        "max_response_bytes": 1_048_576,
        "max_elapsed_ms": 30_000,
    }
    assert package["probe_contract"]["credential_boundary"] == {
        "required_inputs": [
            "app_key",
            "app_secret",
            "account_number",
            "account_product_code",
        ],
        "usage": "USER_APPROVED_PROCESS_MEMORY_ONLY_ONE_SHOT",
        "token_exchange": "ONE_POST_ONLY",
        "persistence": "FORBIDDEN",
        "logging": "FORBIDDEN",
    }
    assert set(package["probe_contract"]["forbidden_operations"]) == {
        "ORDER_CREATE",
        "ORDER_MODIFY",
        "ORDER_CANCEL",
    }


def test_t21_recorded_runner_covers_success_and_every_failure_branch() -> None:
    package = validate_capability_probe_package_t21(_fixture())

    actual = {
        scenario["scenario_id"]: run_recorded_capability_probe_t21(
            package, scenario["scenario_id"]
        )["result_code"]
        for scenario in package["scenarios"]
    }

    assert actual == {
        "success": "COMPLETE",
        "incomplete-pagination": "INCOMPLETE_PAGINATION",
        "duplicate-fill": "DUPLICATE_FILL",
        "cursor-loop": "CURSOR_LOOP",
        "timeout": "TIMEOUT",
        "http-401": "HTTP_401",
        "http-403": "HTTP_403",
        "http-429": "HTTP_429",
        "http-5xx": "HTTP_5XX",
        "malformed-payload": "MALFORMED_PAYLOAD",
        "request-budget": "REQUEST_BUDGET_EXCEEDED",
        "page-budget": "PAGE_BUDGET_EXCEEDED",
        "byte-budget": "BYTE_BUDGET_EXCEEDED",
        "time-budget": "TIME_BUDGET_EXCEEDED",
    }


def test_t21_success_artifact_is_sanitized_and_keeps_provider_not_evaluated() -> None:
    result = run_recorded_capability_probe_t21(_fixture(), "success")
    serialized = json.dumps(result, sort_keys=True)

    assert result["state"] == "RECORDED_FIXTURE_PASS"
    assert result["provider_history_state"] == "NOT_EVALUATED"
    assert result["capabilities"] == {
        "oauth_scope": "NOT_EVALUATED",
        "history_retention_window": "RECORDED_FIXTURE_ONLY",
        "pagination_cursor": "COMPLETE_RECORDED",
        "partial_fill": "OBSERVED_RECORDED",
        "correction_cancel": "OBSERVED_RECORDED",
        "fill_identity": "UNIQUE_RECORDED",
        "outage_behavior": "NOT_TRIGGERED",
    }
    for forbidden in (
        "account_id",
        "account_number",
        "account_product_code",
        "app_key",
        "app_secret",
        "token",
        "quantity",
        "price",
        "profit_loss",
        "raw_payload",
    ):
        assert forbidden not in serialized


def test_t21_history_post_or_order_mutation_surface_fails_closed() -> None:
    history_post = _fixture()
    history_post["probe_contract"]["requests"][1]["method"] = "POST"
    with pytest.raises(CapabilityProbeContractError, match="GET"):
        validate_capability_probe_package_t21(history_post)

    extra_order_endpoint = _fixture()
    extra_order_endpoint["probe_contract"]["requests"].append(
        {
            "name": "order_create",
            "method": "POST",
            "endpoint": "https://openapi.koreainvestment.com:9443/uapi/domestic-stock/v1/trading/order-cash",
        }
    )
    with pytest.raises(CapabilityProbeContractError, match="requests"):
        validate_capability_probe_package_t21(extra_order_endpoint)


def test_t21_request_page_byte_and_time_budgets_fail_closed() -> None:
    package = _fixture()
    expected = {
        "request-budget": "REQUEST_BUDGET_EXCEEDED",
        "page-budget": "PAGE_BUDGET_EXCEEDED",
        "byte-budget": "BYTE_BUDGET_EXCEEDED",
        "time-budget": "TIME_BUDGET_EXCEEDED",
    }

    for scenario_id, result_code in expected.items():
        result = run_recorded_capability_probe_t21(package, scenario_id)
        assert result["result_code"] == result_code
        assert result["state"] == "RECORDED_FIXTURE_FAIL"


def test_t21_validation_does_not_mutate_recorded_fixture() -> None:
    package = _fixture()
    before = copy.deepcopy(package)

    validate_capability_probe_package_t21(package)

    assert package == before
