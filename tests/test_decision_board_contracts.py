from __future__ import annotations

import copy
import json
from pathlib import Path
from typing import Any

import pytest
from jsonschema.exceptions import ValidationError  # type: ignore[import-untyped]
from sab.decision_board.contracts import (
    ContractError,
    canonical_json_bytes,
    decision_payload_hash,
    load_decision_board_report,
    validate_decision_board_report,
)

FIXTURE_DIR = Path(__file__).parent / "fixtures" / "decision_board"
SCHEMA_PATH = Path(__file__).parents[1] / "schemas" / "decision-board.v0.schema.json"
VALID_FIXTURES = ("published-entry.json", "published-holding.json", "blocked.json")


def _load_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    assert isinstance(value, dict)
    return value


def _schema_validator() -> Any:
    from jsonschema import (  # type: ignore[import-untyped]
        Draft202012Validator,
        FormatChecker,
    )

    schema = _load_json(SCHEMA_PATH)
    Draft202012Validator.check_schema(schema)
    return Draft202012Validator(schema, format_checker=FormatChecker())


@pytest.mark.parametrize("fixture_name", VALID_FIXTURES)
def test_golden_reports_pass_json_schema_and_python(fixture_name: str) -> None:
    path = FIXTURE_DIR / fixture_name
    report = _load_json(path)

    _schema_validator().validate(report)
    assert load_decision_board_report(path) == report
    assert validate_decision_board_report(report) == report


def test_invalid_golden_report_is_rejected_by_schema_and_python() -> None:
    report = _load_json(FIXTURE_DIR / "invalid-review-action.json")

    with pytest.raises(ValidationError):
        _schema_validator().validate(report)
    with pytest.raises(
        ContractError, match=r"\$\.decision_payload\.items\[0\]\.action"
    ):
        validate_decision_board_report(report)


def test_payload_hash_uses_canonical_payload_only() -> None:
    report = _load_json(FIXTURE_DIR / "published-entry.json")
    payload = report["decision_payload"]

    assert canonical_json_bytes(payload) == json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    assert decision_payload_hash(payload) == report["decision_payload_hash"]

    changed_envelope = copy.deepcopy(report)
    changed_envelope["metadata"] = {"compiler_version": "different"}
    assert (
        decision_payload_hash(changed_envelope["decision_payload"])
        == report["decision_payload_hash"]
    )


def test_payload_hash_mismatch_is_rejected_with_a_useful_path() -> None:
    report = _load_json(FIXTURE_DIR / "published-entry.json")
    report["decision_payload"]["items"][0]["action"] = "AVOID"

    with pytest.raises(ContractError, match=r"\$\.decision_payload_hash"):
        validate_decision_board_report(report)


def test_contracts_reject_unknown_fields_and_naive_timestamps() -> None:
    report = _load_json(FIXTURE_DIR / "blocked.json")
    report["unexpected"] = True
    with pytest.raises(ContractError, match=r"\$\.unexpected"):
        validate_decision_board_report(report)

    report = _load_json(FIXTURE_DIR / "blocked.json")
    report["created_at"] = "2026-08-06T03:00:03"
    with pytest.raises(ContractError, match=r"\$\.created_at"):
        validate_decision_board_report(report)


def test_empty_published_universe_is_valid() -> None:
    report = _load_json(FIXTURE_DIR / "published-entry.json")
    report["decision_payload"]["items"] = []
    report["decision_payload_hash"] = decision_payload_hash(report["decision_payload"])

    _schema_validator().validate(report)
    assert validate_decision_board_report(report) == report


def test_schema_exposes_all_normative_v0_contracts() -> None:
    schema = _load_json(SCHEMA_PATH)

    assert schema["$schema"] == "https://json-schema.org/draft/2020-12/schema"
    assert schema["$id"].endswith("/decision-board.v0.schema.json")
    assert {
        "InstrumentRefV0",
        "BrokerSnapshotV0",
        "ClaimValidationV0",
        "DecisionInputV0",
        "DecisionItemV0",
        "DecisionPayloadV0",
        "DecisionBoardEnvelopeV0",
        "RunJournalV0",
    } <= schema["$defs"].keys()


def test_run_journal_allows_failed_without_directional_payload() -> None:
    schema = _load_json(SCHEMA_PATH)
    journal_schema = {
        "$schema": schema["$schema"],
        "$defs": schema["$defs"],
        "$ref": "#/$defs/RunJournalV0",
    }
    from jsonschema import (  # type: ignore[import-untyped]
        Draft202012Validator,
        FormatChecker,
    )

    journal = {
        "schema_version": "decision-board.v0",
        "run_id": "entry-2026-08-06T050000Z",
        "run_kind": "ENTRY",
        "status": "FAILED",
        "expected_at": "2026-08-06T05:00:00Z",
        "started_at": "2026-08-06T05:00:01Z",
        "terminal_at": "2026-08-06T05:00:02Z",
        "issues": [
            {
                "code": "COMPILER_FAILED",
                "message": "Synthetic compiler failure.",
            }
        ],
    }

    Draft202012Validator(journal_schema, format_checker=FormatChecker()).validate(
        journal
    )
