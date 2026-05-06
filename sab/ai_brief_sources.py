from __future__ import annotations

import datetime as dt
import json
import math
import os
from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any

import requests  # type: ignore[import-untyped]

SOURCE_PROVIDER_NONE = "none"
SOURCE_PROVIDER_LOCAL_JSON = "local-json"
SOURCE_PROVIDER_HTTP_JSON = "http-json"
SOURCE_FRESHNESS_HOURS = 72
MAX_SOURCES_PER_TICKER = 3
DEFAULT_SOURCE_TIMEOUT_SECONDS = 10.0


@dataclass(frozen=True)
class AiBriefSourceProviderResult:
    sources_by_ticker: dict[str, list[dict[str, object]]] = field(default_factory=dict)
    source_issues: list[dict[str, object]] = field(default_factory=list)


class AiBriefSourceProviderError(RuntimeError):
    code = "source_provider_failed"


class AiBriefSourceProviderTimeoutError(AiBriefSourceProviderError):
    code = "source_provider_timeout"


def load_ai_brief_sources(
    *,
    source_provider: str,
    source_report_path: str | None,
    source_api_url: str | None = None,
    source_timeout_seconds: float | None = None,
    eligible_tickers: set[str],
    now: dt.datetime | None = None,
) -> AiBriefSourceProviderResult:
    if source_provider == SOURCE_PROVIDER_NONE:
        return AiBriefSourceProviderResult()
    resolved_now = now or dt.datetime.now().astimezone()
    if source_provider == SOURCE_PROVIDER_LOCAL_JSON:
        if source_report_path is None or not source_report_path.strip():
            raise AiBriefSourceProviderError(
                "--source-provider local-json requires --source-report"
            )
        return _load_local_json_source_report(
            source_report_path=source_report_path,
            eligible_tickers=eligible_tickers,
            now=resolved_now,
        )
    if source_provider == SOURCE_PROVIDER_HTTP_JSON:
        return _load_http_json_source_report(
            source_api_url=source_api_url,
            source_timeout_seconds=(
                DEFAULT_SOURCE_TIMEOUT_SECONDS
                if source_timeout_seconds is None
                else source_timeout_seconds
            ),
            eligible_tickers=eligible_tickers,
            now=resolved_now,
        )
    raise AiBriefSourceProviderError(f"unsupported source provider {source_provider!r}")


def _load_http_json_source_report(
    *,
    source_api_url: str | None,
    source_timeout_seconds: float,
    eligible_tickers: set[str],
    now: dt.datetime,
) -> AiBriefSourceProviderResult:
    url = str(source_api_url or "").strip()
    if not url:
        raise AiBriefSourceProviderError(
            "--source-provider http-json requires --source-api-url or "
            "AI_BRIEF_SOURCE_API_URL"
        )
    if not math.isfinite(source_timeout_seconds) or source_timeout_seconds <= 0:
        raise AiBriefSourceProviderError("source timeout seconds must be positive")
    request_payload = {
        "schema": "sab.ai_brief_source_request.v1",
        "tickers": sorted(eligible_tickers),
        "max_sources_per_ticker": MAX_SOURCES_PER_TICKER,
        "freshness_hours": SOURCE_FRESHNESS_HOURS,
    }
    headers = {
        "Accept": "application/json",
        "Content-Type": "application/json",
    }
    api_token = str(os.getenv("AI_BRIEF_SOURCE_API_TOKEN") or "").strip()
    if api_token:
        headers["Authorization"] = f"Bearer {api_token}"

    try:
        response = requests.Session().post(
            url,
            headers=headers,
            json=request_payload,
            timeout=source_timeout_seconds,
        )
    except requests.Timeout as exc:
        raise AiBriefSourceProviderTimeoutError("source API request timed out") from exc
    except requests.RequestException as exc:
        raise AiBriefSourceProviderError(f"source API request failed: {exc}") from exc

    if response.status_code >= 400:
        raise AiBriefSourceProviderError(
            f"source API request failed with HTTP {response.status_code}"
        )
    try:
        payload = response.json()
    except ValueError as exc:
        raise AiBriefSourceProviderError(
            "source API response was not valid JSON"
        ) from exc
    if not isinstance(payload, Mapping):
        raise AiBriefSourceProviderError(
            "source API response must contain a JSON object"
        )
    rows = payload.get("sources")
    if not isinstance(rows, list):
        raise AiBriefSourceProviderError("source API response sources must be a list")
    return _normalize_source_rows(
        rows=rows,
        eligible_tickers=eligible_tickers,
        now=now,
        issue_prefix="http_source",
        issue_subject="http source",
    )


def _load_local_json_source_report(
    *,
    source_report_path: str,
    eligible_tickers: set[str],
    now: dt.datetime,
) -> AiBriefSourceProviderResult:
    try:
        with open(source_report_path, encoding="utf-8") as fp:
            payload = json.load(fp)
    except (OSError, json.JSONDecodeError) as exc:
        raise AiBriefSourceProviderError(
            f"failed to load source report: {exc}"
        ) from exc
    if not isinstance(payload, Mapping):
        raise AiBriefSourceProviderError("source report must contain a JSON object")
    rows = payload.get("sources")
    if not isinstance(rows, list):
        raise AiBriefSourceProviderError("source report sources must be a list")

    return _normalize_source_rows(
        rows=rows,
        eligible_tickers=eligible_tickers,
        now=now,
        issue_prefix="local_source",
        issue_subject="local source",
    )


def _normalize_source_rows(
    *,
    rows: list[object],
    eligible_tickers: set[str],
    now: dt.datetime,
    issue_prefix: str,
    issue_subject: str,
) -> AiBriefSourceProviderResult:
    sources_by_ticker: dict[str, list[dict[str, object]]] = {}
    source_issues: list[dict[str, object]] = []
    for idx, raw_row in enumerate(rows):
        if not isinstance(raw_row, Mapping):
            source_issues.append(
                _source_issue(
                    ticker=None,
                    code=f"{issue_prefix}_invalid_row",
                    message=(f"sources[{idx}] was ignored because it is not an object"),
                )
            )
            continue
        ticker = str(raw_row.get("ticker") or "").strip()
        if not ticker:
            source_issues.append(
                _source_issue(
                    ticker=None,
                    code=f"{issue_prefix}_invalid_row",
                    message=f"sources[{idx}] was ignored because ticker is required",
                )
            )
            continue
        if ticker not in eligible_tickers:
            source_issues.append(
                _source_issue(
                    ticker=ticker,
                    code=f"{issue_prefix}_unknown_ticker",
                    message=f"{issue_subject} row ignored because ticker is not eligible",
                )
            )
            continue

        normalized, issue = _normalize_source_row(
            raw_row,
            ticker=ticker,
            now=now,
            issue_prefix=issue_prefix,
            issue_subject=issue_subject,
        )
        if issue is None:
            ticker_sources = sources_by_ticker.setdefault(ticker, [])
            if len(ticker_sources) >= MAX_SOURCES_PER_TICKER:
                source_issues.append(
                    _source_issue(
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

    return AiBriefSourceProviderResult(
        sources_by_ticker=sources_by_ticker,
        source_issues=source_issues,
    )


def _normalize_source_row(
    row: Mapping[str, Any],
    *,
    ticker: str,
    now: dt.datetime,
    issue_prefix: str,
    issue_subject: str,
) -> tuple[dict[str, object], None] | tuple[dict[str, object], dict[str, object]]:
    title = str(row.get("title") or "").strip()
    url = str(row.get("url") or "").strip()
    if not title:
        return {}, _source_issue(
            ticker=ticker,
            code=f"{issue_prefix}_invalid_row",
            message=f"{issue_subject} row ignored because title is required",
        )
    if not url:
        return {}, _source_issue(
            ticker=ticker,
            code=f"{issue_prefix}_invalid_row",
            message=f"{issue_subject} row ignored because url is required",
        )
    try:
        published_at = _parse_offset_datetime(row.get("published_at"))
    except ValueError as exc:
        return {}, _source_issue(
            ticker=ticker,
            code=f"{issue_prefix}_invalid_row",
            message=f"{issue_subject} row ignored because {exc}",
        )
    if now.astimezone(dt.UTC) - published_at.astimezone(dt.UTC) > dt.timedelta(
        hours=SOURCE_FRESHNESS_HOURS
    ):
        return {}, _source_issue(
            ticker=ticker,
            code=f"{issue_prefix}_stale",
            message=(
                f"{issue_subject} row ignored because published_at is older than "
                f"{SOURCE_FRESHNESS_HOURS}h"
            ),
        )
    source: dict[str, object] = {
        "title": title,
        "url": url,
        "published_at": published_at.isoformat(),
    }
    return source, None


def _parse_offset_datetime(value: object) -> dt.datetime:
    text = str(value or "").strip()
    if not text:
        raise ValueError("published_at is required")
    try:
        parsed = dt.datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError("published_at must be an ISO 8601 datetime") from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError("published_at must include a UTC offset")
    return parsed


def _source_issue(*, ticker: str | None, code: str, message: str) -> dict[str, object]:
    return {
        "ticker": ticker,
        "code": code,
        "severity": "WARN",
        "message": message,
    }


__all__ = [
    "DEFAULT_SOURCE_TIMEOUT_SECONDS",
    "MAX_SOURCES_PER_TICKER",
    "SOURCE_FRESHNESS_HOURS",
    "SOURCE_PROVIDER_HTTP_JSON",
    "SOURCE_PROVIDER_LOCAL_JSON",
    "SOURCE_PROVIDER_NONE",
    "AiBriefSourceProviderError",
    "AiBriefSourceProviderResult",
    "AiBriefSourceProviderTimeoutError",
    "load_ai_brief_sources",
]
