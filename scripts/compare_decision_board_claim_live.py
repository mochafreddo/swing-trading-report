"""Explicit opt-in comparison of recorded and injected live claim Responses."""

from __future__ import annotations

import argparse
import json
import math
import os
import re
import selectors
import shlex
import signal
import subprocess
import sys
import time
from contextlib import suppress
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from sab.decision_board.claim_responses import (  # noqa: E402
    build_claim_responses_request_v0,
    decode_claim_response_v0,
)
from sab.decision_board.claims import ClaimVerifierRequestV0  # noqa: E402
from sab.decision_board.instruments import InstrumentRefV0  # noqa: E402

DEFAULT_FIXTURE = (
    ROOT
    / "tests"
    / "fixtures"
    / "decision_board"
    / "claim-verifier-responses-recorded.json"
)
_MAX_PROVIDER_OUTPUT_BYTES = 1_048_576
_MAX_PROVIDER_ERROR_BYTES = 65_536
_REQUEST_FIELDS = {
    "claim_id",
    "claim_text",
    "instrument",
    "article_content_hash",
    "article_text",
}
_INSTRUMENT_FIELDS = {
    "market",
    "canonical_ticker",
    "exchange",
    "company_name",
    "identity_source",
    "identity_version",
}
_SAFE_ENV_NAME = re.compile(r"[A-Z][A-Z0-9_]{0,63}\Z")
_FORBIDDEN_ENV_NAME = re.compile(
    r"(?:API|AUTH|CREDENTIAL|KEY|OPENAI|PASSWORD|SECRET|SUPABASE|TOKEN|TOSS)", re.I
)


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


def _strict_public_request(value: object, *, model: str) -> dict[str, object]:
    if type(value) is not dict or set(value) != _REQUEST_FIELDS:
        raise ValueError("request JSON must contain only public claim request fields")
    instrument_value = value["instrument"]
    if (
        type(instrument_value) is not dict
        or set(instrument_value) != _INSTRUMENT_FIELDS
    ):
        raise ValueError("request instrument fields are invalid")
    instrument = InstrumentRefV0(**instrument_value)
    scalar_names = ("claim_id", "claim_text", "article_content_hash", "article_text")
    if any(type(value[name]) is not str for name in scalar_names):
        raise ValueError("request public values must be strings")
    content_hash = value["article_content_hash"]
    if re.fullmatch(r"sha256:[0-9a-f]{64}", content_hash) is None:
        raise ValueError("request article hash is invalid")
    request = ClaimVerifierRequestV0(
        claim_id=value["claim_id"],
        claim_text=value["claim_text"],
        instrument=instrument,
        article_content_hash=content_hash,
        article_text=value["article_text"],
    )
    return build_claim_responses_request_v0(request, model=model)


def _provider_environment() -> dict[str, str]:
    environment = {"PATH": os.defpath}
    allowlist = os.getenv("DECISION_BOARD_CLAIM_LIVE_SAFE_ENV", "")
    for raw_name in allowlist.split(","):
        name = raw_name.strip()
        if not name:
            continue
        if _SAFE_ENV_NAME.fullmatch(name) is None or _FORBIDDEN_ENV_NAME.search(name):
            raise ValueError("provider environment allowlist contains an unsafe name")
        if name in os.environ:
            environment[name] = os.environ[name]
    return environment


def _run_bounded(
    command: list[str],
    *,
    request_text: str,
    timeout: float,
) -> tuple[int, bytes, bytes]:
    if not math.isfinite(timeout) or timeout <= 0 or timeout > 300:
        raise ValueError("provider timeout is invalid")
    process = subprocess.Popen(
        command,
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        env=_provider_environment(),
        start_new_session=True,
    )
    assert process.stdin is not None
    assert process.stdout is not None
    assert process.stderr is not None
    request_bytes = request_text.encode("utf-8")
    written = 0
    os.set_blocking(process.stdin.fileno(), False)
    os.set_blocking(process.stdout.fileno(), False)
    os.set_blocking(process.stderr.fileno(), False)
    selector = selectors.DefaultSelector()
    selector.register(process.stdin, selectors.EVENT_WRITE, ("stdin", None))
    selector.register(process.stdout, selectors.EVENT_READ, ("stdout", bytearray()))
    selector.register(process.stderr, selectors.EVENT_READ, ("stderr", bytearray()))
    deadline = time.monotonic() + timeout
    buffers: dict[str, bytearray] = {}
    try:
        while selector.get_map():
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise TimeoutError("provider command timed out")
            events = selector.select(min(remaining, 0.1))
            for key, _mask in events:
                name, buffer = key.data
                if name == "stdin":
                    try:
                        count = os.write(
                            key.fd, request_bytes[written : written + 65_536]
                        )
                    except BlockingIOError:
                        continue
                    written += count
                    if written == len(request_bytes):
                        selector.unregister(key.fileobj)
                        process.stdin.close()
                    continue
                chunk = os.read(key.fd, 65_536)
                if not chunk:
                    selector.unregister(key.fileobj)
                    buffers[name] = buffer
                    continue
                buffer.extend(chunk)
                limit = (
                    _MAX_PROVIDER_OUTPUT_BYTES
                    if name == "stdout"
                    else _MAX_PROVIDER_ERROR_BYTES
                )
                if len(buffer) > limit:
                    raise OverflowError(f"provider {name} exceeded the safe bound")
        return_code = process.wait(timeout=max(0.0, deadline - time.monotonic()))
        return return_code, bytes(buffers["stdout"]), bytes(buffers["stderr"])
    except BaseException:
        with suppress(ProcessLookupError):
            os.killpg(process.pid, signal.SIGKILL)
        process.wait()
        raise
    finally:
        selector.close()


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
    try:
        raw_request = json.loads(Path(args.request_json).read_text(encoding="utf-8"))
        request = _strict_public_request(raw_request, model=model)
        fixture = json.loads(Path(args.recorded_fixture).read_text(encoding="utf-8"))
        recorded = fixture["cases"][args.case]["response"]
        expected = decode_claim_response_v0(recorded, expected_model=fixture["model"])
        timeout = float(os.getenv("DECISION_BOARD_CLAIM_LIVE_TIMEOUT_SECONDS", "15"))
        return_code, stdout, _stderr = _run_bounded(
            command,
            request_text=json.dumps(request, ensure_ascii=False, sort_keys=True),
            timeout=timeout,
        )
        if return_code != 0:
            print("provider command failed", file=sys.stderr)
            return 2
        live_response = json.loads(stdout)
        actual = decode_claim_response_v0(live_response, expected_model=model)
    except OverflowError:
        parser.error("provider output exceeded the safe bound")
    except TimeoutError:
        parser.error("provider command timed out")
    except OSError:
        parser.error("local comparison input or provider command is unavailable")
    except TypeError, ValueError:
        parser.error("local comparison input or provider response is invalid")
    passed = actual == expected
    print(json.dumps({"case": args.case, "status": "PASS" if passed else "FAIL"}))
    return 0 if passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
