"""A1 domain joins, injected-clock correction replay and private field exclusion."""

import copy
import json
from datetime import datetime
from pathlib import Path

import pytest
from sab.portfolio_mandate.review_projection import project_mandate_review_a1

ROOT = Path(__file__).resolve().parents[1]


def fixture():
    return json.loads(
        (
            ROOT
            / "tests/fixtures/portfolio_mandate/portfolio-mandate-a1.synthetic.json"
        ).read_text()
    )


def test_integrated_versions_slices_authority_and_corrections_replay():
    value = fixture()
    original = copy.deepcopy(value)
    before = project_mandate_review_a1(
        value, as_of=datetime.fromisoformat("2026-08-28T00:23:00Z")
    )
    after = project_mandate_review_a1(
        value, as_of=datetime.fromisoformat("2026-08-28T00:25:00Z")
    )
    fulfillment = value["predicate_authority_core"]["events"][0][
        "predicate_authority_event_id"
    ]
    for early, late in zip(before["rows"], after["rows"], strict=True):
        assert fulfillment in early["current_authority_event_ids"]
        assert fulfillment not in late["current_authority_event_ids"]
        assert late["superseded_event_count"] == 1
        assert late["approval_state"] == "APPROVED"  # A later draft is not activation.
        assert "ALLOCATION_REBASE_REQUIRED" in late["issue_codes"]
        assert late["action"] is None
    assert value == original
    assert after == json.loads(
        (ROOT / "web/fixtures/portfolio-mandate-review.a1.synthetic.json").read_text()
    )


def test_projection_never_treats_future_approval_or_empty_evidence_as_advice():
    value = fixture()
    result = project_mandate_review_a1(
        value, as_of=datetime.fromisoformat("2026-08-27T00:00:00Z")
    )
    assert result["advice_enabled"] is False
    for row in result["rows"]:
        assert "MANDATE_OUTSIDE_EFFECTIVE_WINDOW" in row["issue_codes"]
        assert "CURRENT_PREDICATE_EVIDENCE_MISSING" in row["issue_codes"]
        assert row["current_authority_event_ids"] == []
    serialized = json.dumps(result)
    for field in [
        "account_ref_hash",
        "quantity",
        "thesis",
        "owner_actor_id",
        "source_span",
    ]:
        assert field not in serialized


def test_invalid_snapshot_errors_never_echo_private_values():
    value = fixture()
    value["position_slice_core"]["snapshots"][0]["quantity"] = "PRIVATE_SENTINEL"
    with pytest.raises(ValueError, match=r"^INVALID_A1_REVIEW_INPUT$"):
        project_mandate_review_a1(
            value, as_of=datetime.fromisoformat("2026-08-28T00:25:00Z")
        )
    with pytest.raises(ValueError, match="UTC offset"):
        project_mandate_review_a1(fixture(), as_of=datetime(2026, 8, 28))
