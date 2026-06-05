from __future__ import annotations

import argparse
import datetime as dt
import json
import math
import os
import sys
import time
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from sab.ai_brief_source_collectors import (  # noqa: E402
    DEFAULT_FEED_TIMEOUT_SECONDS,
    AiBriefSourceCollectorError,
    collect_ai_brief_sources,
    parse_collect_now,
)
from sab.ai_brief_source_live_compare import (  # noqa: E402
    _load_buy_ticker_names,
    _load_eligible_tickers,
)
from sab.ai_brief_sources import (  # noqa: E402
    MAX_SOURCES_PER_TICKER,
    SOURCE_FRESHNESS_HOURS,
    SOURCE_PROVIDER_ALPHA_VANTAGE_NEWS,
    SOURCE_PROVIDER_BENZINGA_NEWS,
    SOURCE_PROVIDER_FINNHUB,
    SOURCE_PROVIDER_HTTP_JSON,
    SOURCE_PROVIDER_MARKETAUX_NEWS,
    SOURCE_PROVIDER_NAVER_NEWS,
    SOURCE_PROVIDER_POLYGON_NEWS,
    AiBriefSourceProviderError,
    load_ai_brief_sources,
)
from sab.config import ConfigLoadError, load_config  # noqa: E402
from sab.data.kis_client import KISClient, KISClientError, KISCredentials  # noqa: E402
from sab.market_data_common import infer_env_from_base_url  # noqa: E402
from sab.tickers import (  # noqa: E402
    parse_ticker,
    validate_strict_holdings_ticker,
    validate_strict_us_ticker,
)

_ALLOWED_LIVE_SOURCE_PROVIDERS = frozenset(
    {
        SOURCE_PROVIDER_HTTP_JSON,
        SOURCE_PROVIDER_FINNHUB,
        SOURCE_PROVIDER_POLYGON_NEWS,
        SOURCE_PROVIDER_ALPHA_VANTAGE_NEWS,
        SOURCE_PROVIDER_MARKETAUX_NEWS,
        SOURCE_PROVIDER_BENZINGA_NEWS,
        SOURCE_PROVIDER_NAVER_NEWS,
    }
)


@dataclass(frozen=True)
class SourceProviderSmokeSpec:
    label: str
    provider: str
    source_api_url: str | None = None


@dataclass(frozen=True)
class LiveIntegrationSmokeCheck:
    name: str
    status: str
    message: str
    summary: dict[str, object]
    duration_ms: int

    def to_dict(self) -> dict[str, object]:
        return {
            "name": self.name,
            "status": self.status,
            "message": self.message,
            "duration_ms": self.duration_ms,
            "summary": self.summary,
        }


@dataclass(frozen=True)
class LiveIntegrationSmokeResult:
    checks: list[LiveIntegrationSmokeCheck]

    @property
    def status(self) -> str:
        statuses = [check.status for check in self.checks]
        if any(status == "FAIL" for status in statuses):
            return "FAIL"
        if any(status == "WARN" for status in statuses):
            return "WARN"
        return "PASS"

    def to_dict(self) -> dict[str, object]:
        status_counts = {
            "pass_count": sum(1 for check in self.checks if check.status == "PASS"),
            "warn_count": sum(1 for check in self.checks if check.status == "WARN"),
            "fail_count": sum(1 for check in self.checks if check.status == "FAIL"),
        }
        return {
            "status": self.status,
            "summary": {
                "check_count": len(self.checks),
                **status_counts,
            },
            "checks": [check.to_dict() for check in self.checks],
        }


def parse_source_provider_specs(
    *,
    provider_values: Sequence[str],
    source_api_url_values: Sequence[str] | None = None,
) -> list[SourceProviderSmokeSpec]:
    source_api_url_values = source_api_url_values or []
    raw_source_api_urls = _parse_labeled_values(
        source_api_url_values,
        option_name="--source-api-url",
    )

    specs: list[SourceProviderSmokeSpec] = []
    seen_label_keys: set[str] = set()
    for raw_value in provider_values:
        label, provider = _parse_labeled_value(
            raw_value, option_name="--source-provider"
        )
        provider = provider.lower()
        label_key = label.casefold()
        if label_key in seen_label_keys:
            raise ValueError(f"duplicate --source-provider label {label!r}")
        if provider not in _ALLOWED_LIVE_SOURCE_PROVIDERS:
            raise ValueError(
                "source provider must be one of "
                f"{sorted(_ALLOWED_LIVE_SOURCE_PROVIDERS)}; got {provider!r}"
            )
        seen_label_keys.add(label_key)
        specs.append(
            SourceProviderSmokeSpec(
                label=label,
                provider=provider,
                source_api_url=raw_source_api_urls.get(label),
            )
        )

    for label in raw_source_api_urls:
        matching_spec = next((spec for spec in specs if spec.label == label), None)
        if matching_spec is None:
            raise ValueError(f"--source-api-url label {label!r} is unknown")
        if matching_spec.provider != SOURCE_PROVIDER_HTTP_JSON:
            raise ValueError(
                "--source-api-url can only be used with http-json source providers"
            )

    return _resolve_http_json_source_api_urls(specs)


def run_smoke(
    *,
    rss_feed_catalog_path: str | None = None,
    rss_tickers: set[str] | None = None,
    rss_freshness_hours: float = SOURCE_FRESHNESS_HOURS,
    rss_max_sources_per_ticker: int = MAX_SOURCES_PER_TICKER,
    rss_feed_timeout_seconds: float = DEFAULT_FEED_TIMEOUT_SECONDS,
    source_entry_report_path: str | None = None,
    source_provider_specs: Sequence[SourceProviderSmokeSpec] | None = None,
    source_buy_report_path: str | None = None,
    source_market: str | None = None,
    source_timeout_seconds: float | None = None,
    kis_token: bool = False,
    kis_domestic_price_tickers: Sequence[str] | None = None,
    kis_overseas_price_tickers: Sequence[str] | None = None,
    kis_domestic_candle_tickers: Sequence[str] | None = None,
    kis_overseas_candle_tickers: Sequence[str] | None = None,
    kis_candle_count: int = 1,
    collect_ai_brief_sources_fn: Callable[..., Any] | None = None,
    load_ai_brief_sources_fn: Callable[..., Any] | None = None,
    load_config_fn: Callable[[], Any] | None = None,
    KISCredentialsCls: Callable[..., Any] | None = None,
    KISClientCls: Callable[..., Any] | None = None,
    now: dt.datetime | None = None,
) -> LiveIntegrationSmokeResult:
    checks: list[LiveIntegrationSmokeCheck] = []
    resolved_now = now or dt.datetime.now().astimezone()
    source_provider_specs = list(source_provider_specs or [])
    kis_domestic_price_tickers = list(kis_domestic_price_tickers or [])
    kis_overseas_price_tickers = list(kis_overseas_price_tickers or [])
    kis_domestic_candle_tickers = list(kis_domestic_candle_tickers or [])
    kis_overseas_candle_tickers = list(kis_overseas_candle_tickers or [])

    if not _has_requested_checks(
        rss_feed_catalog_path=rss_feed_catalog_path,
        source_provider_specs=source_provider_specs,
        kis_token=kis_token,
        kis_domestic_price_tickers=kis_domestic_price_tickers,
        kis_overseas_price_tickers=kis_overseas_price_tickers,
        kis_domestic_candle_tickers=kis_domestic_candle_tickers,
        kis_overseas_candle_tickers=kis_overseas_candle_tickers,
    ):
        raise ValueError("select at least one live integration smoke check")

    _validate_kis_ticker_markets(
        domestic_price_tickers=kis_domestic_price_tickers,
        overseas_price_tickers=kis_overseas_price_tickers,
        domestic_candle_tickers=kis_domestic_candle_tickers,
        overseas_candle_tickers=kis_overseas_candle_tickers,
    )

    if rss_feed_catalog_path:
        checks.append(
            _run_rss_feed_check(
                feed_catalog_path=rss_feed_catalog_path,
                tickers=rss_tickers,
                freshness_hours=rss_freshness_hours,
                max_sources_per_ticker=rss_max_sources_per_ticker,
                feed_timeout_seconds=rss_feed_timeout_seconds,
                collect_ai_brief_sources_fn=(
                    collect_ai_brief_sources
                    if collect_ai_brief_sources_fn is None
                    else collect_ai_brief_sources_fn
                ),
                now=resolved_now,
            )
        )

    if source_provider_specs:
        if source_entry_report_path is None or not source_entry_report_path.strip():
            raise ValueError("--entry-report is required with --source-provider")
        for spec in source_provider_specs:
            checks.append(
                _run_source_provider_check(
                    spec=spec,
                    entry_report_path=source_entry_report_path,
                    buy_report_path=source_buy_report_path,
                    market=source_market,
                    source_timeout_seconds=source_timeout_seconds,
                    load_ai_brief_sources_fn=(
                        load_ai_brief_sources
                        if load_ai_brief_sources_fn is None
                        else load_ai_brief_sources_fn
                    ),
                    now=resolved_now,
                )
            )

    if _has_kis_checks(
        kis_token=kis_token,
        kis_domestic_price_tickers=kis_domestic_price_tickers,
        kis_overseas_price_tickers=kis_overseas_price_tickers,
        kis_domestic_candle_tickers=kis_domestic_candle_tickers,
        kis_overseas_candle_tickers=kis_overseas_candle_tickers,
    ):
        checks.extend(
            _run_kis_checks(
                kis_token=kis_token,
                domestic_price_tickers=kis_domestic_price_tickers,
                overseas_price_tickers=kis_overseas_price_tickers,
                domestic_candle_tickers=kis_domestic_candle_tickers,
                overseas_candle_tickers=kis_overseas_candle_tickers,
                candle_count=kis_candle_count,
                load_config_fn=load_config
                if load_config_fn is None
                else load_config_fn,
                KISCredentialsCls=(
                    KISCredentials if KISCredentialsCls is None else KISCredentialsCls
                ),
                KISClientCls=KISClient if KISClientCls is None else KISClientCls,
            )
        )

    return LiveIntegrationSmokeResult(checks=checks)


def _run_rss_feed_check(
    *,
    feed_catalog_path: str,
    tickers: set[str] | None,
    freshness_hours: float,
    max_sources_per_ticker: int,
    feed_timeout_seconds: float,
    collect_ai_brief_sources_fn: Callable[..., Any],
    now: dt.datetime,
) -> LiveIntegrationSmokeCheck:
    started_at = _monotonic_seconds()
    try:
        result = collect_ai_brief_sources_fn(
            feed_catalog_path=feed_catalog_path,
            tickers=tickers,
            now=now,
            freshness_hours=freshness_hours,
            max_sources_per_ticker=max_sources_per_ticker,
            feed_timeout_seconds=feed_timeout_seconds,
        )
    except (AiBriefSourceCollectorError, ValueError, OSError) as exc:
        return _check(
            name="rss-feed",
            status="FAIL",
            message=f"RSS feed collection failed: {exc}",
            summary={},
            started_at=started_at,
        )

    sources = list(getattr(result, "sources", []))
    issues = list(getattr(result, "issues", []))
    status = _normalize_check_status(getattr(result, "status", "FAIL"))
    if status == "PASS" and not sources:
        status = "WARN"
    return _check(
        name="rss-feed",
        status=status,
        message="RSS feed catalog collected",
        summary={
            "source_count": len(sources),
            "issue_count": len(issues),
            "covered_tickers": sorted(
                {
                    str(source.get("ticker"))
                    for source in sources
                    if isinstance(source, Mapping) and source.get("ticker")
                }
            ),
        },
        started_at=started_at,
    )


def _run_source_provider_check(
    *,
    spec: SourceProviderSmokeSpec,
    entry_report_path: str,
    buy_report_path: str | None,
    market: str | None,
    source_timeout_seconds: float | None,
    load_ai_brief_sources_fn: Callable[..., Any],
    now: dt.datetime,
) -> LiveIntegrationSmokeCheck:
    started_at = _monotonic_seconds()
    try:
        eligible_tickers = _load_eligible_tickers(entry_report_path, market=market)
        ticker_names = (
            _load_buy_ticker_names(buy_report_path, eligible_tickers=eligible_tickers)
            if buy_report_path
            else {}
        )
        if not eligible_tickers:
            return _check(
                name=f"source-provider:{spec.label}",
                status="FAIL",
                message="entry report contains no eligible ENTER tickers",
                summary={
                    "provider": spec.provider,
                    "eligible_ticker_count": 0,
                },
                started_at=started_at,
            )
        provider_result = load_ai_brief_sources_fn(
            source_provider=spec.provider,
            source_report_path=None,
            source_api_url=spec.source_api_url,
            source_timeout_seconds=source_timeout_seconds,
            eligible_tickers=eligible_tickers,
            ticker_names=ticker_names,
            now=now,
        )
    except AiBriefSourceProviderError as exc:
        return _check(
            name=f"source-provider:{spec.label}",
            status="FAIL",
            message=str(exc),
            summary={
                "provider": spec.provider,
                "error_code": exc.code,
            },
            started_at=started_at,
        )
    except (OSError, ValueError) as exc:
        return _check(
            name=f"source-provider:{spec.label}",
            status="FAIL",
            message=f"source provider smoke failed before request: {exc}",
            summary={"provider": spec.provider},
            started_at=started_at,
        )

    sources_by_ticker = getattr(provider_result, "sources_by_ticker", {})
    issues = list(getattr(provider_result, "source_issues", []))
    covered_tickers = sorted(
        ticker
        for ticker, rows in sources_by_ticker.items()
        if isinstance(rows, list) and rows
    )
    source_count = sum(
        len(rows) for rows in sources_by_ticker.values() if isinstance(rows, list)
    )
    status = "WARN" if issues or source_count == 0 else "PASS"
    return _check(
        name=f"source-provider:{spec.label}",
        status=status,
        message="source provider responded",
        summary={
            "provider": spec.provider,
            "eligible_ticker_count": len(eligible_tickers),
            "covered_ticker_count": len(covered_tickers),
            "covered_tickers": covered_tickers,
            "source_count": source_count,
            "issue_count": len(issues),
        },
        started_at=started_at,
    )


def _run_kis_checks(
    *,
    kis_token: bool,
    domestic_price_tickers: Sequence[str],
    overseas_price_tickers: Sequence[str],
    domestic_candle_tickers: Sequence[str],
    overseas_candle_tickers: Sequence[str],
    candle_count: int,
    load_config_fn: Callable[[], Any],
    KISCredentialsCls: Callable[..., Any],
    KISClientCls: Callable[..., Any],
) -> list[LiveIntegrationSmokeCheck]:
    started_at = _monotonic_seconds()
    try:
        client, config_summary = _build_kis_client(
            load_config_fn=load_config_fn,
            KISCredentialsCls=KISCredentialsCls,
            KISClientCls=KISClientCls,
        )
    except (ConfigLoadError, KISClientError, ValueError) as exc:
        return [
            _check(
                name="kis-client",
                status="FAIL",
                message=f"KIS client setup failed: {exc}",
                summary={},
                started_at=started_at,
            )
        ]

    checks: list[LiveIntegrationSmokeCheck] = []
    if kis_token:
        checks.append(
            _run_kis_operation(
                name="kis-token",
                action=lambda: client.ensure_token(),
                summarize=lambda _result: {
                    **config_summary,
                    "cache_status": str(getattr(client, "cache_status", "unknown")),
                },
            )
        )
    for ticker in domestic_price_tickers:
        symbol = _split_domestic_smoke_ticker(ticker)
        checks.append(
            _run_kis_operation(
                name=f"kis-domestic-price:{ticker}",
                action=lambda symbol=symbol: client.domestic_price_detail(
                    ticker=symbol
                ),
                summarize=_summarize_mapping_payload,
            )
        )
    for ticker in overseas_price_tickers:
        symbol, exchange = _split_overseas_smoke_ticker(ticker)
        checks.append(
            _run_kis_operation(
                name=f"kis-overseas-price:{ticker}",
                action=lambda symbol=symbol, exchange=exchange: (
                    client.overseas_price_detail(
                        symbol=symbol,
                        exchange=exchange,
                    )
                ),
                summarize=_summarize_mapping_payload,
            )
        )
    normalized_candle_count = max(1, int(candle_count))
    for ticker in domestic_candle_tickers:
        symbol = _split_domestic_smoke_ticker(ticker)
        checks.append(
            _run_kis_operation(
                name=f"kis-domestic-candles:{ticker}",
                action=lambda symbol=symbol: client.daily_candles(
                    symbol,
                    count=normalized_candle_count,
                    adjusted=False,
                ),
                summarize=_summarize_candle_rows,
            )
        )
    for ticker in overseas_candle_tickers:
        symbol, exchange = _split_overseas_smoke_ticker(ticker)
        checks.append(
            _run_kis_operation(
                name=f"kis-overseas-candles:{ticker}",
                action=lambda symbol=symbol, exchange=exchange: (
                    client.overseas_daily_candles(
                        symbol=symbol,
                        exchange=exchange,
                        count=normalized_candle_count,
                        adjusted=False,
                    )
                ),
                summarize=_summarize_candle_rows,
            )
        )
    return checks


def _build_kis_client(
    *,
    load_config_fn: Callable[[], Any],
    KISCredentialsCls: Callable[..., Any],
    KISClientCls: Callable[..., Any],
) -> tuple[Any, dict[str, object]]:
    cfg = load_config_fn()
    app_key = getattr(cfg, "kis_app_key", None)
    app_secret = getattr(cfg, "kis_app_secret", None)
    base_url = getattr(cfg, "kis_base_url", None)
    if not (app_key and app_secret and base_url):
        raise ValueError(
            "missing KIS_APP_KEY, KIS_APP_SECRET, or KIS_BASE_URL configuration"
        )
    min_interval_ms = getattr(cfg, "kis_min_interval_ms", None)
    min_interval = (
        max(0.0, float(min_interval_ms) / 1000.0)
        if min_interval_ms is not None
        else None
    )
    creds = KISCredentialsCls(
        app_key=app_key,
        app_secret=app_secret,
        base_url=base_url,
        env=infer_env_from_base_url(base_url),
    )
    client = KISClientCls(
        creds,
        cache_dir=getattr(cfg, "data_dir", None),
        min_interval=min_interval,
    )
    return client, {
        "provider_env": infer_env_from_base_url(base_url),
        "cache_dir_configured": bool(getattr(cfg, "data_dir", None)),
    }


def _run_kis_operation(
    *,
    name: str,
    action: Callable[[], Any],
    summarize: Callable[[Any], dict[str, object]],
) -> LiveIntegrationSmokeCheck:
    started_at = _monotonic_seconds()
    try:
        result = action()
        summary = summarize(result)
    except (KISClientError, ValueError, TypeError) as exc:
        return _check(
            name=name,
            status="FAIL",
            message=f"KIS smoke failed: {exc}",
            summary={},
            started_at=started_at,
        )
    status = "PASS"
    if summary.get("empty") is True:
        status = "FAIL"
    return _check(
        name=name,
        status=status,
        message="KIS endpoint responded",
        summary=summary,
        started_at=started_at,
    )


def _summarize_mapping_payload(payload: Any) -> dict[str, object]:
    if not isinstance(payload, Mapping) or not payload:
        return {"empty": True, "field_count": 0, "sample_keys": []}
    sample_keys = sorted(str(key) for key in payload)[:8]
    return {
        "empty": False,
        "field_count": len(payload),
        "sample_keys": sample_keys,
    }


def _summarize_candle_rows(rows: Any) -> dict[str, object]:
    if not isinstance(rows, list) or not rows:
        return {"empty": True, "row_count": 0, "latest_date": None}
    latest_row = rows[-1] if isinstance(rows[-1], Mapping) else {}
    return {
        "empty": False,
        "row_count": len(rows),
        "latest_date": latest_row.get("date")
        if isinstance(latest_row, Mapping)
        else None,
    }


def _validate_kis_ticker_markets(
    *,
    domestic_price_tickers: Sequence[str],
    overseas_price_tickers: Sequence[str],
    domestic_candle_tickers: Sequence[str],
    overseas_candle_tickers: Sequence[str],
) -> None:
    for ticker in domestic_price_tickers:
        _split_domestic_smoke_ticker(ticker)
    for ticker in domestic_candle_tickers:
        _split_domestic_smoke_ticker(ticker)
    for ticker in overseas_price_tickers:
        _split_overseas_smoke_ticker(ticker)
    for ticker in overseas_candle_tickers:
        _split_overseas_smoke_ticker(ticker)


def _split_domestic_smoke_ticker(ticker: str) -> str:
    normalized = _normalize_smoke_ticker(ticker)
    issue = validate_strict_holdings_ticker(normalized)
    if issue is not None:
        raise ValueError(f"{normalized}: {issue}")
    parsed = parse_ticker(normalized)
    if parsed.market != "KR":
        raise ValueError(
            f"{parsed.ticker}: domestic KIS smoke ticker must be a KR ticker"
        )
    return parsed.symbol


def _split_overseas_smoke_ticker(ticker: str) -> tuple[str, str]:
    normalized = _normalize_smoke_ticker(ticker)
    issue = validate_strict_us_ticker(normalized)
    if issue is not None:
        raise ValueError(
            f"{normalized}: overseas KIS smoke ticker must be a US ticker "
            f"with .NAS/.NYS/.AMS suffix ({issue})"
        )
    parsed = parse_ticker(normalized)
    if parsed.exchange is None:
        raise ValueError(
            f"{parsed.ticker}: overseas KIS smoke ticker must be a US ticker "
            "with .NAS/.NYS/.AMS suffix"
        )
    return parsed.symbol, parsed.exchange


def _normalize_smoke_ticker(ticker: str) -> str:
    return str(ticker or "").strip().upper()


def _check(
    *,
    name: str,
    status: str,
    message: str,
    summary: dict[str, object],
    started_at: float,
) -> LiveIntegrationSmokeCheck:
    return LiveIntegrationSmokeCheck(
        name=name,
        status=_normalize_check_status(status),
        message=message,
        summary=summary,
        duration_ms=_elapsed_ms(
            started_at=started_at,
            completed_at=_monotonic_seconds(),
        ),
    )


def _normalize_check_status(value: object) -> str:
    status = str(value or "").strip().upper()
    if status in {"PASS", "WARN", "FAIL"}:
        return status
    return "FAIL"


def _parse_labeled_values(
    values: Sequence[str],
    *,
    option_name: str,
) -> dict[str, str]:
    parsed: dict[str, str] = {}
    seen_label_keys: set[str] = set()
    for raw_value in values:
        label, value = _parse_labeled_value(raw_value, option_name=option_name)
        label_key = label.casefold()
        if label_key in seen_label_keys:
            raise ValueError(f"duplicate {option_name} label {label!r}")
        seen_label_keys.add(label_key)
        parsed[label] = value
    return parsed


def _parse_labeled_value(raw_value: str, *, option_name: str) -> tuple[str, str]:
    label, separator, value = str(raw_value or "").partition("=")
    if not separator:
        raise ValueError(f"{option_name} must use LABEL=VALUE")
    label = label.strip()
    value = value.strip()
    if not label or not all(ch.isalnum() or ch in "._-" for ch in label):
        raise ValueError(f"{option_name} label must match [A-Za-z0-9_.-]+")
    if not value:
        raise ValueError(f"{option_name} value must not be empty")
    if "\n" in value or "\r" in value:
        raise ValueError(f"{option_name} value must be single-line")
    return label, value


def _resolve_http_json_source_api_urls(
    specs: Sequence[SourceProviderSmokeSpec],
) -> list[SourceProviderSmokeSpec]:
    missing_http_json = [
        spec
        for spec in specs
        if spec.provider == SOURCE_PROVIDER_HTTP_JSON and not spec.source_api_url
    ]
    if not missing_http_json:
        return list(specs)
    env_url = _normalize_optional_url(os.getenv("AI_BRIEF_SOURCE_API_URL"))
    if len(missing_http_json) == 1 and env_url is not None:
        missing_label = missing_http_json[0].label
        return [
            SourceProviderSmokeSpec(
                label=spec.label,
                provider=spec.provider,
                source_api_url=env_url
                if spec.label == missing_label
                else spec.source_api_url,
            )
            for spec in specs
        ]
    raise ValueError(
        "http-json source providers require --source-api-url LABEL=URL or "
        "AI_BRIEF_SOURCE_API_URL when exactly one http-json provider is missing a URL"
    )


def _normalize_optional_url(value: object) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    if not text:
        return None
    if "\n" in text or "\r" in text:
        raise ValueError("source API URL must be single-line")
    return text


def _has_requested_checks(
    *,
    rss_feed_catalog_path: str | None,
    source_provider_specs: Sequence[SourceProviderSmokeSpec],
    kis_token: bool,
    kis_domestic_price_tickers: Sequence[str],
    kis_overseas_price_tickers: Sequence[str],
    kis_domestic_candle_tickers: Sequence[str],
    kis_overseas_candle_tickers: Sequence[str],
) -> bool:
    return bool(
        rss_feed_catalog_path
        or source_provider_specs
        or _has_kis_checks(
            kis_token=kis_token,
            kis_domestic_price_tickers=kis_domestic_price_tickers,
            kis_overseas_price_tickers=kis_overseas_price_tickers,
            kis_domestic_candle_tickers=kis_domestic_candle_tickers,
            kis_overseas_candle_tickers=kis_overseas_candle_tickers,
        )
    )


def _has_kis_checks(
    *,
    kis_token: bool,
    kis_domestic_price_tickers: Sequence[str],
    kis_overseas_price_tickers: Sequence[str],
    kis_domestic_candle_tickers: Sequence[str],
    kis_overseas_candle_tickers: Sequence[str],
) -> bool:
    return bool(
        kis_token
        or kis_domestic_price_tickers
        or kis_overseas_price_tickers
        or kis_domestic_candle_tickers
        or kis_overseas_candle_tickers
    )


def _monotonic_seconds() -> float:
    return time.monotonic()


def _elapsed_ms(*, started_at: float, completed_at: float) -> int:
    return max(0, round((completed_at - started_at) * 1000))


def _positive_float(value: float | None, *, name: str) -> float | None:
    if value is None:
        return None
    if not math.isfinite(value) or value <= 0:
        raise ValueError(f"{name} must be positive")
    return float(value)


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Optionally smoke test live RSS/API/KIS market-data integration "
            "boundaries. Only selected checks perform network calls."
        )
    )
    parser.add_argument(
        "--rss-feed-catalog",
        default=None,
        help="JSON RSS/Atom/RDF feed catalog to fetch and parse",
    )
    parser.add_argument(
        "--rss-ticker",
        action="append",
        default=[],
        help="Ticker to include from the RSS feed catalog; repeat to filter",
    )
    parser.add_argument(
        "--rss-freshness-hours",
        type=float,
        default=SOURCE_FRESHNESS_HOURS,
        help="Maximum RSS source age in hours",
    )
    parser.add_argument(
        "--rss-max-sources-per-ticker",
        type=int,
        default=MAX_SOURCES_PER_TICKER,
        help="Maximum emitted RSS source rows per ticker",
    )
    parser.add_argument(
        "--rss-feed-timeout-seconds",
        type=float,
        default=DEFAULT_FEED_TIMEOUT_SECONDS,
        help="Timeout for each live feed URL request",
    )
    parser.add_argument(
        "--entry-report",
        default=None,
        help="Entry report JSON used to derive source-provider eligible tickers",
    )
    parser.add_argument(
        "--source-provider",
        action="append",
        default=[],
        metavar="LABEL=PROVIDER",
        help=(
            "AI Brief source provider to smoke test; repeat as needed. PROVIDER "
            "is http-json, finnhub, polygon-news, alpha-vantage-news, "
            "marketaux-news, benzinga-news, or naver-news."
        ),
    )
    parser.add_argument(
        "--source-api-url",
        action="append",
        default=[],
        metavar="LABEL=URL",
        help="External source API URL for a LABEL whose provider is http-json",
    )
    parser.add_argument(
        "--buy-report",
        default=None,
        help="Optional buy report path for source-provider ticker name enrichment",
    )
    parser.add_argument(
        "--market",
        choices=["KR", "US"],
        default=None,
        help="Single market to evaluate; required for MIXED entry reports",
    )
    parser.add_argument(
        "--source-timeout-seconds",
        type=float,
        default=None,
        help="External source provider timeout in seconds",
    )
    parser.add_argument(
        "--kis-token",
        action="store_true",
        help="Smoke test KIS token acquisition/cache boundary",
    )
    parser.add_argument(
        "--kis-domestic-price-ticker",
        action="append",
        default=[],
        help="KR ticker for KIS domestic price-detail smoke; repeat as needed",
    )
    parser.add_argument(
        "--kis-overseas-price-ticker",
        action="append",
        default=[],
        help="US ticker with .NAS/.NYS/.AMS suffix for KIS overseas price smoke",
    )
    parser.add_argument(
        "--kis-domestic-candle-ticker",
        action="append",
        default=[],
        help="KR ticker for KIS domestic daily candle smoke; repeat as needed",
    )
    parser.add_argument(
        "--kis-overseas-candle-ticker",
        action="append",
        default=[],
        help="US ticker with .NAS/.NYS/.AMS suffix for KIS overseas candle smoke",
    )
    parser.add_argument(
        "--kis-candle-count",
        type=int,
        default=1,
        help="Number of candles requested for each KIS candle smoke",
    )
    parser.add_argument(
        "--now",
        type=str,
        default=None,
        help="Optional ISO 8601 timestamp for deterministic source freshness checks",
    )
    parser.add_argument(
        "--pretty",
        action="store_true",
        help="Pretty-print JSON output",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = _build_parser()
    ns = parser.parse_args(argv)
    try:
        source_provider_specs = parse_source_provider_specs(
            provider_values=ns.source_provider,
            source_api_url_values=ns.source_api_url,
        )
        result = run_smoke(
            rss_feed_catalog_path=ns.rss_feed_catalog,
            rss_tickers=set(ns.rss_ticker) if ns.rss_ticker else None,
            rss_freshness_hours=_positive_float(
                ns.rss_freshness_hours,
                name="rss_freshness_hours",
            )
            or SOURCE_FRESHNESS_HOURS,
            rss_max_sources_per_ticker=ns.rss_max_sources_per_ticker,
            rss_feed_timeout_seconds=_positive_float(
                ns.rss_feed_timeout_seconds,
                name="rss_feed_timeout_seconds",
            )
            or DEFAULT_FEED_TIMEOUT_SECONDS,
            source_entry_report_path=ns.entry_report,
            source_provider_specs=source_provider_specs,
            source_buy_report_path=ns.buy_report,
            source_market=ns.market,
            source_timeout_seconds=_positive_float(
                ns.source_timeout_seconds,
                name="source_timeout_seconds",
            ),
            kis_token=ns.kis_token,
            kis_domestic_price_tickers=ns.kis_domestic_price_ticker,
            kis_overseas_price_tickers=ns.kis_overseas_price_ticker,
            kis_domestic_candle_tickers=ns.kis_domestic_candle_ticker,
            kis_overseas_candle_tickers=ns.kis_overseas_candle_ticker,
            kis_candle_count=ns.kis_candle_count,
            now=parse_collect_now(ns.now) if ns.now else None,
        )
    except ValueError as exc:
        parser.error(str(exc))

    print(
        json.dumps(
            result.to_dict(),
            ensure_ascii=False,
            indent=2 if ns.pretty else None,
            sort_keys=True,
        )
    )
    return 1 if result.status == "FAIL" else 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
