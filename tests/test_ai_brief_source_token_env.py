from __future__ import annotations

import datetime as dt
import json

import pytest
from sab import ai_brief_sources
from sab.ai_brief_sources import load_ai_brief_sources


class _SourceApiResponse:
    status_code = 200

    def __init__(self, payload: dict[str, object]) -> None:
        self.text = json.dumps(payload)

    def close(self) -> None:
        pass


class _SourceApiSession:
    def __init__(self, payload: dict[str, object]) -> None:
        self.payload = payload
        self.calls: list[dict[str, object]] = []

    def post(self, url: str, **kwargs: object) -> _SourceApiResponse:
        self.calls.append({"url": url, **kwargs})
        return _SourceApiResponse(self.payload)

    def close(self) -> None:
        pass


@pytest.fixture(autouse=True)
def _mock_source_api_dns(monkeypatch: pytest.MonkeyPatch) -> None:
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


def test_http_json_sends_token_for_market_specific_configured_url(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    session = _SourceApiSession({"sources": []})
    monkeypatch.setenv("AI_BRIEF_SOURCE_API_TOKEN", "source-token")
    monkeypatch.setenv("AI_BRIEF_SOURCE_API_URL_US", "https://source.example/us")
    monkeypatch.setattr("sab.ai_brief_sources.requests.Session", lambda: session)

    load_ai_brief_sources(
        source_provider="http-json",
        source_report_path=None,
        source_api_url="https://source.example/us",
        source_timeout_seconds=4.5,
        eligible_tickers={"AAPL.NAS"},
        now=dt.datetime(2026, 5, 5, 9, 0, tzinfo=dt.UTC),
    )

    headers = session.calls[0]["headers"]
    assert isinstance(headers, dict)
    assert headers["Authorization"] == "Bearer source-token"
