from __future__ import annotations

import datetime as dt
import os
from collections.abc import Mapping
from typing import Any

from ..ai_brief_eval_common import (
    ALLOWED_CONFIDENCE,
    ALLOWED_ISSUE_SEVERITY,
    ALLOWED_MARKETS,
    contains_automated_order_language,
)
from ..ai_brief_source_chain import parse_source_provider_chain
from ..ai_brief_sources import (
    SOURCE_FUTURE_SKEW_MINUTES,
    is_ai_brief_source_future,
    is_ai_brief_source_stale,
    validate_ai_brief_source_url,
)
from ..utils.atomic_io import advisory_path_lock, atomic_write_json
from ..utils.datetime import offset_iso
from .ai_brief_state import (
    validate_optional_ai_brief_state_fields,
    with_inferred_ai_brief_state,
)
from .metadata import parse_report_offset_datetime
from .paths import ensure_dir, next_report_path
from .time_label import normalize_artifact_date

_ARTIFACT_SCHEMA = "sab.ai_brief.v1"
_MODEL_TRACE_SCHEMA = "sab.ai_brief.model_trace.v1"
_REPORT_TYPE = "ai_brief"
_MAX_RECOMMENDATIONS = 3
_MAX_SOURCES_PER_TICKER = 3
_ALLOWED_MODEL_PROVIDERS = frozenset({"fake", "openai"})
_ALLOWED_SOURCE_PROVIDER_STATUSES = frozenset({"success", "failed", "skipped"})
_ALLOWED_ARTICLE_READ_STATUSES = frozenset(
    {"not_attempted", "metadata_only", "accessed", "verified", "blocked", "failed"}
)
_ALLOWED_SOURCE_BACKING_TIERS = frozenset(
    {"metadata_backed", "article_accessed", "article_verified"}
)
_ALLOWED_ARTICLE_READERS = frozenset({"none", "lightpanda"})
_ALLOWED_MODEL_TRACE_REQUEST_STATUSES = frozenset({"sent", "planned_not_sent"})
_ALLOWED_MODEL_OUTPUT_STATUSES = frozenset(
    {"recommended", "vetoed", "watch", "no_output", "ambiguous_ticker_match"}
)
_EXPANDED_SUMMARY_COUNT_FIELDS = ("recommendable_count", "watch_count")
_ARTICLE_READ_SUMMARY_COUNT_FIELDS = (
    "article_read_attempted_count",
    "article_accessed_count",
    "article_verified_count",
    "article_read_issue_count",
)
_CANDIDATE_ROLE_SUMMARY_COUNT_FIELDS = (
    "executable_count",
    "blocked_but_valid_count",
)
_CANDIDATE_ROLE_ARTIFACT_FIELDS = (
    "executable_tickers",
    "blocked_but_valid_tickers",
)
_NEW_FORMAT_ARTIFACT_FIELDS = frozenset(
    {
        "watch_tickers",
        "watch_candidates",
        "source_provider_summary",
        *_CANDIDATE_ROLE_ARTIFACT_FIELDS,
    }
)


class AiBriefValidationError(ValueError):
    """Raised when an AI brief artifact violates the local JSON contract."""


def _parse_offset_datetime(value: object, *, field_name: str) -> dt.datetime:
    return parse_report_offset_datetime(
        value,
        field_name=field_name,
        error_type=AiBriefValidationError,
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
        raise AiBriefValidationError(f"{field_name} must be an object")
    return value


def _require_list(value: object, *, field_name: str) -> list[Any]:
    if not isinstance(value, list):
        raise AiBriefValidationError(f"{field_name} must be a list")
    return value


def _optional_list(payload: Mapping[str, Any], field_name: str) -> list[Any] | None:
    if field_name not in payload:
        return None
    return _require_list(payload.get(field_name), field_name=field_name)


def _validate_issue_list(payload: Mapping[str, Any], field_name: str) -> None:
    issues = _require_list(payload.get(field_name), field_name=field_name)
    for idx, raw_issue in enumerate(issues):
        issue = _require_mapping(raw_issue, field_name=f"{field_name}[{idx}]")
        code = str(issue.get("code") or "").strip()
        message = str(issue.get("message") or "").strip()
        severity = str(issue.get("severity") or "").strip().upper()
        if not code:
            raise AiBriefValidationError(f"{field_name}[{idx}].code is required")
        if not message:
            raise AiBriefValidationError(f"{field_name}[{idx}].message is required")
        if severity not in ALLOWED_ISSUE_SEVERITY:
            raise AiBriefValidationError(
                f"{field_name}[{idx}].severity must be one of "
                f"{sorted(ALLOWED_ISSUE_SEVERITY)}"
            )


def _validate_source_rows(
    *,
    sources: object,
    field_name: str,
    now: dt.datetime,
) -> int:
    source_rows = _require_list(sources, field_name=field_name)
    if len(source_rows) > _MAX_SOURCES_PER_TICKER:
        raise AiBriefValidationError(
            f"{field_name} must contain at most {_MAX_SOURCES_PER_TICKER} sources"
        )
    for source_index, raw_source in enumerate(source_rows):
        source = _require_mapping(
            raw_source,
            field_name=f"{field_name}[{source_index}]",
        )
        title = str(source.get("title") or "").strip()
        if not title:
            raise AiBriefValidationError("source title is required")
        try:
            validate_ai_brief_source_url(source.get("url"), field_name="source url")
        except ValueError as exc:
            raise AiBriefValidationError(str(exc)) from exc
        published_at = _parse_offset_datetime(
            source.get("published_at"),
            field_name="source.published_at",
        )
        if is_ai_brief_source_stale(published_at, now=now):
            raise AiBriefValidationError("source.published_at must be within 72h")
        if is_ai_brief_source_future(published_at, now=now):
            raise AiBriefValidationError(
                "source.published_at must not be more than "
                f"{SOURCE_FUTURE_SKEW_MINUTES}m in the future"
            )
        if "article_read" in source:
            _validate_article_read(
                source.get("article_read"),
                field_name=f"{field_name}[{source_index}].article_read",
            )
    return len(source_rows)


def _validate_article_read(value: object, *, field_name: str) -> None:
    row = _require_mapping(value, field_name=field_name)
    status = str(row.get("status") or "").strip()
    if status not in _ALLOWED_ARTICLE_READ_STATUSES:
        raise AiBriefValidationError(
            f"{field_name}.status must be one of "
            f"{sorted(_ALLOWED_ARTICLE_READ_STATUSES)}"
        )
    tier = str(row.get("tier") or "").strip()
    if tier not in _ALLOWED_SOURCE_BACKING_TIERS:
        raise AiBriefValidationError(
            f"{field_name}.tier must be one of {sorted(_ALLOWED_SOURCE_BACKING_TIERS)}"
        )
    _parse_offset_datetime(row.get("checked_at"), field_name=f"{field_name}.checked_at")
    reader = str(row.get("reader") or "").strip()
    if reader not in _ALLOWED_ARTICLE_READERS:
        raise AiBriefValidationError(
            f"{field_name}.reader must be one of {sorted(_ALLOWED_ARTICLE_READERS)}"
        )
    excerpt = row.get("excerpt")
    if excerpt is not None and not isinstance(excerpt, str):
        raise AiBriefValidationError(f"{field_name}.excerpt must be a string")
    matched_terms = _require_list(
        row.get("matched_terms"),
        field_name=f"{field_name}.matched_terms",
    )
    for idx, raw_term in enumerate(matched_terms):
        if not isinstance(raw_term, str):
            raise AiBriefValidationError(
                f"{field_name}.matched_terms[{idx}] must be a string"
            )
    issue_code = row.get("issue_code")
    if issue_code is not None and not str(issue_code).strip():
        raise AiBriefValidationError(f"{field_name}.issue_code must not be blank")


def _validate_sources(
    *,
    recommendation: Mapping[str, Any],
    recommendation_index: int,
    now: dt.datetime,
) -> int:
    return _validate_source_rows(
        sources=recommendation.get("sources"),
        field_name=f"recommendations[{recommendation_index}].sources",
        now=now,
    )


def _source_issue_tickers(payload: Mapping[str, Any]) -> set[str | None]:
    issues = _require_list(payload.get("source_issues"), field_name="source_issues")
    tickers: set[str | None] = set()
    for raw_issue in issues:
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


def _validate_recommendation_language(
    recommendation: Mapping[str, Any], *, recommendation_index: int
) -> None:
    fields = _require_list(
        recommendation.get("rationale"),
        field_name=f"recommendations[{recommendation_index}].rationale",
    ) + _require_list(
        recommendation.get("checklist"),
        field_name=f"recommendations[{recommendation_index}].checklist",
    )
    text = " ".join(str(item) for item in fields)
    if contains_automated_order_language(text):
        raise AiBriefValidationError(
            "recommendations[] must avoid automated-order language"
        )


def _validate_recommendations(payload: Mapping[str, Any], *, now: dt.datetime) -> None:
    recommendations = _require_list(
        payload.get("recommendations"), field_name="recommendations"
    )
    if len(recommendations) > _MAX_RECOMMENDATIONS:
        raise AiBriefValidationError(
            f"recommendations must contain at most {_MAX_RECOMMENDATIONS} rows"
        )

    eligible_tickers = {
        str(ticker).strip()
        for ticker in _require_list(
            payload.get("eligible_tickers"), field_name="eligible_tickers"
        )
        if str(ticker).strip()
    }
    source_issue_tickers = _source_issue_tickers(payload)
    seen_ranks: set[int] = set()
    ranks: list[int] = []
    for idx, raw_recommendation in enumerate(recommendations):
        recommendation = _require_mapping(
            raw_recommendation, field_name=f"recommendations[{idx}]"
        )
        rank = recommendation.get("rank")
        if isinstance(rank, bool) or not isinstance(rank, int) or rank <= 0:
            raise AiBriefValidationError(
                "recommendations[].rank must be a positive int"
            )
        if rank in seen_ranks:
            raise AiBriefValidationError("recommendations[].rank must be unique")
        seen_ranks.add(rank)
        ranks.append(rank)
        ticker = str(recommendation.get("ticker") or "").strip()
        if not ticker:
            raise AiBriefValidationError(f"recommendations[{idx}].ticker is required")
        if ticker not in eligible_tickers:
            raise AiBriefValidationError(
                f"recommendations[{idx}].ticker must be in eligible_tickers"
            )
        if str(recommendation.get("action") or "").strip().upper() != "ENTER":
            raise AiBriefValidationError("recommendations[].action must be ENTER")
        confidence = str(recommendation.get("confidence") or "").strip().upper()
        if confidence not in ALLOWED_CONFIDENCE:
            raise AiBriefValidationError(
                "recommendations[].confidence must be one of "
                f"{sorted(ALLOWED_CONFIDENCE)}"
            )
        _parse_offset_datetime(
            recommendation.get("as_of"),
            field_name=f"recommendations[{idx}].as_of",
        )
        if not _require_list(
            recommendation.get("rationale"),
            field_name=f"recommendations[{idx}].rationale",
        ):
            raise AiBriefValidationError("recommendations[].rationale is required")
        if not _require_list(
            recommendation.get("checklist"),
            field_name=f"recommendations[{idx}].checklist",
        ):
            raise AiBriefValidationError("recommendations[].checklist is required")
        _validate_recommendation_language(recommendation, recommendation_index=idx)
        source_count = _validate_sources(
            recommendation=recommendation, recommendation_index=idx, now=now
        )
        if source_count == 0 and ticker not in source_issue_tickers:
            raise AiBriefValidationError(
                "recommendations with no sources must have a source issue"
            )
    expected_ranks = list(range(1, len(recommendations) + 1))
    if ranks != expected_ranks:
        raise AiBriefValidationError(
            "recommendations[].rank must be contiguous from 1 to N in "
            "recommendation order"
        )


def _eligible_tickers(payload: Mapping[str, Any]) -> set[str]:
    return {
        str(ticker).strip()
        for ticker in _require_list(
            payload.get("eligible_tickers"), field_name="eligible_tickers"
        )
        if str(ticker).strip()
    }


def _watch_tickers(payload: Mapping[str, Any]) -> list[str] | None:
    raw_tickers = _optional_list(payload, "watch_tickers")
    if raw_tickers is None:
        if "watch_candidates" in payload:
            raise AiBriefValidationError(
                "watch_tickers is required when watch_candidates is present"
            )
        return None
    tickers: list[str] = []
    seen_tickers: set[str] = set()
    for idx, raw_ticker in enumerate(raw_tickers):
        if not isinstance(raw_ticker, str):
            raise AiBriefValidationError(f"watch_tickers[{idx}] must be a string")
        ticker = raw_ticker.strip()
        if not ticker:
            raise AiBriefValidationError(f"watch_tickers[{idx}] is required")
        if ticker in seen_tickers:
            raise AiBriefValidationError("watch_tickers must be unique")
        seen_tickers.add(ticker)
        tickers.append(ticker)
    return tickers


def _optional_ticker_list(
    payload: Mapping[str, Any], field_name: str
) -> list[str] | None:
    raw_tickers = _optional_list(payload, field_name)
    if raw_tickers is None:
        return None
    tickers: list[str] = []
    seen_tickers: set[str] = set()
    for idx, raw_ticker in enumerate(raw_tickers):
        if not isinstance(raw_ticker, str):
            raise AiBriefValidationError(f"{field_name}[{idx}] must be a string")
        ticker = raw_ticker.strip()
        if not ticker:
            raise AiBriefValidationError(f"{field_name}[{idx}] is required")
        if ticker in seen_tickers:
            raise AiBriefValidationError(f"{field_name} must be unique")
        seen_tickers.add(ticker)
        tickers.append(ticker)
    return tickers


def _validate_candidate_list(
    payload: Mapping[str, Any],
    field_name: str,
    allowed_actions: set[str],
    allowed_tickers: set[str] | None = None,
) -> None:
    rows = _require_list(payload.get(field_name), field_name=field_name)
    for idx, raw_row in enumerate(rows):
        row = _require_mapping(raw_row, field_name=f"{field_name}[{idx}]")
        ticker = str(row.get("ticker") or "").strip()
        action = str(row.get("action") or "").strip().upper()
        reason = str(row.get("reason") or "").strip()
        if not ticker:
            raise AiBriefValidationError(f"{field_name}[{idx}].ticker is required")
        if allowed_tickers is not None and ticker not in allowed_tickers:
            raise AiBriefValidationError(f"{field_name}[{idx}].ticker must be eligible")
        if action not in allowed_actions:
            raise AiBriefValidationError(
                f"{field_name}[{idx}].action must be one of {sorted(allowed_actions)}"
            )
        if not reason:
            raise AiBriefValidationError(f"{field_name}[{idx}].reason is required")


def _validate_watch_candidates(
    payload: Mapping[str, Any],
    *,
    watch_tickers: list[str] | None,
    now: dt.datetime,
) -> None:
    rows = _optional_list(payload, "watch_candidates")
    if rows is None:
        if watch_tickers is not None:
            raise AiBriefValidationError(
                "watch_candidates is required when watch_tickers is present"
            )
        return

    assert watch_tickers is not None
    allowed_tickers = set(watch_tickers)
    actual_tickers: list[str] = []
    seen_tickers: set[str] = set()
    for idx, raw_row in enumerate(rows):
        row = _require_mapping(raw_row, field_name=f"watch_candidates[{idx}]")
        ticker = str(row.get("ticker") or "").strip()
        action = str(row.get("action") or "").strip().upper()
        reason = str(row.get("reason") or "").strip()
        if not ticker:
            raise AiBriefValidationError(f"watch_candidates[{idx}].ticker is required")
        if allowed_tickers is not None and ticker not in allowed_tickers:
            raise AiBriefValidationError(
                f"watch_candidates[{idx}].ticker must be in watch_tickers"
            )
        if ticker in seen_tickers:
            raise AiBriefValidationError("watch_candidates[].ticker must be unique")
        seen_tickers.add(ticker)
        actual_tickers.append(ticker)
        if action != "WATCH":
            raise AiBriefValidationError("watch_candidates[].action must be WATCH")
        if not reason:
            raise AiBriefValidationError(f"watch_candidates[{idx}].reason is required")
        retrigger_conditions = _require_list(
            row.get("retrigger_conditions"),
            field_name=f"watch_candidates[{idx}].retrigger_conditions",
        )
        if not retrigger_conditions:
            raise AiBriefValidationError(
                "watch_candidates[].retrigger_conditions is required"
            )
        normalized_conditions: list[str] = []
        for condition_index, raw_condition in enumerate(retrigger_conditions):
            if not isinstance(raw_condition, str) or not raw_condition.strip():
                raise AiBriefValidationError(
                    "watch_candidates"
                    f"[{idx}].retrigger_conditions[{condition_index}] "
                    "must be a non-empty string"
                )
            normalized_conditions.append(raw_condition.strip())
        language_text = " ".join([reason, *normalized_conditions])
        if contains_automated_order_language(language_text):
            raise AiBriefValidationError(
                "watch_candidates[] must avoid automated-order language"
            )
        _validate_source_rows(
            sources=row.get("sources"),
            field_name=f"watch_candidates[{idx}].sources",
            now=now,
        )

    if actual_tickers != watch_tickers:
        raise AiBriefValidationError(
            "watch_candidates[].ticker order must match watch_tickers"
        )


def _array_count(payload: Mapping[str, Any], field_name: str) -> int:
    return len(_require_list(payload.get(field_name), field_name=field_name))


def _recommendable_count(payload: Mapping[str, Any]) -> int:
    return _array_count(payload, "eligible_tickers") + _array_count(
        payload, "cap_excluded_candidates"
    )


def _candidate_list_tickers(payload: Mapping[str, Any], field_name: str) -> set[str]:
    tickers: set[str] = set()
    for raw_row in _require_list(payload.get(field_name), field_name=field_name):
        if isinstance(raw_row, Mapping):
            ticker = str(raw_row.get("ticker") or "").strip()
            if ticker:
                tickers.add(ticker)
    return tickers


def _validate_candidate_role_counts(
    payload: Mapping[str, Any],
    *,
    summary: Mapping[str, Any],
) -> None:
    role_fields_present = any(
        field_name in payload for field_name in _CANDIDATE_ROLE_ARTIFACT_FIELDS
    ) or any(
        field_name in summary for field_name in _CANDIDATE_ROLE_SUMMARY_COUNT_FIELDS
    )
    if not role_fields_present:
        return

    executable_tickers = _optional_ticker_list(payload, "executable_tickers")
    blocked_tickers = _optional_ticker_list(payload, "blocked_but_valid_tickers")
    if executable_tickers is None:
        raise AiBriefValidationError("executable_tickers is required")
    if blocked_tickers is None:
        raise AiBriefValidationError("blocked_but_valid_tickers is required")

    executable_set = set(executable_tickers)
    blocked_set = set(blocked_tickers)
    if executable_set & blocked_set:
        raise AiBriefValidationError("candidate role tickers must be disjoint")

    role_universe = _eligible_tickers(payload) | _candidate_list_tickers(
        payload, "cap_excluded_candidates"
    )
    unknown_tickers = (executable_set | blocked_set) - role_universe
    if unknown_tickers:
        raise AiBriefValidationError(
            "candidate role tickers must be in eligible_tickers or "
            "cap_excluded_candidates"
        )

    expected_counts = {
        "executable_count": len(executable_tickers),
        "blocked_but_valid_count": len(blocked_tickers),
    }
    for field_name, expected_count in expected_counts.items():
        if field_name not in summary:
            raise AiBriefValidationError(f"summary.{field_name} is required")
        actual_count = _summary_int(summary, field_name)
        if actual_count != expected_count:
            raise AiBriefValidationError(
                f"summary.{field_name} must be {expected_count}, got {actual_count!r}"
            )

    recommendable_count = _summary_int(summary, "recommendable_count")
    if (
        recommendable_count is not None
        and sum(expected_counts.values()) != recommendable_count
    ):
        raise AiBriefValidationError(
            "summary.executable_count + summary.blocked_but_valid_count "
            "must match summary.recommendable_count"
        )


def _watch_count(
    payload: Mapping[str, Any],
    *,
    watch_tickers: list[str] | None,
) -> int:
    if watch_tickers is not None:
        return len(watch_tickers)
    return len(_optional_list(payload, "watch_candidates") or [])


def _artifact_source_rows(payload: Mapping[str, Any]) -> list[Mapping[str, Any]]:
    source_rows: list[Mapping[str, Any]] = []
    for candidate_field in ("recommendations", "watch_candidates"):
        candidates = _optional_list(payload, candidate_field)
        if candidates is None:
            continue
        for raw_candidate in candidates:
            if not isinstance(raw_candidate, Mapping):
                continue
            sources = raw_candidate.get("sources")
            if not isinstance(sources, list):
                continue
            for raw_source in sources:
                if isinstance(raw_source, Mapping):
                    source_rows.append(raw_source)
    return source_rows


def _article_read_summary_counts(payload: Mapping[str, Any]) -> dict[str, int]:
    counts = dict.fromkeys(_ARTICLE_READ_SUMMARY_COUNT_FIELDS, 0)
    for source in _artifact_source_rows(payload):
        raw_read = source.get("article_read")
        if not isinstance(raw_read, Mapping):
            continue
        status = str(raw_read.get("status") or "").strip()
        tier = str(raw_read.get("tier") or "").strip()
        issue_code = str(raw_read.get("issue_code") or "").strip()
        if status != "not_attempted":
            counts["article_read_attempted_count"] += 1
        if status in {"accessed", "verified"} or tier in {
            "article_accessed",
            "article_verified",
        }:
            counts["article_accessed_count"] += 1
        if status == "verified" or tier == "article_verified":
            counts["article_verified_count"] += 1
        if issue_code:
            counts["article_read_issue_count"] += 1
    return counts


def _summary_int(summary: Mapping[str, Any], field_name: str) -> int | None:
    if field_name not in summary:
        return None
    value = summary.get(field_name)
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise AiBriefValidationError(f"summary.{field_name} must be a non-negative int")
    return value


def _is_legacy_without_expanded_counts(
    payload: Mapping[str, Any],
    summary: Mapping[str, Any],
) -> bool:
    return not any(
        field_name in payload for field_name in _NEW_FORMAT_ARTIFACT_FIELDS
    ) and all(
        field_name not in summary for field_name in _EXPANDED_SUMMARY_COUNT_FIELDS
    )


def _validate_summary_counts(
    payload: Mapping[str, Any],
    *,
    summary: Mapping[str, Any],
    watch_tickers: list[str] | None,
) -> None:
    _summary_int(summary, "entry_count")
    legacy_without_expanded_counts = _is_legacy_without_expanded_counts(
        payload,
        summary,
    )
    expected_counts = {
        "preselected_count": _array_count(payload, "eligible_tickers"),
        "recommendation_count": _array_count(payload, "recommendations"),
        "excluded_count": _array_count(payload, "excluded_candidates"),
        "vetoed_count": _array_count(payload, "vetoed_candidates"),
        "cap_excluded_count": _array_count(payload, "cap_excluded_candidates"),
        "source_issue_count": _array_count(payload, "source_issues"),
        "system_issue_count": _array_count(payload, "system_issues"),
    }
    expanded_counts = {
        "recommendable_count": _recommendable_count(payload),
        "watch_count": _watch_count(payload, watch_tickers=watch_tickers),
    }
    if not legacy_without_expanded_counts:
        for field_name in _EXPANDED_SUMMARY_COUNT_FIELDS:
            if field_name not in summary:
                raise AiBriefValidationError(f"summary.{field_name} is required")
        expected_counts.update(expanded_counts)
    for field_name, expected_count in expected_counts.items():
        actual_count = _summary_int(summary, field_name)
        if actual_count is not None and actual_count != expected_count:
            raise AiBriefValidationError(
                f"summary.{field_name} must be {expected_count}, got {actual_count!r}"
            )
    if any(field_name in summary for field_name in _ARTICLE_READ_SUMMARY_COUNT_FIELDS):
        for field_name, expected_count in _article_read_summary_counts(payload).items():
            actual_count = _summary_int(summary, field_name)
            if actual_count != expected_count:
                raise AiBriefValidationError(
                    f"summary.{field_name} must be "
                    f"{expected_count}, got {actual_count!r}"
                )


def _non_negative_int(value: object, *, field_name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise AiBriefValidationError(f"{field_name} must be a non-negative int")
    return value


def _validate_source_provider_summary(
    payload: Mapping[str, Any],
    *,
    summary: Mapping[str, Any],
    watch_tickers: list[str] | None,
) -> None:
    if "source_provider_summary" not in payload:
        return
    source_provider_summary = _require_mapping(
        payload.get("source_provider_summary"),
        field_name="source_provider_summary",
    )
    chain = _require_list(
        source_provider_summary.get("chain"),
        field_name="source_provider_summary.chain",
    )
    for idx, raw_provider in enumerate(chain):
        if not isinstance(raw_provider, str):
            raise AiBriefValidationError(
                f"source_provider_summary.chain[{idx}] must be a string"
            )
        if not raw_provider.strip():
            raise AiBriefValidationError(
                f"source_provider_summary.chain[{idx}] is required"
            )
    chain_providers: list[str] = []
    for idx, raw_provider in enumerate(chain):
        provider = raw_provider.strip().lower()
        if "," in provider:
            raise AiBriefValidationError(
                f"source_provider_summary.chain[{idx}] must be a provider id"
            )
        chain_providers.append(provider)
    if not chain_providers:
        raise AiBriefValidationError("source_provider_summary.chain is required")
    try:
        chain_providers = list(parse_source_provider_chain(",".join(chain_providers)))
    except ValueError as exc:
        raise AiBriefValidationError(f"source_provider_summary.chain {exc}") from exc
    chain_values = set(chain_providers)

    providers = _require_list(
        source_provider_summary.get("providers"),
        field_name="source_provider_summary.providers",
    )
    provider_names: list[str] = []
    for idx, raw_provider_summary in enumerate(providers):
        provider_summary = _require_mapping(
            raw_provider_summary,
            field_name=f"source_provider_summary.providers[{idx}]",
        )
        raw_provider = provider_summary.get("provider")
        if not isinstance(raw_provider, str) or not raw_provider.strip():
            raise AiBriefValidationError(
                f"source_provider_summary.providers[{idx}].provider is required"
            )
        provider = raw_provider.strip().lower()
        if provider not in chain_values:
            raise AiBriefValidationError(
                f"source_provider_summary.providers[{idx}].provider must be in chain"
            )
        provider_names.append(provider)
        raw_status = provider_summary.get("status")
        if not isinstance(raw_status, str) or not raw_status.strip():
            raise AiBriefValidationError(
                f"source_provider_summary.providers[{idx}].status is required"
            )
        status = raw_status.strip()
        if status not in _ALLOWED_SOURCE_PROVIDER_STATUSES:
            raise AiBriefValidationError(
                f"source_provider_summary.providers[{idx}].status must be one of "
                f"{sorted(_ALLOWED_SOURCE_PROVIDER_STATUSES)}"
            )
        covered = _non_negative_int(
            provider_summary.get("covered"),
            field_name=f"source_provider_summary.providers[{idx}].covered",
        )
        total = _non_negative_int(
            provider_summary.get("total"),
            field_name=f"source_provider_summary.providers[{idx}].total",
        )
        if covered > total:
            raise AiBriefValidationError(
                f"source_provider_summary.providers[{idx}].covered must be <= total"
            )

    if chain_providers == ["none"]:
        if provider_names:
            raise AiBriefValidationError(
                "source_provider_summary.providers must be empty when chain is ['none']"
            )
    elif provider_names != chain_providers:
        raise AiBriefValidationError(
            "source_provider_summary.providers must match "
            "source_provider_summary.chain order"
        )

    final = _require_mapping(
        source_provider_summary.get("final"),
        field_name="source_provider_summary.final",
    )
    final_counts = {
        field_name: _non_negative_int(
            final.get(field_name),
            field_name=f"source_provider_summary.final.{field_name}",
        )
        for field_name in (
            "recommendable_covered",
            "recommendable_total",
            "watch_covered",
            "watch_total",
        )
    }
    if final_counts["recommendable_covered"] > final_counts["recommendable_total"]:
        raise AiBriefValidationError(
            "source_provider_summary.final.recommendable_covered must be <= "
            "recommendable_total"
        )
    if final_counts["watch_covered"] > final_counts["watch_total"]:
        raise AiBriefValidationError(
            "source_provider_summary.final.watch_covered must be <= watch_total"
        )
    if chain_providers == ["none"] and (
        final_counts["recommendable_covered"] != 0 or final_counts["watch_covered"] != 0
    ):
        raise AiBriefValidationError(
            "source_provider_summary.final covered counts must be 0 when "
            "chain is ['none']"
        )
    expected_recommendable_total = _recommendable_count(payload)
    if final_counts["recommendable_total"] != expected_recommendable_total:
        raise AiBriefValidationError(
            "source_provider_summary.final.recommendable_total must match "
            "artifact recommendable count"
        )
    expected_watch_total = _watch_count(payload, watch_tickers=watch_tickers)
    if final_counts["watch_total"] != expected_watch_total:
        raise AiBriefValidationError(
            "source_provider_summary.final.watch_total must match artifact watch count"
        )

    recommendable_count = _summary_int(summary, "recommendable_count")
    if (
        recommendable_count is not None
        and final_counts["recommendable_total"] != recommendable_count
    ):
        raise AiBriefValidationError(
            "source_provider_summary.final.recommendable_total must match "
            "summary.recommendable_count"
        )
    watch_count = _summary_int(summary, "watch_count")
    if watch_count is not None and final_counts["watch_total"] != watch_count:
        raise AiBriefValidationError(
            "source_provider_summary.final.watch_total must match summary.watch_count"
        )


def _validate_hash_string(value: object, *, field_name: str) -> None:
    text = str(value or "").strip()
    digest = text.removeprefix("sha256:")
    if (
        not text.startswith("sha256:")
        or len(digest) != 64
        or any(char not in "0123456789abcdefABCDEF" for char in digest)
    ):
        raise AiBriefValidationError(f"{field_name} must be a sha256 hash")


def _model_trace_string_list(value: object, *, field_name: str) -> list[str]:
    rows = _require_list(value, field_name=field_name)
    strings: list[str] = []
    for idx, raw_row in enumerate(rows):
        if not isinstance(raw_row, str) or not raw_row.strip():
            raise AiBriefValidationError(f"{field_name}[{idx}] must be a string")
        strings.append(raw_row.strip())
    return strings


def _validate_model_trace_candidate_summaries(
    model_trace: Mapping[str, Any],
) -> dict[str, tuple[str, str]]:
    summaries = _require_list(
        model_trace.get("candidate_summaries"),
        field_name="model_trace.candidate_summaries",
    )
    expected_count = _non_negative_int(
        model_trace.get("candidate_count"),
        field_name="model_trace.candidate_count",
    )
    if len(summaries) != expected_count:
        raise AiBriefValidationError(
            "model_trace.candidate_count must match candidate_summaries"
        )
    candidates_by_id: dict[str, tuple[str, str]] = {}
    source_count_total = 0
    for idx, raw_summary in enumerate(summaries):
        summary = _require_mapping(
            raw_summary,
            field_name=f"model_trace.candidate_summaries[{idx}]",
        )
        candidate_id = str(summary.get("candidate_id") or "").strip()
        if not candidate_id:
            raise AiBriefValidationError(
                f"model_trace.candidate_summaries[{idx}].candidate_id is required"
            )
        if candidate_id in candidates_by_id:
            raise AiBriefValidationError(
                "model_trace candidate_id values must be unique"
            )
        ticker = str(summary.get("ticker") or "").strip()
        if not ticker:
            raise AiBriefValidationError(
                f"model_trace.candidate_summaries[{idx}].ticker is required"
            )
        status = str(summary.get("model_output_status") or "").strip()
        if status not in _ALLOWED_MODEL_OUTPUT_STATUSES:
            raise AiBriefValidationError(
                "model_trace.candidate_summaries[].model_output_status must be one of "
                f"{sorted(_ALLOWED_MODEL_OUTPUT_STATUSES)}"
            )
        _model_trace_string_list(
            summary.get("source_refs_available"),
            field_name=(
                f"model_trace.candidate_summaries[{idx}].source_refs_available"
            ),
        )
        source_count_total += _non_negative_int(
            summary.get("source_count"),
            field_name=f"model_trace.candidate_summaries[{idx}].source_count",
        )
        candidates_by_id[candidate_id] = (ticker, status)
    expected_source_count = _non_negative_int(
        model_trace.get("source_count"),
        field_name="model_trace.source_count",
    )
    if source_count_total != expected_source_count:
        raise AiBriefValidationError(
            "model_trace.source_count must match candidate_summaries"
        )
    return candidates_by_id


def _validate_model_trace_row_links(
    payload: Mapping[str, Any],
    *,
    model_trace_id: str,
    candidates_by_id: Mapping[str, tuple[str, str]],
) -> None:
    allowed_statuses_by_field = {
        "recommendations": {"recommended", "ambiguous_ticker_match"},
        "vetoed_candidates": {"vetoed", "ambiguous_ticker_match"},
        "watch_candidates": {"watch", "no_output", "ambiguous_ticker_match"},
    }
    for field_name in ("recommendations", "vetoed_candidates", "watch_candidates"):
        rows = _optional_list(payload, field_name)
        if rows is None:
            continue
        allowed_statuses = allowed_statuses_by_field[field_name]
        for idx, raw_row in enumerate(rows):
            if not isinstance(raw_row, Mapping):
                continue
            row_ticker = str(raw_row.get("ticker") or "").strip()
            row_trace_id = str(raw_row.get("model_trace_id") or "").strip()
            if row_trace_id != model_trace_id:
                raise AiBriefValidationError(
                    f"{field_name}[{idx}].model_trace_id must match model_trace"
                )
            row_candidate_id = raw_row.get("candidate_id")
            row_candidate_ids = raw_row.get("candidate_ids")
            if row_candidate_id is not None and row_candidate_ids is not None:
                raise AiBriefValidationError(
                    f"{field_name}[{idx}] must not include both candidate_id and "
                    "candidate_ids"
                )
            if row_candidate_ids is not None:
                candidate_ids = _model_trace_string_list(
                    row_candidate_ids,
                    field_name=f"{field_name}[{idx}].candidate_ids",
                )
                if not candidate_ids:
                    raise AiBriefValidationError(
                        f"{field_name}[{idx}].candidate_ids is required"
                    )
            else:
                candidate_id = str(row_candidate_id or "").strip()
                if not candidate_id:
                    raise AiBriefValidationError(
                        f"{field_name}[{idx}].candidate_id is required"
                    )
                candidate_ids = [candidate_id]
            unknown_ids = sorted(
                candidate_id
                for candidate_id in set(candidate_ids)
                if candidate_id not in candidates_by_id
            )
            if unknown_ids:
                raise AiBriefValidationError(
                    f"{field_name}[{idx}].candidate_id must exist in model_trace"
                )
            for candidate_id in candidate_ids:
                candidate_ticker, candidate_status = candidates_by_id[candidate_id]
                if row_ticker and candidate_ticker != row_ticker:
                    raise AiBriefValidationError(
                        f"{field_name}[{idx}].candidate_id must match row ticker"
                    )
                if candidate_status not in allowed_statuses:
                    raise AiBriefValidationError(
                        f"{field_name}[{idx}].candidate_id must match row status"
                    )


def _validate_model_trace_context(
    payload: Mapping[str, Any],
    model_trace: Mapping[str, Any],
) -> None:
    for field_name in (
        "market",
        "model_provider",
        "model_name",
        "source_entry_report",
    ):
        if (
            str(model_trace.get(field_name) or "").strip()
            != str(payload.get(field_name) or "").strip()
        ):
            raise AiBriefValidationError(
                f"model_trace.{field_name} must match artifact"
            )

    eligible_tickers = _model_trace_string_list(
        model_trace.get("eligible_tickers"),
        field_name="model_trace.eligible_tickers",
    )
    artifact_eligible_tickers = _model_trace_string_list(
        payload.get("eligible_tickers"),
        field_name="eligible_tickers",
    )
    if eligible_tickers != artifact_eligible_tickers:
        raise AiBriefValidationError("model_trace.eligible_tickers must match artifact")

    watch_tickers = _model_trace_string_list(
        model_trace.get("watch_tickers"),
        field_name="model_trace.watch_tickers",
    )
    artifact_watch_tickers = _model_trace_string_list(
        payload.get("watch_tickers"),
        field_name="watch_tickers",
    )
    if watch_tickers != artifact_watch_tickers:
        raise AiBriefValidationError("model_trace.watch_tickers must match artifact")

    attempt_ids = _model_trace_string_list(
        model_trace.get("attempt_ids"),
        field_name="model_trace.attempt_ids",
    )
    model_attempts = _require_list(
        payload.get("model_attempts"),
        field_name="model_attempts",
    )
    expected_attempt_ids: list[str] = []
    for idx, raw_attempt in enumerate(model_attempts):
        attempt = _require_mapping(raw_attempt, field_name=f"model_attempts[{idx}]")
        role = str(attempt.get("role") or "").strip()
        model_name = str(attempt.get("model_name") or "").strip()
        if role and model_name:
            expected_attempt_ids.append(f"{role}:{model_name}")
    if attempt_ids != expected_attempt_ids:
        raise AiBriefValidationError(
            "model_trace.attempt_ids must match model_attempts"
        )


def _validate_model_trace(payload: Mapping[str, Any]) -> None:
    if "model_trace" not in payload:
        return
    model_trace = _require_mapping(payload.get("model_trace"), field_name="model_trace")
    if model_trace.get("schema") != _MODEL_TRACE_SCHEMA:
        raise AiBriefValidationError(
            f"model_trace.schema must be {_MODEL_TRACE_SCHEMA!r}"
        )
    model_trace_id = str(model_trace.get("model_trace_id") or "").strip()
    if not model_trace_id:
        raise AiBriefValidationError("model_trace.model_trace_id is required")
    for field_name in (
        "prompt_version",
        "output_schema_version",
        "model_provider",
        "model_name",
        "market",
        "source_entry_report",
    ):
        if not str(model_trace.get(field_name) or "").strip():
            raise AiBriefValidationError(f"model_trace.{field_name} is required")
    _validate_hash_string(
        model_trace.get("request_hash"),
        field_name="model_trace.request_hash",
    )
    _validate_hash_string(
        model_trace.get("source_catalog_hash"),
        field_name="model_trace.source_catalog_hash",
    )
    request_status = str(model_trace.get("request_status") or "").strip()
    if request_status not in _ALLOWED_MODEL_TRACE_REQUEST_STATUSES:
        raise AiBriefValidationError(
            "model_trace.request_status must be one of "
            f"{sorted(_ALLOWED_MODEL_TRACE_REQUEST_STATUSES)}"
        )
    _model_trace_string_list(
        model_trace.get("eligible_tickers"),
        field_name="model_trace.eligible_tickers",
    )
    _model_trace_string_list(
        model_trace.get("watch_tickers"),
        field_name="model_trace.watch_tickers",
    )
    _model_trace_string_list(
        model_trace.get("attempt_ids"),
        field_name="model_trace.attempt_ids",
    )
    _non_negative_int(
        model_trace.get("source_count"),
        field_name="model_trace.source_count",
    )
    normalization_issues = _require_list(
        model_trace.get("normalization_issues"),
        field_name="model_trace.normalization_issues",
    )
    for idx, raw_issue in enumerate(normalization_issues):
        if not isinstance(raw_issue, Mapping):
            raise AiBriefValidationError(
                f"model_trace.normalization_issues[{idx}] must be an object"
            )
    _validate_model_trace_context(payload, model_trace)
    candidates_by_id = _validate_model_trace_candidate_summaries(model_trace)
    _validate_model_trace_row_links(
        payload,
        model_trace_id=model_trace_id,
        candidates_by_id=candidates_by_id,
    )


def validate_ai_brief_artifact(payload: Mapping[str, Any], *, now: dt.datetime) -> None:
    if payload.get("schema") != _ARTIFACT_SCHEMA:
        raise AiBriefValidationError(f"schema must be {_ARTIFACT_SCHEMA!r}")
    if payload.get("type") != _REPORT_TYPE:
        raise AiBriefValidationError(f"type must be {_REPORT_TYPE!r}")
    _parse_offset_datetime(payload.get("generated_at"), field_name="generated_at")

    market = str(payload.get("market") or "").strip().upper()
    if market not in ALLOWED_MARKETS:
        raise AiBriefValidationError(f"market must be one of {sorted(ALLOWED_MARKETS)}")
    if str(payload.get("model_provider") or "").strip() not in _ALLOWED_MODEL_PROVIDERS:
        raise AiBriefValidationError(
            f"model_provider must be one of {sorted(_ALLOWED_MODEL_PROVIDERS)}"
        )
    if not str(payload.get("model_name") or "").strip():
        raise AiBriefValidationError("model_name is required")
    if not str(payload.get("source_entry_report") or "").strip():
        raise AiBriefValidationError("source_entry_report is required")

    summary = _require_mapping(payload.get("summary"), field_name="summary")
    watch_tickers = _watch_tickers(payload)
    _validate_recommendations(payload, now=now)
    _validate_candidate_list(
        payload,
        "excluded_candidates",
        allowed_actions={"ENTER", "REVIEW", "SKIP"},
    )
    _validate_candidate_list(
        payload,
        "vetoed_candidates",
        allowed_actions={"PASS", "SKIP"},
        allowed_tickers=_eligible_tickers(payload),
    )
    _validate_candidate_list(
        payload,
        "cap_excluded_candidates",
        allowed_actions={"ENTER", "REVIEW", "SKIP"},
    )
    _validate_watch_candidates(payload, watch_tickers=watch_tickers, now=now)
    _validate_candidate_role_counts(payload, summary=summary)
    _validate_issue_list(payload, "source_issues")
    _validate_issue_list(payload, "system_issues")
    _validate_source_provider_summary(
        payload,
        summary=summary,
        watch_tickers=watch_tickers,
    )
    _validate_model_trace(payload)
    _validate_summary_counts(payload, summary=summary, watch_tickers=watch_tickers)
    try:
        validate_optional_ai_brief_state_fields(payload)
    except ValueError as exc:
        raise AiBriefValidationError(str(exc)) from exc


def write_ai_brief_report(
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
    payload = with_inferred_ai_brief_state(payload)
    validate_ai_brief_artifact(payload, now=validation_now)

    lock_path = os.path.join(report_dir, ".ai-brief.report.lock")
    with advisory_path_lock(lock_path):
        out_path = next_report_path(report_dir, report_date, "ai-brief")
        atomic_write_json(out_path, payload, ensure_ascii=False, indent=2)

    return out_path


__all__ = [
    "AiBriefValidationError",
    "validate_ai_brief_artifact",
    "write_ai_brief_report",
]
