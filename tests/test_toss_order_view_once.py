"""Loopback viewer request/privacy contracts, without actual sockets or provider calls."""

import io
import json
from unittest.mock import Mock

import pytest
from scripts import run_toss_order_view_once as view


@pytest.fixture
def server(monkeypatch: pytest.MonkeyPatch):
    def initialize(instance, *args):
        instance.socket = Mock()
        instance.server_port = 43119

    monkeypatch.setattr(view.HTTPServer, "__init__", initialize)
    instance = view.OrderViewServer({}, "2026-08-07", "2026-09-05", synthetic=True)
    yield instance
    instance.server_close()


def request(
    server, path="/", method="GET", *, headers=None, body=b"", authenticated=True
):
    values = {"Host": "127.0.0.1:43119"}
    if authenticated:
        values["Cookie"] = f"{view.COOKIE}={server.session}"
    if method == "POST":
        values.update(
            {
                "Origin": server.origin,
                "X-Local-View": "1",
                "Content-Type": "application/json",
                "Content-Length": str(len(body)),
            }
        )
    values.update(headers or {})
    incoming = (
        f"{method} {path} HTTP/1.0\r\n"
        + "".join(f"{key}: {value}\r\n" for key, value in values.items())
        + "\r\n"
    )

    class Socket:
        def __init__(self):
            self.output = bytearray()

        def makefile(self, *args):
            return io.BytesIO(incoming.encode() + body)

        def settimeout(self, value):
            pass

        def sendall(self, data):
            self.output.extend(data)

    connection = Socket()
    view.OrderViewHandler(connection, ("127.0.0.1", 1), server)
    head, payload = bytes(connection.output).split(b"\r\n\r\n", 1)
    return head.decode(), payload


def test_default_denies_live_server_before_binding(server):
    with pytest.raises(ValueError, match="APPROVAL_REQUIRED"):
        view.OrderViewServer({}, "2026-08-07", "2026-09-05")


def test_html_is_authenticated_static_no_store_and_no_private_payload(server):
    head, body = request(server, authenticated=False)
    assert "403" in head and not body
    head, body = request(server)
    assert "200" in head and "Cache-Control: no-store" in head
    assert "frame-ancestors 'none'" in head and "default-src 'none'" in head
    assert "X-Frame-Options: DENY" in head
    assert "SYNTHETIC_ONLY" in body.decode()
    assert server.session.encode() not in body
    assert b"SYNTHA" not in body
    assert server.spent is False


@pytest.mark.parametrize(
    "headers",
    [
        {"Host": "evil.example"},
        {"Origin": "http://evil.example"},
        {"Sec-Fetch-Site": "cross-site"},
        {"X-Local-View": "0"},
        {"Content-Type": "text/plain"},
        {"Content-Length": "3"},
        {"Transfer-Encoding": "chunked"},
        {"Cookie": "wrong"},
    ],
)
def test_rejected_requests_do_not_consume_query(server, headers):
    head, body = request(server, "/query", "POST", headers=headers, body=b"{}")
    assert "403" in head and not body
    assert server.spent is False


def test_only_exact_query_method_and_body_are_accepted(server):
    for path, method, body in [
        ("/query", "GET", b""),
        ("/query?retry=1", "POST", b"{}"),
        ("/query", "POST", b"[]"),
        ("/orders", "POST", b"{}"),
        ("/query", "DELETE", b""),
    ]:
        head, _ = request(server, path, method, body=body)
        assert "200" not in head
        assert server.spent is False


def test_success_once_and_reload_never_restore_or_requery(server):
    head, body = request(server, "/query", "POST", body=b"{}")
    result = json.loads(body)
    assert "no-store" in head
    assert result["state"] == "COMPLETE" and len(result["rows"]) == 3
    assert server.spent is True
    assert "SYNTHA" not in json.dumps(server.summary)
    _, second = request(server, "/query", "POST", body=b"{}")
    assert json.loads(second) == {"state": "UNAVAILABLE", "rows": []}
    _, html = request(server)
    assert b"disabled" in html and b"SYNTHA" not in html


def test_live_latch_and_credentials_are_consumed_even_on_failure(
    server, monkeypatch, capsys
):
    server.synthetic = False
    server.credentials.update(
        {
            "client_id": "PRIVATE-ID",
            "client_secret": "PRIVATE-SECRET",
            "account_seq": "1",
        }
    )
    calls = []

    def fail(*args, **kwargs):
        assert server.spent
        calls.append(1)
        raise RuntimeError("PRIVATE-EXCEPTION")

    monkeypatch.setattr(view, "run_toss_order_probe_t21", fail)
    assert server.query() == {"state": "FAILED", "rows": []}
    assert server.credentials == {}
    assert server.query() == {"state": "UNAVAILABLE", "rows": []}
    assert calls == [1]
    assert "PRIVATE" not in json.dumps(server.summary)
    assert capsys.readouterr() == ("", "")


def test_expired_session_never_queries(server, monkeypatch):
    monkeypatch.setattr(view.time, "monotonic", lambda: server.expires_at + 1)
    head, _ = request(server, "/query", "POST", body=b"{}")
    assert "403" in head and not server.spent
