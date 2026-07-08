from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from typing import Literal

SellAiBriefCandidateRole = Literal[
    "actionable", "broker_state_review", "excluded_hold", "unsupported"
]

_ACTIONABLE_SELL_ACTIONS = frozenset({"SELL", "SELL_PARTIAL", "REVIEW"})


@dataclass(frozen=True)
class SellAiBriefCandidate:
    ticker: str
    sell_action: str
    role: SellAiBriefCandidateRole
    reason: str
    deterministic_reasons: list[str]
    row: Mapping[str, object]


@dataclass(frozen=True)
class SellAiBriefClassification:
    actionable: list[SellAiBriefCandidate]
    broker_state_review: list[SellAiBriefCandidate]
    excluded_hold: list[SellAiBriefCandidate]
    unsupported: list[SellAiBriefCandidate]
    system_issues: list[dict[str, object]]


def sell_reasons(row: Mapping[str, object]) -> list[str]:
    raw_reasons = row.get("reasons")
    if not isinstance(raw_reasons, list):
        return []
    return [str(reason).strip() for reason in raw_reasons if str(reason).strip()]


def classify_sell_ai_brief_row(
    row: Mapping[str, object],
) -> tuple[SellAiBriefCandidate, dict[str, object] | None]:
    ticker = str(row.get("ticker") or "").strip()
    sell_action = str(row.get("action") or row.get("sell_action") or "").strip().upper()
    deterministic_reasons = sell_reasons(row)

    if not ticker:
        reason = "sell row ticker is required"
        return (
            SellAiBriefCandidate(
                ticker="",
                sell_action=sell_action,
                role="unsupported",
                reason=reason,
                deterministic_reasons=deterministic_reasons,
                row=row,
            ),
            {
                "ticker": None,
                "code": "sell_row_ticker_required",
                "severity": "WARN",
                "message": reason,
            },
        )

    broker_state = str(row.get("broker_state") or "").strip()
    if broker_state == "not_seen_in_toss":
        return (
            SellAiBriefCandidate(
                ticker=ticker,
                sell_action=sell_action,
                role="broker_state_review",
                reason="holding not seen in latest Toss snapshot",
                deterministic_reasons=deterministic_reasons,
                row=row,
            ),
            None,
        )

    if sell_action in _ACTIONABLE_SELL_ACTIONS:
        return (
            SellAiBriefCandidate(
                ticker=ticker,
                sell_action=sell_action,
                role="actionable",
                reason=f"sell report action was {sell_action}",
                deterministic_reasons=deterministic_reasons,
                row=row,
            ),
            None,
        )

    if sell_action == "HOLD":
        return (
            SellAiBriefCandidate(
                ticker=ticker,
                sell_action=sell_action,
                role="excluded_hold",
                reason="sell report action was HOLD",
                deterministic_reasons=deterministic_reasons,
                row=row,
            ),
            None,
        )

    reason = f"unsupported sell action {sell_action or '-'}"
    return (
        SellAiBriefCandidate(
            ticker=ticker,
            sell_action=sell_action,
            role="unsupported",
            reason=reason,
            deterministic_reasons=deterministic_reasons,
            row=row,
        ),
        {
            "ticker": ticker,
            "code": "unsupported_sell_action",
            "severity": "WARN",
            "message": reason,
        },
    )


def classify_sell_ai_brief_rows(
    rows: Iterable[Mapping[str, object]],
) -> SellAiBriefClassification:
    actionable: list[SellAiBriefCandidate] = []
    broker_state_review: list[SellAiBriefCandidate] = []
    excluded_hold: list[SellAiBriefCandidate] = []
    unsupported: list[SellAiBriefCandidate] = []
    system_issues: list[dict[str, object]] = []
    for row in rows:
        classified, issue = classify_sell_ai_brief_row(row)
        if classified.role == "actionable":
            actionable.append(classified)
        elif classified.role == "broker_state_review":
            broker_state_review.append(classified)
        elif classified.role == "excluded_hold":
            excluded_hold.append(classified)
        else:
            unsupported.append(classified)
        if issue is not None:
            system_issues.append(issue)
    return SellAiBriefClassification(
        actionable=actionable,
        broker_state_review=broker_state_review,
        excluded_hold=excluded_hold,
        unsupported=unsupported,
        system_issues=system_issues,
    )


__all__ = [
    "SellAiBriefCandidate",
    "SellAiBriefCandidateRole",
    "SellAiBriefClassification",
    "classify_sell_ai_brief_row",
    "classify_sell_ai_brief_rows",
    "sell_reasons",
]
