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
from sab.portfolio_mandate.outcomes import (
    PortfolioOutcomeContractError,
    append_user_outcome_event,
    project_public_outcome_events,
    propose_outcome_matches,
    validate_portfolio_outcome_o1_fixture,
    validate_public_outcome_projection,
)

FIXTURE_PATH = (
    Path(__file__).parent
    / "fixtures"
    / "portfolio_mandate"
    / "portfolio-outcome-o1.synthetic.json"
)
SCHEMA_PATH = Path(__file__).parents[1] / "schemas" / "portfolio-outcome.o1.schema.json"


def _fixture() -> dict[str, Any]:
    value = json.loads(FIXTURE_PATH.read_text(encoding="utf-8"))
    assert isinstance(value, dict)
    return value


def test_synthetic_fixture_proves_unlinked_proposed_and_ambiguous_matching() -> None:
    fixture = _fixture()

    assert validate_portfolio_outcome_o1_fixture(fixture) == fixture
    assert (
        list(
            propose_outcome_matches(fixture["decisions"], fixture["execution_lineages"])
        )
        == fixture["expected_proposals"]
    )
    assert [item["status"] for item in fixture["expected_proposals"]] == [
        "MATCH_PROPOSED",
        "AMBIGUOUS",
        "UNLINKED",
        "MATCH_PROPOSED",
    ]
    assert fixture["decisions"][2]["candidate_id"] is not None
    assert fixture["decisions"][2]["side"] == "BUY"
    assert fixture["execution_lineages"][3]["slice_candidate_ids"] == []
    assert fixture["expected_proposals"][3]["candidate_decision_ids"] == [
        fixture["decisions"][2]["decision_id"]
    ]


@pytest.mark.parametrize(
    ("field", "bad_value"),
    [
        ("instrument_id", "bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb"),
        ("side", "BUY"),
    ],
)
def test_matcher_requires_instrument_and_side(field: str, bad_value: str) -> None:
    fixture = _fixture()
    fixture["execution_lineages"][0][field] = bad_value

    if field == "side":
        with pytest.raises(PortfolioOutcomeContractError):
            propose_outcome_matches(fixture["decisions"], fixture["execution_lineages"])
        return

    proposals = propose_outcome_matches(
        fixture["decisions"], fixture["execution_lineages"]
    )

    assert proposals[0]["status"] == "UNLINKED"


@pytest.mark.parametrize(
    ("path", "bad_value"),
    [
        (("fills", 0, "executed_at"), "2026-08-01T14:30:00.001Z"),
        (("fills", 0, "price"), "101.000001"),
        (("fills", 0, "quantity"), "2.000000"),
        (("slice_candidate_ids",), ["23333333-3333-4333-8333-333333333333"]),
    ],
)
def test_matcher_requires_window_price_total_quantity_and_slice(
    path: tuple[str | int, ...], bad_value: object
) -> None:
    fixture = _fixture()
    target: Any = fixture["execution_lineages"][0]
    for part in path[:-1]:
        target = target[part]
    target[path[-1]] = bad_value

    proposals = propose_outcome_matches(
        fixture["decisions"], fixture["execution_lineages"]
    )

    assert proposals[0]["status"] == "UNLINKED"


def test_partial_fills_sum_across_cancel_reorder_lineage() -> None:
    fixture = _fixture()
    proposal = propose_outcome_matches(
        fixture["decisions"], fixture["execution_lineages"]
    )[0]

    assert proposal["total_filled_quantity"] == "10.000000"
    assert (
        fixture["execution_lineages"][0]["orders"][1]["supersedes_broker_order_id"]
        == fixture["execution_lineages"][0]["orders"][0]["broker_order_id"]
    )


def test_decision_and_execution_targets_are_exactly_one_slice_or_candidate() -> None:
    fixture = _fixture()
    fixture["decisions"][0]["candidate_id"] = "61111111-1111-4111-8111-111111111111"
    with pytest.raises(PortfolioOutcomeContractError, match=r"decisions\[0\]"):
        validate_portfolio_outcome_o1_fixture(fixture)

    fixture = _fixture()
    fixture["execution_lineages"][0]["slice_candidate_ids"] = []
    fixture["execution_lineages"][0]["candidate_id"] = (
        "61111111-1111-4111-8111-111111111111"
    )
    fixture["decisions"][0]["slice_id"] = None
    fixture["decisions"][0]["candidate_id"] = "61111111-1111-4111-8111-111111111111"
    fixture["decisions"][0]["side"] = "BUY"
    fixture["execution_lineages"][0]["side"] = "BUY"

    proposals = propose_outcome_matches(
        fixture["decisions"], fixture["execution_lineages"]
    )

    assert proposals[0]["status"] == "MATCH_PROPOSED"


def test_duplicate_broker_order_fill_account_identity_fails_closed() -> None:
    fixture = _fixture()
    duplicate = copy.deepcopy(fixture["execution_lineages"][0])
    duplicate["execution_lineage_id"] = "34444444-4444-4444-8444-444444444444"
    duplicate["outcome_lineage_id"] = "44444444-4444-4444-8444-444444444444"
    fixture["execution_lineages"].append(duplicate)

    with pytest.raises(PortfolioOutcomeContractError, match="broker fill identity"):
        validate_portfolio_outcome_o1_fixture(fixture)
    with pytest.raises(PortfolioOutcomeContractError, match="broker fill identity"):
        propose_outcome_matches(fixture["decisions"], fixture["execution_lineages"])


def test_only_keyed_account_hashes_and_exact_wire_precision_are_accepted() -> None:
    fixture = _fixture()
    fixture["execution_lineages"][0]["account_ref_hash"] = "raw-account-id"

    with pytest.raises(PortfolioOutcomeContractError, match="account_ref_hash"):
        validate_portfolio_outcome_o1_fixture(fixture)

    fixture = _fixture()
    fixture["execution_lineages"][0]["fills"][0]["price"] = "100.0"
    with pytest.raises(PortfolioOutcomeContractError, match="price"):
        validate_portfolio_outcome_o1_fixture(fixture)

    fixture = _fixture()
    fixture["execution_lineages"][0]["fills"][0]["executed_at"] = "2026-08-01T13:40:00Z"
    with pytest.raises(PortfolioOutcomeContractError, match="executed_at"):
        validate_portfolio_outcome_o1_fixture(fixture)


def test_user_events_are_append_only_ordered_and_same_lineage() -> None:
    fixture = _fixture()
    existing = copy.deepcopy(fixture["user_events"][:2])
    original = copy.deepcopy(existing)

    result = append_user_outcome_event(
        existing,
        fixture["user_events"][2],
        decisions=fixture["decisions"],
        execution_lineages=fixture["execution_lineages"],
    )

    assert existing == original
    assert list(result) == fixture["user_events"]

    wrong_lineage = copy.deepcopy(fixture["user_events"][2])
    wrong_lineage["outcome_lineage_id"] = fixture["expected_proposals"][1][
        "outcome_lineage_id"
    ]
    with pytest.raises(PortfolioOutcomeContractError, match="supersedes_event_id"):
        append_user_outcome_event(
            existing,
            wrong_lineage,
            decisions=fixture["decisions"],
            execution_lineages=fixture["execution_lineages"],
        )


def test_append_recomputes_proposals_and_rejects_crafted_decision_binding() -> None:
    fixture = _fixture()
    crafted = copy.deepcopy(fixture["user_events"][2])
    crafted["decision_id"] = "77777777-7777-4777-8777-777777777777"

    with pytest.raises(PortfolioOutcomeContractError, match="known synthetic decision"):
        append_user_outcome_event(
            fixture["user_events"][:2],
            crafted,
            decisions=fixture["decisions"],
            execution_lineages=fixture["execution_lineages"],
        )


def test_event_chain_rejects_time_reversal_and_non_head_supersedes() -> None:
    fixture = _fixture()
    event = copy.deepcopy(fixture["user_events"][2])
    event["created_at"] = fixture["user_events"][1]["created_at"]

    with pytest.raises(PortfolioOutcomeContractError, match="created_at"):
        append_user_outcome_event(
            fixture["user_events"][:2],
            event,
            decisions=fixture["decisions"],
            execution_lineages=fixture["execution_lineages"],
        )

    event = copy.deepcopy(fixture["user_events"][2])
    event["supersedes_event_id"] = fixture["user_events"][0]["outcome_event_id"]
    with pytest.raises(PortfolioOutcomeContractError, match="supersedes_event_id"):
        append_user_outcome_event(
            fixture["user_events"][:2],
            event,
            decisions=fixture["decisions"],
            execution_lineages=fixture["execution_lineages"],
        )


def test_matchable_target_side_is_candidate_buy_or_holding_sell() -> None:
    holding_buy = _fixture()
    holding_buy["decisions"][0]["side"] = "BUY"
    with pytest.raises(PortfolioOutcomeContractError, match=r"decisions\[0\]"):
        validate_portfolio_outcome_o1_fixture(holding_buy)

    holding_buy_execution = _fixture()
    holding_buy_execution["execution_lineages"][0]["side"] = "BUY"
    with pytest.raises(PortfolioOutcomeContractError, match=r"execution_lineages\[0\]"):
        validate_portfolio_outcome_o1_fixture(holding_buy_execution)

    candidate_sell = _fixture()
    candidate_sell["decisions"][0]["slice_id"] = None
    candidate_sell["decisions"][0]["candidate_id"] = (
        "61111111-1111-4111-8111-111111111111"
    )
    with pytest.raises(PortfolioOutcomeContractError, match=r"decisions\[0\]"):
        validate_portfolio_outcome_o1_fixture(candidate_sell)

    candidate_sell_execution = _fixture()
    candidate_sell_execution["execution_lineages"][0]["slice_candidate_ids"] = []
    candidate_sell_execution["execution_lineages"][0]["candidate_id"] = (
        "61111111-1111-4111-8111-111111111111"
    )
    with pytest.raises(PortfolioOutcomeContractError, match=r"execution_lineages\[0\]"):
        validate_portfolio_outcome_o1_fixture(candidate_sell_execution)


def test_confirmation_is_bound_to_proposal_candidates_and_total_quantity() -> None:
    cross_lineage = _fixture()
    cross_lineage["user_events"][0]["decision_id"] = cross_lineage["decisions"][1][
        "decision_id"
    ]
    with pytest.raises(PortfolioOutcomeContractError, match="deterministic proposal"):
        validate_portfolio_outcome_o1_fixture(cross_lineage)

    wrong_quantity = _fixture()
    wrong_quantity["user_events"][0]["confirmed_quantity"] = "9.000000"
    with pytest.raises(PortfolioOutcomeContractError, match=r"user_events\[0\]"):
        validate_portfolio_outcome_o1_fixture(wrong_quantity)

    nonpositive_correction = _fixture()
    nonpositive_correction["user_events"][2]["confirmed_quantity"] = "0.000000"
    with pytest.raises(PortfolioOutcomeContractError, match="confirmed_quantity"):
        validate_portfolio_outcome_o1_fixture(nonpositive_correction)


@pytest.mark.parametrize(
    "reserved_status", ["UNLINKED", "MATCH_PROPOSED", "AMBIGUOUS", "NO_ACTION"]
)
def test_user_events_reject_proposal_only_and_no_action_statuses(
    reserved_status: str,
) -> None:
    fixture = _fixture()
    fixture["user_events"][2]["status"] = reserved_status

    with pytest.raises(
        PortfolioOutcomeContractError, match=r"user_events\[2\]\.status"
    ):
        validate_portfolio_outcome_o1_fixture(fixture)


@pytest.mark.parametrize("terminal_status", ["DISMISSED", "UNKNOWN"])
def test_dismissed_and_unknown_require_null_decision_and_quantity(
    terminal_status: str,
) -> None:
    fixture = _fixture()
    event = copy.deepcopy(fixture["user_events"][2])
    event["status"] = terminal_status

    with pytest.raises(PortfolioOutcomeContractError):
        append_user_outcome_event(
            fixture["user_events"][:2],
            event,
            decisions=fixture["decisions"],
            execution_lineages=fixture["execution_lineages"],
        )

    event["decision_id"] = None
    event["confirmed_quantity"] = None
    appended = append_user_outcome_event(
        fixture["user_events"][:2],
        event,
        decisions=fixture["decisions"],
        execution_lineages=fixture["execution_lineages"],
    )
    assert appended[-1]["status"] == terminal_status


def test_other_feedback_requires_nonempty_private_note() -> None:
    fixture = _fixture()
    fixture["user_events"][2]["feedback_note_private"] = None

    with pytest.raises(PortfolioOutcomeContractError, match="feedback_note_private"):
        validate_portfolio_outcome_o1_fixture(fixture)


def test_public_projection_strictly_rejects_private_fields() -> None:
    fixture = _fixture()
    projection = project_public_outcome_events(fixture["user_events"])

    assert list(projection) == fixture["expected_public_projection"]
    assert validate_public_outcome_projection(list(projection)) == list(projection)
    for private_field in (
        "confirmed_quantity",
        "price",
        "account_ref_hash",
        "broker_order_id",
        "broker_fill_id",
        "feedback_note_private",
    ):
        leaked = copy.deepcopy(fixture["expected_public_projection"])
        leaked[0][private_field] = "PRIVATE"
        with pytest.raises(PortfolioOutcomeContractError, match=private_field):
            validate_public_outcome_projection(leaked)


def test_unknown_fields_and_noncanonical_ids_fail_closed() -> None:
    fixture = _fixture()
    fixture["execution_lineages"][0]["private_note"] = "PRIVATE"
    with pytest.raises(PortfolioOutcomeContractError, match="private_note"):
        validate_portfolio_outcome_o1_fixture(fixture)

    fixture = _fixture()
    fixture["decisions"][0]["decision_id"] = "11111111-1111-4111-8111-11111111111A"
    with pytest.raises(PortfolioOutcomeContractError, match="decision_id"):
        validate_portfolio_outcome_o1_fixture(fixture)


def test_contract_cannot_claim_provider_capability_or_attribution() -> None:
    fixture = _fixture()
    fixture["capability"]["provider_history_state"] = "VERIFIED"
    with pytest.raises(PortfolioOutcomeContractError, match="provider_history_state"):
        validate_portfolio_outcome_o1_fixture(fixture)

    fixture = _fixture()
    fixture["capability"]["performance_attribution"] = "ENABLED"
    with pytest.raises(PortfolioOutcomeContractError, match="performance_attribution"):
        validate_portfolio_outcome_o1_fixture(fixture)


def test_synthetic_fills_must_stay_inside_declared_retention_window() -> None:
    fixture = _fixture()
    fixture["capability"]["retention_window"]["ends_at"] = "2026-08-01T13:39:59.999Z"

    with pytest.raises(PortfolioOutcomeContractError, match="retention window"):
        validate_portfolio_outcome_o1_fixture(fixture)


def test_standalone_json_schema_enforces_private_note_and_positive_decimals() -> None:
    schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
    validator = Draft202012Validator(schema, format_checker=FormatChecker())
    assert not list(validator.iter_errors(_fixture()))

    note_without_reason = _fixture()
    note_without_reason["user_events"][0]["feedback_note_private"] = "PRIVATE"
    assert list(validator.iter_errors(note_without_reason))

    zero_confirmation = _fixture()
    zero_confirmation["user_events"][0]["confirmed_quantity"] = "0.000000"
    assert list(validator.iter_errors(zero_confirmation))

    zero_range = _fixture()
    zero_range["decisions"][0]["price_range"]["minimum"] = "0.000000"
    assert list(validator.iter_errors(zero_range))

    zero_fill = _fixture()
    zero_fill["execution_lineages"][0]["fills"][0]["quantity"] = "0.000000"
    assert list(validator.iter_errors(zero_fill))
