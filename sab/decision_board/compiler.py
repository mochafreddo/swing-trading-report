"""Pure deterministic Decision Board V0 ENTRY/HOLDING compiler."""

from __future__ import annotations

import re
import weakref
from collections.abc import Iterable
from dataclasses import dataclass
from enum import StrEnum
from typing import Any, cast
from urllib.parse import urlsplit, urlunsplit

from sab.research.contracts import (
    ResearchSourcePolicyV0,
    SourceCandidateV0,
    validate_and_copy_source_candidate_v0,
)
from sab.research.source_safety import ArticleArtifactV0

from .claims import (
    ClaimRequestV0,
    ClaimValidationV0,
    is_action_change_eligible_v0,
    serialize_claim_validation_v0,
)
from .contracts import (
    ContractError,
    validate_decision_payload,
    validate_public_evidence_url,
)
from .instruments import InstrumentRefV0, copy_trusted_instrument_ref_v0

_ITEM_ID_PATTERN = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:-]{0,127}\Z")
_ORDER_PATTERN = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:-]{0,127}\Z")


class CompilerInputError(ValueError):
    """The compiler received an unissued, mutated, or conflicting input value."""


class ApprovalStateV0(StrEnum):
    APPROVED = "APPROVED"
    REVIEW = "REVIEW"


class DependencyStateV0(StrEnum):
    CURRENT = "CURRENT"
    MISSING = "MISSING"
    STALE = "STALE"
    AMBIGUOUS = "AMBIGUOUS"
    CONFLICTED = "CONFLICTED"


class EntrySignalStateV0(StrEnum):
    READY_ENTER = "READY_ENTER"
    ABSENT = "ABSENT"
    NOT_READY_ENTER = "NOT_READY_ENTER"
    MISSING = "MISSING"
    STALE = "STALE"
    AMBIGUOUS = "AMBIGUOUS"
    CONFLICTED = "CONFLICTED"


class ExposureStateV0(StrEnum):
    PASS = "PASS"
    FAIL = "FAIL"
    MISSING = "MISSING"
    STALE = "STALE"
    AMBIGUOUS = "AMBIGUOUS"
    CONFLICTED = "CONFLICTED"


class HardExitStateV0(StrEnum):
    NONE = "NONE"
    HARD_STOP = "HARD_STOP"
    CONFIRMED_EXIT = "CONFIRMED_EXIT"


class ResearchStateV0(StrEnum):
    CLEAR = "CLEAR"
    NOT_SELECTED_CAP = "NOT_SELECTED_CAP"
    TIMEOUT = "TIMEOUT"
    FAILED = "FAILED"
    COVERAGE_GAP = "COVERAGE_GAP"
    STALE = "STALE"
    CONFLICTED = "CONFLICTED"


class CompilerEvidenceKindV0(StrEnum):
    MATERIAL_ADVERSE = "MATERIAL_ADVERSE"
    SUPPORTIVE = "SUPPORTIVE"


type _InstrumentSnapshot = tuple[str, str, str, str, str, str]
type _EvidenceSnapshot = tuple[
    CompilerEvidenceKindV0,
    int,
    int,
    int,
    int,
    int,
]
type _EntrySnapshot = tuple[object, ...]
type _HoldingSnapshot = tuple[object, ...]


@dataclass(frozen=True, slots=True, init=False, weakref_slot=True)
class CompilerEvidenceV0:
    """Invocation-bound T5 evidence candidate; never a serialized claim authority."""

    kind: CompilerEvidenceKindV0
    validation: ClaimValidationV0
    request: ClaimRequestV0
    article: ArticleArtifactV0
    expected_source: SourceCandidateV0
    policy: ResearchSourcePolicyV0

    @classmethod
    def create(
        cls,
        *,
        kind: CompilerEvidenceKindV0,
        validation: object,
        request: object,
        article: object,
        expected_source: object,
        policy: object,
    ) -> CompilerEvidenceV0:
        if type(kind) is not CompilerEvidenceKindV0:
            raise TypeError("evidence kind must be an exact compiler enum")
        value = object.__new__(cls)
        object.__setattr__(value, "kind", kind)
        object.__setattr__(value, "validation", validation)
        object.__setattr__(value, "request", request)
        object.__setattr__(value, "article", article)
        object.__setattr__(value, "expected_source", expected_source)
        object.__setattr__(value, "policy", policy)
        _register_evidence(value)
        return value


@dataclass(frozen=True, slots=True, init=False, weakref_slot=True)
class EntryCompilerItemV0:
    item_id: str
    instrument: InstrumentRefV0
    item_state: ApprovalStateV0
    identity_state: ApprovalStateV0
    signal_state: EntrySignalStateV0
    mandate_state: DependencyStateV0
    price_state: DependencyStateV0
    exposure_state: ExposureStateV0
    research_state: ResearchStateV0
    evidence: tuple[CompilerEvidenceV0, ...]

    @classmethod
    def create(
        cls,
        *,
        item_id: str,
        instrument: InstrumentRefV0,
        item_state: ApprovalStateV0,
        identity_state: ApprovalStateV0,
        signal_state: EntrySignalStateV0,
        mandate_state: DependencyStateV0,
        price_state: DependencyStateV0,
        exposure_state: ExposureStateV0,
        research_state: ResearchStateV0,
        evidence: tuple[CompilerEvidenceV0, ...] = (),
    ) -> EntryCompilerItemV0:
        values = _validate_common_factory_values(
            item_id=item_id,
            item_id_prefix="entry-",
            instrument=instrument,
            item_state=item_state,
            identity_state=identity_state,
            evidence=evidence,
        )
        _require_exact_enum(signal_state, EntrySignalStateV0, "signal_state")
        _require_exact_enum(mandate_state, DependencyStateV0, "mandate_state")
        _require_exact_enum(price_state, DependencyStateV0, "price_state")
        _require_exact_enum(exposure_state, ExposureStateV0, "exposure_state")
        _require_exact_enum(research_state, ResearchStateV0, "research_state")
        value = object.__new__(cls)
        for name, field_value in (
            *values,
            ("signal_state", signal_state),
            ("mandate_state", mandate_state),
            ("price_state", price_state),
            ("exposure_state", exposure_state),
            ("research_state", research_state),
        ):
            object.__setattr__(value, name, field_value)
        _register_item(value, _entry_snapshot(value), _ENTRY_ITEMS)
        return value


@dataclass(frozen=True, slots=True, init=False, weakref_slot=True)
class HoldingCompilerItemV0:
    item_id: str
    instrument: InstrumentRefV0
    item_state: ApprovalStateV0
    identity_state: ApprovalStateV0
    hard_exit_state: HardExitStateV0
    broker_state: DependencyStateV0
    candle_state: DependencyStateV0
    rule_state: DependencyStateV0
    research_state: ResearchStateV0
    research_priority: int
    research_order: str
    evidence: tuple[CompilerEvidenceV0, ...]

    @classmethod
    def create(
        cls,
        *,
        item_id: str,
        instrument: InstrumentRefV0,
        item_state: ApprovalStateV0,
        identity_state: ApprovalStateV0,
        hard_exit_state: HardExitStateV0,
        broker_state: DependencyStateV0,
        candle_state: DependencyStateV0,
        rule_state: DependencyStateV0,
        research_state: ResearchStateV0,
        research_priority: int,
        research_order: str,
        evidence: tuple[CompilerEvidenceV0, ...] = (),
    ) -> HoldingCompilerItemV0:
        values = _validate_common_factory_values(
            item_id=item_id,
            item_id_prefix="holding-",
            instrument=instrument,
            item_state=item_state,
            identity_state=identity_state,
            evidence=evidence,
        )
        for field_name, field_value, enum_type in (
            ("hard_exit_state", hard_exit_state, HardExitStateV0),
            ("broker_state", broker_state, DependencyStateV0),
            ("candle_state", candle_state, DependencyStateV0),
            ("rule_state", rule_state, DependencyStateV0),
            ("research_state", research_state, ResearchStateV0),
        ):
            _require_exact_enum(field_value, enum_type, field_name)
        validated_priority = _validated_research_priority(research_priority)
        if validated_priority is None:
            raise ValueError("research_priority must be an integer in range 0..1000000")
        validated_order = _validated_research_order(research_order)
        if validated_order is None:
            raise ValueError("research_order must use the conservative ASCII grammar")
        value = object.__new__(cls)
        for name, common_value in values:
            object.__setattr__(value, name, common_value)
        object.__setattr__(value, "hard_exit_state", hard_exit_state)
        object.__setattr__(value, "broker_state", broker_state)
        object.__setattr__(value, "candle_state", candle_state)
        object.__setattr__(value, "rule_state", rule_state)
        object.__setattr__(value, "research_state", research_state)
        object.__setattr__(value, "research_priority", validated_priority)
        object.__setattr__(value, "research_order", validated_order)
        _register_item(value, _holding_snapshot(value), _HOLDING_ITEMS)
        return value


_EVIDENCE: dict[
    int, tuple[weakref.ReferenceType[CompilerEvidenceV0], _EvidenceSnapshot]
] = {}
_ENTRY_ITEMS: dict[
    int, tuple[weakref.ReferenceType[EntryCompilerItemV0], _EntrySnapshot]
] = {}
_HOLDING_ITEMS: dict[
    int, tuple[weakref.ReferenceType[HoldingCompilerItemV0], _HoldingSnapshot]
] = {}


class DecisionCompilerV0:
    """Compile sealed public policy facts without I/O, time, or external calls."""

    @staticmethod
    def compile_entry(
        items: Iterable[EntryCompilerItemV0], *, sealed_input_hash: str
    ) -> dict[str, Any]:
        validated = _validated_items(items, holding=False)
        output: list[dict[str, Any]] = []
        for item in validated:
            assert type(item) is EntryCompilerItemV0
            compiled = _compile_entry_item(item)
            if compiled is not None:
                output.append(compiled)
        return _validated_payload("ENTRY", sealed_input_hash, output)

    @staticmethod
    def compile_holding(
        items: Iterable[HoldingCompilerItemV0],
        *,
        selection: object,
        sealed_input_hash: str,
    ) -> dict[str, Any]:
        validated = _validated_items(items, holding=True)
        from .policy import _validate_holding_research_selection_v0

        holding_items: list[HoldingCompilerItemV0] = []
        for item in validated:
            assert type(item) is HoldingCompilerItemV0
            holding_items.append(item)
        research_states = _validate_holding_research_selection_v0(
            selection,
            items=holding_items,
        )
        output: list[dict[str, Any]] = []
        for item in holding_items:
            output.append(
                _compile_holding_item(
                    item,
                    research_state=research_states[item.item_id],
                )
            )
        return _validated_payload("HOLDING", sealed_input_hash, output)


def _compile_entry_item(item: EntryCompilerItemV0) -> dict[str, Any] | None:
    evidence, material_adverse = _eligible_evidence(item.evidence, item.instrument)
    approval_issues = _approval_issues(item.item_state, item.identity_state)
    if approval_issues:
        return _review_item(item.instrument, approval_issues, evidence)
    if item.signal_state in {
        EntrySignalStateV0.ABSENT,
        EntrySignalStateV0.NOT_READY_ENTER,
    }:
        return None
    dependency_issues = _entry_dependency_issues(item)
    if dependency_issues:
        return _review_item(item.instrument, dependency_issues, evidence)
    if item.exposure_state is ExposureStateV0.FAIL:
        return _decided_item(item.instrument, "AVOID", evidence)
    research_issue = _research_issue(item.research_state)
    if research_issue is not None:
        return _review_item(item.instrument, [research_issue], evidence)
    if material_adverse:
        return _decided_item(item.instrument, "AVOID", evidence)
    return _decided_item(item.instrument, "BUY", evidence)


def _compile_holding_item(
    item: HoldingCompilerItemV0, *, research_state: ResearchStateV0
) -> dict[str, Any]:
    evidence, material_adverse = _eligible_evidence(item.evidence, item.instrument)
    deterministic_current = all(
        state is DependencyStateV0.CURRENT
        for state in (item.broker_state, item.candle_state, item.rule_state)
    )
    # HARD SELL is the top lattice node: research/evidence can annotate, never override it.
    if item.hard_exit_state is not HardExitStateV0.NONE and deterministic_current:
        return _decided_item(item.instrument, "SELL", evidence)
    issues = _approval_issues(item.item_state, item.identity_state)
    issues.extend(_holding_dependency_issues(item))
    if issues:
        return _review_item(item.instrument, issues, evidence)
    if material_adverse:
        return _review_item(
            item.instrument,
            [_issue("REVIEW_MATERIAL_ADVERSE")],
            evidence,
        )
    research_issue = _research_issue(research_state)
    if research_issue is not None:
        return _review_item(item.instrument, [research_issue], evidence)
    return _decided_item(item.instrument, "HOLD", evidence)


def _validated_items(
    values: Iterable[EntryCompilerItemV0] | Iterable[HoldingCompilerItemV0],
    *,
    holding: bool,
) -> tuple[EntryCompilerItemV0 | HoldingCompilerItemV0, ...]:
    try:
        items = tuple(values)
    except TypeError as exc:
        raise CompilerInputError("compiler items must be a finite iterable") from exc
    validated: list[
        tuple[
            EntryCompilerItemV0 | HoldingCompilerItemV0,
            _EntrySnapshot | _HoldingSnapshot,
        ]
    ] = []
    item_ids: set[str] = set()
    instruments: set[_InstrumentSnapshot] = set()
    for value in items:
        typed_value: EntryCompilerItemV0 | HoldingCompilerItemV0
        if type(value) not in {EntryCompilerItemV0, HoldingCompilerItemV0}:
            raise CompilerInputError("compiler item is not an exact V0 input")
        typed_value = cast(EntryCompilerItemV0 | HoldingCompilerItemV0, value)
        snapshot = (
            _validated_holding_snapshot(typed_value)
            if holding
            else _validated_entry_snapshot(typed_value)
        )
        if snapshot is None:
            raise CompilerInputError("compiler item is not an unchanged issued value")
        item_id, instrument_snapshot = _compiler_item_identity(snapshot)
        if item_id in item_ids or instrument_snapshot in instruments:
            raise CompilerInputError("compiler item identities must be unique")
        item_ids.add(item_id)
        instruments.add(instrument_snapshot)
        validated.append((typed_value, snapshot))
    return tuple(
        item
        for item, _snapshot in sorted(
            validated,
            key=lambda pair: _compiler_item_sort_key(pair[1]),
        )
    )


def _compiler_item_identity(
    snapshot: _EntrySnapshot | _HoldingSnapshot,
) -> tuple[str, _InstrumentSnapshot]:
    item_id = snapshot[0]
    instrument = snapshot[1]
    if (
        type(item_id) is not str
        or type(instrument) is not tuple
        or len(instrument) != 6
        or not all(type(part) is str for part in instrument)
    ):
        raise CompilerInputError("compiler item snapshot is invalid")
    return item_id, cast(_InstrumentSnapshot, instrument)


def _compiler_item_sort_key(
    snapshot: _EntrySnapshot | _HoldingSnapshot,
) -> tuple[bytes, tuple[bytes, ...]]:
    item_id, instrument = _compiler_item_identity(snapshot)
    return item_id.encode("utf-8"), tuple(part.encode("utf-8") for part in instrument)


def _validated_entry_snapshot(value: object) -> _EntrySnapshot | None:
    if type(value) is not EntryCompilerItemV0:
        return None
    record = _ENTRY_ITEMS.get(id(value))
    current = _entry_snapshot(value)
    if record is None or record[0]() is not value or current != record[1]:
        return None
    return current


def _validated_holding_snapshot(value: object) -> _HoldingSnapshot | None:
    if type(value) is not HoldingCompilerItemV0:
        return None
    record = _HOLDING_ITEMS.get(id(value))
    current = _holding_snapshot(value)
    if record is None or record[0]() is not value or current != record[1]:
        return None
    return current


def _holding_selection_snapshot(value: object) -> tuple[object, ...] | None:
    snapshot = _validated_holding_snapshot(value)
    if snapshot is None:
        return None
    return (*snapshot[:8], snapshot[9], snapshot[10])


def _eligible_evidence(
    values: tuple[CompilerEvidenceV0, ...], instrument: InstrumentRefV0
) -> tuple[list[dict[str, object]], bool]:
    references: dict[str, dict[str, object]] = {}
    adverse = False
    for value in values:
        record = _EVIDENCE.get(id(value)) if type(value) is CompilerEvidenceV0 else None
        current = _evidence_snapshot(value)
        if record is None or record[0]() is not value or current != record[1]:
            raise CompilerInputError(
                "compiler evidence is not an unchanged issued value"
            )
        request_instrument = copy_trusted_instrument_ref_v0(value.request.instrument)
        if request_instrument != instrument:
            raise CompilerInputError("compiler evidence instrument binding is invalid")
        if not is_action_change_eligible_v0(
            value.validation,
            request=value.request,
            article=value.article,
            expected_source=value.expected_source,
            policy=value.policy,
        ):
            continue
        public = serialize_claim_validation_v0(value.validation)
        claim_id = public["claim_id"]
        if type(claim_id) is not str:
            raise CompilerInputError("compiler evidence claim identity is invalid")
        try:
            source = validate_and_copy_source_candidate_v0(
                value.expected_source,
                expected_instrument=instrument,
            )
            raw_source_url = public["source_url"]
            if type(raw_source_url) is not str:
                raise CompilerInputError(
                    "compiler evidence public reference is invalid"
                )
            parsed_source_url = urlsplit(raw_source_url)
            source_url = urlunsplit(
                (
                    parsed_source_url.scheme,
                    parsed_source_url.netloc,
                    parsed_source_url.path,
                    "",
                    "",
                )
            )
            validate_public_evidence_url(source_url, "$.source_url")
            reference = {
                "claim_id": claim_id,
                "role": (
                    "OPPOSING"
                    if value.kind is CompilerEvidenceKindV0.MATERIAL_ADVERSE
                    else "SUPPORTING"
                ),
                "source_url": source_url,
                "publisher": public["publisher"],
                "published_at": public["published_at"],
                "freshness": "WITHIN_POLICY",
                "citation_label": source.title,
            }
        except (AttributeError, TypeError, ValueError) as exc:
            raise CompilerInputError(
                "compiler evidence public reference is invalid"
            ) from exc
        if not all(type(item) is str for item in reference.values()):
            raise CompilerInputError("compiler evidence public reference is invalid")
        existing = references.get(claim_id)
        if existing is not None and existing != reference:
            raise CompilerInputError("compiler evidence claim references conflict")
        references[claim_id] = reference
        adverse = adverse or value.kind is CompilerEvidenceKindV0.MATERIAL_ADVERSE
    return [references[key] for key in sorted(references, key=str.encode)], adverse


def _entry_dependency_issues(item: EntryCompilerItemV0) -> list[dict[str, str]]:
    issues: list[dict[str, str]] = []
    if item.signal_state is not EntrySignalStateV0.READY_ENTER:
        issues.append(_issue(f"REVIEW_SIGNAL_{item.signal_state.value}"))
    for name, state in (("MANDATE", item.mandate_state), ("PRICE", item.price_state)):
        if state is not DependencyStateV0.CURRENT:
            issues.append(_issue(f"REVIEW_{name}_{state.value}"))
    if item.exposure_state not in {ExposureStateV0.PASS, ExposureStateV0.FAIL}:
        issues.append(_issue(f"REVIEW_EXPOSURE_{item.exposure_state.value}"))
    return issues


def _holding_dependency_issues(item: HoldingCompilerItemV0) -> list[dict[str, str]]:
    issues: list[dict[str, str]] = []
    for name, state in (
        ("BROKER", item.broker_state),
        ("CANDLE", item.candle_state),
        ("RULE", item.rule_state),
    ):
        if state is not DependencyStateV0.CURRENT:
            issues.append(_issue(f"REVIEW_{name}_{state.value}"))
    return issues


def _approval_issues(
    item_state: ApprovalStateV0, identity_state: ApprovalStateV0
) -> list[dict[str, str]]:
    issues: list[dict[str, str]] = []
    if item_state is ApprovalStateV0.REVIEW:
        issues.append(_issue("REVIEW_ITEM_NOT_APPROVED"))
    if identity_state is ApprovalStateV0.REVIEW:
        issues.append(_issue("REVIEW_IDENTITY_NOT_APPROVED"))
    return issues


def _research_issue(state: ResearchStateV0) -> dict[str, str] | None:
    if state is ResearchStateV0.CLEAR:
        return None
    return _issue(f"REVIEW_RESEARCH_{state.value}")


def _issue(code: str) -> dict[str, str]:
    messages = {
        "REVIEW_ITEM_NOT_APPROVED": "The compiler item is not approved.",
        "REVIEW_IDENTITY_NOT_APPROVED": "The public instrument identity is not approved.",
        "REVIEW_MATERIAL_ADVERSE": "Supported material adverse evidence requires review.",
    }
    return {
        "code": code,
        "message": messages.get(code, "A required typed input is not current."),
    }


def _review_item(
    instrument: InstrumentRefV0,
    issues: list[dict[str, str]],
    evidence: list[dict[str, object]],
) -> dict[str, Any]:
    unique = {issue["code"]: issue for issue in issues}
    return {
        "instrument": instrument.to_public_dict(),
        "status": "REVIEW",
        "issues": [unique[key] for key in sorted(unique, key=str.encode)],
        "evidence": evidence,
    }


def _decided_item(
    instrument: InstrumentRefV0, action: str, evidence: list[dict[str, object]]
) -> dict[str, Any]:
    return {
        "instrument": instrument.to_public_dict(),
        "status": "DECIDED",
        "action": action,
        "issues": [],
        "evidence": evidence,
    }


def _validated_payload(
    run_kind: str, sealed_input_hash: object, items: list[dict[str, Any]]
) -> dict[str, Any]:
    payload = {
        "run_kind": run_kind,
        "sealed_input_hash": sealed_input_hash,
        "items": items,
    }
    try:
        return validate_decision_payload(payload)
    except ContractError as exc:
        raise CompilerInputError(
            "compiler payload failed the shared V0 contract"
        ) from exc


def _validate_common_factory_values(
    *,
    item_id: object,
    item_id_prefix: str,
    instrument: object,
    item_state: object,
    identity_state: object,
    evidence: object,
) -> tuple[tuple[str, object], ...]:
    trusted = copy_trusted_instrument_ref_v0(instrument)
    if trusted is None:
        raise TypeError("compiler item requires exact InstrumentRefV0")
    validated_item_id = _validated_item_id(
        item_id,
        item_id_prefix=item_id_prefix,
        canonical_ticker=trusted.canonical_ticker,
    )
    if validated_item_id is None:
        raise ValueError("item_id must match the lane public instrument identity")
    _require_exact_enum(item_state, ApprovalStateV0, "item_state")
    _require_exact_enum(identity_state, ApprovalStateV0, "identity_state")
    if type(evidence) is not tuple or not all(
        type(item) is CompilerEvidenceV0 for item in evidence
    ):
        raise TypeError("compiler evidence must be an exact tuple")
    return (
        ("item_id", validated_item_id),
        ("instrument", trusted),
        ("item_state", item_state),
        ("identity_state", identity_state),
        ("evidence", tuple(evidence)),
    )


def _require_exact_enum(value: object, enum_type: type[StrEnum], name: str) -> None:
    if not _is_canonical_enum_member(value, enum_type):
        raise TypeError(f"{name} must be an exact compiler enum")


def _is_canonical_enum_member(value: object, enum_type: type[StrEnum]) -> bool:
    return type(value) is enum_type and any(value is member for member in enum_type)


def _validated_item_id(
    value: object,
    *,
    item_id_prefix: str,
    canonical_ticker: str,
) -> str | None:
    if type(value) is not str:
        return None
    expected = f"{item_id_prefix}{canonical_ticker}"
    if value != expected or _ITEM_ID_PATTERN.fullmatch(value) is None:
        return None
    return value


def _validated_research_priority(value: object) -> int | None:
    if type(value) is not int or not 0 <= value <= 1_000_000:
        return None
    return value


def _validated_research_order(value: object) -> str | None:
    if type(value) is not str or _ORDER_PATTERN.fullmatch(value) is None:
        return None
    return value


def _instrument_snapshot(value: object) -> _InstrumentSnapshot:
    trusted = copy_trusted_instrument_ref_v0(value)
    if trusted is None:
        raise CompilerInputError("compiler instrument is not an exact trusted value")
    return (
        trusted.market,
        trusted.canonical_ticker,
        trusted.exchange,
        trusted.company_name,
        trusted.identity_source,
        trusted.identity_version,
    )


def _evidence_snapshot(value: object) -> _EvidenceSnapshot | None:
    if type(value) is not CompilerEvidenceV0:
        return None
    try:
        if not _is_canonical_enum_member(value.kind, CompilerEvidenceKindV0):
            return None
        return (
            value.kind,
            id(value.validation),
            id(value.request),
            id(value.article),
            id(value.expected_source),
            id(value.policy),
        )
    except AttributeError:
        return None


def _entry_snapshot(value: EntryCompilerItemV0) -> _EntrySnapshot:
    try:
        instrument = _instrument_snapshot(value.instrument)
        item_id = _validated_item_id(
            value.item_id,
            item_id_prefix="entry-",
            canonical_ticker=instrument[1],
        )
        if item_id is None:
            return ()
        if not all(
            (
                _is_canonical_enum_member(value.item_state, ApprovalStateV0),
                _is_canonical_enum_member(value.identity_state, ApprovalStateV0),
                _is_canonical_enum_member(value.signal_state, EntrySignalStateV0),
                _is_canonical_enum_member(value.mandate_state, DependencyStateV0),
                _is_canonical_enum_member(value.price_state, DependencyStateV0),
                _is_canonical_enum_member(value.exposure_state, ExposureStateV0),
                _is_canonical_enum_member(value.research_state, ResearchStateV0),
            )
        ):
            return ()
        return (
            item_id,
            instrument,
            value.item_state,
            value.identity_state,
            value.signal_state,
            value.mandate_state,
            value.price_state,
            value.exposure_state,
            value.research_state,
            tuple(id(item) for item in value.evidence),
        )
    except AttributeError, TypeError, CompilerInputError:
        return ()


def _holding_snapshot(value: HoldingCompilerItemV0) -> _HoldingSnapshot:
    try:
        instrument = _instrument_snapshot(value.instrument)
        item_id = _validated_item_id(
            value.item_id,
            item_id_prefix="holding-",
            canonical_ticker=instrument[1],
        )
        priority = _validated_research_priority(value.research_priority)
        order = _validated_research_order(value.research_order)
        if item_id is None or priority is None or order is None:
            return ()
        if not all(
            (
                _is_canonical_enum_member(value.item_state, ApprovalStateV0),
                _is_canonical_enum_member(value.identity_state, ApprovalStateV0),
                _is_canonical_enum_member(value.hard_exit_state, HardExitStateV0),
                _is_canonical_enum_member(value.broker_state, DependencyStateV0),
                _is_canonical_enum_member(value.candle_state, DependencyStateV0),
                _is_canonical_enum_member(value.rule_state, DependencyStateV0),
                _is_canonical_enum_member(value.research_state, ResearchStateV0),
            )
        ):
            return ()
        return (
            item_id,
            instrument,
            value.item_state,
            value.identity_state,
            value.hard_exit_state,
            value.broker_state,
            value.candle_state,
            value.rule_state,
            value.research_state,
            priority,
            order,
            tuple(id(item) for item in value.evidence),
        )
    except AttributeError, TypeError, CompilerInputError:
        return ()


def _register_evidence(value: CompilerEvidenceV0) -> None:
    snapshot = _evidence_snapshot(value)
    if snapshot is None:
        raise TypeError("compiler evidence fields are unavailable")
    _register_item(value, snapshot, _EVIDENCE)


def _register_item(value: Any, snapshot: Any, registry: dict[int, Any]) -> None:
    value_id = id(value)

    def discard(reference: weakref.ReferenceType[Any]) -> None:
        current = registry.get(value_id)
        if current is not None and current[0] is reference:
            registry.pop(value_id, None)

    registry[value_id] = (weakref.ref(value, discard), snapshot)


__all__ = [
    "ApprovalStateV0",
    "CompilerEvidenceKindV0",
    "CompilerEvidenceV0",
    "CompilerInputError",
    "DecisionCompilerV0",
    "DependencyStateV0",
    "EntryCompilerItemV0",
    "EntrySignalStateV0",
    "ExposureStateV0",
    "HardExitStateV0",
    "HoldingCompilerItemV0",
    "ResearchStateV0",
]
