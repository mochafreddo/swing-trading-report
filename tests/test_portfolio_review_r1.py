"""Composite review semantics, source visibility and the default-off RPC boundary."""

import copy
import json
from pathlib import Path
from unittest.mock import Mock
from uuid import NAMESPACE_URL, uuid5

import pytest
from sab.portfolio_mandate.review_policy import (
    _hash,
    compile_portfolio_review_r1,
    read_portfolio_review_r1,
)


def identity(value):
    return str(uuid5(NAMESPACE_URL, value))


def holding():
    value = json.loads(
        Path(
            "tests/fixtures/portfolio_mandate/portfolio-mandate-private-v1-preview.synthetic.json"
        ).read_text()
    )["holdings"][0]
    policy = value["invalidation_policy"]
    policy["special_review_rules"] = []
    condition = {
        "metric": "organic_growth",
        "operator": "<",
        "threshold": 0,
        "unit": "PERCENT",
        "period": "QUARTER",
    }
    policy["deterioration_rule"]["signals"] = [
        {"id": "GROWTH", "description": "Synthetic growth", "conditions": [condition]},
        {
            "id": "MARGIN",
            "description": "Synthetic margin",
            "conditions": [{**condition, "metric": "margin"}],
        },
    ]
    return value


def observation(path, period="2026Q2", value="-1", **changes):
    return {
        "observation_id": identity(path + period + value),
        "rule_path": path,
        "period_key": period,
        "metric": "organic_growth",
        "unit": "PERCENT",
        "observed_value": value,
        "evidence_seal_id": identity("seal"),
        "source_content_sha256": "sha256:" + "c" * 64,
        "source_tier": "PRIMARY",
        "authority": "DETERMINISTIC_PARSER",
        "parser_version": "synthetic-v1",
        "recorded_at": "2026-09-07T00:03:00Z",
        "supersedes_observation_id": None,
        "source_event_time": "2026-08-01T00:00:00Z",
        "sealed_at": "2026-09-07T00:02:00Z",
        "source_instrument_id": identity("instrument"),
        **changes,
    }


def payload():
    document = json.dumps(holding())
    return {
        "schema_version": "portfolio-review-input.r1",
        "read_at": "2026-09-07T00:05:00Z",
        "rows": [
            {
                "mandate_version_id": identity("version"),
                "instrument_id": identity("instrument"),
                "approval_state": "APPROVED",
                "classification_state": "ACTIVE",
                "horizon": "LONG_TERM",
                "approved_at": "2026-09-01T00:00:00Z",
                "effective_from": "2026-09-01T00:00:00Z",
                "effective_to": None,
                "holding_document": document,
                "holding_sha256": _hash(document),
                "source_document_sha256": "sha256:" + "a" * 64,
                "policy_recorded_at": "2026-09-01T00:00:00Z",
                "broker": {
                    "snapshot_version": 1,
                    "captured_at": "2026-09-07T00:00:00Z",
                    "sealed_input_hash": "sha256:" + "b" * 64,
                    "allocation_snapshot_version": 1,
                    "allocation_version": 1,
                    "slices": [
                        {
                            "slice_id": identity("slice"),
                            "eligible": True,
                            "classification_state": "ACTIVE",
                        }
                    ],
                },
                "observations": [
                    observation("hard_triggers/0/0"),
                    observation(
                        "hard_triggers/0/1", metric="operating_margin", value="9"
                    ),
                ],
            }
        ],
    }


def envelope(value):
    raw = json.dumps(value)
    return {"payload": raw, "payload_sha256": _hash(raw)}


def compile_value(value):
    return compile_portfolio_review_r1(
        envelope(value),
        review_period="2026Q2",
        broker_max_age_seconds=600,
        evidence_max_age_seconds=180 * 86400,
    )


def test_all_any_and_partial_knowledge_never_produce_directional_advice():
    value = payload()
    original = copy.deepcopy(value)
    result = compile_value(value)["rows"][0]
    assert result["status"] == "THESIS_INVALIDATED_REVIEW_REQUIRED"
    assert result["action"] is None and value == original
    value["rows"][0]["observations"].pop()
    assert compile_value(value)["rows"][0]["matched_hard_trigger_count"] == 0
    document = holding()
    document["invalidation_policy"]["hard_triggers"][0]["condition_match"] = "ANY"
    raw = json.dumps(document)
    value["rows"][0].update(holding_document=raw, holding_sha256=_hash(raw))
    assert compile_value(value)["rows"][0]["matched_hard_trigger_count"] == 1


def test_deterioration_requires_each_consecutive_quarter_and_enough_signals():
    value = payload()
    row = value["rows"][0]
    row["observations"] = [
        observation(f"signals/{i}/0", period, metric=metric)
        for period in ("2026Q1", "2026Q2")
        for i, metric in enumerate(("organic_growth", "margin"))
    ]
    assert compile_value(value)["rows"][0]["deterioration_confirmed"] is True
    row["observations"].pop()
    assert compile_value(value)["rows"][0]["deterioration_confirmed"] is False
    row["observations"][0]["period_key"] = "2025Q4"
    assert compile_value(value)["rows"][0]["status"] == "REVIEW_REQUIRED"


@pytest.mark.parametrize(
    "change",
    [
        "future",
        "stale",
        "wrong_instrument",
        "wrong_unit",
        "duplicate",
        "rating",
        "unstructured",
        "annual",
    ],
)
def test_uncertain_evidence_cannot_confirm_a_trigger(change):
    value = payload()
    row = value["rows"][0]
    o = row["observations"][0]
    if change == "future":
        o["recorded_at"] = "2026-09-08T00:00:00Z"
    elif change == "stale":
        o["source_event_time"] = "2024-01-01T00:00:00Z"
    elif change == "wrong_instrument":
        o["source_instrument_id"] = identity("another")
    elif change == "wrong_unit":
        o["unit"] = "USD"
    elif change == "duplicate":
        row["observations"].append({**o, "observation_id": identity("duplicate")})
    else:
        document = holding()
        trigger = document["invalidation_policy"]["hard_triggers"][0]
        if change == "rating":
            trigger["conditions"][0]["operator"] = "RATING_BELOW"
        elif change == "annual":
            trigger["conditions"][0]["period"] = "YEAR"
        else:
            trigger.pop("conditions")
        raw = json.dumps(document)
        row.update(holding_document=raw, holding_sha256=_hash(raw))
    assert compile_value(value)["rows"][0]["matched_hard_trigger_count"] == 0


def test_correction_visibility_does_not_resurrect_old_fulfillment():
    value = payload()
    row = value["rows"][0]
    old = row["observations"][0]
    row["observations"].append(
        observation(
            "hard_triggers/0/0",
            value="5",
            supersedes_observation_id=old["observation_id"],
            recorded_at="2026-09-07T00:04:00Z",
        )
    )
    result = compile_value(value)["rows"][0]
    assert result["matched_hard_trigger_count"] == 0
    assert result["superseded_observation_count"] == 1
    value["read_at"] = "2026-09-07T00:03:30Z"
    assert compile_value(value)["rows"][0]["matched_hard_trigger_count"] == 1


@pytest.mark.parametrize(
    "field,value",
    [
        ("approval_state", "DRAFT"),
        ("horizon", "SWING"),
        ("effective_to", "2026-09-06T00:00:00Z"),
        ("broker", None),
        ("holding_document", None),
    ],
)
def test_missing_authority_or_snapshot_blocks_the_whole_row(field, value):
    fixture = payload()
    fixture["rows"][0][field] = value
    assert compile_value(fixture)["rows"][0]["status"] == "BLOCKED"


def test_payload_privacy_digest_and_default_off_single_rpc():
    value = payload()
    rpc = Mock(return_value=envelope(value))
    opts = {
        "review_period": "2026Q2",
        "broker_max_age_seconds": 600,
        "evidence_max_age_seconds": 180 * 86400,
    }
    with pytest.raises(ValueError, match="PORTFOLIO_REVIEW_DISABLED"):
        read_portfolio_review_r1(rpc, [identity("version")], **opts)
    rpc.assert_not_called()
    result = read_portfolio_review_r1(rpc, [identity("version")], enabled=True, **opts)
    rpc.assert_called_once_with(
        "read_portfolio_review_r1", {"p_version_ids": [identity("version")]}
    )
    assert result["advice_enabled"] is False
    assert not any(
        field in json.dumps(result)
        for field in [
            "holding_document",
            "thesis",
            "observed_value",
            "account",
            "source_content",
        ]
    )
    damaged = envelope(value)
    damaged["payload"] += " "
    with pytest.raises(ValueError, match=r"^INVALID_PORTFOLIO_REVIEW_INPUT$"):
        compile_portfolio_review_r1(damaged, **opts)
    rpc.side_effect = ValueError("PRIVATE_SENTINEL")
    with pytest.raises(ValueError, match=r"^PORTFOLIO_REVIEW_UNAVAILABLE$"):
        read_portfolio_review_r1(rpc, [identity("version")], enabled=True, **opts)


def test_frozen_disposable_rpc_reproduces_the_web_projection():
    frozen = json.loads(
        Path(
            "tests/fixtures/portfolio_mandate/portfolio-review-r1.rpc.synthetic.json"
        ).read_text()
    )
    projected = compile_portfolio_review_r1(
        frozen,
        review_period="2026Q2",
        broker_max_age_seconds=600,
        evidence_max_age_seconds=180 * 86400,
    )
    assert projected == json.loads(
        Path("web/fixtures/portfolio-review.r1.synthetic.json").read_text()
    )


@pytest.mark.parametrize("change", ["stale", "future", "allocation", "slice"])
def test_broker_visibility_blocks_before_evaluating_policy(change):
    value = payload()
    broker = value["rows"][0]["broker"]
    if change == "stale":
        broker["captured_at"] = "2025-01-01T00:00:00Z"
    elif change == "future":
        broker["captured_at"] = "2026-09-08T00:00:00Z"
    elif change == "allocation":
        broker["allocation_snapshot_version"] += 1
    else:
        broker["slices"][0]["eligible"] = False
    row = compile_value(value)["rows"][0]
    assert row["status"] == "BLOCKED" and row["matched_hard_trigger_count"] == 0


def test_invalid_correction_lineage_is_rejected_without_private_payload():
    value = payload()
    value["rows"][0]["observations"][0]["supersedes_observation_id"] = identity(
        "missing"
    )
    with pytest.raises(ValueError, match=r"^INVALID_PORTFOLIO_REVIEW_INPUT$"):
        compile_value(value)
