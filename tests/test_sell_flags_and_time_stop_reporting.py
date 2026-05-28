from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace
from typing import Any

from sab.report.sell_report import SellReportRow, write_sell_report
from sab.sell_evaluation import _evaluate_holdings, _write_sell_report


def _runtime_with_single_holding() -> Any:
    hybrid_sell = SimpleNamespace(
        profit_target_low=0.05,
        profit_target_high=0.1,
        partial_profit_floor=0.03,
        ema_short_period=10,
        ema_mid_period=21,
        sma_trend_period=20,
        rsi_period=14,
        stop_loss_pct_min=0.03,
        stop_loss_pct_max=0.05,
        failed_breakout_drop_pct=0.03,
        min_bars=20,
        time_stop_days=0,
        time_stop_grace_days=0,
        time_stop_profit_floor=0.0,
    )
    cfg = SimpleNamespace(
        report_dir="reports",
        sell_atr_multiplier=1.0,
        sell_time_stop_days=10,
        sell_require_sma200=True,
        sell_ema_short=20,
        sell_ema_long=50,
        sell_rsi_period=14,
        sell_rsi_floor=50.0,
        sell_rsi_floor_alt=30.0,
        sell_min_bars=20,
        sell_mode="generic",
        hybrid_sell=hybrid_sell,
        data_provider="kis",
        data_dir="data",
    )
    holding = SimpleNamespace(
        ticker="AAPL.NASD",
        quantity=1.0,
        entry_price=100.0,
        entry_date="2025-01-10",
        stop_override=None,
        target_override=None,
        strategy=None,
        entry_currency="USD",
        notes=None,
    )
    return SimpleNamespace(
        cfg=cfg,
        holdings=[holding],
        market_data={
            "AAPL.NASD": [
                {
                    "date": "20250113",
                    "open": 100.0,
                    "high": 101.0,
                    "low": 99.0,
                    "close": 100.0,
                    "volume": 1.0,
                }
            ]
        },
        missing_logged=set(),
        failures=[],
        ticker_currency={"AAPL.NASD": "USD"},
        ticker_data_source={},
    )


def test_evaluate_holdings_propagates_flags_and_time_stop_fields() -> None:
    runtime = _runtime_with_single_holding()

    def _evaluate(*_args: object, **_kwargs: object) -> SimpleNamespace:
        return SimpleNamespace(
            action="SELL",
            reasons=["Price hit custom stop override"],
            stop_price=95.0,
            target_price=110.0,
            eval_price=94.0,
            eval_date="20250113",
            flags=["CORPORATE_ACTION_SUSPECT"],
            days_in_trade_sessions=1,
            time_stop_triggered=False,
        )

    rows = _evaluate_holdings(
        runtime,
        SellSettingsCls=SimpleNamespace,
        HybridSellSettingsCls=SimpleNamespace,
        evaluate_sell_signals_fn=_evaluate,
        evaluate_sell_signals_hybrid_fn=_evaluate,
        SellReportRowCls=SellReportRow,
        split_symbol_and_suffix_fn=lambda ticker: (ticker, "NASD"),
        exchange_from_suffix_fn=lambda _suffix: "NAS",
    )

    assert len(rows) == 1
    assert rows[0].flags == ["CORPORATE_ACTION_SUSPECT"]
    assert rows[0].days_in_trade_sessions == 1
    assert rows[0].time_stop_triggered is False


def test_write_sell_report_serializes_flags_and_time_stop_fields(tmp_path) -> None:
    row = SellReportRow(
        ticker="AAPL.NASD",
        name="Apple",
        quantity=1.0,
        entry_price=100.0,
        entry_date="2025-01-10",
        last_price=94.0,
        pnl_pct=-0.06,
        action="SELL",
        reasons=["Price hit custom stop override"],
        stop_price=95.0,
        target_price=110.0,
        flags=["CORPORATE_ACTION_SUSPECT"],
        days_in_trade_sessions=1,
        time_stop_triggered=False,
    )

    out_path = write_sell_report(
        report_dir=tmp_path.as_posix(),
        provider="test",
        evaluated=[row],
    )
    payload = json.loads(Path(out_path).read_text(encoding="utf-8"))
    item = payload["evaluated"][0]

    assert item["flags"] == ["CORPORATE_ACTION_SUSPECT"]
    assert item["days_in_trade_sessions"] == 1
    assert item["time_stop_triggered"] is False


def test_evaluate_holdings_collects_time_stop_market_warning_into_failures() -> None:
    runtime = _runtime_with_single_holding()

    def _evaluate(*_args: object, **_kwargs: object) -> SimpleNamespace:
        return SimpleNamespace(
            action="REVIEW",
            reasons=["Time stop skipped: unable to resolve holding market"],
            stop_price=95.0,
            target_price=110.0,
            eval_price=94.0,
            eval_date="20250113",
            flags=None,
            days_in_trade_sessions=None,
            time_stop_triggered=False,
        )

    rows = _evaluate_holdings(
        runtime,
        SellSettingsCls=SimpleNamespace,
        HybridSellSettingsCls=SimpleNamespace,
        evaluate_sell_signals_fn=_evaluate,
        evaluate_sell_signals_hybrid_fn=_evaluate,
        SellReportRowCls=SellReportRow,
        split_symbol_and_suffix_fn=lambda ticker: (ticker, "NASD"),
        exchange_from_suffix_fn=lambda _suffix: "NAS",
    )

    assert len(rows) == 1
    assert runtime.failures == [
        "AAPL.NASD: Time stop skipped: unable to resolve holding market"
    ]


def test_evaluate_holdings_collects_invalid_candle_data_into_failures() -> None:
    runtime = _runtime_with_single_holding()

    def _evaluate(*_args: object, **_kwargs: object) -> SimpleNamespace:
        return SimpleNamespace(
            action="REVIEW",
            reasons=["Invalid candle data: non-finite OHLC values"],
            stop_price=None,
            target_price=None,
            eval_price=None,
            eval_date=None,
            flags=None,
            days_in_trade_sessions=None,
            time_stop_triggered=False,
        )

    rows = _evaluate_holdings(
        runtime,
        SellSettingsCls=SimpleNamespace,
        HybridSellSettingsCls=SimpleNamespace,
        evaluate_sell_signals_fn=_evaluate,
        evaluate_sell_signals_hybrid_fn=_evaluate,
        SellReportRowCls=SellReportRow,
        split_symbol_and_suffix_fn=lambda ticker: (ticker, "NASD"),
        exchange_from_suffix_fn=lambda _suffix: "NAS",
    )

    assert len(rows) == 1
    assert rows[0].last_price is None
    assert rows[0].pnl_pct is None
    assert rows[0].eval_date is None
    assert runtime.failures == [
        "AAPL.NASD: Invalid candle data: non-finite OHLC values"
    ]


def test_evaluate_holdings_collects_insufficient_history_into_failures() -> None:
    runtime = _runtime_with_single_holding()

    def _evaluate(*_args: object, **_kwargs: object) -> SimpleNamespace:
        return SimpleNamespace(
            action="REVIEW",
            reasons=["Insufficient completed candles for hybrid sell"],
            stop_price=None,
            target_price=None,
            eval_price=None,
            eval_date=None,
            flags=None,
            days_in_trade_sessions=None,
            time_stop_triggered=False,
        )

    rows = _evaluate_holdings(
        runtime,
        SellSettingsCls=SimpleNamespace,
        HybridSellSettingsCls=SimpleNamespace,
        evaluate_sell_signals_fn=_evaluate,
        evaluate_sell_signals_hybrid_fn=_evaluate,
        SellReportRowCls=SellReportRow,
        split_symbol_and_suffix_fn=lambda ticker: (ticker, "NASD"),
        exchange_from_suffix_fn=lambda _suffix: "NAS",
    )

    assert len(rows) == 1
    assert rows[0].last_price == 100.0
    assert rows[0].pnl_pct == 0.0
    assert rows[0].eval_date == "20250113"
    assert runtime.failures == [
        "AAPL.NASD: Insufficient completed candles for hybrid sell"
    ]


def test_write_sell_report_counts_collected_time_stop_market_warning(tmp_path) -> None:
    row = SellReportRow(
        ticker="AAPL.NASD",
        name="Apple",
        quantity=1.0,
        entry_price=100.0,
        entry_date="2025-01-10",
        last_price=94.0,
        pnl_pct=-0.06,
        action="REVIEW",
        reasons=["Time stop skipped: unable to resolve holding market"],
        stop_price=95.0,
        target_price=110.0,
        flags=None,
        days_in_trade_sessions=None,
        time_stop_triggered=False,
    )
    failure = "AAPL.NASD: Time stop skipped: unable to resolve holding market"

    out_path = write_sell_report(
        report_dir=tmp_path.as_posix(),
        provider="test",
        evaluated=[row],
        failures=[failure],
    )
    payload = json.loads(Path(out_path).read_text(encoding="utf-8"))

    assert payload["summary"]["issue_count"] == 1
    assert payload["issues"] == [failure]


def test_write_sell_runtime_report_uses_resolved_session_state(
    monkeypatch,
) -> None:
    runtime = _runtime_with_single_holding()
    runtime.unique_tickers = ["AAPL.NASD"]
    runtime.cache_hint = None
    runtime.fx_rate = None
    runtime.fx_note = None

    rows = [
        SellReportRow(
            ticker="AAPL.NASD",
            name="Apple",
            quantity=1.0,
            entry_price=100.0,
            entry_date="2025-01-10",
            last_price=101.0,
            pnl_pct=0.01,
            action="HOLD",
            reasons=["No sell criteria triggered"],
            stop_price=None,
            target_price=None,
            currency="USD",
            eval_date="20250113",
            flags=None,
            days_in_trade_sessions=1,
            time_stop_triggered=False,
        )
    ]

    monkeypatch.setattr(
        "sab.sell_evaluation.resolve_run_session_state",
        lambda *_args, **_kwargs: "INTRADAY",
        raising=False,
    )

    captured: dict[str, Any] = {}

    def _fake_write_sell_report(**kwargs: Any) -> str:
        captured.update(kwargs)
        return "dummy-sell.json"

    _write_sell_report(runtime, rows, write_sell_report_fn=_fake_write_sell_report)

    assert (
        captured["run_meta"]["eval_context"]["session_state"]  # type: ignore[index]
        == "INTRADAY"
    )


def test_write_sell_runtime_report_emits_session_state_by_market_for_mixed_run(
    monkeypatch,
) -> None:
    runtime = _runtime_with_single_holding()
    runtime.unique_tickers = ["AAPL.NASD", "005930"]
    runtime.ticker_currency = {"AAPL.NASD": "USD", "005930": "KRW"}
    runtime.cache_hint = None
    runtime.fx_rate = None
    runtime.fx_note = None

    rows = [
        SellReportRow(
            ticker="AAPL.NASD",
            name="Apple",
            quantity=1.0,
            entry_price=100.0,
            entry_date="2025-01-10",
            last_price=101.0,
            pnl_pct=0.01,
            action="HOLD",
            reasons=["No sell criteria triggered"],
            stop_price=None,
            target_price=None,
            currency="USD",
            eval_date="20250113",
            flags=None,
            days_in_trade_sessions=1,
            time_stop_triggered=False,
        )
    ]

    monkeypatch.setattr(
        "sab.sell_evaluation.resolve_run_session_state",
        lambda *_args, **_kwargs: "INTRADAY",
        raising=False,
    )
    monkeypatch.setattr(
        "sab.sell_evaluation.resolve_run_session_state_map",
        lambda *_args, **_kwargs: {"KR": "AFTER_CLOSE", "US": "INTRADAY"},
        raising=False,
    )

    captured: dict[str, Any] = {}

    def _fake_write_sell_report(**kwargs: Any) -> str:
        captured.update(kwargs)
        return "dummy-sell.json"

    _write_sell_report(runtime, rows, write_sell_report_fn=_fake_write_sell_report)

    eval_context = captured["run_meta"]["eval_context"]  # type: ignore[index]
    assert eval_context["market"] == "MIXED"
    assert eval_context["session_state_by_market"] == {
        "KR": "AFTER_CLOSE",
        "US": "INTRADAY",
    }
