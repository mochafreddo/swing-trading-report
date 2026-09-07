"""Ephemeral loopback order viewer. No live invocation without explicit approval."""

from __future__ import annotations

import argparse
import json
import os
import resource
import secrets
import subprocess
import sys
import threading
import time
from datetime import date
from http.cookies import SimpleCookie
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from typing import Any, cast

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from sab.portfolio_mandate.toss_order_probe import (  # noqa: E402
    _aggregate,
    _order_view_row,
    run_toss_order_probe_t21,
)

COOKIE = "toss_order_view_session"


class OrderViewServer(HTTPServer):
    """Single-threaded query owner; latch is consumed before entering the probe."""

    def __init__(
        self,
        credentials: dict[str, str],
        from_date: str,
        to_date: str,
        *,
        approved: bool = False,
        synthetic: bool = False,
    ) -> None:
        if not synthetic and approved is not True:
            raise ValueError("APPROVAL_REQUIRED")
        start, end = date.fromisoformat(from_date), date.fromisoformat(to_date)
        if (
            start.isoformat() != from_date
            or end.isoformat() != to_date
            or not 0 <= (end - start).days < 30
        ):
            raise ValueError("INVALID_DATE_RANGE")
        self.credentials = credentials
        self.from_date, self.to_date = from_date, to_date
        self.synthetic = synthetic
        self.session = secrets.token_urlsafe(32)
        self.spent = False
        self.summary: dict[str, Any] | None = None
        self.expires_at = time.monotonic() + 600
        super().__init__(("127.0.0.1", 0), OrderViewHandler)
        self.timeout = 0.25
        self.origin = f"http://127.0.0.1:{self.server_port}"

    def handle_error(self, request: Any, client_address: Any) -> None:
        # BaseServer otherwise prints tracebacks, potentially containing private data.
        pass

    def query(self) -> dict[str, Any]:
        if self.spent or time.monotonic() >= self.expires_at:
            return {"state": "UNAVAILABLE", "rows": []}
        self.spent = True
        rows: list[dict[str, str | None]] = []
        try:
            if self.synthetic:
                fixture = json.loads(
                    (
                        ROOT / "web/fixtures/toss-order-history.synthetic.json"
                    ).read_text()
                )
                for page in fixture["pages"]:
                    for order in page["response"]["result"]["orders"]:
                        _aggregate(order)
                        row = _order_view_row(order)
                        if (
                            self.from_date
                            <= str(row["orderedAtKst"])[:10]
                            <= self.to_date
                        ):
                            rows.append(row)
                self.summary = {
                    "result_code": "SYNTHETIC_COMPLETE",
                    "provider_calls": 0,
                }
            else:
                self.summary = run_toss_order_probe_t21(
                    self.credentials.pop("client_id", ""),
                    self.credentials.pop("client_secret", ""),
                    self.credentials.pop("account_seq", ""),
                    self.from_date,
                    self.to_date,
                    approved=True,
                    _display_rows=rows,
                )
                if self.summary["result_code"] not in {
                    "COMPLETE_ORDER_AGGREGATE",
                    "COMPLETE_NO_ORDERS",
                }:
                    rows.clear()
                    return {"state": "FAILED", "rows": []}
            return {"state": "COMPLETE" if rows else "EMPTY", "rows": rows}
        except Exception:
            self.summary = {"result_code": "LOCAL_VIEW_FAILED"}
            return {"state": "FAILED", "rows": []}
        finally:
            self.credentials.clear()

    def server_close(self) -> None:
        self.credentials.clear()
        self.session = ""
        super().server_close()


class OrderViewHandler(BaseHTTPRequestHandler):
    def setup(self) -> None:
        super().setup()
        self.connection.settimeout(2)

    def log_message(self, format: str, *args: Any) -> None:
        pass

    def send_error(
        self, code: int, message: str | None = None, explain: str | None = None
    ) -> None:
        self.reply(code, b"", "text/plain")

    def reply(
        self, status: int, body: bytes, content_type: str, nonce: str = ""
    ) -> None:
        self.send_response(status)
        self.send_header("Content-Type", content_type + "; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store, max-age=0")
        self.send_header("Pragma", "no-cache")
        self.send_header("Referrer-Policy", "no-referrer")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("X-Frame-Options", "DENY")
        self.send_header("Cross-Origin-Resource-Policy", "same-origin")
        self.send_header(
            "Permissions-Policy", "camera=(), microphone=(), geolocation=()"
        )
        self.send_header(
            "Content-Security-Policy",
            "default-src 'none'; base-uri 'none'; frame-ancestors 'none'; "
            "form-action 'none'; connect-src 'self'; "
            f"script-src 'nonce-{nonce}'; style-src 'nonce-{nonce}'",
        )
        self.send_header("Connection", "close")
        self.end_headers()
        self.wfile.write(body)
        self.close_connection = True

    def authorized(self) -> bool:
        server = cast(OrderViewServer, self.server)
        if (
            self.headers.get_all("Host") != [server.origin.removeprefix("http://")]
            or self.headers.get("Sec-Fetch-Site") not in {None, "same-origin", "none"}
            or time.monotonic() >= server.expires_at
        ):
            return False
        cookie = SimpleCookie()
        try:
            cookie.load(self.headers.get("Cookie", ""))
            return COOKIE in cookie and secrets.compare_digest(
                cookie[COOKIE].value, server.session
            )
        except Exception:
            return False

    def do_GET(self) -> None:
        if not self.authorized():
            self.reply(403, b"", "text/plain")
            return
        if self.path != "/":
            self.reply(404, b"", "text/plain")
            return
        server = cast(OrderViewServer, self.server)
        nonce = secrets.token_urlsafe(24)
        body = (ROOT / "scripts/toss_order_view.html").read_text()
        body = (
            body.replace("__NONCE__", nonce)
            .replace("__MODE__", "SYNTHETIC_ONLY" if server.synthetic else "LIVE_ONCE")
            .replace("__FROM__", server.from_date)
            .replace("__TO__", server.to_date)
            .replace("__DISABLED__", "disabled" if server.spent else "")
        )
        self.reply(200, body.encode(), "text/html", nonce)

    def do_POST(self) -> None:
        server = cast(OrderViewServer, self.server)
        if (
            not self.authorized()
            or self.headers.get_all("Origin") != [server.origin]
            or self.headers.get("X-Local-View") != "1"
            or self.headers.get("Content-Type") != "application/json"
            or self.headers.get("Transfer-Encoding") is not None
            or self.headers.get_all("Content-Length") != ["2"]
        ):
            self.reply(403, b"", "text/plain")
            return
        if self.path != "/query" or self.rfile.read(2) != b"{}":
            self.reply(400, b"", "text/plain")
            return
        body = server.query()
        try:
            self.reply(200, json.dumps(body).encode(), "application/json")
        finally:
            body.clear()


def run_local_order_view(
    credentials: dict[str, str],
    from_date: str,
    to_date: str,
    *,
    approved: bool = False,
    synthetic: bool = False,
) -> None:
    """Start a new non-persistent browser; stdin QUERY is one explicit agent click."""
    resource.setrlimit(resource.RLIMIT_CORE, (0, 0))
    with OrderViewServer(
        credentials, from_date, to_date, approved=approved, synthetic=synthetic
    ) as server:
        # Only OS/runtime paths reach the browser controller, never provider credentials.
        browser_env = {
            key: os.environ[key]
            for key in ("PATH", "HOME", "TMPDIR")
            if key in os.environ
        }
        browser = subprocess.Popen(
            ["node", str(ROOT / "web/scripts/toss-order-view-browser.mjs")],
            stdin=subprocess.PIPE,
            text=True,
            env=browser_env,
        )
        assert browser.stdin is not None
        browser.stdin.write(
            json.dumps({"origin": server.origin, "session": server.session}) + "\n"
        )
        browser.stdin.flush()

        def forward_controls() -> None:
            for line in sys.stdin:
                if line.strip() in {"QUERY", "CLOSE"} and browser.poll() is None:
                    try:
                        assert browser.stdin is not None
                        browser.stdin.write(line.strip() + "\n")
                        browser.stdin.flush()
                    except BrokenPipeError:
                        return

        threading.Thread(target=forward_controls, daemon=True).start()
        print("LOCAL_VIEW_READY", flush=True)
        while (
            browser.poll() is None
            and not server.spent
            and time.monotonic() < server.expires_at
        ):
            server.handle_request()
        if server.summary is not None:
            print(json.dumps(server.summary, sort_keys=True), flush=True)
    print("LOCAL_SERVER_CLOSED", flush=True)
    browser.wait()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--synthetic", action="store_true")
    args = parser.parse_args()
    if not args.synthetic:
        parser.error(
            "Use --synthetic; live mode requires a separately approved in-memory caller."
        )
    run_local_order_view({}, "2026-08-07", "2026-09-05", synthetic=True)
