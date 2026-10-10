"""Synthetic public API responses, observed through the complete local run."""

import json
import tempfile
import unittest
from contextlib import redirect_stdout
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal, InvalidOperation
from functools import partial
from io import BytesIO, StringIO
from pathlib import Path
from unittest.mock import patch
from urllib.error import HTTPError, URLError
from urllib.parse import parse_qs, urlparse

from single_run import DataError, earnings, replay, run

NOW = datetime(2026, 9, 10, 12, tzinfo=UTC)
DAY = NOW.date()
NEWS_URL = "https://investors.micron.com/news/press-release/2026/Micron-Technology-to-Report-Fiscal-Fourth-Quarter-Results/default.aspx"


class PublicResponses:
    def __init__(self):
        days = [DAY + timedelta(days=i) for i in range(-100, 31)]
        self.days = [d for d in days if d.weekday() < 5 and d != date(2026, 9, 7)]
        past = [d for d in self.days if d < DAY][-50:]
        self.bars = [
            dict(
                xymd=d.strftime("%Y%m%d"),
                open="98",
                high="99",
                low="97",
                clos="98",
                tvol="1000000",
                tamt="98000000",
            )
            for d in past
        ]
        self.bars[-1].update(
            open="99",
            high="101",
            low="99",
            clos="100",
            tvol="1500000",
            tamt="150000000",
        )
        self.stock = dict(
            symbol="MU",
            market="NASDAQ",
            securityType="STOCK",
            isCommonShare=True,
            status="ACTIVE",
            currency="USD",
            sharesOutstanding="100000000",
        )
        self.earnings_day = "September 30, 2026"
        self.earnings_note = (
            "Micron announced that it will report quarterly results after market close."
        )
        self.calls = []
        self.splits = {}
        self.reference_edit = lambda data: data
        self.minute_edit = lambda rows: rows
        self.early_closes = {}

    def __call__(self, url):
        self.calls.append(url)
        query = parse_qs(urlparse(url).query)
        path = urlparse(url).path
        if path.endswith("/stocks/all") or path.endswith("/stocks"):
            value = {"result": [self.stock]}
        elif path.endswith("/market-calendar/US"):
            target = date.fromisoformat(query["date"][0])
            previous = max(d for d in self.days if d < target)
            following = min(d for d in self.days if d > target)

            def session(d):
                return {
                    "date": d.isoformat(),
                    "regularMarket": {
                        "startTime": f"{d}T13:30:00+00:00",
                        "endTime": f"{d}T{self.early_closes.get(str(d), 20):02}:00:00+00:00",
                    }
                    if d in self.days
                    else None,
                }

            value = {
                "result": {
                    "today": session(target),
                    "previousBusinessDay": session(previous),
                    "nextBusinessDay": session(following),
                }
            }
        elif path.endswith("/dailyprice"):
            value = {
                "rt_cd": "0",
                "output1": {"rsym": "DNASMU"},
                "output2": list(reversed(self.bars)),
            }
        elif path.endswith("/chart/MU"):
            times = [
                int(
                    datetime.strptime(r["xymd"], "%Y%m%d")
                    .replace(hour=13, minute=30, tzinfo=UTC)
                    .timestamp()
                )
                for r in self.bars
            ]
            last_day = datetime.strptime(self.bars[-1]["xymd"], "%Y%m%d")
            close_hour = self.early_closes.get(last_day.date().isoformat(), 20)
            last_close = last_day.replace(hour=close_hour, tzinfo=UTC)
            splits = {
                key: event
                for key, event in self.splits.items()
                if event["date"] < int(query["period2"][0])
            }
            value = {
                "chart": {
                    "error": None,
                    "result": [
                        {
                            "meta": {
                                "symbol": "MU",
                                "currency": "USD",
                                "exchangeName": "NMS",
                                "instrumentType": "EQUITY",
                                "exchangeTimezoneName": "America/New_York",
                                "dataGranularity": "1d",
                                "regularMarketTime": int(last_close.timestamp()),
                                "regularMarketPrice": self.bars[-1]["clos"],
                            },
                            "timestamp": times,
                            "events": {"splits": splits},
                            "indicators": {
                                "quote": [
                                    {
                                        name: [r[key] for r in self.bars]
                                        for name, key in [
                                            ("open", "open"),
                                            ("high", "high"),
                                            ("low", "low"),
                                            ("close", "clos"),
                                            ("volume", "tvol"),
                                        ]
                                    }
                                ]
                            },
                        }
                    ],
                }
            }
        elif path.endswith("/inquire-time-itemchartprice"):
            rows = []
            for bar in self.bars[-20:]:
                start = datetime.strptime(bar["xymd"], "%Y%m%d").replace(
                    hour=9, minute=30
                )
                for i in range(13):
                    local = start + timedelta(minutes=30 * i)
                    korean = local + timedelta(hours=13)
                    volume = int(bar["tvol"]) // 13 + (
                        int(bar["tvol"]) % 13 if i == 12 else 0
                    )
                    price = Decimal(bar["clos"])
                    rows.append(
                        dict(
                            tymd=bar["xymd"],
                            xymd=bar["xymd"],
                            xhms=local.strftime("%H%M%S"),
                            kymd=korean.strftime("%Y%m%d"),
                            khms=korean.strftime("%H%M%S"),
                            open=str(price),
                            high=str(price + 1),
                            low=str(price - 1),
                            last=str(price),
                            evol=str(volume),
                            eamt=str(int(price * volume)),
                        )
                    )
            rows = self.minute_edit(list(reversed(rows)))
            key = query.get("KEYB", ["99999999999999"])[0]
            selected = [r for r in rows if r["xymd"] + r["xhms"] <= key][:120]
            value = {"rt_cd": "0", "output1": {"rsym": "DNASMU"}, "output2": selected}
        elif path == "/submissions/CIK0000723125.json":
            value = {
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
        elif url == NEWS_URL:
            value = {
                "@type": "NewsArticle",
                "headline": f"Micron Technology to Report Fiscal Fourth Quarter Results on {self.earnings_day}",
                "description": self.earnings_note,
                "datePublished": "2026-08-26T15:01:00Z",
            }
            return (
                '<script type="application/ld+json">' + json.dumps(value) + "</script>"
            )
        elif path == "/about/press/news":
            return f'<a href="{NEWS_URL}">Micron Technology to Report Fiscal Fourth Quarter Results</a>'
        else:
            raise AssertionError(f"unexpected public request: {url}")
        if path.endswith("/chart/MU"):
            value["chart"]["result"][0] = self.reference_edit(
                value["chart"]["result"][0]
            )
        return json.dumps(value)


class SingleRunTests(unittest.TestCase):
    def test_earnings_replay_and_execution_errors_propagate(self):
        for failure in (
            DataError("replay_response_missing"),
            DataError("replay_request_mismatch"),
            AssertionError("replay body integrity"),
            StopIteration("replay response missing"),
            OSError("replay file unavailable"),
        ):
            with self.subTest(failure=str(failure)):

                def read(url, *, failure=failure):
                    raise failure

                with self.assertRaises(type(failure)) as caught:
                    earnings(read, DAY, NOW)
                self.assertIs(caught.exception, failure)

    def test_earnings_fetch_failure_returns_complete_result(self):
        def read(url):
            raise DataError("http_403")

        self.assertEqual(
            earnings(read, DAY, NOW),
            {
                "status": "unconfirmed",
                "collection_status": "failed",
                "source": "https://www.micron.com/about/press/news",
                "reason": "http_403",
            },
        )

    def test_earnings_invalid_responses_hide_upstream_details(self):
        for failure in (
            KeyError("private upstream detail"),
            IndexError("private upstream detail"),
            TypeError("private upstream detail"),
            ValueError("private upstream detail"),
            InvalidOperation("private upstream detail"),
        ):
            with self.subTest(failure=type(failure).__name__):

                def read(url, *, failure=failure):
                    raise failure

                self.assertEqual(
                    earnings(read, DAY, NOW),
                    {
                        "status": "unconfirmed",
                        "collection_status": "failed",
                        "source": "https://www.micron.com/about/press/news",
                        "reason": "invalid_response",
                    },
                )

        def read_malformed_feed(url):
            return (
                '<script src="/q4Api.js"></script>'
                if url == "https://www.micron.com/about/press/news"
                else "{private upstream detail"
            )

        self.assertEqual(
            earnings(read_malformed_feed, DAY, NOW)["reason"], "invalid_response"
        )

    def test_initial_failures_preserve_price_requests_and_replay(self):
        from single_run import DataError

        for mode, issues in [
            ("stock", ["stock:source_fetch_failed"]),
            ("calendar", ["calendar:source_fetch_failed"]),
            ("rejected", ["bars_0:provider_rejected_request"]),
            ("null", []),
        ]:
            with self.subTest(mode=mode), tempfile.TemporaryDirectory() as tmp:
                source = PublicResponses()

                def fetch(url, *, mode=mode, source=source):
                    if (mode == "stock" and "/api/v1/stocks?symbols=" in url) or (
                        mode == "calendar" and "/market-calendar/" in url
                    ):
                        raise DataError("source_fetch_failed")
                    body = source(url)
                    if "/dailyprice?" in url:
                        data = json.loads(body)
                        if mode == "rejected":
                            data["rt_cd"] = "1"
                        elif mode == "null":
                            data["output2"] = None
                        body = json.dumps(data)
                    return body

                out = Path(tmp) / "run"
                record = run(out, DAY, fetch=fetch, now=NOW, synthetic=True)
                self.assertEqual(record["inputs"]["issues"], issues)
                self.assertEqual(record["result"]["status"], "held")
                self.assertEqual(
                    record["inputs"]["skipped"],
                    {
                        "earnings": "unverified_price_inputs",
                        "turnover": "unverified_price_inputs",
                    },
                )
                urls = [item["url"] for item in record["responses"]]
                self.assertTrue(any("/dailyprice?" in url for url in urls))
                self.assertEqual(
                    any("/chart/MU?" in url for url in urls), mode != "calendar"
                )
                self.assertEqual("bars_0" in record["inputs"], mode != "rejected")
                if mode == "null":
                    self.assertIsNone(record["inputs"]["bars_0"])
                    self.assertIn("invalid_required_data", record["result"]["reasons"])
                self.assertEqual(replay(out), record)

    def test_verified_price_failure_skips_remaining_sources(self):
        source = PublicResponses()
        source.stock["sharesOutstanding"] = "99999999"
        source.earnings_note = "Expected earnings date"
        record = self.run_case(source)
        self.assertEqual(record["result"]["status"], "excluded")
        self.assertIn("market_cap_below_minimum", record["result"]["reasons"])
        self.assertEqual(
            record["inputs"]["skipped"],
            {"earnings": "verified_exclusion", "turnover": "verified_exclusion"},
        )
        self.assertFalse(
            any("inquire-time-itemchartprice" in r["url"] for r in record["responses"])
        )

    def test_confirmed_near_earnings_skip_turnover(self):
        source = PublicResponses()
        source.earnings_day = "September 10, 2026"
        record = self.run_case(source)
        self.assertEqual(
            record["result"]["reasons"], ["earnings_within_exclusion_window"]
        )
        self.assertEqual(
            record["inputs"]["skipped"], {"turnover": "verified_exclusion"}
        )
        self.assertFalse(
            any("inquire-time-itemchartprice" in r["url"] for r in record["responses"])
        )

    def test_verified_public_sources_can_evaluate_without_synthetic_bypass(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / "run"
            record = run(out, DAY, fetch=PublicResponses(), now=NOW)
            self.assertEqual(record["result"]["status"], "selected")
            self.assertFalse(record["synthetic"])
            self.assertEqual(
                record["result"]["metrics"]["average_turnover_lower_bound_usd"],
                "100599987",
            )
            self.assertEqual(replay(out)["result"], record["result"])

    def test_invalid_regular_turnover_is_held(self):
        for mode in ["missing", "duplicate", "amount", "timezone", "unordered"]:
            with self.subTest(mode=mode):
                source = PublicResponses()

                def broken(rows, *, mode=mode):
                    if mode == "missing":
                        rows.pop(10)
                    elif mode == "duplicate":
                        rows.insert(10, dict(rows[10]))
                    elif mode == "amount":
                        rows[10]["eamt"] = "1"
                    elif mode == "timezone":
                        rows[10]["khms"] = "120000"
                    else:
                        rows[10], rows[11] = rows[11], rows[10]
                    return rows

                source.minute_edit = broken
                record = self.run_case(source)
                self.assertEqual(record["result"]["status"], "held")
                self.assertIsNone(record["result"]["plan"])

    def test_early_close_excludes_later_trades_from_lower_bound(self):
        source = PublicResponses()
        source.early_closes[str(DAY - timedelta(days=1))] = 17

        def after_close(rows):
            for row in rows:
                if row["xymd"] == source.bars[-1]["xymd"] and row["xhms"] >= "130000":
                    row["eamt"] = "invalid-after-close"
            return rows

        source.minute_edit = after_close
        record = self.run_case(source)
        self.assertEqual(record["result"]["status"], "selected")
        self.assertEqual(record["inputs"]["turnover"]["bars"], 254)

    def test_calendar_cannot_expand_regular_hours(self):
        source = PublicResponses()
        source.early_closes[str(DAY - timedelta(days=1))] = 21
        record = self.run_case(source)
        self.assertEqual(record["result"]["status"], "held")
        self.assertIn("calendar:invalid_session_time", record["result"]["reasons"])

    def test_binary32_reference_preserves_cent_boundary_prices_without_tolerance(self):
        for mode in (
            "historical_high",
            "latest_close",
            "different_cent",
            "nearby_not_binary32",
            "coarse_binary32",
        ):
            with self.subTest(mode=mode):
                source = PublicResponses()
                source.bars[0]["high"] = "98.5850"
                if mode == "latest_close":
                    source.bars[-1]["clos"] = "100.0050"
                elif mode == "coarse_binary32":
                    source.bars[0]["high"] = "131072.01"

                def changed(data, *, mode=mode):
                    quote = data["indicators"]["quote"][0]
                    quote["high"][0] = "98.58499908447266"
                    if mode == "latest_close":
                        quote["close"][-1] = "100.00499725341797"
                    elif mode == "different_cent":
                        quote["high"][0] = "98.58"
                    elif mode == "nearby_not_binary32":
                        quote["high"][0] = "98.584998"
                    elif mode == "coarse_binary32":
                        quote["high"][0] = "131072.015625"
                    return data

                source.reference_edit = changed
                record = self.run_case(source)
                if mode in ("historical_high", "latest_close"):
                    self.assertEqual(record["result"]["status"], "selected")
                    self.assertEqual(record["inputs"]["bars_0"][-1]["high"], "98.5850")
                    self.assertEqual(
                        record["result"]["plan"]["entry_low"],
                        "100.0050" if mode == "latest_close" else "100",
                    )
                else:
                    self.assertEqual(record["result"]["status"], "held")
                    self.assertIn(
                        "daily_price_reference_mismatch", record["result"]["reasons"]
                    )

    def test_reference_disagreement_or_unknown_adjustment_is_held(self):
        for mode in ["price", "close_time", "open_time", "fractional_volume", "events"]:
            with self.subTest(mode=mode):
                source = PublicResponses()

                def changed(data, *, mode=mode):
                    if mode == "price":
                        data["indicators"]["quote"][0]["high"][0] = "120"
                    elif mode == "close_time":
                        data["meta"]["regularMarketTime"] -= 86400
                    elif mode == "open_time":
                        data["timestamp"][0] += 60
                    elif mode == "fractional_volume":
                        data["indicators"]["quote"][0]["volume"][-2] = "1000000.5"
                    else:
                        data["events"] = {"splits": []}
                    return data

                source.reference_edit = changed
                self.assertEqual(self.run_case(source)["result"]["status"], "held")

    def test_calendar_collection_respects_three_requests_per_second(self):
        from single_run import fetch_public

        source = PublicResponses()
        elapsed = [0.0]
        requests = []

        class Http:
            def open(self, request, timeout):
                if "/market-calendar/US" in request.full_url:
                    recent = [value for value in requests if elapsed[0] - value < 1]
                    if len(recent) >= 3:
                        raise HTTPError(request.full_url, 429, "rate limit", {}, None)
                    requests.append(elapsed[0])
                return BytesIO(source(request.full_url).encode())

        credentials = {
            "TOSS_ACCESS_TOKEN": "synthetic",
            "KIS_ACCESS_TOKEN": "synthetic",
            "KIS_APP_KEY": "synthetic",
            "KIS_APP_SECRET": "synthetic",
        }
        with (
            patch("single_run.build_opener", return_value=Http()),
            patch(
                "single_run.time.sleep",
                side_effect=lambda seconds: elapsed.__setitem__(
                    0, elapsed[0] + seconds
                ),
            ),
        ):
            record = self.run_case(partial(fetch_public, credentials=credentials))
        self.assertEqual(record["result"]["status"], "selected")
        self.assertEqual(len(record["inputs"]["calendar"]["past"]), 50)

    def run_case(self, source):
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / "run"
            record = run(out, DAY, fetch=source, now=NOW, synthetic=True)
            with patch(
                "single_run.build_opener",
                side_effect=AssertionError("network during replay"),
            ) as network:
                self.assertEqual(replay(out)["result"], record["result"])
                network.assert_not_called()
            return record

    def test_atr_wilder_seed_and_both_gap_directions(self):
        # Independent closed form: 2 + (seed - 2) * (13/14)^35 + 1/14.
        for close, high, low, expected in (
            ("80", "81", "79", "2.162180730841244405107496"),
            ("120", "121", "119", "2.183534180114814517233629"),
        ):
            with self.subTest(first_close=close):
                source = PublicResponses()
                source.bars[0].update(open=close, clos=close, high=high, low=low)
                result = self.run_case(source)["result"]
                self.assertEqual(result["status"], "selected")
                atr = Decimal(expected)
                self.assertAlmostEqual(
                    Decimal(result["metrics"]["atr14"]), atr, places=24
                )
                for key, value in (
                    ("entry_high", Decimal(100) + atr / 2),
                    ("stop", Decimal(99) - atr),
                    ("risk", Decimal(1) + atr),
                    ("target", Decimal(102) + atr * 2),
                ):
                    self.assertAlmostEqual(
                        Decimal(result["plan"][key]), value, places=23
                    )

    def test_sma50_includes_the_oldest_close(self):
        for close, expected, status in (
            ("196", "100", "excluded"),
            ("195.99", "99.9998", "selected"),
        ):
            with self.subTest(first_close=close):
                source = PublicResponses()
                source.bars[0].update(open=close, clos=close, high="197", low="195")
                result = self.run_case(source)["result"]
                self.assertEqual(Decimal(result["metrics"]["sma50"]), Decimal(expected))
                self.assertEqual(result["status"], status)
                if status == "excluded":
                    self.assertEqual(result["reasons"], ["close_not_above_sma50"])
                    self.assertIsNone(result["plan"])

    def test_breakout_window_includes_twentieth_but_not_twenty_first_prior_bar(self):
        for index, expected, status in (
            (-21, "101", "excluded"),
            (-22, "99", "selected"),
        ):
            with self.subTest(index=index):
                source = PublicResponses()
                source.bars[index]["high"] = "101"
                result = self.run_case(source)["result"]
                self.assertEqual(
                    Decimal(result["metrics"]["breakout"]), Decimal(expected)
                )
                self.assertEqual(result["status"], status)
                if status == "excluded":
                    self.assertEqual(result["reasons"], ["close_not_above_breakout"])
                    self.assertIsNone(result["plan"])

    def test_volume_window_includes_twentieth_but_not_twenty_first_prior_bar(self):
        for index, expected, status in (
            (-21, "1.428571428571428571428571429", "excluded"),
            (-22, "1.5", "selected"),
        ):
            with self.subTest(index=index):
                source = PublicResponses()
                source.bars[index]["tvol"] = "2000000"
                result = self.run_case(source)["result"]
                self.assertEqual(result["status"], status)
                self.assertEqual(
                    Decimal(result["metrics"]["volume_ratio"]), Decimal(expected)
                )
                if status == "excluded":
                    self.assertEqual(result["reasons"], ["volume_below_multiple"])
                    self.assertIsNone(result["plan"])

    def test_selected_report_and_offline_replay(self):
        source = PublicResponses()
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / "run"
            record = run(out, DAY, fetch=source, now=NOW, synthetic=True)
            self.assertEqual(record["result"]["status"], "selected")
            plan = record["result"]["plan"]
            self.assertEqual(plan["entry_low"], "100")
            self.assertEqual(
                Decimal(plan["entry_high"]).quantize(Decimal(".01")), Decimal("101.04")
            )
            self.assertEqual(
                Decimal(plan["stop"]).quantize(Decimal(".01")), Decimal("96.93")
            )
            self.assertEqual(
                Decimal(plan["risk"]).quantize(Decimal(".01")), Decimal("3.07")
            )
            self.assertEqual(
                Decimal(plan["target"]).quantize(Decimal(".01")), Decimal("106.14")
            )
            report = (out / "report.md").read_text()
            self.assertIn("검증용 사례", report)
            self.assertIn("실제 체결", report)
            with patch(
                "single_run.build_opener",
                side_effect=AssertionError("network during replay"),
            ) as network:
                self.assertEqual(replay(out)["result"], record["result"])
                network.assert_not_called()

    def test_breakout_equality_is_excluded(self):
        source = PublicResponses()
        source.bars[-2]["high"] = "100"
        record = self.run_case(source)
        self.assertEqual(record["result"]["status"], "excluded")
        self.assertIn("close_not_above_breakout", record["result"]["reasons"])
        self.assertIsNone(record["result"]["plan"])

    def test_unused_daily_turnover_does_not_replace_regular_lower_bound(self):
        source = PublicResponses()
        for bar in source.bars:
            bar["tamt"] = "unverified-daily-amount"
        record = self.run_case(source)
        self.assertEqual(record["result"]["status"], "selected")
        self.assertEqual(
            record["result"]["metrics"]["average_turnover_lower_bound_usd"], "100599987"
        )

    def test_volume_multiple_below_boundary_is_excluded(self):
        source = PublicResponses()
        source.bars[-1].update(tvol="1499999", tamt="149999900")
        record = self.run_case(source)
        self.assertEqual(record["result"]["status"], "excluded")
        self.assertIn("volume_below_multiple", record["result"]["reasons"])

    def test_market_cap_below_boundary_is_excluded(self):
        source = PublicResponses()
        source.stock["sharesOutstanding"] = "99999999"
        record = self.run_case(source)
        self.assertEqual(record["result"]["status"], "excluded")
        self.assertIn("market_cap_below_minimum", record["result"]["reasons"])

    def test_sma_equality_is_excluded(self):
        source = PublicResponses()
        for bar in source.bars:
            bar.update(
                open="100",
                high="101",
                low="99",
                clos="100",
                tamt=str(Decimal(bar["tvol"]) * 100),
            )
        record = self.run_case(source)
        self.assertEqual(record["result"]["status"], "excluded")
        self.assertIn("close_not_above_sma50", record["result"]["reasons"])

    def test_bad_quotes_are_held_without_a_price_plan(self):
        for field, value in [
            ("clos", "0"),
            ("high", "98"),
            ("open", "102"),
            ("clos", "NaN"),
            ("tvol", "-1"),
            ("open", True),
        ]:
            with self.subTest(field=field, value=value):
                source = PublicResponses()
                source.bars[-1][field] = value
                record = self.run_case(source)
                self.assertEqual(record["result"]["status"], "held")
                self.assertIsNone(record["result"]["plan"])

    def test_stale_missing_duplicate_and_future_quotes_are_held(self):
        for mode in ["stale", "missing", "duplicate", "unordered", "future"]:
            with self.subTest(mode=mode):
                source = PublicResponses()

                def fetch(url, *, source=source, mode=mode):
                    body = source(url)
                    if "/dailyprice?" not in url:
                        return body
                    data = json.loads(body)
                    rows = data["output2"]
                    if mode == "stale":
                        rows.pop(0)
                    elif mode == "missing":
                        rows.pop(20)
                    elif mode == "duplicate":
                        rows[25]["xymd"] = rows[26]["xymd"]
                    elif mode == "unordered":
                        rows[20], rows[21] = rows[21], rows[20]
                    else:
                        rows[0]["xymd"] = DAY.strftime("%Y%m%d")
                    return json.dumps(data)

                record = self.run_case(fetch)
                self.assertIn("price_reference", record["inputs"])
                result = record["result"]
                self.assertEqual(result["status"], "held")
                self.assertIn(
                    "duplicate_or_unordered_bars"
                    if mode in ("duplicate", "unordered")
                    else "missing_stale_or_future_bars",
                    result["reasons"],
                )
                self.assertIsNone(result["plan"])

    def test_unconfirmed_and_estimated_earnings_are_held(self):
        for note in [
            "",
            "Expected earnings date",
            "Tentative earnings date",
            "Results postponed",
        ]:
            with self.subTest(note=note):
                source = PublicResponses()
                if not note:
                    source.earnings_day = "June 24, 2026"
                else:
                    source.earnings_note = note
                record = self.run_case(source)
                self.assertEqual(record["result"]["status"], "held")
                self.assertIn(
                    "next_confirmed_earnings_unavailable", record["result"]["reasons"]
                )
                self.assertIsNone(record["result"]["plan"])

    def test_earnings_window_includes_today_fifth_session_and_weekend(self):
        for event_day in [
            "September 10, 2026",
            "September 13, 2026",
            "September 16, 2026",
        ]:
            for session in ["before market open", "after market close"]:
                with self.subTest(event_day=event_day, session=session):
                    source = PublicResponses()
                    source.earnings_day = event_day
                    source.earnings_note = "Micron announced results " + session
                    record = self.run_case(source)
                    self.assertEqual(record["result"]["status"], "excluded")
                    self.assertIn(
                        "earnings_within_exclusion_window", record["result"]["reasons"]
                    )

    def test_earnings_on_sixth_session_is_allowed(self):
        source = PublicResponses()
        source.earnings_day = "September 17, 2026"
        self.assertEqual(self.run_case(source)["result"]["status"], "selected")

    def test_newer_earnings_postponement_invalidates_original_announcement(self):
        source = PublicResponses()
        changed_url = "https://investors.micron.com/news/press-release/2026/Micron-Updates-Quarterly-Call/default.aspx"

        def fetch(url):
            if url == changed_url:
                return (
                    '<script type="application/ld+json">'
                    + json.dumps(
                        {
                            "@type": "NewsArticle",
                            "headline": "Micron updates quarterly earnings call",
                            "description": "Micron has postponed its earnings announcement; the new date is not confirmed.",
                            "datePublished": "2026-09-09T15:00:00Z",
                        }
                    )
                    + "</script>"
                )
            body = source(url)
            if "/about/press/news" in url:
                body += f'<a href="{changed_url}">Micron updates quarterly earnings call</a>'
            return body

        record = self.run_case(fetch)
        self.assertEqual(record["result"]["status"], "held")
        self.assertIsNone(record["result"]["plan"])
        self.assertEqual(record["inputs"]["earnings"]["source"], changed_url)

    def test_split_window_is_held(self):
        source = PublicResponses()
        source.splits = {
            "event": {
                "date": int(NOW.timestamp()) - 86400,
                "numerator": 2,
                "denominator": 1,
            }
        }
        record = self.run_case(source)
        self.assertEqual(record["result"]["status"], "held")
        self.assertIn(
            "corporate_action_adjustment_unverified", record["result"]["reasons"]
        )

    def test_report_day_split_is_checked_before_publishing_prices(self):
        source = PublicResponses()
        source.splits = {
            "today": {
                "date": int(NOW.replace(hour=13, minute=30).timestamp()),
                "numerator": 2,
                "denominator": 1,
            }
        }
        record = self.run_case(source)
        self.assertEqual(record["result"]["status"], "held")
        self.assertIn(
            "corporate_action_adjustment_unverified", record["result"]["reasons"]
        )
        self.assertIsNone(record["result"]["plan"])

    def test_cash_dividend_keeps_the_unadjusted_price_plan(self):
        source = PublicResponses()

        def dividend(data):
            data["events"]["dividends"] = {
                "event": {"date": int(NOW.timestamp()) - 86400, "amount": "0.15"}
            }
            data["indicators"]["adjclose"] = [{"adjclose": ["1"] * 50}]
            return data

        source.reference_edit = dividend
        record = self.run_case(source)
        self.assertEqual(record["result"]["status"], "selected")
        self.assertEqual(record["result"]["plan"]["entry_low"], "100")
        self.assertEqual(
            Decimal(record["result"]["plan"]["entry_high"]).quantize(Decimal(".01")),
            Decimal("101.04"),
        )

    def test_unsupported_security_is_excluded(self):
        for field, value in [
            ("market", "AMEX"),
            ("securityType", "ETF"),
            ("isCommonShare", False),
            ("status", "DELISTED"),
        ]:
            with self.subTest(field=field):
                source = PublicResponses()
                source.stock[field] = value
                self.assertEqual(self.run_case(source)["result"]["status"], "excluded")

    def test_unverified_live_session_cannot_become_candidate(self):
        source = PublicResponses()

        def wrong_session(data):
            data["meta"]["exchangeTimezoneName"] = "Asia/Seoul"
            return data

        source.reference_edit = wrong_session
        with tempfile.TemporaryDirectory() as tmp:
            record = run(Path(tmp) / "run", DAY, fetch=source, now=NOW)
            self.assertEqual(record["result"]["status"], "held")
            self.assertIn(
                "price_reference:reference_identity_or_session_mismatch",
                record["result"]["reasons"],
            )
            self.assertIsNone(record["result"]["plan"])

    def test_live_session_hold_does_not_hide_invalid_quotes(self):
        source = PublicResponses()

        def wrong_session(data):
            data["meta"]["exchangeTimezoneName"] = "Asia/Seoul"
            return data

        source.reference_edit = wrong_session
        source.bars[-1]["open"] = "102"
        with tempfile.TemporaryDirectory() as tmp:
            record = run(Path(tmp) / "run", DAY, fetch=source, now=NOW)
            self.assertEqual(record["result"]["status"], "held")
            self.assertIn(
                "price_reference:reference_identity_or_session_mismatch",
                record["result"]["reasons"],
            )
            self.assertIn("invalid_ohlc", record["result"]["reasons"])
            self.assertIsNone(record["result"]["plan"])

    def test_market_closed_or_wrong_report_time_is_held(self):
        for now, day in [
            (NOW, date(2026, 9, 7)),
            (NOW, date(2026, 9, 9)),
            (NOW.replace(hour=14), DAY),
        ]:
            with self.subTest(now=now, day=day), tempfile.TemporaryDirectory() as tmp:
                record = run(
                    Path(tmp) / "run",
                    day,
                    fetch=PublicResponses(),
                    now=now,
                    synthetic=True,
                )
                self.assertEqual(record["result"]["status"], "held")
                self.assertIsNone(record["result"]["plan"])

    def test_replay_rejects_changed_record_and_existing_output(self):
        from single_run import DataError

        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / "run"
            run(out, DAY, fetch=PublicResponses(), now=NOW, synthetic=True)
            original = (out / "record.json").read_bytes()
            with self.assertRaises(FileExistsError):
                run(out, DAY, fetch=PublicResponses(), now=NOW, synthetic=True)
            self.assertEqual((out / "record.json").read_bytes(), original)
            record = json.loads(original)
            record["result"]["status"] = "held"
            (out / "record.json").write_text(json.dumps(record))
            with self.assertRaisesRegex(DataError, "integrity"):
                replay(out)

    def test_cli_issues_tokens_only_on_request_and_keeps_them_out_of_artifacts(self):
        from single_run import main

        source = PublicResponses()
        token_requests = []

        class Http:
            def open(self, request, timeout):
                if "/oauth2/token" in request.full_url:
                    token_requests.append(request.full_url)
                    return BytesIO(b'{"access_token":"synthetic-token-private"}')
                if "openapi." in request.full_url:
                    self_token = request.get_header("Authorization")
                    if self_token != "Bearer synthetic-token-private":
                        raise AssertionError("missing authorization")
                return BytesIO(source(request.full_url).encode())

        with tempfile.TemporaryDirectory() as tmp:
            secret_file = Path(tmp) / "credentials.env"
            secret_file.write_text(
                "TOSS_CLIENT_ID=synthetic-client\nTOSS_CLIENT_SECRET=synthetic-private\n"
                "KIS_APP_KEY=synthetic-key\nKIS_APP_SECRET=synthetic-private\n"
            )
            secret_file.chmod(0o600)
            for issue in [False, True]:
                out = Path(tmp) / str(issue)
                args = [
                    "single_run.py",
                    "run",
                    "--output",
                    str(out),
                    "--report-date",
                    str(DAY),
                    "--credentials-file",
                    str(secret_file),
                ] + (["--issue-tokens"] if issue else [])
                stdout = StringIO()
                with (
                    patch("sys.argv", args),
                    patch("single_run.build_opener", return_value=Http()),
                    patch("single_run.time.sleep"),
                    patch("single_run.datetime", wraps=datetime) as clock,
                    redirect_stdout(stdout),
                ):
                    clock.now.return_value = NOW
                    self.assertEqual(main(), 0 if issue else 2)
                self.assertEqual(len(token_requests), 2 if issue else 0)
                record = (out / "record.json").read_text()
                report = (out / "report.md").read_text()
                for forbidden in [
                    "synthetic-token-private",
                    "synthetic-private",
                    "synthetic-client",
                    "synthetic-key",
                ]:
                    self.assertNotIn(forbidden, record + report + stdout.getvalue())

    def test_cli_token_failure_identifies_service_without_secrets_or_retry(self):
        import single_run as single
        import universe_run as universe

        for cli in (single.main, universe.main):
            for failed_service, reason in (
                ("toss", "http_401"),
                ("kis", "http_403"),
                ("kis", "transport_error"),
                ("kis", "invalid_response"),
            ):
                with (
                    self.subTest(
                        cli=cli.__module__, service=failed_service, reason=reason
                    ),
                    tempfile.TemporaryDirectory() as tmp,
                ):
                    requests = []

                    class Http:
                        def open(
                            self,
                            request,
                            timeout,
                            *,
                            failed_service=failed_service,
                            reason=reason,
                            requests=requests,
                        ):
                            requests.append(request.full_url)
                            service = (
                                "toss"
                                if "tossinvest.com" in request.full_url
                                else "kis"
                            )
                            if service == failed_service:
                                if reason.startswith("http_"):
                                    raise HTTPError(
                                        request.full_url,
                                        int(reason[5:]),
                                        "synthetic-private",
                                        {},
                                        BytesIO(b"synthetic-private"),
                                    )
                                if reason == "transport_error":
                                    raise URLError("synthetic-private")
                                return BytesIO(
                                    b'{"access_token":null,"secret":"synthetic-private"}'
                                )
                            return BytesIO(
                                b'{"access_token":"synthetic-token-private"}'
                            )

                    secret_file = Path(tmp) / "credentials.env"
                    secret_file.write_text(
                        "TOSS_CLIENT_ID=synthetic-client\nTOSS_CLIENT_SECRET=synthetic-private\n"
                        "KIS_APP_KEY=synthetic-key\nKIS_APP_SECRET=synthetic-private\n"
                    )
                    secret_file.chmod(0o600)
                    out = Path(tmp) / "output"
                    args = [
                        "run.py",
                        "run",
                        "--output",
                        str(out),
                        "--credentials-file",
                        str(secret_file),
                        "--issue-tokens",
                    ]
                    stdout = StringIO()
                    with (
                        patch("sys.argv", args),
                        patch("single_run.build_opener", return_value=Http()),
                        redirect_stdout(stdout),
                    ):
                        self.assertEqual(cli(), 1)
                    message = stdout.getvalue()
                    self.assertIn(
                        "oauth_failed:" + failed_service + ":" + reason, message
                    )
                    self.assertIn(
                        "confirmed_before_failure="
                        + ("none" if failed_service == "toss" else "toss"),
                        message,
                    )
                    self.assertIn("no_automatic_retry", message)
                    self.assertEqual(
                        len(requests), 1 if failed_service == "toss" else 2
                    )
                    self.assertTrue(all("/oauth2/token" in url for url in requests))
                    self.assertFalse(out.exists())
                    self.assertEqual(secret_file.stat().st_mode & 0o777, 0o600)
                    self.assertNotIn("synthetic-token-private", secret_file.read_text())
                    for forbidden in (
                        "synthetic-private",
                        "synthetic-token-private",
                        "synthetic-client",
                        "synthetic-key",
                    ):
                        self.assertNotIn(forbidden, message)

    def test_turnover_inclusive_boundary(self):
        for delta, expected in [(0, "selected"), (-1, "held")]:
            with self.subTest(delta=delta):
                source = PublicResponses()

                def amounts(rows, *, delta=delta):
                    for row in rows:
                        row.update(
                            open="1", high="2", low="0.01", last="1", evol="1", eamt="1"
                        )
                        if row["xhms"] == "093000":
                            row.update(
                                open="100",
                                high="101",
                                low="99",
                                last="100",
                                evol="500000",
                                eamt=str(50000001 + delta),
                            )
                    return rows

                source.minute_edit = amounts
                record = self.run_case(source)
                self.assertEqual(record["result"]["status"], expected)
                if expected == "held":
                    self.assertIn(
                        "turnover_lower_bound_insufficient", record["result"]["reasons"]
                    )
                else:
                    self.assertEqual(
                        record["result"]["metrics"]["average_turnover_lower_bound_usd"],
                        "50000000",
                    )


if __name__ == "__main__":
    unittest.main()
