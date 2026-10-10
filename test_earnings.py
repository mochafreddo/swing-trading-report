"""Judge issuer announcements without a universe or network responses."""

import json
import unittest
from datetime import UTC, date, datetime

from earnings import earnings, evaluate_articles

DAY = date(2026, 9, 10)
NOW = datetime(2026, 9, 10, 12, tzinfo=UTC)
SOURCE = {
    "company": "Example Corporation",
    "listing_url": "https://ir.example.com/news",
    "article_prefix": "https://ir.example.com/releases/",
}
ARTICLE = {
    "headline": "Example Corporation announces quarterly results schedule",
    "datePublished": "2026-09-08T10:00:00Z",
    "articleBody": "We will release financial results on September 17, 2026 and host a conference call on September 18, 2026.",
}


class EarningsEvidenceTests(unittest.TestCase):
    def test_release_date_preserves_source_and_publication_precision(self):
        result = evaluate_articles(
            [
                (
                    "https://ir.example.com/releases/results",
                    "https://ir.example.com/feed",
                    ARTICLE,
                )
            ],
            DAY,
            NOW,
            SOURCE,
        )

        self.assertEqual(
            result,
            {
                "status": "confirmed",
                "date": "2026-09-17",
                "source": "https://ir.example.com/releases/results",
                "published_at": "2026-09-08T10:00:00+00:00",
                "publication_precision": "timestamp",
                "evidence_url": "https://ir.example.com/feed",
                "title": "Example Corporation announces quarterly results schedule",
                "session": "unknown",
                "collection_status": "complete",
            },
        )

    def test_conflicting_announcements_do_not_choose_a_release(self):
        result = evaluate_articles(
            [
                ("first", "feed", ARTICLE),
                (
                    "second",
                    "feed",
                    ARTICLE
                    | {"articleBody": "We will release results on September 21, 2026."},
                ),
            ],
            DAY,
            NOW,
            SOURCE,
        )
        self.assertEqual(result["status"], "unconfirmed")
        self.assertEqual(result["reason"], "earnings_dates_conflict")

    def test_newer_postponement_overrides_confirmed_release(self):
        result = evaluate_articles(
            [
                ("release", "feed", ARTICLE),
                (
                    "change",
                    "feed",
                    {
                        "headline": "Example Corporation updates quarterly results",
                        "datePublished": "2026-09-09T10:00:00Z",
                        "articleBody": "The earnings announcement has been postponed.",
                    },
                ),
            ],
            DAY,
            NOW,
            SOURCE,
        )
        self.assertEqual(result["status"], "unconfirmed")
        self.assertEqual(result["reason"], "earnings_schedule_changed")
        self.assertEqual(result["source"], "change")

    def test_date_only_publication_is_held_on_collection_day(self):
        result = evaluate_articles(
            [("release", "feed", ARTICLE | {"datePublished": "2026-09-10"})],
            DAY,
            NOW,
            SOURCE,
        )
        self.assertEqual(result["reason"], "publication_time_unverified")

    def test_incomplete_listing_does_not_confirm_an_available_announcement(self):
        body = (
            '<a href="/releases/results">Results</a><a rel="next" href="/news">Next</a>'
        )
        pages = {
            SOURCE["listing_url"]: body,
            "https://ir.example.com/releases/results": '<script type="application/ld+json">'
            + json.dumps(ARTICLE | {"@type": "NewsArticle"})
            + "</script>",
        }
        result = earnings(pages.__getitem__, DAY, NOW, SOURCE)
        self.assertEqual(result["status"], "unconfirmed")
        self.assertEqual(result["collection_status"], "incomplete")
