"""Explicit opt-in comparison of recorded and injected live claim Responses."""

from __future__ import annotations

import argparse
import json
import os
import shlex
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from sab.decision_board.claim_responses import decode_claim_response_v0  # noqa: E402

DEFAULT_FIXTURE = (
    ROOT
    / "tests"
    / "fixtures"
    / "decision_board"
    / "claim-verifier-responses-recorded.json"
)
_MAX_PROVIDER_OUTPUT_BYTES = 1_048_576


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Compare an explicitly configured provider command against the "
            "recorded Decision Board claim Response. Never runs in CI."
        )
    )
    parser.add_argument("--request-json", required=True)
    parser.add_argument(
        "--case", choices=["SUPPORTED", "CONTRADICTED", "UNCLEAR"], required=True
    )
    parser.add_argument("--recorded-fixture", default=str(DEFAULT_FIXTURE))
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = _parser()
    args = parser.parse_args(argv)
    if os.getenv("CI", "").casefold() in {"1", "true", "yes"}:
        parser.error("Decision Board claim live comparison is forbidden in CI")
    command_value = os.getenv("DECISION_BOARD_CLAIM_LIVE_PROVIDER_COMMAND", "").strip()
    model = os.getenv("DECISION_BOARD_CLAIM_LIVE_MODEL", "").strip()
    if not command_value or not model:
        parser.error(
            "set DECISION_BOARD_CLAIM_LIVE_PROVIDER_COMMAND and "
            "DECISION_BOARD_CLAIM_LIVE_MODEL explicitly"
        )
    command = shlex.split(command_value)
    if not command:
        parser.error("provider command is empty")
    request = json.loads(Path(args.request_json).read_text(encoding="utf-8"))
    if type(request) is not dict or request.get("model") != model:
        parser.error(
            "request JSON must be a Responses request for the configured model"
        )
    fixture = json.loads(Path(args.recorded_fixture).read_text(encoding="utf-8"))
    recorded = fixture["cases"][args.case]["response"]
    expected = decode_claim_response_v0(recorded, expected_model=fixture["model"])
    timeout = float(os.getenv("DECISION_BOARD_CLAIM_LIVE_TIMEOUT_SECONDS", "15"))
    completed = subprocess.run(
        command,
        input=json.dumps(request, ensure_ascii=False, sort_keys=True),
        capture_output=True,
        text=True,
        timeout=timeout,
        check=False,
    )
    if completed.returncode != 0:
        print("provider command failed", file=sys.stderr)
        return 2
    if len(completed.stdout.encode("utf-8")) > _MAX_PROVIDER_OUTPUT_BYTES:
        print("provider response exceeded the safe bound", file=sys.stderr)
        return 2
    live_response = json.loads(completed.stdout)
    actual = decode_claim_response_v0(live_response, expected_model=model)
    passed = actual == expected
    print(json.dumps({"case": args.case, "status": "PASS" if passed else "FAIL"}))
    return 0 if passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
