from __future__ import annotations

import asyncio
import copy
import gc
import json
import weakref
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path

import pytest
import sab.decision_board.claims as claim_module
from jsonschema import (  # type: ignore[import-untyped]
    Draft202012Validator,
    FormatChecker,
)
from sab.decision_board.claims import (
    ClaimRequestV0,
    ClaimValidationFailedV0,
    ClaimValidationSucceededV0,
    ClaimValidationTimedOutV0,
    ClaimValidationV0,
    ClaimVerifierTimeoutError,
    EntailmentV0,
    is_action_change_eligible_v0,
    validate_claim_v0,
)
from sab.decision_board.contracts import validate_claim_validation
from sab.decision_board.instruments import InstrumentRefV0
from sab.research.contracts import (
    ResearchSourcePolicyV0,
    SourceCandidateV0,
    SourcePurposeV0,
    create_source_candidate_v0,
)
from sab.research.deadline import Deadline
from sab.research.source_safety import (
    ArticleArtifactV0,
    create_article_artifact_v0,
)

ROOT = Path(__file__).parents[1]
RECORDED_PATH = (
    Path(__file__).parent
    / "fixtures"
    / "decision_board"
    / "claim-verifier-recorded.json"
)
PRIVATE_SENTINEL = "account-private-sentinel-9917"


def _recorded() -> dict[str, object]:
    value = json.loads(RECORDED_PATH.read_text(encoding="utf-8"))
    assert isinstance(value, dict)
    return value


def _instrument(**overrides: str) -> InstrumentRefV0:
    values = {
        "market": "US",
        "canonical_ticker": "AUR.NAS",
        "exchange": "NASDAQ",
        "company_name": "Aurora Synthetic Systems",
        "identity_source": "synthetic-directory",
        "identity_version": "fixture-2026-08-09",
    }
    values.update(overrides)
    return InstrumentRefV0(**values)


def _source(
    instrument: InstrumentRefV0 | None = None,
    *,
    published_at: datetime | None = datetime(2026, 8, 9, 1, 2, 3, tzinfo=UTC),
) -> SourceCandidateV0:
    return create_source_candidate_v0(
        instrument=instrument or _instrument(),
        title="Synthetic quarterly update",
        canonical_url="https://evidence.example/aurora/update",
        publisher="Synthetic Wire",
        published_at=published_at,
        purpose=SourcePurposeV0.ACTION_CHANGING,
    )


def _article(
    source: SourceCandidateV0 | None = None,
    policy: ResearchSourcePolicyV0 | None = None,
) -> ArticleArtifactV0:
    recorded = _recorded()
    return create_article_artifact_v0(
        source=source or _source(),
        final_url="https://evidence.example/aurora/final-update",
        normalized_text=str(recorded["article_text"]),
        policy=policy or ResearchSourcePolicyV0(),
    )


def _article_with_text(
    source: SourceCandidateV0,
    policy: ResearchSourcePolicyV0,
    *,
    text: str,
    final_url: str,
) -> ArticleArtifactV0:
    return create_article_artifact_v0(
        source=source,
        final_url=final_url,
        normalized_text=text,
        policy=policy,
    )


def _request(
    instrument: InstrumentRefV0 | None = None,
    *,
    action_changing: bool = True,
) -> ClaimRequestV0:
    return ClaimRequestV0(
        claim_id="claim-aurora-guidance",
        instrument=instrument or _instrument(),
        claim_text="Aurora raised its synthetic guidance.",
        action_changing=action_changing,
    )


class _Clock:
    def __init__(self, now: float = 100.0) -> None:
        self.now = now

    def __call__(self) -> float:
        return self.now


class _RecordedVerifier:
    def __init__(
        self,
        payload: object,
        *,
        before_return: Callable[[], None] | None = None,
        error: BaseException | None = None,
    ) -> None:
        self.payload = payload
        self.before_return = before_return
        self.error = error
        self.calls: list[tuple[dict[str, object], Deadline, float]] = []

    async def verify(
        self,
        request: object,
        *,
        deadline: Deadline,
        timeout: float,
    ) -> object:
        self.calls.append((request.to_public_dict(), deadline, timeout))  # type: ignore[attr-defined]
        if self.before_return is not None:
            self.before_return()
        if self.error is not None:
            raise self.error
        return self.payload


def _response(entailment: str = "SUPPORTED") -> dict[str, object]:
    recorded = _recorded()
    responses = recorded["responses"]
    assert isinstance(responses, dict)
    value = responses[entailment]
    assert isinstance(value, dict)
    return copy.deepcopy(value)


def _run(
    verifier: object,
    *,
    request: ClaimRequestV0 | None = None,
    article: ArticleArtifactV0 | None = None,
    source: SourceCandidateV0 | None = None,
    policy: ResearchSourcePolicyV0 | None = None,
    deadline: Deadline | None = None,
    operation_timeout_seconds: float = 10.0,
) -> object:
    trusted_policy = policy or ResearchSourcePolicyV0()
    trusted_source = source or _source()
    trusted_article = article or _article(trusted_source, trusted_policy)
    return asyncio.run(
        validate_claim_v0(
            request or _request(trusted_source.instrument),
            trusted_article,
            expected_source=trusted_source,
            policy=trusted_policy,
            verifier=verifier,  # type: ignore[arg-type]
            deadline=deadline or Deadline.start(),
            operation_timeout_seconds=operation_timeout_seconds,
        )
    )


@pytest.mark.parametrize("entailment", ["SUPPORTED", "CONTRADICTED", "UNCLEAR"])
def test_recorded_entailments_seal_with_exact_local_span(entailment: str) -> None:
    verifier = _RecordedVerifier(_response(entailment))

    result = _run(verifier)

    assert type(result) is ClaimValidationSucceededV0
    validation = result.validation
    payload = _response(entailment)
    location = payload["supporting_location"]
    assert isinstance(location, dict)
    assert validation.entailment is EntailmentV0(entailment)
    assert validation.supporting_span == payload["supporting_span"]
    assert validation.supporting_location.start == location["start"]
    assert validation.supporting_location.end == location["end"]


def test_repeated_span_is_bound_to_returned_half_open_offsets() -> None:
    first = _run(_RecordedVerifier(_response("SUPPORTED")))
    second = _run(_RecordedVerifier(_response("CONTRADICTED")))

    assert type(first) is ClaimValidationSucceededV0
    assert type(second) is ClaimValidationSucceededV0
    assert first.validation.supporting_span == second.validation.supporting_span
    assert first.validation.supporting_location.start == 0
    assert second.validation.supporting_location.start == 22


@pytest.mark.parametrize(
    ("start", "end", "span"),
    [
        pytest.param(21, 0, "Aurora beat guidance.", id="reversed"),
        pytest.param(0, 0, "Aurora beat guidance.", id="zero-length"),
        pytest.param(-1, 20, "Aurora beat guidance.", id="negative"),
        pytest.param(0, 67, "Aurora beat guidance.", id="out-of-range"),
        pytest.param(0, 20, "Aurora beat guidance.", id="off-by-one"),
        pytest.param(44, 67, "Café demand is stable.", id="unicode-byte-offset"),
        pytest.param(44, 66, "Café demand is stable.", id="normalization-mismatch"),
        pytest.param(44, 66, "café demand is stable.", id="case-mismatch"),
        pytest.param(44, 66, " Café demand is stable. ", id="whitespace-mismatch"),
    ],
)
def test_invalid_exact_span_variants_fail_closed(
    start: int, end: int, span: str
) -> None:
    payload = _response("SUPPORTED")
    payload["supporting_span"] = span
    payload["supporting_location"] = {
        "kind": "TEXT_OFFSETS",
        "start": start,
        "end": end,
    }

    result = _run(_RecordedVerifier(payload))

    assert type(result) is ClaimValidationFailedV0
    assert result.code == "VERIFIER_RESULT_MALFORMED"


@pytest.mark.parametrize(
    "mutation",
    [
        pytest.param({"source_url": "https://forged.example/private"}, id="source"),
        pytest.param({"article_content_hash": f"sha256:{'0' * 64}"}, id="hash"),
        pytest.param({"instrument": _instrument().to_public_dict()}, id="instrument"),
        pytest.param({"status": "SUPPORTED"}, id="status-wrapper"),
        pytest.param({"result": "SUPPORTED"}, id="result-wrapper"),
    ],
)
def test_verifier_cannot_add_authority_or_unknown_fields(
    mutation: dict[str, object],
) -> None:
    payload = _response()
    payload.update(mutation)

    result = _run(_RecordedVerifier(payload))

    assert type(result) is ClaimValidationFailedV0
    assert result.code == "VERIFIER_RESULT_MALFORMED"


@pytest.mark.parametrize(
    ("field", "value"),
    [
        pytest.param("entailment", "supported", id="lowercase-entailment"),
        pytest.param("entailment", True, id="boolean-entailment"),
        pytest.param("verifier_version", "", id="empty-version"),
        pytest.param("verifier_version", "private\nversion", id="control-version"),
        pytest.param("verifier_version", "v" * 129, id="long-version"),
    ],
)
def test_entailment_and_verifier_version_are_strict(field: str, value: object) -> None:
    payload = _response()
    payload[field] = value

    result = _run(_RecordedVerifier(payload))

    assert type(result) is ClaimValidationFailedV0
    assert result.code == "VERIFIER_RESULT_MALFORMED"


def test_stale_article_hash_is_rejected_before_verifier_call() -> None:
    policy = ResearchSourcePolicyV0()
    source = _source()
    article = _article(source, policy)
    object.__setattr__(article, "content_hash", f"sha256:{'0' * 64}")
    verifier = _RecordedVerifier(_response())

    result = _run(verifier, article=article, source=source, policy=policy)

    assert type(result) is ClaimValidationFailedV0
    assert result.code == "ARTICLE_INVALID"
    assert verifier.calls == []


@pytest.mark.parametrize("target", ["request", "article", "source", "instrument"])
def test_invocation_inputs_mutated_during_verification_fail_against_baselines(
    target: str,
) -> None:
    policy = ResearchSourcePolicyV0()
    source = _source()
    article = _article(source, policy)
    request = _request(source.instrument)

    def mutate() -> None:
        if target == "request":
            object.__setattr__(request, "claim_text", "mutated public claim")
        elif target == "article":
            object.__setattr__(article, "normalized_text", "mutated article")
        elif target == "source":
            object.__setattr__(source, "publisher", "Mutated Wire")
        else:
            object.__setattr__(request.instrument, "company_name", "Mutated Company")

    result = _run(
        _RecordedVerifier(_response(), before_return=mutate),
        request=request,
        article=article,
        source=source,
        policy=policy,
    )

    assert type(result) is ClaimValidationFailedV0
    assert result.code in {"CLAIM_INPUT_INVALID", "ARTICLE_INVALID"}


def test_request_mutated_before_invocation_is_not_promoted_to_a_new_baseline() -> None:
    request = _request()
    object.__setattr__(request, "claim_text", "mutated before invocation")
    verifier = _RecordedVerifier(_response())

    result = _run(verifier, request=request)

    assert type(result) is ClaimValidationFailedV0
    assert result.code == "CLAIM_INPUT_INVALID"
    assert verifier.calls == []


def test_full_instrument_identity_must_match_even_when_ticker_matches() -> None:
    article_instrument = _instrument(company_name="Different Synthetic Company")
    policy = ResearchSourcePolicyV0()
    source = _source(article_instrument)
    article = _article(source, policy)
    verifier = _RecordedVerifier(_response())

    result = _run(
        verifier,
        request=_request(_instrument()),
        article=article,
        source=source,
        policy=policy,
    )

    assert type(result) is ClaimValidationFailedV0
    assert result.code == "ARTICLE_INVALID"
    assert verifier.calls == []


def test_verifier_receives_only_public_deterministic_fields_and_local_authority() -> (
    None
):
    source = _source()
    policy = ResearchSourcePolicyV0()
    article = _article(source, policy)
    verifier = _RecordedVerifier(_response())

    result = _run(verifier, source=source, article=article, policy=policy)

    assert type(result) is ClaimValidationSucceededV0
    public_request, _deadline, _timeout = verifier.calls[0]
    assert set(public_request) == {
        "claim_id",
        "claim_text",
        "instrument",
        "article_content_hash",
        "article_text",
    }
    assert public_request["instrument"] == source.instrument.to_public_dict()
    assert public_request["article_content_hash"] == article.content_hash
    assert public_request["article_text"] == article.normalized_text
    assert PRIVATE_SENTINEL not in json.dumps(public_request, ensure_ascii=False)


def test_shared_deadline_is_forwarded_and_timeout_is_clamped_to_remaining() -> None:
    clock = _Clock()
    deadline = Deadline.start(10.0, monotonic=clock)
    clock.now = 103.0
    verifier = _RecordedVerifier(_response())

    result = _run(
        verifier,
        deadline=deadline,
        operation_timeout_seconds=9.0,
    )

    assert type(result) is ClaimValidationSucceededV0
    _request_payload, seen_deadline, timeout = verifier.calls[0]
    assert seen_deadline is deadline
    assert timeout == 7.0


def test_operational_timeout_is_typed_per_claim_review_outcome() -> None:
    result = _run(
        _RecordedVerifier(
            _response(),
            error=ClaimVerifierTimeoutError("synthetic timeout"),
        )
    )

    assert type(result) is ClaimValidationTimedOutV0
    assert result.code == "CLAIM_TIMEOUT"
    assert result.claim_id == "claim-aurora-guidance"
    assert result.instrument == _instrument()
    assert type(result.instrument) is InstrumentRefV0


def test_deadline_expiry_precedes_typed_verifier_timeout() -> None:
    clock = _Clock()
    deadline = Deadline.start(5.0, monotonic=clock)

    def expire() -> None:
        clock.now = 105.0

    result = _run(
        _RecordedVerifier(
            _response(),
            before_return=expire,
            error=ClaimVerifierTimeoutError("must not win"),
        ),
        deadline=deadline,
    )

    assert type(result) is ClaimValidationTimedOutV0
    assert result.code == "DEADLINE_EXPIRED"


def test_clock_rollback_precedes_typed_verifier_timeout_as_failed() -> None:
    clock = _Clock()
    deadline = Deadline.start(5.0, monotonic=clock)

    def rollback() -> None:
        clock.now = 99.0

    result = _run(
        _RecordedVerifier(
            _response(),
            before_return=rollback,
            error=ClaimVerifierTimeoutError("must not win"),
        ),
        deadline=deadline,
    )

    assert type(result) is ClaimValidationFailedV0
    assert result.code == "DEADLINE_INVARIANT"


def test_unexpected_clock_error_becomes_typed_failed() -> None:
    class FailingClock(_Clock):
        def __init__(self) -> None:
            super().__init__()
            self.calls = 0

        def __call__(self) -> float:
            self.calls += 1
            if self.calls > 1:
                raise RuntimeError("synthetic clock failure")
            return self.now

    deadline = Deadline.start(5.0, monotonic=FailingClock())

    result = _run(_RecordedVerifier(_response()), deadline=deadline)

    assert type(result) is ClaimValidationFailedV0
    assert result.code == "DEADLINE_INVARIANT"


def test_deadline_expiry_precedes_synchronous_verifier_error() -> None:
    clock = _Clock()
    deadline = Deadline.start(5.0, monotonic=clock)

    class SynchronousFailure:
        def verify(self, *args: object, **kwargs: object) -> object:
            del args, kwargs
            clock.now = 105.0
            raise RuntimeError("synthetic synchronous failure")

    result = _run(SynchronousFailure(), deadline=deadline)

    assert type(result) is ClaimValidationTimedOutV0
    assert result.code == "DEADLINE_EXPIRED"


def test_unexpected_verifier_error_is_failed_not_unclear() -> None:
    result = _run(_RecordedVerifier(_response(), error=RuntimeError(PRIVATE_SENTINEL)))

    assert type(result) is ClaimValidationFailedV0
    assert result.code == "VERIFIER_FAILED"
    assert PRIVATE_SENTINEL not in str(result)


def test_verifier_post_return_payload_alias_mutation_fails_closed() -> None:
    payload = _response()

    class MutatingClock(_Clock):
        def __init__(self) -> None:
            super().__init__()
            self.calls = 0

        def __call__(self) -> float:
            self.calls += 1
            if self.calls == 3:
                payload["source_url"] = "https://forged.example/private"
            return self.now

    clock = MutatingClock()
    deadline = Deadline.start(10.0, monotonic=clock)

    result = _run(_RecordedVerifier(payload), deadline=deadline)

    assert type(result) is ClaimValidationFailedV0
    assert result.code == "VERIFIER_RESULT_MALFORMED"


@pytest.mark.parametrize(
    ("action_changing", "entailment", "expected"),
    [
        (True, "SUPPORTED", True),
        (True, "CONTRADICTED", False),
        (True, "UNCLEAR", False),
        (False, "SUPPORTED", False),
        (False, "CONTRADICTED", False),
        (False, "UNCLEAR", False),
    ],
)
def test_action_change_eligibility_truth_table(
    action_changing: bool, entailment: str, expected: bool
) -> None:
    policy = ResearchSourcePolicyV0()
    source = _source()
    article = _article(source, policy)
    request = _request(source.instrument, action_changing=action_changing)
    result = _run(
        _RecordedVerifier(_response(entailment)),
        request=request,
        article=article,
        source=source,
        policy=policy,
    )
    assert type(result) is ClaimValidationSucceededV0

    eligible = is_action_change_eligible_v0(
        result.validation,
        request=request,
        article=article,
        expected_source=source,
        policy=policy,
    )

    assert eligible is expected


def test_raw_subclass_and_mutated_sealed_values_are_never_eligible() -> None:
    policy = ResearchSourcePolicyV0()
    source = _source()
    article = _article(source, policy)
    request = _request(source.instrument)
    result = _run(
        _RecordedVerifier(_response()),
        request=request,
        article=article,
        source=source,
        policy=policy,
    )
    assert type(result) is ClaimValidationSucceededV0

    raw = object.__new__(ClaimValidationV0)

    class ForgedValidation(ClaimValidationV0):
        pass

    forged = object.__new__(ForgedValidation)
    for slot in ClaimValidationV0.__slots__:
        if slot == "__weakref__":
            continue
        object.__setattr__(forged, slot, getattr(result.validation, slot))
    object.__setattr__(result.validation, "supporting_span", "forged")

    assert not is_action_change_eligible_v0(
        raw,
        request=request,
        article=article,
        expected_source=source,
        policy=policy,
    )
    assert not is_action_change_eligible_v0(
        forged,
        request=request,
        article=article,
        expected_source=source,
        policy=policy,
    )
    assert not is_action_change_eligible_v0(
        result.validation,
        request=request,
        article=article,
        expected_source=source,
        policy=policy,
    )


def test_request_mutation_after_sealing_cannot_keep_action_eligibility() -> None:
    policy = ResearchSourcePolicyV0()
    source = _source()
    article = _article(source, policy)
    request = _request(source.instrument)
    result = _run(
        _RecordedVerifier(_response()),
        request=request,
        article=article,
        source=source,
        policy=policy,
    )
    assert type(result) is ClaimValidationSucceededV0
    object.__setattr__(request, "claim_text", "mutated after sealing")

    assert not is_action_change_eligible_v0(
        result.validation,
        request=request,
        article=article,
        expected_source=source,
        policy=policy,
    )


def test_context_only_supported_issuance_rejects_new_action_request() -> None:
    policy = ResearchSourcePolicyV0()
    source = _source()
    article = _article(source, policy)
    original = _request(source.instrument, action_changing=False)
    result = _run(
        _RecordedVerifier(_response()),
        request=original,
        article=article,
        source=source,
        policy=policy,
    )
    assert type(result) is ClaimValidationSucceededV0
    substitute = _request(source.instrument, action_changing=True)

    assert not is_action_change_eligible_v0(
        result.validation,
        request=substitute,
        article=article,
        expected_source=source,
        policy=policy,
    )


def test_issuance_rejects_fresh_request_with_changed_claim_text() -> None:
    policy = ResearchSourcePolicyV0()
    source = _source()
    article = _article(source, policy)
    original = _request(source.instrument)
    result = _run(
        _RecordedVerifier(_response()),
        request=original,
        article=article,
        source=source,
        policy=policy,
    )
    assert type(result) is ClaimValidationSucceededV0
    substitute = ClaimRequestV0(
        claim_id=original.claim_id,
        instrument=original.instrument,
        claim_text="Aurora lowered its synthetic guidance.",
        action_changing=True,
    )

    assert not is_action_change_eligible_v0(
        result.validation,
        request=substitute,
        article=article,
        expected_source=source,
        policy=policy,
    )


def test_issuance_rejects_coherent_other_source_article_and_validation() -> None:
    policy = ResearchSourcePolicyV0()
    original_source = _source()
    original_article = _article(original_source, policy)
    request = _request(original_source.instrument)
    result = _run(
        _RecordedVerifier(_response()),
        request=request,
        article=original_article,
        source=original_source,
        policy=policy,
    )
    assert type(result) is ClaimValidationSucceededV0
    other_source = create_source_candidate_v0(
        instrument=request.instrument,
        title="Different synthetic update",
        canonical_url="https://evidence.example/aurora/different",
        publisher="Different Synthetic Wire",
        published_at=datetime(2026, 8, 9, 2, 3, 4, tzinfo=UTC),
        purpose=SourcePurposeV0.ACTION_CHANGING,
    )
    other_article = _article_with_text(
        other_source,
        policy,
        text="Aurora cut guidance. Synthetic demand weakened.",
        final_url="https://evidence.example/aurora/different-final",
    )
    validation = result.validation
    object.__setattr__(validation, "source_url", other_article.final_url)
    object.__setattr__(validation, "publisher", other_source.publisher)
    object.__setattr__(validation, "published_at", other_source.published_at)
    object.__setattr__(validation, "article_content_hash", other_article.content_hash)
    object.__setattr__(validation, "supporting_span", "Aurora cut guidance.")
    object.__setattr__(validation.supporting_location, "start", 0)
    object.__setattr__(validation.supporting_location, "end", 20)

    assert not is_action_change_eligible_v0(
        validation,
        request=request,
        article=other_article,
        expected_source=other_source,
        policy=policy,
    )


def test_contradicted_issuance_cannot_be_mutated_to_supported() -> None:
    policy = ResearchSourcePolicyV0()
    source = _source()
    article = _article(source, policy)
    request = _request(source.instrument)
    result = _run(
        _RecordedVerifier(_response("CONTRADICTED")),
        request=request,
        article=article,
        source=source,
        policy=policy,
    )
    assert type(result) is ClaimValidationSucceededV0
    object.__setattr__(result.validation, "entailment", EntailmentV0.SUPPORTED)

    assert not is_action_change_eligible_v0(
        result.validation,
        request=request,
        article=article,
        expected_source=source,
        policy=policy,
    )


def test_issued_span_location_cannot_move_to_another_exact_occurrence() -> None:
    policy = ResearchSourcePolicyV0()
    source = _source()
    article = _article(source, policy)
    request = _request(source.instrument)
    result = _run(
        _RecordedVerifier(_response()),
        request=request,
        article=article,
        source=source,
        policy=policy,
    )
    assert type(result) is ClaimValidationSucceededV0
    object.__setattr__(result.validation.supporting_location, "start", 22)
    object.__setattr__(result.validation.supporting_location, "end", 43)

    assert not is_action_change_eligible_v0(
        result.validation,
        request=request,
        article=article,
        expected_source=source,
        policy=policy,
    )


def test_serializer_rejects_mutated_issued_validation() -> None:
    result = _run(_RecordedVerifier(_response()))
    assert type(result) is ClaimValidationSucceededV0
    object.__setattr__(result.validation.supporting_location, "start", 22)
    object.__setattr__(result.validation.supporting_location, "end", 43)

    with pytest.raises(ValueError, match="unchanged issued value"):
        result.validation.to_public_dict()


def test_serializer_rejects_raw_and_subclass_values_with_issued_fields() -> None:
    result = _run(_RecordedVerifier(_response()))
    assert type(result) is ClaimValidationSucceededV0

    class ForgedValidation(ClaimValidationV0):
        pass

    for forged_type in (ClaimValidationV0, ForgedValidation):
        forged = object.__new__(forged_type)
        for slot in ClaimValidationV0.__slots__:
            if slot == "__weakref__":
                continue
            object.__setattr__(forged, slot, getattr(result.validation, slot))
        with pytest.raises(ValueError, match="unchanged issued value"):
            forged.to_public_dict()


def test_issuance_registry_stores_alias_free_deep_snapshots() -> None:
    result = _run(_RecordedVerifier(_response()))
    assert type(result) is ClaimValidationSucceededV0

    record = claim_module._SEALED_VALIDATIONS[id(result.validation)]

    assert type(record).__name__ == "_ClaimIssuanceRecordV0"
    assert record.reference() is result.validation
    assert type(record.validation_snapshot) is tuple
    assert type(record.validation_serialization) is bytes
    assert type(record.request_snapshot) is tuple
    assert type(record.source_snapshot) is tuple
    assert type(record.article_snapshot) is tuple
    assert type(record.policy_snapshot) is tuple
    assert type(record.verifier_output_snapshot) is tuple


def test_issuance_registry_weakref_cleanup_has_no_strong_reference_leak() -> None:
    result = _run(_RecordedVerifier(_response()))
    assert type(result) is ClaimValidationSucceededV0
    validation = result.validation
    validation_id = id(validation)
    reference = weakref.ref(validation)
    assert validation_id in claim_module._SEALED_VALIDATIONS

    del validation
    del result
    gc.collect()

    assert reference() is None
    assert validation_id not in claim_module._SEALED_VALIDATIONS


def test_registry_identity_check_rejects_wrong_record_at_same_lookup_key() -> None:
    first = _run(_RecordedVerifier(_response()))
    second = _run(_RecordedVerifier(_response()))
    assert type(first) is ClaimValidationSucceededV0
    assert type(second) is ClaimValidationSucceededV0
    first_record = claim_module._SEALED_VALIDATIONS[id(first.validation)]
    second_key = id(second.validation)
    second_record = claim_module._SEALED_VALIDATIONS[second_key]
    claim_module._SEALED_VALIDATIONS[second_key] = first_record
    try:
        with pytest.raises(ValueError, match="unchanged issued value"):
            second.validation.to_public_dict()
    finally:
        claim_module._SEALED_VALIDATIONS[second_key] = second_record


def test_serialization_is_direct_allowlist_and_matches_task1_contract_and_schema() -> (
    None
):
    result = _run(_RecordedVerifier(_response()))
    assert type(result) is ClaimValidationSucceededV0

    public = result.validation.to_public_dict()
    schema = json.loads(
        (ROOT / "schemas" / "decision-board.v0.schema.json").read_text(encoding="utf-8")
    )
    validator = Draft202012Validator(
        {
            "$schema": schema["$schema"],
            "$defs": schema["$defs"],
            "$ref": "#/$defs/ClaimValidationV0",
        },
        format_checker=FormatChecker(),
    )

    assert set(public) == {
        "claim_id",
        "instrument",
        "source_url",
        "publisher",
        "published_at",
        "article_content_hash",
        "supporting_span",
        "supporting_location",
        "verifier_version",
        "entailment",
    }
    assert validate_claim_validation(public) == public
    validator.validate(public)
    assert PRIVATE_SENTINEL not in json.dumps(public, ensure_ascii=False)


def test_request_rejects_private_unknown_subclass_and_unsafe_claim_text() -> None:
    with pytest.raises(TypeError) as private_error:
        ClaimRequestV0(
            claim_id="claim-private",
            instrument=_instrument(),
            claim_text="public claim",
            action_changing=True,
            account_id=PRIVATE_SENTINEL,  # type: ignore[call-arg]
        )
    assert PRIVATE_SENTINEL not in str(private_error.value)

    class InstrumentSubclass(InstrumentRefV0):
        private_value = PRIVATE_SENTINEL

    with pytest.raises(TypeError, match="exact InstrumentRefV0"):
        ClaimRequestV0(
            claim_id="claim-private",
            instrument=InstrumentSubclass(**_instrument().to_public_dict()),
            claim_text="public claim",
            action_changing=True,
        )

    for claim_text in ("", "bad\ncontrol", "\ud800", "x" * 4001):
        with pytest.raises((TypeError, ValueError)):
            ClaimRequestV0(
                claim_id="claim-invalid-text",
                instrument=_instrument(),
                claim_text=claim_text,
                action_changing=True,
            )


def test_claim_id_and_action_changing_are_exact() -> None:
    for claim_id in ("", "private claim", "한글", "x" * 129):
        with pytest.raises((TypeError, ValueError)):
            ClaimRequestV0(
                claim_id=claim_id,
                instrument=_instrument(),
                claim_text="public claim",
                action_changing=True,
            )
    with pytest.raises(TypeError, match="bool"):
        ClaimRequestV0(
            claim_id="claim-exact-bool",
            instrument=_instrument(),
            claim_text="public claim",
            action_changing=1,  # type: ignore[arg-type]
        )


def test_article_without_publication_time_fails_before_verifier() -> None:
    policy = ResearchSourcePolicyV0()
    source = _source(published_at=None)
    article = _article(source, policy)
    verifier = _RecordedVerifier(_response())

    result = _run(verifier, source=source, article=article, policy=policy)

    assert type(result) is ClaimValidationFailedV0
    assert result.code == "ARTICLE_INVALID"
    assert verifier.calls == []
