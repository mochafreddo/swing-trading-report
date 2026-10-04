"""Verify recording and replay contracts through both report entry points."""

import json
import tempfile
import unittest
from datetime import datetime, timedelta
from pathlib import Path
from unittest.mock import patch

import single_run as s
import universe_run as u
from test_single_run import DAY, NOW, PublicResponses
from test_universe_run import UniverseResponses


class ExecutionRecordTests(unittest.TestCase):
    def test_single_evaluation_keeps_start_time_when_responses_cross_open(self):
        source = PublicResponses()
        current = [NOW]

        def fetch(url):
            body = source(url)
            if "SYMB=MU" in url:
                current[0] = NOW + timedelta(hours=2)
            return body

        with tempfile.TemporaryDirectory() as tmp:
            output = Path(tmp) / "run"
            with patch.object(s, "datetime", wraps=datetime) as clock:
                clock.now.side_effect = lambda *args: current[0]
                record = s.run(output, DAY, fetch=fetch, synthetic=True)
            self.assertEqual(record["as_of"], NOW.isoformat())
            self.assertEqual(record["result"]["status"], "selected")
            self.assertEqual(
                record["responses"][-1]["checked_at"], current[0].isoformat()
            )
            with patch.object(s, "datetime", wraps=datetime) as clock:
                clock.now.side_effect = AssertionError("current clock during replay")
                self.assertEqual(s.replay(output), record)

    def test_replays_reject_rechecksummed_inputs_and_results(self):
        for module, fetch in ((s, PublicResponses), (u, UniverseResponses)):
            for field in ("inputs", "result"):
                with (
                    self.subTest(module=module.__name__, field=field),
                    tempfile.TemporaryDirectory() as tmp,
                ):
                    output = Path(tmp) / "run"
                    record = module.run(
                        output, DAY, fetch=fetch(), now=NOW, synthetic=True
                    )
                    record[field]["changed"] = True
                    record.pop("sha256")
                    record["sha256"] = s.digest(record)
                    (output / "record.json").write_text(json.dumps(record))
                    with self.assertRaisesRegex(s.DataError, "replay_result_mismatch"):
                        module.replay(output)

    def test_both_replays_reject_record_and_report_changes_without_network(self):
        for module, fetch in ((s, PublicResponses), (u, UniverseResponses)):
            for artifact, error in (
                ("record.json", "record_integrity_mismatch"),
                ("report.md", "replay_report_mismatch"),
            ):
                with (
                    self.subTest(module=module.__name__, artifact=artifact),
                    tempfile.TemporaryDirectory() as tmp,
                ):
                    output = Path(tmp) / "run"
                    module.run(output, DAY, fetch=fetch(), now=NOW, synthetic=True)
                    path = output / artifact
                    if artifact == "record.json":
                        record = json.loads(path.read_text())
                        record["result"]["status"] = "held"
                        path.write_text(json.dumps(record))
                    else:
                        path.write_text(path.read_text() + "Changed report.\n")
                    with (
                        patch.object(
                            s,
                            "fetch_public",
                            side_effect=AssertionError("network during replay"),
                        ),
                        self.assertRaisesRegex(s.DataError, error),
                    ):
                        module.replay(output)

    def test_replays_reject_response_sequence_changes(self):
        for module, fetch in ((s, PublicResponses), (u, UniverseResponses)):
            for change, error in (
                ("order", "replay_request_mismatch"),
                ("missing", "replay_response_missing"),
                ("extra", "replay_result_mismatch"),
                ("ir_order", "replay_request_mismatch"),
                ("ir_missing", "replay_response_missing"),
            ):
                with (
                    self.subTest(module=module.__name__, change=change),
                    tempfile.TemporaryDirectory() as tmp,
                ):
                    output = Path(tmp) / "run"
                    record = module.run(
                        output, DAY, fetch=fetch(), now=NOW, synthetic=True
                    )
                    if change == "order":
                        record["responses"][0], record["responses"][1] = (
                            record["responses"][1],
                            record["responses"][0],
                        )
                    elif change == "missing":
                        record["responses"].pop()
                    elif change == "extra":
                        record["responses"].append(record["responses"][0])
                    else:
                        index = next(
                            i
                            for i, item in enumerate(record["responses"])
                            if item["url"] == s.NEWS
                        )
                        if change == "ir_order":
                            record["responses"][index]["url"] += "/unexpected"
                        else:
                            record["responses"] = record["responses"][:index]
                    record.pop("sha256")
                    record["sha256"] = s.digest(record)
                    (output / "record.json").write_text(json.dumps(record))
                    with self.assertRaisesRegex(s.DataError, error):
                        module.replay(output)

    def test_replays_reject_changed_rules_and_format(self):
        for module, fetch in ((s, PublicResponses), (u, UniverseResponses)):
            for field in ("rules", "format_version"):
                with (
                    self.subTest(module=module.__name__, field=field),
                    tempfile.TemporaryDirectory() as tmp,
                ):
                    output = Path(tmp) / "run"
                    record = module.run(
                        output, DAY, fetch=fetch(), now=NOW, synthetic=True
                    )
                    record[field] = {} if field == "rules" else 1
                    record.pop("sha256")
                    record["sha256"] = s.digest(record)
                    (output / "record.json").write_text(json.dumps(record))
                    with self.assertRaisesRegex(s.DataError, "replay_version_mismatch"):
                        module.replay(output)

    def test_v2_records_include_shared_code_and_reject_its_changes(self):
        read_bytes = Path.read_bytes
        shared = Path(s.__file__).with_name("execution_record.py")
        for module, fetch in ((s, PublicResponses), (u, UniverseResponses)):
            with (
                self.subTest(module=module.__name__),
                tempfile.TemporaryDirectory() as tmp,
            ):
                output = Path(tmp) / "run"
                record = module.run(output, DAY, fetch=fetch(), now=NOW, synthetic=True)
                self.assertEqual(record["format_version"], 2)
                self.assertIn(shared.name, record["code_sha256"])

                def changed(path):
                    body = read_bytes(path)
                    return body + b"\n# changed\n" if path == shared else body

                with (
                    patch.object(Path, "read_bytes", changed),
                    self.assertRaisesRegex(s.DataError, "replay_version_mismatch"),
                ):
                    module.replay(output)

    def test_both_replays_reject_changed_contract(self):
        read_text = Path.read_text
        for module, fetch in ((s, PublicResponses), (u, UniverseResponses)):
            with (
                self.subTest(module=module.__name__),
                tempfile.TemporaryDirectory() as tmp,
            ):
                output = Path(tmp) / "run"
                module.run(output, DAY, fetch=fetch(), now=NOW, synthetic=True)
                contract = Path(module.__file__).with_name("docs") / (
                    "single-run-contract.md"
                    if module is s
                    else "universe-run-contract.md"
                )

                def changed(path, *args, contract=contract, **kwargs):
                    text = read_text(path, *args, **kwargs)
                    return text + "\nChanged contract.\n" if path == contract else text

                with (
                    patch.object(Path, "read_text", changed),
                    self.assertRaisesRegex(s.DataError, "replay_version_mismatch"),
                ):
                    module.replay(output)
