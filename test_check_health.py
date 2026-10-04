"""Exercise the health report through its command-line boundary."""

import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


class HealthTests(unittest.TestCase):
    def run_report(self, lint, *, code=None):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            shutil.copyfile(
                Path(__file__).with_name("check_health.py"), root / "check_health.py"
            )
            (root / "mise.toml").write_text(
                f"[tasks.lint]\nrun = {json.dumps(lint)}\n"
                '[tasks.test]\nrun = "health-pass"\n'
                '[tasks.negative-controls]\nrun = "health-pass"\n'
            )
            for name, body in (
                ("health-fail", "echo deliberate-error >&2; exit 7"),
                ("health-pass", "echo continued-check"),
                ("health-silent-error", "exit 127"),
                ("actionlint", "exit 0"),
            ):
                executable = root / name
                executable.write_text("#!/bin/sh\n" + body + "\n")
                executable.chmod(0o700)
            return subprocess.run(
                [sys.executable, "-B", "-c", code]
                if code
                else [sys.executable, "-B", str(root / "check_health.py")],
                cwd=root,
                env={**os.environ, "PATH": str(root)},
                capture_output=True,
                text=True,
                check=False,
            )

    def test_failure_keeps_exit_code_and_runs_remaining_checks(self):
        result = self.run_report(["health-fail", "health-pass"])
        self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
        self.assertIn("health-fail | FAILED | 7 |", result.stdout)
        self.assertIn("deliberate-error", result.stdout)
        self.assertEqual(result.stdout.count("PASSED"), 3)

    def test_missing_tool_and_missing_shellcheck_cannot_pass(self):
        for command in ("health-missing", "actionlint"):
            with self.subTest(command=command):
                result = self.run_report([command, "health-pass"])
                self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
                self.assertIn(f"{command} | SKIPPED | - |", result.stdout)
                self.assertIn("Missing tool:", result.stdout)
                self.assertEqual(result.stdout.count("PASSED"), 3)

    def test_silent_exit_127_is_a_failure_not_a_skip(self):
        result = self.run_report(["health-silent-error"])
        self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
        self.assertIn("health-silent-error | FAILED | 127 |", result.stdout)
        self.assertNotIn("SKIPPED", result.stdout)

    def test_capture_failure_is_an_error_and_continues(self):
        result = self.run_report(
            ["health-pass"],
            code="import check_health\nfrom unittest.mock import patch\n"
            'with patch("tempfile.TemporaryFile", side_effect=OSError("capture-failed")):\n'
            "    raise SystemExit(check_health.main())\n",
        )
        self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
        self.assertEqual(result.stdout.count("ERROR | - |"), 3)
        self.assertIn("capture-failed", result.stdout)

    def test_empty_required_task_cannot_pass(self):
        result = self.run_report([])
        self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
        self.assertIn("ERROR:", result.stdout)
        self.assertNotIn("Overall: SUCCESS", result.stdout)

    def test_all_checks_succeed(self):
        result = self.run_report(["health-pass"])
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(result.stdout.count("PASSED"), 3)
        self.assertIn("Overall: SUCCESS", result.stdout)


if __name__ == "__main__":
    unittest.main()
