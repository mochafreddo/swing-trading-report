"""Exercise delivery after the complete synthetic single-report run."""

import json
import tempfile
import unittest
from contextlib import redirect_stdout
from datetime import datetime, timedelta
from http.client import BadStatusLine
from io import BytesIO, StringIO
from pathlib import Path
from unittest.mock import patch
from urllib.error import HTTPError

import universe_run as u
from single_run import DataError, run
from telegram_delivery import deliver, main
from test_single_run import DAY, NOW, PublicResponses
from test_universe_run import UniverseResponses


class TelegramDeliveryTests(unittest.TestCase):
    def test_universe_cutoff_before_calendar_records_missed_without_send(self):
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "run"
            u.run(
                output,
                DAY,
                fetch=UniverseResponses(),
                now=NOW,
                synthetic=True,
                collection_cutoff=NOW,
            )
            send = unittest.mock.Mock()
            state = deliver(output, send=send, target="chat", now=NOW)
            send.assert_not_called()
            self.assertEqual(state["attempts"][-1]["timing"], "missed")
            self.assertEqual(state["attempts"][-1]["status"], "not_sent")

    def test_universe_delivery_after_recovery_window_records_missed_without_send(self):
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "run"
            u.run(
                output,
                DAY,
                fetch=UniverseResponses(),
                now=NOW,
                synthetic=True,
                collection_cutoff=NOW + timedelta(minutes=15),
            )
            send = unittest.mock.Mock()
            state = deliver(
                output,
                send=send,
                target="chat",
                now=NOW + timedelta(hours=1, seconds=1),
            )
            send.assert_not_called()
            attempt = state["attempts"][-1]
            self.assertEqual(attempt["status"], "not_sent")
            self.assertEqual(attempt["timing"], "missed")
            self.assertEqual(attempt["reason"], "premarket_delivery_window_closed")

    def test_universe_delivery_separates_late_readiness_from_publication_time(self):
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "run"
            current = [NOW]
            write_text = Path.write_text

            def write(path, *args, **kwargs):
                result = write_text(path, *args, **kwargs)
                if path.name == "report.md":
                    current[0] = NOW + timedelta(minutes=30, seconds=1)
                return result

            with patch.object(Path, "write_text", write):
                u.run(
                    output,
                    DAY,
                    fetch=UniverseResponses(),
                    clock=lambda: current[0],
                    synthetic=True,
                    collection_cutoff=NOW + timedelta(minutes=15),
                )
            published = NOW + timedelta(minutes=30, seconds=59)
            captions = []

            def send(report, caption):
                captions.append(caption)
                self.assertEqual(report, (output / "report.md").read_bytes())
                return {
                    "ok": True,
                    "result": {"message_id": 9, "date": int(published.timestamp())},
                }

            state = deliver(output, send=send, target="chat", now=published)
            attempt = state["attempts"][-1]
            self.assertEqual(state["scope"], "universe_report")
            self.assertEqual(attempt["status"], "sent")
            self.assertTrue(attempt["publication_on_time"])
            self.assertFalse(attempt["report_ready_on_time"])
            self.assertFalse(attempt["on_time"])
            self.assertEqual(attempt["timing"], "delayed")
            self.assertIn("지연", captions[0])

    def test_universe_delay_saving_intent_rechecks_window_before_http(self):
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "run"
            u.run(
                output,
                DAY,
                fetch=UniverseResponses(),
                now=NOW,
                synthetic=True,
                collection_cutoff=NOW + timedelta(minutes=15),
            )
            import telegram_delivery as delivery

            save = delivery._save
            current = [NOW + timedelta(minutes=59, seconds=59)]

            def delayed_save(path, state):
                save(path, state)
                current[0] = NOW + timedelta(hours=1, seconds=1)

            send = unittest.mock.Mock()
            with (
                patch("telegram_delivery._save", side_effect=delayed_save),
                patch("telegram_delivery.datetime", wraps=datetime) as clock,
            ):
                clock.now.side_effect = lambda zone: current[0]
                state = deliver(output, send=send, target="chat")
            send.assert_not_called()
            self.assertEqual(state["attempts"][-1]["status"], "not_sent")
            self.assertEqual(state["attempts"][-1]["timing"], "missed")

    def test_universe_publication_crossing_deadline_edits_once_without_resending(self):
        for minutes, edit_ok in ((31, True), (60, True), (31, False)):
            with (
                self.subTest(minutes=minutes, edit_ok=edit_ok),
                tempfile.TemporaryDirectory() as directory,
            ):
                output = Path(directory) / "run"
                u.run(
                    output,
                    DAY,
                    fetch=UniverseResponses(),
                    now=NOW,
                    synthetic=True,
                    collection_cutoff=NOW + timedelta(minutes=15),
                )
                published = NOW + timedelta(minutes=minutes, seconds=1)
                started = published - timedelta(seconds=2)
                send = unittest.mock.Mock(
                    return_value={
                        "ok": True,
                        "result": {"message_id": 9, "date": int(published.timestamp())},
                    }
                )

                def edit(message_id, caption, output=output, edit_ok=edit_ok):
                    saved = json.loads((output / "delivery.json").read_text())[
                        "attempts"
                    ][-1]
                    self.assertEqual(saved["status"], "sent")
                    self.assertEqual(saved["caption_update"], "unknown")
                    self.assertEqual(message_id, 9)
                    self.assertIn("지연", caption)
                    if not edit_ok:
                        raise OSError("sensitive upstream detail")
                    return {"ok": True, "result": {"message_id": 9, "caption": caption}}

                editor = unittest.mock.Mock(side_effect=edit)
                state = deliver(
                    output, send=send, edit_caption=editor, target="chat", now=started
                )
                attempt = state["attempts"][-1]
                self.assertEqual(attempt["status"], "sent")
                self.assertEqual(
                    attempt["timing"], "delayed" if minutes == 31 else "missed_deadline"
                )
                self.assertEqual(
                    attempt.get("caption_update"), "updated" if edit_ok else "unknown"
                )
                editor.assert_called_once()
                send.assert_called_once()
                with self.assertRaises(DataError):
                    deliver(
                        output,
                        send=send,
                        edit_caption=editor,
                        target="chat",
                        now=published,
                    )
                send.assert_called_once()
                self.assertNotIn(
                    "sensitive upstream detail", (output / "delivery.json").read_text()
                )

    def test_unknown_response_stops_until_user_confirms_missing(self):
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "run"
            run(output, DAY, fetch=PublicResponses(), now=NOW, synthetic=True)
            sent = []

            def send(report, caption):
                sent.append(report)
                raise TimeoutError("must never be recorded")

            result = deliver(output, send=send, target="test-private-chat", now=NOW)
            self.assertEqual(result["attempts"][-1]["status"], "unknown")
            self.assertEqual(len(sent), 1)
            self.assertEqual(sent[0], (output / "report.md").read_bytes())
            with self.assertRaises(DataError):
                deliver(output, send=send, target="test-private-chat", now=NOW)
            self.assertEqual(len(sent), 1)
            saved = json.loads((output / "delivery.json").read_text())
            self.assertNotIn("must never be recorded", json.dumps(saved))
            self.assertEqual(saved["report_sha256"], result["report_sha256"])

    def test_confirmation_allows_only_one_manual_retry_and_preserves_history(self):
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "run"
            run(output, DAY, fetch=PublicResponses(), now=NOW, synthetic=True)
            sent = []

            def send(report, caption):
                sent.append(caption)
                return {"ok": False, "error_code": 403}

            deliver(output, send=send, target="chat", now=NOW)
            with self.assertRaises(DataError):
                deliver(output, send=send, target="chat", retry=True, now=NOW)
            deliver(output, confirm="missing", now=NOW)
            result = deliver(output, send=send, target="chat", retry=True, now=NOW)
            self.assertEqual(
                [a["status"] for a in result["attempts"]], ["not_sent", "not_sent"]
            )
            self.assertEqual(len(sent), 2)
            self.assertIn("미리보기", sent[0])
            with self.assertRaises(DataError):
                deliver(output, send=send, target="chat", retry=True, now=NOW)
            deliver(output, confirm="received", now=NOW)
            with self.assertRaises(DataError):
                deliver(output, send=send, target="chat", retry=True, now=NOW)
            with self.assertRaises(DataError):
                deliver(output, confirm="missing", now=NOW)
            self.assertEqual(len(sent), 2)

    def test_unknown_then_missing_manual_retry_can_succeed(self):
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "run"
            run(output, DAY, fetch=PublicResponses(), now=NOW, synthetic=True)
            calls = []

            def send(report, caption):
                calls.append(report)
                if len(calls) == 1:
                    raise TimeoutError()
                return {
                    "ok": True,
                    "result": {"message_id": 17, "date": int(NOW.timestamp())},
                }

            deliver(output, send=send, target="chat", now=NOW)
            deliver(output, confirm="missing", now=NOW)
            result = deliver(output, send=send, target="chat", retry=True, now=NOW)
            self.assertEqual(
                [a["status"] for a in result["attempts"]], ["unknown", "sent"]
            )
            self.assertIsNone(result["attempts"][-1]["receipt"])
            self.assertEqual(calls[0], calls[1])

    def test_crash_before_response_leaves_unknown_and_blocks_resend(self):
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "run"
            run(output, DAY, fetch=PublicResponses(), now=NOW, synthetic=True)

            def interrupted(report, caption):
                raise KeyboardInterrupt()

            with self.assertRaises(KeyboardInterrupt):
                deliver(output, send=interrupted, target="chat", now=NOW)
            saved = json.loads((output / "delivery.json").read_text())
            self.assertEqual(saved["attempts"][-1]["status"], "unknown")
            with self.assertRaises(DataError):
                deliver(output, send=interrupted, target="chat", now=NOW)

    def test_publication_time_uses_actual_session_and_keeps_single_symbol_preview(self):
        # September 10 opens at 13:30 UTC, so its scheduled minute is 12:30 UTC.
        for minute, second, expected in [
            (29, 59, False),
            (30, 0, True),
            (30, 59, True),
            (31, 0, False),
        ]:
            with (
                self.subTest(minute=minute, second=second),
                tempfile.TemporaryDirectory() as directory,
            ):
                output = Path(directory) / "run"
                run(output, DAY, fetch=PublicResponses(), now=NOW, synthetic=True)
                published = NOW.replace(minute=minute, second=second)
                result = deliver(
                    output,
                    send=lambda report, caption, published=published: {
                        "ok": True,
                        "result": {"message_id": 9, "date": int(published.timestamp())},
                    },
                    target="chat",
                    now=published,
                )
                attempt = result["attempts"][-1]
                self.assertEqual(attempt["on_time"], expected)
                self.assertEqual(attempt["scheduled_at"], "2026-09-10T12:30:00+00:00")
                self.assertEqual(result["scope"], "single_symbol_preview")

    def test_changed_report_or_target_cannot_be_retried(self):
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "run"
            run(output, DAY, fetch=PublicResponses(), now=NOW, synthetic=True)

            def send(report, caption):
                return {"ok": False, "error_code": 400}

            deliver(output, send=send, target="chat", now=NOW)
            deliver(output, confirm="missing", now=NOW)
            with self.assertRaises(DataError):
                deliver(output, send=send, target="other", retry=True, now=NOW)
            (output / "report.md").write_text("changed")
            with self.assertRaises(DataError):
                deliver(output, send=send, target="chat", retry=True, now=NOW)

    def test_cli_uploads_exact_report_and_records_safe_api_result(self):
        for response in (
            {
                "ok": True,
                "result": {
                    "message_id": 33,
                    "date": int(NOW.timestamp()),
                    "chat": {"id": 456, "type": "private"},
                },
            },
            {
                "ok": False,
                "error_code": 403,
                "description": "sensitive upstream detail",
            },
            {"ok": False, "error_code": 502},
            {"ok": False, "error_code": 403, "_http_status": 502},
            {
                "ok": True,
                "_http_status": 302,
                "result": {
                    "message_id": 33,
                    "date": int(NOW.timestamp()),
                    "chat": {"id": 456, "type": "private"},
                },
            },
            {"_exception": "bad_status"},
            {"ok": True, "result": []},
            {
                "ok": True,
                "result": {
                    "message_id": 33,
                    "date": int(NOW.timestamp()),
                    "chat": {"id": 456, "type": "group"},
                },
            },
        ):
            with (
                self.subTest(response=response),
                tempfile.TemporaryDirectory() as directory,
            ):
                output = Path(directory) / "run"
                run(output, DAY, fetch=PublicResponses(), now=NOW, synthetic=True)
                requests = []

                class Opener:
                    def open(
                        self, request, timeout, requests=requests, response=response
                    ):
                        requests.append(request)
                        if request.full_url.endswith("getChat"):
                            return BytesIO(
                                json.dumps(
                                    {
                                        "ok": True,
                                        "result": {"id": 456, "type": "private"},
                                    }
                                ).encode()
                            )
                        if response.get("_exception"):
                            raise BadStatusLine("sensitive upstream detail")
                        if response.get("_http_status"):
                            raise HTTPError(
                                request.full_url,
                                response["_http_status"],
                                "sensitive upstream detail",
                                {},
                                BytesIO(json.dumps(response).encode()),
                            )
                        return BytesIO(json.dumps(response).encode())

                stdout = StringIO()
                with (
                    patch.dict(
                        "os.environ",
                        {
                            "TELEGRAM_BOT_TOKEN": "123:test_secret",
                            "TELEGRAM_CHAT_ID": "456",
                        },
                    ),
                    patch("telegram_delivery.build_opener", return_value=Opener()),
                    patch("sys.argv", ["telegram_delivery.py", "send", str(output)]),
                    redirect_stdout(stdout),
                    patch("telegram_delivery.datetime", wraps=datetime) as clock,
                ):
                    clock.now.return_value = NOW
                    code = main()
                saved = (output / "delivery.json").read_text()
                attempt = json.loads(saved)["attempts"][-1]
                expected = (
                    "sent"
                    if not response.get("_http_status")
                    and isinstance(response.get("result"), dict)
                    and response["result"].get("chat", {}).get("type") == "private"
                    else "not_sent"
                    if response.get("error_code") == 403
                    and not response.get("_http_status")
                    else "unknown"
                )
                self.assertEqual(attempt["status"], expected)
                self.assertEqual(code, 0 if expected == "sent" else 2)
                self.assertEqual(len(requests), 2)
                self.assertIn((output / "report.md").read_bytes(), requests[-1].data)
                for forbidden in (
                    "test_secret",
                    "sensitive upstream detail",
                    '"id": 456',
                ):
                    self.assertNotIn(forbidden, saved + stdout.getvalue())

    def test_closed_day_has_no_scheduled_delivery(self):
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "run"
            source = PublicResponses()
            source.days.remove(DAY)
            run(output, DAY, fetch=source, now=NOW, synthetic=True)
            result = deliver(
                output,
                send=lambda report, caption: {
                    "ok": True,
                    "result": {"message_id": 9, "date": int(NOW.timestamp())},
                },
                target="chat",
                now=NOW,
            )
            self.assertFalse(result["attempts"][-1]["on_time"])
            self.assertNotIn("scheduled_at", result["attempts"][-1])


if __name__ == "__main__":
    unittest.main()
