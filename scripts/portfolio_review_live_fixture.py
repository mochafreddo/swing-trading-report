"""Bounded HTTP test double for a verified disposable R2 database, never production."""

from __future__ import annotations

import json
import os
import signal
import subprocess
import threading
import time
from collections.abc import Callable
from contextlib import suppress
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from typing import Any, cast
from urllib.request import ProxyHandler, build_opener
from uuid import UUID, uuid4

from sab.portfolio_mandate.review_import import (
    ApprovalBinding,
    EvidenceBinding,
    canonical,
    import_review_packet,
    replay_review_packet,
)
from sab.portfolio_mandate.review_policy import _hash, _json
from sab.portfolio_mandate.review_store import ReviewStore, compiler_sql

TOKEN = "synthetic-review-only"
COMMANDS = {
    "compile",
    "block",
    "correct",
    "unlinked",
    "ambiguous",
    "no_action",
    "replay",
    "receive",
}


class SyntheticReview:
    """Fixed cohort and synthetic bindings injected by the disposable DB test.

    The process holds no credential loader or arbitrary connection/SQL endpoint.
    A single HTTP worker serializes this small, bounded manual test session.
    """

    def __init__(
        self, sql: Callable[[str], str], bundle: dict[str, Any], versions: list[str]
    ):
        self.sql = sql
        self.packet = json.loads(bundle["packet"])
        self.owner = str(UUID(self.packet["owner_id"]))
        self.versions = [str(UUID(v)) for v in versions]
        original = Path(
            "tests/fixtures/portfolio_mandate/portfolio-mandate-private-v1-preview.synthetic.json"
        ).read_text()
        if any(
            a["source_document"] != original for a in self.packet["approvals"]
        ) or any(
            e["content"] != "Synthetic PRIMARY source; no provider request."
            for e in self.packet["sources"]
        ):
            raise ValueError("SYNTHETIC_BINDINGS_REQUIRED")
        self.history: dict[str, tuple[dict[str, str], Callable[[], Any]]] = {}
        self.store = ReviewStore(
            lambda name, params: json.loads(
                self.sql(compiler_sql(name, params)) or "null"
            ),
            enabled=True,
        )

    def authenticated(self, statement: str) -> str:
        return self.sql(
            "set role authenticated; set request.jwt.claims='"
            + canonical({"role": "authenticated", "sub": self.owner})
            + "'; "
            + statement
        )

    def read(self, *, input_only: bool = False) -> dict[str, Any]:
        versions = (
            [self.packet["approvals"][0]["version_id"]] if input_only else self.versions
        )
        ids = ",".join(f"'{UUID(v)!s}'::uuid" for v in versions)
        name = (
            "read_portfolio_review_r1"
            if input_only
            else "read_portfolio_review_store_r2"
        )
        return cast(
            dict[str, Any],
            json.loads(self.authenticated(f"select public.{name}(array[{ids}]);")),
        )

    def command(self, body: object) -> dict[str, Any]:
        if not isinstance(body, dict) or set(body) != {
            "command",
            "request_id",
            "run_id",
        }:
            raise ValueError("INVALID_COMMAND")
        if body["command"] not in COMMANDS:
            raise ValueError("INVALID_COMMAND")
        request_id, run_id = str(UUID(body["request_id"])), str(UUID(body["run_id"]))
        if body["request_id"] != request_id or body["run_id"] != run_id:
            raise ValueError("INVALID_COMMAND")
        if request_id in self.history:
            previous, retry = self.history[request_id]
            if previous != body:
                raise ValueError("REQUEST_CONFLICT")
            value = retry()  # Ordinary writes retry with the original bytes.
            return {
                "ok": True,
                "duplicate": True,
                **(
                    {"verification": value}
                    if body["command"] in {"replay", "receive"}
                    else {}
                ),
            }
        if len(self.history) >= 128:
            raise ValueError("SESSION_LIMIT")
        current = next(r for r in self.read()["rows"] if r["run_id"] is not None)
        if current["run_id"] != run_id:
            raise ValueError("STALE_SELECTION")
        command = body["command"]
        if command == "replay":

            def execute() -> Any:
                bundle = json.loads(
                    self.sql(
                        "select jsonb_build_object('packet',p.packet,'packet_sha256',p.packet_sha256,'projection',r.projection,'projection_sha256',r.projection_sha256) "
                        "from public.portfolio_mandate_review_packet_r2 p join public.portfolio_mandate_review_run_r2 r on r.run_id=p.packet_id "
                        f"where r.run_id='{run_id}' and r.owner_id='{self.owner}';"
                    )
                )
                replay_review_packet(bundle)
                return {
                    "kind": "REPLAY",
                    "run_id": run_id,
                    "matched": True,
                    "packet_sha256": bundle["packet_sha256"],
                    "projection_sha256": bundle["projection_sha256"],
                }
        elif command == "receive":

            def execute() -> Any:
                # Existing sink processes this synthetic owner's eligible runs only.
                count = int(
                    self.sql(
                        "set role portfolio_mandate_review_compiler_r2; "
                        f"select portfolio_mandate_private.receive_local_outbox_r2('{self.owner}');"
                    )
                )
                counts = json.loads(
                    self.sql(
                        "select jsonb_build_object('total',count(*),'received',count(o.received_at),'pending',count(*)-count(o.received_at)) "
                        "from public.portfolio_mandate_review_outbox_r2 o join public.portfolio_mandate_review_decision_r2 d on d.decision_id=o.decision_id "
                        "join public.portfolio_mandate_review_run_r2 r on r.run_id=d.run_id "
                        f"where r.run_id='{run_id}' and r.owner_id='{self.owner}';"
                    )
                )
                return {
                    "kind": "LOCAL_SINK",
                    "run_id": run_id,
                    "scope": "SYNTHETIC_OWNER",
                    "destination": "LOCAL_REVIEW_SINK",
                    "newly_received": count,
                    "external_sends": 0,
                    **counts,
                }
        elif command in {"compile", "block", "correct"}:
            raw = self.read(input_only=True)
            value = json.loads(raw["payload"])
            row = value["rows"][0]
            if command == "block":
                row["broker"] = None
            if command == "correct":
                parents = {o["supersedes_observation_id"] for o in row["observations"]}
                old = next(
                    o for o in row["observations"] if o["observation_id"] not in parents
                )
                row["observations"].append(
                    {
                        **old,
                        "observation_id": str(uuid4()),
                        "supersedes_observation_id": old["observation_id"],
                        "recorded_at": value["read_at"],
                        "observed_value": "2" if old["observed_value"] != "2" else "-2",
                    }
                )
            payload = canonical(value)
            bundle = import_review_packet(
                {"payload": payload, "payload_sha256": _hash(payload)},
                owner_id=self.owner,
                approvals=tuple(ApprovalBinding(**a) for a in self.packet["approvals"]),
                evidence=tuple(EvidenceBinding(**e) for e in self.packet["sources"]),
                **self.packet["parameters"],
            )
            # A correction retains the trigger and appends the next run revision.
            trigger, revision = self.sql(
                f"select trigger_id::text || '|' || revision::text from public.portfolio_mandate_review_run_r2 where run_id='{run_id}';"
            ).split("|")

            def execute() -> Any:
                return self.store.commit(
                    bundle,
                    run_id=request_id,
                    owner_id=self.owner,
                    trigger_id=str(UUID(trigger)),
                    revision=int(revision) + 1,
                    supersedes=run_id,
                )
        else:
            outcomes = current["outcomes"]
            parent = str(UUID(outcomes[-1]["outcome_id"])) if outcomes else None
            if command == "no_action":
                parent_sql = f"'{parent}'" if parent else "null"

                def execute() -> Any:
                    return self.authenticated(
                        f"select public.confirm_portfolio_review_no_action_r2('{run_id}','{request_id}',{parent_sql});"
                    )
            else:

                def execute() -> Any:
                    return self.store.record_outcome(
                        owner_id=self.owner,
                        run_id=run_id,
                        outcome_id=request_id,
                        status=command.upper(),
                        supersedes=parent,
                    )

        value = execute()
        # Retrying an acknowledged receipt cannot consume records created later.
        # A new click/request is required to process a new batch for this owner.
        retry = (lambda: value) if command == "receive" else execute
        self.history[request_id] = (dict(body), retry)
        return {
            "ok": True,
            "duplicate": False,
            **({"verification": value} if command in {"replay", "receive"} else {}),
        }


def handler_for(review: SyntheticReview) -> type[BaseHTTPRequestHandler]:
    class Handler(BaseHTTPRequestHandler):
        def setup(self) -> None:
            super().setup()
            self.connection.settimeout(10)

        def log_message(self, format: str, *args: Any) -> None:
            pass  # Never log request bodies, bindings or SQL failures.

        def respond(self, status: int, body: object) -> None:
            raw = canonical(body).encode()
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Cache-Control", "no-store")
            self.send_header("Content-Length", str(len(raw)))
            self.end_headers()
            self.wfile.write(raw)

        def dispatch(self) -> None:
            if (
                self.headers.get("Host")
                != f"127.0.0.1:{cast(HTTPServer, self.server).server_port}"
                or self.headers.get("Authorization") != f"Bearer {TOKEN}"
                or self.headers.get("Origin") is not None
                or self.headers.get("Transfer-Encoding") is not None
            ):
                self.respond(403, {"error": "FIXTURE_FORBIDDEN"})
                return
            try:
                if self.command == "GET" and self.path == "/binding":
                    result: object = {
                        "ownerId": review.owner,
                        "versionIds": review.versions,
                    }
                elif self.command == "GET" and self.path == "/auth/v1/user":
                    result = {
                        "id": review.owner,
                        "role": "authenticated",
                        "is_anonymous": False,
                    }
                elif self.command == "POST":
                    size = int(self.headers.get("Content-Length", "0"))
                    if (
                        not 0 < size <= 4096
                        or self.headers.get("Content-Type") != "application/json"
                    ):
                        raise ValueError
                    body = _json(self.rfile.read(size).decode("utf-8"))
                    if self.path == "/rest/v1/rpc/read_portfolio_review_store_r2":
                        if body != {"p_version_ids": review.versions}:
                            raise ValueError
                        result = review.read()
                    elif self.path == "/command":
                        result = review.command(body)
                    else:
                        raise ValueError
                else:
                    raise ValueError
                self.respond(200, result)
            except Exception:
                self.respond(409, {"error": "FIXTURE_REQUEST_REJECTED"})

        do_GET = dispatch
        do_POST = dispatch

    return Handler


def exercise_live_ui(review: SyntheticReview, *, seconds: int = 0) -> None:
    """Called only inside the existing identity-verified disposable DB fixture."""
    with HTTPServer(("127.0.0.1", 0), handler_for(review)) as server:
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        environment = {
            "PATH": os.environ["PATH"],
            "PORTFOLIO_FIXTURE_WEB_PORT": "43317",
            "PORTFOLIO_FIXTURE_DATA_PORT": "43318",
            "PORTFOLIO_REVIEW_LIVE_PORT": str(server.server_port),
        }
        process = None
        try:
            with Path("tmp/portfolio-review-live.local.log").open("w") as log:
                process = subprocess.Popen(
                    ["bash", "scripts/portfolio_review_fixture.sh"],
                    env=environment,
                    stdout=log,
                    stderr=log,
                    start_new_session=True,
                )
                opener = build_opener(ProxyHandler({}))
                deadline = time.monotonic() + 90
                while True:
                    if process.poll() is not None or time.monotonic() > deadline:
                        raise RuntimeError("FIXTURE_WEB_UNAVAILABLE")
                    try:
                        with opener.open(
                            "http://127.0.0.1:43317/login", timeout=2
                        ) as response:
                            if response.status == 200:
                                break
                    except OSError:
                        time.sleep(0.2)
                if seconds:
                    # Bounded manual window; subprocess liveness checked each second.
                    deadline = time.monotonic() + seconds
                    while time.monotonic() < deadline:
                        if process.poll() is not None:
                            raise RuntimeError("FIXTURE_WEB_STOPPED")
                        time.sleep(1)
                else:
                    subprocess.run(
                        [
                            "pnpm",
                            "exec",
                            "playwright",
                            "test",
                            "--config",
                            "playwright.portfolio-live.config.ts",
                        ],
                        cwd="web",
                        env={"PATH": os.environ["PATH"], "SAB_SKIP_ROOT_ENV": "1"},
                        stdout=log,
                        stderr=log,
                        check=True,
                        timeout=180,
                    )
        finally:
            if process is not None:
                with suppress(ProcessLookupError):
                    os.killpg(process.pid, signal.SIGTERM)
                process.wait(timeout=15)
            server.shutdown()
            thread.join(timeout=10)
