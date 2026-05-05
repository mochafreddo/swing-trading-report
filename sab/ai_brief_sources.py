from __future__ import annotations

import datetime as dt
import json
from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any

SOURCE_PROVIDER_NONE = "none"
SOURCE_PROVIDER_LOCAL_JSON = "local-json"
SOURCE_FRESHNESS_HOURS = 72
MAX_SOURCES_PER_TICKER = 3


@dataclass(frozen=True)
class AiBriefSourceProviderResult:
    sources_by_ticker: dict[str, list[dict[str, object]]] = field(default_factory=dict)
    source_issues: list[dict[str, object]] = field(default_factory=list)


class AiBriefSourceProviderError(RuntimeError):
    code = "source_provider_failed"


def load_ai_brief_sources(
    *,
    source_provider: str,
    source_report_path: str | None,
    eligible_tickers: set[str],
    now: dt.datetime | None = None,
) -> AiBriefSourceProviderResult:
    if source_provider == SOURCE_PROVIDER_NONE:
        return AiBriefSourceProviderResult()
    if source_provider != SOURCE_PROVIDER_LOCAL_JSON:
        raise AiBriefSourceProviderError(
            f"unsupported source provider {source_provider!r}"
        )
    if source_report_path is None or not source_report_path.strip():
        raise AiBriefSourceProviderError(
            "--source-provider local-json requires --source-report"
        )
    return _load_local_json_source_report(
        source_report_path=source_report_path,
        eligible_tickers=eligible_tickers,
        now=now or dt.datetime.now().astimezone(),
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

    sources_by_ticker: dict[str, list[dict[str, object]]] = {}
    source_issues: list[dict[str, object]] = []
    for idx, raw_row in enumerate(rows):
        if not isinstance(raw_row, Mapping):
            source_issues.append(
                _source_issue(
                    ticker=None,
                    code="local_source_invalid_row",
                    message=f"sources[{idx}] was ignored because it is not an object",
                )
            )
            continue
        ticker = str(raw_row.get("ticker") or "").strip()
        if not ticker:
            source_issues.append(
                _source_issue(
                    ticker=None,
                    code="local_source_invalid_row",
                    message=f"sources[{idx}] was ignored because ticker is required",
                )
            )
            continue
        if ticker not in eligible_tickers:
            source_issues.append(
                _source_issue(
                    ticker=ticker,
                    code="local_source_unknown_ticker",
                    message="local source row ignored because ticker is not eligible",
                )
            )
            continue

        normalized, issue = _normalize_source_row(raw_row, ticker=ticker, now=now)
        if issue is None:
            ticker_sources = sources_by_ticker.setdefault(ticker, [])
            if len(ticker_sources) >= MAX_SOURCES_PER_TICKER:
                source_issues.append(
                    _source_issue(
                        ticker=ticker,
                        code="local_source_cap_exceeded",
                        message=(
                            f"local source row ignored because ticker already has "
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
    row: Mapping[str, Any], *, ticker: str, now: dt.datetime
) -> tuple[dict[str, object], None] | tuple[dict[str, object], dict[str, object]]:
    title = str(row.get("title") or "").strip()
    url = str(row.get("url") or "").strip()
    if not title:
        return {}, _source_issue(
            ticker=ticker,
            code="local_source_invalid_row",
            message="local source row ignored because title is required",
        )
    if not url:
        return {}, _source_issue(
            ticker=ticker,
            code="local_source_invalid_row",
            message="local source row ignored because url is required",
        )
    try:
        published_at = _parse_offset_datetime(row.get("published_at"))
    except ValueError as exc:
        return {}, _source_issue(
            ticker=ticker,
            code="local_source_invalid_row",
            message=f"local source row ignored because {exc}",
        )
    if now.astimezone(dt.UTC) - published_at.astimezone(dt.UTC) > dt.timedelta(
        hours=SOURCE_FRESHNESS_HOURS
    ):
        return {}, _source_issue(
            ticker=ticker,
            code="local_source_stale",
            message=f"local source row ignored because published_at is older than {SOURCE_FRESHNESS_HOURS}h",
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
    "MAX_SOURCES_PER_TICKER",
    "SOURCE_FRESHNESS_HOURS",
    "SOURCE_PROVIDER_LOCAL_JSON",
    "SOURCE_PROVIDER_NONE",
    "AiBriefSourceProviderError",
    "AiBriefSourceProviderResult",
    "load_ai_brief_sources",
]
