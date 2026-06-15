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
_REPORT_TYPE = "ai_brief"
_MAX_RECOMMENDATIONS = 3
_MAX_SOURCES_PER_TICKER = 3
_ALLOWED_MODEL_PROVIDERS = frozenset({"fake", "openai"})
_ALLOWED_SOURCE_PROVIDER_STATUSES = frozenset({"success", "failed", "skipped"})


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
    return len(source_rows)


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


def _summary_int(summary: Mapping[str, Any], field_name: str) -> int | None:
    if field_name not in summary:
        return None
    value = summary.get(field_name)
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise AiBriefValidationError(f"summary.{field_name} must be a non-negative int")
    return value


def _validate_summary_counts(
    payload: Mapping[str, Any],
    *,
    summary: Mapping[str, Any],
    watch_tickers: list[str] | None,
) -> None:
    expected_counts = {
        "preselected_count": _array_count(payload, "eligible_tickers"),
        "recommendation_count": _array_count(payload, "recommendations"),
        "excluded_count": _array_count(payload, "excluded_candidates"),
        "vetoed_count": _array_count(payload, "vetoed_candidates"),
        "cap_excluded_count": _array_count(payload, "cap_excluded_candidates"),
        "source_issue_count": _array_count(payload, "source_issues"),
        "system_issue_count": _array_count(payload, "system_issues"),
        "recommendable_count": _array_count(payload, "eligible_tickers")
        + _array_count(payload, "cap_excluded_candidates"),
        "watch_count": (
            len(watch_tickers)
            if watch_tickers is not None
            else len(_optional_list(payload, "watch_candidates") or [])
        ),
    }
    for field_name, expected_count in expected_counts.items():
        actual_count = _summary_int(summary, field_name)
        if actual_count is not None and actual_count != expected_count:
            raise AiBriefValidationError(
                f"summary.{field_name} must be {expected_count}, got {actual_count!r}"
            )


def _non_negative_int(value: object, *, field_name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise AiBriefValidationError(f"{field_name} must be a non-negative int")
    return value


def _validate_source_provider_summary(
    payload: Mapping[str, Any],
    *,
    summary: Mapping[str, Any],
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
    chain_values = {provider.strip() for provider in chain}

    providers = _require_list(
        source_provider_summary.get("providers"),
        field_name="source_provider_summary.providers",
    )
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
        provider = raw_provider.strip()
        if provider not in chain_values:
            raise AiBriefValidationError(
                f"source_provider_summary.providers[{idx}].provider must be in chain"
            )
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
    _validate_issue_list(payload, "source_issues")
    _validate_issue_list(payload, "system_issues")
    _validate_summary_counts(payload, summary=summary, watch_tickers=watch_tickers)
    _validate_source_provider_summary(payload, summary=summary)
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
