"""Deterministic exact-span claim validation for Decision Board V0."""

from __future__ import annotations

import asyncio
import math
import re
import weakref
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum
from typing import Protocol

from sab.research.contracts import (
    ResearchSourcePolicyV0,
    SourceCandidateV0,
    copy_research_source_policy_v0,
    validate_and_copy_source_candidate_v0,
)
from sab.research.deadline import (
    Deadline,
    DeadlineExpiredError,
    DeadlineInvariantError,
)
from sab.research.source_safety import (
    ArticleArtifactV0,
    ArticleArtifactValidationError,
    validate_and_copy_article_artifact_v0,
)

from .contracts import canonical_json_bytes
from .instruments import (
    InstrumentRefV0,
    copy_trusted_instrument_ref_v0,
    normalize_public_text_v0,
)

MAX_CLAIM_TEXT_CHARS = 4_000
MAX_CLAIM_ID_CHARS = 128
MAX_VERIFIER_VERSION_CHARS = 128

_CLAIM_ID_PATTERN = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:-]{0,127}\Z")
_VERIFIER_VERSION_PATTERN = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:+/-]{0,127}\Z")
_VERIFIER_RESULT_FIELDS = {
    "entailment",
    "supporting_span",
    "supporting_location",
    "verifier_version",
}
_LOCATION_FIELDS = {"kind", "start", "end"}

type _InstrumentSnapshotV0 = tuple[str, str, str, str, str, str]
type _RequestSnapshotV0 = tuple[str, _InstrumentSnapshotV0, str, bool]
type _SourceSnapshotV0 = tuple[
    _InstrumentSnapshotV0,
    str,
    str,
    str,
    str,
    str | None,
    str,
]
type _PolicySnapshotV0 = tuple[int, int, int, int, float]
type _ArticleSnapshotV0 = tuple[_SourceSnapshotV0, str, str, str, str]
type _LocationSnapshotV0 = tuple[str, int, int]
type _ValidationSnapshotV0 = tuple[
    str,
    _InstrumentSnapshotV0,
    str,
    str,
    str,
    str,
    str,
    _LocationSnapshotV0,
    str,
    str,
]
type _VerifierOutputSnapshotV0 = tuple[
    str,
    str,
    _LocationSnapshotV0,
    str,
]

_REQUEST_BASELINES: dict[
    int,
    tuple[weakref.ReferenceType[ClaimRequestV0], _RequestSnapshotV0],
] = {}


class ClaimVerifierTimeoutError(TimeoutError):
    """An expected operational timeout from an injected claim verifier."""


class ClaimValidationIssuanceError(ValueError):
    """A value was not the unchanged result of this process's claim issuance."""


class EntailmentV0(StrEnum):
    SUPPORTED = "SUPPORTED"
    CONTRADICTED = "CONTRADICTED"
    UNCLEAR = "UNCLEAR"


@dataclass(frozen=True, slots=True, weakref_slot=True)
class ClaimRequestV0:
    """One normalized public claim bound to one trusted public instrument."""

    claim_id: str
    instrument: InstrumentRefV0
    claim_text: str
    action_changing: bool

    def __post_init__(self) -> None:
        if (
            type(self.claim_id) is not str
            or _CLAIM_ID_PATTERN.fullmatch(self.claim_id) is None
        ):
            raise ValueError("claim_id must match the conservative ASCII grammar")
        instrument = copy_trusted_instrument_ref_v0(self.instrument)
        if instrument is None:
            raise TypeError("claim request requires exact InstrumentRefV0")
        normalized_claim = normalize_public_text_v0(self.claim_text)
        if normalized_claim is None:
            raise ValueError("claim_text must be normalized public text")
        if len(normalized_claim) > MAX_CLAIM_TEXT_CHARS:
            raise ValueError("claim_text exceeds the safe length")
        if type(self.action_changing) is not bool:
            raise TypeError("action_changing must be an exact bool")
        object.__setattr__(self, "instrument", instrument)
        object.__setattr__(self, "claim_text", normalized_claim)
        _register_claim_request_v0(self)


@dataclass(frozen=True, slots=True)
class ClaimVerifierRequestV0:
    """Public-only deterministic verifier input; never an authority container."""

    claim_id: str
    claim_text: str
    instrument: InstrumentRefV0
    article_content_hash: str
    article_text: str

    def to_public_dict(self) -> dict[str, object]:
        instrument = self.instrument
        return {
            "claim_id": self.claim_id,
            "claim_text": self.claim_text,
            "instrument": {
                "market": instrument.market,
                "canonical_ticker": instrument.canonical_ticker,
                "exchange": instrument.exchange,
                "company_name": instrument.company_name,
                "identity_source": instrument.identity_source,
                "identity_version": instrument.identity_version,
            },
            "article_content_hash": self.article_content_hash,
            "article_text": self.article_text,
        }


class ClaimVerifierV0(Protocol):
    async def verify(
        self,
        request: ClaimVerifierRequestV0,
        *,
        deadline: Deadline,
        timeout: float,
    ) -> object: ...


@dataclass(frozen=True, slots=True, init=False)
class SupportingLocationV0:
    kind: str
    start: int
    end: int


@dataclass(frozen=True, slots=True, init=False, weakref_slot=True)
class ClaimValidationV0:
    claim_id: str
    instrument: InstrumentRefV0
    source_url: str
    publisher: str
    published_at: datetime
    article_content_hash: str
    supporting_span: str
    supporting_location: SupportingLocationV0
    verifier_version: str
    entailment: EntailmentV0

    def to_public_dict(self) -> dict[str, object]:
        """Serialize only an unchanged value bound to its issuance record."""

        return serialize_claim_validation_v0(self)


@dataclass(frozen=True, slots=True, init=False)
class ClaimValidationSucceededV0:
    validation: ClaimValidationV0

    def __new__(cls) -> ClaimValidationSucceededV0:
        raise TypeError("claim validation success is factory-owned")


@dataclass(frozen=True, slots=True, init=False)
class ClaimValidationTimedOutV0:
    code: str
    claim_id: str
    instrument: InstrumentRefV0

    def __new__(cls) -> ClaimValidationTimedOutV0:
        raise TypeError("claim timeout outcome is factory-owned")


@dataclass(frozen=True, slots=True, init=False)
class ClaimValidationFailedV0:
    code: str

    def __new__(cls) -> ClaimValidationFailedV0:
        raise TypeError("claim failure outcome is factory-owned")


type ClaimValidationResultV0 = (
    ClaimValidationSucceededV0 | ClaimValidationTimedOutV0 | ClaimValidationFailedV0
)


@dataclass(frozen=True, slots=True)
class _ClaimIssuanceRecordV0:
    reference: weakref.ReferenceType[ClaimValidationV0]
    validation_snapshot: _ValidationSnapshotV0
    validation_serialization: bytes
    request_snapshot: _RequestSnapshotV0
    source_snapshot: _SourceSnapshotV0
    article_snapshot: _ArticleSnapshotV0
    policy_snapshot: _PolicySnapshotV0
    verifier_output_snapshot: _VerifierOutputSnapshotV0


_SEALED_VALIDATIONS: dict[int, _ClaimIssuanceRecordV0] = {}


async def validate_claim_v0(
    request: ClaimRequestV0,
    article: ArticleArtifactV0,
    *,
    expected_source: SourceCandidateV0,
    policy: ResearchSourcePolicyV0,
    verifier: ClaimVerifierV0,
    deadline: Deadline,
    operation_timeout_seconds: float = 10.0,
) -> ClaimValidationResultV0:
    """Validate one public claim against one trusted article and shared deadline."""

    request_baseline = _copy_claim_request_v0(request)
    if request_baseline is None:
        return _failed("CLAIM_INPUT_INVALID")
    if type(deadline) is not Deadline:
        return _failed("DEADLINE_INVARIANT")
    baselines = _copy_article_baselines(
        article,
        expected_source=expected_source,
        policy=policy,
        expected_instrument=request_baseline.instrument,
    )
    if baselines is None:
        return _failed("ARTICLE_INVALID")
    source_baseline, policy_baseline, article_baseline = baselines
    if article_baseline.source.instrument != request_baseline.instrument:
        return _failed("ARTICLE_INVALID")
    if article_baseline.source.published_at is None:
        return _failed("ARTICLE_INVALID")
    timeout_limit = _operation_timeout_limit(
        operation_timeout_seconds,
        policy_baseline=policy_baseline,
    )
    if timeout_limit is None:
        return _failed("CLAIM_INPUT_INVALID")

    verifier_request = ClaimVerifierRequestV0(
        claim_id=request_baseline.claim_id,
        claim_text=request_baseline.claim_text,
        instrument=_required_instrument_copy(request_baseline.instrument),
        article_content_hash=article_baseline.content_hash,
        article_text=article_baseline.normalized_text,
    )

    try:
        timeout = deadline.child_timeout(timeout_limit)
    except DeadlineExpiredError:
        return _timed_out("DEADLINE_EXPIRED", request=request_baseline)
    except DeadlineInvariantError:
        return _failed("DEADLINE_INVARIANT")
    except Exception:
        return _failed("DEADLINE_INVARIANT")

    try:
        task = asyncio.create_task(
            verifier.verify(
                verifier_request,
                deadline=deadline,
                timeout=timeout,
            )
        )
    except Exception:
        precedence = _deadline_precedence(deadline, request=request_baseline)
        return precedence or _failed("VERIFIER_FAILED")

    try:
        _done, pending = await asyncio.wait({task}, timeout=timeout)
        if pending:
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)
            precedence = _deadline_precedence(deadline, request=request_baseline)
            return precedence or _timed_out("CLAIM_TIMEOUT", request=request_baseline)
        try:
            raw_result = task.result()
        except ClaimVerifierTimeoutError:
            precedence = _deadline_precedence(deadline, request=request_baseline)
            return precedence or _timed_out("CLAIM_TIMEOUT", request=request_baseline)
        except Exception:
            precedence = _deadline_precedence(deadline, request=request_baseline)
            return precedence or _failed("VERIFIER_FAILED")

        precedence = _deadline_precedence(deadline, request=request_baseline)
        if precedence is not None:
            return precedence
        if not _inputs_match_baselines(
            request,
            article,
            expected_source=expected_source,
            policy=policy,
            request_baseline=request_baseline,
            source_baseline=source_baseline,
            policy_baseline=policy_baseline,
            article_baseline=article_baseline,
        ):
            request_after = _copy_claim_request_v0(request)
            if request_after != request_baseline:
                return _failed("CLAIM_INPUT_INVALID")
            return _failed("ARTICLE_INVALID")
        parsed = _parse_verifier_result(raw_result, article_baseline.normalized_text)
        if parsed is None:
            return _failed("VERIFIER_RESULT_MALFORMED")
        entailment, span, start, end, version = parsed
        validation = _allocate_validation_v0(
            request=request_baseline,
            source=source_baseline,
            article=article_baseline,
            policy=policy_baseline,
            supporting_span=span,
            start=start,
            end=end,
            verifier_version=version,
            entailment=entailment,
        )
        return _succeeded(validation)
    except Exception:
        precedence = _deadline_precedence(deadline, request=request_baseline)
        return precedence or _failed("VERIFIER_FAILED")
    finally:
        if not task.done():
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)


def is_action_change_eligible_v0(
    validation: object,
    *,
    request: ClaimRequestV0,
    article: ArticleArtifactV0,
    expected_source: SourceCandidateV0,
    policy: ResearchSourcePolicyV0,
) -> bool:
    """Return true only for a deeply revalidated action-changing support claim."""

    record = _registered_issuance_record_v0(validation)
    if record is None or not _validation_matches_issuance_v0(validation, record):
        return False
    request_baseline = _copy_claim_request_v0(request)
    if (
        request_baseline is None
        or _claim_request_snapshot_v0(request_baseline) != record.request_snapshot
    ):
        return False
    baselines = _copy_article_baselines(
        article,
        expected_source=expected_source,
        policy=policy,
        expected_instrument=request_baseline.instrument,
    )
    if baselines is None:
        return False
    source_baseline, policy_baseline, article_baseline = baselines
    if article_baseline.source.instrument != request_baseline.instrument:
        return False
    if (
        _source_snapshot_v0(source_baseline) != record.source_snapshot
        or _policy_snapshot_v0(policy_baseline) != record.policy_snapshot
        or _article_snapshot_v0(article_baseline) != record.article_snapshot
        or not record.request_snapshot[3]
        or record.verifier_output_snapshot[0] != EntailmentV0.SUPPORTED.value
        or record.validation_snapshot[-1] != EntailmentV0.SUPPORTED.value
    ):
        return False
    trusted = _validate_claim_validation_fields_v0(
        validation,
        request=request_baseline,
        article=article_baseline,
    )
    return trusted is not None and trusted.entailment is EntailmentV0.SUPPORTED


def serialize_claim_validation_v0(value: object) -> dict[str, object]:
    """Return a fresh Task 1 allowlist only for an unchanged issued validation."""

    record = _registered_issuance_record_v0(value)
    if record is None or not _validation_matches_issuance_v0(value, record):
        raise ClaimValidationIssuanceError(
            "claim validation is not an unchanged issued value"
        )
    try:
        public = _claim_validation_public_dict_unchecked(value)
        serialized = canonical_json_bytes(public)
    except Exception:
        raise ClaimValidationIssuanceError(
            "claim validation is not an unchanged issued value"
        ) from None
    if serialized != record.validation_serialization:
        raise ClaimValidationIssuanceError(
            "claim validation is not an unchanged issued value"
        )
    return public


def _copy_claim_request_v0(value: object) -> ClaimRequestV0 | None:
    if type(value) is not ClaimRequestV0:
        return None
    registered = _REQUEST_BASELINES.get(id(value))
    if (
        registered is None
        or registered[0]() is not value
        or _claim_request_snapshot_v0(value) != registered[1]
    ):
        return None
    try:
        copied = ClaimRequestV0(
            claim_id=value.claim_id,
            instrument=value.instrument,
            claim_text=value.claim_text,
            action_changing=value.action_changing,
        )
    except AttributeError, TypeError, ValueError:
        return None
    return copied if copied == value else None


def _claim_request_snapshot_v0(value: ClaimRequestV0) -> _RequestSnapshotV0 | None:
    try:
        instrument = _instrument_snapshot_v0(value.instrument)
        if instrument is None:
            return None
        return (
            value.claim_id,
            instrument,
            value.claim_text,
            value.action_changing,
        )
    except AttributeError:
        return None


def _register_claim_request_v0(value: ClaimRequestV0) -> None:
    request_id = id(value)
    snapshot = _claim_request_snapshot_v0(value)
    if snapshot is None:  # constructor validation establishes every field
        raise TypeError("claim request fields are unavailable")

    def discard(reference: weakref.ReferenceType[ClaimRequestV0]) -> None:
        current = _REQUEST_BASELINES.get(request_id)
        if current is not None and current[0] is reference:
            _REQUEST_BASELINES.pop(request_id, None)

    _REQUEST_BASELINES[request_id] = (weakref.ref(value, discard), snapshot)


def _copy_article_baselines(
    article: object,
    *,
    expected_source: object,
    policy: object,
    expected_instrument: InstrumentRefV0,
) -> tuple[SourceCandidateV0, ResearchSourcePolicyV0, ArticleArtifactV0] | None:
    try:
        source = validate_and_copy_source_candidate_v0(
            expected_source,
            expected_instrument=expected_instrument,
        )
        source = validate_and_copy_source_candidate_v0(
            source,
            expected_instrument=expected_instrument,
        )
        policy_copy = copy_research_source_policy_v0(policy)
        if policy_copy is None:
            return None
        article_copy = validate_and_copy_article_artifact_v0(
            article,
            expected_source=source,
            policy=policy_copy,
        )
    except AttributeError, TypeError, ValueError, ArticleArtifactValidationError:
        return None
    return source, policy_copy, article_copy


def _inputs_match_baselines(
    request: object,
    article: object,
    *,
    expected_source: object,
    policy: object,
    request_baseline: ClaimRequestV0,
    source_baseline: SourceCandidateV0,
    policy_baseline: ResearchSourcePolicyV0,
    article_baseline: ArticleArtifactV0,
) -> bool:
    request_after = _copy_claim_request_v0(request)
    if request_after != request_baseline:
        return False
    baselines_after = _copy_article_baselines(
        article,
        expected_source=expected_source,
        policy=policy,
        expected_instrument=request_baseline.instrument,
    )
    if baselines_after is None:
        return False
    source_after, policy_after, article_after = baselines_after
    return (
        source_after == source_baseline
        and policy_after == policy_baseline
        and article_after == article_baseline
    )


def _operation_timeout_limit(
    value: object,
    *,
    policy_baseline: ResearchSourcePolicyV0,
) -> float | None:
    if (
        isinstance(value, bool)
        or not isinstance(value, (int, float))
        or not math.isfinite(value)
        or value <= 0
    ):
        return None
    return min(float(value), policy_baseline.operation_timeout_seconds)


def _deadline_precedence(
    deadline: Deadline,
    *,
    request: ClaimRequestV0,
) -> ClaimValidationResultV0 | None:
    try:
        deadline.remaining()
    except DeadlineExpiredError:
        return _timed_out("DEADLINE_EXPIRED", request=request)
    except DeadlineInvariantError:
        return _failed("DEADLINE_INVARIANT")
    except Exception:
        return _failed("DEADLINE_INVARIANT")
    return None


def _parse_verifier_result(
    value: object,
    article_text: str,
) -> tuple[EntailmentV0, str, int, int, str] | None:
    if type(value) is not dict or set(value) != _VERIFIER_RESULT_FIELDS:
        return None
    location = value.get("supporting_location")
    if type(location) is not dict or set(location) != _LOCATION_FIELDS:
        return None
    raw_entailment = value.get("entailment")
    if type(raw_entailment) is not str:
        return None
    try:
        entailment = EntailmentV0(raw_entailment)
    except ValueError:
        return None
    span = value.get("supporting_span")
    version = value.get("verifier_version")
    kind = location.get("kind")
    start = location.get("start")
    end = location.get("end")
    if type(span) is not str or not span:
        return None
    if type(version) is not str or _VERIFIER_VERSION_PATTERN.fullmatch(version) is None:
        return None
    if kind != "TEXT_OFFSETS" or type(kind) is not str:
        return None
    if type(start) is not int or type(end) is not int:
        return None
    if not 0 <= start < end <= len(article_text):
        return None
    if span != article_text[start:end]:
        return None
    return entailment, span, start, end, version


def _allocate_validation_v0(
    *,
    request: ClaimRequestV0,
    source: SourceCandidateV0,
    article: ArticleArtifactV0,
    policy: ResearchSourcePolicyV0,
    supporting_span: str,
    start: int,
    end: int,
    verifier_version: str,
    entailment: EntailmentV0,
) -> ClaimValidationV0:
    published_at = article.source.published_at
    if published_at is None:  # guarded before verifier invocation
        raise ValueError("validated claim article requires publication time")
    location = object.__new__(SupportingLocationV0)
    object.__setattr__(location, "kind", "TEXT_OFFSETS")
    object.__setattr__(location, "start", start)
    object.__setattr__(location, "end", end)
    validation = object.__new__(ClaimValidationV0)
    object.__setattr__(validation, "claim_id", request.claim_id)
    object.__setattr__(
        validation,
        "instrument",
        _required_instrument_copy(request.instrument),
    )
    object.__setattr__(validation, "source_url", article.final_url)
    object.__setattr__(validation, "publisher", article.source.publisher)
    object.__setattr__(validation, "published_at", published_at)
    object.__setattr__(validation, "article_content_hash", article.content_hash)
    object.__setattr__(validation, "supporting_span", supporting_span)
    object.__setattr__(validation, "supporting_location", location)
    object.__setattr__(validation, "verifier_version", verifier_version)
    object.__setattr__(validation, "entailment", entailment)
    validation_snapshot = _claim_validation_snapshot_v0(validation)
    request_snapshot = _claim_request_snapshot_v0(request)
    source_snapshot = _source_snapshot_v0(source)
    article_snapshot = _article_snapshot_v0(article)
    policy_snapshot = _policy_snapshot_v0(policy)
    if (
        validation_snapshot is None
        or request_snapshot is None
        or source_snapshot is None
        or article_snapshot is None
        or policy_snapshot is None
    ):
        raise ValueError("claim issuance baselines are invalid")
    validation_serialization = canonical_json_bytes(
        _claim_validation_public_dict_unchecked(validation)
    )
    verifier_output_snapshot: _VerifierOutputSnapshotV0 = (
        entailment.value,
        supporting_span,
        ("TEXT_OFFSETS", start, end),
        verifier_version,
    )
    validation_id = id(validation)

    def discard(reference: weakref.ReferenceType[ClaimValidationV0]) -> None:
        current = _SEALED_VALIDATIONS.get(validation_id)
        if current is not None and current.reference is reference:
            _SEALED_VALIDATIONS.pop(validation_id, None)

    reference = weakref.ref(validation, discard)
    _SEALED_VALIDATIONS[validation_id] = _ClaimIssuanceRecordV0(
        reference=reference,
        validation_snapshot=validation_snapshot,
        validation_serialization=validation_serialization,
        request_snapshot=request_snapshot,
        source_snapshot=source_snapshot,
        article_snapshot=article_snapshot,
        policy_snapshot=policy_snapshot,
        verifier_output_snapshot=verifier_output_snapshot,
    )
    return validation


def _validate_claim_validation_fields_v0(
    value: object,
    *,
    request: ClaimRequestV0,
    article: ArticleArtifactV0,
) -> ClaimValidationV0 | None:
    if type(value) is not ClaimValidationV0:
        return None
    try:
        instrument = copy_trusted_instrument_ref_v0(value.instrument)
        location = value.supporting_location
        published_at = article.source.published_at
        if (
            instrument is None
            or instrument != request.instrument
            or type(location) is not SupportingLocationV0
            or location.kind != "TEXT_OFFSETS"
            or type(location.start) is not int
            or type(location.end) is not int
            or not 0 <= location.start < location.end <= len(article.normalized_text)
            or type(value.supporting_span) is not str
            or value.supporting_span
            != article.normalized_text[location.start : location.end]
            or value.claim_id != request.claim_id
            or value.source_url != article.final_url
            or value.publisher != article.source.publisher
            or published_at is None
            or type(value.published_at) is not datetime
            or value.published_at.tzinfo is not UTC
            or value.published_at != published_at
            or value.article_content_hash != article.content_hash
            or type(value.verifier_version) is not str
            or _VERIFIER_VERSION_PATTERN.fullmatch(value.verifier_version) is None
            or type(value.entailment) is not EntailmentV0
        ):
            return None
    except AttributeError:
        return None
    return value


def _registered_issuance_record_v0(
    value: object,
) -> _ClaimIssuanceRecordV0 | None:
    if type(value) is not ClaimValidationV0:
        return None
    record = _SEALED_VALIDATIONS.get(id(value))
    if record is None or record.reference() is not value:
        return None
    return record


def _validation_matches_issuance_v0(
    value: object,
    record: _ClaimIssuanceRecordV0,
) -> bool:
    snapshot = _claim_validation_snapshot_v0(value)
    if snapshot is None or snapshot != record.validation_snapshot:
        return False
    try:
        return (
            canonical_json_bytes(_claim_validation_public_dict_unchecked(value))
            == record.validation_serialization
        )
    except Exception:
        return False


def _instrument_snapshot_v0(value: object) -> _InstrumentSnapshotV0 | None:
    instrument = copy_trusted_instrument_ref_v0(value)
    if instrument is None:
        return None
    return (
        instrument.market,
        instrument.canonical_ticker,
        instrument.exchange,
        instrument.company_name,
        instrument.identity_source,
        instrument.identity_version,
    )


def _source_snapshot_v0(value: object) -> _SourceSnapshotV0 | None:
    if type(value) is not SourceCandidateV0:
        return None
    instrument = _instrument_snapshot_v0(value.instrument)
    if instrument is None:
        return None
    try:
        published_at = (
            value.published_at.isoformat().replace("+00:00", "Z")
            if value.published_at is not None
            else None
        )
        return (
            instrument,
            value.canonical_ticker,
            value.title,
            value.canonical_url,
            value.publisher,
            published_at,
            value.purpose.value,
        )
    except AttributeError:
        return None


def _policy_snapshot_v0(value: object) -> _PolicySnapshotV0 | None:
    policy = copy_research_source_policy_v0(value)
    if policy is None:
        return None
    return (
        policy.freshness_hours,
        policy.max_redirects,
        policy.max_response_bytes,
        policy.max_article_text_chars,
        float(policy.operation_timeout_seconds),
    )


def _article_snapshot_v0(value: object) -> _ArticleSnapshotV0 | None:
    if type(value) is not ArticleArtifactV0:
        return None
    source = _source_snapshot_v0(value.source)
    if source is None:
        return None
    try:
        seal = value._integrity_seal
        if type(seal) is not str:
            return None
        return (
            source,
            value.final_url,
            value.normalized_text,
            value.content_hash,
            seal,
        )
    except AttributeError:
        return None


def _claim_validation_snapshot_v0(
    value: object,
) -> _ValidationSnapshotV0 | None:
    if type(value) is not ClaimValidationV0:
        return None
    try:
        instrument = _instrument_snapshot_v0(value.instrument)
        location = value.supporting_location
        if (
            instrument is None
            or type(location) is not SupportingLocationV0
            or type(location.kind) is not str
            or type(location.start) is not int
            or type(location.end) is not int
            or type(value.published_at) is not datetime
            or value.published_at.tzinfo is not UTC
            or type(value.entailment) is not EntailmentV0
        ):
            return None
        return (
            value.claim_id,
            instrument,
            value.source_url,
            value.publisher,
            value.published_at.isoformat().replace("+00:00", "Z"),
            value.article_content_hash,
            value.supporting_span,
            (location.kind, location.start, location.end),
            value.verifier_version,
            value.entailment.value,
        )
    except AttributeError:
        return None


def _claim_validation_public_dict_unchecked(
    value: object,
) -> dict[str, object]:
    if type(value) is not ClaimValidationV0:
        raise TypeError("claim validation must be exact V0 value")
    instrument = value.instrument
    location = value.supporting_location
    return {
        "claim_id": value.claim_id,
        "instrument": {
            "market": instrument.market,
            "canonical_ticker": instrument.canonical_ticker,
            "exchange": instrument.exchange,
            "company_name": instrument.company_name,
            "identity_source": instrument.identity_source,
            "identity_version": instrument.identity_version,
        },
        "source_url": value.source_url,
        "publisher": value.publisher,
        "published_at": value.published_at.isoformat().replace("+00:00", "Z"),
        "article_content_hash": value.article_content_hash,
        "supporting_span": value.supporting_span,
        "supporting_location": {
            "kind": location.kind,
            "start": location.start,
            "end": location.end,
        },
        "verifier_version": value.verifier_version,
        "entailment": value.entailment.value,
    }


def _required_instrument_copy(value: object) -> InstrumentRefV0:
    copied = copy_trusted_instrument_ref_v0(value)
    if copied is None:  # invocation baselines prove this path
        raise TypeError("claim validation requires an exact InstrumentRefV0")
    return copied


def _succeeded(validation: ClaimValidationV0) -> ClaimValidationSucceededV0:
    result = object.__new__(ClaimValidationSucceededV0)
    object.__setattr__(result, "validation", validation)
    return result


def _timed_out(code: str, *, request: ClaimRequestV0) -> ClaimValidationTimedOutV0:
    result = object.__new__(ClaimValidationTimedOutV0)
    object.__setattr__(result, "code", code)
    object.__setattr__(result, "claim_id", request.claim_id)
    object.__setattr__(
        result,
        "instrument",
        _required_instrument_copy(request.instrument),
    )
    return result


def _failed(code: str) -> ClaimValidationFailedV0:
    result = object.__new__(ClaimValidationFailedV0)
    object.__setattr__(result, "code", code)
    return result


__all__ = [
    "MAX_CLAIM_ID_CHARS",
    "MAX_CLAIM_TEXT_CHARS",
    "MAX_VERIFIER_VERSION_CHARS",
    "ClaimRequestV0",
    "ClaimValidationFailedV0",
    "ClaimValidationIssuanceError",
    "ClaimValidationResultV0",
    "ClaimValidationSucceededV0",
    "ClaimValidationTimedOutV0",
    "ClaimValidationV0",
    "ClaimVerifierRequestV0",
    "ClaimVerifierTimeoutError",
    "ClaimVerifierV0",
    "EntailmentV0",
    "SupportingLocationV0",
    "is_action_change_eligible_v0",
    "serialize_claim_validation_v0",
    "validate_claim_v0",
]
