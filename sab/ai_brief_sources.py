from __future__ import annotations

import datetime as dt
import json
import math
import os
import time
from collections.abc import Iterator, Mapping, Sequence
from contextlib import contextmanager
from dataclasses import dataclass, field
from typing import Any

import requests  # type: ignore[import-untyped]

from . import ai_brief_source_report as source_report
from . import ai_brief_source_url_safety as source_url_safety
from .ai_brief_source_normalizers import (
    normalize_alpha_vantage_news_rows,
    normalize_benzinga_news_rows,
    normalize_finnhub_news_rows,
    normalize_marketaux_news_rows,
    normalize_naver_news_rows,
    normalize_polygon_news_rows,
)
from .tickers import parse_ticker
from .utils.closing import close_quietly

SOURCE_PROVIDER_NONE = "none"
SOURCE_PROVIDER_LOCAL_JSON = "local-json"
SOURCE_PROVIDER_HTTP_JSON = "http-json"
SOURCE_PROVIDER_FINNHUB = "finnhub"
SOURCE_PROVIDER_POLYGON_NEWS = "polygon-news"
SOURCE_PROVIDER_ALPHA_VANTAGE_NEWS = "alpha-vantage-news"
SOURCE_PROVIDER_MARKETAUX_NEWS = "marketaux-news"
SOURCE_PROVIDER_BENZINGA_NEWS = "benzinga-news"
SOURCE_PROVIDER_NAVER_NEWS = "naver-news"
SOURCE_REPORT_SCHEMA = source_report.SOURCE_REPORT_SCHEMA
SOURCE_REPORT_TYPE = source_report.SOURCE_REPORT_TYPE
SOURCE_FRESHNESS_HOURS = source_report.SOURCE_FRESHNESS_HOURS
SOURCE_FUTURE_SKEW_MINUTES = source_report.SOURCE_FUTURE_SKEW_MINUTES
MAX_SOURCES_PER_TICKER = source_report.MAX_SOURCES_PER_TICKER
MAX_SOURCE_API_RESPONSE_BYTES = 1_000_000
DEFAULT_SOURCE_TIMEOUT_SECONDS = 10.0
SOURCE_ROW_DNS_TIMEOUT_SECONDS = source_url_safety.SOURCE_ROW_DNS_TIMEOUT_SECONDS
SOURCE_DNS_RESOLVER_WORKERS = source_url_safety.SOURCE_DNS_RESOLVER_WORKERS
SOURCE_RESPONSE_READ_TIMEOUT_SECONDS = 1.0
FINNHUB_COMPANY_NEWS_URL = "https://api.finnhub.io/api/v1/company-news"
POLYGON_NEWS_URL = "https://api.polygon.io/v2/reference/news"
POLYGON_NEWS_LIMIT = 10
ALPHA_VANTAGE_NEWS_URL = "https://www.alphavantage.co/query"
ALPHA_VANTAGE_NEWS_LIMIT = 10
MARKETAUX_NEWS_URL = "https://api.marketaux.com/v1/news/all"
MARKETAUX_NEWS_LIMIT = 10
BENZINGA_NEWS_URL = "https://api.benzinga.com/api/v2/news"
BENZINGA_NEWS_LIMIT = 10
NAVER_NEWS_SEARCH_URL = "https://openapi.naver.com/v1/search/news.json"
NAVER_NEWS_DISPLAY_COUNT = 10
SOURCE_DNS_PIN_LOCK = source_url_safety.SOURCE_DNS_PIN_LOCK
_SOURCE_DNS_RESOLVER_SLOTS = source_url_safety._SOURCE_DNS_RESOLVER_SLOTS
socket = source_url_safety.socket
threading = source_url_safety.threading
type _JsonValue = (
    None | bool | int | float | str | Sequence[_JsonValue] | Mapping[str, _JsonValue]
)
type _SourceQueryParams = Mapping[str, str | int]
_ValidatedSourceApiUrl = source_url_safety.ValidatedSourceApiUrl


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
    ticker_names: Mapping[str, str] | None = None,
    now: dt.datetime | None = None,
) -> AiBriefSourceProviderResult:
    if source_provider == SOURCE_PROVIDER_NONE:
        return AiBriefSourceProviderResult()
    resolved_now = now or dt.datetime.now().astimezone()
    resolved_timeout = (
        DEFAULT_SOURCE_TIMEOUT_SECONDS
        if source_timeout_seconds is None
        else source_timeout_seconds
    )
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
            source_timeout_seconds=resolved_timeout,
            eligible_tickers=eligible_tickers,
            now=resolved_now,
        )
    if source_provider == SOURCE_PROVIDER_FINNHUB:
        return _load_finnhub_source_report(
            source_timeout_seconds=resolved_timeout,
            eligible_tickers=eligible_tickers,
            now=resolved_now,
        )
    if source_provider == SOURCE_PROVIDER_POLYGON_NEWS:
        return _load_polygon_news_source_report(
            source_timeout_seconds=resolved_timeout,
            eligible_tickers=eligible_tickers,
            now=resolved_now,
        )
    if source_provider == SOURCE_PROVIDER_ALPHA_VANTAGE_NEWS:
        return _load_alpha_vantage_news_source_report(
            source_timeout_seconds=resolved_timeout,
            eligible_tickers=eligible_tickers,
            now=resolved_now,
        )
    if source_provider == SOURCE_PROVIDER_MARKETAUX_NEWS:
        return _load_marketaux_news_source_report(
            source_timeout_seconds=resolved_timeout,
            eligible_tickers=eligible_tickers,
            now=resolved_now,
        )
    if source_provider == SOURCE_PROVIDER_BENZINGA_NEWS:
        return _load_benzinga_news_source_report(
            source_timeout_seconds=resolved_timeout,
            eligible_tickers=eligible_tickers,
            now=resolved_now,
        )
    if source_provider == SOURCE_PROVIDER_NAVER_NEWS:
        return _load_naver_news_source_report(
            source_timeout_seconds=resolved_timeout,
            eligible_tickers=eligible_tickers,
            ticker_names=ticker_names or {},
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
    if not math.isfinite(source_timeout_seconds) or source_timeout_seconds <= 0:
        raise AiBriefSourceProviderError("source timeout seconds must be positive")
    deadline = time.monotonic() + source_timeout_seconds
    url = str(source_api_url or "").strip()
    if not url:
        raise AiBriefSourceProviderError(
            "--source-provider http-json requires --source-api-url or "
            "AI_BRIEF_SOURCE_API_URL"
        )
    try:
        validated_source_api_url = _validate_source_api_request_url(
            url,
            deadline=deadline,
        )
    except ValueError as exc:
        raise AiBriefSourceProviderError(str(exc)) from exc
    url = validated_source_api_url.url
    request_payload: dict[str, _JsonValue] = {
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

    session = requests.Session()
    session.trust_env = False
    try:
        try:
            with _pin_source_api_dns(
                validated_source_api_url.hostnames,
                validated_source_api_url.addrinfos,
                deadline=deadline,
            ):
                response = session.post(
                    url,
                    headers=headers,
                    json=request_payload,
                    timeout=_source_request_timeout(deadline),
                    stream=True,
                    allow_redirects=False,
                )
        except requests.Timeout:
            raise AiBriefSourceProviderTimeoutError(
                "source API request timed out"
            ) from None
        except requests.RequestException as exc:
            raise AiBriefSourceProviderError(
                f"source API request failed: {_exception_type_name(exc)}"
            ) from None

        _raise_for_source_response_status(response, subject="source API")
        payload = _parse_source_api_response_payload(response, deadline=deadline)
        report_issues = _normalize_source_report_issues(
            payload,
            issue_prefix="http_source",
            issue_subject="http source",
            eligible_tickers=eligible_tickers,
        )
        rows = payload.get("sources")
        if not isinstance(rows, list):
            raise AiBriefSourceProviderError(
                "source API response sources must be a list"
            )
        result = _normalize_source_rows(
            rows=rows,
            eligible_tickers=eligible_tickers,
            now=now,
            issue_prefix="http_source",
            issue_subject="http source",
            source_url_deadline=deadline,
            resolve_source_url_hostnames=True,
        )
        return AiBriefSourceProviderResult(
            sources_by_ticker=result.sources_by_ticker,
            source_issues=[*report_issues, *result.source_issues],
        )
    finally:
        close_quietly(session)


def _parse_source_api_response_payload(
    response: Any,
    *,
    deadline: float,
) -> Mapping[str, Any]:
    payload = _decode_json_response(response, deadline=deadline, subject="source API")
    if not isinstance(payload, Mapping):
        raise AiBriefSourceProviderError(
            "source API response must contain a JSON object"
        )
    _validate_source_report_contract(payload, subject="source API response")
    return payload


def _raise_for_source_response_status(response: Any, *, subject: str) -> None:
    """Reject unfollowed redirects and HTTP error responses, closing the body."""
    status_code = response.status_code
    if 300 <= status_code < 400:
        close_quietly(response)
        raise AiBriefSourceProviderError(
            f"{subject} redirect was not followed (HTTP {status_code})"
        )
    if status_code >= 400:
        close_quietly(response)
        raise AiBriefSourceProviderError(
            f"{subject} request failed with HTTP {status_code}"
        )


def _get_vendor_source_response(
    *,
    session: requests.Session,
    validated_source_api_url: _ValidatedSourceApiUrl,
    params: _SourceQueryParams,
    headers: Mapping[str, str],
    deadline: float,
    source_subject: str,
) -> Any:
    try:
        with _pin_source_api_dns(
            validated_source_api_url.hostnames,
            validated_source_api_url.addrinfos,
            deadline=deadline,
        ):
            response = session.get(
                validated_source_api_url.url,
                params=params,
                headers=headers,
                timeout=_source_request_timeout(deadline),
                stream=True,
                allow_redirects=False,
            )
    except requests.Timeout:
        raise AiBriefSourceProviderTimeoutError(
            f"{source_subject} request timed out"
        ) from None
    except requests.RequestException as exc:
        raise AiBriefSourceProviderError(
            f"{source_subject} request failed: {_exception_type_name(exc)}"
        ) from None

    _raise_for_source_response_status(response, subject=source_subject)
    return response


def _decode_json_response(response: Any, *, deadline: float, subject: str) -> Any:
    """Read the bounded body and decode it as JSON, or raise a provider error."""
    body = _read_bounded_response_body(response, deadline=deadline)
    try:
        return json.loads(body.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise AiBriefSourceProviderError(
            f"{subject} response was not valid JSON"
        ) from exc


def _expect_json_array(payload: Any, *, subject: str) -> list[object]:
    if not isinstance(payload, list):
        raise AiBriefSourceProviderError(
            f"{subject} response must contain a JSON array"
        )
    return payload


def _extract_list_field(payload: Any, *, key: str, subject: str) -> list[object]:
    if not isinstance(payload, Mapping):
        raise AiBriefSourceProviderError(
            f"{subject} response must contain a JSON object"
        )
    field_value = payload.get(key)
    if not isinstance(field_value, list):
        raise AiBriefSourceProviderError(f"{subject} response {key} must be a list")
    return field_value


def _load_finnhub_source_report(
    *,
    source_timeout_seconds: float,
    eligible_tickers: set[str],
    now: dt.datetime,
) -> AiBriefSourceProviderResult:
    if not math.isfinite(source_timeout_seconds) or source_timeout_seconds <= 0:
        raise AiBriefSourceProviderError("source timeout seconds must be positive")
    api_key = str(os.getenv("FINNHUB_API_KEY") or "").strip()
    if not api_key:
        raise AiBriefSourceProviderError(
            "--source-provider finnhub requires FINNHUB_API_KEY"
        )

    deadline, validated_source_api_url = _create_vendor_deadline_and_url(
        source_timeout_seconds=source_timeout_seconds,
        api_url=FINNHUB_COMPANY_NEWS_URL,
    )

    now_utc = now.astimezone(dt.UTC)
    from_date = (now_utc - dt.timedelta(hours=SOURCE_FRESHNESS_HOURS)).date()
    to_date = now_utc.date()
    headers = {"Accept": "application/json"}
    source_rows: list[object] = []
    source_issues: list[dict[str, object]] = []

    session = requests.Session()
    session.trust_env = False
    try:
        for ticker in sorted(eligible_tickers):
            parsed = parse_ticker(ticker)
            if parsed.market != "US":
                source_issues.append(
                    _source_issue(
                        ticker=ticker,
                        code="finnhub_source_unsupported_market",
                        message="Finnhub source provider supports US tickers only",
                    )
                )
                continue

            params = {
                "symbol": parsed.symbol,
                "from": from_date.isoformat(),
                "to": to_date.isoformat(),
                "token": api_key,
            }
            response = _get_vendor_source_response(
                session=session,
                validated_source_api_url=validated_source_api_url,
                params=params,
                headers=headers,
                deadline=deadline,
                source_subject="Finnhub source",
            )
            payload = _parse_finnhub_response_payload(response, deadline=deadline)
            source_rows.extend(normalize_finnhub_news_rows(ticker, payload))

        normalized = _normalize_source_rows(
            rows=source_rows,
            eligible_tickers=eligible_tickers,
            now=now,
            issue_prefix="finnhub_source",
            issue_subject="Finnhub source",
            source_url_deadline=deadline,
            resolve_source_url_hostnames=True,
        )
        return AiBriefSourceProviderResult(
            sources_by_ticker=normalized.sources_by_ticker,
            source_issues=[*source_issues, *normalized.source_issues],
        )
    finally:
        close_quietly(session)


def _parse_finnhub_response_payload(response: Any, *, deadline: float) -> list[object]:
    payload = _decode_json_response(
        response, deadline=deadline, subject="Finnhub source"
    )
    return _expect_json_array(payload, subject="Finnhub source")


def _load_polygon_news_source_report(
    *,
    source_timeout_seconds: float,
    eligible_tickers: set[str],
    now: dt.datetime,
) -> AiBriefSourceProviderResult:
    if not math.isfinite(source_timeout_seconds) or source_timeout_seconds <= 0:
        raise AiBriefSourceProviderError("source timeout seconds must be positive")
    api_key = str(os.getenv("POLYGON_API_KEY") or "").strip()
    if not api_key:
        raise AiBriefSourceProviderError(
            "--source-provider polygon-news requires POLYGON_API_KEY"
        )

    deadline, validated_source_api_url = _create_vendor_deadline_and_url(
        source_timeout_seconds=source_timeout_seconds,
        api_url=POLYGON_NEWS_URL,
    )

    headers = {
        "Accept": "application/json",
        "Authorization": f"Bearer {api_key}",
    }
    source_rows: list[object] = []
    source_issues: list[dict[str, object]] = []

    session = requests.Session()
    session.trust_env = False
    try:
        for ticker in sorted(eligible_tickers):
            parsed = parse_ticker(ticker)
            if parsed.market != "US":
                source_issues.append(
                    _source_issue(
                        ticker=ticker,
                        code="polygon_news_source_unsupported_market",
                        message=(
                            "Polygon News source provider supports US tickers only"
                        ),
                    )
                )
                continue

            params: dict[str, str | int] = {
                "ticker": parsed.symbol,
                "limit": POLYGON_NEWS_LIMIT,
                "order": "desc",
                "sort": "published_utc",
            }
            response = _get_vendor_source_response(
                session=session,
                validated_source_api_url=validated_source_api_url,
                params=params,
                headers=headers,
                deadline=deadline,
                source_subject="Polygon News source",
            )
            payload = _parse_polygon_news_response_payload(response, deadline=deadline)
            source_rows.extend(normalize_polygon_news_rows(ticker, payload))

        normalized = _normalize_source_rows(
            rows=source_rows,
            eligible_tickers=eligible_tickers,
            now=now,
            issue_prefix="polygon_news_source",
            issue_subject="Polygon News source",
            source_url_deadline=deadline,
            resolve_source_url_hostnames=True,
        )
        return AiBriefSourceProviderResult(
            sources_by_ticker=normalized.sources_by_ticker,
            source_issues=[*source_issues, *normalized.source_issues],
        )
    finally:
        close_quietly(session)


def _parse_polygon_news_response_payload(
    response: Any,
    *,
    deadline: float,
) -> list[object]:
    payload = _decode_json_response(
        response, deadline=deadline, subject="Polygon News source"
    )
    return _extract_list_field(payload, key="results", subject="Polygon News source")


def _load_alpha_vantage_news_source_report(
    *,
    source_timeout_seconds: float,
    eligible_tickers: set[str],
    now: dt.datetime,
) -> AiBriefSourceProviderResult:
    if not math.isfinite(source_timeout_seconds) or source_timeout_seconds <= 0:
        raise AiBriefSourceProviderError("source timeout seconds must be positive")
    api_key = str(os.getenv("ALPHA_VANTAGE_API_KEY") or "").strip()
    if not api_key:
        raise AiBriefSourceProviderError(
            "--source-provider alpha-vantage-news requires ALPHA_VANTAGE_API_KEY"
        )

    deadline, validated_source_api_url = _create_vendor_deadline_and_url(
        source_timeout_seconds=source_timeout_seconds,
        api_url=ALPHA_VANTAGE_NEWS_URL,
    )

    time_from = now.astimezone(dt.UTC) - dt.timedelta(hours=SOURCE_FRESHNESS_HOURS)
    time_from_text = time_from.strftime("%Y%m%dT%H%M")
    headers = {"Accept": "application/json"}
    source_rows: list[object] = []
    source_issues: list[dict[str, object]] = []

    session = requests.Session()
    session.trust_env = False
    try:
        for ticker in sorted(eligible_tickers):
            parsed = parse_ticker(ticker)
            if parsed.market != "US":
                source_issues.append(
                    _source_issue(
                        ticker=ticker,
                        code="alpha_vantage_news_source_unsupported_market",
                        message=(
                            "Alpha Vantage News source provider supports US "
                            "tickers only"
                        ),
                    )
                )
                continue

            params: dict[str, str | int] = {
                "function": "NEWS_SENTIMENT",
                "tickers": parsed.symbol,
                "time_from": time_from_text,
                "sort": "LATEST",
                "limit": ALPHA_VANTAGE_NEWS_LIMIT,
                "apikey": api_key,
            }
            response = _get_vendor_source_response(
                session=session,
                validated_source_api_url=validated_source_api_url,
                params=params,
                headers=headers,
                deadline=deadline,
                source_subject="Alpha Vantage News source",
            )
            payload = _parse_alpha_vantage_news_response_payload(
                response,
                deadline=deadline,
            )
            source_rows.extend(normalize_alpha_vantage_news_rows(ticker, payload))

        normalized = _normalize_source_rows(
            rows=source_rows,
            eligible_tickers=eligible_tickers,
            now=now,
            issue_prefix="alpha_vantage_news_source",
            issue_subject="Alpha Vantage News source",
            source_url_deadline=deadline,
            resolve_source_url_hostnames=True,
        )
        return AiBriefSourceProviderResult(
            sources_by_ticker=normalized.sources_by_ticker,
            source_issues=[*source_issues, *normalized.source_issues],
        )
    finally:
        close_quietly(session)


def _parse_alpha_vantage_news_response_payload(
    response: Any,
    *,
    deadline: float,
) -> list[object]:
    payload = _decode_json_response(
        response, deadline=deadline, subject="Alpha Vantage News source"
    )
    return _extract_list_field(payload, key="feed", subject="Alpha Vantage News source")


def _load_marketaux_news_source_report(
    *,
    source_timeout_seconds: float,
    eligible_tickers: set[str],
    now: dt.datetime,
) -> AiBriefSourceProviderResult:
    if not math.isfinite(source_timeout_seconds) or source_timeout_seconds <= 0:
        raise AiBriefSourceProviderError("source timeout seconds must be positive")
    api_token = str(os.getenv("MARKETAUX_API_TOKEN") or "").strip()
    if not api_token:
        raise AiBriefSourceProviderError(
            "--source-provider marketaux-news requires MARKETAUX_API_TOKEN"
        )

    deadline, validated_source_api_url = _create_vendor_deadline_and_url(
        source_timeout_seconds=source_timeout_seconds,
        api_url=MARKETAUX_NEWS_URL,
    )

    published_after = (
        now.astimezone(dt.UTC) - dt.timedelta(hours=SOURCE_FRESHNESS_HOURS)
    ).strftime("%Y-%m-%dT%H:%M:%S")
    headers = {"Accept": "application/json"}
    source_rows: list[object] = []
    source_issues: list[dict[str, object]] = []

    session = requests.Session()
    session.trust_env = False
    try:
        for ticker in sorted(eligible_tickers):
            parsed = parse_ticker(ticker)
            if parsed.market != "US":
                source_issues.append(
                    _source_issue(
                        ticker=ticker,
                        code="marketaux_news_source_unsupported_market",
                        message=(
                            "Marketaux News source provider supports US tickers only"
                        ),
                    )
                )
                continue

            params: dict[str, str | int] = {
                "api_token": api_token,
                "symbols": parsed.symbol,
                "countries": "us",
                "language": "en",
                "filter_entities": "true",
                "must_have_entities": "true",
                "published_after": published_after,
                "limit": MARKETAUX_NEWS_LIMIT,
            }
            response = _get_vendor_source_response(
                session=session,
                validated_source_api_url=validated_source_api_url,
                params=params,
                headers=headers,
                deadline=deadline,
                source_subject="Marketaux News source",
            )
            payload = _parse_marketaux_news_response_payload(
                response,
                deadline=deadline,
            )
            source_rows.extend(normalize_marketaux_news_rows(ticker, payload))

        normalized = _normalize_source_rows(
            rows=source_rows,
            eligible_tickers=eligible_tickers,
            now=now,
            issue_prefix="marketaux_news_source",
            issue_subject="Marketaux News source",
            source_url_deadline=deadline,
            resolve_source_url_hostnames=True,
        )
        return AiBriefSourceProviderResult(
            sources_by_ticker=normalized.sources_by_ticker,
            source_issues=[*source_issues, *normalized.source_issues],
        )
    finally:
        close_quietly(session)


def _parse_marketaux_news_response_payload(
    response: Any,
    *,
    deadline: float,
) -> list[object]:
    payload = _decode_json_response(
        response, deadline=deadline, subject="Marketaux News source"
    )
    return _extract_list_field(payload, key="data", subject="Marketaux News source")


def _load_benzinga_news_source_report(
    *,
    source_timeout_seconds: float,
    eligible_tickers: set[str],
    now: dt.datetime,
) -> AiBriefSourceProviderResult:
    if not math.isfinite(source_timeout_seconds) or source_timeout_seconds <= 0:
        raise AiBriefSourceProviderError("source timeout seconds must be positive")
    api_token = str(os.getenv("BENZINGA_API_TOKEN") or "").strip()
    if not api_token:
        raise AiBriefSourceProviderError(
            "--source-provider benzinga-news requires BENZINGA_API_TOKEN"
        )

    deadline, validated_source_api_url = _create_vendor_deadline_and_url(
        source_timeout_seconds=source_timeout_seconds,
        api_url=BENZINGA_NEWS_URL,
    )

    published_since = int(
        (
            now.astimezone(dt.UTC) - dt.timedelta(hours=SOURCE_FRESHNESS_HOURS)
        ).timestamp()
    )
    headers = {"Accept": "application/json"}
    source_rows: list[object] = []
    source_issues: list[dict[str, object]] = []

    session = requests.Session()
    session.trust_env = False
    try:
        for ticker in sorted(eligible_tickers):
            parsed = parse_ticker(ticker)
            if parsed.market != "US":
                source_issues.append(
                    _source_issue(
                        ticker=ticker,
                        code="benzinga_news_source_unsupported_market",
                        message=(
                            "Benzinga News source provider supports US tickers only"
                        ),
                    )
                )
                continue

            params: dict[str, str | int] = {
                "token": api_token,
                "tickers": parsed.symbol,
                "pageSize": BENZINGA_NEWS_LIMIT,
                "displayOutput": "headline",
                "sort": "created:desc",
                "publishedSince": published_since,
            }
            response = _get_vendor_source_response(
                session=session,
                validated_source_api_url=validated_source_api_url,
                params=params,
                headers=headers,
                deadline=deadline,
                source_subject="Benzinga News source",
            )
            payload = _parse_benzinga_news_response_payload(
                response,
                deadline=deadline,
            )
            source_rows.extend(normalize_benzinga_news_rows(ticker, payload))

        normalized = _normalize_source_rows(
            rows=source_rows,
            eligible_tickers=eligible_tickers,
            now=now,
            issue_prefix="benzinga_news_source",
            issue_subject="Benzinga News source",
            source_url_deadline=deadline,
            resolve_source_url_hostnames=True,
        )
        return AiBriefSourceProviderResult(
            sources_by_ticker=normalized.sources_by_ticker,
            source_issues=[*source_issues, *normalized.source_issues],
        )
    finally:
        close_quietly(session)


def _parse_benzinga_news_response_payload(
    response: Any,
    *,
    deadline: float,
) -> list[object]:
    payload = _decode_json_response(
        response, deadline=deadline, subject="Benzinga News source"
    )
    return _expect_json_array(payload, subject="Benzinga News source")


def _load_naver_news_source_report(
    *,
    source_timeout_seconds: float,
    eligible_tickers: set[str],
    ticker_names: Mapping[str, str],
    now: dt.datetime,
) -> AiBriefSourceProviderResult:
    if not math.isfinite(source_timeout_seconds) or source_timeout_seconds <= 0:
        raise AiBriefSourceProviderError("source timeout seconds must be positive")
    client_id = str(os.getenv("NAVER_CLIENT_ID") or "").strip()
    client_secret = str(os.getenv("NAVER_CLIENT_SECRET") or "").strip()
    if not client_id or not client_secret:
        raise AiBriefSourceProviderError(
            "--source-provider naver-news requires NAVER_CLIENT_ID and "
            "NAVER_CLIENT_SECRET"
        )

    deadline, validated_source_api_url = _create_vendor_deadline_and_url(
        source_timeout_seconds=source_timeout_seconds,
        api_url=NAVER_NEWS_SEARCH_URL,
    )

    headers = {
        "Accept": "application/json",
        "X-Naver-Client-Id": client_id,
        "X-Naver-Client-Secret": client_secret,
    }
    source_rows: list[object] = []
    source_issues: list[dict[str, object]] = []

    session = requests.Session()
    session.trust_env = False
    try:
        for ticker in sorted(eligible_tickers):
            parsed = parse_ticker(ticker)
            if parsed.market != "KR":
                source_issues.append(
                    _source_issue(
                        ticker=ticker,
                        code="naver_news_source_unsupported_market",
                        message="Naver News source provider supports KR tickers only",
                    )
                )
                continue

            params: dict[str, str | int] = {
                "query": _naver_news_query_for_ticker(
                    ticker,
                    ticker_code=parsed.symbol,
                    ticker_names=ticker_names,
                ),
                "display": NAVER_NEWS_DISPLAY_COUNT,
                "start": 1,
                "sort": "date",
            }
            response = _get_vendor_source_response(
                session=session,
                validated_source_api_url=validated_source_api_url,
                params=params,
                headers=headers,
                deadline=deadline,
                source_subject="Naver News source",
            )
            payload = _parse_naver_news_response_payload(response, deadline=deadline)
            source_rows.extend(normalize_naver_news_rows(ticker, payload))

        normalized = _normalize_source_rows(
            rows=source_rows,
            eligible_tickers=eligible_tickers,
            now=now,
            issue_prefix="naver_news_source",
            issue_subject="Naver News source",
            source_url_deadline=deadline,
            resolve_source_url_hostnames=True,
        )
        return AiBriefSourceProviderResult(
            sources_by_ticker=normalized.sources_by_ticker,
            source_issues=[*source_issues, *normalized.source_issues],
        )
    finally:
        close_quietly(session)


def _naver_news_query_for_ticker(
    ticker: str,
    *,
    ticker_code: str,
    ticker_names: Mapping[str, str],
) -> str:
    name = str(ticker_names.get(ticker) or "").strip()
    return name or ticker_code


def _parse_naver_news_response_payload(
    response: Any,
    *,
    deadline: float,
) -> list[object]:
    payload = _decode_json_response(
        response, deadline=deadline, subject="Naver News source"
    )
    return _extract_list_field(payload, key="items", subject="Naver News source")


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
        except requests.Timeout:
            raise AiBriefSourceProviderTimeoutError(
                "source API response body timed out"
            ) from None
        except requests.RequestException as exc:
            raise AiBriefSourceProviderError(
                f"source API response body failed: {_exception_type_name(exc)}"
            ) from None
        finally:
            close_quietly(response)
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
        close_quietly(response)


def _remaining_source_timeout(deadline: float) -> float:
    remaining = deadline - time.monotonic()
    if remaining <= 0:
        raise AiBriefSourceProviderTimeoutError("source API request timed out")
    return remaining


def _source_request_timeout(deadline: float) -> tuple[float, float]:
    remaining = _remaining_source_timeout(deadline)
    return remaining, min(remaining, SOURCE_RESPONSE_READ_TIMEOUT_SECONDS)


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
    source_url_deadline: float | None = None,
    resolve_source_url_hostnames: bool = False,
) -> AiBriefSourceProviderResult:
    result = source_report.normalize_source_rows(
        rows=rows,
        eligible_tickers=eligible_tickers,
        now=now,
        issue_prefix=issue_prefix,
        issue_subject=issue_subject,
        source_url_deadline=source_url_deadline,
        resolve_source_url_hostnames=resolve_source_url_hostnames,
        url_validator=_validate_source_row_url,
    )
    return AiBriefSourceProviderResult(
        sources_by_ticker=result.sources_by_ticker,
        source_issues=result.source_issues,
    )


def _normalize_source_report_issues(
    payload: Mapping[str, Any],
    *,
    issue_prefix: str,
    issue_subject: str,
    eligible_tickers: set[str],
) -> list[dict[str, object]]:
    return source_report.normalize_source_report_issues(
        payload,
        issue_prefix=issue_prefix,
        issue_subject=issue_subject,
        eligible_tickers=eligible_tickers,
    )


def _validate_source_report_contract(
    payload: Mapping[str, Any],
    *,
    subject: str,
) -> None:
    try:
        source_report.validate_source_report_contract(payload, subject=subject)
    except ValueError as exc:
        raise AiBriefSourceProviderError(str(exc)) from exc


def validate_ai_brief_source_url(value: object, *, field_name: str = "url") -> str:
    return source_url_safety.validate_ai_brief_source_url(
        value,
        field_name=field_name,
    )


def validate_ai_brief_source_api_url(value: object) -> str:
    return _validate_source_api_request_url(value, deadline=None).url


def _validate_source_row_url(
    value: object,
    *,
    field_name: str = "url",
    deadline: float | None = None,
    resolve_hostname: bool = False,
) -> str:
    try:
        return source_url_safety.validate_source_row_url(
            value,
            field_name=field_name,
            deadline=deadline,
            resolve_hostname=resolve_hostname,
            dns_lock=SOURCE_DNS_PIN_LOCK,
            resolver_slots=_SOURCE_DNS_RESOLVER_SLOTS,
        )
    except source_url_safety.AiBriefSourceUrlTimeoutError as exc:
        raise AiBriefSourceProviderTimeoutError(str(exc)) from exc


def _validate_source_api_request_url(
    value: object,
    *,
    deadline: float | None,
) -> _ValidatedSourceApiUrl:
    try:
        return source_url_safety.validate_source_api_request_url(
            value,
            deadline=deadline,
            dns_lock=SOURCE_DNS_PIN_LOCK,
            resolver_slots=_SOURCE_DNS_RESOLVER_SLOTS,
        )
    except source_url_safety.AiBriefSourceUrlTimeoutError as exc:
        raise AiBriefSourceProviderTimeoutError(str(exc)) from exc


def _create_vendor_deadline_and_url(
    *,
    source_timeout_seconds: float,
    api_url: str,
) -> tuple[float, _ValidatedSourceApiUrl]:
    deadline = time.monotonic() + source_timeout_seconds
    try:
        validated_source_api_url = _validate_source_api_request_url(
            api_url,
            deadline=deadline,
        )
    except ValueError as exc:
        raise AiBriefSourceProviderError(str(exc)) from exc
    return deadline, validated_source_api_url


def _source_api_token_for_url(url: str) -> str:
    api_token = str(os.getenv("AI_BRIEF_SOURCE_API_TOKEN") or "").strip()
    if not api_token:
        return ""
    for env_key in (
        "AI_BRIEF_SOURCE_API_URL",
        "AI_BRIEF_SOURCE_API_URL_KR",
        "AI_BRIEF_SOURCE_API_URL_US",
    ):
        configured_url = str(os.getenv(env_key) or "").strip()
        if configured_url and url == configured_url:
            return api_token
    return ""


def _getaddrinfo_with_timeout(
    hostname: str,
    port: int,
    *,
    timeout: float,
) -> list[Any]:
    return source_url_safety.getaddrinfo_with_timeout(
        hostname,
        port,
        timeout=timeout,
        resolver_slots=_SOURCE_DNS_RESOLVER_SLOTS,
    )


@contextmanager
def _pin_source_api_dns(
    hostnames: tuple[str, ...],
    addrinfos: tuple[Any, ...],
    *,
    deadline: float | None = None,
) -> Iterator[None]:
    with source_url_safety.pin_source_api_dns(
        hostnames,
        addrinfos,
        lock=SOURCE_DNS_PIN_LOCK,
        deadline=deadline,
        remaining_timeout=_remaining_source_timeout,
        timeout_error=lambda: AiBriefSourceProviderTimeoutError(
            "source API DNS pin lock timed out"
        ),
        socket_module=socket,
    ):
        yield


def _exception_type_name(exc: BaseException) -> str:
    return type(exc).__name__


def is_ai_brief_source_stale(
    published_at: dt.datetime,
    *,
    now: dt.datetime,
    freshness_hours: float = SOURCE_FRESHNESS_HOURS,
) -> bool:
    return source_report.is_ai_brief_source_stale(
        published_at,
        now=now,
        freshness_hours=freshness_hours,
    )


def is_ai_brief_source_future(
    published_at: dt.datetime,
    *,
    now: dt.datetime,
) -> bool:
    return source_report.is_ai_brief_source_future(published_at, now=now)


def _source_issue(*, ticker: str | None, code: str, message: str) -> dict[str, object]:
    return source_report.source_issue(ticker=ticker, code=code, message=message)


__all__ = [
    "DEFAULT_SOURCE_TIMEOUT_SECONDS",
    "MAX_SOURCES_PER_TICKER",
    "MAX_SOURCE_API_RESPONSE_BYTES",
    "SOURCE_FRESHNESS_HOURS",
    "SOURCE_FUTURE_SKEW_MINUTES",
    "SOURCE_PROVIDER_ALPHA_VANTAGE_NEWS",
    "SOURCE_PROVIDER_BENZINGA_NEWS",
    "SOURCE_PROVIDER_FINNHUB",
    "SOURCE_PROVIDER_HTTP_JSON",
    "SOURCE_PROVIDER_LOCAL_JSON",
    "SOURCE_PROVIDER_MARKETAUX_NEWS",
    "SOURCE_PROVIDER_NAVER_NEWS",
    "SOURCE_PROVIDER_NONE",
    "SOURCE_PROVIDER_POLYGON_NEWS",
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
