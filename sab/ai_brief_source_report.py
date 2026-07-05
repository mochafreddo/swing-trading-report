from __future__ import annotations

import datetime as dt
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from typing import Any

from . import ai_brief_url_safety as url_safety
from .ai_brief_eval_common import parse_iso_offset_datetime
from .observability import sanitize_log_text

SOURCE_REPORT_SCHEMA = "sab.ai_brief_sources.v1"
SOURCE_REPORT_TYPE = "ai_brief_sources"
SOURCE_FRESHNESS_HOURS = 72
SOURCE_FUTURE_SKEW_MINUTES = 15
MAX_SOURCES_PER_TICKER = 3
_ALLOWED_SOURCE_ISSUE_SEVERITIES = frozenset({"INFO", "WARN", "ERROR"})

type SourceRowUrlValidator = Callable[..., str]


@dataclass(frozen=True)
class SourceRowsNormalizationResult:
    sources_by_ticker: dict[str, list[dict[str, object]]] = field(default_factory=dict)
    source_issues: list[dict[str, object]] = field(default_factory=list)


def _validate_source_report_row_url(
    value: object,
    *,
    field_name: str = "url",
    **_: object,
) -> str:
    return url_safety.validate_url(value, field_name=field_name)


def normalize_source_rows(
    *,
    rows: list[object],
    eligible_tickers: set[str],
    now: dt.datetime,
    issue_prefix: str,
    issue_subject: str,
    source_url_deadline: float | None = None,
    resolve_source_url_hostnames: bool = False,
    url_validator: SourceRowUrlValidator = _validate_source_report_row_url,
) -> SourceRowsNormalizationResult:
    sources_by_ticker: dict[str, list[dict[str, object]]] = {}
    source_issues: list[dict[str, object]] = []
    seen_urls_by_ticker: dict[str, set[str]] = {}
    for idx, raw_row in enumerate(rows):
        if not isinstance(raw_row, Mapping):
            source_issues.append(
                source_issue(
                    ticker=None,
                    code=f"{issue_prefix}_invalid_row",
                    message=(f"sources[{idx}] was ignored because it is not an object"),
                )
            )
            continue
        ticker = str(raw_row.get("ticker") or "").strip()
        if not ticker:
            source_issues.append(
                source_issue(
                    ticker=None,
                    code=f"{issue_prefix}_invalid_row",
                    message=f"sources[{idx}] was ignored because ticker is required",
                )
            )
            continue
        if ticker not in eligible_tickers:
            source_issues.append(
                source_issue(
                    ticker=ticker,
                    code=f"{issue_prefix}_unknown_ticker",
                    message=f"{issue_subject} row ignored because ticker is not eligible",
                )
            )
            continue

        normalized, issue = normalize_source_row(
            raw_row,
            ticker=ticker,
            now=now,
            issue_prefix=issue_prefix,
            issue_subject=issue_subject,
            source_url_deadline=source_url_deadline,
            resolve_source_url_hostnames=resolve_source_url_hostnames,
            url_validator=url_validator,
        )
        if issue is None:
            source_url = str(normalized.get("url") or "").strip()
            seen_urls = seen_urls_by_ticker.setdefault(ticker, set())
            if source_url in seen_urls:
                source_issues.append(
                    source_issue(
                        ticker=ticker,
                        code=f"{issue_prefix}_duplicate_url",
                        message=f"{issue_subject} row ignored because URL is duplicated",
                    )
                )
                continue
            seen_urls.add(source_url)
            ticker_sources = sources_by_ticker.setdefault(ticker, [])
            if len(ticker_sources) >= MAX_SOURCES_PER_TICKER:
                source_issues.append(
                    source_issue(
                        ticker=ticker,
                        code=f"{issue_prefix}_cap_exceeded",
                        message=(
                            f"{issue_subject} row ignored because ticker already has "
                            f"{MAX_SOURCES_PER_TICKER} sources"
                        ),
                    )
                )
                continue
            ticker_sources.append(normalized)
        else:
            source_issues.append(issue)

    return SourceRowsNormalizationResult(
        sources_by_ticker=sources_by_ticker,
        source_issues=source_issues,
    )


def normalize_source_report_issues(
    payload: Mapping[str, Any],
    *,
    issue_prefix: str,
    issue_subject: str,
    eligible_tickers: set[str],
) -> list[dict[str, object]]:
    issues: list[dict[str, object]] = []
    for field_name in ("source_issues", "issues"):
        raw_issues = payload.get(field_name)
        if raw_issues is None:
            continue
        if not isinstance(raw_issues, list):
            issues.append(
                source_issue(
                    ticker=None,
                    code=f"{issue_prefix}_invalid_issue",
                    message=(
                        f"{issue_subject} {field_name} ignored because it is not a list"
                    ),
                )
            )
            continue
        for idx, raw_issue in enumerate(raw_issues):
            issue = normalize_source_report_issue(
                raw_issue,
                field_name=field_name,
                idx=idx,
                issue_prefix=issue_prefix,
                issue_subject=issue_subject,
            )
            ticker = issue.get("ticker")
            if ticker is not None and str(ticker) not in eligible_tickers:
                continue
            issues.append(issue)
    return issues


def validate_source_report_contract(
    payload: Mapping[str, Any],
    *,
    subject: str,
) -> None:
    schema = str(payload.get("schema") or "").strip()
    if schema and schema != SOURCE_REPORT_SCHEMA:
        raise ValueError(f"{subject} schema must be {SOURCE_REPORT_SCHEMA!r}")
    report_type = str(payload.get("type") or "").strip()
    if report_type and report_type != SOURCE_REPORT_TYPE:
        raise ValueError(f"{subject} type must be {SOURCE_REPORT_TYPE!r}")


def normalize_source_report_issue(
    raw_issue: object,
    *,
    field_name: str,
    idx: int,
    issue_prefix: str,
    issue_subject: str,
) -> dict[str, object]:
    if not isinstance(raw_issue, Mapping):
        return source_issue(
            ticker=None,
            code=f"{issue_prefix}_invalid_issue",
            message=(
                f"{issue_subject} {field_name}[{idx}] ignored because it is "
                "not an object"
            ),
        )
    code = str(raw_issue.get("code") or "").strip()
    message = sanitize_log_text(str(raw_issue.get("message") or "").strip())
    severity = str(raw_issue.get("severity") or "WARN").strip().upper()
    if not code or not message:
        return source_issue(
            ticker=None,
            code=f"{issue_prefix}_invalid_issue",
            message=(
                f"{issue_subject} {field_name}[{idx}] ignored because code and "
                "message are required"
            ),
        )
    if severity not in _ALLOWED_SOURCE_ISSUE_SEVERITIES:
        return source_issue(
            ticker=None,
            code=f"{issue_prefix}_invalid_issue",
            message=(
                f"{issue_subject} {field_name}[{idx}] ignored because severity "
                f"must be one of {sorted(_ALLOWED_SOURCE_ISSUE_SEVERITIES)}"
            ),
        )
    ticker = raw_issue.get("ticker")
    return {
        "ticker": None if ticker is None else str(ticker).strip() or None,
        "code": code,
        "severity": severity,
        "message": message,
    }


def normalize_source_row(
    row: Mapping[str, Any],
    *,
    ticker: str,
    now: dt.datetime,
    issue_prefix: str,
    issue_subject: str,
    source_url_deadline: float | None,
    resolve_source_url_hostnames: bool,
    url_validator: SourceRowUrlValidator,
) -> tuple[dict[str, object], None] | tuple[dict[str, object], dict[str, object]]:
    title = str(row.get("title") or "").strip()
    url = str(row.get("url") or "").strip()
    if not title:
        return {}, source_issue(
            ticker=ticker,
            code=f"{issue_prefix}_invalid_row",
            message=f"{issue_subject} row ignored because title is required",
        )
    try:
        url = url_validator(
            url,
            field_name="url",
            deadline=source_url_deadline,
            resolve_hostname=resolve_source_url_hostnames,
        )
    except ValueError as exc:
        return {}, source_issue(
            ticker=ticker,
            code=f"{issue_prefix}_invalid_row",
            message=f"{issue_subject} row ignored because {exc}",
        )
    try:
        published_at = parse_offset_datetime(row.get("published_at"))
    except ValueError as exc:
        return {}, source_issue(
            ticker=ticker,
            code=f"{issue_prefix}_invalid_row",
            message=f"{issue_subject} row ignored because {exc}",
        )
    if is_ai_brief_source_stale(published_at, now=now):
        return {}, source_issue(
            ticker=ticker,
            code=f"{issue_prefix}_stale",
            message=(
                f"{issue_subject} row ignored because published_at is older than "
                f"{SOURCE_FRESHNESS_HOURS}h"
            ),
        )
    if is_ai_brief_source_future(published_at, now=now):
        return {}, source_issue(
            ticker=ticker,
            code=f"{issue_prefix}_future",
            message=(
                f"{issue_subject} row ignored because published_at is more than "
                f"{SOURCE_FUTURE_SKEW_MINUTES}m in the future"
            ),
        )
    source: dict[str, object] = {
        "title": title,
        "url": url,
        "published_at": published_at.isoformat(),
    }
    return source, None


def parse_offset_datetime(value: object) -> dt.datetime:
    return parse_iso_offset_datetime(value, field_name="published_at")


def is_ai_brief_source_stale(
    published_at: dt.datetime,
    *,
    now: dt.datetime,
    freshness_hours: float = SOURCE_FRESHNESS_HOURS,
) -> bool:
    return now.astimezone(dt.UTC) - published_at.astimezone(dt.UTC) > dt.timedelta(
        hours=freshness_hours
    )


def is_ai_brief_source_future(
    published_at: dt.datetime,
    *,
    now: dt.datetime,
) -> bool:
    return published_at.astimezone(dt.UTC) - now.astimezone(dt.UTC) > dt.timedelta(
        minutes=SOURCE_FUTURE_SKEW_MINUTES
    )


def source_issue(*, ticker: str | None, code: str, message: str) -> dict[str, object]:
    return {
        "ticker": ticker,
        "code": code,
        "severity": "WARN",
        "message": sanitize_log_text(message),
    }


__all__ = [
    "MAX_SOURCES_PER_TICKER",
    "SOURCE_FRESHNESS_HOURS",
    "SOURCE_FUTURE_SKEW_MINUTES",
    "SOURCE_REPORT_SCHEMA",
    "SOURCE_REPORT_TYPE",
    "SourceRowsNormalizationResult",
    "is_ai_brief_source_future",
    "is_ai_brief_source_stale",
    "normalize_source_report_issues",
    "normalize_source_rows",
    "parse_offset_datetime",
    "source_issue",
    "validate_source_report_contract",
]
