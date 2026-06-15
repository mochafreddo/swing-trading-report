from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from typing import Literal

AiBriefCandidateRole = Literal["recommendable", "watch_only", "excluded"]

_PORTFOLIO_CAP_REASON_PREFIX = "portfolio market cap reached"
_RISK_ALIGNMENT_REASON = "risk_alignment=tight_stop_vs_volatility"
_HYBRID_TRIGGER_GUARD_REASON = "hybrid trigger guard failed"


@dataclass(frozen=True)
class AiBriefEntryCandidate:
    ticker: str
    action: str
    role: AiBriefCandidateRole
    reason: str
    entry: Mapping[str, object]


@dataclass(frozen=True)
class AiBriefEntryClassification:
    recommendable: list[AiBriefEntryCandidate]
    watch_only: list[AiBriefEntryCandidate]
    excluded: list[AiBriefEntryCandidate]


def entry_reasons(entry: Mapping[str, object]) -> list[str]:
    raw_reasons = entry.get("reasons")
    if not isinstance(raw_reasons, list):
        return []
    return [str(reason).strip() for reason in raw_reasons if str(reason).strip()]


def _has_reason_prefix(reasons: Iterable[str], prefix: str) -> bool:
    return any(reason.lower().startswith(prefix) for reason in reasons)


def _has_reason_text(reasons: Iterable[str], text: str) -> bool:
    return any(text in reason.lower() for reason in reasons)


def _base_gate_failure(entry: Mapping[str, object]) -> str | None:
    entry_state = str(entry.get("entry_state") or "").strip().upper()
    entry_price_status = str(entry.get("entry_price_status") or "").strip().lower()
    failures: list[str] = []
    if entry_state != "READY":
        failures.append(f"entry_state={entry_state or '-'}")
    if entry_price_status != "available":
        failures.append(f"entry_price_status={entry_price_status or '-'}")
    if failures:
        return "entry row failed AI brief base gates: " + ", ".join(failures)
    return None


def classify_ai_brief_entry_row(entry: Mapping[str, object]) -> AiBriefEntryCandidate:
    ticker = str(entry.get("ticker") or "").strip()
    action = str(entry.get("action") or "").strip().upper()
    reasons = entry_reasons(entry)

    if not ticker:
        return AiBriefEntryCandidate(
            ticker="",
            action=action,
            role="excluded",
            reason="entry row ticker is required",
            entry=entry,
        )

    base_gate_failure = _base_gate_failure(entry)
    if base_gate_failure is not None:
        return AiBriefEntryCandidate(
            ticker=ticker,
            action=action,
            role="excluded",
            reason=base_gate_failure,
            entry=entry,
        )

    if action == "ENTER":
        return AiBriefEntryCandidate(
            ticker=ticker,
            action=action,
            role="recommendable",
            reason="entry report action was ENTER",
            entry=entry,
        )
    if action == "SKIP" and _has_reason_prefix(reasons, _PORTFOLIO_CAP_REASON_PREFIX):
        return AiBriefEntryCandidate(
            ticker=ticker,
            action=action,
            role="recommendable",
            reason="portfolio policy blocked automatic entry",
            entry=entry,
        )
    if action == "REVIEW" and _has_reason_text(reasons, _RISK_ALIGNMENT_REASON):
        return AiBriefEntryCandidate(
            ticker=ticker,
            action=action,
            role="recommendable",
            reason="risk alignment requires manual review",
            entry=entry,
        )
    if action == "SKIP" and _has_reason_text(reasons, _HYBRID_TRIGGER_GUARD_REASON):
        return AiBriefEntryCandidate(
            ticker=ticker,
            action=action,
            role="watch_only",
            reason="entry trigger is pending re-confirmation",
            entry=entry,
        )

    return AiBriefEntryCandidate(
        ticker=ticker,
        action=action,
        role="excluded",
        reason=f"unsupported action {action or '-'} for AI brief role",
        entry=entry,
    )


def classify_ai_brief_entry_rows(
    rows: Iterable[Mapping[str, object]],
) -> AiBriefEntryClassification:
    recommendable: list[AiBriefEntryCandidate] = []
    watch_only: list[AiBriefEntryCandidate] = []
    excluded: list[AiBriefEntryCandidate] = []
    for row in rows:
        classified = classify_ai_brief_entry_row(row)
        if classified.role == "recommendable":
            recommendable.append(classified)
        elif classified.role == "watch_only":
            watch_only.append(classified)
        else:
            excluded.append(classified)
    return AiBriefEntryClassification(
        recommendable=recommendable,
        watch_only=watch_only,
        excluded=excluded,
    )


__all__ = [
    "AiBriefCandidateRole",
    "AiBriefEntryCandidate",
    "AiBriefEntryClassification",
    "classify_ai_brief_entry_row",
    "classify_ai_brief_entry_rows",
    "entry_reasons",
]
