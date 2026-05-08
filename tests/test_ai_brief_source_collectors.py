from __future__ import annotations

import datetime as dt
import json
import threading
import time
import types
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

import pytest
import requests  # type: ignore[import-untyped]
from sab import ai_brief_source_collectors as collectors
from sab import ai_brief_sources
from sab.ai_brief_source_collectors import (
    MAX_FEED_BYTES,
    MAX_FEED_CATALOG_BYTES,
    AiBriefSourceCollectorError,
    collect_ai_brief_sources,
    parse_collect_now,
)
from sab.ai_brief_source_eval import evaluate_ai_brief_source_report
from scripts.collect_ai_brief_sources import main as collect_sources_main

FEED_FIXTURE_DIR = Path(__file__).parent / "fixtures" / "ai_brief_source_feeds"
SOURCE_FIXTURE_DIR = Path(__file__).parent / "fixtures" / "ai_brief_sources"
COLLECT_NOW = dt.datetime(2026, 5, 6, 12, 0, tzinfo=dt.UTC)


class _MockFeedResponse:
    def __init__(self, body: bytes, *, status_code: int = 200) -> None:
        self.body = body
        self.status_code = status_code
        self.closed = False

    def iter_content(self, chunk_size: int):
        for idx in range(0, len(self.body), chunk_size):
            yield self.body[idx : idx + chunk_size]

    def close(self) -> None:
        self.closed = True


class _MockFeedSession:
    def __init__(self, responses: dict[str, object]) -> None:
        self.responses = responses
        self.calls: list[dict[str, object]] = []
        self.closed = False
        self.trust_env = True

    def get(
        self,
        url: str,
        *,
        timeout: float,
        stream: bool,
        allow_redirects: bool,
    ) -> object:
        self.calls.append(
            {
                "url": url,
                "timeout": timeout,
                "stream": stream,
                "allow_redirects": allow_redirects,
            }
        )
        response = self.responses[url]
        if isinstance(response, BaseException):
            raise response
        return response

    def close(self) -> None:
        self.closed = True


def _install_mock_feed_session(
    monkeypatch: pytest.MonkeyPatch,
    session: _MockFeedSession,
    *,
    resolved_ip: str = "93.184.216.34",
) -> None:
    monkeypatch.setattr(
        ai_brief_sources.socket,
        "getaddrinfo",
        lambda *_args, **_kwargs: [
            (
                ai_brief_sources.socket.AF_INET,
                ai_brief_sources.socket.SOCK_STREAM,
                0,
                "",
                (resolved_ip, 443),
            )
        ],
    )
    monkeypatch.setattr(
        collectors,
        "requests",
        types.SimpleNamespace(
            Session=lambda: session,
            Timeout=requests.Timeout,
            RequestException=requests.RequestException,
        ),
        raising=False,
    )


@pytest.fixture(autouse=True)
def _mock_source_url_dns(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        ai_brief_sources.socket,
        "getaddrinfo",
        lambda *_args, **_kwargs: [
            (
                ai_brief_sources.socket.AF_INET,
                ai_brief_sources.socket.SOCK_STREAM,
                0,
                "",
                ("93.184.216.34", 443),
            )
        ],
    )


def _feed_fixture(name: str) -> str:
    return (FEED_FIXTURE_DIR / name).as_posix()


def _source_fixture(name: str) -> str:
    return (SOURCE_FIXTURE_DIR / name).as_posix()


def _assert_timeout_tuple_not_expired(
    timeout: object,
    *,
    requested_timeout_seconds: float,
) -> None:
    assert isinstance(timeout, tuple)
    connect_timeout, read_timeout = timeout
    assert isinstance(connect_timeout, float)
    assert isinstance(read_timeout, float)
    assert 0 < connect_timeout <= requested_timeout_seconds
    assert read_timeout == pytest.approx(min(connect_timeout, 1.0), abs=0.01)


def _issue_codes(result) -> set[str]:
    return {issue.code for issue in result.issues}


@pytest.mark.parametrize("url_field", ["url", "feed_url"])
def test_collect_fetches_https_feed_url_into_eval_compatible_payload(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    url_field: str,
) -> None:
    feed_url = "https://feeds.example.test/aapl.xml"
    catalog = tmp_path / "feeds.json"
    catalog.write_text(
        json.dumps(
            {
                "schema": "sab.ai_brief_source_feed_catalog.v1",
                "feeds": [{"ticker": "AAPL.NAS", url_field: feed_url}],
            }
        ),
        encoding="utf-8",
    )
    session = _MockFeedSession(
        {feed_url: _MockFeedResponse(Path(_feed_fixture("aapl.rss")).read_bytes())}
    )
    _install_mock_feed_session(monkeypatch, session)

    result = collect_ai_brief_sources(
        feed_catalog_path=catalog.as_posix(),
        now=COLLECT_NOW,
    )

    assert result.status == "PASS"
    assert result.sources == [
        {
            "ticker": "AAPL.NAS",
            "title": "Apple expands AI capacity for device roadmap",
            "url": "https://news.example.test/aapl-ai-capacity",
            "published_at": "2026-05-06T11:30:00+00:00",
        }
    ]
    assert session.calls[0]["url"] == feed_url
    _assert_timeout_tuple_not_expired(
        session.calls[0]["timeout"],
        requested_timeout_seconds=10.0,
    )
    assert session.calls[0]["stream"] is True
    assert session.calls[0]["allow_redirects"] is False

    source_report = tmp_path / "collected.sources.json"
    source_report.write_text(json.dumps(result.to_dict()), encoding="utf-8")
    eval_result = evaluate_ai_brief_source_report(
        entry_report_path=_source_fixture("entry.us.json"),
        source_report_path=source_report.as_posix(),
        minimum_coverage_ratio=0.0,
        now=COLLECT_NOW,
    )

    assert eval_result.status == "PASS"
    assert eval_result.summary["covered_ticker_count"] == 1


def test_collect_url_feed_respects_requested_ticker_filter(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    aapl_url = "https://feeds.example.test/aapl.xml"
    msft_url = "https://feeds.example.test/msft.xml"
    catalog = tmp_path / "feeds.json"
    catalog.write_text(
        json.dumps(
            {
                "schema": "sab.ai_brief_source_feed_catalog.v1",
                "feeds": [
                    {"ticker": "AAPL.NAS", "url": aapl_url},
                    {"ticker": "MSFT.NAS", "url": msft_url},
                ],
            }
        ),
        encoding="utf-8",
    )
    session = _MockFeedSession(
        {
            aapl_url: _MockFeedResponse(Path(_feed_fixture("aapl.rss")).read_bytes()),
            msft_url: AssertionError("filtered URL feed should not be fetched"),
        }
    )
    _install_mock_feed_session(monkeypatch, session)

    result = collect_ai_brief_sources(
        feed_catalog_path=catalog.as_posix(),
        tickers={"AAPL.NAS"},
        now=COLLECT_NOW,
    )

    assert result.status == "PASS"
    assert [source["ticker"] for source in result.sources] == ["AAPL.NAS"]
    assert [call["url"] for call in session.calls] == [aapl_url]


def test_collect_url_feed_filter_ignores_invalid_rows_for_other_tickers(
    tmp_path: Path,
) -> None:
    catalog = tmp_path / "feeds.json"
    feed_path = tmp_path / "aapl.rss"
    feed_path.write_bytes(Path(_feed_fixture("aapl.rss")).read_bytes())
    catalog.write_text(
        json.dumps(
            {
                "schema": "sab.ai_brief_source_feed_catalog.v1",
                "feeds": [
                    {
                        "ticker": "MSFT.NAS",
                        "path": "missing.rss",
                        "url": "https://feeds.example.test/msft.xml",
                    },
                    {"ticker": "AAPL.NAS", "path": feed_path.name},
                ],
            }
        ),
        encoding="utf-8",
    )

    result = collect_ai_brief_sources(
        feed_catalog_path=catalog.as_posix(),
        tickers={"AAPL.NAS"},
        now=COLLECT_NOW,
    )

    assert result.status == "PASS"
    assert [source["ticker"] for source in result.sources] == ["AAPL.NAS"]
    assert result.issues == []


@pytest.mark.parametrize(
    ("feed_url", "response", "expected_code", "expected_call_count"),
    [
        ("http://feeds.example.test/aapl.xml", None, "feed_url_invalid", 0),
        ("https://%31%32%37.0.0.1/aapl.xml", None, "feed_url_invalid", 0),
        ("https:\\\\127.0.0.1\\aapl.xml", None, "feed_url_invalid", 0),
        ("https://127.0.0.1/aapl.xml", None, "feed_url_invalid", 0),
        ("https://127.1/aapl.xml", None, "feed_url_invalid", 0),
        ("https://2130706433/aapl.xml", None, "feed_url_invalid", 0),
        ("https://100.64.0.1/aapl.xml", None, "feed_url_invalid", 0),
        ("https://[64:ff9b::a9fe:a9fe]/aapl.xml", None, "feed_url_invalid", 0),
        ("https://224.0.0.1/aapl.xml", None, "feed_url_invalid", 0),
        ("https://[ff02::1]/aapl.xml", None, "feed_url_invalid", 0),
        ("https://[::ffff:224.0.0.1]/aapl.xml", None, "feed_url_invalid", 0),
        ("https://[64:ff9b::e000:1]/aapl.xml", None, "feed_url_invalid", 0),
        ("https://[::7f00:1]/aapl.xml", None, "feed_url_invalid", 0),
        (
            "https://feeds.example.test/redirect.xml",
            _MockFeedResponse(b"", status_code=302),
            "feed_url_redirect",
            1,
        ),
        (
            "https://feeds.example.test/timeout.xml",
            requests.Timeout("slow feed"),
            "feed_url_timeout",
            1,
        ),
        (
            "https://feeds.example.test/http-503.xml",
            _MockFeedResponse(b"service unavailable", status_code=503),
            "feed_url_failed",
            1,
        ),
        (
            "https://feeds.example.test/invalid.xml",
            _MockFeedResponse(b"<rss><channel><item>"),
            "feed_url_failed",
            1,
        ),
        (
            "https://feeds.example.test/oversized.xml",
            _MockFeedResponse(b"x" * (MAX_FEED_BYTES + 1)),
            "feed_url_too_large",
            1,
        ),
    ],
)
def test_collect_reports_url_fetch_failures_as_warnings(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    feed_url: str,
    response: object,
    expected_code: str,
    expected_call_count: int,
) -> None:
    catalog = tmp_path / "feeds.json"
    catalog.write_text(
        json.dumps(
            {
                "schema": "sab.ai_brief_source_feed_catalog.v1",
                "feeds": [{"ticker": "AAPL.NAS", "url": feed_url}],
            }
        ),
        encoding="utf-8",
    )
    session = _MockFeedSession({feed_url: response})
    _install_mock_feed_session(monkeypatch, session)

    result = collect_ai_brief_sources(
        feed_catalog_path=catalog.as_posix(),
        now=COLLECT_NOW,
    )

    assert result.status == "WARN"
    assert result.sources == []
    assert _issue_codes(result) == {expected_code}
    assert len(session.calls) == expected_call_count


def test_collect_rejects_zero_feed_url_port_before_fetch(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    feed_url = "https://feeds.example.test:0/aapl.xml"
    catalog = tmp_path / "feeds.json"
    catalog.write_text(
        json.dumps(
            {
                "schema": "sab.ai_brief_source_feed_catalog.v1",
                "feeds": [{"ticker": "AAPL.NAS", "url": feed_url}],
            }
        ),
        encoding="utf-8",
    )
    session = _MockFeedSession(
        {feed_url: AssertionError("zero-port feed should not be fetched")}
    )
    _install_mock_feed_session(monkeypatch, session)

    result = collect_ai_brief_sources(
        feed_catalog_path=catalog.as_posix(),
        now=COLLECT_NOW,
    )

    assert result.status == "WARN"
    assert result.sources == []
    assert _issue_codes(result) == {"feed_url_invalid"}
    assert "port" in result.issues[0].message
    assert session.calls == []
    assert session.closed is False


def test_collect_rejects_feed_url_hostname_resolving_to_private_ip(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    feed_url = "https://feeds.example.test/aapl.xml"
    catalog = tmp_path / "feeds.json"
    catalog.write_text(
        json.dumps(
            {
                "schema": "sab.ai_brief_source_feed_catalog.v1",
                "feeds": [{"ticker": "AAPL.NAS", "url": feed_url}],
            }
        ),
        encoding="utf-8",
    )
    session = _MockFeedSession(
        {feed_url: AssertionError("private DNS feed should not be fetched")}
    )
    _install_mock_feed_session(monkeypatch, session, resolved_ip="10.0.0.7")

    result = collect_ai_brief_sources(
        feed_catalog_path=catalog.as_posix(),
        now=COLLECT_NOW,
    )

    assert result.status == "WARN"
    assert result.sources == []
    assert _issue_codes(result) == {"feed_url_invalid"}
    assert session.calls == []


def test_collect_reports_unresolved_feed_url_hostname_as_warning(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    feed_url = "https://feeds.example.test/aapl.xml"
    catalog = tmp_path / "feeds.json"
    catalog.write_text(
        json.dumps(
            {
                "schema": "sab.ai_brief_source_feed_catalog.v1",
                "feeds": [{"ticker": "AAPL.NAS", "url": feed_url}],
            }
        ),
        encoding="utf-8",
    )
    session = _MockFeedSession(
        {feed_url: AssertionError("unresolved feed should not be fetched")}
    )

    def unresolved_getaddrinfo(*_args: object, **_kwargs: object) -> list[object]:
        raise ai_brief_sources.socket.gaierror("no such host")

    monkeypatch.setattr(
        ai_brief_sources.socket,
        "getaddrinfo",
        unresolved_getaddrinfo,
    )
    monkeypatch.setattr(
        collectors,
        "requests",
        types.SimpleNamespace(
            Session=lambda: session,
            Timeout=requests.Timeout,
            RequestException=requests.RequestException,
        ),
        raising=False,
    )

    result = collect_ai_brief_sources(
        feed_catalog_path=catalog.as_posix(),
        now=COLLECT_NOW,
    )

    assert result.status == "WARN"
    assert result.sources == []
    assert _issue_codes(result) == {"feed_url_invalid"}
    assert "could not be resolved" in result.issues[0].message
    assert session.calls == []


def test_collect_reports_feed_url_dns_timeout_as_timeout_warning(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    feed_url = "https://feeds.example.test/aapl.xml"
    catalog = tmp_path / "feeds.json"
    catalog.write_text(
        json.dumps(
            {
                "schema": "sab.ai_brief_source_feed_catalog.v1",
                "feeds": [{"ticker": "AAPL.NAS", "url": feed_url}],
            }
        ),
        encoding="utf-8",
    )
    session = _MockFeedSession(
        {feed_url: AssertionError("timed out DNS feed should not be fetched")}
    )

    def slow_getaddrinfo(*_args: object, **_kwargs: object) -> list[object]:
        time.sleep(0.05)
        return [(0, 0, 0, "", ("93.184.216.34", 443))]

    monkeypatch.setattr(ai_brief_sources.socket, "getaddrinfo", slow_getaddrinfo)
    monkeypatch.setattr(
        collectors,
        "requests",
        types.SimpleNamespace(
            Session=lambda: session,
            Timeout=requests.Timeout,
            RequestException=requests.RequestException,
        ),
        raising=False,
    )

    result = collect_ai_brief_sources(
        feed_catalog_path=catalog.as_posix(),
        now=COLLECT_NOW,
        feed_timeout_seconds=0.001,
    )

    assert result.status == "WARN"
    assert result.sources == []
    assert _issue_codes(result) == {"feed_url_timeout"}
    assert session.calls == []


def test_collect_redacts_malformed_feed_catalog_url(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    malformed_url = "https://secret-token@ex\u2100ample.test/aapl.xml"
    catalog = tmp_path / "feeds.json"
    catalog.write_text(
        json.dumps(
            {
                "schema": "sab.ai_brief_source_feed_catalog.v1",
                "feeds": [{"ticker": "AAPL.NAS", "url": malformed_url}],
            }
        ),
        encoding="utf-8",
    )
    session = _MockFeedSession(
        {malformed_url: AssertionError("malformed feed should not be fetched")}
    )
    monkeypatch.setattr(
        collectors,
        "requests",
        types.SimpleNamespace(
            Session=lambda: session,
            Timeout=requests.Timeout,
            RequestException=requests.RequestException,
        ),
        raising=False,
    )

    result = collect_ai_brief_sources(
        feed_catalog_path=catalog.as_posix(),
        now=COLLECT_NOW,
    )

    assert result.status == "WARN"
    assert result.sources == []
    assert _issue_codes(result) == {"feed_url_invalid"}
    message = result.issues[0].message
    assert "invalid" in message
    assert "secret-token" not in message
    assert "ex" not in message
    assert session.calls == []


def test_collect_pins_feed_url_dns_resolution_during_request(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    feed_url = "https://feeds.example.test/aapl.xml"
    catalog = tmp_path / "feeds.json"
    catalog.write_text(
        json.dumps(
            {
                "schema": "sab.ai_brief_source_feed_catalog.v1",
                "feeds": [{"ticker": "AAPL.NAS", "url": feed_url}],
            }
        ),
        encoding="utf-8",
    )

    lookup_count = 0

    def rebinding_getaddrinfo(*_args, **_kwargs):
        nonlocal lookup_count
        hostname = _args[0].decode("ascii") if isinstance(_args[0], bytes) else _args[0]
        if "news.example" in str(hostname):
            resolved_ip = "93.184.216.34"
        else:
            lookup_count += 1
            resolved_ip = "93.184.216.34" if lookup_count == 1 else "127.0.0.1"
        return [
            (
                ai_brief_sources.socket.AF_INET,
                ai_brief_sources.socket.SOCK_STREAM,
                0,
                "",
                (resolved_ip, 443),
            )
        ]

    class _ResolvingFeedSession(_MockFeedSession):
        def __init__(self, responses: dict[str, object]) -> None:
            super().__init__(responses)
            self.resolved_ips: list[str] = []

        def get(
            self,
            url: str,
            *,
            timeout: float,
            stream: bool,
            allow_redirects: bool,
        ) -> object:
            addrinfos = ai_brief_sources.socket.getaddrinfo(
                b"feeds.example.test",
                443,
                type=ai_brief_sources.socket.SOCK_STREAM,
            )
            self.resolved_ips = [str(addrinfo[4][0]) for addrinfo in addrinfos]
            return super().get(
                url,
                timeout=timeout,
                stream=stream,
                allow_redirects=allow_redirects,
            )

    session = _ResolvingFeedSession(
        {feed_url: _MockFeedResponse(Path(_feed_fixture("aapl.rss")).read_bytes())}
    )
    monkeypatch.setattr(ai_brief_sources.socket, "getaddrinfo", rebinding_getaddrinfo)
    monkeypatch.setattr(
        collectors,
        "requests",
        types.SimpleNamespace(
            Session=lambda: session,
            Timeout=requests.Timeout,
            RequestException=requests.RequestException,
        ),
        raising=False,
    )

    result = collect_ai_brief_sources(
        feed_catalog_path=catalog.as_posix(),
        now=COLLECT_NOW,
    )

    assert result.status == "PASS"
    assert session.resolved_ips == ["93.184.216.34"]


def test_collect_pins_feed_url_idna_dns_alias_during_request(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    feed_host = "b\N{LATIN SMALL LETTER U WITH DIAERESIS}cher.example"
    feed_url = f"https://{feed_host}/aapl.xml"
    idna_host = "xn--bcher-kva.example"
    catalog = tmp_path / "feeds.json"
    catalog.write_text(
        json.dumps(
            {
                "schema": "sab.ai_brief_source_feed_catalog.v1",
                "feeds": [{"ticker": "AAPL.NAS", "url": feed_url}],
            }
        ),
        encoding="utf-8",
    )

    lookup_count = 0

    def rebinding_getaddrinfo(*_args, **_kwargs):
        nonlocal lookup_count
        hostname = _args[0].decode("ascii") if isinstance(_args[0], bytes) else _args[0]
        if "news.example" in str(hostname):
            resolved_ip = "93.184.216.34"
        else:
            lookup_count += 1
            resolved_ip = "93.184.216.34" if lookup_count == 1 else "127.0.0.1"
        return [
            (
                ai_brief_sources.socket.AF_INET,
                ai_brief_sources.socket.SOCK_STREAM,
                0,
                "",
                (resolved_ip, 443),
            )
        ]

    class _ResolvingFeedSession(_MockFeedSession):
        def __init__(self, responses: dict[str, object]) -> None:
            super().__init__(responses)
            self.resolved_ips: list[str] = []

        def get(
            self,
            url: str,
            *,
            timeout: float,
            stream: bool,
            allow_redirects: bool,
        ) -> object:
            addrinfos = ai_brief_sources.socket.getaddrinfo(
                idna_host.encode("ascii"),
                443,
                type=ai_brief_sources.socket.SOCK_STREAM,
            )
            self.resolved_ips = [str(addrinfo[4][0]) for addrinfo in addrinfos]
            return super().get(
                url,
                timeout=timeout,
                stream=stream,
                allow_redirects=allow_redirects,
            )

    session = _ResolvingFeedSession(
        {feed_url: _MockFeedResponse(Path(_feed_fixture("aapl.rss")).read_bytes())}
    )
    monkeypatch.setattr(ai_brief_sources.socket, "getaddrinfo", rebinding_getaddrinfo)
    monkeypatch.setattr(
        collectors,
        "requests",
        types.SimpleNamespace(
            Session=lambda: session,
            Timeout=requests.Timeout,
            RequestException=requests.RequestException,
        ),
        raising=False,
    )

    result = collect_ai_brief_sources(
        feed_catalog_path=catalog.as_posix(),
        now=COLLECT_NOW,
    )

    assert result.status == "PASS"
    assert session.resolved_ips == ["93.184.216.34"]


def test_collect_pins_feed_url_idna2008_dns_alias_during_request(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    feed_host = "fa\N{LATIN SMALL LETTER SHARP S}.example"
    feed_url = f"https://{feed_host}/aapl.xml"
    idna_host = "xn--fa-hia.example"
    catalog = tmp_path / "feeds.json"
    catalog.write_text(
        json.dumps(
            {
                "schema": "sab.ai_brief_source_feed_catalog.v1",
                "feeds": [{"ticker": "AAPL.NAS", "url": feed_url}],
            }
        ),
        encoding="utf-8",
    )

    lookup_count = 0

    def rebinding_getaddrinfo(*_args, **_kwargs):
        nonlocal lookup_count
        hostname = _args[0].decode("ascii") if isinstance(_args[0], bytes) else _args[0]
        if "news.example" in str(hostname):
            resolved_ip = "93.184.216.34"
        else:
            lookup_count += 1
            resolved_ip = "93.184.216.34" if lookup_count == 1 else "127.0.0.1"
        return [
            (
                ai_brief_sources.socket.AF_INET,
                ai_brief_sources.socket.SOCK_STREAM,
                0,
                "",
                (resolved_ip, 443),
            )
        ]

    class _ResolvingFeedSession(_MockFeedSession):
        def __init__(self, responses: dict[str, object]) -> None:
            super().__init__(responses)
            self.resolved_ips: list[str] = []

        def get(
            self,
            url: str,
            *,
            timeout: float,
            stream: bool,
            allow_redirects: bool,
        ) -> object:
            addrinfos = ai_brief_sources.socket.getaddrinfo(
                idna_host.encode("ascii"),
                443,
                type=ai_brief_sources.socket.SOCK_STREAM,
            )
            self.resolved_ips = [str(addrinfo[4][0]) for addrinfo in addrinfos]
            return super().get(
                url,
                timeout=timeout,
                stream=stream,
                allow_redirects=allow_redirects,
            )

    session = _ResolvingFeedSession(
        {feed_url: _MockFeedResponse(Path(_feed_fixture("aapl.rss")).read_bytes())}
    )
    monkeypatch.setattr(ai_brief_sources.socket, "getaddrinfo", rebinding_getaddrinfo)
    monkeypatch.setattr(
        collectors,
        "requests",
        types.SimpleNamespace(
            Session=lambda: session,
            Timeout=requests.Timeout,
            RequestException=requests.RequestException,
        ),
        raising=False,
    )

    result = collect_ai_brief_sources(
        feed_catalog_path=catalog.as_posix(),
        now=COLLECT_NOW,
    )

    assert result.status == "PASS"
    assert session.resolved_ips == ["93.184.216.34"]


def test_collect_validates_feed_url_dns_after_pin_lock(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    feed_url = "https://feeds.example.test/aapl.xml"
    catalog = tmp_path / "feeds.json"
    catalog.write_text(
        json.dumps(
            {
                "schema": "sab.ai_brief_source_feed_catalog.v1",
                "feeds": [{"ticker": "AAPL.NAS", "url": feed_url}],
            }
        ),
        encoding="utf-8",
    )

    def original_getaddrinfo(*_args: object, **_kwargs: object) -> list[object]:
        return [(0, 0, 0, "", ("93.184.216.34", 443))]

    def stale_getaddrinfo(*_args: object, **_kwargs: object) -> list[object]:
        return [(0, 0, 0, "", ("10.0.0.9", 443))]

    class _RestoringLock:
        def __enter__(self) -> None:
            monkeypatch.setattr(
                ai_brief_sources.socket,
                "getaddrinfo",
                original_getaddrinfo,
            )

        def __exit__(self, *args: object) -> None:
            return None

    session = _MockFeedSession(
        {feed_url: _MockFeedResponse(Path(_feed_fixture("aapl.rss")).read_bytes())}
    )
    monkeypatch.setattr(ai_brief_sources.socket, "getaddrinfo", stale_getaddrinfo)
    lock = _RestoringLock()
    monkeypatch.setattr(ai_brief_sources, "SOURCE_DNS_PIN_LOCK", lock)
    monkeypatch.setattr(collectors, "SOURCE_DNS_PIN_LOCK", lock)
    monkeypatch.setattr(
        collectors,
        "requests",
        types.SimpleNamespace(
            Session=lambda: session,
            Timeout=requests.Timeout,
            RequestException=requests.RequestException,
        ),
        raising=False,
    )

    result = collect_ai_brief_sources(
        feed_catalog_path=catalog.as_posix(),
        now=COLLECT_NOW,
    )

    assert result.status == "PASS"
    assert session.calls[0]["url"] == feed_url


def test_collect_redacts_feed_url_from_request_exception_issue(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    feed_url = "https://feeds.example.test/aapl.xml?token=secret-token"
    catalog = tmp_path / "feeds.json"
    catalog.write_text(
        json.dumps(
            {
                "schema": "sab.ai_brief_source_feed_catalog.v1",
                "feeds": [{"ticker": "AAPL.NAS", "url": feed_url}],
            }
        ),
        encoding="utf-8",
    )
    session = _MockFeedSession(
        {
            feed_url: requests.ConnectionError(
                "Max retries exceeded with url: /aapl.xml?token=secret-token"
            )
        }
    )
    _install_mock_feed_session(monkeypatch, session)

    result = collect_ai_brief_sources(
        feed_catalog_path=catalog.as_posix(),
        now=COLLECT_NOW,
    )

    assert result.status == "WARN"
    assert result.sources == []
    assert _issue_codes(result) == {"feed_url_failed"}
    assert "ConnectionError" in result.issues[0].message
    assert "secret-token" not in result.issues[0].message
    assert "aapl.xml" not in result.issues[0].message


def test_collect_redacts_feed_url_from_timeout_issue(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    feed_url = "https://feeds.example.test/aapl.xml?token=secret-token"
    catalog = tmp_path / "feeds.json"
    catalog.write_text(
        json.dumps(
            {
                "schema": "sab.ai_brief_source_feed_catalog.v1",
                "feeds": [{"ticker": "AAPL.NAS", "url": feed_url}],
            }
        ),
        encoding="utf-8",
    )
    session = _MockFeedSession(
        {feed_url: requests.Timeout("Read timed out for /aapl.xml?token=secret-token")}
    )
    _install_mock_feed_session(monkeypatch, session)

    result = collect_ai_brief_sources(
        feed_catalog_path=catalog.as_posix(),
        now=COLLECT_NOW,
    )

    assert result.status == "WARN"
    assert result.sources == []
    assert _issue_codes(result) == {"feed_url_timeout"}
    assert "Timeout" in result.issues[0].message
    assert "secret-token" not in result.issues[0].message
    assert "aapl.xml" not in result.issues[0].message


def test_collect_reports_streaming_body_deadline_as_timeout(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    feed_url = "https://feeds.example.test/aapl.xml"
    catalog = tmp_path / "feeds.json"
    catalog.write_text(
        json.dumps(
            {
                "schema": "sab.ai_brief_source_feed_catalog.v1",
                "feeds": [{"ticker": "AAPL.NAS", "url": feed_url}],
            }
        ),
        encoding="utf-8",
    )
    response = _MockFeedResponse(Path(_feed_fixture("aapl.rss")).read_bytes())
    session = _MockFeedSession({feed_url: response})
    _install_mock_feed_session(monkeypatch, session)
    monotonic_values = iter([0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.5, 2.0])
    monkeypatch.setattr(collectors.time, "monotonic", lambda: next(monotonic_values))

    result = collect_ai_brief_sources(
        feed_catalog_path=catalog.as_posix(),
        now=COLLECT_NOW,
        feed_timeout_seconds=1.0,
    )

    assert result.status == "WARN"
    assert result.sources == []
    assert _issue_codes(result) == {"feed_url_timeout"}
    assert response.closed is True


def test_collect_uses_remaining_timeout_for_feed_url_request(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    feed_url = "https://feeds.example.test/aapl.xml"
    catalog = tmp_path / "feeds.json"
    catalog.write_text(
        json.dumps(
            {
                "schema": "sab.ai_brief_source_feed_catalog.v1",
                "feeds": [{"ticker": "AAPL.NAS", "url": feed_url}],
            }
        ),
        encoding="utf-8",
    )
    response = _MockFeedResponse(Path(_feed_fixture("aapl.rss")).read_bytes())
    session = _MockFeedSession({feed_url: response})
    _install_mock_feed_session(monkeypatch, session)
    monotonic_values = iter([0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.75, 0.8])
    monkeypatch.setattr(
        collectors.time,
        "monotonic",
        lambda: next(monotonic_values, 0.8),
    )

    result = collect_ai_brief_sources(
        feed_catalog_path=catalog.as_posix(),
        now=COLLECT_NOW,
        feed_timeout_seconds=1.0,
    )

    assert result.status == "PASS"
    timeout = session.calls[0]["timeout"]
    assert isinstance(timeout, tuple)
    assert timeout == pytest.approx((0.25, 0.25))


def test_collect_disables_proxy_env_and_closes_feed_url_session(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    feed_url = "https://feeds.example.test/aapl.xml"
    catalog = tmp_path / "feeds.json"
    catalog.write_text(
        json.dumps(
            {
                "schema": "sab.ai_brief_source_feed_catalog.v1",
                "feeds": [{"ticker": "AAPL.NAS", "url": feed_url}],
            }
        ),
        encoding="utf-8",
    )
    session = _MockFeedSession(
        {feed_url: _MockFeedResponse(Path(_feed_fixture("aapl.rss")).read_bytes())}
    )
    _install_mock_feed_session(monkeypatch, session)

    result = collect_ai_brief_sources(
        feed_catalog_path=catalog.as_posix(),
        now=COLLECT_NOW,
    )

    assert result.status == "PASS"
    assert session.trust_env is False
    assert session.closed is True


def test_collect_keeps_feed_url_session_open_while_streaming_body(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    feed_url = "https://feeds.example.test/aapl.xml"
    catalog = tmp_path / "feeds.json"
    catalog.write_text(
        json.dumps(
            {
                "schema": "sab.ai_brief_source_feed_catalog.v1",
                "feeds": [{"ticker": "AAPL.NAS", "url": feed_url}],
            }
        ),
        encoding="utf-8",
    )
    session = _MockFeedSession({})

    class _StreamingBodyResponse(_MockFeedResponse):
        def __init__(self, body: bytes) -> None:
            super().__init__(body)
            self.streamed_with_open_session = False

        def iter_content(self, chunk_size: int):
            self.streamed_with_open_session = not session.closed
            yield from super().iter_content(chunk_size)

    response = _StreamingBodyResponse(Path(_feed_fixture("aapl.rss")).read_bytes())
    session.responses[feed_url] = response
    _install_mock_feed_session(monkeypatch, session)

    result = collect_ai_brief_sources(
        feed_catalog_path=catalog.as_posix(),
        now=COLLECT_NOW,
    )

    assert result.status == "PASS"
    assert response.streamed_with_open_session is True
    assert response.closed is True
    assert session.closed is True


def test_collect_reports_streaming_body_request_exception_as_warning(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    feed_url = "https://feeds.example.test/aapl.xml?token=secret-token"
    catalog = tmp_path / "feeds.json"
    catalog.write_text(
        json.dumps(
            {
                "schema": "sab.ai_brief_source_feed_catalog.v1",
                "feeds": [{"ticker": "AAPL.NAS", "url": feed_url}],
            }
        ),
        encoding="utf-8",
    )

    class _FailingBodyResponse(_MockFeedResponse):
        def iter_content(self, chunk_size: int):
            raise requests.exceptions.ChunkedEncodingError(
                "bad chunk for /aapl.xml?token=secret-token"
            )

    response = _FailingBodyResponse(b"")
    session = _MockFeedSession({feed_url: response})
    _install_mock_feed_session(monkeypatch, session)

    result = collect_ai_brief_sources(
        feed_catalog_path=catalog.as_posix(),
        now=COLLECT_NOW,
    )

    assert result.status == "WARN"
    assert result.sources == []
    assert _issue_codes(result) == {"feed_url_failed"}
    assert "ChunkedEncodingError" in result.issues[0].message
    assert "secret-token" not in result.issues[0].message
    assert "aapl.xml" not in result.issues[0].message
    assert response.closed is True


def test_collect_reports_live_feed_unsafe_xml_as_warning(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    feed_url = "https://feeds.example.test/aapl.xml"
    catalog = tmp_path / "feeds.json"
    catalog.write_text(
        json.dumps(
            {
                "schema": "sab.ai_brief_source_feed_catalog.v1",
                "feeds": [{"ticker": "AAPL.NAS", "url": feed_url}],
            }
        ),
        encoding="utf-8",
    )
    response = _MockFeedResponse(
        b"""<?xml version="1.0"?>
<!DOCTYPE rss [<!ENTITY xxe SYSTEM "file:///etc/passwd">]>
<rss><channel><item><title>&xxe;</title></item></channel></rss>"""
    )
    session = _MockFeedSession({feed_url: response})
    _install_mock_feed_session(monkeypatch, session)

    result = collect_ai_brief_sources(
        feed_catalog_path=catalog.as_posix(),
        now=COLLECT_NOW,
    )

    assert result.status == "WARN"
    assert result.sources == []
    assert _issue_codes(result) == {"feed_url_unsafe_xml"}
    assert response.closed is True


@pytest.mark.parametrize(
    ("body", "expected_code"),
    [
        (b"<rss><channel></channel></rss>", "feed_url_empty"),
        (b"<html><body>not a feed</body></html>", "feed_format_unsupported"),
    ],
)
def test_collect_reports_live_feed_empty_and_unsupported_root_as_warning(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    body: bytes,
    expected_code: str,
) -> None:
    feed_url = "https://feeds.example.test/aapl.xml"
    catalog = tmp_path / "feeds.json"
    catalog.write_text(
        json.dumps(
            {
                "schema": "sab.ai_brief_source_feed_catalog.v1",
                "feeds": [{"ticker": "AAPL.NAS", "url": feed_url}],
            }
        ),
        encoding="utf-8",
    )
    response = _MockFeedResponse(body)
    session = _MockFeedSession({feed_url: response})
    _install_mock_feed_session(monkeypatch, session)

    result = collect_ai_brief_sources(
        feed_catalog_path=catalog.as_posix(),
        now=COLLECT_NOW,
    )

    assert result.status == "WARN"
    assert result.sources == []
    assert _issue_codes(result) == {expected_code}
    assert response.closed is True


def test_collect_rejects_feed_catalog_row_with_both_path_and_url(
    tmp_path: Path,
) -> None:
    catalog = tmp_path / "feeds.json"
    catalog.write_text(
        json.dumps(
            {
                "schema": "sab.ai_brief_source_feed_catalog.v1",
                "feeds": [
                    {
                        "ticker": "AAPL.NAS",
                        "path": "aapl.rss",
                        "url": "https://feeds.example.test/aapl.xml",
                    }
                ],
            }
        ),
        encoding="utf-8",
    )

    result = collect_ai_brief_sources(
        feed_catalog_path=catalog.as_posix(),
        now=COLLECT_NOW,
    )

    assert result.status == "WARN"
    assert result.sources == []
    assert _issue_codes(result) == {"feed_catalog_invalid_row"}


def test_collects_rss_and_atom_feeds_into_eval_compatible_payload(
    tmp_path: Path,
) -> None:
    result = collect_ai_brief_sources(
        feed_catalog_path=_feed_fixture("feeds.good.json"),
        now=COLLECT_NOW,
    )

    assert result.status == "PASS"
    assert [source["ticker"] for source in result.sources] == [
        "AAPL.NAS",
        "MSFT.NAS",
        "NVDA.NAS",
    ]
    assert result.sources[0]["published_at"] == "2026-05-06T11:30:00+00:00"
    assert result.sources[1]["url"] == "https://news.example.test/msft-cloud-bookings"

    payload = result.to_dict()
    assert payload["type"] == "ai_brief_sources"
    source_report = tmp_path / "collected.sources.json"
    source_report.write_text(json.dumps(payload), encoding="utf-8")
    eval_result = evaluate_ai_brief_source_report(
        entry_report_path=_source_fixture("entry.us.json"),
        source_report_path=source_report.as_posix(),
        now=COLLECT_NOW,
    )

    assert eval_result.status == "PASS"
    assert eval_result.summary["covered_ticker_count"] == 3


def test_collect_filters_requested_tickers() -> None:
    result = collect_ai_brief_sources(
        feed_catalog_path=_feed_fixture("feeds.good.json"),
        tickers={"AAPL.NAS"},
        now=COLLECT_NOW,
    )

    assert result.status == "PASS"
    assert [source["ticker"] for source in result.sources] == ["AAPL.NAS"]
    payload = result.to_dict()
    summary = payload["summary"]
    assert isinstance(summary, dict)
    assert summary["covered_tickers"] == ["AAPL.NAS"]


def test_collect_reports_missing_requested_ticker() -> None:
    result = collect_ai_brief_sources(
        feed_catalog_path=_feed_fixture("feeds.good.json"),
        tickers={"TSLA.NAS"},
        now=COLLECT_NOW,
    )

    assert result.status == "WARN"
    assert result.sources == []
    assert _issue_codes(result) == {"feed_catalog_missing_ticker"}


def test_collect_rejects_options_that_exceed_source_report_contract() -> None:
    with pytest.raises(ValueError, match="freshness_hours"):
        collect_ai_brief_sources(
            feed_catalog_path=_feed_fixture("feeds.good.json"),
            now=COLLECT_NOW,
            freshness_hours=73,
        )
    with pytest.raises(ValueError, match="max_sources_per_ticker"):
        collect_ai_brief_sources(
            feed_catalog_path=_feed_fixture("feeds.good.json"),
            now=COLLECT_NOW,
            max_sources_per_ticker=4,
        )
    with pytest.raises(ValueError, match="feed_timeout_seconds"):
        collect_ai_brief_sources(
            feed_catalog_path=_feed_fixture("feeds.good.json"),
            now=COLLECT_NOW,
            feed_timeout_seconds=0,
        )
    with pytest.raises(ValueError, match="feed_timeout_seconds"):
        collect_ai_brief_sources(
            feed_catalog_path=_feed_fixture("feeds.good.json"),
            now=COLLECT_NOW,
            feed_timeout_seconds=float("nan"),
        )


def test_collect_respects_custom_freshness_hours() -> None:
    result = collect_ai_brief_sources(
        feed_catalog_path=_feed_fixture("feeds.good.json"),
        now=COLLECT_NOW,
        freshness_hours=0.25,
    )

    assert result.status == "WARN"
    assert result.sources == []
    assert _issue_codes(result) == {"feed_item_stale"}


def test_collect_reports_invalid_stale_duplicate_and_cap_issues() -> None:
    result = collect_ai_brief_sources(
        feed_catalog_path=_feed_fixture("feeds.issues.json"),
        now=COLLECT_NOW,
    )

    assert result.status == "WARN"
    assert [source["url"] for source in result.sources] == [
        "https://news.example.test/aapl-newest",
        "https://news.example.test/aapl-second",
        "https://news.example.test/aapl-third",
    ]
    assert _issue_codes(result) == {
        "feed_catalog_invalid_row",
        "feed_file_failed",
        "feed_item_cap_exceeded",
        "feed_item_duplicate_url",
        "feed_item_invalid_row",
        "feed_item_stale",
    }


def test_collect_redacts_duplicate_feed_item_url_issue(tmp_path: Path) -> None:
    feed_path = tmp_path / "signed.rss"
    feed_path.write_text(
        """<?xml version="1.0"?>
<rss><channel>
  <item>
    <title>Signed URL one</title>
    <link>https://news.example.test/aapl?token=secret-token</link>
    <pubDate>Wed, 06 May 2026 11:30:00 GMT</pubDate>
  </item>
  <item>
    <title>Signed URL two</title>
    <link>https://news.example.test/aapl?token=secret-token</link>
    <pubDate>Wed, 06 May 2026 11:20:00 GMT</pubDate>
  </item>
</channel></rss>""",
        encoding="utf-8",
    )
    catalog = tmp_path / "feeds.json"
    catalog.write_text(
        json.dumps(
            {
                "schema": "sab.ai_brief_source_feed_catalog.v1",
                "feeds": [{"ticker": "AAPL.NAS", "path": feed_path.name}],
            }
        ),
        encoding="utf-8",
    )

    result = collect_ai_brief_sources(
        feed_catalog_path=catalog.as_posix(),
        now=COLLECT_NOW,
    )

    assert result.status == "WARN"
    assert _issue_codes(result) == {"feed_item_duplicate_url"}
    assert "secret-token" not in result.issues[0].message
    assert "https://news.example.test" not in result.issues[0].message


def test_collect_local_feed_path_does_not_resolve_feed_item_hostnames(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fail_getaddrinfo(*_args: object, **_kwargs: object) -> list[object]:
        raise AssertionError("local feed path collection should stay offline")

    monkeypatch.setattr(ai_brief_sources.socket, "getaddrinfo", fail_getaddrinfo)

    result = collect_ai_brief_sources(
        feed_catalog_path=_feed_fixture("feeds.good.json"),
        now=COLLECT_NOW,
    )

    assert result.status == "PASS"
    assert [source["ticker"] for source in result.sources] == [
        "AAPL.NAS",
        "MSFT.NAS",
        "NVDA.NAS",
    ]


def test_collect_accepts_rdf_dc_date() -> None:
    result = collect_ai_brief_sources(
        feed_catalog_path=_feed_fixture("feeds.rdf.json"),
        now=COLLECT_NOW,
    )

    assert result.status == "PASS"
    assert result.sources == [
        {
            "ticker": "META.NAS",
            "title": "Meta ad spending outlook improves",
            "url": "https://news.example.test/meta-ad-spend",
            "published_at": "2026-05-06T08:45:00+00:00",
        }
    ]


def test_collect_rejects_doctype_entity_feed_before_xml_parse(
    tmp_path: Path,
) -> None:
    feed = tmp_path / "unsafe.rss"
    feed.write_bytes(
        """<?xml version="1.0" encoding="UTF-16"?>
<!DOCTYPE rss [<!ENTITY unsafe "expanded">]>
<rss version="2.0">
  <channel>
    <item>
      <title>&unsafe;</title>
      <link>https://news.example.test/unsafe</link>
      <pubDate>Wed, 06 May 2026 11:30:00 GMT</pubDate>
    </item>
  </channel>
</rss>
""".encode("utf-16"),
    )
    catalog = tmp_path / "feeds.json"
    catalog.write_text(
        json.dumps(
            {
                "schema": "sab.ai_brief_source_feed_catalog.v1",
                "feeds": [{"ticker": "AAPL.NAS", "path": "unsafe.rss"}],
            }
        ),
        encoding="utf-8",
    )

    result = collect_ai_brief_sources(
        feed_catalog_path=catalog.as_posix(),
        now=COLLECT_NOW,
    )

    assert result.sources == []
    assert _issue_codes(result) == {"feed_file_unsafe_xml"}


def test_collect_rejects_feed_file_over_size_limit(tmp_path: Path) -> None:
    feed = tmp_path / "oversized.rss"
    feed.write_bytes(b"x" * (MAX_FEED_BYTES + 1))
    catalog = tmp_path / "feeds.json"
    catalog.write_text(
        json.dumps(
            {
                "schema": "sab.ai_brief_source_feed_catalog.v1",
                "feeds": [{"ticker": "AAPL.NAS", "path": "oversized.rss"}],
            }
        ),
        encoding="utf-8",
    )

    result = collect_ai_brief_sources(
        feed_catalog_path=catalog.as_posix(),
        now=COLLECT_NOW,
    )

    assert result.sources == []
    assert _issue_codes(result) == {"feed_file_too_large"}


def test_collect_rejects_feed_catalog_over_size_limit(tmp_path: Path) -> None:
    catalog = tmp_path / "oversized-feeds.json"
    catalog.write_bytes(b"x" * (MAX_FEED_CATALOG_BYTES + 1))

    with pytest.raises(AiBriefSourceCollectorError, match="feed catalog is too large"):
        collect_ai_brief_sources(
            feed_catalog_path=catalog.as_posix(),
            now=COLLECT_NOW,
        )


def test_parse_feed_root_reads_only_size_limit_plus_sentinel(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    feed = tmp_path / "oversized.rss"
    read_sizes: list[int] = []

    class _BoundedRead:
        def __enter__(self) -> _BoundedRead:
            return self

        def __exit__(self, *args: object) -> None:
            return None

        def read(self, size: int) -> bytes:
            read_sizes.append(size)
            return b"x" * size

    monkeypatch.setattr(
        collectors,
        "open",
        lambda *_args, **_kwargs: _BoundedRead(),
        raising=False,
    )

    with pytest.raises(collectors._FeedFileTooLargeError):
        collectors._parse_feed_root(feed)

    assert read_sizes == [MAX_FEED_BYTES + 1]


def test_collect_rejects_feed_path_outside_catalog_dir(tmp_path: Path) -> None:
    catalog = tmp_path / "feeds.json"
    catalog.write_text(
        json.dumps(
            {
                "schema": "sab.ai_brief_source_feed_catalog.v1",
                "feeds": [{"ticker": "AAPL.NAS", "path": "../outside.rss"}],
            }
        ),
        encoding="utf-8",
    )

    result = collect_ai_brief_sources(
        feed_catalog_path=catalog.as_posix(),
        now=COLLECT_NOW,
    )

    assert result.sources == []
    assert _issue_codes(result) == {"feed_catalog_invalid_row"}
    assert "within the feed catalog directory" in result.issues[0].message


def test_collect_does_not_preserve_absolute_feed_paths_in_issues(
    tmp_path: Path,
) -> None:
    feed = tmp_path / "bad.xml"
    feed.write_text("<rss><channel><item>", encoding="utf-8")
    catalog = tmp_path / "feeds.json"
    catalog.write_text(
        json.dumps(
            {
                "schema": "sab.ai_brief_source_feed_catalog.v1",
                "feeds": [{"ticker": "AAPL.NAS", "path": "bad.xml"}],
            }
        ),
        encoding="utf-8",
    )

    result = collect_ai_brief_sources(
        feed_catalog_path=catalog.as_posix(),
        now=COLLECT_NOW,
    )

    assert result.sources == []
    assert _issue_codes(result) == {"feed_file_failed"}
    assert "bad.xml" in result.issues[0].message
    assert tmp_path.as_posix() not in result.issues[0].message


def test_collect_rejects_invalid_urls_and_future_dates(tmp_path: Path) -> None:
    feed = tmp_path / "bad-source.rss"
    feed.write_text(
        """<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0">
  <channel>
    <item>
      <title>Unsupported URL scheme</title>
      <link>file:///private/news.html</link>
      <pubDate>Wed, 06 May 2026 11:30:00 GMT</pubDate>
    </item>
    <item>
      <title>Credential URL</title>
      <link>https://token@example.test/secret</link>
      <pubDate>Wed, 06 May 2026 11:20:00 GMT</pubDate>
    </item>
    <item>
      <title>Local metadata URL</title>
      <link>http://169.254.169.254/latest/meta-data</link>
      <pubDate>Wed, 06 May 2026 11:10:00 GMT</pubDate>
    </item>
    <item>
      <title>Short loopback URL</title>
      <link>http://127.1/latest</link>
      <pubDate>Wed, 06 May 2026 11:09:00 GMT</pubDate>
    </item>
    <item>
      <title>Integer loopback URL</title>
      <link>http://2130706433/latest</link>
      <pubDate>Wed, 06 May 2026 11:08:00 GMT</pubDate>
    </item>
    <item>
      <title>Hex loopback URL</title>
      <link>http://0x7f000001/latest</link>
      <pubDate>Wed, 06 May 2026 11:07:00 GMT</pubDate>
    </item>
    <item>
      <title>Integer metadata URL</title>
      <link>http://2852039166/latest</link>
      <pubDate>Wed, 06 May 2026 11:06:00 GMT</pubDate>
    </item>
    <item>
      <title>Unicode dot loopback URL</title>
      <link>http://127\u30020\u30020\u30021/latest</link>
      <pubDate>Wed, 06 May 2026 11:05:00 GMT</pubDate>
    </item>
    <item>
      <title>Fullwidth short loopback URL</title>
      <link>http://\uff11\uff12\uff17.\uff11/latest</link>
      <pubDate>Wed, 06 May 2026 11:04:00 GMT</pubDate>
    </item>
    <item>
      <title>Fullwidth hex loopback URL</title>
      <link>http://\uff10x\uff17f\uff10\uff10\uff10\uff10\uff10\uff11/latest</link>
      <pubDate>Wed, 06 May 2026 11:03:00 GMT</pubDate>
    </item>
    <item>
      <title>Future source</title>
      <link>https://news.example.test/future</link>
      <pubDate>Wed, 06 May 2026 12:16:00 GMT</pubDate>
    </item>
  </channel>
</rss>
""",
        encoding="utf-8",
    )
    catalog = tmp_path / "feeds.json"
    catalog.write_text(
        json.dumps(
            {
                "schema": "sab.ai_brief_source_feed_catalog.v1",
                "feeds": [{"ticker": "AAPL.NAS", "path": "bad-source.rss"}],
            }
        ),
        encoding="utf-8",
    )

    result = collect_ai_brief_sources(
        feed_catalog_path=catalog.as_posix(),
        now=COLLECT_NOW,
    )

    assert result.sources == []
    assert _issue_codes(result) == {"feed_item_future", "feed_item_invalid_row"}
    assert any("userinfo" in issue.message for issue in result.issues)
    assert any("local or private hosts" in issue.message for issue in result.issues)


def test_collect_redacts_malformed_feed_item_url(tmp_path: Path) -> None:
    feed = tmp_path / "malformed-source.rss"
    feed.write_text(
        """<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0">
  <channel>
    <item>
      <title>Malformed URL</title>
      <link>https://secret-token@ex\u2100ample.test/source</link>
      <pubDate>Wed, 06 May 2026 11:30:00 GMT</pubDate>
    </item>
  </channel>
</rss>
""",
        encoding="utf-8",
    )
    catalog = tmp_path / "feeds.json"
    catalog.write_text(
        json.dumps(
            {
                "schema": "sab.ai_brief_source_feed_catalog.v1",
                "feeds": [{"ticker": "AAPL.NAS", "path": "malformed-source.rss"}],
            }
        ),
        encoding="utf-8",
    )

    result = collect_ai_brief_sources(
        feed_catalog_path=catalog.as_posix(),
        now=COLLECT_NOW,
    )

    assert result.sources == []
    assert _issue_codes(result) == {"feed_item_invalid_row"}
    message = result.issues[0].message
    assert "invalid" in message
    assert "secret-token" not in message
    assert "ex" not in message


def test_collect_rejects_feed_item_hostname_resolving_to_private_ip(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    feed_url = "https://feeds.example.test/private-source-host.rss"
    feed_body = b"""<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0">
  <channel>
    <item>
      <title>Private resolving source</title>
      <link>https://news.example.test/source</link>
      <pubDate>Wed, 06 May 2026 11:30:00 GMT</pubDate>
    </item>
  </channel>
</rss>
"""
    catalog = tmp_path / "feeds.json"
    catalog.write_text(
        json.dumps(
            {
                "schema": "sab.ai_brief_source_feed_catalog.v1",
                "feeds": [{"ticker": "AAPL.NAS", "url": feed_url}],
            }
        ),
        encoding="utf-8",
    )

    def selective_getaddrinfo(
        host: object,
        port: object,
        *_args: object,
        **_kwargs: object,
    ) -> list[object]:
        host_text = host.decode("ascii") if isinstance(host, bytes) else str(host)
        port_int = port if isinstance(port, int) else int(str(port))
        resolved_ip = (
            "169.254.169.254" if host_text == "news.example.test" else "93.184.216.34"
        )
        return [
            (
                ai_brief_sources.socket.AF_INET,
                ai_brief_sources.socket.SOCK_STREAM,
                0,
                "",
                (resolved_ip, port_int),
            )
        ]

    session = _MockFeedSession({feed_url: _MockFeedResponse(feed_body)})
    monkeypatch.setattr(
        ai_brief_sources.socket,
        "getaddrinfo",
        selective_getaddrinfo,
    )
    monkeypatch.setattr(
        collectors,
        "requests",
        types.SimpleNamespace(
            Session=lambda: session,
            Timeout=requests.Timeout,
            RequestException=requests.RequestException,
        ),
        raising=False,
    )

    result = collect_ai_brief_sources(
        feed_catalog_path=catalog.as_posix(),
        now=COLLECT_NOW,
    )

    assert result.sources == []
    assert _issue_codes(result) == {"feed_item_invalid_row"}
    assert "local or private hosts" in result.issues[0].message


def test_collect_reports_unresolved_live_feed_item_hostname_as_invalid_row(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    feed_url = "https://feeds.example.test/unresolved-source-host.rss"
    feed_body = b"""<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0">
  <channel>
    <item>
      <title>Unresolved source</title>
      <link>https://news.example.test/source</link>
      <pubDate>Wed, 06 May 2026 11:30:00 GMT</pubDate>
    </item>
  </channel>
</rss>
"""
    catalog = tmp_path / "feeds.json"
    catalog.write_text(
        json.dumps(
            {
                "schema": "sab.ai_brief_source_feed_catalog.v1",
                "feeds": [{"ticker": "AAPL.NAS", "url": feed_url}],
            }
        ),
        encoding="utf-8",
    )

    def selective_getaddrinfo(
        host: object,
        port: object,
        *_args: object,
        **_kwargs: object,
    ) -> list[object]:
        host_text = host.decode("ascii") if isinstance(host, bytes) else str(host)
        port_int = port if isinstance(port, int) else int(str(port))
        if host_text == "news.example.test":
            raise ai_brief_sources.socket.gaierror("no such host")
        return [
            (
                ai_brief_sources.socket.AF_INET,
                ai_brief_sources.socket.SOCK_STREAM,
                0,
                "",
                ("93.184.216.34", port_int),
            )
        ]

    session = _MockFeedSession({feed_url: _MockFeedResponse(feed_body)})
    monkeypatch.setattr(
        ai_brief_sources.socket,
        "getaddrinfo",
        selective_getaddrinfo,
    )
    monkeypatch.setattr(
        collectors,
        "requests",
        types.SimpleNamespace(
            Session=lambda: session,
            Timeout=requests.Timeout,
            RequestException=requests.RequestException,
        ),
        raising=False,
    )

    result = collect_ai_brief_sources(
        feed_catalog_path=catalog.as_posix(),
        now=COLLECT_NOW,
    )

    assert result.sources == []
    assert _issue_codes(result) == {"feed_item_invalid_row"}
    assert "could not be resolved" in result.issues[0].message


@pytest.mark.parametrize(
    "source_url",
    [
        "https://[64:ff9b::a9fe:a9fe]/source",
        "https://224.0.0.1/source",
        "https://[ff02::1]/source",
        "https://[::ffff:224.0.0.1]/source",
        "https://[64:ff9b::e000:1]/source",
        "https://[::7f00:1]/source",
    ],
)
def test_collect_rejects_feed_item_urls_with_blocked_ip_literals(
    tmp_path: Path,
    source_url: str,
) -> None:
    feed = tmp_path / "blocked-ip-source.rss"
    feed.write_text(
        f"""<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0">
  <channel>
    <item>
      <title>Blocked IP source</title>
      <link>{source_url}</link>
      <pubDate>Wed, 06 May 2026 11:30:00 GMT</pubDate>
    </item>
  </channel>
</rss>
""",
        encoding="utf-8",
    )
    catalog = tmp_path / "feeds.json"
    catalog.write_text(
        json.dumps(
            {
                "schema": "sab.ai_brief_source_feed_catalog.v1",
                "feeds": [{"ticker": "AAPL.NAS", "path": "blocked-ip-source.rss"}],
            }
        ),
        encoding="utf-8",
    )

    result = collect_ai_brief_sources(
        feed_catalog_path=catalog.as_posix(),
        now=COLLECT_NOW,
    )

    assert result.sources == []
    assert _issue_codes(result) == {"feed_item_invalid_row"}
    assert "local or private hosts" in result.issues[0].message


def test_collect_reports_live_feed_item_dns_timeout_as_feed_timeout(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    feed_url = "https://feeds.example.test/aapl.xml"
    catalog = tmp_path / "feeds.json"
    catalog.write_text(
        json.dumps(
            {
                "schema": "sab.ai_brief_source_feed_catalog.v1",
                "feeds": [{"ticker": "AAPL.NAS", "url": feed_url}],
            }
        ),
        encoding="utf-8",
    )
    session = _MockFeedSession(
        {feed_url: _MockFeedResponse(Path(_feed_fixture("aapl.rss")).read_bytes())}
    )

    def selective_getaddrinfo(
        host: object,
        port: object,
        *_args: object,
        **_kwargs: object,
    ) -> list[object]:
        host_text = host.decode("ascii") if isinstance(host, bytes) else str(host)
        port_int = port if isinstance(port, int) else int(str(port))
        if host_text == "feeds.example.test":
            return [(0, 0, 0, "", ("93.184.216.34", port_int))]
        time.sleep(0.05)
        return [(0, 0, 0, "", ("93.184.216.34", port_int))]

    monkeypatch.setattr(ai_brief_sources.socket, "getaddrinfo", selective_getaddrinfo)
    monkeypatch.setattr(
        collectors,
        "requests",
        types.SimpleNamespace(
            Session=lambda: session,
            Timeout=requests.Timeout,
            RequestException=requests.RequestException,
        ),
        raising=False,
    )

    result = collect_ai_brief_sources(
        feed_catalog_path=catalog.as_posix(),
        now=COLLECT_NOW,
        feed_timeout_seconds=0.01,
    )

    assert result.status == "WARN"
    assert result.sources == []
    assert _issue_codes(result) == {"feed_url_timeout"}


def test_source_dns_pin_captures_original_resolver_after_lock(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    assert collectors.SOURCE_DNS_PIN_LOCK is ai_brief_sources.SOURCE_DNS_PIN_LOCK

    def original_getaddrinfo(*_args: object, **_kwargs: object) -> list[object]:
        return [(0, 0, 0, "", ("93.184.216.34", 443))]

    def stale_getaddrinfo(*_args: object, **_kwargs: object) -> list[object]:
        return [(0, 0, 0, "", ("10.0.0.9", 443))]

    @contextmanager
    def restoring_lock() -> Iterator[None]:
        monkeypatch.setattr(
            ai_brief_sources.socket,
            "getaddrinfo",
            original_getaddrinfo,
        )
        yield

    monkeypatch.setattr(
        ai_brief_sources.socket,
        "getaddrinfo",
        stale_getaddrinfo,
    )
    monkeypatch.setattr(ai_brief_sources, "SOURCE_DNS_PIN_LOCK", restoring_lock())

    with ai_brief_sources._pin_source_api_dns(
        ("source.example",),
        ((0, 0, 0, "", ("93.184.216.34", 443)),),
    ):
        pass

    assert ai_brief_sources.socket.getaddrinfo is original_getaddrinfo


def test_nested_feed_dns_pin_is_reentrant(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def public_getaddrinfo(*_args: object, **_kwargs: object) -> list[object]:
        return [(0, 0, 0, "", ("93.184.216.34", 443))]

    monkeypatch.setattr(
        ai_brief_sources.socket,
        "getaddrinfo",
        public_getaddrinfo,
    )

    with collectors._pin_feed_url_dns(
        ("feeds.example.test",),
        ((0, 0, 0, "", ("93.184.216.34", 443)),),
    ):
        feed_url = collectors._validate_feed_url("https://feeds.example.test/aapl.xml")

    assert feed_url.url == "https://feeds.example.test/aapl.xml"
    assert ai_brief_sources.socket.getaddrinfo is public_getaddrinfo


def test_feed_dns_pin_delegates_same_host_different_port(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def original_getaddrinfo(
        _host: object,
        port: object,
        *_args: object,
        **_kwargs: object,
    ) -> list[object]:
        port_int = port if isinstance(port, int) else int(str(port))
        return [(0, 0, 0, "", ("198.51.100.9", port_int))]

    monkeypatch.setattr(
        ai_brief_sources.socket,
        "getaddrinfo",
        original_getaddrinfo,
    )

    with collectors._pin_feed_url_dns(
        ("feeds.example.test",),
        ((0, 0, 0, "", ("93.184.216.34", 443)),),
    ):
        pinned_addrinfos = ai_brief_sources.socket.getaddrinfo(
            "feeds.example.test", 443
        )
        delegated_addrinfos = ai_brief_sources.socket.getaddrinfo(
            "feeds.example.test", 8443
        )

    assert pinned_addrinfos == [(0, 0, 0, "", ("93.184.216.34", 443))]
    assert delegated_addrinfos == [(0, 0, 0, "", ("198.51.100.9", 8443))]
    assert ai_brief_sources.socket.getaddrinfo is original_getaddrinfo


def test_feed_dns_pin_delegates_same_host_same_port_different_family(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[object] = []

    def original_getaddrinfo(
        host: object,
        port: object,
        *_args: object,
        **_kwargs: object,
    ) -> list[object]:
        calls.append(host)
        port_int = port if isinstance(port, int) else int(str(port))
        return [
            (
                ai_brief_sources.socket.AF_INET6,
                ai_brief_sources.socket.SOCK_STREAM,
                0,
                "",
                ("2001:db8::9", port_int, 0, 0),
            )
        ]

    monkeypatch.setattr(
        ai_brief_sources.socket,
        "getaddrinfo",
        original_getaddrinfo,
    )

    with (
        collectors._pin_feed_url_dns(
            ("feeds.example.test",),
            (
                (
                    ai_brief_sources.socket.AF_INET,
                    ai_brief_sources.socket.SOCK_STREAM,
                    0,
                    "",
                    ("93.184.216.34", 443),
                ),
            ),
        ),
        pytest.raises(ai_brief_sources.socket.gaierror),
    ):
        ai_brief_sources.socket.getaddrinfo(
            "feeds.example.test",
            443,
            family=ai_brief_sources.socket.AF_INET6,
            type=ai_brief_sources.socket.SOCK_STREAM,
        )

    assert calls == []
    assert ai_brief_sources.socket.getaddrinfo is original_getaddrinfo


def test_feed_dns_pin_rejects_same_host_same_port_nonzero_flags(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[object] = []

    def original_getaddrinfo(
        host: object,
        port: object,
        *_args: object,
        **_kwargs: object,
    ) -> list[object]:
        calls.append(host)
        port_int = port if isinstance(port, int) else int(str(port))
        return [(0, 0, 0, "", ("127.0.0.1", port_int))]

    monkeypatch.setattr(
        ai_brief_sources.socket,
        "getaddrinfo",
        original_getaddrinfo,
    )

    with (
        collectors._pin_feed_url_dns(
            ("feeds.example.test",),
            (
                (
                    ai_brief_sources.socket.AF_INET,
                    ai_brief_sources.socket.SOCK_STREAM,
                    0,
                    "",
                    ("93.184.216.34", 443),
                ),
            ),
        ),
        pytest.raises(ai_brief_sources.socket.gaierror),
    ):
        ai_brief_sources.socket.getaddrinfo(
            "feeds.example.test",
            443,
            family=ai_brief_sources.socket.AF_INET,
            type=ai_brief_sources.socket.SOCK_STREAM,
            flags=1,
        )

    assert calls == []
    assert ai_brief_sources.socket.getaddrinfo is original_getaddrinfo


def test_feed_dns_resolver_waits_for_slot_within_timeout(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class _RecordingSlots:
        def __init__(self) -> None:
            self.acquire_calls: list[tuple[bool, float | None]] = []

        def acquire(
            self,
            blocking: bool = True,
            timeout: float | None = None,
        ) -> bool:
            self.acquire_calls.append((blocking, timeout))
            return True

        def release(self) -> None:
            pass

    slots = _RecordingSlots()
    monkeypatch.setattr(collectors, "_FEED_DNS_RESOLVER_SLOTS", slots)
    monkeypatch.setattr(
        ai_brief_sources.socket,
        "getaddrinfo",
        lambda *_args, **_kwargs: [(0, 0, 0, "", ("93.184.216.34", 443))],
    )

    addrinfos = collectors._getaddrinfo_with_timeout(
        "feeds.example.test",
        443,
        timeout=0.5,
    )

    assert addrinfos == [(0, 0, 0, "", ("93.184.216.34", 443))]
    assert slots.acquire_calls == [(True, 0.5)]


def test_feed_dns_resolver_releases_slot_when_thread_start_fails(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class _RecordingSlots:
        def __init__(self) -> None:
            self.release_count = 0

        def acquire(
            self,
            blocking: bool = True,
            timeout: float | None = None,
        ) -> bool:
            return True

        def release(self) -> None:
            self.release_count += 1

    class _FailingThread:
        def __init__(self, *_args: object, **_kwargs: object) -> None:
            pass

        def start(self) -> None:
            raise RuntimeError("thread unavailable")

    slots = _RecordingSlots()
    monkeypatch.setattr(collectors, "_FEED_DNS_RESOLVER_SLOTS", slots)
    monkeypatch.setattr(collectors.threading, "Thread", _FailingThread)

    with pytest.raises(RuntimeError, match="thread unavailable"):
        collectors._getaddrinfo_with_timeout(
            "feeds.example.test",
            443,
            timeout=0.5,
        )

    assert slots.release_count == 1


def test_feed_dns_resolver_does_not_start_thread_when_slot_wait_expires(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class _RecordingSlots:
        def __init__(self) -> None:
            self.release_count = 0

        def acquire(
            self,
            blocking: bool = True,
            timeout: float | None = None,
        ) -> bool:
            return True

        def release(self) -> None:
            self.release_count += 1

    class _UnexpectedThread:
        def __init__(self, *_args: object, **_kwargs: object) -> None:
            raise AssertionError("resolver thread should not start after timeout")

    slots = _RecordingSlots()
    monotonic_values = iter([0.0, 0.6])
    monkeypatch.setattr(collectors, "_FEED_DNS_RESOLVER_SLOTS", slots)
    monkeypatch.setattr(collectors.time, "monotonic", lambda: next(monotonic_values))
    monkeypatch.setattr(collectors.threading, "Thread", _UnexpectedThread)

    with pytest.raises(TimeoutError):
        collectors._getaddrinfo_with_timeout(
            "feeds.example.test",
            443,
            timeout=0.5,
        )

    assert slots.release_count == 1


def test_feed_dns_resolver_rejects_result_completed_after_timeout(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class _RecordingSlots:
        def __init__(self) -> None:
            self.release_count = 0

        def acquire(
            self,
            blocking: bool = True,
            timeout: float | None = None,
        ) -> bool:
            return True

        def release(self) -> None:
            self.release_count += 1

    class _SynchronousThread:
        def __init__(self, *, target, **_kwargs: object) -> None:
            self._target = target

        def start(self) -> None:
            self._target()

    slots = _RecordingSlots()
    monotonic_values = iter([0.0, 0.0, 0.6, 0.6])
    monkeypatch.setattr(collectors, "_FEED_DNS_RESOLVER_SLOTS", slots)
    monkeypatch.setattr(
        ai_brief_sources.socket,
        "getaddrinfo",
        lambda *_args, **_kwargs: [(0, 0, 0, "", ("93.184.216.34", 443))],
    )
    monkeypatch.setattr(collectors.time, "monotonic", lambda: next(monotonic_values))
    monkeypatch.setattr(collectors.threading, "Thread", _SynchronousThread)

    with pytest.raises(TimeoutError):
        collectors._getaddrinfo_with_timeout(
            "feeds.example.test",
            443,
            timeout=0.5,
        )

    assert slots.release_count == 1


def test_feed_dns_resolver_late_completion_releases_acquired_slot(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class _RecordingSlots:
        def __init__(self, released: threading.Event) -> None:
            self.released = released
            self.release_count = 0

        def acquire(
            self,
            blocking: bool = True,
            timeout: float | None = None,
        ) -> bool:
            return True

        def release(self) -> None:
            self.release_count += 1
            self.released.set()

    class _UnexpectedSlots:
        def release(self) -> None:
            raise AssertionError("late resolver released the replacement slots")

    resolver_started = threading.Event()
    release_resolver = threading.Event()
    slot_released = threading.Event()

    def gated_getaddrinfo(*_args: object, **_kwargs: object) -> list[object]:
        resolver_started.set()
        release_resolver.wait(timeout=1.0)
        return [(0, 0, 0, "", ("93.184.216.34", 443))]

    slots = _RecordingSlots(slot_released)
    monkeypatch.setattr(collectors, "_FEED_DNS_RESOLVER_SLOTS", slots)
    monkeypatch.setattr(ai_brief_sources.socket, "getaddrinfo", gated_getaddrinfo)

    with pytest.raises(TimeoutError):
        collectors._getaddrinfo_with_timeout(
            "feeds.example.test",
            443,
            timeout=0.001,
        )

    assert resolver_started.wait(timeout=1.0)
    monkeypatch.setattr(
        collectors,
        "_FEED_DNS_RESOLVER_SLOTS",
        _UnexpectedSlots(),
    )
    release_resolver.set()

    assert slot_released.wait(timeout=1.0)
    assert slots.release_count == 1


def test_collect_script_outputs_json(capsys) -> None:
    exit_code = collect_sources_main(
        [
            "--feed-catalog",
            _feed_fixture("feeds.good.json"),
            "--ticker",
            "MSFT.NAS",
            "--now",
            "2026-05-06T12:00:00+00:00",
            "--pretty",
        ]
    )

    captured = capsys.readouterr()
    payload = json.loads(captured.out)
    assert exit_code == 0
    assert payload["schema"] == "sab.ai_brief_sources.v1"
    assert payload["type"] == "ai_brief_sources"
    assert payload["summary"]["covered_tickers"] == ["MSFT.NAS"]
    assert payload["sources"][0]["title"] == "Microsoft cloud bookings accelerate"


def test_collect_script_passes_feed_timeout_seconds_to_url_fetch(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys,
) -> None:
    feed_url = "https://feeds.example.test/aapl.xml"
    catalog = tmp_path / "feeds.json"
    catalog.write_text(
        json.dumps(
            {
                "schema": "sab.ai_brief_source_feed_catalog.v1",
                "feeds": [{"ticker": "AAPL.NAS", "url": feed_url}],
            }
        ),
        encoding="utf-8",
    )
    session = _MockFeedSession(
        {feed_url: _MockFeedResponse(Path(_feed_fixture("aapl.rss")).read_bytes())}
    )
    _install_mock_feed_session(monkeypatch, session)

    exit_code = collect_sources_main(
        [
            "--feed-catalog",
            catalog.as_posix(),
            "--feed-timeout-seconds",
            "2.5",
            "--now",
            "2026-05-06T12:00:00+00:00",
        ]
    )

    captured = capsys.readouterr()
    payload = json.loads(captured.out)
    assert exit_code == 0
    assert payload["summary"]["covered_tickers"] == ["AAPL.NAS"]
    _assert_timeout_tuple_not_expired(
        session.calls[0]["timeout"],
        requested_timeout_seconds=2.5,
    )


def test_collect_script_creates_output_parent(tmp_path: Path) -> None:
    output_path = tmp_path / "reports" / "collected.sources.json"

    exit_code = collect_sources_main(
        [
            "--feed-catalog",
            _feed_fixture("feeds.good.json"),
            "--ticker",
            "AAPL.NAS",
            "--output",
            output_path.as_posix(),
            "--now",
            "2026-05-06T12:00:00+00:00",
        ]
    )

    payload = json.loads(output_path.read_text(encoding="utf-8"))
    assert exit_code == 0
    assert payload["type"] == "ai_brief_sources"
    assert payload["summary"]["covered_tickers"] == ["AAPL.NAS"]


def test_parse_collect_now_requires_utc_offset() -> None:
    with pytest.raises(ValueError, match="UTC offset"):
        parse_collect_now("2026-05-06T12:00:00")
