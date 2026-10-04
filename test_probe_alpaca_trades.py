"""CLI/record/replay checks using synthetic public responses, never real credentials."""

import hashlib
import json
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from io import BytesIO, StringIO
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
from urllib.error import HTTPError
from urllib.parse import parse_qs, urlsplit

import probe_alpaca_trades as probe


def page(rows, token=None, requested=None):
    body = json.dumps({"trades": {"AAPL": rows}, "next_page_token": token})
    return {
        "body": body,
        "sha256": hashlib.sha256(body.encode()).hexdigest(),
        "requested_page_token": requested,
        "checked_at": "2026-09-24T00:00:00Z",
    }


ROW = {
    "t": "2026-09-11T13:30:00.000000001Z",
    "p": 100,
    "s": 2,
    "x": "D",
    "z": "C",
    "i": 1,
    "c": ["@"],
}


def record(pages):
    return {
        "day": "2026-09-11",
        "feed": "sip",
        "symbols": probe.SYMBOLS,
        "pages": pages,
        "error": None,
        "elapsed_seconds": 1.0,
    }


def cli(*args):
    stdout, stderr = StringIO(), StringIO()
    with (
        patch.object(probe.sys, "argv", ["probe_alpaca_trades.py", *map(str, args)]),
        redirect_stdout(stdout),
        redirect_stderr(stderr),
    ):
        probe.main()
    return json.loads(stdout.getvalue()), stderr.getvalue()


class ProbeTests(unittest.TestCase):
    def test_replay_inspects_trade_pages_once_without_network(self):
        with tempfile.TemporaryDirectory() as root:
            source = Path(root) / "record.json"
            source.write_text(json.dumps(record([page([ROW])])))
            with (
                patch.object(
                    probe, "inspect_pages", wraps=probe.inspect_pages
                ) as inspect,
                patch.object(
                    probe, "build_opener", side_effect=AssertionError("no network")
                ),
                patch.object(
                    probe.getpass,
                    "getpass",
                    side_effect=AssertionError("no credentials"),
                ),
            ):
                summary, _ = cli("--replay", source)
            inspect.assert_called_once()
            self.assertTrue(summary["pagination_complete"])

    def test_credential_echo_is_rejected_without_saving_or_exposing_it(self):
        for echoed in ("test-key", "test-secret"):
            with self.subTest(echoed=echoed), tempfile.TemporaryDirectory() as root:
                output = Path(root) / "run"
                first = page([ROW], "next")
                data = json.loads(page([dict(ROW, i=2)], requested="next")["body"])
                data["echo"] = echoed
                responses = iter([first["body"].encode(), json.dumps(data).encode()])
                with (
                    patch.object(probe.sys.stdin, "isatty", return_value=True),
                    patch.object(
                        probe.getpass,
                        "getpass",
                        side_effect=["test-key", "test-secret"],
                    ),
                    patch.object(
                        probe,
                        "build_opener",
                        return_value=SimpleNamespace(
                            open=lambda *args, responses=responses, **kwargs: BytesIO(
                                next(responses)
                            )
                        ),
                    ),
                    patch.object(probe.time, "sleep"),
                ):
                    summary, progress = cli(
                        "--day", "2026-09-11", "--max-pages", 2, "--output", output
                    )
                saved = json.loads((output / "record.json").read_text())
                self.assertEqual(len(saved["pages"]), 1)
                self.assertEqual(saved["pages"][0]["body"], first["body"])
                self.assertEqual(saved["error"], "transport_or_response_invalid")
                self.assertEqual(summary["collection_status"], "failed")
                self.assertFalse(summary["pagination_complete"])
                artifacts = "".join(path.read_text() for path in output.iterdir())
                for secret in ("test-key", "test-secret"):
                    self.assertNotIn(secret, artifacts + progress + json.dumps(summary))
                with patch.object(
                    probe, "build_opener", side_effect=AssertionError("offline only")
                ) as network:
                    replay, _ = cli("--replay", output / "record.json")
                    self.assertEqual(summary, replay)
                    network.assert_not_called()

    def test_replay_groups_condition_amounts_without_certifying_turnover(self):
        with tempfile.TemporaryDirectory() as root:
            source = Path(root) / "record.json"
            rows = [
                ROW,
                dict(ROW, i=2, s=3, u="canceled"),
                dict(ROW, i=3, s=4, u="incorrect"),
                dict(ROW, i=4, p=110, s=5, u="corrected"),
                dict(ROW, i=5, c=["@", "M"]),
                dict(ROW, i=6, c=["@", "T"]),
                dict(ROW, i=7, p=120, s=7, t="2026-09-11T20:04:00Z", c=["@", "6"]),
                dict(ROW, i=8, c=["unknown"]),
            ]
            source.write_text(json.dumps(record([page(rows)])))
            summary, _ = cli("--replay", source)
            groups = summary["diagnostic_condition_totals"]["AAPL"]
            self.assertEqual(
                groups["before_close"], {"rows": 2, "volume": "7", "amount_usd": "750"}
            )
            self.assertEqual(
                groups["closing_after_close"],
                {"rows": 1, "volume": "7", "amount_usd": "840"},
            )
            self.assertEqual(groups["canceled_or_incorrect"]["volume"], "7")
            self.assertEqual(groups["non_volume"]["rows"], 1)
            self.assertEqual(groups["extended_hours"]["rows"], 1)
            self.assertEqual(groups["unknown"]["rows"], 1)
            self.assertFalse(summary["exact_regular_turnover_verified"])
            self.assertEqual(summary["validation_status"], "held")

    def test_replay_observes_closing_and_extended_conditions_across_early_close(self):
        with tempfile.TemporaryDirectory() as root:
            source = Path(root) / "record.json"
            rows = [
                dict(ROW, i=1, t="2025-11-28T17:59:59Z", c=["@", "T"]),
                dict(ROW, i=2, t="2025-11-28T18:00:00.353393653Z", c=["@", "6", "X"]),
                dict(ROW, i=3, t="2025-11-28T18:04:28.21898086Z", c=["@", "6"]),
            ]
            source.write_text(json.dumps(dict(record([page(rows)]), day="2025-11-28")))
            summary, _ = cli("--replay", source)
            self.assertEqual(
                summary["session_condition_counts"],
                {
                    "AAPL/extended_hours_before_close": 1,
                    "AAPL/closing_trade_at_or_after_close": 2,
                },
            )
            self.assertEqual(
                summary["closing_trade_examples"]["AAPL"]["t"],
                "2025-11-28T18:00:00.353393653Z",
            )
            self.assertEqual(
                summary["counts"], {"AAPL/before_close": 1, "AAPL/at_or_after_close": 2}
            )
            self.assertIn(
                "session_conditions_require_review", summary["validation_issues"]
            )
            self.assertFalse(summary["exact_regular_turnover_verified"])

    def test_replay_surfaces_trade_updates_without_certifying_amount(self):
        with tempfile.TemporaryDirectory() as root:
            source = Path(root) / "record.json"
            rows = [
                dict(ROW, i=index, u=value)
                for index, value in enumerate(
                    ["canceled", "incorrect", "corrected", "future-status", None], 1
                )
            ]
            source.write_text(json.dumps(record([page(rows)])))
            before = source.read_bytes()
            with patch.object(
                probe, "build_opener", side_effect=AssertionError("offline only")
            ):
                summary, _ = cli("--replay", source)
            self.assertEqual(
                summary["trade_update_counts"],
                {
                    "AAPL/canceled": 1,
                    "AAPL/incorrect": 1,
                    "AAPL/corrected": 1,
                    "AAPL/unknown": 2,
                },
            )
            self.assertIn(
                "historical_trade_updates_require_review", summary["validation_issues"]
            )
            self.assertIn(
                "unknown_trade_update_requires_review", summary["validation_issues"]
            )
            self.assertEqual(summary["counts"], {"AAPL/before_close": 5})
            self.assertIsNone(summary["returned_row_amount_usd"]["AAPL"])
            self.assertFalse(summary["exact_regular_turnover_verified"])
            self.assertEqual(source.read_bytes(), before)

    def test_resume_preserves_history_on_interrupt_timeout_http_error_or_page_limit(
        self,
    ):
        for failure, expected in [
            (KeyboardInterrupt(), "interrupted"),
            (TimeoutError(), "failed"),
            (
                HTTPError(
                    "https://data.alpaca.markets/", 400, "bad token", {}, BytesIO()
                ),
                "failed",
            ),
            (None, "page_limit_reached"),
        ]:
            with (
                self.subTest(expected=expected, failure=type(failure).__name__),
                tempfile.TemporaryDirectory() as root,
            ):
                source, output = Path(root) / "source.json", Path(root) / "continued"
                source.write_text(
                    json.dumps(record([page([ROW, dict(ROW, p=101)], "next")]))
                )
                before = source.read_bytes()

                def respond(request, timeout, *, failure=failure):
                    if failure is not None:
                        raise failure
                    return BytesIO(page([dict(ROW, i=2)], "later")["body"].encode())

                with (
                    patch.object(probe.sys.stdin, "isatty", return_value=True),
                    patch.object(
                        probe.getpass,
                        "getpass",
                        side_effect=["test-key", "test-secret"],
                    ),
                    patch.object(
                        probe,
                        "build_opener",
                        return_value=SimpleNamespace(open=respond),
                    ),
                ):
                    summary, _ = cli(
                        "--resume", source, "--max-pages", 1, "--output", output
                    )
                self.assertEqual(summary["collection_status"], expected)
                self.assertEqual(summary["pages"], 1 if failure else 2)
                self.assertEqual(summary["identity_recurrences"], {"AAPL/D": 1})
                self.assertFalse(summary["pagination_complete"])
                self.assertIsNone(summary["returned_row_amount_usd"]["AAPL"])
                self.assertEqual(source.read_bytes(), before)
                replay, _ = cli("--replay", output / "record.json")
                self.assertEqual(summary, replay)

    def test_resume_rejects_corrupt_complete_or_out_of_scope_records_without_prompting(
        self,
    ):
        good = record([page([ROW], "next")])
        variants = []
        corrupt = json.loads(json.dumps(good))
        corrupt["pages"][0]["body"] += " "
        variants.append(corrupt)
        variants.append(record([page([ROW])]))
        variants.append(dict(good, feed="iex"))
        variants.append(dict(good, symbols=["AAPL"]))
        variants.append(
            record([page([ROW], "next"), page([dict(ROW, i=2)], "next", "next")])
        )
        variants.append(
            record([page([ROW], "next"), page([dict(ROW, i=2)], None, "wrong")])
        )
        for saved in variants:
            with self.subTest(saved=saved), tempfile.TemporaryDirectory() as root:
                source, output = Path(root) / "source.json", Path(root) / "continued"
                source.write_text(json.dumps(saved))
                before = source.read_bytes()
                with (
                    patch.object(probe.sys.stdin, "isatty", return_value=True),
                    patch.object(
                        probe.getpass,
                        "getpass",
                        side_effect=AssertionError("no credentials"),
                    ),
                    patch.object(
                        probe, "build_opener", side_effect=AssertionError("no network")
                    ),
                    self.assertRaises(SystemExit) as raised,
                ):
                    cli("--resume", source, "--output", output)
                self.assertEqual(raised.exception.code, 2)
                self.assertFalse(output.exists())
                self.assertEqual(source.read_bytes(), before)

    def test_replay_distinguishes_in_progress_checkpoint_from_failure(self):
        with tempfile.TemporaryDirectory() as root:
            source = Path(root) / "record.json"
            source.write_text(
                json.dumps(
                    dict(record([page([ROW], "next")]), error="collection_in_progress")
                )
            )
            summary, _ = cli("--replay", source)
            self.assertEqual(summary["collection_status"], "in_progress")
            self.assertFalse(summary["pagination_complete"])

    def test_resume_rejects_changed_request_before_credentials(self):
        with tempfile.TemporaryDirectory() as root:
            source, output = Path(root) / "source.json", Path(root) / "continued"
            saved = record([page([ROW], "next")])
            saved["request"] = {"feed": "iex"}
            source.write_text(json.dumps(saved))
            with (
                patch.object(probe.sys.stdin, "isatty", return_value=True),
                patch.object(
                    probe.getpass,
                    "getpass",
                    side_effect=AssertionError(
                        "invalid record must not request credentials"
                    ),
                ),
                patch.object(
                    probe, "build_opener", side_effect=AssertionError("no network")
                ),
                self.assertRaises(SystemExit) as raised,
            ):
                cli("--resume", source, "--output", output)
            self.assertEqual(raised.exception.code, 2)
            self.assertFalse(output.exists())

    def test_resume_fetches_only_next_page_into_new_record_then_replays(self):
        with tempfile.TemporaryDirectory() as root:
            source, output = Path(root) / "source.json", Path(root) / "continued"
            source.write_text(json.dumps(record([page([ROW], "next-page")])))
            before = source.read_bytes()
            requests = []

            def respond(request, timeout):
                query = parse_qs(urlsplit(request.full_url).query)
                self.assertEqual(query["page_token"], ["next-page"])
                self.assertEqual(query["feed"], ["sip"])
                self.assertEqual(query["symbols"], ["MU,AAPL,XOM"])
                self.assertEqual(query["start"], ["2026-09-11T09:30:00-04:00"])
                self.assertEqual(query["end"], ["2026-09-11T16:05:00-04:00"])
                self.assertEqual(query["asof"], ["2026-09-11"])
                requests.append(query)
                return BytesIO(page([dict(ROW, i=2)])["body"].encode())

            with (
                patch.object(probe.sys.stdin, "isatty", return_value=True),
                patch.object(
                    probe.getpass, "getpass", side_effect=["test-key", "test-secret"]
                ),
                patch.object(
                    probe, "build_opener", return_value=SimpleNamespace(open=respond)
                ),
            ):
                summary, progress = cli(
                    "--resume", source, "--max-pages", 1, "--output", output
                )
            saved = json.loads((output / "record.json").read_text())
            self.assertEqual(len(requests), 1)
            self.assertEqual(len(saved["pages"]), 2)
            self.assertEqual(saved["pages"][0], json.loads(before)["pages"][0])
            self.assertEqual(
                saved["resumed_from_sha256"], hashlib.sha256(before).hexdigest()
            )
            self.assertEqual(summary["collection_status"], "complete")
            self.assertEqual(summary["counts"], {"AAPL/before_close": 2})
            self.assertFalse(summary["exact_regular_turnover_verified"])
            with patch.object(
                probe, "build_opener", side_effect=AssertionError("offline only")
            ):
                replay, _ = cli("--replay", output / "record.json")
            self.assertEqual(summary, replay)
            self.assertEqual(source.read_bytes(), before)
            for secret in ("test-key", "test-secret"):
                self.assertNotIn(
                    secret, (output / "record.json").read_text() + progress
                )

    def test_replay_retains_colliding_rows_and_reports_hold(self):
        with tempfile.TemporaryDirectory() as root:
            source = Path(root) / "record.json"
            rows = [ROW, dict(ROW, t="2026-09-11T14:00:00Z", p=101), ROW]
            source.write_text(json.dumps(record([page(rows, "next")])))
            before = source.read_bytes()
            with (
                patch.object(
                    probe, "build_opener", side_effect=AssertionError("offline only")
                ),
                patch.object(
                    probe.getpass,
                    "getpass",
                    side_effect=AssertionError("no credentials"),
                ),
            ):
                summary, _ = cli("--replay", source)
            self.assertEqual(summary["counts"], {"AAPL/before_close": 3})
            self.assertEqual(summary["identity_recurrences"], {"AAPL/D": 2})
            self.assertEqual(summary["validation_status"], "held")
            self.assertIn(
                "duplicate_trade_identity_requires_review", summary["validation_issues"]
            )
            self.assertIsNone(summary["returned_row_amount_usd"]["AAPL"])
            self.assertIsNone(summary["returned_row_amount_usd"]["MU"])
            self.assertEqual(summary["collection_status"], "page_limit_reached")
            self.assertFalse(summary["exact_regular_turnover_verified"])
            self.assertEqual(source.read_bytes(), before)


if __name__ == "__main__":
    unittest.main()
