"""Judge issuer announcements without a universe or network responses."""

import base64
import json
import subprocess
import unittest
from datetime import UTC, date, datetime
from unittest.mock import patch

import earnings as ir
from earnings import earnings, evaluate_articles
from test_single_run import reviewed_archive

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
    def setUp(self):
        review = patch.dict(ir.REVIEWED_ARCHIVES, reviewed_archive(SOURCE))
        review.start()
        self.addCleanup(review.stop)

    def test_empty_feed_body_reads_preserved_pdf_before_confirming(self):
        raw = b"%PDF-1.7 synthetic external response"

        def read(url):
            if url == SOURCE["listing_url"]:
                return '<script src="/q4Api.js"></script>'
            if url.endswith("/files/results.pdf"):
                return "data:application/pdf;base64," + base64.b64encode(raw).decode()
            if "GetPressReleaseListCount?" in url:
                return json.dumps({"GetPressReleaseListCountResult": 1})
            rows = (
                []
                if "pageNumber=1" in url
                else [
                    {
                        "LinkToDetailPage": "/files/results.pdf",
                        "Headline": ARTICLE["headline"],
                        "PressReleaseDate": ARTICLE["datePublished"],
                        "Body": "",
                    }
                ]
            )
            return json.dumps({"GetPressReleaseListResult": rows})

        def extract(command, **kwargs):
            self.assertEqual(kwargs["input"], raw)
            kwargs["stdout"].write(ARTICLE["articleBody"].encode())
            return subprocess.CompletedProcess(command, 0)

        with patch("subprocess.run", side_effect=extract):
            result = earnings(read, DAY, NOW, SOURCE)
        self.assertEqual(result["status"], "confirmed")
        self.assertEqual(result["date"], "2026-09-17")
        self.assertEqual(
            result["evidence_url"], "https://ir.example.com/files/results.pdf"
        )

    def test_reviewed_pdf_route_preserves_original_and_records_canonical_source(self):
        review = ir.REVIEWED_ARCHIVES[tuple(SOURCE.values())]
        review["document_routes"] = {
            "https://ir.example.com/files/": "https://cdn.example.com/issuer/files/"
        }
        requests = []

        def read(url):
            requests.append(url)
            if url == SOURCE["listing_url"]:
                return '<script src="/q4Api.js"></script>'
            if url == "https://cdn.example.com/issuer/files/results.pdf":
                return ARTICLE["articleBody"]
            if "GetPressReleaseListCount?" in url:
                return json.dumps({"GetPressReleaseListCountResult": 1})
            if "GetPressReleaseList?" in url:
                return json.dumps(
                    {
                        "GetPressReleaseListResult": []
                        if "pageNumber=1" in url
                        else [
                            {
                                "LinkToDetailPage": "/files/results.pdf",
                                "Headline": ARTICLE["headline"],
                                "PressReleaseDate": ARTICLE["datePublished"],
                                "Body": "",
                            }
                        ]
                    }
                )
            raise ir.DataError("redirect_not_allowed")

        result = earnings(read, DAY, NOW, SOURCE)
        self.assertEqual(result["status"], "confirmed")
        self.assertEqual(result["source"], "https://ir.example.com/files/results.pdf")
        self.assertEqual(
            result["evidence_url"], "https://cdn.example.com/issuer/files/results.pdf"
        )
        self.assertNotIn("https://ir.example.com/files/results.pdf", requests)

    def test_reviewed_document_route_rejects_path_escape_and_query(self):
        ir.REVIEWED_ARCHIVES[tuple(SOURCE.values())]["document_routes"] = {
            "https://ir.example.com/files/": "https://cdn.example.com/issuer/files/"
        }
        for suffix in (
            "%2e%2e/other.pdf",
            "results.pdf?destination=other",
            "a%5cb.pdf",
        ):
            with self.subTest(suffix=suffix):

                def read(url, suffix=suffix):
                    if url == SOURCE["listing_url"]:
                        return '<script src="/q4Api.js"></script>'
                    if "GetPressReleaseList?" in url:
                        return json.dumps(
                            {
                                "GetPressReleaseListResult": [
                                    {
                                        "LinkToDetailPage": "/files/" + suffix,
                                        "Headline": ARTICLE["headline"],
                                        "PressReleaseDate": ARTICLE["datePublished"],
                                        "Body": "",
                                    }
                                ]
                            }
                        )
                    self.fail("Untrusted document route was requested")

                result = earnings(read, DAY, NOW, SOURCE)
                self.assertEqual(result["reason"], "earnings_document_route_invalid")
                self.assertEqual(result["status"], "unconfirmed")

    def test_pdf_tool_failure_never_confirms_or_exposes_process_details(self):
        def read(url):
            if url == SOURCE["listing_url"]:
                return '<script src="/q4Api.js"></script>'
            if url.endswith("/files/results.pdf"):
                return (
                    "data:application/pdf;base64,"
                    + base64.b64encode(b"%PDF-1.7").decode()
                )
            return json.dumps(
                {
                    "GetPressReleaseListResult": [
                        {
                            "LinkToDetailPage": "/files/results.pdf",
                            "Headline": ARTICLE["headline"],
                            "PressReleaseDate": ARTICLE["datePublished"],
                            "Body": "",
                        }
                    ]
                }
            )

        for failure in (
            FileNotFoundError("private process detail"),
            subprocess.TimeoutExpired("pdftotext", 20),
        ):
            with (
                self.subTest(failure=type(failure).__name__),
                patch("subprocess.run", side_effect=failure),
            ):
                result = earnings(read, DAY, NOW, SOURCE)
            self.assertEqual(result["status"], "unconfirmed")
            self.assertEqual(result["reason"], "earnings_pdf_extraction_unavailable")
            self.assertNotIn("private", str(result))

    def test_q4_scope_requires_valid_count_and_current_issuer_review(self):
        def read(url):
            if url == SOURCE["listing_url"]:
                return '<script src="/q4Api.js"></script>'
            if url.endswith("/review"):
                return "Changed source page"
            if "GetPressReleaseListCount?" in url:
                return json.dumps({"GetPressReleaseListCountResult": count})
            rows = (
                []
                if "pageNumber=1" in url
                else [
                    {
                        "LinkToDetailPage": "/releases/results",
                        "Headline": ARTICLE["headline"],
                        "PressReleaseDate": ARTICLE["datePublished"],
                        "Body": ARTICLE["articleBody"],
                    }
                ]
            )
            return json.dumps({"GetPressReleaseListResult": rows})

        for count in (True, "1", -1):
            with self.subTest(count=count):
                result = earnings(read, DAY, NOW, SOURCE)
                self.assertEqual(result["status"], "unconfirmed")
                self.assertEqual(result["reason"], "earnings_scope_invalid_count")
        count = 1
        key = tuple(SOURCE[key] for key in ("company", "listing_url", "article_prefix"))
        original = ir.REVIEWED_ARCHIVES[key]
        for review, reason in [
            (
                original | {"reviewed_on": "2026-09-11"},
                "earnings_scope_unreviewed_source",
            ),
            (
                original | {"source": "https://ir.example.com/review"},
                "earnings_scope_review_changed",
            ),
        ]:
            with (
                self.subTest(reason=reason),
                patch.dict(ir.REVIEWED_ARCHIVES, {key: review}),
            ):
                result = earnings(read, DAY, NOW, SOURCE)
                self.assertEqual(result["status"], "unconfirmed")
                self.assertEqual(result["reason"], reason)

    def test_full_feed_keeps_issuer_document_announcements_outside_html_prefix(self):
        def read(url):
            if url == SOURCE["listing_url"]:
                return '<script src="/q4Api.js"></script>'
            if "GetPressReleaseListCount?" in url:
                return json.dumps({"GetPressReleaseListCountResult": 1})
            rows = (
                []
                if "pageNumber=1" in url
                else [
                    {
                        "LinkToDetailPage": "/files/results.pdf",
                        "Headline": ARTICLE["headline"],
                        "PressReleaseDate": ARTICLE["datePublished"],
                        "Body": ARTICLE["articleBody"],
                    }
                ]
            )
            return json.dumps({"GetPressReleaseListResult": rows})

        result = earnings(read, DAY, NOW, SOURCE)
        self.assertEqual(result["status"], "confirmed")
        self.assertEqual(result["scope_status"], "verified")
        self.assertEqual(result["source"], "https://ir.example.com/files/results.pdf")

    def test_q4_terminal_page_cannot_hide_missing_announcements(self):
        def read(url):
            if url == SOURCE["listing_url"]:
                return '<script src="/q4Api.js"></script>'
            if "GetPressReleaseListCount?" in url:
                return json.dumps({"GetPressReleaseListCountResult": 2})
            rows = (
                []
                if "pageNumber=1" in url
                else [
                    {
                        "LinkToDetailPage": "/releases/results",
                        "Headline": ARTICLE["headline"],
                        "PressReleaseDate": ARTICLE["datePublished"],
                        "Body": ARTICLE["articleBody"],
                    }
                ]
            )
            return json.dumps({"GetPressReleaseListResult": rows})

        result = earnings(read, DAY, NOW, SOURCE)
        self.assertEqual(result["status"], "unconfirmed")
        self.assertEqual(result["collection_status"], "complete")
        self.assertEqual(result["scope_status"], "unverified")
        self.assertEqual(result["reason"], "earnings_scope_count_mismatch")

    def test_empty_verified_archive_has_no_confirmed_next_date(self):
        def read(url):
            if url == SOURCE["listing_url"]:
                return '<script src="/q4Api.js"></script>'
            if "GetPressReleaseListCount?" in url:
                return json.dumps({"GetPressReleaseListCountResult": 0})
            return json.dumps({"GetPressReleaseListResult": []})

        result = earnings(read, DAY, NOW, SOURCE)
        self.assertEqual(result["status"], "unconfirmed")
        self.assertEqual(result["scope_status"], "verified")
        self.assertEqual(result["collection_status"], "complete")
        self.assertEqual(result["reason"], "next_confirmed_earnings_not_found")

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

    def test_tentative_body_never_confirms_a_release(self):
        result = evaluate_articles(
            [
                (
                    "release",
                    "feed",
                    ARTICLE
                    | {
                        "articleBody": ARTICLE["articleBody"]
                        + " This date is tentative."
                    },
                )
            ],
            DAY,
            NOW,
            SOURCE,
        )
        self.assertEqual(result["status"], "unconfirmed")
        self.assertEqual(result["reason"], "uncertain_earnings_announcement")

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
