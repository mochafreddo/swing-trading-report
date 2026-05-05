from __future__ import annotations

import datetime as dt
import os
from collections.abc import Mapping
from typing import Any

from ..utils.atomic_io import advisory_path_lock, atomic_write_json
from .time_label import normalize_artifact_date

_ARTIFACT_SCHEMA = "sab.ai_brief.v1"
_REPORT_TYPE = "ai_brief"
_MAX_RECOMMENDATIONS = 3
_MAX_SOURCES_PER_TICKER = 3
_SOURCE_FRESHNESS_HOURS = 72
_ALLOWED_MARKETS = frozenset({"KR", "US"})
_ALLOWED_MODEL_PROVIDERS = frozenset({"fake", "openai"})
_ALLOWED_CONFIDENCE = frozenset({"LOW", "MEDIUM", "HIGH"})
_ALLOWED_ISSUE_SEVERITY = frozenset({"INFO", "WARN", "ERROR"})
_AUTOMATED_ORDER_PHRASES = (
    "buy now",
    "execute order",
    "place order",
    "submit order",
    "automatic order",
    "automated order",
)


class AiBriefValidationError(ValueError):
    """Raised when an AI brief artifact violates the local JSON contract."""


def _ensure_dir(path: str) -> None:
    os.makedirs(path, exist_ok=True)


def _next_report_path(report_dir: str, date: str) -> str:
    suffix = ".ai-brief.json"
    base = os.path.join(report_dir, f"{date}{suffix}")
    if not os.path.exists(base):
        return base
    i = 1
    while True:
        path = os.path.join(report_dir, f"{date}-{i}{suffix}")
        if not os.path.exists(path):
            return path
        i += 1


def _offset_iso(now: dt.datetime | None = None) -> str:
    if now is None:
        aware = dt.datetime.now().astimezone()
    elif now.tzinfo is None:
        local_tz = dt.datetime.now().astimezone().tzinfo or dt.UTC
        aware = now.replace(tzinfo=local_tz)
    else:
        aware = now
    return aware.replace(microsecond=0).isoformat(timespec="seconds")


def _parse_offset_datetime(value: object, *, field_name: str) -> dt.datetime:
    text = str(value or "").strip()
    if not text:
        raise AiBriefValidationError(f"{field_name} must be an offset datetime")
    try:
        parsed = dt.datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError as exc:
        raise AiBriefValidationError(
            f"{field_name} must be an ISO 8601 datetime"
        ) from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise AiBriefValidationError(f"{field_name} must include a UTC offset")
    return parsed


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
        if severity not in _ALLOWED_ISSUE_SEVERITY:
            raise AiBriefValidationError(
                f"{field_name}[{idx}].severity must be one of "
                f"{sorted(_ALLOWED_ISSUE_SEVERITY)}"
            )


def _validate_sources(
    *,
    recommendation: Mapping[str, Any],
    recommendation_index: int,
    now: dt.datetime,
) -> int:
    sources = _require_list(
        recommendation.get("sources"),
        field_name=f"recommendations[{recommendation_index}].sources",
    )
    if len(sources) > _MAX_SOURCES_PER_TICKER:
        raise AiBriefValidationError(
            "recommendations[].sources must contain at most "
            f"{_MAX_SOURCES_PER_TICKER} sources"
        )
    for source_index, raw_source in enumerate(sources):
        source = _require_mapping(
            raw_source,
            field_name=f"recommendations[{recommendation_index}].sources[{source_index}]",
        )
        title = str(source.get("title") or "").strip()
        url = str(source.get("url") or "").strip()
        if not title:
            raise AiBriefValidationError("source title is required")
        if not url:
            raise AiBriefValidationError("source url is required")
        published_at = _parse_offset_datetime(
            source.get("published_at"),
            field_name="source.published_at",
        )
        if now.astimezone(dt.UTC) - published_at.astimezone(dt.UTC) > dt.timedelta(
            hours=_SOURCE_FRESHNESS_HOURS
        ):
            raise AiBriefValidationError("source.published_at must be within 72h")
    return len(sources)


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
    text = " ".join(str(item).lower() for item in fields)
    if any(phrase in text for phrase in _AUTOMATED_ORDER_PHRASES):
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
        if confidence not in _ALLOWED_CONFIDENCE:
            raise AiBriefValidationError(
                "recommendations[].confidence must be one of "
                f"{sorted(_ALLOWED_CONFIDENCE)}"
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


def _eligible_tickers(payload: Mapping[str, Any]) -> set[str]:
    return {
        str(ticker).strip()
        for ticker in _require_list(
            payload.get("eligible_tickers"), field_name="eligible_tickers"
        )
        if str(ticker).strip()
    }


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


def validate_ai_brief_artifact(payload: Mapping[str, Any], *, now: dt.datetime) -> None:
    if payload.get("schema") != _ARTIFACT_SCHEMA:
        raise AiBriefValidationError(f"schema must be {_ARTIFACT_SCHEMA!r}")
    if payload.get("type") != _REPORT_TYPE:
        raise AiBriefValidationError(f"type must be {_REPORT_TYPE!r}")
    _parse_offset_datetime(payload.get("generated_at"), field_name="generated_at")

    market = str(payload.get("market") or "").strip().upper()
    if market not in _ALLOWED_MARKETS:
        raise AiBriefValidationError(
            f"market must be one of {sorted(_ALLOWED_MARKETS)}"
        )
    if str(payload.get("model_provider") or "").strip() not in _ALLOWED_MODEL_PROVIDERS:
        raise AiBriefValidationError(
            f"model_provider must be one of {sorted(_ALLOWED_MODEL_PROVIDERS)}"
        )
    if not str(payload.get("model_name") or "").strip():
        raise AiBriefValidationError("model_name is required")
    if not str(payload.get("source_entry_report") or "").strip():
        raise AiBriefValidationError("source_entry_report is required")

    _require_mapping(payload.get("summary"), field_name="summary")
    _validate_recommendations(payload, now=now)
    _validate_candidate_list(
        payload, "excluded_candidates", allowed_actions={"REVIEW", "SKIP"}
    )
    _validate_candidate_list(
        payload,
        "vetoed_candidates",
        allowed_actions={"PASS", "SKIP"},
        allowed_tickers=_eligible_tickers(payload),
    )
    _validate_candidate_list(
        payload, "cap_excluded_candidates", allowed_actions={"ENTER"}
    )
    _validate_issue_list(payload, "source_issues")
    _validate_issue_list(payload, "system_issues")


def write_ai_brief_report(
    *,
    report_dir: str,
    artifact: Mapping[str, Any],
    now: dt.datetime | None = None,
    artifact_date: object | None = None,
) -> str:
    _ensure_dir(report_dir)
    generated_at = str(artifact.get("generated_at") or _offset_iso(now)).strip()
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
    validate_ai_brief_artifact(payload, now=validation_now)

    lock_path = os.path.join(report_dir, ".ai-brief.report.lock")
    with advisory_path_lock(lock_path):
        out_path = _next_report_path(report_dir, report_date)
        atomic_write_json(out_path, payload, ensure_ascii=False, indent=2)

    return out_path


__all__ = [
    "AiBriefValidationError",
    "validate_ai_brief_artifact",
    "write_ai_brief_report",
]
