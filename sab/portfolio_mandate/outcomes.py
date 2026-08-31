"""Synthetic-only Portfolio Outcome O1 matching and audit contracts.

This module has no broker, provider, persistence, writer, or attribution adapter.
It accepts already-synthetic values and exposes deterministic validation helpers.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from copy import deepcopy
from datetime import datetime
from decimal import Decimal
from pathlib import Path
from typing import Any, Literal, TypedDict, cast

from jsonschema import (  # type: ignore[import-untyped]
    Draft202012Validator,
    FormatChecker,
)

SCHEMA_VERSION = "portfolio-outcome.o1"
_SCHEMA_PATH = (
    Path(__file__).parents[2] / "schemas" / "portfolio-outcome.o1.schema.json"
)


class PortfolioOutcomeContractError(ValueError):
    """An Outcome O1 value failed validation at an exact contract path."""

    def __init__(self, path: str, message: str) -> None:
        self.path = path
        self.message = message
        super().__init__(f"{path}: {message}")


class OutcomeProposalO1(TypedDict):
    outcome_lineage_id: str
    execution_lineage_id: str
    status: Literal["UNLINKED", "MATCH_PROPOSED", "AMBIGUOUS"]
    candidate_decision_ids: list[str]
    total_filled_quantity: str


class PublicOutcomeProjectionO1(TypedDict):
    outcome_lineage_id: str
    status: str
    decision_id: str | None
    feedback_reason: str | None
    last_event_id: str
    last_event_at: str


PortfolioOutcomeO1Fixture = dict[str, Any]


def validate_portfolio_outcome_o1_fixture(
    value: Mapping[str, Any],
) -> PortfolioOutcomeO1Fixture:
    """Validate the shared synthetic fixture and all cross-record invariants."""

    fixture = dict(value)
    _validate_schema(fixture, _fixture_validator())
    decisions = cast(list[dict[str, Any]], fixture["decisions"])
    executions = cast(list[dict[str, Any]], fixture["execution_lineages"])
    events = cast(list[dict[str, Any]], fixture["user_events"])

    _validate_capability_and_matching_inputs(
        fixture["capability"], decisions, executions
    )
    proposals = propose_outcome_matches(decisions, executions)
    if list(proposals) != fixture["expected_proposals"]:
        raise PortfolioOutcomeContractError(
            "expected_proposals",
            "must equal deterministic synthetic matcher output",
        )

    known_decisions = {item["decision_id"] for item in decisions}
    _validate_event_history(events, proposals, known_decisions)

    projection = project_public_outcome_events(events)
    if list(projection) != fixture["expected_public_projection"]:
        raise PortfolioOutcomeContractError(
            "expected_public_projection",
            "must equal the latest append-only user event projection",
        )
    validate_public_outcome_projection(fixture["expected_public_projection"])
    return fixture


def propose_outcome_matches(
    decisions: Sequence[Mapping[str, Any]],
    execution_lineages: Sequence[Mapping[str, Any]],
) -> tuple[OutcomeProposalO1, ...]:
    """Propose links using every exact synthetic execution constraint.

    The function can only emit ``UNLINKED``, ``MATCH_PROPOSED``, or ``AMBIGUOUS``.
    A user event is required for ``MATCH_CONFIRMED`` or any later status.
    """

    _validate_schema(
        {"decisions": list(decisions), "execution_lineages": list(execution_lineages)},
        _matching_input_validator(),
    )
    _validate_matching_input_invariants(decisions, execution_lineages)
    proposals: list[OutcomeProposalO1] = []
    for execution in execution_lineages:
        fills = cast(Sequence[Mapping[str, Any]], execution["fills"])
        total_quantity = sum(
            (Decimal(cast(str, fill["quantity"])) for fill in fills), Decimal(0)
        )
        candidates = sorted(
            cast(str, decision["decision_id"])
            for decision in decisions
            if _matches_decision(decision, execution, fills, total_quantity)
        )
        status: Literal["UNLINKED", "MATCH_PROPOSED", "AMBIGUOUS"]
        if not candidates:
            status = "UNLINKED"
        elif len(candidates) == 1:
            status = "MATCH_PROPOSED"
        else:
            status = "AMBIGUOUS"
        proposals.append(
            {
                "outcome_lineage_id": cast(str, execution["outcome_lineage_id"]),
                "execution_lineage_id": cast(str, execution["execution_lineage_id"]),
                "status": status,
                "candidate_decision_ids": candidates,
                "total_filled_quantity": f"{total_quantity:.6f}",
            }
        )
    return tuple(proposals)


def append_user_outcome_event(
    existing_events: Sequence[Mapping[str, Any]],
    new_event: Mapping[str, Any],
    *,
    decisions: Sequence[Mapping[str, Any]],
    execution_lineages: Sequence[Mapping[str, Any]],
) -> tuple[dict[str, Any], ...]:
    """Recompute proposals and return a validated append-only history copy."""

    copied = [deepcopy(dict(item)) for item in existing_events]
    copied.append(deepcopy(dict(new_event)))
    _validate_schema(copied, _user_events_validator())
    proposals = propose_outcome_matches(decisions, execution_lineages)
    known_decisions = {cast(str, decision["decision_id"]) for decision in decisions}
    _validate_event_history(copied, proposals, known_decisions)
    return tuple(copied)


def project_public_outcome_events(
    events: Sequence[Mapping[str, Any]],
) -> tuple[PublicOutcomeProjectionO1, ...]:
    """Project the latest event per lineage without private feedback notes."""

    latest: dict[str, Mapping[str, Any]] = {}
    for event in events:
        latest[cast(str, event["outcome_lineage_id"])] = event
    projected = tuple(
        PublicOutcomeProjectionO1(
            outcome_lineage_id=lineage_id,
            status=cast(str, event["status"]),
            decision_id=cast(str | None, event["decision_id"]),
            feedback_reason=cast(str | None, event["feedback_reason"]),
            last_event_id=cast(str, event["outcome_event_id"]),
            last_event_at=cast(str, event["created_at"]),
        )
        for lineage_id, event in latest.items()
    )
    validate_public_outcome_projection(list(projected))
    return projected


def validate_public_outcome_projection(
    value: Sequence[Mapping[str, Any]],
) -> list[PublicOutcomeProjectionO1]:
    """Validate the strict public shape; private notes and raw IDs are rejected."""

    copied = [dict(item) for item in value]
    _validate_schema(copied, _public_projection_validator())
    return cast(list[PublicOutcomeProjectionO1], copied)


def _matches_decision(
    decision: Mapping[str, Any],
    execution: Mapping[str, Any],
    fills: Sequence[Mapping[str, Any]],
    total_quantity: Decimal,
) -> bool:
    if (
        decision["instrument_id"] != execution["instrument_id"]
        or decision["side"] != execution["side"]
    ):
        return False
    slice_matches = (
        decision["slice_id"] is not None
        and execution["candidate_id"] is None
        and decision["slice_id"] in execution["slice_candidate_ids"]
    )
    candidate_matches = (
        decision["candidate_id"] is not None
        and not execution["slice_candidate_ids"]
        and decision["candidate_id"] == execution["candidate_id"]
    )
    if not (slice_matches or candidate_matches):
        return False
    valid_from = _timestamp(cast(str, decision["valid_from"]))
    valid_until = _timestamp(cast(str, decision["valid_until"]))
    minimum_price = Decimal(cast(Mapping[str, str], decision["price_range"])["minimum"])
    maximum_price = Decimal(cast(Mapping[str, str], decision["price_range"])["maximum"])
    minimum_quantity = Decimal(
        cast(Mapping[str, str], decision["quantity_range"])["minimum"]
    )
    maximum_quantity = Decimal(
        cast(Mapping[str, str], decision["quantity_range"])["maximum"]
    )
    return minimum_quantity <= total_quantity <= maximum_quantity and all(
        valid_from <= _timestamp(cast(str, fill["executed_at"])) <= valid_until
        and minimum_price <= Decimal(cast(str, fill["price"])) <= maximum_price
        for fill in fills
    )


def _validate_capability_and_matching_inputs(
    capability: Mapping[str, Any],
    decisions: Sequence[Mapping[str, Any]],
    executions: Sequence[Mapping[str, Any]],
) -> None:
    retention = cast(Mapping[str, str], capability["retention_window"])
    retention_start = _timestamp(retention["starts_at"])
    retention_end = _timestamp(retention["ends_at"])
    if retention_start >= retention_end:
        raise PortfolioOutcomeContractError(
            "capability.retention_window.ends_at", "must be later than starts_at"
        )

    _validate_matching_input_invariants(
        decisions,
        executions,
        retention_start=retention_start,
        retention_end=retention_end,
    )


def _validate_matching_input_invariants(
    decisions: Sequence[Mapping[str, Any]],
    executions: Sequence[Mapping[str, Any]],
    *,
    retention_start: datetime | None = None,
    retention_end: datetime | None = None,
) -> None:

    decision_ids: set[str] = set()
    for index, decision in enumerate(decisions):
        decision_id = cast(str, decision["decision_id"])
        if decision_id in decision_ids:
            raise PortfolioOutcomeContractError(
                f"decisions[{index}].decision_id", "must be unique"
            )
        decision_ids.add(decision_id)
        if _timestamp(cast(str, decision["valid_from"])) >= _timestamp(
            cast(str, decision["valid_until"])
        ):
            raise PortfolioOutcomeContractError(
                f"decisions[{index}].valid_until", "must be later than valid_from"
            )
        for range_name in ("price_range", "quantity_range"):
            value = cast(Mapping[str, str], decision[range_name])
            minimum = Decimal(value["minimum"])
            maximum = Decimal(value["maximum"])
            if minimum <= 0 or maximum < minimum:
                raise PortfolioOutcomeContractError(
                    f"decisions[{index}].{range_name}",
                    "must be positive and ordered",
                )

    execution_ids: set[str] = set()
    outcome_ids: set[str] = set()
    fill_identities: set[tuple[str, str, str]] = set()
    for execution_index, execution in enumerate(executions):
        execution_id = cast(str, execution["execution_lineage_id"])
        outcome_id = cast(str, execution["outcome_lineage_id"])
        if execution_id in execution_ids:
            raise PortfolioOutcomeContractError(
                f"execution_lineages[{execution_index}].execution_lineage_id",
                "must be unique",
            )
        if outcome_id in outcome_ids:
            raise PortfolioOutcomeContractError(
                f"execution_lineages[{execution_index}].outcome_lineage_id",
                "must be unique",
            )
        execution_ids.add(execution_id)
        outcome_ids.add(outcome_id)

        orders = cast(Sequence[Mapping[str, Any]], execution["orders"])
        order_by_id: dict[str, Mapping[str, Any]] = {}
        prior_order: Mapping[str, Any] | None = None
        for order_index, order in enumerate(orders):
            order_id = cast(str, order["broker_order_id"])
            if order_id in order_by_id:
                raise PortfolioOutcomeContractError(
                    f"execution_lineages[{execution_index}].orders[{order_index}]"
                    ".broker_order_id",
                    "must be unique within the execution lineage",
                )
            if prior_order is None:
                valid_order_link = order["supersedes_broker_order_id"] is None
            else:
                valid_order_link = order["supersedes_broker_order_id"] == prior_order[
                    "broker_order_id"
                ] and _timestamp(cast(str, order["created_at"])) > _timestamp(
                    cast(str, prior_order["created_at"])
                )
            if not valid_order_link:
                raise PortfolioOutcomeContractError(
                    f"execution_lineages[{execution_index}].orders[{order_index}]"
                    ".supersedes_broker_order_id",
                    "must form an ordered direct cancel/reorder lineage",
                )
            order_by_id[order_id] = order
            prior_order = order

        account_ref_hash = cast(str, execution["account_ref_hash"])
        for fill_index, fill in enumerate(
            cast(Sequence[Mapping[str, Any]], execution["fills"])
        ):
            prefix = f"execution_lineages[{execution_index}].fills[{fill_index}]"
            fill_order = order_by_id.get(cast(str, fill["broker_order_id"]))
            if fill_order is None:
                raise PortfolioOutcomeContractError(
                    f"{prefix}.broker_order_id", "must reference this execution lineage"
                )
            if _timestamp(cast(str, fill["executed_at"])) < _timestamp(
                cast(str, fill_order["created_at"])
            ):
                raise PortfolioOutcomeContractError(
                    f"{prefix}.executed_at", "must not precede its broker order"
                )
            fill_time = _timestamp(cast(str, fill["executed_at"]))
            if (
                retention_start is not None
                and retention_end is not None
                and not retention_start <= fill_time <= retention_end
            ):
                raise PortfolioOutcomeContractError(
                    f"{prefix}.executed_at", "must be inside synthetic retention window"
                )
            if (
                Decimal(cast(str, fill["price"])) <= 0
                or Decimal(cast(str, fill["quantity"])) <= 0
            ):
                raise PortfolioOutcomeContractError(
                    prefix, "price and quantity must be positive"
                )
            identity = (
                cast(str, fill["broker_order_id"]),
                cast(str, fill["broker_fill_id"]),
                account_ref_hash,
            )
            if identity in fill_identities:
                raise PortfolioOutcomeContractError(
                    prefix,
                    "broker fill identity (order, fill, account hash) must be unique",
                )
            fill_identities.add(identity)


def _validate_event_history(
    events: Sequence[Mapping[str, Any]],
    proposals: Sequence[Mapping[str, Any]],
    known_decisions: set[str],
) -> None:
    proposal_by_lineage = {
        cast(str, proposal["outcome_lineage_id"]): proposal for proposal in proposals
    }
    event_ids: set[str] = set()
    heads: dict[str, Mapping[str, Any]] = {}
    for index, event in enumerate(events):
        prefix = f"user_events[{index}]"
        event_id = cast(str, event["outcome_event_id"])
        lineage_id = cast(str, event["outcome_lineage_id"])
        if event_id in event_ids:
            raise PortfolioOutcomeContractError(
                f"{prefix}.outcome_event_id", "must be unique and immutable"
            )
        proposal = proposal_by_lineage.get(lineage_id)
        if proposal is None:
            raise PortfolioOutcomeContractError(
                f"{prefix}.outcome_lineage_id", "must reference a known outcome lineage"
            )
        event_ids.add(event_id)

        decision_id = cast(str | None, event["decision_id"])
        if decision_id is not None and decision_id not in known_decisions:
            raise PortfolioOutcomeContractError(
                f"{prefix}.decision_id", "must reference a known synthetic decision"
            )
        if (
            decision_id is not None
            and decision_id not in proposal["candidate_decision_ids"]
        ):
            raise PortfolioOutcomeContractError(
                f"{prefix}.decision_id",
                "must belong to this outcome lineage deterministic proposal",
            )
        confirmed_quantity = cast(str | None, event["confirmed_quantity"])
        if confirmed_quantity is not None and Decimal(confirmed_quantity) <= 0:
            raise PortfolioOutcomeContractError(
                f"{prefix}.confirmed_quantity", "must be positive when present"
            )
        status = cast(str, event["status"])
        linked_statuses = {"MATCH_CONFIRMED", "EXECUTED", "PARTIALLY_EXECUTED"}
        if status in linked_statuses and (
            decision_id is None or confirmed_quantity is None
        ):
            raise PortfolioOutcomeContractError(
                prefix, "linked execution status requires decision and quantity"
            )
        if status in {"DISMISSED", "UNKNOWN"} and (
            decision_id is not None or confirmed_quantity is not None
        ):
            raise PortfolioOutcomeContractError(
                prefix, "DISMISSED and UNKNOWN require null decision and quantity"
            )
        prior = heads.get(lineage_id)
        if prior is None:
            if event["supersedes_event_id"] is not None:
                raise PortfolioOutcomeContractError(
                    f"{prefix}.supersedes_event_id",
                    "must reference the current head of the same outcome lineage",
                )
            if (
                event["event_kind"] != "MATCH_CONFIRMATION"
                or event["status"] != "MATCH_CONFIRMED"
                or decision_id is None
                or confirmed_quantity is None
                or confirmed_quantity != proposal["total_filled_quantity"]
                or event["feedback_reason"] is not None
                or event["feedback_note_private"] is not None
            ):
                raise PortfolioOutcomeContractError(
                    prefix,
                    "first lineage event must be a user MATCH_CONFIRMED snapshot",
                )
        else:
            if event["event_kind"] == "MATCH_CONFIRMATION":
                raise PortfolioOutcomeContractError(
                    f"{prefix}.event_kind", "cannot confirm the same lineage twice"
                )
            if event["supersedes_event_id"] != prior["outcome_event_id"]:
                raise PortfolioOutcomeContractError(
                    f"{prefix}.supersedes_event_id",
                    "must reference the current head of the same outcome lineage",
                )
            if _timestamp(cast(str, event["created_at"])) <= _timestamp(
                cast(str, prior["created_at"])
            ):
                raise PortfolioOutcomeContractError(
                    f"{prefix}.created_at", "must be later than the superseded event"
                )
            if event["event_kind"] == "FEEDBACK" and (
                event["feedback_reason"] is None
                or any(
                    event[field] != prior[field]
                    for field in ("status", "decision_id", "confirmed_quantity")
                )
            ):
                raise PortfolioOutcomeContractError(
                    prefix,
                    "feedback must preserve matching state and select one reason",
                )

        if (
            event["feedback_reason"] is None
            and event["feedback_note_private"] is not None
        ):
            raise PortfolioOutcomeContractError(
                f"{prefix}.feedback_note_private", "requires feedback_reason"
            )
        if event["feedback_reason"] == "OTHER" and not cast(
            str | None, event["feedback_note_private"]
        ):
            raise PortfolioOutcomeContractError(
                f"{prefix}.feedback_note_private",
                "must be nonempty when feedback_reason is OTHER",
            )
        heads[lineage_id] = event


def _fixture_validator() -> Draft202012Validator:
    return _validator(_schema())


def _matching_input_validator() -> Draft202012Validator:
    schema = _schema()
    return _validator(
        {
            "$schema": schema["$schema"],
            "$defs": schema["$defs"],
            "type": "object",
            "additionalProperties": False,
            "required": ["decisions", "execution_lineages"],
            "properties": {
                "decisions": schema["properties"]["decisions"],
                "execution_lineages": schema["properties"]["execution_lineages"],
            },
        }
    )


def _user_events_validator() -> Draft202012Validator:
    schema = _schema()
    return _validator(
        {
            "$schema": schema["$schema"],
            "$defs": schema["$defs"],
            "type": "array",
            "items": {"$ref": "#/$defs/userEvent"},
        }
    )


def _public_projection_validator() -> Draft202012Validator:
    schema = _schema()
    return _validator(
        {
            "$schema": schema["$schema"],
            "$defs": schema["$defs"],
            "type": "array",
            "items": {"$ref": "#/$defs/publicProjection"},
        }
    )


def _schema() -> dict[str, Any]:
    import json

    value = json.loads(_SCHEMA_PATH.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise PortfolioOutcomeContractError("$", "schema must be an object")
    Draft202012Validator.check_schema(value)
    return value


def _validator(schema: Mapping[str, Any]) -> Draft202012Validator:
    return Draft202012Validator(schema, format_checker=FormatChecker())


def _validate_schema(value: object, validator: Draft202012Validator) -> None:
    errors = sorted(
        validator.iter_errors(value), key=lambda error: _json_path(error.path)
    )
    if not errors:
        return
    error = errors[0]
    path = _json_path(error.absolute_path)
    if error.validator == "additionalProperties":
        message = error.message
    else:
        message = error.message
    raise PortfolioOutcomeContractError(path, message)


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


__all__ = [
    "OutcomeProposalO1",
    "PortfolioOutcomeContractError",
    "PortfolioOutcomeO1Fixture",
    "PublicOutcomeProjectionO1",
    "append_user_outcome_event",
    "project_public_outcome_events",
    "propose_outcome_matches",
    "validate_portfolio_outcome_o1_fixture",
    "validate_public_outcome_projection",
]
