from __future__ import annotations

import datetime as dt

from sab.article_reader import (
    ArticleReaderSettings,
    ArticleReadResult,
    article_read_summary,
    enrich_sources_with_article_reads,
    extract_bounded_excerpt,
    verify_article_text,
)

NOW = dt.datetime(2026, 6, 24, 9, 35, tzinfo=dt.UTC)


def test_article_read_result_serializes_without_empty_optional_values() -> None:
    result = ArticleReadResult(
        status="verified",
        tier="article_verified",
        checked_at=NOW,
        reader="lightpanda",
        excerpt="Apple expanded AI infrastructure capacity.",
        matched_terms=("AAPL", "Apple"),
        issue_code=None,
    )

    assert result.to_dict() == {
        "status": "verified",
        "tier": "article_verified",
        "checked_at": "2026-06-24T09:35:00+00:00",
        "reader": "lightpanda",
        "excerpt": "Apple expanded AI infrastructure capacity.",
        "matched_terms": ["AAPL", "Apple"],
        "issue_code": None,
    }


def test_extract_bounded_excerpt_collapses_whitespace_and_bounds_length() -> None:
    text = "  Apple\n\nexpanded   AI capacity for its device roadmap.  "

    excerpt = extract_bounded_excerpt(text, max_chars=32)

    assert excerpt == "Apple expanded AI capacity fo..."
    assert len(excerpt) <= 32


def test_verify_article_text_returns_verified_for_ticker_or_company_match() -> None:
    result = verify_article_text(
        "Apple said AAPL infrastructure spending increased.",
        ticker="AAPL.NAS",
        company_terms=("Apple",),
    )

    assert result.tier == "article_verified"
    assert result.matched_terms == ("AAPL", "Apple")


def test_verify_article_text_returns_accessed_when_no_terms_match() -> None:
    result = verify_article_text(
        "The market opened higher after broad technology gains.",
        ticker="AAPL.NAS",
        company_terms=("Apple",),
    )

    assert result.tier == "article_accessed"
    assert result.matched_terms == ()


def test_article_read_summary_counts_statuses_and_tiers() -> None:
    rows: dict[str, list[dict[str, object]]] = {
        "AAPL.NAS": [
            {
                "title": "AAPL source",
                "url": "https://news.example/aapl",
                "published_at": "2026-06-24T09:00:00+00:00",
                "article_read": {
                    "status": "verified",
                    "tier": "article_verified",
                    "checked_at": "2026-06-24T09:35:00+00:00",
                    "reader": "lightpanda",
                    "excerpt": "Apple expanded capacity.",
                    "matched_terms": ["AAPL", "Apple"],
                    "issue_code": None,
                },
            }
        ],
        "MSFT.NAS": [
            {
                "title": "MSFT source",
                "url": "https://news.example/msft",
                "published_at": "2026-06-24T09:00:00+00:00",
                "article_read": {
                    "status": "blocked",
                    "tier": "metadata_backed",
                    "checked_at": "2026-06-24T09:35:00+00:00",
                    "reader": "lightpanda",
                    "excerpt": "",
                    "matched_terms": [],
                    "issue_code": "article_access_blocked",
                },
            }
        ],
    }

    assert article_read_summary(rows) == {
        "article_read_attempted_count": 2,
        "article_accessed_count": 0,
        "article_verified_count": 1,
        "article_read_issue_count": 1,
    }


def test_article_reader_settings_disabled_by_default() -> None:
    settings = ArticleReaderSettings()

    assert settings.reader == "none"
    assert settings.enabled is False


class _FakeLightpandaRunner:
    def __init__(self, responses: dict[str, tuple[int, str, str]]) -> None:
        self.responses = responses
        self.calls: list[tuple[str, float]] = []

    def __call__(self, url: str, timeout_seconds: float) -> tuple[int, str, str]:
        self.calls.append((url, timeout_seconds))
        return self.responses[url]


def test_enrich_sources_marks_verified_from_lightpanda_markdown() -> None:
    sources: dict[str, list[dict[str, object]]] = {
        "AAPL.NAS": [
            {
                "title": "Apple source",
                "url": "https://news.example/aapl",
                "published_at": "2026-06-24T09:00:00+00:00",
            }
        ]
    }
    runner = _FakeLightpandaRunner(
        {"https://news.example/aapl": (0, "# Apple\nAAPL expanded AI capacity.", "")}
    )

    enriched, issues = enrich_sources_with_article_reads(
        sources,
        ticker_names={"AAPL.NAS": "Apple"},
        settings=ArticleReaderSettings(reader="lightpanda", max_urls=8),
        now=NOW,
        lightpanda_runner=runner,
    )

    article_read = enriched["AAPL.NAS"][0]["article_read"]
    assert isinstance(article_read, dict)
    assert issues == []
    assert article_read["status"] == "verified"
    assert article_read["tier"] == "article_verified"
    assert runner.calls == [("https://news.example/aapl", 8.0)]


def test_enrich_sources_preserves_rows_and_records_blocked_issue() -> None:
    sources: dict[str, list[dict[str, object]]] = {
        "MSFT.NAS": [
            {
                "title": "MSFT source",
                "url": "https://news.example/msft",
                "published_at": "2026-06-24T09:00:00+00:00",
            }
        ]
    }
    runner = _FakeLightpandaRunner(
        {"https://news.example/msft": (1, "", "HTTP 403 forbidden")}
    )

    enriched, issues = enrich_sources_with_article_reads(
        sources,
        ticker_names={"MSFT.NAS": "Microsoft"},
        settings=ArticleReaderSettings(reader="lightpanda", max_urls=8),
        now=NOW,
        lightpanda_runner=runner,
    )

    article_read = enriched["MSFT.NAS"][0]["article_read"]
    assert isinstance(article_read, dict)
    assert enriched["MSFT.NAS"][0]["url"] == "https://news.example/msft"
    assert article_read["status"] == "blocked"
    assert article_read["issue_code"] == "article_access_blocked"
    assert issues == [
        {
            "ticker": "MSFT.NAS",
            "code": "article_access_blocked",
            "severity": "WARN",
            "message": "article reader could not access source URL",
        }
    ]


def test_enrich_sources_marks_remaining_rows_not_attempted_after_cap() -> None:
    sources: dict[str, list[dict[str, object]]] = {
        "AAPL.NAS": [
            {
                "title": "AAPL source 1",
                "url": "https://news.example/aapl-1",
                "published_at": "2026-06-24T09:00:00+00:00",
            },
            {
                "title": "AAPL source 2",
                "url": "https://news.example/aapl-2",
                "published_at": "2026-06-24T09:00:00+00:00",
            },
        ]
    }
    runner = _FakeLightpandaRunner(
        {"https://news.example/aapl-1": (0, "Apple mentions AAPL.", "")}
    )

    enriched, issues = enrich_sources_with_article_reads(
        sources,
        ticker_names={"AAPL.NAS": "Apple"},
        settings=ArticleReaderSettings(reader="lightpanda", max_urls=1),
        now=NOW,
        lightpanda_runner=runner,
    )

    first_read = enriched["AAPL.NAS"][0]["article_read"]
    second_read = enriched["AAPL.NAS"][1]["article_read"]
    assert isinstance(first_read, dict)
    assert isinstance(second_read, dict)
    assert issues == []
    assert first_read["status"] == "verified"
    assert second_read["status"] == "not_attempted"
    assert runner.calls == [("https://news.example/aapl-1", 8.0)]
