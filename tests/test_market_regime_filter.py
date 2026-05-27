from __future__ import annotations

import datetime as dt
import logging
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace
from typing import Any, cast

import pytest
import sab.config as sab_config
from sab.config import Config, load_config
from sab.scan_evaluation import (
    MarketRegimeContext,
    _evaluate_candidates,
    _resolve_market_regime_context,
    _write_scan_report,
)
from sab.scan_types import _ScanRuntime

_CLEAR_ENV_KEYS = {name for name, _ in sab_config._ENV_YAML_CONFLICT_BINDINGS} | {
    "KIS_APP_KEY",
    "KIS_APP_SECRET",
    "SAB_CONFIG",
    "SAB_CONFIG_STRICT",
}


def _reset_config_env(monkeypatch: pytest.MonkeyPatch) -> None:
    for key in _CLEAR_ENV_KEYS:
        monkeypatch.delenv(key, raising=False)


def _candles(
    count: int,
    *,
    start_date: int = 1,
    close_start: float = 100.0,
    close_step: float = 1.0,
) -> list[dict[str, float | str]]:
    rows: list[dict[str, float | str]] = []
    base_date = dt.date(2024, 1, start_date)
    for index in range(count):
        close = close_start + (index * close_step)
        session_date = base_date + dt.timedelta(days=index)
        rows.append(
            {
                "date": session_date.strftime("%Y%m%d"),
                "open": close - 0.5,
                "high": close + 1.0,
                "low": close - 1.0,
                "close": close,
                "volume": 1_000_000.0,
            }
        )
    return rows


def _build_runtime(
    *,
    tickers: list[str],
    cfg: Config | None = None,
) -> _ScanRuntime:
    resolved_cfg = cfg or replace(
        Config(),
        data_provider="kis",
        strategy_mode="ema_cross",
        use_market_regime_filter=True,
        rs_lookback_days=0,
        rs_benchmark_ticker_kr="069500",
        rs_benchmark_ticker_us="SPY.AMS",
    )
    runtime = _ScanRuntime(
        cfg=resolved_cfg,
        logger=logging.getLogger("tests.market_regime_filter"),
        tickers=tickers,
    )
    runtime.market_data = {ticker: _candles(3) for ticker in tickers}
    runtime.ticker_currency = {
        ticker: ("USD" if "." in ticker else "KRW") for ticker in tickers
    }
    runtime.ticker_data_source = dict.fromkeys(tickers, resolved_cfg.data_provider)
    runtime.latest_dates = dict.fromkeys(tickers, "20240103")
    return runtime


def test_load_config_parses_market_regime_filter(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(tmp_path)
    config_path = tmp_path / "config.yaml"
    config_path.write_text(
        """
strategy:
  use_market_regime_filter: true
""".strip()
        + "\n",
        encoding="utf-8",
    )

    _reset_config_env(monkeypatch)
    monkeypatch.setattr(
        sab_config, "load_dotenv_if_available", lambda override=False: None
    )
    monkeypatch.setenv("SAB_CONFIG", str(config_path))

    cfg = load_config()

    assert cfg.use_market_regime_filter is True


def test_resolve_market_regime_context_marks_bullish_market() -> None:
    runtime = _build_runtime(tickers=["AAPL.NAS"])
    benchmark_rows = _candles(205, close_start=100.0, close_step=1.0)
    runtime.latest_dates = {"AAPL.NAS": str(benchmark_rows[-1]["date"])}

    class _FakeKISClient:
        def overseas_daily_candles(
            self,
            *,
            symbol: str,
            exchange: str,
            count: int,
            adjusted: bool,
        ) -> list[dict[str, Any]]:
            assert symbol == "SPY"
            assert exchange == "AMS"
            assert adjusted is True
            assert count >= 200
            return benchmark_rows

    runtime.kis_client = cast(Any, _FakeKISClient())

    contexts = _resolve_market_regime_context(runtime)

    assert contexts["US"].benchmark_ticker == "SPY.AMS"
    assert contexts["US"].is_bullish is True
    assert contexts["US"].benchmark_close > contexts["US"].benchmark_sma200
    assert runtime.system_issues == []


def test_evaluate_candidates_skips_ticker_when_market_regime_blocked(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    runtime = _build_runtime(tickers=["AAPL.NAS"])
    monkeypatch.setattr(
        "sab.scan_evaluation._resolve_market_regime_context",
        lambda runtime_obj: {
            "US": MarketRegimeContext(
                benchmark_ticker="SPY.AMS",
                benchmark_close=400.0,
                benchmark_sma200=410.0,
                is_bullish=False,
            )
        },
    )

    _evaluate_candidates(
        runtime,
        EvaluationSettingsCls=lambda **kwargs: SimpleNamespace(**kwargs),
        HybridEvaluationSettingsCls=lambda **kwargs: SimpleNamespace(**kwargs),
        evaluate_ticker_fn=lambda *_args, **_kwargs: pytest.fail(
            "ticker evaluator must not run when market regime is blocked"
        ),
        evaluate_ticker_hybrid_fn=lambda *_args, **_kwargs: pytest.fail(
            "hybrid evaluator must not run when market regime is blocked"
        ),
        split_overseas_fn=lambda ticker: (
            ticker.split(".")[0],
            ticker.split(".")[1] if "." in ticker else None,
        ),
        excd_from_suffix_fn=lambda suffix: suffix,
        enrich_entry_reference_prices=False,
    )

    assert runtime.candidates == []
    assert runtime.screen_outs == [
        "AAPL.NAS: Market regime filter blocked (benchmark SPY.AMS close 400.00 <= SMA200 410.00)"
    ]


def test_evaluate_candidates_keeps_other_market_when_one_market_blocked(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    runtime = _build_runtime(tickers=["005930", "AAPL.NAS"])
    monkeypatch.setattr(
        "sab.scan_evaluation._resolve_market_regime_context",
        lambda runtime_obj: {
            "KR": MarketRegimeContext(
                benchmark_ticker="069500",
                benchmark_close=300.0,
                benchmark_sma200=310.0,
                is_bullish=False,
            ),
            "US": MarketRegimeContext(
                benchmark_ticker="SPY.AMS",
                benchmark_close=400.0,
                benchmark_sma200=390.0,
                is_bullish=True,
            ),
        },
    )
    evaluated: list[str] = []

    def _evaluate(
        ticker: str,
        _candles: list[dict[str, float]],
        _settings: Any,
        _meta: dict[str, Any] | None = None,
    ) -> SimpleNamespace:
        evaluated.append(ticker)
        return SimpleNamespace(
            candidate={"ticker": ticker, "score_value": 1.0}, reason=None
        )

    _evaluate_candidates(
        runtime,
        EvaluationSettingsCls=lambda **kwargs: SimpleNamespace(**kwargs),
        HybridEvaluationSettingsCls=lambda **kwargs: SimpleNamespace(**kwargs),
        evaluate_ticker_fn=_evaluate,
        evaluate_ticker_hybrid_fn=lambda *_args, **_kwargs: SimpleNamespace(
            candidate=None, reason=None
        ),
        split_overseas_fn=lambda ticker: (
            ticker.split(".")[0],
            ticker.split(".")[1] if "." in ticker else None,
        ),
        excd_from_suffix_fn=lambda suffix: suffix,
        enrich_entry_reference_prices=False,
    )

    assert evaluated == ["AAPL.NAS"]
    assert [candidate["ticker"] for candidate in runtime.candidates] == ["AAPL.NAS"]
    assert runtime.screen_outs == [
        "005930: Market regime filter blocked (benchmark 069500 close 300.00 <= SMA200 310.00)"
    ]


def test_evaluate_candidates_disables_market_regime_filter_when_benchmark_unavailable() -> (
    None
):
    runtime = _build_runtime(tickers=["AAPL.NAS"])
    evaluated: list[str] = []

    class _FakeKISClient:
        def overseas_daily_candles(
            self,
            *,
            symbol: str,
            exchange: str,
            count: int,
            adjusted: bool,
        ) -> list[dict[str, Any]]:
            assert symbol == "SPY"
            assert exchange == "AMS"
            assert adjusted is True
            return []

    runtime.kis_client = cast(Any, _FakeKISClient())

    def _evaluate(
        ticker: str,
        _candles: list[dict[str, float]],
        _settings: Any,
        _meta: dict[str, Any] | None = None,
    ) -> SimpleNamespace:
        evaluated.append(ticker)
        return SimpleNamespace(
            candidate={"ticker": ticker, "score_value": 1.0}, reason=None
        )

    _evaluate_candidates(
        runtime,
        EvaluationSettingsCls=lambda **kwargs: SimpleNamespace(**kwargs),
        HybridEvaluationSettingsCls=lambda **kwargs: SimpleNamespace(**kwargs),
        evaluate_ticker_fn=_evaluate,
        evaluate_ticker_hybrid_fn=lambda *_args, **_kwargs: SimpleNamespace(
            candidate=None, reason=None
        ),
        split_overseas_fn=lambda ticker: (
            ticker.split(".")[0],
            ticker.split(".")[1] if "." in ticker else None,
        ),
        excd_from_suffix_fn=lambda suffix: suffix,
        enrich_entry_reference_prices=False,
    )

    assert evaluated == ["AAPL.NAS"]
    assert runtime.system_issues == [
        "Market regime filter disabled: SPY.AMS: Market regime unavailable (insufficient completed history for SMA200)"
    ]


def test_write_scan_report_includes_market_regime_filter_in_config_snapshot() -> None:
    runtime = _build_runtime(
        tickers=["AAPL.NAS"],
        cfg=replace(Config(), use_market_regime_filter=True, universe_markets=["US"]),
    )
    captured: dict[str, Any] = {}

    def _fake_write_report(**kwargs: Any) -> str:
        captured.update(kwargs)
        return "dummy-report.json"

    _write_scan_report(runtime, write_report_fn=_fake_write_report)

    assert captured["run_meta"]["config_snapshot"]["use_market_regime_filter"] is True
