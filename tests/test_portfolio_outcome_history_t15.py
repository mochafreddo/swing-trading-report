from __future__ import annotations

import copy
import json
from pathlib import Path
from typing import Any

import pytest
from sab.portfolio_mandate.outcome_history import (
    OutcomeHistoryContractError,
    adapt_outcome_history_t15,
    parse_redacted_outcome_history_t15_bytes,
)
from sab.portfolio_mandate.outcomes import (
    append_user_outcome_event,
    propose_outcome_matches,
)

FIXTURE_DIR = Path(__file__).parent / "fixtures" / "portfolio_mandate"
RECORDED_PATH = FIXTURE_DIR / "portfolio-outcome-history-t15.recorded.json"
REDACTED_PATH = FIXTURE_DIR / "portfolio-outcome-history-t15.redacted-import.json"
O1_PATH = FIXTURE_DIR / "portfolio-outcome-o1.synthetic.json"


def _read(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    assert isinstance(value, dict)
    return value


def test_recorded_pages_flatten_only_after_complete_cursor_chain() -> None:
    result = adapt_outcome_history_t15(_read(RECORDED_PATH))
    o1 = _read(O1_PATH)

    assert result["input_mode"] == "RECORDED"
    assert result["provider_history_state"] == "NOT_EVALUATED"
    assert result["pagination_state"] == "COMPLETE"
    assert result["page_count"] == 2
    assert len(result["execution_lineages"]) == 1
    assert list(
        propose_outcome_matches(o1["decisions"], result["execution_lineages"])
    ) == [o1["expected_proposals"][0]]


def test_incomplete_or_discontinuous_pagination_fails_closed() -> None:
    incomplete = _read(RECORDED_PATH)
    incomplete["pages"][-1]["next_cursor"] = "page-3"
    with pytest.raises(OutcomeHistoryContractError, match=r"pagination.*complete"):
        adapt_outcome_history_t15(incomplete)

    discontinuous = _read(RECORDED_PATH)
    discontinuous["pages"][1]["request_cursor"] = "wrong-page"
    with pytest.raises(OutcomeHistoryContractError, match="request_cursor"):
        adapt_outcome_history_t15(discontinuous)


def test_duplicate_fill_identity_across_pages_is_rejected() -> None:
    duplicate = _read(RECORDED_PATH)
    copied = copy.deepcopy(duplicate["pages"][0]["execution_lineages"][0])
    copied["execution_lineage_id"] = "39999999-9999-4999-8999-999999999999"
    copied["outcome_lineage_id"] = "49999999-9999-4999-8999-999999999999"
    duplicate["pages"][1]["execution_lineages"].append(copied)

    with pytest.raises(OutcomeHistoryContractError, match="fill identity"):
        adapt_outcome_history_t15(duplicate)


def test_redacted_import_is_bounded_duplicate_key_aware_and_private_safe() -> None:
    result = parse_redacted_outcome_history_t15_bytes(REDACTED_PATH.read_bytes())

    assert result["input_mode"] == "REDACTED_IMPORT"
    assert result["provider_history_state"] == "NOT_EVALUATED"
    serialized = json.dumps(result, sort_keys=True)
    assert "raw-account" not in serialized

    raw_account = _read(REDACTED_PATH)
    raw_account["pages"][0]["execution_lineages"][0]["account_ref_hash"] = "raw-account"
    with pytest.raises(OutcomeHistoryContractError, match="account_ref_hash"):
        parse_redacted_outcome_history_t15_bytes(json.dumps(raw_account).encode())

    with pytest.raises(OutcomeHistoryContractError, match="duplicate key"):
        parse_redacted_outcome_history_t15_bytes(
            b'{"schema_version":"a","schema_version":"b"}'
        )
    with pytest.raises(OutcomeHistoryContractError, match="byte limit"):
        parse_redacted_outcome_history_t15_bytes(b" " * 1_048_577)


def test_redacted_import_cannot_bypass_the_bounded_bytes_parser() -> None:
    with pytest.raises(OutcomeHistoryContractError, match="bytes parser"):
        adapt_outcome_history_t15(_read(REDACTED_PATH))


def test_adapted_history_replays_existing_append_only_correction_contract() -> None:
    history = adapt_outcome_history_t15(_read(RECORDED_PATH))
    o1 = _read(O1_PATH)

    corrected = append_user_outcome_event(
        o1["user_events"][:2],
        o1["user_events"][2],
        decisions=o1["decisions"],
        execution_lineages=history["execution_lineages"],
    )

    assert corrected == tuple(o1["user_events"])
