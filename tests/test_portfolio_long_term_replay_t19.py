from __future__ import annotations

import copy
import hashlib
import json
from datetime import datetime
from pathlib import Path
from typing import Any

import pytest
from sab.portfolio_mandate.historical_replay import (
    HistoricalReplayContractError,
    replay_historical_cadence_t19,
    validate_historical_replay_candidate_t19,
)

FIXTURE_PATH = (
    Path(__file__).parent
    / "fixtures"
    / "portfolio_mandate"
    / "portfolio-long-term-replay-t19.candidate.json"
)


def _fixture(*, approved: bool = False) -> dict[str, Any]:
    value = json.loads(FIXTURE_PATH.read_text(encoding="utf-8"))
    assert isinstance(value, dict)
    if not approved:
        value["gate_state"] = "CANDIDATE_NOT_APPROVED_NO_PRODUCTION_ADVICE"
        value["approval_signature"] = None
    return value


def test_t19_candidate_contract_has_twelve_cases_and_four_fake_clock_cadences() -> None:
    candidate = validate_historical_replay_candidate_t19(_fixture())

    assert candidate["gate_state"] == "CANDIDATE_NOT_APPROVED_NO_PRODUCTION_ADVICE"
    assert candidate["approval_signature"] is None
    assert len(candidate["cases"]) == 12
    assert len(candidate["cadences"]) == 4

    replayed: list[str] = []
    for cadence in candidate["cadences"]:
        now = datetime.fromisoformat(cadence["scheduled_for"].replace("Z", "+00:00"))

        def fake_clock(now: datetime = now) -> datetime:
            return now

        result = replay_historical_cadence_t19(candidate, clock=fake_clock)
        replayed.extend(decision["case_id"] for decision in result["decisions"])
        assert result["gate_state"] == candidate["gate_state"]

    assert sorted(replayed) == sorted(case["case_id"] for case in candidate["cases"])


def test_t19_rejects_source_span_hash_and_identity_drift() -> None:
    span_drift = _fixture()
    span_drift["cases"][0]["source"]["supporting_span"] += " drift"
    with pytest.raises(HistoricalReplayContractError, match="content_sha256"):
        validate_historical_replay_candidate_t19(span_drift)

    identity_drift = _fixture()
    identity_drift["cases"][0]["issuer"]["cik"] = "0000000000"
    with pytest.raises(HistoricalReplayContractError, match="source_url"):
        validate_historical_replay_candidate_t19(identity_drift)

    parser_drift = _fixture()
    parser_drift["cases"][0]["source"]["parser_version"] = "other-parser.v1"
    with pytest.raises(HistoricalReplayContractError, match="parser_version"):
        validate_historical_replay_candidate_t19(parser_drift)


@pytest.mark.parametrize(
    ("evidence_state", "expected_action"),
    [
        ("STALE", "BLOCK_STALE"),
        ("CONFLICTING", "BLOCK_CONFLICT"),
        ("INSUFFICIENT", "BLOCK_INSUFFICIENT"),
    ],
)
def test_t19_fail_closed_evidence_precedence(
    evidence_state: str, expected_action: str
) -> None:
    candidate = _fixture()
    case = candidate["cases"][0]
    case["evidence_state"] = evidence_state
    case["expected_action_set"] = [expected_action]

    validated = validate_historical_replay_candidate_t19(candidate)

    assert validated["cases"][0]["expected_action_set"] == [expected_action]


def test_t19_ai_candidate_cannot_be_promoted_to_sell_or_fulfilled() -> None:
    candidate = _fixture()
    case = candidate["cases"][0]
    case["authority"] = "AI_RESEARCH"
    case["predicate_result"] = "FULFILLED"
    case["expected_action_set"] = ["SELL"]

    with pytest.raises(HistoricalReplayContractError, match="AI_RESEARCH"):
        validate_historical_replay_candidate_t19(candidate)


def test_t19_rejects_any_result_outside_the_frozen_action_set() -> None:
    candidate = _fixture()
    candidate["cases"][0]["expected_action_set"] = ["BUY"]

    with pytest.raises(HistoricalReplayContractError, match="frozen_action_set"):
        validate_historical_replay_candidate_t19(candidate)


def test_t19_rejects_future_generation_and_duplicate_cadence_identity() -> None:
    future_generated = _fixture()
    future_generated["generated_at"] = future_generated["cadences"][0]["scheduled_for"]
    with pytest.raises(HistoricalReplayContractError, match="generated_at"):
        validate_historical_replay_candidate_t19(future_generated)

    duplicate_cadence = _fixture()
    duplicate_cadence["cadences"][1]["cadence_id"] = duplicate_cadence["cadences"][0][
        "cadence_id"
    ]
    with pytest.raises(HistoricalReplayContractError, match="cadence_id"):
        validate_historical_replay_candidate_t19(duplicate_cadence)


def test_t19_validation_does_not_mutate_the_candidate_manifest() -> None:
    candidate = _fixture()
    before = copy.deepcopy(candidate)

    validate_historical_replay_candidate_t19(candidate)

    assert candidate == before


def test_t19_user_approval_binds_the_existing_manifest_and_replays_only() -> None:
    manifest = _fixture(approved=True)
    approved = validate_historical_replay_candidate_t19(manifest)
    assert approved["approval_signature"]["production_advice_authorized"] is False
    payload = {
        key: value
        for key, value in approved.items()
        if key not in {"gate_state", "approval_signature"}
    }
    digest = hashlib.sha256(
        json.dumps(
            payload, sort_keys=True, ensure_ascii=False, separators=(",", ":")
        ).encode()
    ).hexdigest()
    assert digest == "ec82f8c11132d121893d9512d3b88a11fe69868c7e47c3e2825855eacdd6973e"
    for cadence in approved["cadences"]:
        now = datetime.fromisoformat(cadence["scheduled_for"].replace("Z", "+00:00"))

        def fake_clock(now: datetime = now) -> datetime:
            return now

        result = replay_historical_cadence_t19(approved, clock=fake_clock)
        assert result["gate_state"] == "APPROVED_REPLAY_ONLY_NO_PRODUCTION_ADVICE"
        assert all(
            not {"BUY", "HOLD", "SELL"}.intersection(item["expected_action_set"])
            for item in result["decisions"]
        )
    assert manifest == approved


@pytest.mark.parametrize(
    "field", ["reason", "source", "expected_action_set", "approval_text", "sha256"]
)
def test_t19_signed_manifest_rejects_unapproved_changes(field: str) -> None:
    manifest = _fixture(approved=True)
    if field in {"approval_text", "sha256"}:
        manifest["approval_signature"][field] += " changed"
    elif field == "source":
        manifest["cases"][0]["source"]["supporting_span"] += " changed"
    elif field == "expected_action_set":
        manifest["cases"][0][field] = ["REVIEW_REQUIRED"]
    else:
        manifest["cases"][0][field] += " changed"
    with pytest.raises(
        HistoricalReplayContractError, match=r"approval_signature\.sha256"
    ):
        validate_historical_replay_candidate_t19(manifest)


def test_t19_approval_state_and_production_boundary_fail_closed() -> None:
    for change in (
        "missing_signature",
        "unapproved_state",
        "production_advice",
        "early_record",
    ):
        manifest = _fixture(approved=True)
        if change == "missing_signature":
            manifest["approval_signature"] = None
        elif change == "unapproved_state":
            manifest["gate_state"] = "CANDIDATE_NOT_APPROVED_NO_PRODUCTION_ADVICE"
        elif change == "production_advice":
            manifest["approval_signature"]["production_advice_authorized"] = True
        else:
            manifest["approval_signature"]["recorded_at"] = "2000-01-01T00:00:00Z"
        with pytest.raises(HistoricalReplayContractError, match="approval_signature"):
            validate_historical_replay_candidate_t19(manifest)
