from __future__ import annotations

import asyncio
import copy
import json
from datetime import UTC, datetime
from typing import Any

import pytest
from sab.decision_board.claims import (
    ClaimRequestV0,
    ClaimValidationSucceededV0,
    ClaimValidationV0,
    EntailmentV0,
    validate_claim_v0,
)
from sab.decision_board.compiler import (
    ApprovalStateV0,
    CompilerEvidenceKindV0,
    CompilerEvidenceV0,
    CompilerInputError,
    DecisionCompilerV0,
    DependencyStateV0,
    EntryCompilerItemV0,
    EntrySignalStateV0,
    ExposureStateV0,
    HardExitStateV0,
    HoldingCompilerItemV0,
    ResearchStateV0,
)
from sab.decision_board.contracts import (
    canonical_json_bytes,
    decision_payload_hash,
    validate_decision_payload,
)
from sab.decision_board.instruments import InstrumentRefV0
from sab.decision_board.policy import select_holding_research_v0
from sab.research.contracts import (
    ResearchSourcePolicyV0,
    SourcePurposeV0,
    create_source_candidate_v0,
)
from sab.research.deadline import Deadline
from sab.research.source_safety import create_article_artifact_v0

SEALED_HASH = f"sha256:{'a' * 64}"
PRIVATE_SENTINEL = "account-private-sentinel-4219"


def _instrument(index: int = 1) -> InstrumentRefV0:
    return InstrumentRefV0(
        market="US",
        canonical_ticker=f"SYN{index}.NAS",
        exchange="NASDAQ",
        company_name=f"Synthetic Company {index}",
        identity_source="synthetic-directory",
        identity_version="fixture-v1",
    )


def _entry(index: int = 1, **overrides: object) -> EntryCompilerItemV0:
    values: dict[str, object] = {
        "item_id": f"entry-SYN{index}.NAS",
        "instrument": _instrument(index),
        "item_state": ApprovalStateV0.APPROVED,
        "identity_state": ApprovalStateV0.APPROVED,
        "signal_state": EntrySignalStateV0.READY_ENTER,
        "mandate_state": DependencyStateV0.CURRENT,
        "price_state": DependencyStateV0.CURRENT,
        "exposure_state": ExposureStateV0.PASS,
        "research_state": ResearchStateV0.CLEAR,
        "evidence": (),
    }
    values.update(overrides)
    return EntryCompilerItemV0.create(**values)  # type: ignore[arg-type]


def _holding(index: int = 1, **overrides: object) -> HoldingCompilerItemV0:
    values: dict[str, object] = {
        "item_id": f"holding-SYN{index}.NAS",
        "instrument": _instrument(index),
        "item_state": ApprovalStateV0.APPROVED,
        "identity_state": ApprovalStateV0.APPROVED,
        "hard_exit_state": HardExitStateV0.NONE,
        "broker_state": DependencyStateV0.CURRENT,
        "candle_state": DependencyStateV0.CURRENT,
        "rule_state": DependencyStateV0.CURRENT,
        "research_state": ResearchStateV0.CLEAR,
        "research_priority": index,
        "research_order": f"tie-{index:02d}",
        "evidence": (),
    }
    values.update(overrides)
    return HoldingCompilerItemV0.create(**values)  # type: ignore[arg-type]


def _item(payload: dict[str, object]) -> dict[str, object]:
    items = payload["items"]
    assert isinstance(items, list) and len(items) == 1
    assert isinstance(items[0], dict)
    return items[0]


def _compile_holding(
    items: tuple[HoldingCompilerItemV0, ...], *, max_research_items: int = 5
) -> dict[str, Any]:
    selection = select_holding_research_v0(
        items,
        max_research_items=max_research_items,
    )
    return DecisionCompilerV0.compile_holding(
        items,
        selection=selection,
        sealed_input_hash=SEALED_HASH,
    )


@pytest.mark.parametrize(
    ("overrides", "expected_status", "expected_action", "expected_code"),
    [
        ({}, "DECIDED", "BUY", None),
        (
            {"item_state": ApprovalStateV0.REVIEW},
            "REVIEW",
            None,
            "REVIEW_ITEM_NOT_APPROVED",
        ),
        (
            {"identity_state": ApprovalStateV0.REVIEW},
            "REVIEW",
            None,
            "REVIEW_IDENTITY_NOT_APPROVED",
        ),
        (
            {"mandate_state": DependencyStateV0.MISSING},
            "REVIEW",
            None,
            "REVIEW_MANDATE_MISSING",
        ),
        (
            {"signal_state": EntrySignalStateV0.STALE},
            "REVIEW",
            None,
            "REVIEW_SIGNAL_STALE",
        ),
        (
            {"price_state": DependencyStateV0.AMBIGUOUS},
            "REVIEW",
            None,
            "REVIEW_PRICE_AMBIGUOUS",
        ),
        (
            {"exposure_state": ExposureStateV0.CONFLICTED},
            "REVIEW",
            None,
            "REVIEW_EXPOSURE_CONFLICTED",
        ),
        ({"exposure_state": ExposureStateV0.FAIL}, "DECIDED", "AVOID", None),
        (
            {"research_state": ResearchStateV0.TIMEOUT},
            "REVIEW",
            None,
            "REVIEW_RESEARCH_TIMEOUT",
        ),
    ],
)
def test_entry_truth_table(
    overrides: dict[str, object],
    expected_status: str,
    expected_action: str | None,
    expected_code: str | None,
) -> None:
    payload = DecisionCompilerV0.compile_entry(
        (_entry(**overrides),),  # type: ignore[arg-type]
        sealed_input_hash=SEALED_HASH,
    )
    item = _item(payload)

    assert item["status"] == expected_status
    assert item.get("action") == expected_action
    issues = item["issues"]
    assert isinstance(issues, list)
    codes = [issue["code"] for issue in issues]
    assert (expected_code in codes) if expected_code else not codes


@pytest.mark.parametrize(
    "signal_state",
    [EntrySignalStateV0.ABSENT, EntrySignalStateV0.NOT_READY_ENTER],
)
def test_entry_non_candidate_is_omitted(signal_state: EntrySignalStateV0) -> None:
    payload = DecisionCompilerV0.compile_entry(
        (_entry(signal_state=signal_state),), sealed_input_hash=SEALED_HASH
    )
    assert payload["items"] == []


@pytest.mark.parametrize(
    ("overrides", "expected_status", "expected_action", "expected_code"),
    [
        ({}, "DECIDED", "HOLD", None),
        (
            {"item_state": ApprovalStateV0.REVIEW},
            "REVIEW",
            None,
            "REVIEW_ITEM_NOT_APPROVED",
        ),
        (
            {"identity_state": ApprovalStateV0.REVIEW},
            "REVIEW",
            None,
            "REVIEW_IDENTITY_NOT_APPROVED",
        ),
        (
            {"broker_state": DependencyStateV0.MISSING},
            "REVIEW",
            None,
            "REVIEW_BROKER_MISSING",
        ),
        (
            {"candle_state": DependencyStateV0.STALE},
            "REVIEW",
            None,
            "REVIEW_CANDLE_STALE",
        ),
        (
            {"rule_state": DependencyStateV0.CONFLICTED},
            "REVIEW",
            None,
            "REVIEW_RULE_CONFLICTED",
        ),
        (
            {"research_state": ResearchStateV0.COVERAGE_GAP},
            "REVIEW",
            None,
            "REVIEW_RESEARCH_COVERAGE_GAP",
        ),
        (
            {"research_state": ResearchStateV0.NOT_SELECTED_CAP},
            "REVIEW",
            None,
            "REVIEW_RESEARCH_NOT_SELECTED_CAP",
        ),
        ({"hard_exit_state": HardExitStateV0.HARD_STOP}, "DECIDED", "SELL", None),
        ({"hard_exit_state": HardExitStateV0.CONFIRMED_EXIT}, "DECIDED", "SELL", None),
    ],
)
def test_holding_truth_table(
    overrides: dict[str, object],
    expected_status: str,
    expected_action: str | None,
    expected_code: str | None,
) -> None:
    item = _item(
        _compile_holding(
            (_holding(**overrides),),  # type: ignore[arg-type]
        )
    )
    assert item["status"] == expected_status
    assert item.get("action") == expected_action
    issues = item["issues"]
    assert isinstance(issues, list)
    codes = [issue["code"] for issue in issues]
    assert (expected_code in codes) if expected_code else not codes


def test_hard_exit_with_stale_deterministic_input_is_review() -> None:
    item = _item(
        _compile_holding(
            (
                _holding(
                    hard_exit_state=HardExitStateV0.HARD_STOP,
                    candle_state=DependencyStateV0.STALE,
                ),
            ),
        )
    )
    assert item["status"] == "REVIEW"
    assert "action" not in item


class _Verifier:
    def __init__(self, entailment: EntailmentV0) -> None:
        self.entailment = entailment

    async def verify(self, request: object, **_kwargs: object) -> object:
        text = request.article_text  # type: ignore[attr-defined]
        return {
            "entailment": self.entailment.value,
            "supporting_span": text,
            "supporting_location": {
                "kind": "TEXT_OFFSETS",
                "start": 0,
                "end": len(text),
            },
            "verifier_version": "synthetic-v1",
        }


def _evidence(
    *,
    instrument: InstrumentRefV0 | None = None,
    entailment: EntailmentV0 = EntailmentV0.SUPPORTED,
    action_changing: bool = True,
    kind: CompilerEvidenceKindV0 = CompilerEvidenceKindV0.MATERIAL_ADVERSE,
    claim_id: str = "claim-adverse-1",
) -> CompilerEvidenceV0:
    trusted = instrument or _instrument()
    policy = ResearchSourcePolicyV0()
    source = create_source_candidate_v0(
        instrument=trusted,
        title="Synthetic adverse event",
        canonical_url="https://evidence.example/adverse",
        publisher="Synthetic Wire",
        published_at=datetime(2026, 8, 9, tzinfo=UTC),
        purpose=SourcePurposeV0.ACTION_CHANGING,
    )
    article = create_article_artifact_v0(
        source=source,
        final_url="https://evidence.example/adverse-final",
        normalized_text="Synthetic material event.",
        policy=policy,
    )
    request = ClaimRequestV0(
        claim_id=claim_id,
        instrument=trusted,
        claim_text="A synthetic material adverse event occurred.",
        action_changing=action_changing,
    )
    result = asyncio.run(
        validate_claim_v0(
            request,
            article,
            expected_source=source,
            policy=policy,
            verifier=_Verifier(entailment),
            deadline=Deadline.start(),
        )
    )
    assert type(result) is ClaimValidationSucceededV0
    return CompilerEvidenceV0.create(
        kind=kind,
        validation=result.validation,
        request=request,
        article=article,
        expected_source=source,
        policy=policy,
    )


def test_only_supported_action_changing_material_adverse_changes_entry_action() -> None:
    adverse = _evidence()
    item = _item(
        DecisionCompilerV0.compile_entry(
            (_entry(evidence=(adverse,)),), sealed_input_hash=SEALED_HASH
        )
    )
    assert item["action"] == "AVOID"
    assert item["evidence"] == [
        {
            "claim_id": "claim-adverse-1",
            "role": "OPPOSING",
            "source_url": "https://evidence.example/adverse-final",
            "publisher": "Synthetic Wire",
            "published_at": "2026-08-09T00:00:00Z",
            "freshness": "WITHIN_POLICY",
            "citation_label": "Synthetic adverse event",
        }
    ]

    for evidence, expected_references in (
        (_evidence(entailment=EntailmentV0.CONTRADICTED), []),
        (_evidence(entailment=EntailmentV0.UNCLEAR), []),
        (_evidence(action_changing=False), []),
        (
            _evidence(kind=CompilerEvidenceKindV0.SUPPORTIVE),
            [
                {
                    "claim_id": "claim-adverse-1",
                    "role": "SUPPORTING",
                    "source_url": "https://evidence.example/adverse-final",
                    "publisher": "Synthetic Wire",
                    "published_at": "2026-08-09T00:00:00Z",
                    "freshness": "WITHIN_POLICY",
                    "citation_label": "Synthetic adverse event",
                }
            ],
        ),
    ):
        item = _item(
            DecisionCompilerV0.compile_entry(
                (_entry(evidence=(evidence,)),), sealed_input_hash=SEALED_HASH
            )
        )
        assert item["action"] == "BUY"
        assert item["evidence"] == expected_references


def test_collision_precedence_and_hard_sell_non_override() -> None:
    adverse = _evidence()
    entry = _item(
        DecisionCompilerV0.compile_entry(
            (
                _entry(
                    exposure_state=ExposureStateV0.FAIL,
                    research_state=ResearchStateV0.STALE,
                    evidence=(adverse,),
                ),
            ),
            sealed_input_hash=SEALED_HASH,
        )
    )
    assert entry["action"] == "AVOID"

    conflicted = _item(
        DecisionCompilerV0.compile_entry(
            (_entry(research_state=ResearchStateV0.CONFLICTED, evidence=(adverse,)),),
            sealed_input_hash=SEALED_HASH,
        )
    )
    assert conflicted["status"] == "REVIEW"

    stale_required = _item(
        DecisionCompilerV0.compile_entry(
            (
                _entry(
                    price_state=DependencyStateV0.STALE,
                    exposure_state=ExposureStateV0.FAIL,
                ),
            ),
            sealed_input_hash=SEALED_HASH,
        )
    )
    assert stale_required["status"] == "REVIEW"

    for research_state in (
        ResearchStateV0.TIMEOUT,
        ResearchStateV0.NOT_SELECTED_CAP,
        ResearchStateV0.CONFLICTED,
    ):
        holding = _item(
            _compile_holding(
                (
                    _holding(
                        hard_exit_state=HardExitStateV0.HARD_STOP,
                        research_state=research_state,
                        evidence=(adverse,),
                    ),
                ),
            )
        )
        assert holding["action"] == "SELL"

    supportive = _evidence(kind=CompilerEvidenceKindV0.SUPPORTIVE)
    hard_sell = _item(
        _compile_holding(
            (
                _holding(
                    item_state=ApprovalStateV0.REVIEW,
                    identity_state=ApprovalStateV0.REVIEW,
                    hard_exit_state=HardExitStateV0.CONFIRMED_EXIT,
                    evidence=(supportive,),
                ),
            ),
        )
    )
    assert hard_sell["action"] == "SELL"
    assert hard_sell["evidence"] == [
        {
            "claim_id": "claim-adverse-1",
            "role": "SUPPORTING",
            "source_url": "https://evidence.example/adverse-final",
            "publisher": "Synthetic Wire",
            "published_at": "2026-08-09T00:00:00Z",
            "freshness": "WITHIN_POLICY",
            "citation_label": "Synthetic adverse event",
        }
    ]


def test_identity_review_precedes_entry_non_candidate_omission() -> None:
    item = _item(
        DecisionCompilerV0.compile_entry(
            (
                _entry(
                    identity_state=ApprovalStateV0.REVIEW,
                    signal_state=EntrySignalStateV0.ABSENT,
                ),
            ),
            sealed_input_hash=SEALED_HASH,
        )
    )
    assert item["status"] == "REVIEW"


def test_material_adverse_holding_is_review_and_item_failures_are_isolated() -> None:
    adverse = _evidence()
    payload = _compile_holding(
        (_holding(2), _holding(1, evidence=(adverse,))),
    )
    items = payload["items"]
    assert [item["instrument"]["canonical_ticker"] for item in items] == [
        "SYN1.NAS",
        "SYN2.NAS",
    ]  # type: ignore[index]
    assert [item["status"] for item in items] == ["REVIEW", "DECIDED"]  # type: ignore[index]


def test_research_cap_is_separate_and_sixth_hard_sell_is_compiled() -> None:
    holdings = tuple(
        _holding(
            index,
            hard_exit_state=(
                HardExitStateV0.HARD_STOP if index == 6 else HardExitStateV0.NONE
            ),
        )
        for index in range(1, 7)
    )
    selection = select_holding_research_v0(holdings, max_research_items=5)
    assert selection.selected_item_ids == tuple(
        f"holding-SYN{index}.NAS" for index in range(1, 6)
    )
    assert selection.states[-1] == (
        "holding-SYN6.NAS",
        ResearchStateV0.NOT_SELECTED_CAP,
    )

    compiled = DecisionCompilerV0.compile_holding(
        holdings,
        selection=selection,
        sealed_input_hash=SEALED_HASH,
    )
    assert len(compiled["items"]) == 6
    assert compiled["items"][5]["action"] == "SELL"  # type: ignore[index]


@pytest.mark.parametrize("limit", [0, 3, 5])
def test_research_selection_limit_ties_and_permutation(limit: int) -> None:
    holdings = (
        _holding(3, research_priority=1, research_order="same"),
        _holding(1, research_priority=1, research_order="same"),
        _holding(2, research_priority=1, research_order="same"),
    )
    first = select_holding_research_v0(holdings, max_research_items=limit)
    second = select_holding_research_v0(
        tuple(reversed(holdings)), max_research_items=limit
    )
    assert first == second
    assert first.selected_item_ids == tuple(
        f"holding-SYN{index}.NAS" for index in range(1, min(limit, 3) + 1)
    )


def test_research_selection_rejects_over_cap_and_duplicate_items() -> None:
    with pytest.raises(CompilerInputError):
        select_holding_research_v0((_holding(),), max_research_items=6)
    with pytest.raises(CompilerInputError):
        select_holding_research_v0((_holding(), _holding()))


def test_deterministic_order_dedupe_replay_and_contract_validation() -> None:
    first_evidence = _evidence(claim_id="claim-z")
    duplicate = first_evidence
    second_evidence = _evidence(claim_id="claim-a")
    inputs = (
        _entry(2),
        _entry(1, evidence=(first_evidence, duplicate, second_evidence)),
    )
    first = DecisionCompilerV0.compile_entry(inputs, sealed_input_hash=SEALED_HASH)
    replay = DecisionCompilerV0.compile_entry(
        tuple(reversed(inputs)), sealed_input_hash=SEALED_HASH
    )

    assert first == replay == validate_decision_payload(copy.deepcopy(first))
    assert canonical_json_bytes(first) == canonical_json_bytes(replay)
    assert decision_payload_hash(first) == decision_payload_hash(replay)
    assert first["items"][0]["evidence"] == [  # type: ignore[index]
        {
            "claim_id": "claim-a",
            "role": "OPPOSING",
            "source_url": "https://evidence.example/adverse-final",
            "publisher": "Synthetic Wire",
            "published_at": "2026-08-09T00:00:00Z",
            "freshness": "WITHIN_POLICY",
            "citation_label": "Synthetic adverse event",
        },
        {
            "claim_id": "claim-z",
            "role": "OPPOSING",
            "source_url": "https://evidence.example/adverse-final",
            "publisher": "Synthetic Wire",
            "published_at": "2026-08-09T00:00:00Z",
            "freshness": "WITHIN_POLICY",
            "citation_label": "Synthetic adverse event",
        },
    ]


def test_duplicate_identity_and_invalid_hash_fail_closed() -> None:
    with pytest.raises(CompilerInputError):
        DecisionCompilerV0.compile_entry(
            (_entry(), _entry()), sealed_input_hash=SEALED_HASH
        )
    with pytest.raises(CompilerInputError):
        DecisionCompilerV0.compile_entry((_entry(),), sealed_input_hash="not-a-hash")
    with pytest.raises(ValueError):
        _entry(2, item_id="entry-SYN1.NAS")
    with pytest.raises(ValueError):
        _entry(1, item_id="entry-SYN2.NAS")


def test_factory_rejects_non_lane_item_identity() -> None:
    with pytest.raises(ValueError) as exc_info:
        _entry(item_id=PRIVATE_SENTINEL)
    assert PRIVATE_SENTINEL not in str(exc_info.value)
    with pytest.raises(ValueError):
        _entry(item_id="entry-account-123")


def test_t5_wrong_binding_raw_subclass_and_mutation_cannot_change_action() -> None:
    trusted = _instrument()
    issued = _evidence(instrument=trusted, claim_id="claim-original")
    wrong_request = _evidence(instrument=trusted, claim_id="claim-other")
    wrong_article = _evidence(instrument=trusted, claim_id="claim-wrong-article")
    wrong_source = _evidence(instrument=trusted, claim_id="claim-wrong-source")
    wrong_policy = _evidence(instrument=trusted, claim_id="claim-wrong-policy")
    object.__setattr__(wrong_article.article, "normalized_text", "changed article")
    object.__setattr__(wrong_source.expected_source, "publisher", "Changed Wire")
    object.__setattr__(wrong_policy.policy, "freshness_hours", 1)
    mismatches = (
        CompilerEvidenceV0.create(
            kind=CompilerEvidenceKindV0.MATERIAL_ADVERSE,
            validation=issued.validation,
            request=wrong_request.request,
            article=issued.article,
            expected_source=issued.expected_source,
            policy=issued.policy,
        ),
        CompilerEvidenceV0.create(
            kind=CompilerEvidenceKindV0.MATERIAL_ADVERSE,
            validation=issued.validation,
            request=issued.request,
            article=wrong_article.article,
            expected_source=issued.expected_source,
            policy=issued.policy,
        ),
        CompilerEvidenceV0.create(
            kind=CompilerEvidenceKindV0.MATERIAL_ADVERSE,
            validation=issued.validation,
            request=issued.request,
            article=issued.article,
            expected_source=wrong_source.expected_source,
            policy=issued.policy,
        ),
        CompilerEvidenceV0.create(
            kind=CompilerEvidenceKindV0.MATERIAL_ADVERSE,
            validation=issued.validation,
            request=issued.request,
            article=issued.article,
            expected_source=issued.expected_source,
            policy=wrong_policy.policy,
        ),
        CompilerEvidenceV0.create(
            kind=CompilerEvidenceKindV0.MATERIAL_ADVERSE,
            validation={"claim_id": "claim-dict", "entailment": "SUPPORTED"},
            request=issued.request,
            article=issued.article,
            expected_source=issued.expected_source,
            policy=issued.policy,
        ),
        CompilerEvidenceV0.create(
            kind=CompilerEvidenceKindV0.MATERIAL_ADVERSE,
            validation=object.__new__(ClaimValidationV0),
            request=issued.request,
            article=issued.article,
            expected_source=issued.expected_source,
            policy=issued.policy,
        ),
    )
    for evidence in mismatches:
        item = _item(
            DecisionCompilerV0.compile_entry(
                (_entry(evidence=(evidence,)),), sealed_input_hash=SEALED_HASH
            )
        )
        assert item["action"] == "BUY"
        assert item["evidence"] == []

    class ForgedValidation(ClaimValidationV0):
        pass

    forged = CompilerEvidenceV0.create(
        kind=CompilerEvidenceKindV0.MATERIAL_ADVERSE,
        validation=object.__new__(ForgedValidation),
        request=issued.request,
        article=issued.article,
        expected_source=issued.expected_source,
        policy=issued.policy,
    )
    assert (
        _item(
            DecisionCompilerV0.compile_entry(
                (_entry(evidence=(forged,)),), sealed_input_hash=SEALED_HASH
            )
        )["action"]
        == "BUY"
    )

    object.__setattr__(issued.validation, "supporting_span", "mutated")
    assert (
        _item(
            DecisionCompilerV0.compile_entry(
                (_entry(evidence=(issued,)),), sealed_input_hash=SEALED_HASH
            )
        )["action"]
        == "BUY"
    )


def test_mutated_raw_and_subclassed_inputs_are_rejected() -> None:
    item = _entry()
    object.__setattr__(item, "item_id", "mutated")
    with pytest.raises(CompilerInputError):
        DecisionCompilerV0.compile_entry((item,), sealed_input_hash=SEALED_HASH)

    raw = object.__new__(EntryCompilerItemV0)
    with pytest.raises(CompilerInputError):
        DecisionCompilerV0.compile_entry((raw,), sealed_input_hash=SEALED_HASH)

    class ForgedEntry(EntryCompilerItemV0):
        pass

    forged = object.__new__(ForgedEntry)
    with pytest.raises(CompilerInputError):
        DecisionCompilerV0.compile_entry((forged,), sealed_input_hash=SEALED_HASH)

    raw_evidence = object.__new__(CompilerEvidenceV0)
    with pytest.raises(CompilerInputError):
        DecisionCompilerV0.compile_entry(
            (_entry(evidence=(raw_evidence,)),), sealed_input_hash=SEALED_HASH
        )


def test_privacy_and_no_side_effect_projection(monkeypatch: pytest.MonkeyPatch) -> None:
    import socket
    import subprocess
    import urllib.request

    def forbidden(*_args: object, **_kwargs: object) -> object:
        pytest.fail("compiler attempted a forbidden side effect")

    monkeypatch.setattr("builtins.open", forbidden)
    monkeypatch.setattr(socket, "create_connection", forbidden)
    monkeypatch.setattr(subprocess, "run", forbidden)
    monkeypatch.setattr(urllib.request, "urlopen", forbidden)
    payload = DecisionCompilerV0.compile_entry(
        (_entry(),), sealed_input_hash=SEALED_HASH
    )
    rendered = json.dumps(payload, ensure_ascii=False)
    assert PRIVATE_SENTINEL not in rendered
    assert set(payload) == {"run_kind", "sealed_input_hash", "items"}


class _EqualStateText(str):
    pass


def _equal_enum_mutation(value: object, mutation: str) -> object:
    raw_value = value.value  # type: ignore[attr-defined]
    if mutation == "raw-string":
        return raw_value
    if mutation == "string-subclass":
        return _EqualStateText(raw_value)
    return str.__new__(type(value), raw_value)  # type: ignore[type-var]


@pytest.mark.parametrize(
    ("field", "original"),
    [
        ("item_state", ApprovalStateV0.REVIEW),
        ("identity_state", ApprovalStateV0.REVIEW),
        ("signal_state", EntrySignalStateV0.MISSING),
        ("mandate_state", DependencyStateV0.STALE),
        ("price_state", DependencyStateV0.AMBIGUOUS),
        ("exposure_state", ExposureStateV0.FAIL),
        ("research_state", ResearchStateV0.TIMEOUT),
    ],
)
@pytest.mark.parametrize(
    "mutation", ["raw-string", "string-subclass", "fresh-equal-enum"]
)
def test_entry_rejects_equal_but_noncanonical_state_mutation(
    field: str, original: object, mutation: str
) -> None:
    item = _entry(**{field: original})  # type: ignore[arg-type]
    object.__setattr__(item, field, _equal_enum_mutation(original, mutation))

    with pytest.raises(CompilerInputError):
        DecisionCompilerV0.compile_entry((item,), sealed_input_hash=SEALED_HASH)


@pytest.mark.parametrize(
    ("field", "original"),
    [
        ("item_state", ApprovalStateV0.REVIEW),
        ("identity_state", ApprovalStateV0.REVIEW),
        ("hard_exit_state", HardExitStateV0.NONE),
        ("broker_state", DependencyStateV0.STALE),
        ("candle_state", DependencyStateV0.AMBIGUOUS),
        ("rule_state", DependencyStateV0.CONFLICTED),
        ("research_state", ResearchStateV0.TIMEOUT),
    ],
)
@pytest.mark.parametrize(
    "mutation", ["raw-string", "string-subclass", "fresh-equal-enum"]
)
def test_holding_rejects_equal_but_noncanonical_state_mutation(
    field: str, original: object, mutation: str
) -> None:
    item = _holding(**{field: original})  # type: ignore[arg-type]
    object.__setattr__(item, field, _equal_enum_mutation(original, mutation))

    with pytest.raises(CompilerInputError):
        _compile_holding((item,))


@pytest.mark.parametrize(
    "mutation", ["raw-string", "string-subclass", "fresh-equal-enum"]
)
def test_evidence_rejects_equal_but_noncanonical_kind_mutation(mutation: str) -> None:
    evidence = _evidence()
    object.__setattr__(
        evidence,
        "kind",
        _equal_enum_mutation(CompilerEvidenceKindV0.MATERIAL_ADVERSE, mutation),
    )

    with pytest.raises(CompilerInputError):
        DecisionCompilerV0.compile_entry(
            (_entry(evidence=(evidence,)),), sealed_input_hash=SEALED_HASH
        )


def test_factory_rejects_fresh_equal_exact_enum() -> None:
    fresh = str.__new__(ApprovalStateV0, ApprovalStateV0.REVIEW.value)

    with pytest.raises(TypeError):
        _entry(item_state=fresh)


def test_holding_selection_cannot_authorize_a_compiler_subset() -> None:
    holdings = tuple(_holding(index) for index in range(1, 7))
    selection = select_holding_research_v0(holdings, max_research_items=5)

    with pytest.raises(CompilerInputError):
        DecisionCompilerV0.compile_holding(
            holdings[:5],
            selection=selection,
            sealed_input_hash=SEALED_HASH,
        )


def test_holding_selection_result_mutation_is_rejected() -> None:
    holdings = tuple(_holding(index) for index in range(1, 3))
    selection = select_holding_research_v0(holdings, max_research_items=2)
    object.__setattr__(
        selection,
        "selected_item_ids",
        tuple(reversed(selection.selected_item_ids)),
    )

    with pytest.raises(CompilerInputError):
        DecisionCompilerV0.compile_holding(
            holdings,
            selection=selection,
            sealed_input_hash=SEALED_HASH,
        )


@pytest.mark.parametrize(
    "mutation", ["raw-string", "string-subclass", "fresh-equal-enum"]
)
def test_holding_selection_rejects_noncanonical_state_mutation(mutation: str) -> None:
    holdings = (_holding(),)
    selection = select_holding_research_v0(holdings, max_research_items=0)
    item_id, state = selection.states[0]
    object.__setattr__(
        selection,
        "states",
        ((item_id, _equal_enum_mutation(state, mutation)),),
    )

    with pytest.raises(CompilerInputError):
        DecisionCompilerV0.compile_holding(
            holdings,
            selection=selection,
            sealed_input_hash=SEALED_HASH,
        )


def test_holding_selection_rejects_raw_result_and_changed_universe() -> None:
    holdings = (_holding(1), _holding(2))
    selection = select_holding_research_v0(holdings, max_research_items=1)

    with pytest.raises(CompilerInputError):
        DecisionCompilerV0.compile_holding(
            (_holding(1), _holding(2, broker_state=DependencyStateV0.STALE)),
            selection=selection,
            sealed_input_hash=SEALED_HASH,
        )
    with pytest.raises(CompilerInputError):
        DecisionCompilerV0.compile_holding(
            holdings,
            selection=object.__new__(type(selection)),
            sealed_input_hash=SEALED_HASH,
        )


def test_holding_selection_binding_is_permutation_stable() -> None:
    holdings = (_holding(2), _holding(1))
    selection = select_holding_research_v0(holdings, max_research_items=1)

    first = DecisionCompilerV0.compile_holding(
        holdings,
        selection=selection,
        sealed_input_hash=SEALED_HASH,
    )
    replay = DecisionCompilerV0.compile_holding(
        tuple(reversed(holdings)),
        selection=selection,
        sealed_input_hash=SEALED_HASH,
    )

    assert first == replay
    assert first["items"][1]["status"] == "REVIEW"


def test_selected_research_outcome_can_update_without_changing_universe() -> None:
    initial = (_holding(1), _holding(2))
    selection = select_holding_research_v0(initial, max_research_items=1)
    final = (
        _holding(1, research_state=ResearchStateV0.TIMEOUT),
        _holding(2),
    )

    payload = DecisionCompilerV0.compile_holding(
        final,
        selection=selection,
        sealed_input_hash=SEALED_HASH,
    )

    assert [item["status"] for item in payload["items"]] == ["REVIEW", "REVIEW"]


class _EvilOrderingText(str):
    def encode(self, *_args: object, **_kwargs: object) -> bytes:
        raise AssertionError("untrusted encode must never run")

    def __lt__(self, _other: object) -> bool:
        raise AssertionError("untrusted comparison must never run")


class _EvilPriority(int):
    def __lt__(self, _other: object) -> bool:
        raise AssertionError("untrusted comparison must never run")


def test_entry_rejects_equal_item_id_subclass_before_ordering() -> None:
    first = _entry(1)
    second = _entry(2)
    object.__setattr__(first, "item_id", _EvilOrderingText(first.item_id))

    with pytest.raises(CompilerInputError):
        DecisionCompilerV0.compile_entry(
            (second, first),
            sealed_input_hash=SEALED_HASH,
        )


@pytest.mark.parametrize(
    ("field", "mutated"),
    [
        ("item_id", "holding-SYN1.NAS"),
        ("research_order", "tie-01"),
    ],
)
def test_holding_rejects_equal_text_subclass_before_selection(
    field: str, mutated: str
) -> None:
    holding = _holding(1)
    object.__setattr__(holding, field, _EvilOrderingText(mutated))

    with pytest.raises(CompilerInputError):
        select_holding_research_v0((holding,), max_research_items=1)


@pytest.mark.parametrize("mutated", [True, _EvilPriority(1)])
def test_holding_rejects_equal_nonexact_priority_before_selection(
    mutated: object,
) -> None:
    holding = _holding(1, research_priority=1)
    object.__setattr__(holding, "research_priority", mutated)

    with pytest.raises(CompilerInputError):
        select_holding_research_v0((holding, _holding(2)), max_research_items=1)


@pytest.mark.parametrize(
    ("field", "mutation"),
    [
        ("item_id", "evil-text"),
        ("item_id", "wrong-lane"),
        ("item_id", "wrong-ticker"),
        ("item_id", "bad-grammar"),
        ("research_order", "evil-text"),
        ("research_order", "bad-grammar"),
        ("research_priority", "evil-int"),
        ("research_priority", "bool"),
    ],
)
def test_holding_compile_rejects_ordering_scalar_mutation_after_selection(
    field: str, mutation: str
) -> None:
    holdings = (_holding(1), _holding(2))
    selection = select_holding_research_v0(holdings, max_research_items=1)
    mutated: object
    if field == "item_id":
        mutated = {
            "evil-text": _EvilOrderingText("holding-SYN1.NAS"),
            "wrong-lane": "entry-SYN1.NAS",
            "wrong-ticker": "holding-SYN2.NAS",
            "bad-grammar": "holding-SYN1 NAS",
        }[mutation]
    elif field == "research_order":
        mutated = (
            _EvilOrderingText("tie-01") if mutation == "evil-text" else "unsafe order"
        )
    else:
        mutated = _EvilPriority(1) if mutation == "evil-int" else True
    object.__setattr__(holdings[0], field, mutated)

    with pytest.raises(CompilerInputError):
        DecisionCompilerV0.compile_holding(
            holdings,
            selection=selection,
            sealed_input_hash=SEALED_HASH,
        )


@pytest.mark.parametrize(
    ("factory", "overrides"),
    [
        (_entry, {"item_id": _EvilOrderingText("entry-SYN1.NAS")}),
        (_holding, {"item_id": _EvilOrderingText("holding-SYN1.NAS")}),
        (_holding, {"research_order": _EvilOrderingText("tie-01")}),
        (_holding, {"research_priority": _EvilPriority(1)}),
        (_holding, {"research_priority": True}),
    ],
)
def test_factories_reject_nonexact_ordering_scalars(
    factory: object, overrides: dict[str, object]
) -> None:
    with pytest.raises((TypeError, ValueError)):
        factory(**overrides)  # type: ignore[operator]


@pytest.mark.parametrize(
    ("factory", "field", "mutated"),
    [
        (_entry, "item_id", "holding-SYN1.NAS"),
        (_entry, "item_id", "entry-SYN2.NAS"),
        (_entry, "item_id", "entry-SYN1 NAS"),
        (_holding, "item_id", "entry-SYN1.NAS"),
        (_holding, "item_id", "holding-SYN2.NAS"),
        (_holding, "item_id", "holding-SYN1 NAS"),
        (_holding, "research_order", "unsafe order"),
    ],
)
def test_invocation_rejects_lane_binding_and_grammar_mutation(
    factory: object, field: str, mutated: object
) -> None:
    item = factory()  # type: ignore[operator]
    object.__setattr__(item, field, mutated)

    with pytest.raises(CompilerInputError):
        if type(item) is EntryCompilerItemV0:
            DecisionCompilerV0.compile_entry((item,), sealed_input_hash=SEALED_HASH)
        else:
            select_holding_research_v0((item,), max_research_items=1)
