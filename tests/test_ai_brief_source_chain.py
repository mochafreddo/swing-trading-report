from __future__ import annotations

import datetime as dt
from typing import cast

import pytest
import sab.ai_brief_source_chain as source_chain
from sab.ai_brief_sources import (
    MAX_SOURCES_PER_TICKER,
    AiBriefSourceProviderError,
    AiBriefSourceProviderResult,
    AiBriefSourceProviderTimeoutError,
)


def _source(ticker: str, suffix: str) -> dict[str, object]:
    return {
        "title": f"{ticker} source {suffix}",
        "url": f"https://news.example/{ticker}/{suffix}",
        "published_at": "2026-06-15T12:00:00+00:00",
    }


@pytest.mark.parametrize("source_providers", [(), ("none",)])
def test_source_chain_no_source_provider_returns_empty_result(
    source_providers: tuple[str, ...],
) -> None:
    result = source_chain.load_ai_brief_source_chain(
        source_providers=source_providers,
        source_report_path=None,
        source_api_url=None,
        source_timeout_seconds=2.0,
        source_universe_tickers={"AAPL.NAS"},
        recommendable_tickers={"AAPL.NAS"},
        watch_tickers={"MSFT.NAS"},
        ticker_names={},
        now=dt.datetime(2026, 6, 15, 12, 0, tzinfo=dt.UTC),
    )

    assert result.sources_by_ticker == {}
    assert result.source_issues == []
    assert result.system_issues == []
    assert result.summary == {
        "chain": ["none"],
        "providers": [],
        "final": {
            "recommendable_covered": 0,
            "recommendable_total": 1,
            "watch_covered": 0,
            "watch_total": 1,
        },
    }


def test_source_chain_accepts_string_provider_as_single_provider(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[str] = []

    def fake_load(**kwargs: object) -> AiBriefSourceProviderResult:
        provider = str(kwargs["source_provider"])
        calls.append(provider)
        return AiBriefSourceProviderResult(
            sources_by_ticker={"AAPL.NAS": [_source("AAPL.NAS", provider)]}
        )

    monkeypatch.setattr(source_chain, "load_ai_brief_sources", fake_load)

    result = source_chain.load_ai_brief_source_chain(
        source_providers="finnhub",
        source_report_path=None,
        source_api_url=None,
        source_timeout_seconds=2.0,
        source_universe_tickers={"AAPL.NAS"},
        recommendable_tickers={"AAPL.NAS"},
        watch_tickers=set(),
        ticker_names={},
        now=dt.datetime(2026, 6, 15, 12, 0, tzinfo=dt.UTC),
    )

    assert calls == ["finnhub"]
    assert result.summary["chain"] == ["finnhub"]
    assert result.sources_by_ticker == {"AAPL.NAS": [_source("AAPL.NAS", "finnhub")]}


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
                sources_by_ticker={
                    "AAPL.NAS": [_source("AAPL.NAS", "finnhub")],
                    "MSFT.NAS": [_source("MSFT.NAS", "finnhub")],
                }
            )
        if provider == "benzinga-news":
            return AiBriefSourceProviderResult(
                sources_by_ticker={
                    "AAPL.NAS": [_source("AAPL.NAS", "benzinga")],
                    "MSFT.NAS": [_source("MSFT.NAS", "benzinga")],
                }
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
        ("benzinga-news", {"AAPL.NAS", "MSFT.NAS"}),
    ]
    assert sorted(result.sources_by_ticker) == ["AAPL.NAS", "MSFT.NAS"]
    assert len(result.sources_by_ticker["AAPL.NAS"]) == 2
    assert len(result.sources_by_ticker["MSFT.NAS"]) == 2
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


def test_source_chain_preserves_zero_result_issue_after_later_coverage(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fake_load(**kwargs: object) -> AiBriefSourceProviderResult:
        provider = str(kwargs["source_provider"])
        if provider == "finnhub":
            return AiBriefSourceProviderResult()
        return AiBriefSourceProviderResult(
            sources_by_ticker={"AAPL.NAS": [_source("AAPL.NAS", "fallback")]}
        )

    monkeypatch.setattr(source_chain, "load_ai_brief_sources", fake_load)

    result = source_chain.load_ai_brief_source_chain(
        source_providers=("finnhub", "polygon-news"),
        source_report_path=None,
        source_api_url=None,
        source_timeout_seconds=2.0,
        source_universe_tickers={"AAPL.NAS"},
        recommendable_tickers={"AAPL.NAS"},
        watch_tickers=set(),
        ticker_names={},
        now=dt.datetime(2026, 6, 15, 12, 0, tzinfo=dt.UTC),
    )

    assert result.source_issues == [
        {
            "ticker": "AAPL.NAS",
            "code": "finnhub_source_no_results",
            "severity": "WARN",
            "message": "finnhub returned no usable sources for AAPL.NAS",
        }
    ]
    assert "AAPL.NAS" in result.sources_by_ticker


def test_source_chain_ignores_unrequested_provider_tickers(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    provider_issue: dict[str, object] = {
        "ticker": "TSLA.NAS",
        "code": "provider_unexpected_ticker",
        "severity": "WARN",
        "message": "provider returned an unexpected ticker",
    }

    def fake_load(**_kwargs: object) -> AiBriefSourceProviderResult:
        return AiBriefSourceProviderResult(
            sources_by_ticker={
                "AAPL.NAS": [_source("AAPL.NAS", "expected")],
                "TSLA.NAS": [_source("TSLA.NAS", "unexpected")],
            },
            source_issues=[provider_issue],
        )

    monkeypatch.setattr(source_chain, "load_ai_brief_sources", fake_load)

    result = source_chain.load_ai_brief_source_chain(
        source_providers=("finnhub",),
        source_report_path=None,
        source_api_url=None,
        source_timeout_seconds=2.0,
        source_universe_tickers={"AAPL.NAS"},
        recommendable_tickers={"AAPL.NAS"},
        watch_tickers=set(),
        ticker_names={},
        now=dt.datetime(2026, 6, 15, 12, 0, tzinfo=dt.UTC),
    )

    assert sorted(result.sources_by_ticker) == ["AAPL.NAS"]
    assert result.source_issues == [provider_issue]


def test_source_chain_dedupes_duplicate_urls_across_providers(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fake_load(**_kwargs: object) -> AiBriefSourceProviderResult:
        return AiBriefSourceProviderResult(
            sources_by_ticker={"AAPL.NAS": [_source("AAPL.NAS", "shared")]}
        )

    monkeypatch.setattr(source_chain, "load_ai_brief_sources", fake_load)

    result = source_chain.load_ai_brief_source_chain(
        source_providers=("finnhub", "benzinga-news"),
        source_report_path=None,
        source_api_url=None,
        source_timeout_seconds=2.0,
        source_universe_tickers={"AAPL.NAS"},
        recommendable_tickers={"AAPL.NAS"},
        watch_tickers=set(),
        ticker_names={},
        now=dt.datetime(2026, 6, 15, 12, 0, tzinfo=dt.UTC),
    )

    assert result.sources_by_ticker["AAPL.NAS"] == [_source("AAPL.NAS", "shared")]


def test_source_chain_duplicate_only_provider_counts_as_no_result(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fake_load(**_kwargs: object) -> AiBriefSourceProviderResult:
        return AiBriefSourceProviderResult(
            sources_by_ticker={"AAPL.NAS": [_source("AAPL.NAS", "shared")]}
        )

    monkeypatch.setattr(source_chain, "load_ai_brief_sources", fake_load)

    result = source_chain.load_ai_brief_source_chain(
        source_providers=("finnhub", "benzinga-news"),
        source_report_path=None,
        source_api_url=None,
        source_timeout_seconds=2.0,
        source_universe_tickers={"AAPL.NAS"},
        recommendable_tickers={"AAPL.NAS"},
        watch_tickers=set(),
        ticker_names={},
        now=dt.datetime(2026, 6, 15, 12, 0, tzinfo=dt.UTC),
    )

    providers = cast(list[dict[str, object]], result.summary["providers"])
    assert providers[1] == {
        "provider": "benzinga-news",
        "status": "success",
        "covered": 0,
        "total": 1,
    }
    assert result.source_issues == [
        {
            "ticker": "AAPL.NAS",
            "code": "benzinga_news_source_no_results",
            "severity": "WARN",
            "message": "benzinga-news returned no usable sources for AAPL.NAS",
        }
    ]


def test_source_chain_skips_later_provider_after_ticker_reaches_cap(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[tuple[str, set[str]]] = []

    def fake_load(**kwargs: object) -> AiBriefSourceProviderResult:
        provider = str(kwargs["source_provider"])
        tickers = set(cast(set[str], kwargs["eligible_tickers"]))
        calls.append((provider, tickers))
        return AiBriefSourceProviderResult(
            sources_by_ticker={
                "AAPL.NAS": [
                    _source("AAPL.NAS", f"finnhub-{idx}")
                    for idx in range(MAX_SOURCES_PER_TICKER)
                ]
            }
        )

    monkeypatch.setattr(source_chain, "load_ai_brief_sources", fake_load)

    result = source_chain.load_ai_brief_source_chain(
        source_providers=("finnhub", "benzinga-news"),
        source_report_path=None,
        source_api_url=None,
        source_timeout_seconds=2.0,
        source_universe_tickers={"AAPL.NAS"},
        recommendable_tickers={"AAPL.NAS"},
        watch_tickers=set(),
        ticker_names={},
        now=dt.datetime(2026, 6, 15, 12, 0, tzinfo=dt.UTC),
    )

    providers = cast(list[dict[str, object]], result.summary["providers"])
    assert calls == [("finnhub", {"AAPL.NAS"})]
    assert providers[1] == {
        "provider": "benzinga-news",
        "status": "skipped",
        "covered": 0,
        "total": 0,
    }
    assert len(result.sources_by_ticker["AAPL.NAS"]) == MAX_SOURCES_PER_TICKER


def test_source_chain_records_cap_issue_when_later_provider_overfills_remaining_slot(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    first_provider_sources = [
        _source("AAPL.NAS", f"finnhub-{idx}")
        for idx in range(MAX_SOURCES_PER_TICKER - 1)
    ]
    second_provider_sources = [
        _source("AAPL.NAS", "benzinga-extra-1"),
        _source("AAPL.NAS", "benzinga-extra-2"),
    ]

    def fake_load(**kwargs: object) -> AiBriefSourceProviderResult:
        provider = str(kwargs["source_provider"])
        if provider == "finnhub":
            return AiBriefSourceProviderResult(
                sources_by_ticker={"AAPL.NAS": first_provider_sources}
            )
        return AiBriefSourceProviderResult(
            sources_by_ticker={"AAPL.NAS": second_provider_sources}
        )

    monkeypatch.setattr(source_chain, "load_ai_brief_sources", fake_load)

    result = source_chain.load_ai_brief_source_chain(
        source_providers=("finnhub", "benzinga-news"),
        source_report_path=None,
        source_api_url=None,
        source_timeout_seconds=2.0,
        source_universe_tickers={"AAPL.NAS"},
        recommendable_tickers={"AAPL.NAS"},
        watch_tickers=set(),
        ticker_names={},
        now=dt.datetime(2026, 6, 15, 12, 0, tzinfo=dt.UTC),
    )

    assert len(result.sources_by_ticker["AAPL.NAS"]) == MAX_SOURCES_PER_TICKER
    assert result.sources_by_ticker["AAPL.NAS"] == [
        *first_provider_sources,
        second_provider_sources[0],
    ]
    assert [issue["code"] for issue in result.source_issues] == [
        "source_chain_cap_exceeded"
    ]
    providers = cast(list[dict[str, object]], result.summary["providers"])
    assert providers[1] == {
        "provider": "benzinga-news",
        "status": "success",
        "covered": 1,
        "total": 1,
    }


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        (None, ()),
        ("", ()),
        ("   ", ()),
        (" Finnhub, BENZINGA-news ", ("finnhub", "benzinga-news")),
    ],
)
def test_parse_source_provider_chain_normalizes_successful_values(
    value: str | None,
    expected: tuple[str, ...],
) -> None:
    assert source_chain.parse_source_provider_chain(value) == expected


@pytest.mark.parametrize(
    "value",
    [
        "finnhub,finnhub",
        "none,finnhub",
        "polygon-news,none",
        "typo-provider",
    ],
)
def test_parse_source_provider_chain_rejects_invalid_chains(value: str) -> None:
    with pytest.raises(ValueError):
        source_chain.parse_source_provider_chain(value)


def test_source_chain_rejects_none_combined_with_providers() -> None:
    with pytest.raises(ValueError, match="cannot combine none"):
        source_chain.load_ai_brief_source_chain(
            source_providers=("none", "finnhub"),
            source_report_path=None,
            source_api_url=None,
            source_timeout_seconds=2.0,
            source_universe_tickers={"AAPL.NAS"},
            recommendable_tickers={"AAPL.NAS"},
            watch_tickers=set(),
            ticker_names={},
            now=dt.datetime(2026, 6, 15, 12, 0, tzinfo=dt.UTC),
        )


def test_source_chain_rejects_duplicate_providers() -> None:
    with pytest.raises(ValueError, match="duplicate"):
        source_chain.load_ai_brief_source_chain(
            source_providers=("finnhub", "finnhub"),
            source_report_path=None,
            source_api_url=None,
            source_timeout_seconds=2.0,
            source_universe_tickers={"AAPL.NAS"},
            recommendable_tickers={"AAPL.NAS"},
            watch_tickers=set(),
            ticker_names={},
            now=dt.datetime(2026, 6, 15, 12, 0, tzinfo=dt.UTC),
        )


def test_source_chain_rejects_unsupported_provider() -> None:
    with pytest.raises(ValueError, match="unsupported"):
        source_chain.load_ai_brief_source_chain(
            source_providers=("typo-provider",),
            source_report_path=None,
            source_api_url=None,
            source_timeout_seconds=2.0,
            source_universe_tickers={"AAPL.NAS"},
            recommendable_tickers={"AAPL.NAS"},
            watch_tickers=set(),
            ticker_names={},
            now=dt.datetime(2026, 6, 15, 12, 0, tzinfo=dt.UTC),
        )


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


def test_source_chain_preserves_non_429_provider_failure_code(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fail_load(**_kwargs: object) -> AiBriefSourceProviderResult:
        raise AiBriefSourceProviderTimeoutError("source API request timed out")

    monkeypatch.setattr(source_chain, "load_ai_brief_sources", fail_load)

    result = source_chain.load_ai_brief_source_chain(
        source_providers=("http-json",),
        source_report_path=None,
        source_api_url="https://source.example/api",
        source_timeout_seconds=2.0,
        source_universe_tickers={"AAPL.NAS"},
        recommendable_tickers={"AAPL.NAS"},
        watch_tickers=set(),
        ticker_names={},
        now=dt.datetime(2026, 6, 15, 12, 0, tzinfo=dt.UTC),
    )

    assert result.system_issues[0]["code"] == "source_provider_timeout"
    providers = cast(list[dict[str, object]], result.summary["providers"])
    assert providers[0] == {
        "provider": "http-json",
        "status": "failed",
        "code": "source_provider_timeout",
        "covered": 0,
        "total": 1,
    }
