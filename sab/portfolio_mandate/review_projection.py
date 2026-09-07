"""Read-only A1 joins for local review; never publish a directional decision."""

from __future__ import annotations

from datetime import datetime
from typing import Literal, TypedDict

from .contracts import (
    PortfolioMandateContractError,
    validate_portfolio_mandate_a1_fixture,
)


class MandateReviewRow(TypedDict):
    slice_id: str
    instrument_id: str
    mandate_version_id: str | None
    horizon: str | None
    approval_state: str | None
    issue_codes: list[str]
    current_authority_event_ids: list[str]
    superseded_event_count: int
    action: None


class MandateReviewProjection(TypedDict):
    schema_version: Literal["portfolio-mandate-review.a1"]
    mode: Literal["LOCAL_ONLY"]
    as_of: str
    advice_enabled: Literal[False]
    unallocated_position_count: int
    rows: list[MandateReviewRow]


def project_mandate_review_a1(
    value: object, *, as_of: datetime
) -> MandateReviewProjection:
    """Join exact A1 versions/slices/seals and respect visible corrections.

    Input must be one coherent snapshot. The A1 watermark is opaque and contains
    no freshness timestamp, so this projection cannot turn approval or predicate
    authority into active advice. Private quantities, actors and prose stay out.
    """
    if as_of.tzinfo is None or as_of.utcoffset() is None:
        raise ValueError("review clock must include a UTC offset")
    try:
        fixture = validate_portfolio_mandate_a1_fixture(value)
    except PortfolioMandateContractError, ValueError, TypeError, KeyError:
        # Schema errors can include private input values; callers see a fixed code.
        raise ValueError("INVALID_A1_REVIEW_INPUT") from None
    core = fixture["position_slice_core"]
    versions = {
        v["mandate_version_id"]: v for v in fixture["mandate_version_core"]["versions"]
    }
    positions = {p["broker_position_id"]: p for p in core["broker_positions"]}
    allocations = {a["allocation_id"]: a for a in core["allocations"] if a["active"]}
    visible_seals = {
        seal["evidence_seal_id"]
        for seal in fixture["stable_identity"]["evidence_seals"]
        if datetime.fromisoformat(seal["sealed_at"]) <= as_of
        and datetime.fromisoformat(seal["source_event_time"]) <= as_of
    }
    visible_events = [
        e
        for e in fixture["predicate_authority_core"]["events"]
        if datetime.fromisoformat(e["created_at"]) <= as_of
        and e["evidence_seal_id"] in visible_seals
    ]
    superseded = {
        e["supersedes_event_id"]
        for e in visible_events
        if e["supersedes_event_id"] is not None
    }
    rows: list[MandateReviewRow] = []
    for part in sorted(core["slices"], key=lambda item: item["slice_id"]):
        allocation = allocations.get(part["allocation_id"])
        if allocation is None:
            continue
        position = positions[allocation["broker_position_id"]]
        version = versions.get(part["mandate_version_id"] or "")
        issues = ["BROKER_FRESHNESS_UNPROVEN", "PRODUCTION_ADVICE_NOT_CONNECTED"]
        latest_snapshot = max(
            s["snapshot_version"]
            for s in core["snapshots"]
            if s["broker_position_id"] == allocation["broker_position_id"]
        )
        if allocation["snapshot_version"] != latest_snapshot:
            issues.append("ALLOCATION_REBASE_REQUIRED")
        if not allocation["decision_eligible"] or not part["decision_eligible"]:
            issues.append("SLICE_INELIGIBLE")
        if version is None or part["classification_state"] != "ACTIVE":
            issues.append("UNCLASSIFIED_NO_ADVICE")
        elif (
            version["approval_state"] != "APPROVED"
            or version["classification_state"] != "ACTIVE"
        ):
            issues.append("MANDATE_NOT_ACTIVE")
        elif (
            version["effective_from"] is None
            or datetime.fromisoformat(version["effective_from"]) > as_of
            or (
                version["effective_to"] is not None
                and datetime.fromisoformat(version["effective_to"]) <= as_of
            )
            or version["approved_at"] is None
            or datetime.fromisoformat(version["approved_at"]) > as_of
        ):
            issues.append("MANDATE_OUTSIDE_EFFECTIVE_WINDOW")
        events = [
            e
            for e in visible_events
            if e["mandate_version_id"] == part["mandate_version_id"]
        ]
        current = [
            e
            for e in events
            if e["predicate_authority_event_id"] not in superseded
            and e["policy_effect"] in {"SELL_ELIGIBLE", "REVIEW_ONLY"}
            and e["event_type"] != "PREDICATE_SUPERSEDED"
        ]
        if current:
            issues.append("PREDICATE_REVIEW_REQUIRED")
        else:
            issues.append("CURRENT_PREDICATE_EVIDENCE_MISSING")
        rows.append(
            MandateReviewRow(
                slice_id=part["slice_id"],
                instrument_id=position["instrument_id"],
                mandate_version_id=part["mandate_version_id"],
                horizon=version["horizon"] if version else None,
                approval_state=version["approval_state"] if version else None,
                issue_codes=issues,
                current_authority_event_ids=sorted(
                    e["predicate_authority_event_id"] for e in current
                ),
                superseded_event_count=sum(
                    e["predicate_authority_event_id"] in superseded for e in events
                ),
                action=None,
            )
        )
    return MandateReviewProjection(
        schema_version="portfolio-mandate-review.a1",
        mode="LOCAL_ONLY",
        as_of=as_of.isoformat(),
        advice_enabled=False,
        unallocated_position_count=len(
            set(positions) - {a["broker_position_id"] for a in allocations.values()}
        ),
        rows=rows,
    )
