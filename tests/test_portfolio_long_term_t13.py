from __future__ import annotations

import copy
import json
from pathlib import Path
from typing import Any

import pytest
from jsonschema import (  # type: ignore[import-untyped]
    Draft202012Validator,
    FormatChecker,
)
from sab.portfolio_mandate.long_term import (
    PortfolioLongTermContractError,
    compile_portfolio_long_term_t13,
    validate_portfolio_long_term_t13_fixture,
)

REPO_ROOT = Path(__file__).parents[1]
FIXTURE_PATH = REPO_ROOT / "web" / "fixtures" / "portfolio-long-term.t13.synthetic.json"
SCHEMA_PATH = REPO_ROOT / "schemas" / "portfolio-long-term.t13.schema.json"


def _shared_fixture() -> dict[str, Any]:
    value = json.loads(FIXTURE_PATH.read_text(encoding="utf-8"))
    assert isinstance(value, dict)
    return value


def _representative_case() -> dict[str, Any]:
    return {
        "schema_version": "portfolio-long-term.t13",
        "mode": "LOCAL_ONLY",
        "as_of": "2026-09-01T00:00:00Z",
        "cases": [
            {
                "case_id": "representative-hold",
                "instrument": {
                    "instrument_id": "11111111-1111-4111-8111-111111111111",
                    "canonical_ticker": "ACME.NAS",
                    "company_name": "Acme Holdings",
                },
                "mandate": {
                    "classification_state": "ACTIVE",
                    "approval_state": "APPROVED",
                    "horizon": "LONG_TERM",
                    "thesis": "Recurring revenue can compound while retention stays durable.",
                    "invalidation_predicate": {
                        "metric": "net_revenue_retention_pct",
                        "operator": "LT",
                        "threshold": "100.000000",
                        "unit": "PERCENT",
                        "period": "FY2026Q2",
                    },
                    "review_cadence": {"kind": "WEEKLY", "due": True},
                },
                "evidence": {
                    "validation_status": "VALID",
                    "source_tier": "PRIMARY",
                    "filing_event": {
                        "source_id": "21111111-1111-4111-8111-111111111111",
                        "source_url": "https://investor.example.com/filings/fy2026q2",
                        "publisher": "Acme Holdings",
                        "published_at": "2026-08-31T20:00:00Z",
                        "period": "FY2026Q2",
                        "supporting_span": "Net revenue retention was 108 percent.",
                    },
                    "predicate_evaluation": {
                        "authority": "DETERMINISTIC_PARSER",
                        "result": "NOT_FULFILLED",
                        "observed_value": "108.000000",
                        "unit": "PERCENT",
                        "period": "FY2026Q2",
                        "parser_version": "filing-parser.v1",
                    },
                },
                "concentration": {"status": "PASS"},
            }
        ],
    }


def test_current_authoritative_non_fulfillment_keeps_long_term_holding() -> None:
    result = compile_portfolio_long_term_t13(_representative_case())

    assert result == (
        {
            "case_id": "representative-hold",
            "instrument_id": "11111111-1111-4111-8111-111111111111",
            "canonical_ticker": "ACME.NAS",
            "status": "DECIDED",
            "action": "HOLD",
            "reason_code": "PREDICATE_NOT_FULFILLED",
            "mode": "LOCAL_ONLY",
        },
    )


def test_long_term_policy_truth_table_fails_closed() -> None:
    cases: list[tuple[tuple[str, ...], object, tuple[str, str | None, str]]] = [
        (
            ("evidence", "predicate_evaluation", "result"),
            "FULFILLED",
            ("DECIDED", "SELL", "PREDICATE_FULFILLED"),
        ),
        (
            ("evidence", "validation_status"),
            "STALE",
            ("REVIEW", "REVIEW", "EVIDENCE_STALE"),
        ),
        (
            ("evidence", "validation_status"),
            "CONFLICTED",
            ("REVIEW", "REVIEW", "EVIDENCE_CONFLICTED"),
        ),
        (
            ("concentration", "status"),
            "BREACH",
            ("REVIEW", "REVIEW", "CONCENTRATION_BREACH"),
        ),
        (
            ("evidence", "predicate_evaluation", "authority"),
            "AI_RESEARCH",
            ("REVIEW", "REVIEW", "PREDICATE_REVIEW_ONLY"),
        ),
        (
            ("mandate", "classification_state"),
            "UNCLASSIFIED",
            ("NO_ADVICE", None, "MANDATE_UNCLASSIFIED"),
        ),
        (
            ("mandate", "review_cadence", "due"),
            False,
            ("NOT_DUE", None, "REVIEW_NOT_DUE"),
        ),
    ]

    for path, value, expected in cases:
        fixture = copy.deepcopy(_representative_case())
        target: Any = fixture["cases"][0]
        for part in path[:-1]:
            target = target[part]
        target[path[-1]] = value
        if path == ("evidence", "predicate_evaluation", "authority"):
            target["result"] = "CANDIDATE"

        decision = compile_portfolio_long_term_t13(fixture)[0]

        assert (
            decision["status"],
            decision["action"],
            decision["reason_code"],
        ) == expected


def test_shared_synthetic_fixture_compiles_to_the_frozen_projection() -> None:
    fixture = _shared_fixture()
    schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))

    Draft202012Validator(schema, format_checker=FormatChecker()).validate(fixture)
    assert validate_portfolio_long_term_t13_fixture(fixture) == fixture
    first = compile_portfolio_long_term_t13(fixture)
    second = compile_portfolio_long_term_t13(copy.deepcopy(fixture))

    assert list(first) == fixture["expected_decisions"]
    assert first == second
    serialized = json.dumps(first, sort_keys=True, separators=(",", ":"))
    for private_field in (
        "account_id",
        "account_ref_hash",
        "quantity",
        "entry_price",
        "profit_loss",
        "notes",
        "tags",
    ):
        assert private_field not in serialized


def test_predicate_and_mandate_authority_fail_closed() -> None:
    ai_fulfillment = _shared_fixture()
    ai_evaluation = ai_fulfillment["cases"][5]["evidence"]["predicate_evaluation"]
    ai_evaluation["result"] = "FULFILLED"
    with pytest.raises(PortfolioLongTermContractError, match="AI_RESEARCH"):
        validate_portfolio_long_term_t13_fixture(ai_fulfillment)

    missing_parser = _shared_fixture()
    missing_parser["cases"][1]["evidence"]["predicate_evaluation"]["parser_version"] = (
        None
    )
    with pytest.raises(PortfolioLongTermContractError, match="parser_version"):
        validate_portfolio_long_term_t13_fixture(missing_parser)

    unapproved_active = _shared_fixture()
    unapproved_active["cases"][0]["mandate"]["approval_state"] = "DRAFT"
    with pytest.raises(PortfolioLongTermContractError, match="ACTIVE requires"):
        validate_portfolio_long_term_t13_fixture(unapproved_active)

    private_input = _shared_fixture()
    private_input["cases"][0]["instrument"]["quantity"] = "10.000000"
    with pytest.raises(PortfolioLongTermContractError, match="private field"):
        validate_portfolio_long_term_t13_fixture(private_input)

    malformed_filing = _shared_fixture()
    malformed_filing["cases"][0]["evidence"]["filing_event"] = {
        "source_url": "http://untrusted.example.com/not-primary"
    }
    with pytest.raises(PortfolioLongTermContractError, match="filing_event"):
        validate_portfolio_long_term_t13_fixture(malformed_filing)

    unclassified = compile_portfolio_long_term_t13(_shared_fixture())[6]
    assert (unclassified["status"], unclassified["action"]) == (
        "NO_ADVICE",
        None,
    )
