from __future__ import annotations

import datetime as dt
from typing import cast

import pytest
import sab.ai_brief_source_chain as source_chain
from sab.ai_brief_sources import (
    AiBriefSourceProviderError,
    AiBriefSourceProviderResult,
)


def _source(ticker: str, suffix: str) -> dict[str, object]:
    return {
        "title": f"{ticker} source {suffix}",
        "url": f"https://news.example/{ticker}/{suffix}",
        "published_at": "2026-06-15T12:00:00+00:00",
    }


def test_source_chain_merges_remaining_tickers_and_records_coverage(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[tuple[str, set[str]]] = []

    def fake_load(**kwargs: object) -> AiBriefSourceProviderResult:
        provider = str(kwargs["source_provider"])
        tickers = set(cast(set[str], kwargs["eligible_tickers"]))
        calls.append((provider, tickers))
        if provider == "finnhub":
            return AiBriefSourceProviderResult(
                sources_by_ticker={"AAPL.NAS": [_source("AAPL.NAS", "finnhub")]}
            )
        if provider == "benzinga-news":
            return AiBriefSourceProviderResult(
                sources_by_ticker={"MSFT.NAS": [_source("MSFT.NAS", "benzinga")]}
            )
        return AiBriefSourceProviderResult()

    monkeypatch.setattr(source_chain, "load_ai_brief_sources", fake_load)

    result = source_chain.load_ai_brief_source_chain(
        source_providers=("finnhub", "benzinga-news"),
        source_report_path=None,
        source_api_url=None,
        source_timeout_seconds=2.0,
        source_universe_tickers={"AAPL.NAS", "MSFT.NAS"},
        recommendable_tickers={"AAPL.NAS"},
        watch_tickers={"MSFT.NAS"},
        ticker_names={},
        now=dt.datetime(2026, 6, 15, 12, 0, tzinfo=dt.UTC),
    )

    assert calls == [
        ("finnhub", {"AAPL.NAS", "MSFT.NAS"}),
        ("benzinga-news", {"MSFT.NAS"}),
    ]
    assert sorted(result.sources_by_ticker) == ["AAPL.NAS", "MSFT.NAS"]
    assert result.source_issues == []
    assert result.system_issues == []
    assert result.summary["chain"] == ["finnhub", "benzinga-news"]
    assert result.summary["final"] == {
        "recommendable_covered": 1,
        "recommendable_total": 1,
        "watch_covered": 1,
        "watch_total": 1,
    }


def test_source_chain_records_provider_zero_results_per_remaining_ticker(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        source_chain,
        "load_ai_brief_sources",
        lambda **_kwargs: AiBriefSourceProviderResult(),
    )

    result = source_chain.load_ai_brief_source_chain(
        source_providers=("benzinga-news",),
        source_report_path=None,
        source_api_url=None,
        source_timeout_seconds=2.0,
        source_universe_tickers={"AAPL.NAS", "MSFT.NAS"},
        recommendable_tickers={"AAPL.NAS", "MSFT.NAS"},
        watch_tickers=set(),
        ticker_names={},
        now=dt.datetime(2026, 6, 15, 12, 0, tzinfo=dt.UTC),
    )

    assert {issue["ticker"] for issue in result.source_issues} == {
        "AAPL.NAS",
        "MSFT.NAS",
    }
    assert {issue["code"] for issue in result.source_issues} == {
        "benzinga_news_source_no_results"
    }
    providers = cast(list[dict[str, object]], result.summary["providers"])
    assert providers[0] == {
        "provider": "benzinga-news",
        "status": "success",
        "covered": 0,
        "total": 2,
    }


def test_source_chain_converts_http_429_to_provider_failure_summary(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[str] = []

    def fake_load(**kwargs: object) -> AiBriefSourceProviderResult:
        provider = str(kwargs["source_provider"])
        calls.append(provider)
        if provider == "polygon-news":
            raise AiBriefSourceProviderError(
                "Polygon News source request failed with HTTP 429"
            )
        return AiBriefSourceProviderResult(
            sources_by_ticker={"AAPL.NAS": [_source("AAPL.NAS", "fallback")]}
        )

    monkeypatch.setattr(source_chain, "load_ai_brief_sources", fake_load)

    result = source_chain.load_ai_brief_source_chain(
        source_providers=("polygon-news", "finnhub"),
        source_report_path=None,
        source_api_url=None,
        source_timeout_seconds=2.0,
        source_universe_tickers={"AAPL.NAS"},
        recommendable_tickers={"AAPL.NAS"},
        watch_tickers=set(),
        ticker_names={},
        now=dt.datetime(2026, 6, 15, 12, 0, tzinfo=dt.UTC),
    )

    assert calls == ["polygon-news", "finnhub"]
    assert result.system_issues[0]["code"] == "http_429"
    providers = cast(list[dict[str, object]], result.summary["providers"])
    assert providers[0] == {
        "provider": "polygon-news",
        "status": "failed",
        "code": "http_429",
        "covered": 0,
        "total": 1,
    }
    assert "AAPL.NAS" in result.sources_by_ticker
