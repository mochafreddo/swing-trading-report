from __future__ import annotations

import copy
import json
from pathlib import Path
from typing import Any

import pytest
from sab.portfolio_mandate.contracts import (
    PortfolioMandateContractError,
    validate_portfolio_mandate_a1_fixture,
)

FIXTURE_PATH = (
    Path(__file__).parent
    / "fixtures"
    / "portfolio_mandate"
    / "portfolio-mandate-a1.synthetic.json"
)


def _fixture() -> dict[str, Any]:
    value = json.loads(FIXTURE_PATH.read_text(encoding="utf-8"))
    assert isinstance(value, dict)
    return value


def test_rn1_c3_001_ticker_reuse_never_binds_identity() -> None:
    fixture = _fixture()

    assert validate_portfolio_mandate_a1_fixture(fixture) == fixture
    aliases = fixture["stable_identity"]["listing_aliases"]
    assert aliases[0]["ticker"] == aliases[1]["ticker"]
    assert aliases[0]["instrument_id"] != aliases[1]["instrument_id"]


def test_rn1_c3_002_alias_outside_validity_window_is_rejected() -> None:
    fixture = _fixture()
    fixture["stable_identity"]["evidence_seals"][0]["source_event_time"] = (
        "2024-12-31T23:59:59Z"
    )

    with pytest.raises(
        PortfolioMandateContractError,
        match=r"stable_identity\.evidence_seals\[0\]\.source_event_time",
    ):
        validate_portfolio_mandate_a1_fixture(fixture)


def test_rn1_c3_006_registry_or_source_mismatch_blocks_packet() -> None:
    fixture = _fixture()
    fixture["stable_identity"]["evidence_seals"][0]["registry_version"] = (
        "synthetic-registry-v0"
    )

    with pytest.raises(
        PortfolioMandateContractError,
        match=r"stable_identity\.evidence_seals\[0\]\.registry_version",
    ):
        validate_portfolio_mandate_a1_fixture(fixture)


def test_rn1_c3_009_alias_is_not_a_binding_key() -> None:
    fixture = _fixture()
    seal = fixture["stable_identity"]["evidence_seals"][0]
    seal["instrument_id"] = seal.pop("ticker")

    with pytest.raises(
        PortfolioMandateContractError,
        match=r"stable_identity\.evidence_seals\[0]",
    ):
        validate_portfolio_mandate_a1_fixture(fixture)


def test_rn1_g006_public_surface_rejects_private_position_fields() -> None:
    fixture = _fixture()
    public_seal = copy.deepcopy(fixture["stable_identity"]["evidence_seals"][0])
    public_seal["account_id"] = "PRIVATE-ACCOUNT"
    fixture["stable_identity"]["evidence_seals"][0] = public_seal

    with pytest.raises(
        PortfolioMandateContractError,
        match=r"stable_identity\.evidence_seals\[0]",
    ):
        validate_portfolio_mandate_a1_fixture(fixture)


def test_rn1_c2_002_stale_expected_version_is_rejected() -> None:
    fixture = _fixture()
    command = fixture["mandate_version_core"]["activation_commands"][0]
    command["expected_mandate_version_id"] = command["draft_mandate_version_id"]

    with pytest.raises(
        PortfolioMandateContractError,
        match=r"mandate_version_core\.activation_commands\[0\]"
        r"\.expected_mandate_version_id",
    ):
        validate_portfolio_mandate_a1_fixture(fixture)


def test_rn1_c2_004_non_user_cannot_activate() -> None:
    fixture = _fixture()
    fixture["mandate_version_core"]["activation_commands"][0]["actor_kind"] = "AI"

    with pytest.raises(
        PortfolioMandateContractError,
        match=r"mandate_version_core\.activation_commands\[0\]\.actor_kind",
    ):
        validate_portfolio_mandate_a1_fixture(fixture)


def test_activation_actor_must_own_the_mandate() -> None:
    fixture = _fixture()
    fixture["mandate_version_core"]["activation_commands"][0]["actor_id"] = (
        "99999999-9999-4999-8999-999999999999"
    )

    with pytest.raises(
        PortfolioMandateContractError,
        match=r"mandate_version_core\.activation_commands\[0\]\.actor_id",
    ):
        validate_portfolio_mandate_a1_fixture(fixture)


def test_rn1_c2_005_incomplete_draft_cannot_activate() -> None:
    fixture = _fixture()
    fixture["mandate_version_core"]["versions"][1]["thesis"] = None

    with pytest.raises(
        PortfolioMandateContractError,
        match=r"mandate_version_core\.activation_commands\[0\]\.draft_mandate_version_id",
    ):
        validate_portfolio_mandate_a1_fixture(fixture)


def test_rn1_c2_009_one_active_approved_version_constraint() -> None:
    fixture = _fixture()
    duplicate = copy.deepcopy(fixture["mandate_version_core"]["versions"][0])
    duplicate["mandate_version_id"] = "99999999-9999-4999-8999-999999999999"
    duplicate["version_number"] = 3
    fixture["mandate_version_core"]["versions"].append(duplicate)

    with pytest.raises(
        PortfolioMandateContractError,
        match=r"mandate_version_core\.versions",
    ):
        validate_portfolio_mandate_a1_fixture(fixture)


def test_rn1_c2_010_activation_is_idempotent() -> None:
    fixture = _fixture()
    fixture["mandate_version_core"]["activation_commands"].append(
        copy.deepcopy(fixture["mandate_version_core"]["activation_commands"][0])
    )

    with pytest.raises(
        PortfolioMandateContractError,
        match=r"mandate_version_core\.activation_commands",
    ):
        validate_portfolio_mandate_a1_fixture(fixture)


def test_rn1_c1_009_rebase_identity_is_idempotent() -> None:
    fixture = _fixture()
    fixture["position_slice_core"]["rebase_commands"].append(
        copy.deepcopy(fixture["position_slice_core"]["rebase_commands"][0])
    )

    with pytest.raises(
        PortfolioMandateContractError,
        match=r"position_slice_core\.rebase_commands",
    ):
        validate_portfolio_mandate_a1_fixture(fixture)


def test_rn1_c1_011_quantity_invariant_failure_rolls_back() -> None:
    fixture = _fixture()
    fixture["position_slice_core"]["slices"][0]["quantity"] = "-0.000001"

    with pytest.raises(
        PortfolioMandateContractError,
        match=r"position_slice_core\.slices\[0\]\.quantity",
    ):
        validate_portfolio_mandate_a1_fixture(fixture)

    fixture = _fixture()
    fixture["position_slice_core"]["slices"][0]["quantity"] = "5.000000"
    with pytest.raises(
        PortfolioMandateContractError,
        match=r"position_slice_core\.allocations\[0\]",
    ):
        validate_portfolio_mandate_a1_fixture(fixture)


def test_rn1_c1_012_static_fixture_rejects_stale_allocation_version() -> None:
    fixture = _fixture()
    fixture["position_slice_core"]["rebase_commands"][0][
        "expected_allocation_version"
    ] = 2

    with pytest.raises(
        PortfolioMandateContractError,
        match=r"position_slice_core\.rebase_commands\[0\]"
        r"\.expected_allocation_version",
    ):
        validate_portfolio_mandate_a1_fixture(fixture)


def test_mandate_and_slices_match_the_exact_broker_instrument() -> None:
    fixture = _fixture()
    fixture["position_slice_core"]["broker_positions"][0]["instrument_id"] = (
        "44444444-4444-4444-8444-444444444444"
    )

    with pytest.raises(
        PortfolioMandateContractError,
        match=r"mandate_version_core\.mandates\[0\]\.broker_position_id",
    ):
        validate_portfolio_mandate_a1_fixture(fixture)


def test_activation_command_binds_current_snapshot_and_allocation() -> None:
    fixture = _fixture()
    fixture["mandate_version_core"]["activation_commands"][0]["allocation_version"] = 2

    with pytest.raises(
        PortfolioMandateContractError,
        match=r"mandate_version_core\.activation_commands\[0\]\.allocation_version",
    ):
        validate_portfolio_mandate_a1_fixture(fixture)


def test_activation_draft_must_supersede_the_exact_expected_version() -> None:
    fixture = _fixture()
    fixture["mandate_version_core"]["versions"][1]["supersedes_version_id"] = None

    with pytest.raises(
        PortfolioMandateContractError,
        match=r"mandate_version_core\.activation_commands\[0\]"
        r"\.draft_mandate_version_id",
    ):
        validate_portfolio_mandate_a1_fixture(fixture)


def test_predicate_event_references_an_approved_exact_definition() -> None:
    fixture = _fixture()
    fixture["predicate_authority_core"]["events"][0]["predicate_id"] = (
        "99999999-9999-4999-8999-999999999999"
    )

    with pytest.raises(
        PortfolioMandateContractError,
        match=r"predicate_authority_core\.events\[0\]\.predicate_id",
    ):
        validate_portfolio_mandate_a1_fixture(fixture)


def test_active_slice_requires_exact_mandate_and_eligibility() -> None:
    fixture = _fixture()
    fixture["position_slice_core"]["slices"][0]["mandate_version_id"] = None
    fixture["position_slice_core"]["slices"][0]["decision_eligible"] = False

    with pytest.raises(
        PortfolioMandateContractError,
        match=r"position_slice_core\.slices\[0\]",
    ):
        validate_portfolio_mandate_a1_fixture(fixture)


def test_activation_requires_a_slice_on_the_expected_version() -> None:
    fixture = _fixture()
    draft_id = fixture["mandate_version_core"]["versions"][1]["mandate_version_id"]
    for position_slice in fixture["position_slice_core"]["slices"]:
        position_slice["mandate_version_id"] = draft_id

    with pytest.raises(
        PortfolioMandateContractError,
        match=r"mandate_version_core\.activation_commands\[0\]"
        r"\.expected_mandate_version_id",
    ):
        validate_portfolio_mandate_a1_fixture(fixture)


def test_predicate_event_requires_an_exact_evidence_seal() -> None:
    fixture = _fixture()
    fixture["predicate_authority_core"]["events"][0]["evidence_seal_id"] = (
        "99999999-9999-4999-8999-999999999999"
    )

    with pytest.raises(
        PortfolioMandateContractError,
        match=r"predicate_authority_core\.events\[0\]\.evidence_seal_id",
    ):
        validate_portfolio_mandate_a1_fixture(fixture)


def test_evidence_seal_ids_are_unique() -> None:
    fixture = _fixture()
    fixture["stable_identity"]["evidence_seals"].append(
        copy.deepcopy(fixture["stable_identity"]["evidence_seals"][0])
    )

    with pytest.raises(
        PortfolioMandateContractError,
        match=r"stable_identity\.evidence_seals",
    ):
        validate_portfolio_mandate_a1_fixture(fixture)


def test_evidence_source_scope_tuples_are_unique() -> None:
    fixture = _fixture()
    duplicate = copy.deepcopy(fixture["stable_identity"]["evidence_seals"][0])
    duplicate["evidence_seal_id"] = "99999999-9999-4999-8999-999999999999"
    fixture["stable_identity"]["evidence_seals"].append(duplicate)

    with pytest.raises(
        PortfolioMandateContractError,
        match=r"stable_identity\.evidence_seals",
    ):
        validate_portfolio_mandate_a1_fixture(fixture)


def test_instrument_scoped_source_cannot_cross_instruments() -> None:
    fixture = _fixture()
    first = fixture["stable_identity"]["evidence_seals"][0]
    second = copy.deepcopy(fixture["stable_identity"]["evidence_seals"][1])
    second["evidence_seal_id"] = "98989898-9898-4898-8898-989898989898"
    second["source_id"] = first["source_id"]
    second["scope"] = "INSTRUMENT"
    fixture["stable_identity"]["evidence_seals"].append(second)

    with pytest.raises(
        PortfolioMandateContractError,
        match=r"stable_identity\.evidence_seals",
    ):
        validate_portfolio_mandate_a1_fixture(fixture)


def test_rebase_command_requires_exact_verified_evidence() -> None:
    fixture = _fixture()
    fixture["position_slice_core"]["rebase_evidence"][0]["cause"] = "AMBIGUOUS_SELL"

    with pytest.raises(
        PortfolioMandateContractError,
        match=r"position_slice_core\.rebase_commands\[0\]\.rebase_evidence_id",
    ):
        validate_portfolio_mandate_a1_fixture(fixture)


def test_rn1_c5_001_verified_parser_event_can_satisfy_predicate() -> None:
    fixture = _fixture()

    assert validate_portfolio_mandate_a1_fixture(fixture) == fixture
    event = fixture["predicate_authority_core"]["events"][0]
    assert event["event_type"] == "PREDICATE_FULFILLED"
    assert event["policy_effect"] == "SELL_ELIGIBLE"


def test_verified_parser_event_must_satisfy_the_approved_numeric_predicate() -> None:
    fixture = _fixture()
    fixture["predicate_authority_core"]["events"][0]["observed_value"] = "99.99"

    with pytest.raises(
        PortfolioMandateContractError,
        match=r"predicate_authority_core\.events\[0\]\.observed_value",
    ):
        validate_portfolio_mandate_a1_fixture(fixture)

    fixture = _fixture()
    fixture["predicate_authority_core"]["events"][0]["observed_metric"] = "REVENUE"
    with pytest.raises(
        PortfolioMandateContractError,
        match=r"predicate_authority_core\.events\[0\]\.observed_value",
    ):
        validate_portfolio_mandate_a1_fixture(fixture)


def test_rn1_c5_002_user_confirmation_requires_full_audit_fields() -> None:
    fixture = _fixture()
    fixture["predicate_authority_core"]["events"][1]["reason"] = None

    with pytest.raises(
        PortfolioMandateContractError,
        match=r"predicate_authority_core\.events\[1\]",
    ):
        validate_portfolio_mandate_a1_fixture(fixture)


def test_user_predicate_actor_must_own_the_mandate() -> None:
    fixture = _fixture()
    fixture["predicate_authority_core"]["events"][1]["actor_id"] = (
        "99999999-9999-4999-8999-999999999999"
    )

    with pytest.raises(
        PortfolioMandateContractError,
        match=r"predicate_authority_core\.events\[1\]\.actor_id",
    ):
        validate_portfolio_mandate_a1_fixture(fixture)


def test_rn1_c5_003_ai_candidate_cannot_create_directional_action() -> None:
    fixture = _fixture()
    fixture["predicate_authority_core"]["events"][2]["policy_effect"] = "SELL_ELIGIBLE"

    with pytest.raises(
        PortfolioMandateContractError,
        match=r"predicate_authority_core\.events\[2\]",
    ):
        validate_portfolio_mandate_a1_fixture(fixture)


def test_predicate_authority_actor_matches_the_producer() -> None:
    fixture = _fixture()
    fixture["predicate_authority_core"]["events"][2]["actor_kind"] = "DETERMINISTIC"

    with pytest.raises(
        PortfolioMandateContractError,
        match=r"predicate_authority_core\.events\[2\]",
    ):
        validate_portfolio_mandate_a1_fixture(fixture)


def test_rn1_c5_004_validator_cannot_assert_semantics() -> None:
    fixture = _fixture()
    fixture["predicate_authority_core"]["events"][3]["event_type"] = (
        "PREDICATE_FULFILLED"
    )

    with pytest.raises(
        PortfolioMandateContractError,
        match=r"predicate_authority_core\.events\[3\]",
    ):
        validate_portfolio_mandate_a1_fixture(fixture)


def test_rn1_c5_005_unknown_parser_surface_fails_to_review() -> None:
    fixture = _fixture()
    fixture["predicate_authority_core"]["events"][0]["structured_surface"] = False

    with pytest.raises(
        PortfolioMandateContractError,
        match=r"predicate_authority_core\.events\[0\]",
    ):
        validate_portfolio_mandate_a1_fixture(fixture)


def test_rn1_c5_006_restated_source_supersedes_fulfillment() -> None:
    fixture = _fixture()
    restatement = fixture["predicate_authority_core"]["events"][4]

    assert restatement["event_type"] == "PREDICATE_SUPERSEDED"
    assert (
        restatement["supersedes_event_id"]
        == fixture["predicate_authority_core"]["events"][0][
            "predicate_authority_event_id"
        ]
    )
    assert validate_portfolio_mandate_a1_fixture(fixture) == fixture


def test_correction_only_supersedes_an_earlier_fulfillment() -> None:
    fixture = _fixture()
    restatement = fixture["predicate_authority_core"]["events"][4]
    restatement["supersedes_event_id"] = fixture["predicate_authority_core"]["events"][
        2
    ]["predicate_authority_event_id"]

    with pytest.raises(
        PortfolioMandateContractError,
        match=r"predicate_authority_core\.events\[4\]\.supersedes_event_id",
    ):
        validate_portfolio_mandate_a1_fixture(fixture)

    fixture = _fixture()
    fixture["predicate_authority_core"]["events"][4]["created_at"] = (
        "2026-08-28T00:19:59Z"
    )
    with pytest.raises(
        PortfolioMandateContractError,
        match=r"predicate_authority_core\.events\[4\]\.supersedes_event_id",
    ):
        validate_portfolio_mandate_a1_fixture(fixture)


def test_provenance_requires_a_structured_span_and_no_supersedes_target() -> None:
    fixture = _fixture()
    fixture["predicate_authority_core"]["events"][3]["source_span"] = None
    with pytest.raises(
        PortfolioMandateContractError,
        match=r"predicate_authority_core\.events\[3\]",
    ):
        validate_portfolio_mandate_a1_fixture(fixture)

    fixture = _fixture()
    fixture["predicate_authority_core"]["events"][2]["supersedes_event_id"] = fixture[
        "predicate_authority_core"
    ]["events"][0]["predicate_authority_event_id"]
    with pytest.raises(
        PortfolioMandateContractError,
        match=r"predicate_authority_core\.events\[2\]",
    ):
        validate_portfolio_mandate_a1_fixture(fixture)


def test_rn1_c5_007_free_text_never_fulfills_predicate() -> None:
    fixture = _fixture()
    candidate = fixture["predicate_authority_core"]["events"][2]
    candidate["structured_surface"] = False
    candidate["free_text_only"] = True
    candidate["source_span"] = None
    candidate["reason"] = "Synthetic natural-language resemblance only."

    with pytest.raises(
        PortfolioMandateContractError,
        match=r"predicate_authority_core\.events\[2\]",
    ):
        validate_portfolio_mandate_a1_fixture(fixture)
