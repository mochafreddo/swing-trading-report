from __future__ import annotations

import datetime as dt
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field

from .ai_brief_source_report import source_issue
from .ai_brief_sources import (
    MAX_SOURCES_PER_TICKER,
    SOURCE_PROVIDER_NONE,
    AiBriefSourceProviderError,
    load_ai_brief_sources,
)

_PROVIDER_ISSUE_PREFIX = {
    "local-json": "local_source",
    "http-json": "http_source",
    "finnhub": "finnhub_source",
    "polygon-news": "polygon_news_source",
    "alpha-vantage-news": "alpha_vantage_news_source",
    "marketaux-news": "marketaux_news_source",
    "benzinga-news": "benzinga_news_source",
    "naver-news": "naver_news_source",
}


@dataclass(frozen=True)
class AiBriefSourceChainResult:
    sources_by_ticker: dict[str, list[dict[str, object]]] = field(default_factory=dict)
    source_issues: list[dict[str, object]] = field(default_factory=list)
    system_issues: list[dict[str, object]] = field(default_factory=list)
    summary: dict[str, object] = field(default_factory=dict)


def parse_source_provider_chain(value: str | None) -> tuple[str, ...]:
    text = str(value or "").strip()
    if not text:
        return ()
    providers = tuple(part.strip().lower() for part in text.split(",") if part.strip())
    if len(set(providers)) != len(providers):
        raise ValueError("source provider chain must not contain duplicate providers")
    if SOURCE_PROVIDER_NONE in providers and len(providers) > 1:
        raise ValueError("source provider chain cannot combine none with providers")
    return providers


def _provider_issue_prefix(provider: str) -> str:
    return _PROVIDER_ISSUE_PREFIX.get(provider, provider.replace("-", "_"))


def _failure_code(exc: AiBriefSourceProviderError) -> str:
    message = str(exc)
    if "HTTP 429" in message:
        return "http_429"
    return exc.code


def _provider_system_issue(
    *,
    provider: str,
    exc: AiBriefSourceProviderError,
) -> dict[str, object]:
    code = _failure_code(exc)
    return {
        "ticker": None,
        "code": "source_provider_chain_failed" if code != "http_429" else code,
        "severity": "WARN",
        "message": f"{provider} source provider failed: {exc}",
    }


def _no_result_issues(
    *,
    provider: str,
    requested_tickers: set[str],
    covered_tickers: set[str],
) -> list[dict[str, object]]:
    prefix = _provider_issue_prefix(provider)
    missing = sorted(requested_tickers - covered_tickers)
    return [
        source_issue(
            ticker=ticker,
            code=f"{prefix}_no_results",
            message=f"{provider} returned no usable sources for {ticker}",
        )
        for ticker in missing
    ]


def _merge_sources(
    target: dict[str, list[dict[str, object]]],
    incoming: Mapping[str, list[dict[str, object]]],
) -> list[dict[str, object]]:
    merge_issues: list[dict[str, object]] = []
    seen_urls = {
        ticker: {str(source.get("url") or "") for source in sources}
        for ticker, sources in target.items()
    }
    for ticker in sorted(incoming):
        target_rows = target.setdefault(ticker, [])
        ticker_seen_urls = seen_urls.setdefault(ticker, set())
        for source in incoming[ticker]:
            url = str(source.get("url") or "")
            if url and url in ticker_seen_urls:
                continue
            if len(target_rows) >= MAX_SOURCES_PER_TICKER:
                merge_issues.append(
                    source_issue(
                        ticker=ticker,
                        code="source_chain_cap_exceeded",
                        message=(
                            "source chain row ignored because ticker already has "
                            f"{MAX_SOURCES_PER_TICKER} sources"
                        ),
                    )
                )
                continue
            target_rows.append(dict(source))
            if url:
                ticker_seen_urls.add(url)
    return merge_issues


def _remaining_tickers(
    *,
    source_universe_tickers: set[str],
    sources_by_ticker: Mapping[str, list[dict[str, object]]],
) -> set[str]:
    return {
        ticker
        for ticker in source_universe_tickers
        if len(sources_by_ticker.get(ticker, [])) < MAX_SOURCES_PER_TICKER
    }


def _coverage(
    tickers: set[str],
    sources_by_ticker: Mapping[str, list[dict[str, object]]],
) -> int:
    return sum(1 for ticker in tickers if sources_by_ticker.get(ticker))


def load_ai_brief_source_chain(
    *,
    source_providers: Sequence[str],
    source_report_path: str | None,
    source_api_url: str | None,
    source_timeout_seconds: float | None,
    source_universe_tickers: set[str],
    recommendable_tickers: set[str],
    watch_tickers: set[str],
    ticker_names: Mapping[str, str],
    now: dt.datetime | None = None,
) -> AiBriefSourceChainResult:
    chain = tuple(source_providers)
    if not chain or chain == (SOURCE_PROVIDER_NONE,):
        return AiBriefSourceChainResult(
            summary={
                "chain": [SOURCE_PROVIDER_NONE],
                "providers": [],
                "final": {
                    "recommendable_covered": 0,
                    "recommendable_total": len(recommendable_tickers),
                    "watch_covered": 0,
                    "watch_total": len(watch_tickers),
                },
            }
        )

    sources_by_ticker: dict[str, list[dict[str, object]]] = {}
    source_issues: list[dict[str, object]] = []
    no_result_issues: list[dict[str, object]] = []
    system_issues: list[dict[str, object]] = []
    provider_summaries: list[dict[str, object]] = []
    resolved_now = now or dt.datetime.now().astimezone()

    for provider in chain:
        requested_tickers = _remaining_tickers(
            source_universe_tickers=source_universe_tickers,
            sources_by_ticker=sources_by_ticker,
        )
        if not requested_tickers:
            provider_summaries.append(
                {
                    "provider": provider,
                    "status": "skipped",
                    "covered": 0,
                    "total": 0,
                }
            )
            continue
        try:
            provider_result = load_ai_brief_sources(
                source_provider=provider,
                source_report_path=source_report_path,
                source_api_url=source_api_url,
                source_timeout_seconds=source_timeout_seconds,
                eligible_tickers=requested_tickers,
                ticker_names=ticker_names,
                now=resolved_now,
            )
        except AiBriefSourceProviderError as exc:
            code = _failure_code(exc)
            system_issues.append(_provider_system_issue(provider=provider, exc=exc))
            provider_summaries.append(
                {
                    "provider": provider,
                    "status": "failed",
                    "code": code,
                    "covered": 0,
                    "total": len(requested_tickers),
                }
            )
            continue

        covered_tickers = {
            ticker
            for ticker, sources in provider_result.sources_by_ticker.items()
            if ticker in requested_tickers and sources
        }
        source_issues.extend(provider_result.source_issues)
        source_issues.extend(
            _merge_sources(sources_by_ticker, provider_result.sources_by_ticker)
        )
        no_result_issues.extend(
            _no_result_issues(
                provider=provider,
                requested_tickers=requested_tickers,
                covered_tickers=covered_tickers,
            )
        )
        provider_summaries.append(
            {
                "provider": provider,
                "status": "success",
                "covered": len(covered_tickers),
                "total": len(requested_tickers),
            }
        )

    return AiBriefSourceChainResult(
        sources_by_ticker=sources_by_ticker,
        source_issues=[*source_issues, *no_result_issues],
        system_issues=system_issues,
        summary={
            "chain": list(chain),
            "providers": provider_summaries,
            "final": {
                "recommendable_covered": _coverage(
                    recommendable_tickers,
                    sources_by_ticker,
                ),
                "recommendable_total": len(recommendable_tickers),
                "watch_covered": _coverage(watch_tickers, sources_by_ticker),
                "watch_total": len(watch_tickers),
            },
        },
    )


__all__ = [
    "AiBriefSourceChainResult",
    "load_ai_brief_source_chain",
    "parse_source_provider_chain",
]
