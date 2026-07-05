from __future__ import annotations

import datetime as dt
import json
import logging
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace
from typing import Any, cast
from unittest.mock import patch

import pytest
from sab.config import Config
from sab.config_loader import ConfigLoadError
from sab.holdings_loader import (
    Holding,
    HoldingsData,
    HoldingSettings,
)
from sab.report.supabase_storage import SupabaseReportIndexError
from sab.scan import run_scan
from sab.sell import _resolve_sell_target_bars, run_sell
from sab.signals.sell_rules import SellEvaluation


def _write_json_artifact(path: Path, payload: dict[str, Any]) -> str:
    path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    return str(path)


def _write_watchlist(path: Path, tickers: list[str]) -> Path:
    path.write_text("\n".join(tickers) + "\n", encoding="utf-8")
    return path


@pytest.mark.parametrize(
    "err",
    [ConfigLoadError("bad config")],
)
def test_run_scan_returns_1_when_config_loading_fails(err: Exception) -> None:
    with patch("sab.scan.load_config", side_effect=err):
        code = run_scan(
            limit=None,
            watchlist_path=None,
            provider=None,
            screener_limit=None,
            universe=None,
        )

    assert code == 1


def test_run_scan_returns_1_when_watchlist_loading_fails() -> None:
    cfg = replace(Config(), data_provider="pykrx")

    with (
        patch("sab.scan.load_config", return_value=cfg),
        patch(
            "sab.scan.load_watchlist",
            side_effect=ConfigLoadError("watchlist has invalid ticker"),
        ),
    ):
        code = run_scan(
            limit=None,
            watchlist_path=None,
            provider=None,
            screener_limit=None,
            universe=None,
        )

    assert code == 1


def test_resolve_sell_target_bars_requests_tail_trim_buffer() -> None:
    runtime = SimpleNamespace(cfg=replace(Config(), min_history_bars=200), holdings=[])

    assert _resolve_sell_target_bars(cast(Any, runtime)) == 201


def test_run_scan_returns_1_when_watchlist_file_missing_in_watchlist_universe(
    tmp_path: Path,
) -> None:
    cfg = replace(
        Config(),
        data_provider="pykrx",
        watchlist_path=str(tmp_path / "missing-watchlist.txt"),
    )

    with (
        patch("sab.scan.load_config", return_value=cfg),
        patch("sab.scan.load_watchlist") as mock_load_watchlist,
    ):
        code = run_scan(
            limit=None,
            watchlist_path=None,
            provider=None,
            screener_limit=None,
            universe="watchlist",
        )

    assert code == 1
    mock_load_watchlist.assert_not_called()


def test_run_scan_returns_1_when_watchlist_file_missing_in_both_universe(
    tmp_path: Path,
) -> None:
    cfg = replace(
        Config(),
        data_provider="pykrx",
        watchlist_path=str(tmp_path / "missing-watchlist.txt"),
        screener_enabled=True,
    )

    with (
        patch("sab.scan.load_config", return_value=cfg),
        patch("sab.scan.load_watchlist") as mock_load_watchlist,
    ):
        code = run_scan(
            limit=None,
            watchlist_path=None,
            provider=None,
            screener_limit=None,
            universe="both",
        )

    assert code == 1
    mock_load_watchlist.assert_not_called()


def test_run_scan_screener_universe_allows_missing_watchlist_file(
    tmp_path: Path,
) -> None:
    cfg = replace(
        Config(),
        data_provider="pykrx",
        data_dir=str(tmp_path),
        report_dir=str(tmp_path),
        watchlist_path=str(tmp_path / "missing-watchlist.txt"),
        universe_markets=["US"],
    )

    def _fake_collect(
        runtime: Any,
        *,
        screener_enabled: bool,
        screener_only: bool,
        screener_limit: int,
        screener_limit_from_cli: bool,
        evaluation_limit: int | None,
    ) -> None:
        del (
            screener_enabled,
            screener_only,
            screener_limit,
            screener_limit_from_cli,
            evaluation_limit,
        )
        runtime.tickers = ["AAPL.US"]
        runtime.market_data = {
            "AAPL.US": [
                {
                    "date": "20250101",
                    "open": 100.0,
                    "high": 101.0,
                    "low": 99.0,
                    "close": 100.0,
                    "volume": 1_000_000.0,
                }
            ]
        }

    with (
        patch("sab.scan.load_config", return_value=cfg),
        patch("sab.scan.scan_screener._load_scan_tickers") as mock_load_scan_tickers,
        patch("sab.scan._collect_scan_runtime", side_effect=_fake_collect),
        patch("sab.scan._evaluate_scan_runtime", return_value=None),
        patch(
            "sab.scan._render_scan_report",
            return_value=str(tmp_path / "2026-02-26.buy.md"),
        ),
        patch("sab.scan.maybe_upload_report_artifact", return_value=None),
    ):
        code = run_scan(
            limit=None,
            watchlist_path=None,
            provider=None,
            screener_limit=None,
            universe="screener",
        )

    assert code == 0
    mock_load_scan_tickers.assert_not_called()


def test_run_scan_screener_universe_skips_watchlist_loading(tmp_path: Path) -> None:
    cfg = replace(
        Config(),
        data_provider="pykrx",
        data_dir=str(tmp_path),
        report_dir=str(tmp_path),
        universe_markets=["US"],
    )

    def _fake_collect(
        runtime: Any,
        *,
        screener_enabled: bool,
        screener_only: bool,
        screener_limit: int,
        screener_limit_from_cli: bool,
        evaluation_limit: int | None,
    ) -> None:
        del (
            screener_enabled,
            screener_only,
            screener_limit,
            screener_limit_from_cli,
            evaluation_limit,
        )
        runtime.tickers = ["AAPL.US"]
        runtime.market_data = {
            "AAPL.US": [
                {
                    "date": "20250101",
                    "open": 100.0,
                    "high": 101.0,
                    "low": 99.0,
                    "close": 100.0,
                    "volume": 1_000_000.0,
                }
            ]
        }

    with (
        patch("sab.scan.load_config", return_value=cfg),
        patch("sab.scan.scan_screener._load_scan_tickers") as mock_load_scan_tickers,
        patch("sab.scan._collect_scan_runtime", side_effect=_fake_collect),
        patch("sab.scan._evaluate_scan_runtime", return_value=None),
        patch(
            "sab.scan._render_scan_report",
            return_value=str(tmp_path / "2026-02-26.buy.md"),
        ),
        patch("sab.scan.maybe_upload_report_artifact", return_value=None),
    ):
        code = run_scan(
            limit=None,
            watchlist_path=None,
            provider=None,
            screener_limit=None,
            universe="screener",
        )

    assert code == 0
    mock_load_scan_tickers.assert_not_called()


def test_run_scan_fails_fast_when_collection_sets_fatal(tmp_path: Path) -> None:
    cfg = replace(
        Config(),
        data_provider="pykrx",
        data_dir=str(tmp_path),
        report_dir=str(tmp_path),
    )

    def _fake_collect(
        runtime: Any,
        *,
        screener_enabled: bool,
        screener_only: bool,
        screener_limit: int,
        screener_limit_from_cli: bool,
        evaluation_limit: int | None,
    ) -> None:
        del (
            screener_enabled,
            screener_only,
            screener_limit,
            screener_limit_from_cli,
            evaluation_limit,
        )
        runtime.failures.append("fatal from screener boundary")
        runtime.fatal_failure = True

    with (
        patch("sab.scan.load_config", return_value=cfg),
        patch("sab.scan.scan_screener._load_scan_tickers", return_value=[]),
        patch("sab.scan._collect_scan_runtime", side_effect=_fake_collect),
        patch("sab.scan._evaluate_scan_runtime") as mock_evaluate,
        patch("sab.scan._mark_missing_scan_market_data") as mock_mark_missing,
        patch(
            "sab.scan._render_scan_report",
            return_value=str(tmp_path / "2026-02-26.buy.md"),
        ),
        patch("sab.scan.maybe_upload_report_artifact", return_value=None),
    ):
        code = run_scan(
            limit=None,
            watchlist_path=None,
            provider=None,
            screener_limit=None,
            universe=None,
        )

    assert code == 1
    mock_evaluate.assert_not_called()
    mock_mark_missing.assert_not_called()


@pytest.mark.parametrize(
    "err",
    [ConfigLoadError("bad config")],
)
def test_run_sell_returns_1_when_config_loading_fails(err: Exception) -> None:
    with patch("sab.sell.load_config", side_effect=err):
        code = run_sell(provider=None)

    assert code == 1


def test_run_sell_returns_1_when_resolved_holdings_file_is_missing(
    tmp_path: Path,
) -> None:
    cfg = replace(
        Config(),
        data_provider="pykrx",
        data_dir=str(tmp_path),
        report_dir=str(tmp_path),
        holdings_path=str(tmp_path / "missing-holdings.yaml"),
    )

    with patch("sab.sell.load_config", return_value=cfg):
        code = run_sell(provider=None)

    assert code == 1


def _build_candles(count: int = 220) -> list[dict[str, float | str]]:
    candles: list[dict[str, float | str]] = []
    base_date = dt.date.today() - dt.timedelta(days=count - 1)
    for idx in range(count):
        day = base_date + dt.timedelta(days=idx)
        close = 100.0 + (idx * 0.1)
        candles.append(
            {
                "date": day.strftime("%Y%m%d"),
                "open": close,
                "high": close + 1.0,
                "low": close - 1.0,
                "close": close,
                "volume": 1_000_000.0,
            }
        )
    return candles


class _FakeKISClient:
    cache_status = "none"

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        pass

    def overseas_daily_candles(
        self, *, symbol: str, exchange: str, count: int
    ) -> list[dict[str, float | str]]:
        return _build_candles()

    def daily_candles(self, symbol: str, *, count: int) -> list[dict[str, float | str]]:
        return _build_candles()


class _FakeHitKISClient(_FakeKISClient):
    cache_status = "hit"


def _build_holdings(tickers: list[str]) -> HoldingsData:
    return HoldingsData(
        path=None,
        settings=HoldingSettings(),
        holdings=[
            Holding(
                ticker=ticker,
                quantity=1.0,
                entry_price=100.0,
                entry_date="2025-01-01",
            )
            for ticker in tickers
        ],
    )


@pytest.mark.parametrize(
    ("tickers", "expected_exchange"),
    [
        (["AAPL.NAS", "005930"], {"AAPL.NAS": "NAS", "005930": None}),
        (["005930", "IBM.NYS"], {"005930": None, "IBM.NYS": "NYS"}),
    ],
)
def test_run_sell_maps_exchange_per_ticker_without_suffix_scope_leak(
    tmp_path: Path, tickers: list[str], expected_exchange: dict[str, str | None]
) -> None:
    cfg = replace(
        Config(),
        data_provider="kis",
        kis_app_key="key",
        kis_app_secret="secret",
        kis_base_url="https://example.com",
        data_dir=str(tmp_path),
        report_dir=str(tmp_path),
        holdings=_build_holdings(tickers),
        sell_mode="generic",
    )
    captured_exchange: dict[str, str | None] = {}

    def fake_evaluate_sell_signals(
        ticker: str,
        candles: list[dict[str, float]],
        holding: dict[str, Any],
        settings: Any,
    ) -> SellEvaluation:
        captured_exchange[ticker] = holding.get("exchange")
        return SellEvaluation(
            action="HOLD",
            reasons=["ok"],
            eval_price=float(candles[-1]["close"]),
            eval_date=str(candles[-1]["date"]),
        )

    with (
        patch("sab.sell.load_config", return_value=cfg),
        patch("sab.market_data_common.KISClient", _FakeKISClient),
        patch("sab.sell.resolve_fx_rate", return_value=(None, None, [])),
        patch(
            "sab.sell.write_sell_report",
            return_value=str(tmp_path / "2026-02-06.sell.md"),
        ),
        patch("sab.sell.maybe_upload_report_artifact", return_value=None),
        patch("sab.sell.evaluate_sell_signals", side_effect=fake_evaluate_sell_signals),
    ):
        code = run_sell(provider=None)

    assert code == 0
    assert captured_exchange == expected_exchange


def test_run_scan_logs_kis_token_cache_status_once(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    watchlist_file = tmp_path / "watchlist.txt"
    watchlist_file.write_text("005930\n", encoding="utf-8")
    cfg = replace(
        Config(),
        data_provider="kis",
        kis_app_key="key",
        kis_app_secret="secret",
        kis_base_url="https://example.com",
        data_dir=str(tmp_path),
        report_dir=str(tmp_path),
        watchlist_path=str(watchlist_file),
        screener_enabled=False,
        screener_only=False,
    )
    caplog.set_level(logging.INFO)

    with (
        patch("sab.scan.load_config", return_value=cfg),
        patch("sab.scan.load_watchlist", return_value=["005930"]),
        patch("sab.market_data_common.KISClient", _FakeHitKISClient),
        patch("sab.scan.maybe_upload_report_artifact", return_value=None),
        patch(
            "sab.scan.write_report",
            return_value=str(tmp_path / "2026-02-19.buy.md"),
        ),
    ):
        code = run_scan(
            limit=None,
            watchlist_path=None,
            provider=None,
            screener_limit=None,
            universe="watchlist",
        )

    assert code == 0
    lines = [
        record.getMessage()
        for record in caplog.records
        if "KIS token cache status=" in record.getMessage()
    ]
    assert lines == [f"KIS token cache status=hit (env=real, cache_dir={tmp_path})"]


def test_run_sell_logs_kis_token_cache_status_once(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    cfg = replace(
        Config(),
        data_provider="kis",
        kis_app_key="key",
        kis_app_secret="secret",
        kis_base_url="https://example.com",
        data_dir=str(tmp_path),
        report_dir=str(tmp_path),
        holdings=_build_holdings(["005930"]),
    )
    caplog.set_level(logging.INFO)

    with (
        patch("sab.sell.load_config", return_value=cfg),
        patch("sab.market_data_common.KISClient", _FakeHitKISClient),
        patch("sab.sell.resolve_fx_rate", return_value=(None, None, [])),
        patch("sab.sell.maybe_upload_report_artifact", return_value=None),
        patch(
            "sab.sell.write_sell_report",
            return_value=str(tmp_path / "2026-02-19.sell.md"),
        ),
    ):
        code = run_sell(provider=None)

    assert code == 0
    lines = [
        record.getMessage()
        for record in caplog.records
        if "KIS token cache status=" in record.getMessage()
    ]
    assert lines == [f"KIS token cache status=hit (env=real, cache_dir={tmp_path})"]


def test_run_scan_logs_structured_run_lifecycle(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    monkeypatch.setenv("SAB_RUN_ID", "scan-test-run")
    watchlist_file = tmp_path / "watchlist.txt"
    watchlist_file.write_text("005930\n", encoding="utf-8")
    report_path = str(tmp_path / "2026-02-19.buy.json")
    cfg = replace(
        Config(),
        data_provider="kis",
        kis_app_key="key",
        kis_app_secret="secret",
        kis_base_url="https://example.com",
        data_dir=str(tmp_path),
        report_dir=str(tmp_path),
        watchlist_path=str(watchlist_file),
        screener_enabled=False,
        screener_only=False,
    )
    caplog.set_level(logging.INFO, logger="sab.scan")

    with (
        patch("sab.scan.load_config", return_value=cfg),
        patch("sab.scan.load_watchlist", return_value=["005930"]),
        patch("sab.market_data_common.KISClient", _FakeHitKISClient),
        patch("sab.scan.resolve_fx_rate", return_value=(None, None, [])),
        patch("sab.scan.maybe_upload_report_artifact", return_value=None),
        patch("sab.scan.write_report", return_value=report_path),
    ):
        code = run_scan(
            limit=None,
            watchlist_path=None,
            provider=None,
            screener_limit=None,
            universe="watchlist",
        )

    assert code == 0
    lifecycle = [
        record
        for record in caplog.records
        if getattr(record, "run_id", None) == "scan-test-run"
    ]
    assert [getattr(record, "event", None) for record in lifecycle] == [
        "scan_started",
        "scan_report_written",
        "scan_completed",
    ]
    assert all(getattr(record, "operation", None) == "scan" for record in lifecycle)
    assert lifecycle[1].__dict__["report_path"] == report_path
    assert lifecycle[-1].__dict__["status"] == "success"


def test_run_sell_logs_structured_run_lifecycle(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    monkeypatch.setenv("SAB_RUN_ID", "sell-test-run")
    report_path = str(tmp_path / "2026-02-19.sell.json")
    cfg = replace(
        Config(),
        data_provider="kis",
        kis_app_key="key",
        kis_app_secret="secret",
        kis_base_url="https://example.com",
        data_dir=str(tmp_path),
        report_dir=str(tmp_path),
        holdings=_build_holdings(["005930"]),
    )
    caplog.set_level(logging.INFO, logger="sab.sell")

    with (
        patch("sab.sell.load_config", return_value=cfg),
        patch("sab.market_data_common.KISClient", _FakeHitKISClient),
        patch("sab.sell.resolve_fx_rate", return_value=(None, None, [])),
        patch("sab.sell.maybe_upload_report_artifact", return_value=None),
        patch("sab.sell.write_sell_report", return_value=report_path),
    ):
        code = run_sell(provider=None)

    assert code == 0
    lifecycle = [
        record
        for record in caplog.records
        if getattr(record, "run_id", None) == "sell-test-run"
    ]
    assert [getattr(record, "event", None) for record in lifecycle] == [
        "sell_started",
        "sell_report_written",
        "sell_completed",
    ]
    assert all(getattr(record, "operation", None) == "sell" for record in lifecycle)
    assert lifecycle[1].__dict__["report_path"] == report_path
    assert lifecycle[-1].__dict__["status"] == "success"


def test_run_sell_expands_target_bars_for_long_held_positions(tmp_path: Path) -> None:
    cfg = replace(
        Config(),
        data_provider="kis",
        kis_app_key="key",
        kis_app_secret="secret",
        kis_base_url="https://example.com",
        data_dir=str(tmp_path),
        report_dir=str(tmp_path),
        holdings=HoldingsData(
            path=None,
            settings=HoldingSettings(),
            holdings=[
                Holding(
                    ticker="005930",
                    quantity=1.0,
                    entry_price=100.0,
                    entry_date="2020-01-02",
                )
            ],
        ),
    )
    captured_target_bars: list[int] = []

    def _collect_runtime(runtime: Any, *, target_bars: int) -> None:
        captured_target_bars.append(target_bars)
        runtime.market_data = {"005930": _build_candles()}

    with (
        patch("sab.sell.load_config", return_value=cfg),
        patch("sab.sell._collect_sell_runtime", side_effect=_collect_runtime),
        patch("sab.sell._evaluate_sell_runtime", return_value=[]),
        patch(
            "sab.sell.write_sell_report",
            return_value=str(tmp_path / "2026-02-24.sell.long-hold.md"),
        ),
        patch("sab.sell.maybe_upload_report_artifact", return_value=None),
    ):
        code = run_sell(provider=None)

    assert code == 0
    assert captured_target_bars
    estimated_sessions = int((dt.date.today() - dt.date(2020, 1, 2)).days * (5 / 7))
    expected_target_bars = min(estimated_sessions + 30, 4000) + 1
    assert captured_target_bars[0] == expected_target_bars


def test_run_scan_returns_1_when_supabase_index_upsert_fails(tmp_path: Path) -> None:
    watchlist_file = _write_watchlist(tmp_path / "watchlist.txt", ["005930"])
    cfg = replace(
        Config(),
        data_provider="kis",
        kis_app_key="key",
        kis_app_secret="secret",
        kis_base_url="https://example.com",
        data_dir=str(tmp_path),
        report_dir=str(tmp_path),
        watchlist_path=str(watchlist_file),
        screener_enabled=False,
        screener_only=False,
    )

    report_path = tmp_path / "2026-02-19.buy.json"

    def _write_scan_report(**kwargs: Any) -> str:
        return _write_json_artifact(
            report_path,
            {
                "issues": list(kwargs.get("failures") or []),
                "system_issues": list(kwargs.get("system_issues") or []),
            },
        )

    with (
        patch("sab.scan.load_config", return_value=cfg),
        patch("sab.scan.load_watchlist", return_value=["005930"]),
        patch("sab.market_data_common.KISClient", _FakeKISClient),
        patch("sab.scan.write_report", side_effect=_write_scan_report),
        patch(
            "sab.scan.maybe_upload_report_artifact",
            side_effect=SupabaseReportIndexError(
                "index down",
                storage_key="2026/02/2026-02-19.buy.json",
            ),
        ),
    ):
        code = run_scan(
            limit=None,
            watchlist_path=None,
            provider=None,
            screener_limit=None,
            universe="watchlist",
        )

    assert code == 1
    report = json.loads(report_path.read_text(encoding="utf-8"))
    assert any(
        "Supabase upload failed: index down" in issue
        for issue in report["system_issues"]
    )


def test_run_sell_returns_1_when_supabase_index_upsert_fails(tmp_path: Path) -> None:
    cfg = replace(
        Config(),
        data_provider="kis",
        kis_app_key="key",
        kis_app_secret="secret",
        kis_base_url="https://example.com",
        data_dir=str(tmp_path),
        report_dir=str(tmp_path),
        holdings=_build_holdings(["005930"]),
    )

    report_path = tmp_path / "2026-02-19.sell.json"

    def _write_sell_report(**kwargs: Any) -> str:
        return _write_json_artifact(
            report_path,
            {"issues": list(kwargs.get("failures") or [])},
        )

    with (
        patch("sab.sell.load_config", return_value=cfg),
        patch("sab.market_data_common.KISClient", _FakeKISClient),
        patch("sab.sell.resolve_fx_rate", return_value=(None, None, [])),
        patch("sab.sell.write_sell_report", side_effect=_write_sell_report),
        patch(
            "sab.sell.maybe_upload_report_artifact",
            side_effect=SupabaseReportIndexError(
                "index down",
                storage_key="2026/02/2026-02-19.sell.json",
            ),
        ),
    ):
        code = run_sell(provider=None)

    assert code == 1
    report = json.loads(report_path.read_text(encoding="utf-8"))
    assert any(
        "Supabase upload failed: index down" in issue for issue in report["issues"]
    )


def test_run_scan_returns_1_when_unexpected_ticker_evaluation_error_occurs(
    tmp_path: Path,
) -> None:
    watchlist_file = _write_watchlist(
        tmp_path / "watchlist.txt",
        ["AAPL.US", "MSFT.US"],
    )
    cfg = replace(
        Config(),
        data_provider="pykrx",
        data_dir=str(tmp_path),
        report_dir=str(tmp_path),
        watchlist_path=str(watchlist_file),
        screener_enabled=False,
        screener_only=False,
        universe_markets=["US"],
    )

    def _collect_runtime(
        runtime: Any,
        *,
        screener_enabled: bool,
        screener_only: bool,
        screener_limit: int,
        screener_limit_from_cli: bool,
        evaluation_limit: int | None,
    ) -> None:
        del (
            screener_enabled,
            screener_only,
            screener_limit,
            screener_limit_from_cli,
            evaluation_limit,
        )
        runtime.market_data = {
            "AAPL.US": _build_candles(),
            "MSFT.US": _build_candles(),
        }
        runtime.ticker_currency = {"AAPL.US": "USD", "MSFT.US": "USD"}

    def _evaluate_ticker(
        ticker: str,
        _candles: list[dict[str, float]],
        _settings: Any,
        _meta: dict[str, Any] | None = None,
    ) -> SimpleNamespace:
        if ticker == "AAPL.US":
            raise RuntimeError("evaluation exploded")
        return SimpleNamespace(
            candidate={"ticker": ticker, "score_value": 1.0},
            reason=None,
        )

    with (
        patch("sab.scan.load_config", return_value=cfg),
        patch("sab.scan.load_watchlist", return_value=["AAPL.US", "MSFT.US"]),
        patch("sab.scan._collect_scan_runtime", side_effect=_collect_runtime),
        patch("sab.scan.evaluate_ticker", side_effect=_evaluate_ticker),
        patch(
            "sab.scan.write_report",
            return_value=str(tmp_path / "2026-02-24.buy.md"),
        ),
        patch("sab.scan.maybe_upload_report_artifact", return_value=None),
    ):
        code = run_scan(
            limit=None,
            watchlist_path=None,
            provider=None,
            screener_limit=None,
            universe="watchlist",
        )

    assert code == 1


def test_run_sell_returns_1_when_unexpected_ticker_evaluation_error_occurs(
    tmp_path: Path,
) -> None:
    cfg = replace(
        Config(),
        data_provider="kis",
        kis_app_key="key",
        kis_app_secret="secret",
        kis_base_url="https://example.com",
        data_dir=str(tmp_path),
        report_dir=str(tmp_path),
        holdings=_build_holdings(["AAPL.NAS", "MSFT.NAS"]),
        sell_mode="generic",
    )

    def _evaluate_sell_signals(
        ticker: str,
        candles: list[dict[str, float]],
        _holding: dict[str, Any],
        _settings: Any,
    ) -> SellEvaluation:
        if ticker == "AAPL.NAS":
            raise RuntimeError("sell evaluation exploded")
        return SellEvaluation(
            action="HOLD",
            reasons=["ok"],
            eval_price=float(candles[-1]["close"]),
            eval_date=str(candles[-1]["date"]),
        )

    with (
        patch("sab.sell.load_config", return_value=cfg),
        patch("sab.market_data_common.KISClient", _FakeKISClient),
        patch("sab.sell.resolve_fx_rate", return_value=(None, None, [])),
        patch("sab.sell.evaluate_sell_signals", side_effect=_evaluate_sell_signals),
        patch(
            "sab.sell.write_sell_report",
            return_value=str(tmp_path / "2026-02-24.sell.md"),
        ),
        patch("sab.sell.maybe_upload_report_artifact", return_value=None),
    ):
        code = run_sell(provider=None)

    assert code == 1


def test_run_sell_returns_1_when_all_market_data_missing(tmp_path: Path) -> None:
    cfg = replace(
        Config(),
        data_provider="pykrx",
        data_dir=str(tmp_path),
        report_dir=str(tmp_path),
        holdings=_build_holdings(["005930"]),
    )

    with (
        patch("sab.sell.load_config", return_value=cfg),
        patch("sab.sell._collect_sell_runtime", return_value=None),
        patch("sab.sell._evaluate_sell_runtime", return_value=[]),
        patch(
            "sab.sell.write_sell_report",
            return_value=str(tmp_path / "2026-02-24.sell.missing-data.md"),
        ),
        patch("sab.sell.maybe_upload_report_artifact", return_value=None),
    ):
        code = run_sell(provider=None)

    assert code == 1


def test_run_scan_returns_1_when_partial_market_data_missing(tmp_path: Path) -> None:
    watchlist_file = _write_watchlist(
        tmp_path / "watchlist.txt",
        ["AAPL.US", "MSFT.US"],
    )
    cfg = replace(
        Config(),
        data_provider="pykrx",
        data_dir=str(tmp_path),
        report_dir=str(tmp_path),
        watchlist_path=str(watchlist_file),
        screener_enabled=False,
        screener_only=False,
        universe_markets=["US"],
    )

    def _collect_runtime(
        runtime: Any,
        *,
        screener_enabled: bool,
        screener_only: bool,
        screener_limit: int,
        screener_limit_from_cli: bool,
        evaluation_limit: int | None,
    ) -> None:
        del (
            screener_enabled,
            screener_only,
            screener_limit,
            screener_limit_from_cli,
            evaluation_limit,
        )
        runtime.market_data = {
            "AAPL.US": _build_candles(),
        }
        runtime.ticker_currency = {"AAPL.US": "USD", "MSFT.US": "USD"}

    with (
        patch("sab.scan.load_config", return_value=cfg),
        patch("sab.scan.load_watchlist", return_value=["AAPL.US", "MSFT.US"]),
        patch("sab.scan._collect_scan_runtime", side_effect=_collect_runtime),
        patch(
            "sab.scan.write_report",
            return_value=str(tmp_path / "2026-02-24.buy.partial-missing.md"),
        ),
        patch("sab.scan.maybe_upload_report_artifact", return_value=None),
    ):
        code = run_scan(
            limit=None,
            watchlist_path=None,
            provider=None,
            screener_limit=None,
            universe="watchlist",
        )

    assert code == 1


def test_run_scan_allows_partial_market_data_when_coverage_meets_threshold(
    tmp_path: Path,
) -> None:
    watchlist_file = tmp_path / "watchlist.txt"
    cfg = replace(
        Config(),
        data_provider="pykrx",
        data_dir=str(tmp_path),
        report_dir=str(tmp_path),
        watchlist_path=str(watchlist_file),
        screener_enabled=False,
        screener_only=False,
        universe_markets=["US"],
    )
    tickers = [
        "AAPL.NAS",
        "MSFT.NAS",
        "AMZN.NAS",
        "GOOG.NAS",
        "META.NAS",
        "TSLA.NAS",
        "NVDA.NAS",
        "NFLX.NAS",
        "INTC.NAS",
        "AMD.NAS",
    ]
    watchlist_file.write_text("\n".join(tickers) + "\n", encoding="utf-8")

    def _collect_runtime(
        runtime: Any,
        *,
        screener_enabled: bool,
        screener_only: bool,
        screener_limit: int,
        screener_limit_from_cli: bool,
        evaluation_limit: int | None,
    ) -> None:
        del (
            screener_enabled,
            screener_only,
            screener_limit,
            screener_limit_from_cli,
            evaluation_limit,
        )
        runtime.market_data = {ticker: _build_candles() for ticker in tickers[:7]}
        runtime.ticker_currency = dict.fromkeys(tickers, "USD")

    with (
        patch("sab.scan.load_config", return_value=cfg),
        patch("sab.scan.load_watchlist", return_value=tickers),
        patch("sab.scan._collect_scan_runtime", side_effect=_collect_runtime),
        patch("sab.scan._evaluate_scan_runtime", return_value=None),
        patch(
            "sab.scan.write_report",
            return_value=str(tmp_path / "2026-02-24.buy.coverage-threshold.md"),
        ),
        patch("sab.scan.maybe_upload_report_artifact", return_value=None),
    ):
        code = run_scan(
            limit=None,
            watchlist_path=None,
            provider=None,
            screener_limit=None,
            universe="watchlist",
        )

    assert code == 0


def test_run_sell_returns_1_when_partial_market_data_missing(tmp_path: Path) -> None:
    cfg = replace(
        Config(),
        data_provider="pykrx",
        data_dir=str(tmp_path),
        report_dir=str(tmp_path),
        holdings=_build_holdings(["005930", "000660"]),
    )

    def _collect_runtime(runtime: Any, *, target_bars: int) -> None:
        del target_bars
        runtime.market_data = {"005930": _build_candles()}

    with (
        patch("sab.sell.load_config", return_value=cfg),
        patch("sab.sell._collect_sell_runtime", side_effect=_collect_runtime),
        patch("sab.sell._evaluate_sell_runtime", return_value=[]),
        patch(
            "sab.sell.write_sell_report",
            return_value=str(tmp_path / "2026-02-24.sell.partial-missing.md"),
        ),
        patch("sab.sell.maybe_upload_report_artifact", return_value=None),
    ):
        code = run_sell(provider=None)

    assert code == 1


def test_run_sell_allows_partial_market_data_when_coverage_meets_threshold(
    tmp_path: Path,
) -> None:
    tickers = [
        "AAPL.NAS",
        "MSFT.NAS",
        "AMZN.NAS",
        "GOOG.NAS",
        "META.NAS",
        "TSLA.NAS",
        "NVDA.NAS",
        "NFLX.NAS",
        "INTC.NAS",
        "AMD.NAS",
    ]
    cfg = replace(
        Config(),
        data_provider="pykrx",
        data_dir=str(tmp_path),
        report_dir=str(tmp_path),
        holdings=_build_holdings(tickers),
    )

    def _collect_runtime(runtime: Any, *, target_bars: int) -> None:
        del target_bars
        runtime.market_data = {ticker: _build_candles() for ticker in tickers[:7]}

    with (
        patch("sab.sell.load_config", return_value=cfg),
        patch("sab.sell._collect_sell_runtime", side_effect=_collect_runtime),
        patch("sab.sell._evaluate_sell_runtime", return_value=[]),
        patch(
            "sab.sell.write_sell_report",
            return_value=str(tmp_path / "2026-02-24.sell.coverage-threshold.md"),
        ),
        patch("sab.sell.maybe_upload_report_artifact", return_value=None),
    ):
        code = run_sell(provider=None)

    assert code == 0


def test_run_scan_hybrid_returns_1_when_unexpected_ticker_evaluation_error_occurs(
    tmp_path: Path,
) -> None:
    watchlist_file = _write_watchlist(
        tmp_path / "watchlist.txt",
        ["AAPL.US", "MSFT.US"],
    )
    cfg = replace(
        Config(),
        data_provider="pykrx",
        data_dir=str(tmp_path),
        report_dir=str(tmp_path),
        watchlist_path=str(watchlist_file),
        screener_enabled=False,
        screener_only=False,
        strategy_mode="sma_ema_hybrid",
        universe_markets=["US"],
    )

    def _collect_runtime(
        runtime: Any,
        *,
        screener_enabled: bool,
        screener_only: bool,
        screener_limit: int,
        screener_limit_from_cli: bool,
        evaluation_limit: int | None,
    ) -> None:
        del (
            screener_enabled,
            screener_only,
            screener_limit,
            screener_limit_from_cli,
            evaluation_limit,
        )
        runtime.market_data = {
            "AAPL.US": _build_candles(),
            "MSFT.US": _build_candles(),
        }
        runtime.ticker_currency = {"AAPL.US": "USD", "MSFT.US": "USD"}

    def _evaluate_ticker_hybrid(
        ticker: str,
        _candles: list[dict[str, float]],
        _settings: Any,
        _meta: dict[str, Any] | None = None,
    ) -> SimpleNamespace:
        if ticker == "AAPL.US":
            raise RuntimeError("hybrid evaluation exploded")
        return SimpleNamespace(
            candidate={"ticker": ticker, "score_value": 1.0},
            reason=None,
        )

    with (
        patch("sab.scan.load_config", return_value=cfg),
        patch("sab.scan.load_watchlist", return_value=["AAPL.US", "MSFT.US"]),
        patch("sab.scan._collect_scan_runtime", side_effect=_collect_runtime),
        patch(
            "sab.scan.evaluate_ticker",
            side_effect=AssertionError("generic evaluator should not be used"),
        ),
        patch("sab.scan.evaluate_ticker_hybrid", side_effect=_evaluate_ticker_hybrid),
        patch(
            "sab.scan.write_report",
            return_value=str(tmp_path / "2026-02-24.buy.hybrid.md"),
        ),
        patch("sab.scan.maybe_upload_report_artifact", return_value=None),
    ):
        code = run_scan(
            limit=None,
            watchlist_path=None,
            provider=None,
            screener_limit=None,
            universe="watchlist",
        )

    assert code == 1


def test_run_sell_hybrid_returns_1_when_unexpected_ticker_evaluation_error_occurs(
    tmp_path: Path,
) -> None:
    cfg = replace(
        Config(),
        data_provider="kis",
        kis_app_key="key",
        kis_app_secret="secret",
        kis_base_url="https://example.com",
        data_dir=str(tmp_path),
        report_dir=str(tmp_path),
        holdings=_build_holdings(["AAPL.NAS", "MSFT.NAS"]),
        sell_mode="sma_ema_hybrid",
    )

    def _evaluate_sell_signals_hybrid(
        ticker: str,
        candles: list[dict[str, float]],
        _holding: dict[str, Any],
        _settings: Any,
    ) -> SimpleNamespace:
        if ticker == "AAPL.NAS":
            raise RuntimeError("hybrid sell evaluation exploded")
        return SimpleNamespace(
            action="HOLD",
            reasons=["ok"],
            stop_price=None,
            target_price=None,
            eval_price=float(candles[-1]["close"]),
            eval_date=str(candles[-1]["date"]),
        )

    with (
        patch("sab.sell.load_config", return_value=cfg),
        patch("sab.market_data_common.KISClient", _FakeKISClient),
        patch("sab.sell.resolve_fx_rate", return_value=(None, None, [])),
        patch(
            "sab.sell.evaluate_sell_signals",
            side_effect=AssertionError("generic evaluator should not be used"),
        ),
        patch(
            "sab.sell.evaluate_sell_signals_hybrid",
            side_effect=_evaluate_sell_signals_hybrid,
        ),
        patch(
            "sab.sell.write_sell_report",
            return_value=str(tmp_path / "2026-02-24.sell.hybrid.md"),
        ),
        patch("sab.sell.maybe_upload_report_artifact", return_value=None),
    ):
        code = run_sell(provider=None)

    assert code == 1
