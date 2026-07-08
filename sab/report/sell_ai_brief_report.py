from __future__ import annotations

import datetime as dt
import os
from collections.abc import Mapping
from typing import Any

from ..ai_brief_eval_common import (
    ALLOWED_CONFIDENCE,
    ALLOWED_ENTRY_REPORT_MARKETS,
    ALLOWED_ISSUE_SEVERITY,
    contains_automated_order_language,
)
from ..ai_brief_sources import (
    SOURCE_FUTURE_SKEW_MINUTES,
    is_ai_brief_source_future,
    is_ai_brief_source_stale,
    validate_ai_brief_source_url,
)
from ..utils.atomic_io import advisory_path_lock, atomic_write_json
from ..utils.datetime import offset_iso
from .metadata import parse_report_offset_datetime
from .paths import ensure_dir, next_report_path
from .time_label import normalize_artifact_date

_ARTIFACT_SCHEMA = "sab.sell_ai_brief.v1"
_REPORT_TYPE = "sell-ai-brief"
_MAX_JUDGMENTS = 5
_MAX_SOURCES_PER_TICKER = 3
_ACTIONABLE_SELL_ACTIONS = frozenset({"SELL", "SELL_PARTIAL", "REVIEW"})
_SELL_AI_STANCES = frozenset({"AGREE", "DEFER", "CAUTION"})
_SELL_BRIEF_STATES = frozenset(
    {
        "NO_ACTION",
        "FINAL_JUDGMENT",
        "NEEDS_REVIEW_WEAK_NEWS",
        "MODEL_OR_SYSTEM_ISSUE",
    }
)


class SellAiBriefValidationError(ValueError):
    """Raised when a Sell AI Brief artifact violates the local JSON contract."""


def _parse_offset_datetime(value: object, *, field_name: str) -> dt.datetime:
    return parse_report_offset_datetime(
        value,
        field_name=field_name,
        error_type=SellAiBriefValidationError,
    )


def _report_date_from_generated_at(
    generated_at: str, artifact_date: object | None
) -> str:
    normalized_artifact_date = normalize_artifact_date(artifact_date)
    if normalized_artifact_date is not None:
        return normalized_artifact_date
    return (
        _parse_offset_datetime(generated_at, field_name="generated_at")
        .date()
        .isoformat()
    )


def _require_mapping(value: object, *, field_name: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise SellAiBriefValidationError(f"{field_name} must be an object")
    return value


def _require_list(value: object, *, field_name: str) -> list[Any]:
    if not isinstance(value, list):
        raise SellAiBriefValidationError(f"{field_name} must be a list")
    return value


def _optional_list(payload: Mapping[str, Any], field_name: str) -> list[Any] | None:
    if field_name not in payload:
        return None
    return _require_list(payload.get(field_name), field_name=field_name)


def _summary_int(summary: Mapping[str, Any], field_name: str) -> int:
    value = summary.get(field_name)
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise SellAiBriefValidationError(
            f"summary.{field_name} must be a non-negative int"
        )
    return value


def _ticker_list(payload: Mapping[str, Any], field_name: str) -> list[str]:
    rows = _require_list(payload.get(field_name), field_name=field_name)
    tickers: list[str] = []
    seen: set[str] = set()
    for idx, raw_ticker in enumerate(rows):
        if not isinstance(raw_ticker, str):
            raise SellAiBriefValidationError(f"{field_name}[{idx}] must be a string")
        ticker = raw_ticker.strip()
        if not ticker:
            raise SellAiBriefValidationError(f"{field_name}[{idx}] is required")
        if ticker in seen:
            raise SellAiBriefValidationError(f"{field_name} must be unique")
        seen.add(ticker)
        tickers.append(ticker)
    return tickers


def _string_list(value: object, *, field_name: str) -> list[str]:
    rows = _require_list(value, field_name=field_name)
    strings: list[str] = []
    for idx, raw_item in enumerate(rows):
        if not isinstance(raw_item, str) or not raw_item.strip():
            raise SellAiBriefValidationError(
                f"{field_name}[{idx}] must be a non-empty string"
            )
        strings.append(raw_item.strip())
    return strings


def _validate_issue_list(payload: Mapping[str, Any], field_name: str) -> None:
    issues = _require_list(payload.get(field_name), field_name=field_name)
    for idx, raw_issue in enumerate(issues):
        issue = _require_mapping(raw_issue, field_name=f"{field_name}[{idx}]")
        code = str(issue.get("code") or "").strip()
        message = str(issue.get("message") or "").strip()
        severity = str(issue.get("severity") or "").strip().upper()
        if not code:
            raise SellAiBriefValidationError(f"{field_name}[{idx}].code is required")
        if not message:
            raise SellAiBriefValidationError(f"{field_name}[{idx}].message is required")
        if contains_automated_order_language(message):
            raise SellAiBriefValidationError(
                f"{field_name}[{idx}].message must avoid automated-order language"
            )
        if severity not in ALLOWED_ISSUE_SEVERITY:
            raise SellAiBriefValidationError(
                f"{field_name}[{idx}].severity must be one of "
                f"{sorted(ALLOWED_ISSUE_SEVERITY)}"
            )


def _source_issue_tickers(payload: Mapping[str, Any]) -> set[str | None]:
    tickers: set[str | None] = set()
    for raw_issue in _require_list(
        payload.get("source_issues"), field_name="source_issues"
    ):
        if not isinstance(raw_issue, Mapping):
            continue
        raw_ticker = raw_issue.get("ticker")
        if raw_ticker is None:
            tickers.add(None)
            continue
        ticker = str(raw_ticker).strip()
        if ticker:
            tickers.add(ticker)
    return tickers


def _validate_article_read(value: object, *, field_name: str) -> None:
    row = _require_mapping(value, field_name=field_name)
    status = str(row.get("status") or "").strip()
    if status not in {
        "not_attempted",
        "metadata_only",
        "accessed",
        "verified",
        "blocked",
        "failed",
    }:
        raise SellAiBriefValidationError(f"{field_name}.status is invalid")
    tier = str(row.get("tier") or "").strip()
    if tier not in {"metadata_backed", "article_accessed", "article_verified"}:
        raise SellAiBriefValidationError(f"{field_name}.tier is invalid")
    _parse_offset_datetime(row.get("checked_at"), field_name=f"{field_name}.checked_at")
    reader = str(row.get("reader") or "").strip()
    if reader not in {"none", "lightpanda"}:
        raise SellAiBriefValidationError(f"{field_name}.reader is invalid")
    matched_terms = _require_list(
        row.get("matched_terms"),
        field_name=f"{field_name}.matched_terms",
    )
    for idx, raw_term in enumerate(matched_terms):
        if not isinstance(raw_term, str):
            raise SellAiBriefValidationError(
                f"{field_name}.matched_terms[{idx}] must be a string"
            )


def _validate_source_rows(
    *,
    sources: object,
    field_name: str,
    now: dt.datetime,
) -> int:
    source_rows = _require_list(sources, field_name=field_name)
    if len(source_rows) > _MAX_SOURCES_PER_TICKER:
        raise SellAiBriefValidationError(
            f"{field_name} must contain at most {_MAX_SOURCES_PER_TICKER} sources"
        )
    for source_index, raw_source in enumerate(source_rows):
        source = _require_mapping(
            raw_source,
            field_name=f"{field_name}[{source_index}]",
        )
        title = str(source.get("title") or "").strip()
        if not title:
            raise SellAiBriefValidationError("source title is required")
        try:
            validate_ai_brief_source_url(source.get("url"), field_name="source url")
        except ValueError as exc:
            raise SellAiBriefValidationError(str(exc)) from exc
        published_at = _parse_offset_datetime(
            source.get("published_at"),
            field_name="source.published_at",
        )
        if is_ai_brief_source_stale(published_at, now=now):
            raise SellAiBriefValidationError("source.published_at must be within 72h")
        if is_ai_brief_source_future(published_at, now=now):
            raise SellAiBriefValidationError(
                "source.published_at must not be more than "
                f"{SOURCE_FUTURE_SKEW_MINUTES}m in the future"
            )
        if "article_read" in source:
            _validate_article_read(
                source.get("article_read"),
                field_name=f"{field_name}[{source_index}].article_read",
            )
    return len(source_rows)


def _validate_candidate_sources(
    row: Mapping[str, Any],
    *,
    field_name: str,
    ticker: str,
    source_issue_tickers: set[str | None],
    now: dt.datetime,
) -> int:
    source_count = _validate_source_rows(
        sources=row.get("sources"),
        field_name=field_name,
        now=now,
    )
    if source_count == 0 and ticker not in source_issue_tickers:
        raise SellAiBriefValidationError(
            f"{field_name} with no sources must have a source issue"
        )
    return source_count


def _validate_actionable_candidates(
    payload: Mapping[str, Any],
) -> dict[str, str]:
    actionable_tickers = _ticker_list(payload, "actionable_tickers")
    rows = _require_list(
        payload.get("actionable_candidates"),
        field_name="actionable_candidates",
    )
    if len(rows) != len(actionable_tickers):
        raise SellAiBriefValidationError(
            "actionable_candidates must match actionable_tickers"
        )
    action_by_ticker: dict[str, str] = {}
    for idx, raw_row in enumerate(rows):
        row = _require_mapping(raw_row, field_name=f"actionable_candidates[{idx}]")
        ticker = str(row.get("ticker") or "").strip()
        sell_action = (
            str(row.get("sell_action") or row.get("action") or "").strip().upper()
        )
        if ticker != actionable_tickers[idx]:
            raise SellAiBriefValidationError(
                "actionable_candidates[].ticker order must match actionable_tickers"
            )
        if sell_action == "HOLD":
            raise SellAiBriefValidationError("HOLD must not be actionable")
        if sell_action not in _ACTIONABLE_SELL_ACTIONS:
            raise SellAiBriefValidationError(
                "actionable_candidates[].sell_action must be SELL, SELL_PARTIAL, or REVIEW"
            )
        _string_list(
            row.get("deterministic_reasons"),
            field_name=f"actionable_candidates[{idx}].deterministic_reasons",
        )
        action_by_ticker[ticker] = sell_action
    return action_by_ticker


def _validate_excluded_hold_candidates(payload: Mapping[str, Any]) -> None:
    rows = _require_list(
        payload.get("excluded_hold_candidates"),
        field_name="excluded_hold_candidates",
    )
    for idx, raw_row in enumerate(rows):
        row = _require_mapping(raw_row, field_name=f"excluded_hold_candidates[{idx}]")
        ticker = str(row.get("ticker") or "").strip()
        sell_action = (
            str(row.get("sell_action") or row.get("action") or "").strip().upper()
        )
        reason = str(row.get("reason") or "").strip()
        if not ticker:
            raise SellAiBriefValidationError(
                f"excluded_hold_candidates[{idx}].ticker is required"
            )
        if sell_action != "HOLD":
            raise SellAiBriefValidationError(
                "excluded_hold_candidates[].sell_action must be HOLD"
            )
        if not reason:
            raise SellAiBriefValidationError(
                f"excluded_hold_candidates[{idx}].reason is required"
            )


def _validate_simple_candidate_list(
    payload: Mapping[str, Any],
    field_name: str,
    *,
    allowed_actions: set[str] | None,
) -> None:
    rows = _require_list(payload.get(field_name), field_name=field_name)
    for idx, raw_row in enumerate(rows):
        row = _require_mapping(raw_row, field_name=f"{field_name}[{idx}]")
        ticker = str(row.get("ticker") or "").strip()
        sell_action = (
            str(row.get("sell_action") or row.get("action") or "").strip().upper()
        )
        reason = str(row.get("reason") or "").strip()
        if not ticker:
            raise SellAiBriefValidationError(f"{field_name}[{idx}].ticker is required")
        if allowed_actions is not None and sell_action not in allowed_actions:
            raise SellAiBriefValidationError(
                f"{field_name}[{idx}].sell_action must be one of "
                f"{sorted(allowed_actions)}"
            )
        if not reason:
            raise SellAiBriefValidationError(f"{field_name}[{idx}].reason is required")
        if contains_automated_order_language(reason):
            raise SellAiBriefValidationError(
                f"{field_name} must avoid automated-order language"
            )


def _validate_judgments(
    payload: Mapping[str, Any],
    *,
    source_action_by_ticker: Mapping[str, str],
    now: dt.datetime,
) -> None:
    judgments = _require_list(payload.get("judgments"), field_name="judgments")
    if len(judgments) > _MAX_JUDGMENTS:
        raise SellAiBriefValidationError(
            f"judgments must contain at most {_MAX_JUDGMENTS} rows"
        )
    source_issue_tickers = _source_issue_tickers(payload)
    seen_tickers: set[str] = set()
    for idx, raw_judgment in enumerate(judgments):
        judgment = _require_mapping(raw_judgment, field_name=f"judgments[{idx}]")
        ticker = str(judgment.get("ticker") or "").strip()
        if not ticker:
            raise SellAiBriefValidationError(f"judgments[{idx}].ticker is required")
        if ticker in seen_tickers:
            raise SellAiBriefValidationError("judgments[].ticker must be unique")
        seen_tickers.add(ticker)
        if ticker not in source_action_by_ticker:
            raise SellAiBriefValidationError(
                "judgments[].ticker must be in actionable_tickers"
            )
        sell_action = (
            str(judgment.get("sell_action") or judgment.get("action") or "")
            .strip()
            .upper()
        )
        if sell_action == "HOLD":
            raise SellAiBriefValidationError("HOLD must not appear in judgments")
        source_action = source_action_by_ticker[ticker]
        if sell_action != source_action:
            raise SellAiBriefValidationError(
                "judgments[].sell_action must match source sell action"
            )
        ai_stance = str(judgment.get("ai_stance") or "").strip().upper()
        if ai_stance not in _SELL_AI_STANCES:
            raise SellAiBriefValidationError(
                f"judgments[].ai_stance must be one of {sorted(_SELL_AI_STANCES)}"
            )
        confidence = str(judgment.get("confidence") or "").strip().upper()
        if confidence not in ALLOWED_CONFIDENCE:
            raise SellAiBriefValidationError(
                f"judgments[].confidence must be one of {sorted(ALLOWED_CONFIDENCE)}"
            )
        _parse_offset_datetime(
            judgment.get("as_of"), field_name=f"judgments[{idx}].as_of"
        )
        deterministic_reasons = _string_list(
            judgment.get("deterministic_reasons"),
            field_name=f"judgments[{idx}].deterministic_reasons",
        )
        rationale = _string_list(
            judgment.get("rationale"),
            field_name=f"judgments[{idx}].rationale",
        )
        checklist = _string_list(
            judgment.get("checklist"),
            field_name=f"judgments[{idx}].checklist",
        )
        if contains_automated_order_language(
            " ".join([*deterministic_reasons, *rationale, *checklist])
        ):
            raise SellAiBriefValidationError(
                "judgments[] must avoid automated-order language"
            )
        _validate_candidate_sources(
            judgment,
            field_name=f"judgments[{idx}].sources",
            ticker=ticker,
            source_issue_tickers=source_issue_tickers,
            now=now,
        )


def _validate_vetoed_candidates(
    payload: Mapping[str, Any],
    *,
    source_action_by_ticker: Mapping[str, str],
) -> None:
    rows = _require_list(
        payload.get("vetoed_candidates"), field_name="vetoed_candidates"
    )
    seen_tickers: set[str] = set()
    for idx, raw_row in enumerate(rows):
        row = _require_mapping(raw_row, field_name=f"vetoed_candidates[{idx}]")
        ticker = str(row.get("ticker") or "").strip()
        sell_action = (
            str(row.get("sell_action") or row.get("action") or "").strip().upper()
        )
        reason = str(row.get("reason") or "").strip()
        if not ticker:
            raise SellAiBriefValidationError(
                f"vetoed_candidates[{idx}].ticker is required"
            )
        if ticker in seen_tickers:
            raise SellAiBriefValidationError(
                "vetoed_candidates[].ticker must be unique"
            )
        seen_tickers.add(ticker)
        if ticker not in source_action_by_ticker:
            raise SellAiBriefValidationError(
                "vetoed_candidates[].ticker must be in actionable_tickers"
            )
        if sell_action == "HOLD":
            raise SellAiBriefValidationError(
                "HOLD must not appear in vetoed_candidates"
            )
        if sell_action != source_action_by_ticker[ticker]:
            raise SellAiBriefValidationError(
                "vetoed_candidates[].sell_action must match source sell action"
            )
        if not reason:
            raise SellAiBriefValidationError(
                f"vetoed_candidates[{idx}].reason is required"
            )
        if contains_automated_order_language(reason):
            raise SellAiBriefValidationError(
                "vetoed_candidates must avoid automated-order language"
            )


def _validate_actionable_coverage(
    payload: Mapping[str, Any],
    *,
    source_action_by_ticker: Mapping[str, str],
    summary: Mapping[str, Any],
) -> None:
    expected_tickers = set(source_action_by_ticker)
    judgment_tickers = {
        str(row.get("ticker") or "").strip()
        for row in _require_list(payload.get("judgments"), field_name="judgments")
        if isinstance(row, Mapping)
    }
    vetoed_tickers = {
        str(row.get("ticker") or "").strip()
        for row in _require_list(
            payload.get("vetoed_candidates"), field_name="vetoed_candidates"
        )
        if isinstance(row, Mapping)
    }
    covered_tickers = judgment_tickers | vetoed_tickers
    missing = sorted(expected_tickers - covered_tickers)
    if not missing:
        return
    system_issue_count = _summary_int(summary, "system_issue_count")
    if system_issue_count > 0 and not covered_tickers:
        return
    raise SellAiBriefValidationError(
        "actionable_tickers must appear in judgments or vetoed_candidates; "
        f"missing {', '.join(missing)}"
    )


def _validate_summary_counts(
    payload: Mapping[str, Any],
    *,
    summary: Mapping[str, Any],
) -> None:
    expected = {
        "preselected_count": len(
            _require_list(
                payload.get("actionable_tickers"), field_name="actionable_tickers"
            )
        ),
        "judgment_count": len(
            _require_list(payload.get("judgments"), field_name="judgments")
        ),
        "excluded_hold_count": len(
            _require_list(
                payload.get("excluded_hold_candidates"),
                field_name="excluded_hold_candidates",
            )
        ),
        "broker_state_review_count": len(
            _require_list(
                payload.get("broker_state_review_candidates"),
                field_name="broker_state_review_candidates",
            )
        ),
        "unsupported_action_count": len(
            _require_list(
                payload.get("unsupported_action_candidates"),
                field_name="unsupported_action_candidates",
            )
        ),
        "vetoed_count": len(
            _require_list(
                payload.get("vetoed_candidates"), field_name="vetoed_candidates"
            )
        ),
        "cap_excluded_count": len(
            _require_list(
                payload.get("cap_excluded_candidates"),
                field_name="cap_excluded_candidates",
            )
        ),
        "source_issue_count": len(
            _require_list(payload.get("source_issues"), field_name="source_issues")
        ),
        "system_issue_count": len(
            _require_list(payload.get("system_issues"), field_name="system_issues")
        ),
    }
    expected["actionable_count"] = (
        expected["preselected_count"] + expected["cap_excluded_count"]
    )
    for field_name, expected_count in expected.items():
        actual_count = _summary_int(summary, field_name)
        if actual_count != expected_count:
            raise SellAiBriefValidationError(
                f"summary.{field_name} must be {expected_count}, got {actual_count!r}"
            )
    evaluated_count = _summary_int(summary, "evaluated_count")
    minimum_evaluated = (
        expected["actionable_count"]
        + expected["broker_state_review_count"]
        + expected["excluded_hold_count"]
        + expected["unsupported_action_count"]
    )
    if evaluated_count < minimum_evaluated:
        raise SellAiBriefValidationError(
            "summary.evaluated_count must cover actionable, hold, and unsupported rows"
        )


def infer_sell_ai_brief_state(
    payload: Mapping[str, Any],
) -> tuple[str, str]:
    summary = _require_mapping(payload.get("summary"), field_name="summary")
    preselected_count = _summary_int(summary, "preselected_count")
    judgment_count = _summary_int(summary, "judgment_count")
    source_issue_count = _summary_int(summary, "source_issue_count")
    system_issue_count = _summary_int(summary, "system_issue_count")
    if preselected_count == 0 and judgment_count == 0 and system_issue_count == 0:
        return "NO_ACTION", "no_actionable_sell_candidates"
    if system_issue_count > 0 and judgment_count == 0:
        return "MODEL_OR_SYSTEM_ISSUE", "system_issue_without_model_judgment"
    vetoed_count = _summary_int(summary, "vetoed_count")
    if preselected_count > 0 and judgment_count == 0 and vetoed_count == 0:
        return "MODEL_OR_SYSTEM_ISSUE", "missing_model_judgment"
    if source_issue_count > 0:
        return "NEEDS_REVIEW_WEAK_NEWS", "weak_news_coverage"
    for raw_judgment in _require_list(payload.get("judgments"), field_name="judgments"):
        if isinstance(raw_judgment, Mapping) and not raw_judgment.get("sources"):
            return "NEEDS_REVIEW_WEAK_NEWS", "weak_news_coverage"
    return "FINAL_JUDGMENT", "model_judgment_ready"


def _with_inferred_state(payload: Mapping[str, Any]) -> dict[str, Any]:
    row = dict(payload)
    state, reason = infer_sell_ai_brief_state(row)
    row["brief_state"] = state
    row["brief_reason"] = reason
    return row


def _validate_state(payload: Mapping[str, Any]) -> None:
    state = str(payload.get("brief_state") or "").strip().upper()
    reason = str(payload.get("brief_reason") or "").strip()
    if state not in _SELL_BRIEF_STATES:
        raise SellAiBriefValidationError(
            f"brief_state must be one of {sorted(_SELL_BRIEF_STATES)}"
        )
    if not reason:
        raise SellAiBriefValidationError("brief_reason is required")
    inferred_state, inferred_reason = infer_sell_ai_brief_state(payload)
    if state != inferred_state:
        raise SellAiBriefValidationError(
            f"brief_state must be {inferred_state}, got {state!r}"
        )
    if reason != inferred_reason:
        raise SellAiBriefValidationError(
            f"brief_reason must be {inferred_reason}, got {reason!r}"
        )


def validate_sell_ai_brief_artifact(
    payload: Mapping[str, Any],
    *,
    now: dt.datetime,
) -> None:
    if payload.get("schema", _ARTIFACT_SCHEMA) != _ARTIFACT_SCHEMA:
        raise SellAiBriefValidationError(f"schema must be {_ARTIFACT_SCHEMA!r}")
    if payload.get("type", _REPORT_TYPE) != _REPORT_TYPE:
        raise SellAiBriefValidationError(f"type must be {_REPORT_TYPE!r}")
    if "generated_at" in payload:
        _parse_offset_datetime(payload.get("generated_at"), field_name="generated_at")

    market = str(payload.get("market") or "").strip().upper()
    if market not in ALLOWED_ENTRY_REPORT_MARKETS:
        raise SellAiBriefValidationError(
            f"market must be one of {sorted(ALLOWED_ENTRY_REPORT_MARKETS)}"
        )
    if str(payload.get("model_provider") or "").strip() not in {"fake", "openai"}:
        raise SellAiBriefValidationError("model_provider must be fake or openai")
    if not str(payload.get("model_name") or "").strip():
        raise SellAiBriefValidationError("model_name is required")
    if not str(payload.get("source_sell_report") or "").strip():
        raise SellAiBriefValidationError("source_sell_report is required")

    summary = _require_mapping(payload.get("summary"), field_name="summary")
    source_action_by_ticker = _validate_actionable_candidates(payload)
    if list(source_action_by_ticker) != _ticker_list(payload, "actionable_tickers"):
        raise SellAiBriefValidationError("actionable_tickers must be preserved")
    tickers = _optional_list(payload, "tickers")
    if tickers is not None and [
        str(ticker).strip() for ticker in tickers if str(ticker).strip()
    ] != _ticker_list(payload, "actionable_tickers"):
        raise SellAiBriefValidationError("tickers must match actionable_tickers")
    _validate_excluded_hold_candidates(payload)
    _validate_simple_candidate_list(
        payload,
        "broker_state_review_candidates",
        allowed_actions=set(_ACTIONABLE_SELL_ACTIONS),
    )
    _validate_simple_candidate_list(
        payload,
        "unsupported_action_candidates",
        allowed_actions=None,
    )
    _validate_simple_candidate_list(
        payload,
        "cap_excluded_candidates",
        allowed_actions=set(_ACTIONABLE_SELL_ACTIONS),
    )
    _validate_issue_list(payload, "source_issues")
    _validate_issue_list(payload, "system_issues")
    _validate_judgments(
        payload,
        source_action_by_ticker=source_action_by_ticker,
        now=now,
    )
    _validate_vetoed_candidates(
        payload, source_action_by_ticker=source_action_by_ticker
    )
    _validate_actionable_coverage(
        payload,
        source_action_by_ticker=source_action_by_ticker,
        summary=summary,
    )
    _validate_summary_counts(payload, summary=summary)
    _validate_state(payload)


def write_sell_ai_brief_report(
    *,
    report_dir: str,
    artifact: Mapping[str, Any],
    now: dt.datetime | None = None,
    artifact_date: object | None = None,
) -> str:
    ensure_dir(report_dir)
    generated_at = str(artifact.get("generated_at") or offset_iso(now)).strip()
    report_date = _report_date_from_generated_at(generated_at, artifact_date)
    validation_now = (
        now
        if now is not None and now.tzinfo is not None
        else _parse_offset_datetime(generated_at, field_name="generated_at")
    )
    if validation_now.tzinfo is None:
        validation_now = validation_now.replace(tzinfo=dt.UTC)

    payload: dict[str, Any] = {
        "schema": _ARTIFACT_SCHEMA,
        "type": _REPORT_TYPE,
        "generated_at": generated_at,
        "report_date": report_date,
        **dict(artifact),
    }
    payload["schema"] = _ARTIFACT_SCHEMA
    payload["type"] = _REPORT_TYPE
    payload["generated_at"] = generated_at
    payload["report_date"] = report_date
    payload = _with_inferred_state(payload)
    validate_sell_ai_brief_artifact(payload, now=validation_now)

    lock_path = os.path.join(report_dir, ".sell-ai-brief.report.lock")
    with advisory_path_lock(lock_path):
        out_path = next_report_path(report_dir, report_date, "sell-ai-brief")
        atomic_write_json(out_path, payload, ensure_ascii=False, indent=2)

    return out_path


__all__ = [
    "SellAiBriefValidationError",
    "infer_sell_ai_brief_state",
    "validate_sell_ai_brief_artifact",
    "write_sell_ai_brief_report",
]
