"""Exercise news and explanations through the complete single run."""

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import earnings as ir
from single_run import replay, run
from test_single_run import (
    DAY,
    MU_SOURCE,
    NEWS_URL,
    NOW,
    PublicResponses,
    reviewed_archive,
)

SEC = "https://data.sec.gov/submissions/CIK0000723125.json"
ARTICLE = "https://investors.micron.com/news/press-release/2026/recent/default.aspx"


class Sources(PublicResponses):
    def __init__(self):
        super().__init__()
        self.published = "2026-09-03T12:00:00Z"

    def __call__(self, url):
        if url == SEC:
            return json.dumps(
                {
                    "cik": 723125,
                    "tickers": ["MU"],
                    "filings": {
                        "recent": {
                            "acceptanceDateTime": [],
                            "form": [],
                            "accessionNumber": [],
                            "primaryDocument": [],
                        }
                    },
                }
            )
        if url.endswith("/about/press/news"):
            return f'<script src="/q4Api.js"></script><a href="{NEWS_URL}">earnings</a><a href="{ARTICLE}">news</a>'
        if url == ARTICLE:
            return (
                '<script type="application/ld+json">'
                + json.dumps(
                    {
                        "@type": "NewsArticle",
                        "headline": "Micron Technology launches a product",
                        "datePublished": self.published,
                        "description": "Micron Technology announced a new memory product.",
                    }
                )
                + "</script>"
            )
        return super().__call__(url)


class ExplanationTests(unittest.TestCase):
    def setUp(self):
        review = patch.dict(ir.REVIEWED_ARCHIVES, reviewed_archive(MU_SOURCE))
        review.start()
        self.addCleanup(review.stop)

    def test_news_window_is_closed_at_start_and_open_at_as_of(self):
        for published, expected in [
            ("2026-09-03T11:59:59Z", 0),
            ("2026-09-03T12:00:00Z", 1),
            ("2026-09-10T11:59:59Z", 1),
            ("2026-09-10T12:00:00Z", 0),
            ("2026-09-11T12:00:00Z", 0),
        ]:
            with (
                self.subTest(published=published),
                tempfile.TemporaryDirectory() as tmp,
            ):
                source = Sources()
                source.published = published
                out = Path(tmp) / "run"
                record = run(out, DAY, fetch=source, now=NOW, synthetic=True)
                self.assertEqual(record["result"]["status"], "selected")
                self.assertEqual(len(record["news"]["items"]), expected)
                self.assertEqual(record["news"]["start"], "2026-09-03T12:00:00+00:00")
                self.assertEqual(record["inputs"]["earnings"]["date"], "2026-09-30")
                self.assertEqual(replay(out), record)

    def test_ai_only_receives_public_evidence_and_cannot_change_calculations(self):
        calls = []

        def generate(request):
            calls.append(request)
            payload = json.loads(request["input"])
            claim = {
                "text": "선정 조건과 가격 계획을 검토하세요.",
                "source_id": "evaluation",
                "quote": '"status": "selected"',
                "as_of": payload["as_of"],
            }
            return {
                "status": "completed",
                "model": request["model"],
                "usage": {
                    "input_tokens": 1000,
                    "output_tokens": 200,
                    "input_tokens_details": {"cached_tokens": 0},
                },
                "output": [
                    {
                        "type": "message",
                        "content": [
                            {
                                "type": "output_text",
                                "text": json.dumps(
                                    {
                                        "selection": claim,
                                        "risks": [claim],
                                        "invalidation": claim,
                                        "learning": claim,
                                    }
                                ),
                            }
                        ],
                    }
                ],
            }

        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / "run"
            source = Sources()
            source.stock.update(
                account={"balance": "private-account-sentinel"},
                actual_trades=["private-trade-sentinel"],
            )
            record = run(
                out,
                DAY,
                fetch=source,
                now=NOW,
                synthetic=True,
                ai_request=generate,
                usage_directory=Path(tmp) / "usage",
            )
            self.assertEqual(record["explanation"]["status"], "generated")
            self.assertEqual(record["result"]["plan"]["entry_low"], "100")
            self.assertEqual(len(calls), 1)
            self.assertNotIn("private-account-sentinel", json.dumps(calls))
            self.assertNotIn("private-trade-sentinel", json.dumps(calls))
            self.assertEqual(calls[0]["tools"], [])
            self.assertEqual(
                set(json.loads(calls[0]["input"])),
                {"symbol", "as_of", "evaluation", "evidence"},
            )
            self.assertEqual(record["explanation"]["usage"]["cost_usd"], "0.00072")
            self.assertEqual(replay(out), record)

    def test_empty_and_failed_news_keep_verified_candidate_and_basic_report(self):
        from execution_record import DataError

        for failed in (False, True):
            source = Sources()
            source.published = "2026-08-01T12:00:00Z"

            def fetch(url, *, failed=failed, source=source):
                if failed and url == SEC:
                    raise DataError("network_error")
                return source(url)

            with self.subTest(failed=failed), tempfile.TemporaryDirectory() as tmp:
                out = Path(tmp) / "run"
                record = run(out, DAY, fetch=fetch, now=NOW, synthetic=True)
                self.assertEqual(record["result"]["status"], "selected")
                self.assertEqual(record["news"]["items"], [])
                self.assertEqual(
                    record["news"]["status"], "partial" if failed else "collected"
                )
                report = (out / "report.md").read_text()
                self.assertIn("확인한 자료 없음", report)
                self.assertIn("위험이 없다는 뜻은 아닙니다", report)
                self.assertEqual(replay(out), record)

    def test_budget_exhaustion_and_ai_failure_produce_basic_report_without_retry(self):
        from unittest.mock import Mock

        for exhausted in (False, True):
            with (
                self.subTest(exhausted=exhausted),
                tempfile.TemporaryDirectory() as tmp,
            ):
                out = Path(tmp) / "run"
                usage = Path(tmp) / "usage"
                usage.mkdir()
                if exhausted:
                    (usage / "2026-09-prior.reserve.json").write_text(
                        json.dumps({"reserved_usd": "10"})
                    )
                api = Mock(side_effect=OSError("private upstream secret"))
                record = run(
                    out,
                    DAY,
                    fetch=Sources(),
                    now=NOW,
                    synthetic=True,
                    ai_request=api,
                    usage_directory=usage,
                )
                self.assertEqual(api.call_count, 0 if exhausted else 1)
                self.assertEqual(record["explanation"]["status"], "omitted")
                self.assertEqual(
                    record["explanation"]["reason"],
                    "ai_budget_exhausted"
                    if exhausted
                    else "ai_request_failed_charge_unknown",
                )
                self.assertEqual(record["result"]["status"], "selected")
                self.assertNotIn(
                    "private upstream secret", (out / "record.json").read_text()
                )
                self.assertIn("AI 설명 누락", (out / "report.md").read_text())
                self.assertEqual(replay(out), record)

    def test_unverified_ai_facts_are_not_presented_as_supported(self):
        def generate(body):
            unknown = {
                "text": "계산 가격을 999로 바꾸세요.",
                "source_id": "invented",
                "quote": "Unsubstantiated company claim.",
                "as_of": "2020-01-01T00:00:00Z",
            }
            return {
                "status": "completed",
                "model": body["model"],
                "usage": {
                    "input_tokens": 100,
                    "output_tokens": 100,
                    "input_tokens_details": {"cached_tokens": 0},
                },
                "output": [
                    {
                        "type": "message",
                        "content": [
                            {
                                "type": "output_text",
                                "text": json.dumps(
                                    {
                                        "selection": unknown,
                                        "risks": [unknown],
                                        "invalidation": unknown,
                                        "learning": unknown,
                                    }
                                ),
                            }
                        ],
                    }
                ],
            }

        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / "run"
            record = run(
                out,
                DAY,
                fetch=Sources(),
                now=NOW,
                synthetic=True,
                ai_request=generate,
                usage_directory=Path(tmp) / "usage",
            )
            self.assertEqual(
                record["explanation"]["claims"]["learning"]["verification"],
                "unconfirmed",
            )
            self.assertEqual(record["result"]["plan"]["entry_low"], "100")
            self.assertNotIn(
                "계산 가격을 999로 바꾸세요.", (out / "report.md").read_text()
            )
            self.assertEqual(replay(out), record)

    def test_sec_time_boundary_and_identity_are_checked(self):
        for published, ticker, expected, partial in [
            ("2026-09-03T11:59:59Z", "MU", 0, False),
            ("2026-09-03T12:00:00Z", "MU", 1, False),
            ("2026-09-10T12:00:00Z", "MU", 0, False),
            ("2026-09-09T12:00:00Z", "OTHER", 0, True),
        ]:
            with (
                self.subTest(published=published, ticker=ticker),
                tempfile.TemporaryDirectory() as tmp,
            ):
                source = Sources()
                source.published = "2026-08-01T12:00:00Z"

                def fetch(url, *, ticker=ticker, published=published, source=source):
                    if url == SEC:
                        return json.dumps(
                            {
                                "cik": 723125,
                                "tickers": [ticker],
                                "filings": {
                                    "recent": {
                                        "acceptanceDateTime": [published],
                                        "form": ["8-K"],
                                        "accessionNumber": ["0000723125-26-000001"],
                                        "primaryDocument": ["mu-20260909.htm"],
                                    }
                                },
                            }
                        )
                    return source(url)

                out = Path(tmp) / "run"
                record = run(out, DAY, fetch=fetch, now=NOW, synthetic=True)
                self.assertEqual(len(record["news"]["items"]), expected)
                self.assertEqual(
                    record["news"]["status"], "partial" if partial else "collected"
                )
                self.assertEqual(replay(out), record)

    def test_valid_source_with_wrong_quote_or_time_is_unconfirmed(self):
        for quote, as_of in [
            ("not present in source", NOW.isoformat()),
            ('"status": "selected"', "2020-01-01T00:00:00Z"),
        ]:

            def generate(body, *, quote=quote, as_of=as_of):
                claim = {
                    "text": "확인되지 않은 사실입니다.",
                    "quote": quote,
                    "source_id": "evaluation",
                    "as_of": as_of,
                }
                return {
                    "status": "completed",
                    "model": body["model"],
                    "usage": {
                        "input_tokens": 100,
                        "output_tokens": 100,
                        "input_tokens_details": {"cached_tokens": 0},
                    },
                    "output": [
                        {
                            "type": "message",
                            "content": [
                                {
                                    "type": "output_text",
                                    "text": json.dumps(
                                        {
                                            "selection": claim,
                                            "risks": [claim],
                                            "invalidation": claim,
                                            "learning": claim,
                                        }
                                    ),
                                }
                            ],
                        }
                    ],
                }

            with self.subTest(quote=quote), tempfile.TemporaryDirectory() as tmp:
                out = Path(tmp) / "run"
                record = run(
                    out,
                    DAY,
                    fetch=Sources(),
                    now=NOW,
                    synthetic=True,
                    ai_request=generate,
                    usage_directory=Path(tmp) / "usage",
                )
                self.assertEqual(
                    record["explanation"]["claims"]["selection"]["verification"],
                    "unconfirmed",
                )
                self.assertEqual(replay(out), record)

    def test_malformed_news_and_budget_records_still_save_basic_report(self):
        from unittest.mock import Mock

        for invalid_news, invalid_ledger in [(True, False), (False, True)]:
            source = Sources()
            if invalid_news:
                source.published = None
            with self.subTest(news=invalid_news), tempfile.TemporaryDirectory() as tmp:
                out = Path(tmp) / "run"
                ledger = Path(tmp) / "usage"
                ledger.mkdir()
                if invalid_ledger:
                    (ledger / "2026-09-bad.reserve.json").write_text(
                        '{"reserved_usd": "invalid"}'
                    )
                api = Mock(side_effect=OSError("offline"))
                record = run(
                    out,
                    DAY,
                    fetch=source,
                    now=NOW,
                    synthetic=True,
                    ai_request=api,
                    usage_directory=ledger,
                )
                self.assertEqual(record["result"]["status"], "selected")
                self.assertEqual(record["explanation"]["status"], "omitted")
                self.assertEqual(api.call_count, 0 if invalid_ledger else 1)
                self.assertEqual(replay(out), record)

    def test_valid_quote_never_certifies_unsubstantiated_ai_narrative(self):
        def generate(body):
            payload = json.loads(body["input"])
            claim = {
                "text": "Micron이 파산을 신청했습니다. 진입 가격은 999달러입니다.",
                "source_id": "evaluation",
                "quote": '"status": "selected"',
                "as_of": payload["as_of"],
            }
            return {
                "status": "completed",
                "model": body["model"],
                "usage": {
                    "input_tokens": 100,
                    "output_tokens": 100,
                    "input_tokens_details": {"cached_tokens": 0},
                },
                "output": [
                    {
                        "type": "message",
                        "content": [
                            {
                                "type": "output_text",
                                "text": json.dumps(
                                    {
                                        "selection": claim,
                                        "risks": [claim],
                                        "invalidation": claim,
                                        "learning": claim,
                                    }
                                ),
                            }
                        ],
                    }
                ],
            }

        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / "run"
            record = run(
                out,
                DAY,
                fetch=Sources(),
                now=NOW,
                synthetic=True,
                ai_request=generate,
                usage_directory=Path(tmp) / "usage",
            )
            claim = record["explanation"]["claims"]["selection"]
            self.assertEqual(claim["verification"], "quote_verified")
            self.assertEqual(claim["fact_verification"], "unconfirmed")
            self.assertEqual(record["result"]["plan"]["entry_low"], "100")
            self.assertIn(
                "AI 해석 (사실관계 확인 불가): Micron이 파산",
                (out / "report.md").read_text(),
            )
            self.assertEqual(replay(out), record)

    def test_cli_accepts_shared_credentials_template_with_openai_key(self):
        from contextlib import chdir, redirect_stdout
        from datetime import datetime
        from io import StringIO
        from unittest.mock import patch

        from single_run import main

        template = Path(".env.example").read_text()
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / "run"
            keyfile = Path(tmp) / "credentials.env"
            keyfile.write_text(
                template.replace("OPENAI_API_KEY=", "OPENAI_API_KEY=fake-openai-key")
            )
            keyfile.chmod(0o600)
            calls = []

            def api(body, *, key):
                calls.append(key)
                payload = json.loads(body["input"])
                claim = {
                    "text": "선정 근거를 검토하세요.",
                    "source_id": "evaluation",
                    "quote": '"status": "selected"',
                    "as_of": payload["as_of"],
                }
                return {
                    "status": "completed",
                    "model": body["model"],
                    "usage": {
                        "input_tokens": 100,
                        "output_tokens": 100,
                        "input_tokens_details": {"cached_tokens": 0},
                    },
                    "output": [
                        {
                            "type": "message",
                            "content": [
                                {
                                    "type": "output_text",
                                    "text": json.dumps(
                                        {
                                            "selection": claim,
                                            "risks": [claim],
                                            "invalidation": claim,
                                            "learning": claim,
                                        }
                                    ),
                                }
                            ],
                        }
                    ],
                }

            with (
                chdir(tmp),
                patch(
                    "sys.argv",
                    [
                        "single_run.py",
                        "run",
                        "--output",
                        str(out),
                        "--report-date",
                        str(DAY),
                        "--credentials-file",
                        str(keyfile),
                    ],
                ),
                patch(
                    "single_run.fetch_public",
                    side_effect=lambda url, **kwargs: Sources()(url),
                ),
                patch("single_run.call_openai", side_effect=api),
                patch("single_run.datetime", wraps=datetime) as clock,
                redirect_stdout(StringIO()) as stdout,
            ):
                clock.now.return_value = NOW
                self.assertEqual(main(), 0)
            self.assertEqual(calls, ["fake-openai-key"])
            record = json.loads((out / "record.json").read_text())
            self.assertEqual(record["explanation"]["status"], "generated")
            self.assertNotIn(
                "fake-openai-key", (out / "record.json").read_text() + stdout.getvalue()
            )
            self.assertEqual(replay(out), record)
