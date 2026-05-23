from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any, TypedDict

BRIEF_STATE_NO_SIGNAL = "NO_SIGNAL"
BRIEF_STATE_FINAL_JUDGMENT = "FINAL_JUDGMENT"
BRIEF_STATE_NEEDS_REVIEW_WEAK_NEWS = "NEEDS_REVIEW_WEAK_NEWS"

BRIEF_REASON_NO_ENTER_CANDIDATES = "no_enter_candidates"
BRIEF_REASON_SOURCE_BACKED_FINAL = "source_backed_final"
BRIEF_REASON_WEAK_NEWS_COVERAGE = "weak_news_coverage"
BRIEF_REASON_MODEL_OR_SYSTEM_ISSUE = "model_or_system_issue"
BRIEF_REASON_MODEL_DEFERRED = "model_deferred"

BRIEF_RULE_NO_SIGNAL = "no_signal"
BRIEF_RULE_SOURCE_BACKED_FINAL = "source_backed_final"
BRIEF_RULE_SYSTEM_ISSUE = "system_issue"
BRIEF_RULE_WEAK_NEWS_COVERAGE = "weak_news_coverage"
BRIEF_RULE_MODEL_DEFERRED = "model_deferred"

AI_BRIEF_STATES = frozenset(
    {
        BRIEF_STATE_NO_SIGNAL,
        BRIEF_STATE_FINAL_JUDGMENT,
        BRIEF_STATE_NEEDS_REVIEW_WEAK_NEWS,
    }
)
AI_BRIEF_REASONS = frozenset(
    {
        BRIEF_REASON_NO_ENTER_CANDIDATES,
        BRIEF_REASON_SOURCE_BACKED_FINAL,
        BRIEF_REASON_WEAK_NEWS_COVERAGE,
        BRIEF_REASON_MODEL_OR_SYSTEM_ISSUE,
        BRIEF_REASON_MODEL_DEFERRED,
    }
)


@dataclass(frozen=True)
class AiBriefState:
    state: str
    reason: str


class AiBriefStateRuleContract(TypedDict):
    state: str
    reason: str


class AiBriefStateContract(TypedDict):
    version: int
    states: list[str]
    reasons: list[str]
    reasons_by_state: dict[str, list[str]]
    inference_precedence: list[str]
    rules: dict[str, AiBriefStateRuleContract]


AI_BRIEF_STATE_RULES = {
    BRIEF_RULE_NO_SIGNAL: AiBriefState(
        state=BRIEF_STATE_NO_SIGNAL,
        reason=BRIEF_REASON_NO_ENTER_CANDIDATES,
    ),
    BRIEF_RULE_SOURCE_BACKED_FINAL: AiBriefState(
        state=BRIEF_STATE_FINAL_JUDGMENT,
        reason=BRIEF_REASON_SOURCE_BACKED_FINAL,
    ),
    BRIEF_RULE_SYSTEM_ISSUE: AiBriefState(
        state=BRIEF_STATE_NEEDS_REVIEW_WEAK_NEWS,
        reason=BRIEF_REASON_MODEL_OR_SYSTEM_ISSUE,
    ),
    BRIEF_RULE_WEAK_NEWS_COVERAGE: AiBriefState(
        state=BRIEF_STATE_NEEDS_REVIEW_WEAK_NEWS,
        reason=BRIEF_REASON_WEAK_NEWS_COVERAGE,
    ),
    BRIEF_RULE_MODEL_DEFERRED: AiBriefState(
        state=BRIEF_STATE_NEEDS_REVIEW_WEAK_NEWS,
        reason=BRIEF_REASON_MODEL_DEFERRED,
    ),
}
AI_BRIEF_INFERENCE_PRECEDENCE = (
    BRIEF_RULE_NO_SIGNAL,
    BRIEF_RULE_SOURCE_BACKED_FINAL,
    BRIEF_RULE_SYSTEM_ISSUE,
    BRIEF_RULE_WEAK_NEWS_COVERAGE,
    BRIEF_RULE_MODEL_DEFERRED,
)
AI_BRIEF_STATE_ORDER = (
    BRIEF_STATE_NO_SIGNAL,
    BRIEF_STATE_FINAL_JUDGMENT,
    BRIEF_STATE_NEEDS_REVIEW_WEAK_NEWS,
)
AI_BRIEF_REASON_ORDER = (
    BRIEF_REASON_NO_ENTER_CANDIDATES,
    BRIEF_REASON_SOURCE_BACKED_FINAL,
    BRIEF_REASON_WEAK_NEWS_COVERAGE,
    BRIEF_REASON_MODEL_OR_SYSTEM_ISSUE,
    BRIEF_REASON_MODEL_DEFERRED,
)
AI_BRIEF_REASONS_BY_STATE = {
    state: frozenset(
        decision.reason
        for decision in AI_BRIEF_STATE_RULES.values()
        if decision.state == state
    )
    for state in AI_BRIEF_STATE_ORDER
}


@dataclass(frozen=True)
class AiBriefStateInputs:
    preselected_count: int
    recommendation_count: int
    source_issue_count: int
    system_issue_count: int
    recommendations: list[Mapping[str, Any]]


def _as_mapping(value: object) -> Mapping[str, Any]:
    return value if isinstance(value, Mapping) else {}


def _mapping_rows(value: object) -> list[Mapping[str, Any]]:
    if not isinstance(value, list):
        return []
    return [row for row in value if isinstance(row, Mapping)]


def _safe_int(value: object, *, default: int = 0) -> int:
    if value is None:
        return default
    if isinstance(value, bool):
        return int(value)
    if isinstance(value, int):
        return value
    try:
        return int(float(str(value).strip()))
    except TypeError, ValueError:
        return default


def _count_with_row_floor(
    summary_value: object,
    top_level_value: object,
    *,
    row_count: int,
) -> int:
    return max(
        _safe_int(summary_value, default=row_count),
        _safe_int(top_level_value, default=row_count),
        row_count,
    )


def _brief_state_inputs(payload: Mapping[str, Any]) -> AiBriefStateInputs:
    summary = _as_mapping(payload.get("summary"))
    recommendations = _mapping_rows(payload.get("recommendations"))
    source_issues = _mapping_rows(payload.get("source_issues"))
    system_issues = _mapping_rows(payload.get("system_issues"))
    eligible_tickers = payload.get("eligible_tickers")
    eligible_count = len(eligible_tickers) if isinstance(eligible_tickers, list) else 0

    recommendation_count = _count_with_row_floor(
        summary.get("recommendation_count"),
        payload.get("recommendation_count"),
        row_count=len(recommendations),
    )
    preselected_count = _count_with_row_floor(
        summary.get("preselected_count"),
        payload.get("preselected_count"),
        row_count=max(eligible_count, len(recommendations), recommendation_count),
    )
    source_issue_count = _count_with_row_floor(
        summary.get("source_issue_count"),
        payload.get("source_issue_count"),
        row_count=len(source_issues),
    )
    system_issue_count = _count_with_row_floor(
        summary.get("system_issue_count"),
        payload.get("system_issue_count"),
        row_count=len(system_issues),
    )
    return AiBriefStateInputs(
        preselected_count=preselected_count,
        recommendation_count=recommendation_count,
        source_issue_count=source_issue_count,
        system_issue_count=system_issue_count,
        recommendations=recommendations,
    )


def _recommendation_has_sources(recommendation: Mapping[str, Any]) -> bool:
    return bool(_mapping_rows(recommendation.get("sources")))


def _state_for_rule(rule_id: str) -> AiBriefState:
    return AI_BRIEF_STATE_RULES[rule_id]


def infer_ai_brief_state(payload: Mapping[str, Any]) -> AiBriefState:
    inputs = _brief_state_inputs(payload)
    missing_recommendation_sources = any(
        not _recommendation_has_sources(recommendation)
        for recommendation in inputs.recommendations
    )

    if inputs.preselected_count == 0:
        return _state_for_rule(BRIEF_RULE_NO_SIGNAL)
    if (
        inputs.recommendations
        and inputs.recommendation_count > 0
        and not missing_recommendation_sources
        and inputs.source_issue_count == 0
        and inputs.system_issue_count == 0
    ):
        return _state_for_rule(BRIEF_RULE_SOURCE_BACKED_FINAL)
    if inputs.system_issue_count > 0:
        return _state_for_rule(BRIEF_RULE_SYSTEM_ISSUE)
    elif inputs.source_issue_count > 0 or missing_recommendation_sources:
        return _state_for_rule(BRIEF_RULE_WEAK_NEWS_COVERAGE)
    return _state_for_rule(BRIEF_RULE_MODEL_DEFERRED)


def validate_ai_brief_state_pair(state: object, reason: object) -> AiBriefState:
    state_text = str(state or "").strip()
    reason_text = str(reason or "").strip()
    if state_text not in AI_BRIEF_STATES:
        raise ValueError(f"brief_state must be one of {sorted(AI_BRIEF_STATES)}")
    if reason_text not in AI_BRIEF_REASONS:
        raise ValueError(f"brief_reason must be one of {sorted(AI_BRIEF_REASONS)}")
    allowed_reasons = AI_BRIEF_REASONS_BY_STATE[state_text]
    if reason_text not in allowed_reasons:
        raise ValueError(
            f"brief_reason {reason_text!r} is not valid for brief_state {state_text!r}"
        )
    return AiBriefState(state=state_text, reason=reason_text)


def validate_optional_ai_brief_state_fields(payload: Mapping[str, Any]) -> None:
    state_present = "brief_state" in payload
    reason_present = "brief_reason" in payload
    if not state_present and not reason_present:
        return
    if not state_present:
        raise ValueError("brief_state is required when brief_reason is present")
    if not reason_present:
        raise ValueError("brief_reason is required when brief_state is present")
    explicit = validate_ai_brief_state_pair(
        payload.get("brief_state"), payload.get("brief_reason")
    )
    inferred = infer_ai_brief_state(payload)
    if explicit != inferred:
        raise ValueError("brief_state/brief_reason must match deterministic inference")


def read_ai_brief_state(payload: Mapping[str, Any]) -> AiBriefState:
    try:
        explicit = validate_ai_brief_state_pair(
            payload.get("brief_state"),
            payload.get("brief_reason"),
        )
        inferred = infer_ai_brief_state(payload)
        if explicit == inferred:
            return explicit
    except ValueError:
        pass
    return infer_ai_brief_state(payload)


def with_inferred_ai_brief_state(payload: Mapping[str, Any]) -> dict[str, Any]:
    next_payload = dict(payload)
    decision = infer_ai_brief_state(next_payload)
    next_payload["brief_state"] = decision.state
    next_payload["brief_reason"] = decision.reason
    return next_payload


def export_ai_brief_state_contract() -> AiBriefStateContract:
    return {
        "version": 1,
        "states": list(AI_BRIEF_STATE_ORDER),
        "reasons": list(AI_BRIEF_REASON_ORDER),
        "reasons_by_state": {
            state: [
                reason
                for reason in AI_BRIEF_REASON_ORDER
                if reason in AI_BRIEF_REASONS_BY_STATE[state]
            ]
            for state in AI_BRIEF_STATE_ORDER
        },
        "inference_precedence": list(AI_BRIEF_INFERENCE_PRECEDENCE),
        "rules": {
            rule_id: {"state": decision.state, "reason": decision.reason}
            for rule_id, decision in AI_BRIEF_STATE_RULES.items()
        },
    }


__all__ = [
    "AI_BRIEF_INFERENCE_PRECEDENCE",
    "AI_BRIEF_REASONS",
    "AI_BRIEF_REASONS_BY_STATE",
    "AI_BRIEF_STATES",
    "AI_BRIEF_STATE_RULES",
    "BRIEF_REASON_MODEL_DEFERRED",
    "BRIEF_REASON_MODEL_OR_SYSTEM_ISSUE",
    "BRIEF_REASON_NO_ENTER_CANDIDATES",
    "BRIEF_REASON_SOURCE_BACKED_FINAL",
    "BRIEF_REASON_WEAK_NEWS_COVERAGE",
    "BRIEF_RULE_MODEL_DEFERRED",
    "BRIEF_RULE_NO_SIGNAL",
    "BRIEF_RULE_SOURCE_BACKED_FINAL",
    "BRIEF_RULE_SYSTEM_ISSUE",
    "BRIEF_RULE_WEAK_NEWS_COVERAGE",
    "BRIEF_STATE_FINAL_JUDGMENT",
    "BRIEF_STATE_NEEDS_REVIEW_WEAK_NEWS",
    "BRIEF_STATE_NO_SIGNAL",
    "AiBriefState",
    "AiBriefStateContract",
    "export_ai_brief_state_contract",
    "infer_ai_brief_state",
    "read_ai_brief_state",
    "validate_optional_ai_brief_state_fields",
    "with_inferred_ai_brief_state",
]
