"""Fail-closed validators for the static Portfolio Mandate A1 contract."""

from __future__ import annotations

from collections.abc import Iterable
from datetime import datetime
from decimal import Decimal
from pathlib import Path
from typing import Any, Literal, TypedDict, cast

from jsonschema import (  # type: ignore[import-untyped]
    Draft202012Validator,
    FormatChecker,
)

SCHEMA_VERSION = "portfolio-mandate.a1"
_SCHEMA_PATH = (
    Path(__file__).parents[2] / "schemas" / "portfolio-mandate.a1.schema.json"
)


class PortfolioMandateContractError(ValueError):
    """A Portfolio Mandate A1 value failed validation at an exact path."""

    def __init__(self, path: str, message: str) -> None:
        self.path = path
        self.message = message
        super().__init__(f"{path}: {message}")


class SourceIdentifierA1(TypedDict):
    scheme: str
    value: str


class IssuerA1(TypedDict):
    issuer_id: str
    legal_name: str
    source_identifiers: list[SourceIdentifierA1]


class InstrumentA1(TypedDict):
    instrument_id: str
    issuer_id: str
    security_type: Literal["COMMON_STOCK", "PREFERRED_STOCK", "ETF"]
    currency: str


class ListingAliasA1(TypedDict):
    listing_alias_id: str
    instrument_id: str
    exchange_mic: str
    ticker: str
    valid_from: str
    valid_to: str | None
    registry_version: str


class EvidenceIdentitySealA1(TypedDict):
    evidence_seal_id: str
    source_id: str
    instrument_id: str
    issuer_id: str
    registry_version: str
    source_event_time: str
    source_issuer_identifier: SourceIdentifierA1
    scope: Literal["ISSUER", "INSTRUMENT"]
    exchange_mic: str
    ticker: str
    sealed_at: str
    actor_kind: Literal["SOURCE_VALIDATOR"]


class StableIdentityA1(TypedDict):
    registry_version: str
    issuers: list[IssuerA1]
    instruments: list[InstrumentA1]
    listing_aliases: list[ListingAliasA1]
    evidence_seals: list[EvidenceIdentitySealA1]


class MandateA1(TypedDict):
    mandate_id: str
    instrument_id: str
    broker_position_id: str | None
    owner_actor_id: str
    created_at: str


class MandateVersionA1(TypedDict):
    mandate_version_id: str
    mandate_id: str
    version_number: int
    supersedes_version_id: str | None
    classification_state: Literal["UNCLASSIFIED", "ACTIVE", "EXIT_REVIEW", "CLOSED"]
    horizon: Literal["SWING", "LONG_TERM"] | None
    proposed_horizon: Literal["SWING", "LONG_TERM"] | None
    approval_state: Literal["DRAFT", "APPROVED", "NEEDS_REAPPROVAL"]
    thesis: str | None
    invalidation_conditions: list[str]
    approved_by_kind: Literal["USER"] | None
    approved_at: str | None
    policy_version: str
    effective_from: str | None
    effective_to: str | None


class ActivationCommandA1(TypedDict):
    command_id: str
    mandate_id: str
    draft_mandate_version_id: str
    expected_mandate_version_id: str
    actor_kind: Literal["USER"]
    actor_id: str
    broker_snapshot_version: int
    allocation_version: int
    requested_at: str


class MandateVersionCoreA1(TypedDict):
    mandates: list[MandateA1]
    versions: list[MandateVersionA1]
    activation_commands: list[ActivationCommandA1]


class BrokerPositionA1(TypedDict):
    broker_position_id: str
    instrument_id: str
    account_ref_hash: str
    currency: str


class BrokerPositionSnapshotA1(TypedDict):
    broker_position_snapshot_id: str
    broker_position_id: str
    snapshot_version: int
    quantity: str
    currency: str
    watermark: str
    sealed_input_hash: str


class AllocationA1(TypedDict):
    allocation_id: str
    broker_position_id: str
    allocation_version: int
    snapshot_version: int
    active: bool
    decision_eligible: bool


class PositionSliceA1(TypedDict):
    slice_id: str
    allocation_id: str
    mandate_version_id: str | None
    quantity: str
    currency: str
    classification_state: Literal["ACTIVE", "UNCLASSIFIED", "PENDING_ALLOCATION"]
    decision_eligible: bool


class RebaseCommandA1(TypedDict):
    command_id: str
    rebase_evidence_id: str
    broker_position_id: str
    source_snapshot_version: int
    target_snapshot_version: int
    target_quantity: str
    currency: str
    cause: Literal[
        "ZERO_DELTA",
        "UNIQUE_BUY",
        "UNRESOLVED_BUY",
        "UNIQUE_SELL",
        "AMBIGUOUS_SELL",
        "POSITION_CLOSED",
        "VERIFIED_CORPORATE_ACTION",
        "AMBIGUOUS_CORPORATE_ACTION",
    ]
    matched_slice_id: str | None
    corporate_action_ratio: str | None
    expected_allocation_version: int
    actor_kind: Literal["DETERMINISTIC"]
    requested_at: str


class RebaseEvidenceA1(TypedDict):
    rebase_evidence_id: str
    broker_position_id: str
    source_snapshot_version: int
    target_snapshot_version: int
    cause: str
    matched_slice_id: str | None
    corporate_action_ratio: str | None
    source_id: str
    evidence_hash: str
    verification_state: Literal["VERIFIED", "UNRESOLVED"]
    producer_kind: Literal["DETERMINISTIC"]


class PositionSliceCoreA1(TypedDict):
    broker_positions: list[BrokerPositionA1]
    snapshots: list[BrokerPositionSnapshotA1]
    allocations: list[AllocationA1]
    rebase_evidence: list[RebaseEvidenceA1]
    slices: list[PositionSliceA1]
    rebase_commands: list[RebaseCommandA1]


class PredicateAuthorityEventA1(TypedDict):
    predicate_authority_event_id: str
    command_id: str
    mandate_version_id: str
    predicate_id: str
    event_type: Literal[
        "PREDICATE_FULFILLED",
        "USER_PREDICATE_CONFIRMED",
        "PREDICATE_CANDIDATE",
        "PROVENANCE_VALIDATED",
        "PREDICATE_SUPERSEDED",
    ]
    producer_kind: Literal["DETERMINISTIC_PARSER", "USER", "AI", "SOURCE_VALIDATOR"]
    actor_kind: Literal["DETERMINISTIC", "USER", "RESEARCH_ADAPTER", "SOURCE_VALIDATOR"]
    policy_effect: Literal["SELL_ELIGIBLE", "REVIEW_ONLY", "PROVENANCE_ONLY"]
    source_id: str
    evidence_seal_id: str
    source_span: str | None
    observed_metric: str | None
    observed_value: str | None
    unit: str | None
    period: str | None
    parser_version: str | None
    predicate_schema_version: str | None
    actor_id: str | None
    reason: str | None
    structured_surface: bool
    free_text_only: bool
    supersedes_event_id: str | None
    created_at: str


class PredicateDefinitionA1(TypedDict):
    predicate_id: str
    mandate_version_id: str
    predicate_schema_version: str
    metric: str
    comparison_operator: Literal["LT", "LTE", "EQ", "GTE", "GT"]
    threshold_value: str
    expected_unit: str
    expected_period: str
    approval_state: Literal["APPROVED"]
    approved_by_kind: Literal["USER"]


class PredicateAuthorityCoreA1(TypedDict):
    definitions: list[PredicateDefinitionA1]
    events: list[PredicateAuthorityEventA1]


class PortfolioMandateA1Fixture(TypedDict):
    schema_version: Literal["portfolio-mandate.a1"]
    stable_identity: StableIdentityA1
    mandate_version_core: MandateVersionCoreA1
    position_slice_core: PositionSliceCoreA1
    predicate_authority_core: PredicateAuthorityCoreA1


def validate_portfolio_mandate_a1_fixture(
    value: object,
) -> PortfolioMandateA1Fixture:
    """Validate one synthetic A1 fixture without coercion or private-field spill."""

    validator = Draft202012Validator(
        _load_schema(),
        format_checker=FormatChecker(),
    )
    errors = sorted(validator.iter_errors(value), key=lambda error: list(error.path))
    if errors:
        error = errors[0]
        raise PortfolioMandateContractError(
            _json_path(error.absolute_path), error.message
        )
    fixture = cast(PortfolioMandateA1Fixture, value)
    _validate_stable_identity(fixture["stable_identity"])
    _validate_mandate_version_core(
        fixture["mandate_version_core"], fixture["stable_identity"]
    )
    _validate_position_slice_core(
        fixture["position_slice_core"],
        fixture["stable_identity"],
        fixture["mandate_version_core"],
    )
    _validate_predicate_authority_core(
        fixture["predicate_authority_core"],
        fixture["mandate_version_core"],
        fixture["stable_identity"],
    )
    return fixture


def _load_schema() -> dict[str, Any]:
    import json

    schema = json.loads(_SCHEMA_PATH.read_text(encoding="utf-8"))
    if not isinstance(schema, dict):
        raise PortfolioMandateContractError("$", "schema must be an object")
    Draft202012Validator.check_schema(schema)
    return schema


def _validate_stable_identity(identity: StableIdentityA1) -> None:
    issuers = {issuer["issuer_id"]: issuer for issuer in identity["issuers"]}
    instruments = {
        instrument["instrument_id"]: instrument
        for instrument in identity["instruments"]
    }
    aliases = identity["listing_aliases"]
    evidence_seal_ids = {
        seal["evidence_seal_id"] for seal in identity["evidence_seals"]
    }
    evidence_source_scopes = {
        (seal["source_id"], seal["instrument_id"], seal["registry_version"])
        for seal in identity["evidence_seals"]
    }

    if len(issuers) != len(identity["issuers"]):
        raise PortfolioMandateContractError(
            "stable_identity.issuers", "issuer_id values must be unique"
        )
    if len(instruments) != len(identity["instruments"]):
        raise PortfolioMandateContractError(
            "stable_identity.instruments", "instrument_id values must be unique"
        )
    if len(evidence_seal_ids) != len(identity["evidence_seals"]):
        raise PortfolioMandateContractError(
            "stable_identity.evidence_seals",
            "evidence_seal_id values must be unique",
        )
    if len(evidence_source_scopes) != len(identity["evidence_seals"]):
        raise PortfolioMandateContractError(
            "stable_identity.evidence_seals",
            "source_id, instrument_id, and registry_version must be unique",
        )
    for index, seal in enumerate(identity["evidence_seals"]):
        for prior in identity["evidence_seals"][:index]:
            if (
                prior["source_id"] == seal["source_id"]
                and prior["instrument_id"] != seal["instrument_id"]
                and (
                    prior["issuer_id"] != seal["issuer_id"]
                    or prior["scope"] == "INSTRUMENT"
                    or seal["scope"] == "INSTRUMENT"
                )
            ):
                raise PortfolioMandateContractError(
                    "stable_identity.evidence_seals",
                    "source scope cannot be rebound to another instrument",
                )
    for index, instrument in enumerate(identity["instruments"]):
        if instrument["issuer_id"] not in issuers:
            raise PortfolioMandateContractError(
                f"stable_identity.instruments[{index}].issuer_id",
                "must reference a stable issuer_id",
            )
    for index, alias in enumerate(aliases):
        if alias["instrument_id"] not in instruments:
            raise PortfolioMandateContractError(
                f"stable_identity.listing_aliases[{index}].instrument_id",
                "must reference a stable instrument_id",
            )
        if alias["registry_version"] != identity["registry_version"]:
            raise PortfolioMandateContractError(
                f"stable_identity.listing_aliases[{index}].registry_version",
                "must match the sealed registry version",
            )

    for index, seal in enumerate(identity["evidence_seals"]):
        prefix = f"stable_identity.evidence_seals[{index}]"
        resolved_instrument = instruments.get(seal["instrument_id"])
        if resolved_instrument is None:
            raise PortfolioMandateContractError(
                f"{prefix}.instrument_id", "must reference a stable instrument_id"
            )
        if resolved_instrument["issuer_id"] != seal["issuer_id"]:
            raise PortfolioMandateContractError(
                f"{prefix}.issuer_id", "must match the instrument issuer_id"
            )
        if seal["registry_version"] != identity["registry_version"]:
            raise PortfolioMandateContractError(
                f"{prefix}.registry_version", "must match the sealed registry version"
            )
        issuer_identifiers = issuers[seal["issuer_id"]]["source_identifiers"]
        if seal["source_issuer_identifier"] not in issuer_identifiers:
            raise PortfolioMandateContractError(
                f"{prefix}.source_issuer_identifier",
                "must be registered for the exact issuer",
            )
        candidates = [
            alias
            for alias in aliases
            if alias["instrument_id"] == seal["instrument_id"]
            and alias["exchange_mic"] == seal["exchange_mic"]
            and alias["ticker"] == seal["ticker"]
        ]
        if len(candidates) != 1:
            raise PortfolioMandateContractError(
                prefix, "alias lookup must resolve to exactly one stable instrument"
            )
        alias = candidates[0]
        event_time = _timestamp(seal["source_event_time"])
        valid_from = _timestamp(alias["valid_from"])
        valid_to = None if alias["valid_to"] is None else _timestamp(alias["valid_to"])
        if event_time < valid_from or (valid_to is not None and event_time >= valid_to):
            raise PortfolioMandateContractError(
                f"{prefix}.source_event_time",
                "must fall inside the exact alias validity window",
            )


def _validate_mandate_version_core(
    core: MandateVersionCoreA1,
    identity: StableIdentityA1,
) -> None:
    instrument_ids = {
        instrument["instrument_id"] for instrument in identity["instruments"]
    }
    mandates = {mandate["mandate_id"]: mandate for mandate in core["mandates"]}
    versions = {version["mandate_version_id"]: version for version in core["versions"]}
    if len(mandates) != len(core["mandates"]):
        raise PortfolioMandateContractError(
            "mandate_version_core.mandates", "mandate_id values must be unique"
        )
    if len(versions) != len(core["versions"]):
        raise PortfolioMandateContractError(
            "mandate_version_core.versions",
            "mandate_version_id values must be unique",
        )
    for index, mandate in enumerate(core["mandates"]):
        if mandate["instrument_id"] not in instrument_ids:
            raise PortfolioMandateContractError(
                f"mandate_version_core.mandates[{index}].instrument_id",
                "must reference a stable instrument_id",
            )

    active_by_mandate: dict[str, MandateVersionA1] = {}
    version_numbers: set[tuple[str, int]] = set()
    for index, version in enumerate(core["versions"]):
        prefix = f"mandate_version_core.versions[{index}]"
        if version["mandate_id"] not in mandates:
            raise PortfolioMandateContractError(
                f"{prefix}.mandate_id", "must reference a stable mandate_id"
            )
        number_identity = (version["mandate_id"], version["version_number"])
        if number_identity in version_numbers:
            raise PortfolioMandateContractError(
                "mandate_version_core.versions",
                "version_number must be unique within a mandate",
            )
        version_numbers.add(number_identity)
        superseded = (
            versions.get(version["supersedes_version_id"])
            if version["supersedes_version_id"] is not None
            else None
        )
        if version["supersedes_version_id"] is not None and (
            superseded is None
            or superseded["mandate_id"] != version["mandate_id"]
            or superseded["version_number"] >= version["version_number"]
        ):
            raise PortfolioMandateContractError(
                f"{prefix}.supersedes_version_id",
                "must reference an earlier version on the exact mandate",
            )
        is_active_approved = (
            version["classification_state"] == "ACTIVE"
            and version["approval_state"] == "APPROVED"
            and version["effective_to"] is None
        )
        if is_active_approved:
            if version["mandate_id"] in active_by_mandate:
                raise PortfolioMandateContractError(
                    "mandate_version_core.versions",
                    "a mandate can have at most one ACTIVE/APPROVED version",
                )
            active_by_mandate[version["mandate_id"]] = version
            if (
                version["horizon"] is None
                or version["proposed_horizon"] is not None
                or version["thesis"] is None
                or not version["invalidation_conditions"]
                or version["approved_by_kind"] != "USER"
                or version["approved_at"] is None
                or version["effective_from"] is None
            ):
                raise PortfolioMandateContractError(
                    prefix, "ACTIVE/APPROVED requires a complete user-approved version"
                )
        elif version["classification_state"] == "UNCLASSIFIED" and version[
            "approval_state"
        ] in {"DRAFT", "NEEDS_REAPPROVAL"}:
            if (
                version["horizon"] is not None
                or version["approved_by_kind"] is not None
                or version["approved_at"] is not None
                or version["effective_from"] is not None
            ):
                raise PortfolioMandateContractError(
                    prefix, "an unapproved version cannot be active or approved"
                )
        elif version["classification_state"] in {"EXIT_REVIEW", "CLOSED"} and (
            version["approval_state"] == "APPROVED"
            and version["horizon"] is None
            and version["approved_by_kind"] == "USER"
        ):
            pass
        else:
            raise PortfolioMandateContractError(
                prefix, "classification, horizon, and approval combination is invalid"
            )

    command_ids: set[str] = set()
    for index, command in enumerate(core["activation_commands"]):
        prefix = f"mandate_version_core.activation_commands[{index}]"
        if command["command_id"] in command_ids:
            raise PortfolioMandateContractError(
                "mandate_version_core.activation_commands",
                "activation command_id values must be unique",
            )
        command_ids.add(command["command_id"])
        resolved_mandate = mandates.get(command["mandate_id"])
        draft = versions.get(command["draft_mandate_version_id"])
        if (
            resolved_mandate is None
            or draft is None
            or draft["mandate_id"] != resolved_mandate["mandate_id"]
        ):
            raise PortfolioMandateContractError(
                f"{prefix}.draft_mandate_version_id",
                "must reference a draft on the exact mandate",
            )
        if command["actor_id"] != resolved_mandate["owner_actor_id"]:
            raise PortfolioMandateContractError(
                f"{prefix}.actor_id",
                "must match the mandate owner",
            )
        active = active_by_mandate.get(command["mandate_id"])
        if (
            active is None
            or active["mandate_version_id"] != command["expected_mandate_version_id"]
        ):
            raise PortfolioMandateContractError(
                f"{prefix}.expected_mandate_version_id",
                "must match the exact current active version",
            )
        if (
            draft["classification_state"] != "UNCLASSIFIED"
            or draft["approval_state"] not in {"DRAFT", "NEEDS_REAPPROVAL"}
            or draft["proposed_horizon"] is None
            or draft["thesis"] is None
            or not draft["invalidation_conditions"]
        ):
            raise PortfolioMandateContractError(
                f"{prefix}.draft_mandate_version_id",
                "draft must contain a proposed horizon, thesis, and invalidation",
            )
        if draft["supersedes_version_id"] != command["expected_mandate_version_id"]:
            raise PortfolioMandateContractError(
                f"{prefix}.draft_mandate_version_id",
                "draft must supersede the exact expected mandate version",
            )


def _validate_position_slice_core(
    core: PositionSliceCoreA1,
    identity: StableIdentityA1,
    mandate_core: MandateVersionCoreA1,
) -> None:
    instrument_ids = {
        instrument["instrument_id"] for instrument in identity["instruments"]
    }
    mandate_version_ids = {
        version["mandate_version_id"] for version in mandate_core["versions"]
    }
    mandate_versions = {
        version["mandate_version_id"]: version for version in mandate_core["versions"]
    }
    mandates = {mandate["mandate_id"]: mandate for mandate in mandate_core["mandates"]}
    positions = {
        position["broker_position_id"]: position
        for position in core["broker_positions"]
    }
    if len(positions) != len(core["broker_positions"]):
        raise PortfolioMandateContractError(
            "position_slice_core.broker_positions",
            "broker_position_id values must be unique",
        )
    for index, position in enumerate(core["broker_positions"]):
        if position["instrument_id"] not in instrument_ids:
            raise PortfolioMandateContractError(
                f"position_slice_core.broker_positions[{index}].instrument_id",
                "must reference a stable instrument_id",
            )
    for index, mandate in enumerate(mandate_core["mandates"]):
        broker_position_id = mandate["broker_position_id"]
        if broker_position_id is None:
            continue
        bound_position = positions.get(broker_position_id)
        if (
            bound_position is None
            or bound_position["instrument_id"] != mandate["instrument_id"]
        ):
            raise PortfolioMandateContractError(
                f"mandate_version_core.mandates[{index}].broker_position_id",
                "must reference a broker position for the exact instrument",
            )

    snapshots: dict[tuple[str, int], BrokerPositionSnapshotA1] = {}
    for index, snapshot in enumerate(core["snapshots"]):
        key = (snapshot["broker_position_id"], snapshot["snapshot_version"])
        if key in snapshots:
            raise PortfolioMandateContractError(
                "position_slice_core.snapshots",
                "snapshot_version must be unique within a broker position",
            )
        snapshots[key] = snapshot
        resolved_position = positions.get(snapshot["broker_position_id"])
        if (
            resolved_position is None
            or resolved_position["currency"] != snapshot["currency"]
        ):
            raise PortfolioMandateContractError(
                f"position_slice_core.snapshots[{index}].broker_position_id",
                "must reference the exact broker position and currency",
            )

    allocations = {
        allocation["allocation_id"]: allocation for allocation in core["allocations"]
    }
    if len(allocations) != len(core["allocations"]):
        raise PortfolioMandateContractError(
            "position_slice_core.allocations", "allocation_id values must be unique"
        )
    active_by_position: dict[str, AllocationA1] = {}
    for index, allocation in enumerate(core["allocations"]):
        if (
            allocation["broker_position_id"] not in positions
            or (allocation["broker_position_id"], allocation["snapshot_version"])
            not in snapshots
        ):
            raise PortfolioMandateContractError(
                f"position_slice_core.allocations[{index}]",
                "must reference an exact broker snapshot",
            )
        if allocation["active"]:
            if allocation["broker_position_id"] in active_by_position:
                raise PortfolioMandateContractError(
                    "position_slice_core.allocations",
                    "a broker position can have at most one active allocation",
                )
            active_by_position[allocation["broker_position_id"]] = allocation

    slices_by_allocation: dict[str, list[PositionSliceA1]] = {
        allocation_id: [] for allocation_id in allocations
    }
    seen_slice_ids: set[str] = set()
    for index, position_slice in enumerate(core["slices"]):
        if position_slice["slice_id"] in seen_slice_ids:
            raise PortfolioMandateContractError(
                "position_slice_core.slices", "slice_id values must be unique"
            )
        seen_slice_ids.add(position_slice["slice_id"])
        if (
            position_slice["classification_state"] == "ACTIVE"
            and (
                position_slice["mandate_version_id"] is None
                or not position_slice["decision_eligible"]
            )
        ) or (
            position_slice["classification_state"]
            in {"UNCLASSIFIED", "PENDING_ALLOCATION"}
            and (
                position_slice["mandate_version_id"] is not None
                or position_slice["decision_eligible"]
            )
        ):
            raise PortfolioMandateContractError(
                f"position_slice_core.slices[{index}]",
                "slice classification, mandate binding, and eligibility are invalid",
            )
        resolved_allocation = allocations.get(position_slice["allocation_id"])
        if resolved_allocation is None:
            raise PortfolioMandateContractError(
                f"position_slice_core.slices[{index}].allocation_id",
                "must reference an allocation",
            )
        if (
            position_slice["mandate_version_id"] is not None
            and position_slice["mandate_version_id"] not in mandate_version_ids
        ):
            raise PortfolioMandateContractError(
                f"position_slice_core.slices[{index}].mandate_version_id",
                "must reference an exact mandate version",
            )
        resolved_position = positions[resolved_allocation["broker_position_id"]]
        if position_slice["mandate_version_id"] is not None:
            mandate_version = mandate_versions[position_slice["mandate_version_id"]]
            mandate = mandates[mandate_version["mandate_id"]]
            if mandate["broker_position_id"] != resolved_position["broker_position_id"]:
                raise PortfolioMandateContractError(
                    f"position_slice_core.slices[{index}].mandate_version_id",
                    "must bind to the exact allocation broker position",
                )
        if position_slice["currency"] != resolved_position["currency"]:
            raise PortfolioMandateContractError(
                f"position_slice_core.slices[{index}].currency",
                "must match the broker position currency",
            )
        slices_by_allocation[position_slice["allocation_id"]].append(position_slice)

    for index, allocation in enumerate(core["allocations"]):
        snapshot = snapshots[
            (allocation["broker_position_id"], allocation["snapshot_version"])
        ]
        slice_total = sum(
            (
                Decimal(item["quantity"])
                for item in slices_by_allocation[allocation["allocation_id"]]
            ),
            Decimal(0),
        )
        if slice_total != Decimal(snapshot["quantity"]):
            raise PortfolioMandateContractError(
                f"position_slice_core.allocations[{index}]",
                "quarantine-inclusive slice sum must equal broker quantity",
            )

    evidence_by_id = {
        evidence["rebase_evidence_id"]: evidence for evidence in core["rebase_evidence"]
    }
    if len(evidence_by_id) != len(core["rebase_evidence"]):
        raise PortfolioMandateContractError(
            "position_slice_core.rebase_evidence",
            "rebase evidence identities must be unique",
        )
    command_ids: set[str] = set()
    rebase_identities: set[tuple[str, int]] = set()
    for index, command in enumerate(core["rebase_commands"]):
        prefix = f"position_slice_core.rebase_commands[{index}]"
        identity_key = (
            command["broker_position_id"],
            command["target_snapshot_version"],
        )
        if command["command_id"] in command_ids or identity_key in rebase_identities:
            raise PortfolioMandateContractError(
                "position_slice_core.rebase_commands",
                "command and target rebase identities must be unique",
            )
        command_ids.add(command["command_id"])
        rebase_identities.add(identity_key)
        evidence = evidence_by_id.get(command["rebase_evidence_id"])
        expected_verification_state = (
            "UNRESOLVED"
            if command["cause"]
            in {"UNRESOLVED_BUY", "AMBIGUOUS_SELL", "AMBIGUOUS_CORPORATE_ACTION"}
            else "VERIFIED"
        )
        if (
            evidence is None
            or evidence["broker_position_id"] != command["broker_position_id"]
            or evidence["source_snapshot_version"] != command["source_snapshot_version"]
            or evidence["target_snapshot_version"] != command["target_snapshot_version"]
            or evidence["cause"] != command["cause"]
            or evidence["matched_slice_id"] != command["matched_slice_id"]
            or evidence["corporate_action_ratio"] != command["corporate_action_ratio"]
            or evidence["verification_state"] != expected_verification_state
        ):
            raise PortfolioMandateContractError(
                f"{prefix}.rebase_evidence_id",
                "must reference exact deterministic rebase evidence",
            )
        active = active_by_position.get(command["broker_position_id"])
        if (
            active is None
            or active["allocation_version"] != command["expected_allocation_version"]
        ):
            raise PortfolioMandateContractError(
                f"{prefix}.expected_allocation_version",
                "must match the exact active allocation version",
            )
        if active["snapshot_version"] != command["source_snapshot_version"]:
            raise PortfolioMandateContractError(
                f"{prefix}.source_snapshot_version",
                "must match the active allocation snapshot",
            )
        target = snapshots.get(
            (command["broker_position_id"], command["target_snapshot_version"])
        )
        if (
            target is None
            or target["quantity"] != command["target_quantity"]
            or target["currency"] != command["currency"]
            or command["target_snapshot_version"] <= command["source_snapshot_version"]
        ):
            raise PortfolioMandateContractError(
                f"{prefix}.target_snapshot_version",
                "must reference the exact newer target snapshot",
            )
        source = snapshots[
            (command["broker_position_id"], command["source_snapshot_version"])
        ]
        delta = Decimal(command["target_quantity"]) - Decimal(source["quantity"])
        source_slice_ids = {
            item["slice_id"] for item in slices_by_allocation[active["allocation_id"]]
        }
        cause = command["cause"]
        matched = command["matched_slice_id"]
        ratio = command["corporate_action_ratio"]
        cause_valid = (
            (cause == "ZERO_DELTA" and delta == 0 and matched is None and ratio is None)
            or (
                cause == "UNIQUE_BUY"
                and delta > 0
                and matched in source_slice_ids
                and ratio is None
            )
            or (
                cause == "UNRESOLVED_BUY"
                and delta > 0
                and matched is None
                and ratio is None
            )
            or (
                cause == "UNIQUE_SELL"
                and delta < 0
                and matched in source_slice_ids
                and ratio is None
            )
            or (
                cause == "AMBIGUOUS_SELL"
                and delta < 0
                and matched is None
                and ratio is None
            )
            or (
                cause == "AMBIGUOUS_CORPORATE_ACTION"
                and matched is None
                and ratio is None
            )
            or (
                cause == "POSITION_CLOSED"
                and Decimal(command["target_quantity"]) == 0
                and matched is None
                and ratio is None
            )
            or (
                cause == "VERIFIED_CORPORATE_ACTION"
                and ratio is not None
                and matched is None
            )
        )
        if not cause_valid:
            raise PortfolioMandateContractError(
                f"{prefix}.cause",
                "rebase cause does not match the exact delta evidence",
            )

    for index, activation_command in enumerate(mandate_core["activation_commands"]):
        mandate = mandates[activation_command["mandate_id"]]
        broker_position_id = mandate["broker_position_id"]
        active = (
            None
            if broker_position_id is None
            else active_by_position.get(broker_position_id)
        )
        if (
            active is None
            or active["allocation_version"] != activation_command["allocation_version"]
        ):
            raise PortfolioMandateContractError(
                f"mandate_version_core.activation_commands[{index}].allocation_version",
                "must match the exact active allocation version",
            )
        if active["snapshot_version"] != activation_command["broker_snapshot_version"]:
            raise PortfolioMandateContractError(
                f"mandate_version_core.activation_commands[{index}]"
                ".broker_snapshot_version",
                "must match the exact active broker snapshot",
            )
        expected_version_id = activation_command["expected_mandate_version_id"]
        if not any(
            position_slice["mandate_version_id"] == expected_version_id
            for position_slice in slices_by_allocation[active["allocation_id"]]
        ):
            raise PortfolioMandateContractError(
                f"mandate_version_core.activation_commands[{index}]"
                ".expected_mandate_version_id",
                "must bind at least one active slice on the exact expected version",
            )


def _validate_predicate_authority_core(
    core: PredicateAuthorityCoreA1,
    mandate_core: MandateVersionCoreA1,
    identity: StableIdentityA1,
) -> None:
    mandate_version_ids = {
        version["mandate_version_id"] for version in mandate_core["versions"]
    }
    versions = {
        version["mandate_version_id"]: version for version in mandate_core["versions"]
    }
    mandates = {mandate["mandate_id"]: mandate for mandate in mandate_core["mandates"]}
    evidence_seals = {
        seal["evidence_seal_id"]: seal for seal in identity["evidence_seals"]
    }
    definitions: dict[tuple[str, str], PredicateDefinitionA1] = {}
    for index, definition in enumerate(core["definitions"]):
        key = (definition["predicate_id"], definition["mandate_version_id"])
        if key in definitions:
            raise PortfolioMandateContractError(
                "predicate_authority_core.definitions",
                "predicate definitions must be unique within a mandate version",
            )
        if definition["mandate_version_id"] not in mandate_version_ids:
            raise PortfolioMandateContractError(
                f"predicate_authority_core.definitions[{index}].mandate_version_id",
                "must reference an exact mandate version",
            )
        definitions[key] = definition
    event_ids: set[str] = set()
    command_ids: set[str] = set()
    for index, event in enumerate(core["events"]):
        prefix = f"predicate_authority_core.events[{index}]"
        if event["predicate_authority_event_id"] in event_ids:
            raise PortfolioMandateContractError(
                "predicate_authority_core.events", "event identities must be unique"
            )
        if event["command_id"] in command_ids:
            raise PortfolioMandateContractError(
                "predicate_authority_core.events", "command identities must be unique"
            )
        if event["mandate_version_id"] not in mandate_version_ids:
            raise PortfolioMandateContractError(
                f"{prefix}.mandate_version_id",
                "must reference an exact mandate version",
            )
        version = versions[event["mandate_version_id"]]
        mandate = mandates[version["mandate_id"]]
        if (
            event["producer_kind"] == "USER"
            and event["actor_id"] != mandate["owner_actor_id"]
        ):
            raise PortfolioMandateContractError(
                f"{prefix}.actor_id", "must match the mandate owner"
            )
        evidence_seal = evidence_seals.get(event["evidence_seal_id"])
        if (
            evidence_seal is None
            or evidence_seal["source_id"] != event["source_id"]
            or evidence_seal["instrument_id"] != mandate["instrument_id"]
        ):
            raise PortfolioMandateContractError(
                f"{prefix}.evidence_seal_id",
                "must reference an exact source seal for the mandate instrument",
            )
        resolved_definition = definitions.get(
            (event["predicate_id"], event["mandate_version_id"])
        )
        if resolved_definition is None:
            raise PortfolioMandateContractError(
                f"{prefix}.predicate_id",
                "must reference an approved predicate on the exact mandate version",
            )
        if (
            event["event_type"] in {"PREDICATE_FULFILLED", "USER_PREDICATE_CONFIRMED"}
            and event["predicate_schema_version"]
            != resolved_definition["predicate_schema_version"]
        ):
            raise PortfolioMandateContractError(
                f"{prefix}.predicate_schema_version",
                "must match the approved predicate schema version",
            )
        if event["event_type"] == "PREDICATE_FULFILLED":
            observed_value = event["observed_value"]
            operator = resolved_definition["comparison_operator"]
            threshold = Decimal(resolved_definition["threshold_value"])
            comparison_holds = (
                observed_value is not None
                and event["observed_metric"] == resolved_definition["metric"]
                and event["unit"] == resolved_definition["expected_unit"]
                and event["period"] == resolved_definition["expected_period"]
                and {
                    "LT": Decimal(observed_value) < threshold,
                    "LTE": Decimal(observed_value) <= threshold,
                    "EQ": Decimal(observed_value) == threshold,
                    "GTE": Decimal(observed_value) >= threshold,
                    "GT": Decimal(observed_value) > threshold,
                }[operator]
            )
            if not comparison_holds:
                raise PortfolioMandateContractError(
                    f"{prefix}.observed_value",
                    "must satisfy the approved typed predicate",
                )
        if event["supersedes_event_id"] is not None:
            prior_event = next(
                (
                    prior
                    for prior in core["events"][:index]
                    if prior["predicate_authority_event_id"]
                    == event["supersedes_event_id"]
                ),
                None,
            )
            if (
                event["event_type"] != "PREDICATE_SUPERSEDED"
                or prior_event is None
                or prior_event["mandate_version_id"] != event["mandate_version_id"]
                or prior_event["predicate_id"] != event["predicate_id"]
                or prior_event["event_type"] != "PREDICATE_FULFILLED"
                or _timestamp(prior_event["created_at"])
                >= _timestamp(event["created_at"])
            ):
                raise PortfolioMandateContractError(
                    f"{prefix}.supersedes_event_id",
                    "must reference an earlier fulfillment for the exact predicate",
                )
        event_ids.add(event["predicate_authority_event_id"])
        command_ids.add(event["command_id"])

        event_type = event["event_type"]
        valid = False
        if event_type == "PREDICATE_FULFILLED":
            valid = (
                event["producer_kind"] == "DETERMINISTIC_PARSER"
                and event["actor_kind"] == "DETERMINISTIC"
                and event["policy_effect"] == "SELL_ELIGIBLE"
                and event["source_span"] is not None
                and event["observed_metric"] is not None
                and event["observed_value"] is not None
                and event["unit"] is not None
                and event["period"] is not None
                and event["parser_version"] is not None
                and event["predicate_schema_version"] is not None
                and event["structured_surface"]
                and not event["free_text_only"]
                and event["supersedes_event_id"] is None
            )
        elif event_type == "USER_PREDICATE_CONFIRMED":
            valid = (
                event["producer_kind"] == "USER"
                and event["actor_kind"] == "USER"
                and event["policy_effect"] == "SELL_ELIGIBLE"
                and event["source_span"] is not None
                and event["predicate_schema_version"] is not None
                and event["actor_id"] is not None
                and event["reason"] is not None
                and event["structured_surface"]
                and not event["free_text_only"]
                and event["supersedes_event_id"] is None
            )
        elif event_type == "PREDICATE_CANDIDATE":
            valid = (
                event["producer_kind"] == "AI"
                and event["actor_kind"] == "RESEARCH_ADAPTER"
                and event["policy_effect"] == "REVIEW_ONLY"
                and event["supersedes_event_id"] is None
            )
        elif event_type == "PROVENANCE_VALIDATED":
            valid = (
                event["producer_kind"] == "SOURCE_VALIDATOR"
                and event["actor_kind"] == "SOURCE_VALIDATOR"
                and event["policy_effect"] == "PROVENANCE_ONLY"
                and event["source_span"] is not None
                and event["supersedes_event_id"] is None
            )
        elif event_type == "PREDICATE_SUPERSEDED":
            valid = (
                event["producer_kind"] in {"DETERMINISTIC_PARSER", "USER"}
                and (
                    (
                        event["producer_kind"] == "DETERMINISTIC_PARSER"
                        and event["actor_kind"] == "DETERMINISTIC"
                    )
                    or (
                        event["producer_kind"] == "USER"
                        and event["actor_kind"] == "USER"
                    )
                )
                and event["policy_effect"] == "REVIEW_ONLY"
                and event["supersedes_event_id"] is not None
                and event["reason"] is not None
            )
        if event["free_text_only"]:
            valid = False
        elif not event["structured_surface"]:
            valid = valid and (
                event_type == "PREDICATE_CANDIDATE"
                and event["policy_effect"] == "REVIEW_ONLY"
            )
        if not valid:
            raise PortfolioMandateContractError(
                prefix,
                "producer, audit fields, source surface, and policy effect are invalid",
            )


def _timestamp(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def _json_path(parts: Iterable[str | int]) -> str:
    result = ""
    for part in parts:
        if isinstance(part, int):
            result += f"[{part}]"
        else:
            result += ("." if result else "") + str(part)
    return result or "$"
