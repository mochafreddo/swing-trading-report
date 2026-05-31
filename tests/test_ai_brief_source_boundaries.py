from __future__ import annotations

import datetime as dt
import time

import pytest
from sab import ai_brief_source_report as source_report
from sab import ai_brief_source_url_safety as source_url_safety
from sab import ai_brief_sources


def test_source_report_boundary_normalizes_local_rows_without_dns(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fail_getaddrinfo(*_args: object, **_kwargs: object) -> list[object]:
        raise AssertionError("offline source report normalization should not use DNS")

    monkeypatch.setattr(source_url_safety.socket, "getaddrinfo", fail_getaddrinfo)

    now = dt.datetime(2026, 5, 5, 9, 0, tzinfo=dt.UTC)
    result = source_report.normalize_source_rows(
        rows=[
            {
                "ticker": "AAPL.NAS",
                "title": "Apple source",
                "url": "https://news.example.test/aapl",
                "published_at": now.isoformat(),
            }
        ],
        eligible_tickers={"AAPL.NAS"},
        now=now,
        issue_prefix="local_source",
        issue_subject="local source",
    )

    assert result.source_issues == []
    assert result.sources_by_ticker == {
        "AAPL.NAS": [
            {
                "title": "Apple source",
                "url": "https://news.example.test/aapl",
                "published_at": now.isoformat(),
            }
        ]
    }


def test_source_url_safety_boundary_resolves_and_rejects_private_api_dns(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        source_url_safety.socket,
        "getaddrinfo",
        lambda *_args, **_kwargs: [
            (
                source_url_safety.socket.AF_INET,
                source_url_safety.socket.SOCK_STREAM,
                0,
                "",
                ("10.0.0.9", 443),
            )
        ],
    )

    with pytest.raises(ValueError, match="local or private"):
        source_url_safety.validate_source_api_request_url(
            "https://source.example/api",
            deadline=None,
        )


def test_source_api_dns_pin_lock_timeout_keeps_specific_provider_message(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class _NonAcquiringLock:
        def acquire(self, *, timeout: float) -> bool:
            return False

        def release(self) -> None:
            raise AssertionError("release should not run when acquire fails")

    monkeypatch.setattr(ai_brief_sources, "SOURCE_DNS_PIN_LOCK", _NonAcquiringLock())
    monkeypatch.setattr(
        source_url_safety.socket,
        "getaddrinfo",
        lambda *_args, **_kwargs: [
            (
                source_url_safety.socket.AF_INET,
                source_url_safety.socket.SOCK_STREAM,
                0,
                "",
                ("93.184.216.34", 443),
            )
        ],
    )

    with pytest.raises(
        ai_brief_sources.AiBriefSourceProviderTimeoutError,
        match="source API DNS pin lock timed out",
    ):
        ai_brief_sources._validate_source_api_request_url(
            "https://source.example/api",
            deadline=time.monotonic() + 1.0,
        )
