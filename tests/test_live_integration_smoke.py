from __future__ import annotations

import datetime as dt
import importlib
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pytest
from sab.ai_brief_sources import AiBriefSourceProviderError, AiBriefSourceProviderResult

SMOKE_NOW = dt.datetime(2026, 6, 1, 9, 0, tzinfo=dt.UTC)


def _load_smoke_module():
    try:
        return importlib.import_module("scripts.live_integration_smoke")
    except ModuleNotFoundError as exc:
        pytest.fail(f"live integration smoke script is missing: {exc}")


def _write_entry_report(tmp_path: Path) -> Path:
    path = tmp_path / "source.entry.json"
    path.write_text(
        json.dumps(
            {
                "schema": "sab.report.v1",
                "type": "entry",
                "market": "US",
                "entries": [
                    {"ticker": "AAPL.NAS", "action": "ENTER"},
                    {"ticker": "MSFT.NAS", "action": "REVIEW"},
                ],
            }
        ),
        encoding="utf-8",
    )
    return path


@dataclass(frozen=True)
class _CollectorResult:
    status: str
    sources: list[dict[str, object]]
    issues: list[dict[str, object]]

    def to_dict(self) -> dict[str, object]:
        return {
            "status": self.status,
            "sources": self.sources,
            "issues": self.issues,
            "summary": {
                "source_count": len(self.sources),
                "issue_count": len(self.issues),
            },
        }


@dataclass(frozen=True)
class _FakeConfig:
    kis_app_key: str | None
    kis_app_secret: str | None
    kis_base_url: str | None
    kis_min_interval_ms: float | None
    data_dir: str


@dataclass(frozen=True)
class _FakeKISCredentials:
    app_key: str
    app_secret: str
    base_url: str
    env: str


class _FakeKISClient:
    def __init__(
        self,
        creds: _FakeKISCredentials,
        *,
        cache_dir: str | None = None,
        min_interval: float | None = None,
    ) -> None:
        self.creds = creds
        self.cache_dir = cache_dir
        self.min_interval = min_interval
        self.calls: list[tuple[str, dict[str, object]]] = []
        self.cache_status = "miss"

    def ensure_token(self) -> None:
        self.calls.append(("ensure_token", {}))

    def domestic_price_detail(self, *, ticker: str) -> dict[str, object]:
        self.calls.append(("domestic_price_detail", {"ticker": ticker}))
        return {"stck_prpr": "72000", "stck_bsop_date": "20260601"}

    def overseas_price_detail(self, *, symbol: str, exchange: str) -> dict[str, object]:
        self.calls.append(
            ("overseas_price_detail", {"symbol": symbol, "exchange": exchange})
        )
        return {"last": "190.25", "xymd": "20260601"}

    def daily_candles(
        self,
        ticker: str,
        *,
        count: int = 120,
        adjusted: bool = True,
    ) -> list[dict[str, object]]:
        self.calls.append(
            (
                "daily_candles",
                {"ticker": ticker, "count": count, "adjusted": adjusted},
            )
        )
        return [{"date": "20260529", "close": 72000.0}]

    def overseas_daily_candles(
        self,
        *,
        symbol: str,
        exchange: str = "NAS",
        count: int = 120,
        adjusted: bool = True,
    ) -> list[dict[str, object]]:
        self.calls.append(
            (
                "overseas_daily_candles",
                {
                    "symbol": symbol,
                    "exchange": exchange,
                    "count": count,
                    "adjusted": adjusted,
                },
            )
        )
        return [{"date": "20260529", "close": 190.25}]


def test_live_integration_smoke_runs_selected_boundaries_and_redacts_secrets(
    tmp_path: Path,
) -> None:
    smoke = _load_smoke_module()
    entry_report = _write_entry_report(tmp_path)
    feed_catalog = tmp_path / "feeds.json"
    feed_catalog.write_text(
        json.dumps(
            {
                "schema": "sab.ai_brief_source_feed_catalog.v1",
                "feeds": [
                    {"ticker": "AAPL.NAS", "url": "https://feeds.example/aapl.xml"}
                ],
            }
        ),
        encoding="utf-8",
    )
    fake_kis_clients: list[_FakeKISClient] = []

    def fake_collect_ai_brief_sources(**kwargs: object) -> _CollectorResult:
        assert kwargs["feed_catalog_path"] == feed_catalog.as_posix()
        assert kwargs["tickers"] == {"AAPL.NAS"}
        assert kwargs["now"] == SMOKE_NOW
        return _CollectorResult(
            status="PASS",
            sources=[
                {
                    "ticker": "AAPL.NAS",
                    "title": "Apple feed item",
                    "url": "https://news.example/aapl",
                    "published_at": "2026-06-01T08:30:00+00:00",
                }
            ],
            issues=[],
        )

    def fake_load_ai_brief_sources(**kwargs: object) -> AiBriefSourceProviderResult:
        assert kwargs["source_provider"] == "finnhub"
        assert kwargs["eligible_tickers"] == {"AAPL.NAS"}
        assert kwargs["source_api_url"] is None
        assert kwargs["now"] == SMOKE_NOW
        return AiBriefSourceProviderResult(
            sources_by_ticker={
                "AAPL.NAS": [
                    {
                        "title": "Apple API item",
                        "url": "https://news.example/api-aapl",
                        "published_at": "2026-06-01T08:45:00+00:00",
                    }
                ]
            },
            source_issues=[],
        )

    def fake_kis_client_cls(*args: Any, **kwargs: Any) -> _FakeKISClient:
        client = _FakeKISClient(*args, **kwargs)
        fake_kis_clients.append(client)
        return client

    result = smoke.run_smoke(
        rss_feed_catalog_path=feed_catalog.as_posix(),
        rss_tickers={"AAPL.NAS"},
        source_entry_report_path=entry_report.as_posix(),
        source_provider_specs=[
            smoke.SourceProviderSmokeSpec(label="finnhub", provider="finnhub")
        ],
        kis_token=True,
        kis_domestic_price_tickers=["005930"],
        kis_overseas_price_tickers=["AAPL.NAS"],
        kis_domestic_candle_tickers=["005930"],
        kis_overseas_candle_tickers=["AAPL.NAS"],
        kis_candle_count=2,
        collect_ai_brief_sources_fn=fake_collect_ai_brief_sources,
        load_ai_brief_sources_fn=fake_load_ai_brief_sources,
        load_config_fn=lambda: _FakeConfig(
            kis_app_key="app-key-secret",
            kis_app_secret="app-secret-value",
            kis_base_url="https://openapi.example",
            kis_min_interval_ms=25,
            data_dir=(tmp_path / "data").as_posix(),
        ),
        KISCredentialsCls=_FakeKISCredentials,
        KISClientCls=fake_kis_client_cls,
        now=SMOKE_NOW,
    )

    payload = result.to_dict()
    assert payload["status"] == "PASS"
    assert [check["name"] for check in payload["checks"]] == [
        "rss-feed",
        "source-provider:finnhub",
        "kis-token",
        "kis-domestic-price:005930",
        "kis-overseas-price:AAPL.NAS",
        "kis-domestic-candles:005930",
        "kis-overseas-candles:AAPL.NAS",
    ]
    assert fake_kis_clients[0].min_interval == pytest.approx(0.025)
    assert fake_kis_clients[0].calls == [
        ("ensure_token", {}),
        ("domestic_price_detail", {"ticker": "005930"}),
        ("overseas_price_detail", {"symbol": "AAPL", "exchange": "NAS"}),
        ("daily_candles", {"ticker": "005930", "count": 2, "adjusted": False}),
        (
            "overseas_daily_candles",
            {"symbol": "AAPL", "exchange": "NAS", "count": 2, "adjusted": False},
        ),
    ]
    serialized = json.dumps(payload, ensure_ascii=False)
    assert "app-key-secret" not in serialized
    assert "app-secret-value" not in serialized


@pytest.mark.parametrize(
    ("kis_kwargs", "expected_message"),
    [
        (
            {"kis_domestic_price_tickers": ["AAPL.NAS"]},
            "domestic KIS smoke ticker must be a KR ticker",
        ),
        (
            {"kis_domestic_candle_tickers": ["AAPL.NAS"]},
            "domestic KIS smoke ticker must be a KR ticker",
        ),
        (
            {"kis_overseas_price_tickers": ["005930"]},
            "overseas KIS smoke ticker must be a US ticker",
        ),
        (
            {"kis_overseas_candle_tickers": ["005930"]},
            "overseas KIS smoke ticker must be a US ticker",
        ),
    ],
)
def test_live_integration_smoke_rejects_wrong_market_kis_tickers_before_client_setup(
    tmp_path: Path,
    kis_kwargs: dict[str, list[str]],
    expected_message: str,
) -> None:
    smoke = _load_smoke_module()
    fake_kis_clients: list[_FakeKISClient] = []

    def fake_kis_client_cls(*args: Any, **kwargs: Any) -> _FakeKISClient:
        client = _FakeKISClient(*args, **kwargs)
        fake_kis_clients.append(client)
        return client

    with pytest.raises(ValueError, match=expected_message):
        smoke.run_smoke(
            load_config_fn=lambda: _FakeConfig(
                kis_app_key="app-key-secret",
                kis_app_secret="app-secret-value",
                kis_base_url="https://openapi.example",
                kis_min_interval_ms=25,
                data_dir=(tmp_path / "data").as_posix(),
            ),
            KISCredentialsCls=_FakeKISCredentials,
            KISClientCls=fake_kis_client_cls,
            now=SMOKE_NOW,
            **kis_kwargs,
        )

    assert fake_kis_clients == []


def test_live_integration_smoke_marks_provider_errors_as_fail(tmp_path: Path) -> None:
    smoke = _load_smoke_module()
    entry_report = _write_entry_report(tmp_path)

    def fail_load_ai_brief_sources(**_kwargs: object) -> AiBriefSourceProviderResult:
        raise AiBriefSourceProviderError("FINNHUB_API_KEY is missing")

    result = smoke.run_smoke(
        source_entry_report_path=entry_report.as_posix(),
        source_provider_specs=[
            smoke.SourceProviderSmokeSpec(label="finnhub", provider="finnhub")
        ],
        load_ai_brief_sources_fn=fail_load_ai_brief_sources,
        now=SMOKE_NOW,
    )

    payload = result.to_dict()
    assert payload["status"] == "FAIL"
    assert payload["checks"][0]["status"] == "FAIL"
    assert payload["checks"][0]["summary"]["error_code"] == "source_provider_failed"
    assert "FINNHUB_API_KEY is missing" in payload["checks"][0]["message"]


def test_live_integration_smoke_cli_outputs_json_and_returns_nonzero_for_fail(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    smoke = _load_smoke_module()
    captured_kwargs: dict[str, object] = {}

    class FakeResult:
        status = "FAIL"

        def to_dict(self) -> dict[str, object]:
            return {
                "status": "FAIL",
                "checks": [
                    {
                        "name": "source-provider:finnhub",
                        "status": "FAIL",
                        "message": "provider failed",
                        "summary": {},
                    }
                ],
            }

    def fake_run_smoke(**kwargs: object) -> FakeResult:
        captured_kwargs.update(kwargs)
        return FakeResult()

    monkeypatch.setattr(smoke, "run_smoke", fake_run_smoke)

    exit_code = smoke.main(
        [
            "--entry-report",
            "reports/example.entry.json",
            "--source-provider",
            "finnhub=finnhub",
            "--kis-token",
            "--pretty",
        ]
    )

    out = capsys.readouterr().out
    assert exit_code == 1
    assert out.startswith("{\n  ")
    assert json.loads(out)["status"] == "FAIL"
    assert captured_kwargs["source_entry_report_path"] == "reports/example.entry.json"
    assert captured_kwargs["source_provider_specs"] == [
        smoke.SourceProviderSmokeSpec(label="finnhub", provider="finnhub")
    ]
    assert captured_kwargs["kis_token"] is True


def test_live_integration_smoke_cli_requires_at_least_one_check() -> None:
    smoke = _load_smoke_module()
    with pytest.raises(SystemExit) as exc_info:
        smoke.main([])

    assert exc_info.value.code == 2
