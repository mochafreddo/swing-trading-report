from __future__ import annotations

import datetime as dt

from sab.article_reader import (
    ArticleReaderSettings,
    ArticleReadResult,
    article_read_summary,
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
