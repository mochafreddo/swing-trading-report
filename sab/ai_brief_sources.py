from __future__ import annotations

import datetime as dt
import ipaddress
import json
import math
import os
import socket
import time
from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any
from urllib.parse import urlparse

import requests  # type: ignore[import-untyped]

SOURCE_PROVIDER_NONE = "none"
SOURCE_PROVIDER_LOCAL_JSON = "local-json"
SOURCE_PROVIDER_HTTP_JSON = "http-json"
SOURCE_REPORT_SCHEMA = "sab.ai_brief_sources.v1"
SOURCE_REPORT_TYPE = "ai_brief_sources"
SOURCE_FRESHNESS_HOURS = 72
SOURCE_FUTURE_SKEW_MINUTES = 15
MAX_SOURCES_PER_TICKER = 3
MAX_SOURCE_API_RESPONSE_BYTES = 1_000_000
DEFAULT_SOURCE_TIMEOUT_SECONDS = 10.0
_ALLOWED_SOURCE_URL_SCHEMES = frozenset({"http", "https"})
_ALLOWED_SOURCE_ISSUE_SEVERITIES = frozenset({"INFO", "WARN", "ERROR"})


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
    try:
        url = validate_ai_brief_source_api_url(url)
    except ValueError as exc:
        raise AiBriefSourceProviderError(str(exc)) from exc
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
    api_token = _source_api_token_for_url(url)
    if api_token:
        headers["Authorization"] = f"Bearer {api_token}"

    deadline = time.monotonic() + source_timeout_seconds
    try:
        response = requests.Session().post(
            url,
            headers=headers,
            json=request_payload,
            timeout=source_timeout_seconds,
            stream=True,
            allow_redirects=False,
        )
    except requests.Timeout as exc:
        raise AiBriefSourceProviderTimeoutError("source API request timed out") from exc
    except requests.RequestException as exc:
        raise AiBriefSourceProviderError(f"source API request failed: {exc}") from exc

    if 300 <= response.status_code < 400:
        _close_response(response)
        raise AiBriefSourceProviderError(
            f"source API redirect was not followed (HTTP {response.status_code})"
        )
    if response.status_code >= 400:
        _close_response(response)
        raise AiBriefSourceProviderError(
            f"source API request failed with HTTP {response.status_code}"
        )
    payload = _parse_source_api_response_payload(response, deadline=deadline)
    report_issues = _normalize_source_report_issues(
        payload,
        issue_prefix="http_source",
        issue_subject="http source",
        eligible_tickers=eligible_tickers,
    )
    rows = payload.get("sources")
    if not isinstance(rows, list):
        raise AiBriefSourceProviderError("source API response sources must be a list")
    result = _normalize_source_rows(
        rows=rows,
        eligible_tickers=eligible_tickers,
        now=now,
        issue_prefix="http_source",
        issue_subject="http source",
    )
    return AiBriefSourceProviderResult(
        sources_by_ticker=result.sources_by_ticker,
        source_issues=[*report_issues, *result.source_issues],
    )


def _parse_source_api_response_payload(
    response: Any,
    *,
    deadline: float,
) -> Mapping[str, Any]:
    body = _read_bounded_response_body(response, deadline=deadline)
    try:
        payload = json.loads(body.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise AiBriefSourceProviderError(
            "source API response was not valid JSON"
        ) from exc
    if not isinstance(payload, Mapping):
        raise AiBriefSourceProviderError(
            "source API response must contain a JSON object"
        )
    _validate_source_report_contract(payload, subject="source API response")
    return payload


def _read_bounded_response_body(response: Any, *, deadline: float) -> bytes:
    iter_content = getattr(response, "iter_content", None)
    if callable(iter_content):
        chunks: list[bytes] = []
        total_size = 0
        try:
            for chunk in iter_content(chunk_size=64 * 1024):
                if time.monotonic() > deadline:
                    raise AiBriefSourceProviderTimeoutError(
                        "source API response body timed out"
                    )
                if not chunk:
                    continue
                if isinstance(chunk, str):
                    chunk = chunk.encode("utf-8")
                total_size += len(chunk)
                if total_size > MAX_SOURCE_API_RESPONSE_BYTES:
                    raise AiBriefSourceProviderError(
                        "source API response body is too large "
                        f"({total_size} bytes > "
                        f"{MAX_SOURCE_API_RESPONSE_BYTES} bytes)"
                    )
                chunks.append(bytes(chunk))
        except requests.Timeout as exc:
            raise AiBriefSourceProviderTimeoutError(
                "source API response body timed out"
            ) from exc
        except requests.RequestException as exc:
            raise AiBriefSourceProviderError(
                f"source API response body failed: {exc}"
            ) from exc
        finally:
            _close_response(response)
        return b"".join(chunks)

    try:
        content = getattr(response, "content", None)
        if isinstance(content, bytes | bytearray):
            body = bytes(content)
        else:
            text = getattr(response, "text", None)
            if isinstance(text, str):
                body = text.encode("utf-8")
            else:
                raise AiBriefSourceProviderError(
                    "source API response body is unavailable"
                )
        if len(body) > MAX_SOURCE_API_RESPONSE_BYTES:
            raise AiBriefSourceProviderError(
                "source API response body is too large "
                f"({len(body)} bytes > {MAX_SOURCE_API_RESPONSE_BYTES} bytes)"
            )
        return body
    finally:
        _close_response(response)


def _close_response(response: Any) -> None:
    close = getattr(response, "close", None)
    if callable(close):
        close()


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
    _validate_source_report_contract(payload, subject="source report")
    rows = payload.get("sources")
    if not isinstance(rows, list):
        raise AiBriefSourceProviderError("source report sources must be a list")

    report_issues = _normalize_source_report_issues(
        payload,
        issue_prefix="local_source",
        issue_subject="local source",
        eligible_tickers=eligible_tickers,
    )
    result = _normalize_source_rows(
        rows=rows,
        eligible_tickers=eligible_tickers,
        now=now,
        issue_prefix="local_source",
        issue_subject="local source",
    )
    return AiBriefSourceProviderResult(
        sources_by_ticker=result.sources_by_ticker,
        source_issues=[*report_issues, *result.source_issues],
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
    seen_urls_by_ticker: dict[str, set[str]] = {}
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
            source_url = str(normalized.get("url") or "").strip()
            seen_urls = seen_urls_by_ticker.setdefault(ticker, set())
            if source_url in seen_urls:
                source_issues.append(
                    _source_issue(
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


def _normalize_source_report_issues(
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
                _source_issue(
                    ticker=None,
                    code=f"{issue_prefix}_invalid_issue",
                    message=(
                        f"{issue_subject} {field_name} ignored because it is not a list"
                    ),
                )
            )
            continue
        for idx, raw_issue in enumerate(raw_issues):
            issue = _normalize_source_report_issue(
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


def _validate_source_report_contract(
    payload: Mapping[str, Any],
    *,
    subject: str,
) -> None:
    schema = str(payload.get("schema") or "").strip()
    if schema and schema != SOURCE_REPORT_SCHEMA:
        raise AiBriefSourceProviderError(
            f"{subject} schema must be {SOURCE_REPORT_SCHEMA!r}"
        )
    report_type = str(payload.get("type") or "").strip()
    if report_type and report_type != SOURCE_REPORT_TYPE:
        raise AiBriefSourceProviderError(
            f"{subject} type must be {SOURCE_REPORT_TYPE!r}"
        )


def _normalize_source_report_issue(
    raw_issue: object,
    *,
    field_name: str,
    idx: int,
    issue_prefix: str,
    issue_subject: str,
) -> dict[str, object]:
    if not isinstance(raw_issue, Mapping):
        return _source_issue(
            ticker=None,
            code=f"{issue_prefix}_invalid_issue",
            message=(
                f"{issue_subject} {field_name}[{idx}] ignored because it is "
                "not an object"
            ),
        )
    code = str(raw_issue.get("code") or "").strip()
    message = str(raw_issue.get("message") or "").strip()
    severity = str(raw_issue.get("severity") or "WARN").strip().upper()
    if not code or not message:
        return _source_issue(
            ticker=None,
            code=f"{issue_prefix}_invalid_issue",
            message=(
                f"{issue_subject} {field_name}[{idx}] ignored because code and "
                "message are required"
            ),
        )
    if severity not in _ALLOWED_SOURCE_ISSUE_SEVERITIES:
        return _source_issue(
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
    try:
        url = validate_ai_brief_source_url(url)
    except ValueError as exc:
        return {}, _source_issue(
            ticker=ticker,
            code=f"{issue_prefix}_invalid_row",
            message=f"{issue_subject} row ignored because {exc}",
        )
    try:
        published_at = _parse_offset_datetime(row.get("published_at"))
    except ValueError as exc:
        return {}, _source_issue(
            ticker=ticker,
            code=f"{issue_prefix}_invalid_row",
            message=f"{issue_subject} row ignored because {exc}",
        )
    if is_ai_brief_source_stale(published_at, now=now):
        return {}, _source_issue(
            ticker=ticker,
            code=f"{issue_prefix}_stale",
            message=(
                f"{issue_subject} row ignored because published_at is older than "
                f"{SOURCE_FRESHNESS_HOURS}h"
            ),
        )
    if is_ai_brief_source_future(published_at, now=now):
        return {}, _source_issue(
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


def validate_ai_brief_source_url(value: object, *, field_name: str = "url") -> str:
    text = str(value or "").strip()
    if not text:
        raise ValueError(f"{field_name} is required")
    if any(char.isspace() or ord(char) < 32 or ord(char) == 127 for char in text):
        raise ValueError(f"{field_name} must not contain whitespace or control chars")
    parsed = urlparse(text)
    if parsed.scheme.lower() not in _ALLOWED_SOURCE_URL_SCHEMES:
        raise ValueError(f"{field_name} must use http or https")
    if not parsed.netloc or not parsed.hostname:
        raise ValueError(f"{field_name} must include a hostname")
    if (
        "@" in parsed.netloc
        or parsed.username is not None
        or parsed.password is not None
    ):
        raise ValueError(f"{field_name} must not include userinfo")
    return text


def validate_ai_brief_source_api_url(value: object) -> str:
    text = validate_ai_brief_source_url(value, field_name="source API URL")
    parsed = urlparse(text)
    if parsed.scheme.lower() != "https":
        raise ValueError("source API URL must use https")
    hostname = parsed.hostname or ""
    if _is_blocked_source_api_hostname(hostname):
        raise ValueError("source API URL must not target local or private hosts")
    return text


def _source_api_token_for_url(url: str) -> str:
    api_token = str(os.getenv("AI_BRIEF_SOURCE_API_TOKEN") or "").strip()
    configured_url = str(os.getenv("AI_BRIEF_SOURCE_API_URL") or "").strip()
    if not api_token or not configured_url:
        return ""
    try:
        configured_url = validate_ai_brief_source_api_url(configured_url)
    except ValueError:
        return ""
    return api_token if url == configured_url else ""


def _is_blocked_source_api_hostname(hostname: str) -> bool:
    normalized = hostname.strip().strip("[]").lower().rstrip(".")
    if normalized in {"localhost", "ip6-localhost"} or normalized.endswith(
        ".localhost"
    ):
        return True
    try:
        return _is_blocked_source_api_ip(ipaddress.ip_address(normalized))
    except ValueError:
        pass
    try:
        addrinfos = socket.getaddrinfo(normalized, None, type=socket.SOCK_STREAM)
    except OSError:
        return False
    return any(
        _is_blocked_source_api_ip(ipaddress.ip_address(addrinfo[4][0]))
        for addrinfo in addrinfos
    )


def _is_blocked_source_api_ip(
    address: ipaddress.IPv4Address | ipaddress.IPv6Address,
) -> bool:
    return (
        address.is_loopback
        or address.is_private
        or address.is_link_local
        or address.is_multicast
        or address.is_reserved
        or address.is_unspecified
    )


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
    "MAX_SOURCE_API_RESPONSE_BYTES",
    "SOURCE_FRESHNESS_HOURS",
    "SOURCE_FUTURE_SKEW_MINUTES",
    "SOURCE_PROVIDER_HTTP_JSON",
    "SOURCE_PROVIDER_LOCAL_JSON",
    "SOURCE_PROVIDER_NONE",
    "SOURCE_REPORT_SCHEMA",
    "SOURCE_REPORT_TYPE",
    "AiBriefSourceProviderError",
    "AiBriefSourceProviderResult",
    "AiBriefSourceProviderTimeoutError",
    "is_ai_brief_source_future",
    "is_ai_brief_source_stale",
    "load_ai_brief_sources",
    "validate_ai_brief_source_api_url",
    "validate_ai_brief_source_url",
]
