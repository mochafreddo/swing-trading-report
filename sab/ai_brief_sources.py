from __future__ import annotations

import datetime as dt
import email.utils
import html
import json
import math
import os
import re
import socket
import threading
import time
from collections.abc import Iterator, Mapping, Sequence
from contextlib import contextmanager
from dataclasses import dataclass, field
from typing import Any
from urllib.parse import urlparse

import requests  # type: ignore[import-untyped]

from . import ai_brief_url_safety as url_safety
from .ai_brief_eval_common import parse_iso_offset_datetime
from .tickers import parse_ticker

SOURCE_PROVIDER_NONE = "none"
SOURCE_PROVIDER_LOCAL_JSON = "local-json"
SOURCE_PROVIDER_HTTP_JSON = "http-json"
SOURCE_PROVIDER_FINNHUB = "finnhub"
SOURCE_PROVIDER_POLYGON_NEWS = "polygon-news"
SOURCE_PROVIDER_ALPHA_VANTAGE_NEWS = "alpha-vantage-news"
SOURCE_PROVIDER_MARKETAUX_NEWS = "marketaux-news"
SOURCE_PROVIDER_BENZINGA_NEWS = "benzinga-news"
SOURCE_PROVIDER_NAVER_NEWS = "naver-news"
SOURCE_REPORT_SCHEMA = "sab.ai_brief_sources.v1"
SOURCE_REPORT_TYPE = "ai_brief_sources"
SOURCE_FRESHNESS_HOURS = 72
SOURCE_FUTURE_SKEW_MINUTES = 15
MAX_SOURCES_PER_TICKER = 3
MAX_SOURCE_API_RESPONSE_BYTES = 1_000_000
DEFAULT_SOURCE_TIMEOUT_SECONDS = 10.0
SOURCE_ROW_DNS_TIMEOUT_SECONDS = 1.0
SOURCE_DNS_RESOLVER_WORKERS = 4
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
_ALLOWED_SOURCE_ISSUE_SEVERITIES = frozenset({"INFO", "WARN", "ERROR"})
SOURCE_DNS_PIN_LOCK = threading.RLock()
_SOURCE_DNS_RESOLVER_SLOTS = threading.BoundedSemaphore(SOURCE_DNS_RESOLVER_WORKERS)
_HTML_TAG_RE = re.compile(r"<[^>]*>")
type _JsonValue = (
    None | bool | int | float | str | Sequence[_JsonValue] | Mapping[str, _JsonValue]
)
type _SourceQueryParams = Mapping[str, str | int]


@dataclass(frozen=True)
class _ValidatedSourceApiUrl:
    url: str
    hostnames: tuple[str, ...]
    addrinfos: tuple[Any, ...]


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
        _close_session(session)


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

    if 300 <= response.status_code < 400:
        _close_response(response)
        raise AiBriefSourceProviderError(
            f"{source_subject} redirect was not followed (HTTP {response.status_code})"
        )
    if response.status_code >= 400:
        _close_response(response)
        raise AiBriefSourceProviderError(
            f"{source_subject} request failed with HTTP {response.status_code}"
        )
    return response


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

    deadline = time.monotonic() + source_timeout_seconds
    try:
        validated_source_api_url = _validate_source_api_request_url(
            FINNHUB_COMPANY_NEWS_URL,
            deadline=deadline,
        )
    except ValueError as exc:
        raise AiBriefSourceProviderError(str(exc)) from exc

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
            source_rows.extend(_normalize_finnhub_news_rows(ticker, payload))

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
        _close_session(session)


def _parse_finnhub_response_payload(response: Any, *, deadline: float) -> list[object]:
    body = _read_bounded_response_body(response, deadline=deadline)
    try:
        payload = json.loads(body.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise AiBriefSourceProviderError(
            "Finnhub source response was not valid JSON"
        ) from exc
    if not isinstance(payload, list):
        raise AiBriefSourceProviderError(
            "Finnhub source response must contain a JSON array"
        )
    return payload


def _normalize_finnhub_news_rows(
    ticker: str,
    payload: list[object],
) -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    for item in payload:
        if not isinstance(item, Mapping):
            rows.append(
                {
                    "ticker": ticker,
                    "title": "",
                    "url": "",
                    "published_at": "",
                }
            )
            continue
        rows.append(
            {
                "ticker": ticker,
                "title": str(item.get("headline") or "").strip(),
                "url": str(item.get("url") or "").strip(),
                "published_at": _finnhub_published_at_iso(item.get("datetime")),
            }
        )
    return rows


def _finnhub_published_at_iso(value: object) -> str:
    if isinstance(value, bool):
        return ""
    try:
        timestamp = float(str(value).strip())
    except TypeError, ValueError:
        return ""
    if not math.isfinite(timestamp):
        return ""
    return dt.datetime.fromtimestamp(timestamp, tz=dt.UTC).isoformat()


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

    deadline = time.monotonic() + source_timeout_seconds
    try:
        validated_source_api_url = _validate_source_api_request_url(
            POLYGON_NEWS_URL,
            deadline=deadline,
        )
    except ValueError as exc:
        raise AiBriefSourceProviderError(str(exc)) from exc

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
            source_rows.extend(_normalize_polygon_news_rows(ticker, payload))

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
        _close_session(session)


def _parse_polygon_news_response_payload(
    response: Any,
    *,
    deadline: float,
) -> list[object]:
    body = _read_bounded_response_body(response, deadline=deadline)
    try:
        payload = json.loads(body.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise AiBriefSourceProviderError(
            "Polygon News source response was not valid JSON"
        ) from exc
    if not isinstance(payload, Mapping):
        raise AiBriefSourceProviderError(
            "Polygon News source response must contain a JSON object"
        )
    results = payload.get("results")
    if not isinstance(results, list):
        raise AiBriefSourceProviderError(
            "Polygon News source response results must be a list"
        )
    return results


def _normalize_polygon_news_rows(
    ticker: str,
    payload: list[object],
) -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    for item in payload:
        if not isinstance(item, Mapping):
            rows.append(
                {
                    "ticker": ticker,
                    "title": "",
                    "url": "",
                    "published_at": "",
                }
            )
            continue
        rows.append(
            {
                "ticker": ticker,
                "title": str(item.get("title") or "").strip(),
                "url": str(item.get("article_url") or "").strip(),
                "published_at": str(item.get("published_utc") or "").strip(),
            }
        )
    return rows


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

    deadline = time.monotonic() + source_timeout_seconds
    try:
        validated_source_api_url = _validate_source_api_request_url(
            ALPHA_VANTAGE_NEWS_URL,
            deadline=deadline,
        )
    except ValueError as exc:
        raise AiBriefSourceProviderError(str(exc)) from exc

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
            source_rows.extend(_normalize_alpha_vantage_news_rows(ticker, payload))

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
        _close_session(session)


def _parse_alpha_vantage_news_response_payload(
    response: Any,
    *,
    deadline: float,
) -> list[object]:
    body = _read_bounded_response_body(response, deadline=deadline)
    try:
        payload = json.loads(body.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise AiBriefSourceProviderError(
            "Alpha Vantage News source response was not valid JSON"
        ) from exc
    if not isinstance(payload, Mapping):
        raise AiBriefSourceProviderError(
            "Alpha Vantage News source response must contain a JSON object"
        )
    feed = payload.get("feed")
    if not isinstance(feed, list):
        raise AiBriefSourceProviderError(
            "Alpha Vantage News source response feed must be a list"
        )
    return feed


def _normalize_alpha_vantage_news_rows(
    ticker: str,
    payload: list[object],
) -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    for item in payload:
        if not isinstance(item, Mapping):
            rows.append(
                {
                    "ticker": ticker,
                    "title": "",
                    "url": "",
                    "published_at": "",
                }
            )
            continue
        rows.append(
            {
                "ticker": ticker,
                "title": str(item.get("title") or "").strip(),
                "url": str(item.get("url") or "").strip(),
                "published_at": _alpha_vantage_news_published_at_iso(
                    item.get("time_published")
                ),
            }
        )
    return rows


def _alpha_vantage_news_published_at_iso(value: object) -> str:
    text = str(value or "").strip()
    if not text:
        return ""
    for date_format in ("%Y%m%dT%H%M%S", "%Y%m%dT%H%M"):
        try:
            parsed = dt.datetime.strptime(text, date_format)
        except ValueError:
            continue
        return parsed.replace(tzinfo=dt.UTC).isoformat()
    return ""


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

    deadline = time.monotonic() + source_timeout_seconds
    try:
        validated_source_api_url = _validate_source_api_request_url(
            MARKETAUX_NEWS_URL,
            deadline=deadline,
        )
    except ValueError as exc:
        raise AiBriefSourceProviderError(str(exc)) from exc

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
            source_rows.extend(_normalize_marketaux_news_rows(ticker, payload))

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
        _close_session(session)


def _parse_marketaux_news_response_payload(
    response: Any,
    *,
    deadline: float,
) -> list[object]:
    body = _read_bounded_response_body(response, deadline=deadline)
    try:
        payload = json.loads(body.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise AiBriefSourceProviderError(
            "Marketaux News source response was not valid JSON"
        ) from exc
    if not isinstance(payload, Mapping):
        raise AiBriefSourceProviderError(
            "Marketaux News source response must contain a JSON object"
        )
    data = payload.get("data")
    if not isinstance(data, list):
        raise AiBriefSourceProviderError(
            "Marketaux News source response data must be a list"
        )
    return data


def _normalize_marketaux_news_rows(
    ticker: str,
    payload: list[object],
) -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    for item in payload:
        if not isinstance(item, Mapping):
            rows.append(
                {
                    "ticker": ticker,
                    "title": "",
                    "url": "",
                    "published_at": "",
                }
            )
            continue
        rows.append(
            {
                "ticker": ticker,
                "title": str(item.get("title") or "").strip(),
                "url": str(item.get("url") or "").strip(),
                "published_at": str(item.get("published_at") or "").strip(),
            }
        )
    return rows


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

    deadline = time.monotonic() + source_timeout_seconds
    try:
        validated_source_api_url = _validate_source_api_request_url(
            BENZINGA_NEWS_URL,
            deadline=deadline,
        )
    except ValueError as exc:
        raise AiBriefSourceProviderError(str(exc)) from exc

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
            source_rows.extend(_normalize_benzinga_news_rows(ticker, payload))

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
        _close_session(session)


def _parse_benzinga_news_response_payload(
    response: Any,
    *,
    deadline: float,
) -> list[object]:
    body = _read_bounded_response_body(response, deadline=deadline)
    try:
        payload = json.loads(body.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise AiBriefSourceProviderError(
            "Benzinga News source response was not valid JSON"
        ) from exc
    if not isinstance(payload, list):
        raise AiBriefSourceProviderError(
            "Benzinga News source response must contain a JSON array"
        )
    return payload


def _normalize_benzinga_news_rows(
    ticker: str,
    payload: list[object],
) -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    for item in payload:
        if not isinstance(item, Mapping):
            rows.append(
                {
                    "ticker": ticker,
                    "title": "",
                    "url": "",
                    "published_at": "",
                }
            )
            continue
        rows.append(
            {
                "ticker": ticker,
                "title": str(item.get("title") or "").strip(),
                "url": str(item.get("url") or "").strip(),
                "published_at": _benzinga_news_published_at_iso(
                    _benzinga_news_publication_value(item)
                ),
            }
        )
    return rows


def _benzinga_news_publication_value(item: Mapping[str, Any]) -> object:
    created = item.get("created")
    if created is not None and str(created).strip():
        return created
    return item.get("updated")


def _benzinga_news_published_at_iso(value: object) -> str:
    if isinstance(value, bool) or value is None:
        return ""
    text = str(value).strip()
    if not text:
        return ""
    try:
        timestamp = float(text)
    except ValueError:
        pass
    else:
        if math.isfinite(timestamp):
            return dt.datetime.fromtimestamp(timestamp, tz=dt.UTC).isoformat()
    try:
        parsed = dt.datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        try:
            parsed = email.utils.parsedate_to_datetime(text)
        except TypeError, ValueError:
            return ""
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        parsed = parsed.replace(tzinfo=dt.UTC)
    return parsed.isoformat()


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

    deadline = time.monotonic() + source_timeout_seconds
    try:
        validated_source_api_url = _validate_source_api_request_url(
            NAVER_NEWS_SEARCH_URL,
            deadline=deadline,
        )
    except ValueError as exc:
        raise AiBriefSourceProviderError(str(exc)) from exc

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
            source_rows.extend(_normalize_naver_news_rows(ticker, payload))

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
        _close_session(session)


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
    body = _read_bounded_response_body(response, deadline=deadline)
    try:
        payload = json.loads(body.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise AiBriefSourceProviderError(
            "Naver News source response was not valid JSON"
        ) from exc
    if not isinstance(payload, Mapping):
        raise AiBriefSourceProviderError(
            "Naver News source response must contain a JSON object"
        )
    items = payload.get("items")
    if not isinstance(items, list):
        raise AiBriefSourceProviderError(
            "Naver News source response items must be a list"
        )
    return items


def _normalize_naver_news_rows(
    ticker: str,
    payload: list[object],
) -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    for item in payload:
        if not isinstance(item, Mapping):
            rows.append(
                {
                    "ticker": ticker,
                    "title": "",
                    "url": "",
                    "published_at": "",
                }
            )
            continue
        rows.append(
            {
                "ticker": ticker,
                "title": _clean_naver_news_text(item.get("title")),
                "url": _naver_news_url(item),
                "published_at": _naver_news_published_at_iso(item.get("pubDate")),
            }
        )
    return rows


def _clean_naver_news_text(value: object) -> str:
    text = str(value or "").strip()
    if not text:
        return ""
    return _HTML_TAG_RE.sub("", html.unescape(text)).strip()


def _naver_news_url(item: Mapping[str, Any]) -> str:
    originallink = str(item.get("originallink") or "").strip()
    if originallink:
        return originallink
    return str(item.get("link") or "").strip()


def _naver_news_published_at_iso(value: object) -> str:
    text = str(value or "").strip()
    if not text:
        return ""
    try:
        parsed = email.utils.parsedate_to_datetime(text)
    except TypeError, ValueError:
        return ""
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        return ""
    return parsed.isoformat()


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


def _close_session(session: Any) -> None:
    close = getattr(session, "close", None)
    if callable(close):
        close()


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
            source_url_deadline=source_url_deadline,
            resolve_source_url_hostnames=resolve_source_url_hostnames,
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
    source_url_deadline: float | None,
    resolve_source_url_hostnames: bool,
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
        url = _validate_source_row_url(
            url,
            deadline=source_url_deadline,
            resolve_hostname=resolve_source_url_hostnames,
        )
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
    return parse_iso_offset_datetime(value, field_name="published_at")


def validate_ai_brief_source_url(value: object, *, field_name: str = "url") -> str:
    return url_safety.validate_url(value, field_name=field_name)


def validate_ai_brief_source_api_url(value: object) -> str:
    return _validate_source_api_request_url(value, deadline=None).url


def _validate_source_row_url(
    value: object,
    *,
    field_name: str = "url",
    deadline: float | None = None,
    resolve_hostname: bool = False,
) -> str:
    text = validate_ai_brief_source_url(value, field_name=field_name)
    parsed = urlparse(text)
    hostname = parsed.hostname or ""
    port = _validated_url_port(parsed, field_name=field_name)
    hostnames = _source_api_hostname_aliases(hostname)
    if _is_blocked_source_row_hostname(hostname):
        raise ValueError(f"{field_name} must not target local or private hosts")
    if resolve_hostname:
        hostnames = _source_api_fetch_hostname_aliases(hostname, field_name=field_name)
        _resolve_public_source_addrinfos(
            hostnames,
            port,
            field_name=field_name,
            deadline=deadline,
        )
    return text


def _validate_source_api_request_url(
    value: object,
    *,
    deadline: float | None,
) -> _ValidatedSourceApiUrl:
    text = validate_ai_brief_source_url(value, field_name="source API URL")
    parsed = urlparse(text)
    if parsed.scheme.lower() != "https":
        raise ValueError("source API URL must use https")
    hostname = parsed.hostname or ""
    port = _validated_url_port(parsed, field_name="source API URL")
    hostnames = _source_api_fetch_hostname_aliases(
        hostname,
        field_name="source API URL",
    )
    addrinfos = _resolve_source_api_addrinfos(hostnames, port, deadline=deadline)
    return _ValidatedSourceApiUrl(
        url=text,
        hostnames=hostnames,
        addrinfos=addrinfos,
    )


def _validated_url_port(parsed: Any, *, field_name: str) -> int:
    return url_safety.validated_url_port(parsed, field_name=field_name)


def _source_api_token_for_url(url: str) -> str:
    api_token = str(os.getenv("AI_BRIEF_SOURCE_API_TOKEN") or "").strip()
    configured_url = str(os.getenv("AI_BRIEF_SOURCE_API_URL") or "").strip()
    if not api_token or not configured_url:
        return ""
    return api_token if url == configured_url else ""


def _is_blocked_source_row_hostname(hostname: str) -> bool:
    return any(
        url_safety.is_blocked_hostname(alias)
        for alias in _source_api_hostname_aliases(hostname)
    )


def _source_api_hostname_aliases(hostname: str) -> tuple[str, ...]:
    return url_safety.hostname_aliases(hostname)


def _source_api_fetch_hostname_aliases(
    hostname: str,
    *,
    field_name: str,
) -> tuple[str, ...]:
    return url_safety.fetch_hostname_aliases(hostname, field_name=field_name)


def _resolve_source_api_addrinfos(
    hostnames: tuple[str, ...],
    port: int,
    *,
    deadline: float | None,
) -> tuple[Any, ...]:
    return _resolve_public_source_addrinfos(
        hostnames,
        port,
        field_name="source API URL",
        deadline=deadline,
    )


def _resolve_public_source_addrinfos(
    hostnames: tuple[str, ...],
    port: int,
    *,
    field_name: str,
    deadline: float | None,
) -> tuple[Any, ...]:
    if any(url_safety.is_local_hostname(hostname) for hostname in hostnames):
        raise ValueError(f"{field_name} must not target local or private hosts")
    if any(url_safety.is_blocked_ip_text(hostname) for hostname in hostnames):
        raise ValueError(f"{field_name} must not target local or private hosts")
    resolution_hostname = hostnames[-1] if hostnames else ""
    try:
        with _source_dns_pin_lock(deadline):
            addrinfos = _getaddrinfo_with_timeout(
                resolution_hostname,
                port,
                timeout=_source_dns_timeout(deadline),
            )
    except TimeoutError as exc:
        raise AiBriefSourceProviderTimeoutError(
            f"{field_name} DNS resolution timed out"
        ) from exc
    except OSError as exc:
        raise ValueError(f"{field_name} hostname could not be resolved") from exc
    if not addrinfos:
        raise ValueError(f"{field_name} hostname could not be resolved")
    if any(url_safety.is_blocked_addrinfo(addrinfo) for addrinfo in addrinfos):
        raise ValueError(f"{field_name} must not target local or private hosts")
    return tuple(addrinfos)


def _getaddrinfo_with_timeout(
    hostname: str,
    port: int,
    *,
    timeout: float,
) -> list[Any]:
    return url_safety.getaddrinfo_with_timeout(
        hostname,
        port,
        timeout=timeout,
        slots=_SOURCE_DNS_RESOLVER_SLOTS,
        resolver=socket.getaddrinfo,
        thread_factory=threading.Thread,
        monotonic=time.monotonic,
        thread_name="ai-brief-source-dns",
    )


def _source_dns_timeout(deadline: float | None) -> float:
    timeout = SOURCE_ROW_DNS_TIMEOUT_SECONDS
    if deadline is None:
        return timeout
    remaining = deadline - time.monotonic()
    if remaining <= 0:
        raise TimeoutError("DNS resolution timed out")
    return min(timeout, remaining)


@contextmanager
def _pin_source_api_dns(
    hostnames: tuple[str, ...],
    addrinfos: tuple[Any, ...],
    *,
    deadline: float | None = None,
) -> Iterator[None]:
    with url_safety.pin_dns(
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


@contextmanager
def _source_dns_pin_lock(deadline: float | None) -> Iterator[None]:
    with url_safety.dns_pin_lock(
        SOURCE_DNS_PIN_LOCK,
        deadline=deadline,
        remaining_timeout=_remaining_source_timeout,
        timeout_error=lambda: AiBriefSourceProviderTimeoutError(
            "source API DNS pin lock timed out"
        ),
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
