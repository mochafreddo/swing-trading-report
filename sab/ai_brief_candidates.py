from __future__ import annotations

import math
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from typing import Literal

AiBriefCandidateRole = Literal[
    "executable", "blocked_but_valid", "watch_only", "excluded"
]

_PORTFOLIO_BLOCK_REASON_PREFIXES = (
    "portfolio exposure cap reached",
    "portfolio market cap reached",
    "portfolio max active holdings reached",
)
_RISK_ALIGNMENT_REASON_TOKEN = "risk_alignment"
_TIGHT_STOP_VS_VOLATILITY_REASON_TOKEN = "tight_stop_vs_volatility"
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
    executable: list[AiBriefEntryCandidate]
    blocked_but_valid: list[AiBriefEntryCandidate]
    watch_only: list[AiBriefEntryCandidate]
    excluded: list[AiBriefEntryCandidate]

    @property
    def recommendable(self) -> list[AiBriefEntryCandidate]:
        return [*self.executable, *self.blocked_but_valid]


def entry_reasons(entry: Mapping[str, object]) -> list[str]:
    raw_reasons = entry.get("reasons")
    if not isinstance(raw_reasons, list):
        return []
    return [str(reason).strip() for reason in raw_reasons if str(reason).strip()]


def _has_any_reason_prefix(reasons: Iterable[str], prefixes: Iterable[str]) -> bool:
    return any(
        reason.lower().startswith(prefix) for reason in reasons for prefix in prefixes
    )


def _has_reason_text(reasons: Iterable[str], text: str) -> bool:
    return any(text in reason.lower() for reason in reasons)


def _has_risk_alignment_tight_stop_reason(reasons: Iterable[str]) -> bool:
    return any(
        _RISK_ALIGNMENT_REASON_TOKEN in reason.lower()
        and _TIGHT_STOP_VS_VOLATILITY_REASON_TOKEN in reason.lower()
        for reason in reasons
    )


def _base_gate_failure(entry: Mapping[str, object]) -> str | None:
    entry_state = str(entry.get("entry_state") or "").strip().upper()
    entry_price_status = str(entry.get("entry_price_status") or "").strip().lower()
    failures: list[str] = []
    if entry_state != "READY":
        failures.append(f"entry_state={entry_state or '-'}")
    if entry_price_status != "available" and not _legacy_entry_price_available(entry):
        failures.append(f"entry_price_status={entry_price_status or '-'}")
    if failures:
        return "entry row failed AI brief base gates: " + ", ".join(failures)
    return None


def _legacy_entry_price_available(entry: Mapping[str, object]) -> bool:
    if "entry_price_status" in entry:
        return False
    entry_price = entry.get("entry_price")
    if isinstance(entry_price, bool) or not isinstance(entry_price, (int, float)):
        return False
    return math.isfinite(float(entry_price)) and float(entry_price) > 0


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
            role="executable",
            reason="entry report action was ENTER",
            entry=entry,
        )
    if action == "SKIP" and _has_any_reason_prefix(
        reasons, _PORTFOLIO_BLOCK_REASON_PREFIXES
    ):
        return AiBriefEntryCandidate(
            ticker=ticker,
            action=action,
            role="blocked_but_valid",
            reason="portfolio policy blocked automatic entry",
            entry=entry,
        )
    if action == "REVIEW" and _has_risk_alignment_tight_stop_reason(reasons):
        return AiBriefEntryCandidate(
            ticker=ticker,
            action=action,
            role="blocked_but_valid",
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
    if action in {"SKIP", "REVIEW"}:
        return AiBriefEntryCandidate(
            ticker=ticker,
            action=action,
            role="excluded",
            reason=f"action {action} did not match an AI brief inclusion rule",
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
    executable: list[AiBriefEntryCandidate] = []
    blocked_but_valid: list[AiBriefEntryCandidate] = []
    watch_only: list[AiBriefEntryCandidate] = []
    excluded: list[AiBriefEntryCandidate] = []
    for row in rows:
        classified = classify_ai_brief_entry_row(row)
        if classified.role == "executable":
            executable.append(classified)
        elif classified.role == "blocked_but_valid":
            blocked_but_valid.append(classified)
        elif classified.role == "watch_only":
            watch_only.append(classified)
        else:
            excluded.append(classified)
    return AiBriefEntryClassification(
        executable=executable,
        blocked_but_valid=blocked_but_valid,
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
