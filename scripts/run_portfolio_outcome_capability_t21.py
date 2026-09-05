#!/usr/bin/env python3
"""Report Toss history readiness; optionally replay historical KIS fixtures."""

from __future__ import annotations

import argparse
import json
import os
import resource
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from sab.portfolio_mandate.capability_probe import (  # noqa: E402
    run_recorded_capability_probe_t21,
    validate_capability_probe_package_t21,
)
from sab.portfolio_mandate.toss_order_probe import (  # noqa: E402
    run_toss_order_probe_t21,
)


def toss_history_readiness() -> dict[str, Any]:
    """Describe the current local-only boundary, not a live API capability claim."""
    return {
        "schema_version": "portfolio-outcome-readiness.t21",
        "execution_history_provider": "TOSS_SECURITIES",
        "market_data_provider": "KIS_UNCHANGED",
        "provider_history_state": "NOT_EVALUATED",
        "state": "READY_FOR_TOSS_ORDER_AGGREGATE_PROBE_APPROVAL",
        "public_spec_version": "1.2.14",
        "public_async_spec_version": "1.2.2",
        "websocket_history_recovery": "UNSUPPORTED_DISCONNECTED_EVENTS_NOT_REPLAYED",
        "websocket_execution_granularity": "ORDER_SNAPSHOT_WITHOUT_FILLED_AT",
        "history_input_mode": "TOSS_API_ORDER_AGGREGATE",
        "file_import_required": False,
        "documented_history_reads": [
            "GET /api/v1/orders",
            "GET /api/v1/orders/{orderId}",
        ],
        "documented_execution_granularity": "ORDER_AGGREGATE_NOT_INDIVIDUAL_FILL",
        "t15_mapping_state": "BLOCKED_NO_VERIFIED_FILL_ID_OR_CORRECTION_LINK",
        "repository_adapter_scope": "HOLDINGS_AND_DEFAULT_DENY_ORDER_PROBE",
        "holdings_are_execution_evidence": False,
        "allowed_live_requests": [],
        "proposed_requests": [
            "POST https://openapi.tossinvest.com/oauth2/token (once)",
            "GET https://openapi.tossinvest.com/api/v1/orders (CLOSED only)",
        ],
        "proposed_budgets": {
            "max_requests": 5,
            "max_pages": 4,
            "max_response_body_bytes": 1_048_576,
            "max_elapsed_seconds": 30,
            "page_size": 20,
            "max_date_window_days": 30,
        },
        "account_routing": "PRECONFIGURED_ACCOUNT_SEQ_NOT_ACCOUNT_NUMBER",
        "credential_usage_authorized": False,
        "kis_probe_approval_applicable": False,
        "next_steps": [
            "REQUEST_TOSS_SPECIFIC_APPROVAL_WITH_EXPLICIT_DATE_RANGE",
            "RUN_BOUNDED_CLOSED_ORDER_PROBE_WITHOUT_FILL_CONVERSION",
            "KEEP_RETENTION_MANUAL_COVERAGE_AND_FILL_LINEAGE_UNVERIFIED",
        ],
        "provider_calls": 0,
        "order_operations": 0,
    }


def _load(path: Path) -> dict[str, Any]:
    def reject_duplicates(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for key, value in pairs:
            if key in result:
                raise ValueError(f"duplicate key: {key}")
            result[key] = value
        return result

    value = json.loads(
        path.read_text(encoding="utf-8"), object_pairs_hook=reject_duplicates
    )
    if not isinstance(value, dict):
        raise ValueError("recorded package must be an object")
    return value


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument(
        "--recorded-replay",
        action="store_true",
        help="Replay historical KIS fixtures only; this does not validate Toss history.",
    )
    mode.add_argument(
        "--toss-probe-approved",
        action="store_true",
        help="Execute only after explicit Toss-specific approval; credentials from process environment only.",
    )
    parser.add_argument(
        "--from-date", help="Inclusive order creation date, KST, YYYY-MM-DD"
    )
    parser.add_argument(
        "--to-date", help="Inclusive order creation date, KST, YYYY-MM-DD"
    )
    parser.add_argument(
        "--fixture",
        type=Path,
        default=Path(
            "tests/fixtures/portfolio_mandate/portfolio-outcome-capability-t21.recorded.json"
        ),
    )
    parser.add_argument(
        "--artifact",
        type=Path,
        default=Path("tmp/portfolio-outcome-capability-t21.local.json"),
    )
    args = parser.parse_args()
    if args.toss_probe_approved:
        if not args.from_date or not args.to_date:
            parser.error("approved probe requires explicit --from-date and --to-date")
        # Private data must never enter a process core dump. No secret file loader.
        resource.setrlimit(resource.RLIMIT_CORE, (0, 0))
        result = run_toss_order_probe_t21(
            os.environ.pop("TOSS_INVEST_CLIENT_ID", ""),
            os.environ.pop("TOSS_INVEST_CLIENT_SECRET", ""),
            os.environ.pop("TOSS_INVEST_ACCOUNT", ""),
            args.from_date,
            args.to_date,
            approved=True,
        )
        print(json.dumps(result, sort_keys=True))
        return (
            0
            if result["result_code"]
            in {"COMPLETE_ORDER_AGGREGATE", "COMPLETE_NO_ORDERS"}
            else 1
        )
    if not args.recorded_replay:
        print(json.dumps(toss_history_readiness(), sort_keys=True))
        return 0
    package = validate_capability_probe_package_t21(_load(args.fixture))
    artifacts = [
        run_recorded_capability_probe_t21(package, scenario["scenario_id"])
        for scenario in package["scenarios"]
    ]
    expected = {
        scenario["scenario_id"]: scenario["expected_result_code"]
        for scenario in package["scenarios"]
    }
    actual = {
        artifact["scenario_id"]: artifact["result_code"] for artifact in artifacts
    }
    if actual != expected:
        raise RuntimeError("recorded result codes do not match the frozen fixture")
    args.artifact.parent.mkdir(parents=True, exist_ok=True)
    temporary = args.artifact.with_suffix(args.artifact.suffix + ".tmp")
    temporary.write_text(
        json.dumps(
            {
                "schema_version": "portfolio-outcome-capability-artifact-set.t21",
                "provider_history_state": "NOT_EVALUATED",
                "evidence_scope": "HISTORICAL_KIS_RECORDED_ONLY_NOT_TOSS",
                "artifacts": artifacts,
            },
            indent=2,
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )
    temporary.replace(args.artifact)
    print(
        json.dumps(
            {
                "provider_history_state": "NOT_EVALUATED",
                "evidence_scope": "HISTORICAL_KIS_RECORDED_ONLY_NOT_TOSS",
                "scenario_count": len(artifacts),
                "recorded_pass_count": sum(
                    artifact["state"] == "RECORDED_FIXTURE_PASS"
                    for artifact in artifacts
                ),
                "recorded_failure_branch_count": sum(
                    artifact["state"] == "RECORDED_FIXTURE_FAIL"
                    for artifact in artifacts
                ),
                "provider_calls": 0,
                "order_operations": 0,
                "artifact_path": str(args.artifact),
            },
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
