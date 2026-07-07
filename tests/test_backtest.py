from __future__ import annotations

import json
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
from sab.backtest import BacktestRunConfig, run_backtest, run_historical_backtest
from sab.config import Config


def _candles() -> list[dict[str, Any]]:
    return [
        {
            "date": "20260101",
            "open": 100.0,
            "high": 101.0,
            "low": 99.0,
            "close": 100.0,
            "volume": 1_000_000,
        },
        {
            "date": "20260102",
            "open": 101.0,
            "high": 103.0,
            "low": 100.0,
            "close": 102.0,
            "volume": 1_100_000,
        },
        {
            "date": "20260105",
            "open": 103.0,
            "high": 106.0,
            "low": 102.0,
            "close": 105.0,
            "volume": 1_200_000,
        },
        {
            "date": "20260106",
            "open": 106.0,
            "high": 111.0,
            "low": 105.0,
            "close": 110.0,
            "volume": 1_300_000,
        },
    ]


def test_run_historical_backtest_replays_entry_exit_and_metrics() -> None:
    buy_calls: list[str] = []
    sell_calls: list[str] = []

    def fake_buy(
        ticker: str,
        candles: list[dict[str, Any]],
        settings: object,
        meta: dict[str, Any] | None = None,
    ) -> SimpleNamespace:
        del settings, meta
        eval_date = candles[-1]["date"]
        buy_calls.append(f"{ticker}:{eval_date}")
        if eval_date != "20260102":
            return SimpleNamespace(ticker=ticker, candidate=None, reason="no signal")
        return SimpleNamespace(
            ticker=ticker,
            candidate={
                "ticker": ticker,
                "eval_date": eval_date,
                "price_value": 102.0,
                "pattern": "swing_high_breakout",
                "entry_state": "READY",
                "quality_state": "A",
                "reasons": [{"id": "pattern_swing_high_breakout"}],
            },
            reason=None,
        )

    def fake_sell(
        ticker: str,
        candles: list[dict[str, Any]],
        holding: dict[str, Any],
        settings: object,
    ) -> SimpleNamespace:
        del ticker, holding, settings
        eval_date = candles[-1]["date"]
        sell_calls.append(eval_date)
        action = "SELL" if eval_date == "20260106" else "HOLD"
        return SimpleNamespace(
            action=action,
            reasons=["target reached"] if action == "SELL" else ["hold"],
            eval_price=candles[-1]["close"],
            eval_date=eval_date,
            stop_price=99.0,
            target_price=120.0,
            flags=None,
            days_in_trade_sessions=None,
            time_stop_triggered=False,
        )

    result = run_historical_backtest(
        cfg=replace(
            Config(),
            strategy_mode="sma_ema_hybrid",
            sell_mode="sma_ema_hybrid",
            min_history_bars=1,
        ),
        market_data={"AAPL.NAS": _candles()},
        run_config=BacktestRunConfig(
            start_date="2026-01-02",
            end_date="2026-01-06",
            transaction_cost_bps=0.0,
            slippage_bps=0.0,
        ),
        evaluate_ticker_hybrid_fn=fake_buy,
        evaluate_sell_signals_hybrid_fn=fake_sell,
    )

    trades = result["trades"]
    assert len(trades) == 1
    assert trades[0]["ticker"] == "AAPL.NAS"
    assert trades[0]["entry_signal_date"] == "2026-01-02"
    assert trades[0]["entry_date"] == "2026-01-05"
    assert trades[0]["entry_price"] == 103.0
    assert trades[0]["exit_date"] == "2026-01-06"
    assert trades[0]["exit_price"] == 110.0
    assert trades[0]["exit_action"] == "SELL"
    assert trades[0]["return_pct"] == pytest.approx((110.0 - 103.0) / 103.0)
    assert trades[0]["holding_period_bars"] == 1
    assert result["summary"]["closed_trade_count"] == 1
    assert result["summary"]["win_rate"] == pytest.approx(1.0)
    assert result["summary"]["total_return_pct"] == pytest.approx(
        (110.0 - 103.0) / 103.0
    )
    assert result["summary"]["max_drawdown_pct"] == pytest.approx(
        (102.0 - 103.0) / 103.0
    )
    assert result["config_snapshot"]["backtest"]["entry_execution"] == "next_open"
    assert any(call.endswith(":20260102") for call in buy_calls)
    assert "20260106" in sell_calls


def test_run_backtest_writes_json_report_from_local_ohlcv(tmp_path: Path) -> None:
    data_file = tmp_path / "history.json"
    data_file.write_text(json.dumps({"AAPL.NAS": _candles()}), encoding="utf-8")
    report_dir = tmp_path / "reports"

    def fake_buy(
        ticker: str,
        candles: list[dict[str, Any]],
        settings: object,
        meta: dict[str, Any] | None = None,
    ) -> SimpleNamespace:
        del settings, meta
        if candles[-1]["date"] != "20260102":
            return SimpleNamespace(ticker=ticker, candidate=None, reason="no signal")
        return SimpleNamespace(
            ticker=ticker,
            candidate={
                "ticker": ticker,
                "eval_date": candles[-1]["date"],
                "price_value": 102.0,
                "entry_state": "READY",
                "quality_state": "A",
            },
            reason=None,
        )

    def fake_sell(
        ticker: str,
        candles: list[dict[str, Any]],
        holding: dict[str, Any],
        settings: object,
    ) -> SimpleNamespace:
        del ticker, holding, settings
        return SimpleNamespace(
            action="SELL" if candles[-1]["date"] == "20260106" else "HOLD",
            reasons=["target reached"],
            eval_price=candles[-1]["close"],
            eval_date=candles[-1]["date"],
        )

    exit_code = run_backtest(
        data_file_path=data_file.as_posix(),
        tickers="AAPL.NAS",
        start_date="2026-01-02",
        end_date="2026-01-06",
        strategy_mode="sma_ema_hybrid",
        sell_mode="sma_ema_hybrid",
        report_dir=report_dir.as_posix(),
        transaction_cost_bps=0.0,
        slippage_bps=0.0,
        evaluate_ticker_hybrid_fn=fake_buy,
        evaluate_sell_signals_hybrid_fn=fake_sell,
    )

    assert exit_code == 0
    report_path = report_dir / "2026-01-06.backtest.json"
    payload = json.loads(report_path.read_text(encoding="utf-8"))
    assert payload["schema"] == "sab.report.v1"
    assert payload["type"] == "backtest"
    assert payload["period"] == {"start_date": "2026-01-02", "end_date": "2026-01-06"}
    assert payload["symbols"] == ["AAPL.NAS"]
    assert payload["summary"]["closed_trade_count"] == 1
    assert payload["trades"][0]["exit_action"] == "SELL"


def test_run_historical_backtest_keeps_remainder_after_partial_exit() -> None:
    candles = [
        {"date": "20260101", "open": 99.0, "high": 101.0, "low": 98.0, "close": 100.0},
        {"date": "20260102", "open": 100.0, "high": 103.0, "low": 99.0, "close": 102.0},
        {"date": "20260105", "open": 100.0, "high": 101.0, "low": 99.0, "close": 100.0},
        {
            "date": "20260106",
            "open": 110.0,
            "high": 111.0,
            "low": 109.0,
            "close": 110.0,
        },
        {
            "date": "20260107",
            "open": 120.0,
            "high": 121.0,
            "low": 119.0,
            "close": 120.0,
        },
    ]

    def fake_buy(
        ticker: str,
        candles: list[dict[str, Any]],
        settings: object,
        meta: dict[str, Any] | None = None,
    ) -> SimpleNamespace:
        del settings, meta
        if candles[-1]["date"] != "20260102":
            return SimpleNamespace(ticker=ticker, candidate=None)
        return SimpleNamespace(
            ticker=ticker,
            candidate={"ticker": ticker, "eval_date": "20260102", "price_value": 102.0},
        )

    def fake_sell(
        ticker: str,
        candles: list[dict[str, Any]],
        holding: dict[str, Any],
        settings: object,
    ) -> SimpleNamespace:
        del ticker, holding, settings
        return SimpleNamespace(
            action="SELL_PARTIAL" if candles[-1]["date"] == "20260106" else "HOLD",
            reasons=["partial target reached"],
            eval_price=candles[-1]["close"],
            eval_date=candles[-1]["date"],
        )

    result = run_historical_backtest(
        cfg=replace(Config(), min_history_bars=1),
        market_data={"AAPL.NAS": candles},
        run_config=BacktestRunConfig(
            start_date="2026-01-02",
            end_date="2026-01-07",
            partial_exit_fraction=0.5,
            intraday_exit_policy="none",
        ),
        evaluate_ticker_fn=fake_buy,
        evaluate_sell_signals_fn=fake_sell,
    )

    trades = result["trades"]
    assert [trade["exit_action"] for trade in trades] == [
        "SELL_PARTIAL",
        "END_OF_BACKTEST",
    ]
    assert trades[0]["status"] == "partial_closed"
    assert trades[0]["quantity_fraction"] == pytest.approx(0.5)
    assert trades[0]["remaining_fraction_after_exit"] == pytest.approx(0.5)
    assert trades[1]["quantity_fraction"] == pytest.approx(0.5)
    assert result["summary"]["total_return_pct"] == pytest.approx(0.15)


def test_run_historical_backtest_uses_conservative_intraday_stop_target_path() -> None:
    candles = [
        {"date": "20260101", "open": 99.0, "high": 101.0, "low": 98.0, "close": 100.0},
        {"date": "20260102", "open": 100.0, "high": 103.0, "low": 99.0, "close": 102.0},
        {"date": "20260105", "open": 100.0, "high": 101.0, "low": 99.0, "close": 100.0},
        {"date": "20260106", "open": 100.0, "high": 110.0, "low": 90.0, "close": 104.0},
    ]

    def fake_buy(
        ticker: str,
        candles: list[dict[str, Any]],
        settings: object,
        meta: dict[str, Any] | None = None,
    ) -> SimpleNamespace:
        del settings, meta
        if candles[-1]["date"] != "20260102":
            return SimpleNamespace(ticker=ticker, candidate=None)
        return SimpleNamespace(
            ticker=ticker,
            candidate={"ticker": ticker, "eval_date": "20260102", "price_value": 102.0},
        )

    def fake_sell(
        ticker: str,
        candles: list[dict[str, Any]],
        holding: dict[str, Any],
        settings: object,
    ) -> SimpleNamespace:
        del ticker, holding, settings
        return SimpleNamespace(
            action="HOLD",
            reasons=["hold"],
            eval_price=candles[-1]["close"],
            eval_date=candles[-1]["date"],
            stop_price=95.0,
            target_price=108.0,
        )

    result = run_historical_backtest(
        cfg=replace(Config(), min_history_bars=1),
        market_data={"AAPL.NAS": candles},
        run_config=BacktestRunConfig(
            start_date="2026-01-02",
            end_date="2026-01-06",
            intraday_exit_policy="conservative",
        ),
        evaluate_ticker_fn=fake_buy,
        evaluate_sell_signals_fn=fake_sell,
    )

    trade = result["trades"][0]
    assert trade["exit_action"] == "STOP_INTRADAY"
    assert trade["exit_price"] == pytest.approx(95.0)
    assert trade["exit_reasons"] == [
        "Intraday stop/target policy conservative chose stop before target"
    ]


def test_run_backtest_records_assumptions_and_position_sizing(
    tmp_path: Path,
) -> None:
    data_file = tmp_path / "history.json"
    data_file.write_text(json.dumps({"AAPL.NAS": _candles()}), encoding="utf-8")
    assumptions_file = tmp_path / "assumptions.json"
    assumptions_file.write_text(
        json.dumps(
            {
                "data_source": {"vendor": "fixture"},
                "universe": {"snapshot": "point-in-time-test"},
                "benchmark": {"ticker": "SPY.NAS"},
                "survivorship": {"policy": "point_in_time_membership"},
            }
        ),
        encoding="utf-8",
    )
    report_dir = tmp_path / "reports"

    def fake_buy(
        ticker: str,
        candles: list[dict[str, Any]],
        settings: object,
        meta: dict[str, Any] | None = None,
    ) -> SimpleNamespace:
        del settings, meta
        if candles[-1]["date"] != "20260102":
            return SimpleNamespace(ticker=ticker, candidate=None, reason="no signal")
        return SimpleNamespace(
            ticker=ticker,
            candidate={"ticker": ticker, "eval_date": "20260102", "price_value": 102.0},
            reason=None,
        )

    def fake_sell(
        ticker: str,
        candles: list[dict[str, Any]],
        holding: dict[str, Any],
        settings: object,
    ) -> SimpleNamespace:
        del ticker, holding, settings
        return SimpleNamespace(
            action="SELL" if candles[-1]["date"] == "20260106" else "HOLD",
            reasons=["target reached"],
            eval_price=candles[-1]["close"],
            eval_date=candles[-1]["date"],
        )

    exit_code = run_backtest(
        data_file_path=data_file.as_posix(),
        tickers="AAPL.NAS",
        start_date="2026-01-02",
        end_date="2026-01-06",
        strategy_mode="ema_cross",
        report_dir=report_dir.as_posix(),
        position_size_pct=0.25,
        assumptions_file_path=assumptions_file.as_posix(),
        intraday_exit_policy="none",
        evaluate_ticker_fn=fake_buy,
        evaluate_sell_signals_fn=fake_sell,
    )

    assert exit_code == 0
    payload = json.loads(
        (report_dir / "2026-01-06.backtest.json").read_text(encoding="utf-8")
    )
    assert payload["assumptions"]["survivorship"]["policy"] == (
        "point_in_time_membership"
    )
    assert payload["assumptions"]["survivorship"]["status"] == "provided"
    assert payload["assumptions"]["benchmark"]["ticker"] == "SPY.NAS"
    assert payload["config_snapshot"]["backtest"]["position_size_pct"] == 0.25
    assert payload["trades"][0]["quantity_fraction"] == pytest.approx(0.25)
    expected_return = (110.0 - 103.0) / 103.0 * 0.25
    assert payload["summary"]["total_return_pct"] == pytest.approx(expected_return)


def test_run_historical_backtest_uses_previous_completed_stop_for_intraday_exit() -> (
    None
):
    candles = [
        {"date": "20260102", "open": 100.0, "high": 103.0, "low": 99.0, "close": 102.0},
        {"date": "20260105", "open": 100.0, "high": 102.0, "low": 99.0, "close": 101.0},
        {
            "date": "20260106",
            "open": 106.0,
            "high": 110.0,
            "low": 104.0,
            "close": 108.0,
        },
    ]

    def fake_buy(
        ticker: str,
        candles: list[dict[str, Any]],
        settings: object,
        meta: dict[str, Any] | None = None,
    ) -> SimpleNamespace:
        del settings, meta
        return SimpleNamespace(
            ticker=ticker,
            candidate=(
                {"ticker": ticker, "eval_date": "20260102", "price_value": 102.0}
                if candles[-1]["date"] == "20260102"
                else None
            ),
        )

    def fake_sell(
        ticker: str,
        candles: list[dict[str, Any]],
        holding: dict[str, Any],
        settings: object,
    ) -> SimpleNamespace:
        del ticker, holding, settings
        stop_price = 105.0 if candles[-1]["date"] == "20260106" else 90.0
        return SimpleNamespace(
            action="HOLD",
            reasons=["hold"],
            eval_price=candles[-1]["close"],
            eval_date=candles[-1]["date"],
            stop_price=stop_price,
            target_price=None,
        )

    result = run_historical_backtest(
        cfg=replace(Config(), min_history_bars=1),
        market_data={"AAPL.NAS": candles},
        run_config=BacktestRunConfig(
            start_date="2026-01-02",
            end_date="2026-01-06",
            intraday_exit_policy="conservative",
        ),
        evaluate_ticker_fn=fake_buy,
        evaluate_sell_signals_fn=fake_sell,
    )

    assert result["trades"][0]["exit_action"] == "END_OF_BACKTEST"
    assert result["trades"][0]["exit_price"] == pytest.approx(108.0)


def test_run_historical_backtest_orders_equity_curve_by_exit_date() -> None:
    rows = [
        {
            "date": "20260102",
            "open": 100.0,
            "high": 101.0,
            "low": 100.0,
            "close": 100.0,
        },
        {
            "date": "20260105",
            "open": 100.0,
            "high": 101.0,
            "low": 100.0,
            "close": 100.0,
        },
        {
            "date": "20260106",
            "open": 150.0,
            "high": 151.0,
            "low": 100.0,
            "close": 150.0,
        },
        {"date": "20260110", "open": 50.0, "high": 101.0, "low": 50.0, "close": 50.0},
    ]

    def fake_buy(
        ticker: str,
        candles: list[dict[str, Any]],
        settings: object,
        meta: dict[str, Any] | None = None,
    ) -> SimpleNamespace:
        del settings, meta
        return SimpleNamespace(
            ticker=ticker,
            candidate=(
                {"ticker": ticker, "eval_date": "20260102", "price_value": 100.0}
                if candles[-1]["date"] == "20260102"
                else None
            ),
        )

    def fake_sell(
        ticker: str,
        candles: list[dict[str, Any]],
        holding: dict[str, Any],
        settings: object,
    ) -> SimpleNamespace:
        del holding, settings
        eval_date = candles[-1]["date"]
        action = (
            "SELL"
            if (
                (ticker == "MSFT.NAS" and eval_date == "20260106")
                or (ticker == "AAPL.NAS" and eval_date == "20260110")
            )
            else "HOLD"
        )
        return SimpleNamespace(
            action=action,
            reasons=["exit"] if action == "SELL" else ["hold"],
            eval_price=candles[-1]["close"],
            eval_date=eval_date,
        )

    result = run_historical_backtest(
        cfg=replace(Config(), min_history_bars=1),
        market_data={"AAPL.NAS": rows, "MSFT.NAS": rows},
        run_config=BacktestRunConfig(
            start_date="2026-01-02",
            end_date="2026-01-10",
            intraday_exit_policy="none",
        ),
        evaluate_ticker_fn=fake_buy,
        evaluate_sell_signals_fn=fake_sell,
    )

    dated_points = [
        point for point in result["equity_curve"] if point["date"] is not None
    ]
    assert [point["date"] for point in dated_points] == sorted(
        point["date"] for point in dated_points
    )
    assert result["summary"]["max_drawdown_pct"] == pytest.approx(-1.0 / 3.0)


def test_run_historical_backtest_marks_open_positions_for_drawdown() -> None:
    candles = [
        {"date": "20260102", "open": 100.0, "high": 101.0, "low": 99.0, "close": 100.0},
        {"date": "20260105", "open": 100.0, "high": 101.0, "low": 99.0, "close": 100.0},
        {"date": "20260106", "open": 100.0, "high": 101.0, "low": 50.0, "close": 100.0},
    ]

    def fake_buy(
        ticker: str,
        candles: list[dict[str, Any]],
        settings: object,
        meta: dict[str, Any] | None = None,
    ) -> SimpleNamespace:
        del settings, meta
        return SimpleNamespace(
            ticker=ticker,
            candidate=(
                {"ticker": ticker, "eval_date": "20260102", "price_value": 100.0}
                if candles[-1]["date"] == "20260102"
                else None
            ),
        )

    def fake_sell(
        ticker: str,
        candles: list[dict[str, Any]],
        holding: dict[str, Any],
        settings: object,
    ) -> SimpleNamespace:
        del ticker, holding, settings
        return SimpleNamespace(
            action="HOLD",
            reasons=["hold"],
            eval_price=candles[-1]["close"],
            eval_date=candles[-1]["date"],
        )

    result = run_historical_backtest(
        cfg=replace(Config(), min_history_bars=1),
        market_data={"AAPL.NAS": candles},
        run_config=BacktestRunConfig(
            start_date="2026-01-02",
            end_date="2026-01-06",
            intraday_exit_policy="none",
        ),
        evaluate_ticker_fn=fake_buy,
        evaluate_sell_signals_fn=fake_sell,
    )

    assert result["summary"]["max_drawdown_pct"] == pytest.approx(-0.5)


def test_run_historical_backtest_rejects_invalid_or_inverted_dates() -> None:
    with pytest.raises(ValueError, match="start_date"):
        run_historical_backtest(
            cfg=replace(Config(), min_history_bars=1),
            market_data={"AAPL.NAS": _candles()},
            run_config=BacktestRunConfig(start_date="2026-99-99"),
        )

    with pytest.raises(ValueError, match="start_date must be on or before end_date"):
        run_historical_backtest(
            cfg=replace(Config(), min_history_bars=1),
            market_data={"AAPL.NAS": _candles()},
            run_config=BacktestRunConfig(
                start_date="2026-02-01",
                end_date="2026-01-01",
            ),
        )


def test_run_historical_backtest_waits_for_next_valid_open_after_signal() -> None:
    candles = [
        {"date": "20260102", "open": 100.0, "high": 101.0, "low": 99.0, "close": 100.0},
        {"date": "20260105", "open": 0.0, "high": 101.0, "low": 99.0, "close": 100.0},
        {
            "date": "20260106",
            "open": 105.0,
            "high": 106.0,
            "low": 104.0,
            "close": 105.0,
        },
    ]

    def fake_buy(
        ticker: str,
        candles: list[dict[str, Any]],
        settings: object,
        meta: dict[str, Any] | None = None,
    ) -> SimpleNamespace:
        del settings, meta
        return SimpleNamespace(
            ticker=ticker,
            candidate=(
                {"ticker": ticker, "eval_date": "20260102", "price_value": 100.0}
                if candles[-1]["date"] == "20260102"
                else None
            ),
        )

    result = run_historical_backtest(
        cfg=replace(Config(), min_history_bars=1),
        market_data={"AAPL.NAS": candles},
        run_config=BacktestRunConfig(
            start_date="2026-01-02",
            end_date="2026-01-06",
            intraday_exit_policy="none",
        ),
        evaluate_ticker_fn=fake_buy,
    )

    assert result["trades"][0]["entry_date"] == "2026-01-06"
    assert result["trades"][0]["entry_price"] == pytest.approx(105.0)
    assert any("invalid entry open" in issue for issue in result["issues"])


def test_run_historical_backtest_reports_invalid_ohlcv_rows() -> None:
    result = run_historical_backtest(
        cfg=replace(Config(), min_history_bars=1),
        market_data={
            "AAPL.NAS": [
                {
                    "date": "20260102",
                    "open": 100.0,
                    "high": 101.0,
                    "low": 99.0,
                    "close": 100.0,
                },
                {
                    "date": "bad",
                    "open": 100.0,
                    "high": 101.0,
                    "low": 99.0,
                    "close": 100.0,
                },
                {
                    "date": "20260103",
                    "open": 100.0,
                    "high": 99.0,
                    "low": 101.0,
                    "close": 100.0,
                },
                {
                    "date": "20260102",
                    "open": 100.0,
                    "high": 101.0,
                    "low": 99.0,
                    "close": 100.0,
                },
            ]
        },
    )

    assert result["symbols"] == ["AAPL.NAS"]
    assert any("invalid date" in issue for issue in result["issues"])
    assert any("invalid OHLC range" in issue for issue in result["issues"])
    assert any("duplicate date" in issue for issue in result["issues"])


def test_run_historical_backtest_fills_gap_through_stop_at_open() -> None:
    candles = [
        {"date": "20260102", "open": 100.0, "high": 101.0, "low": 99.0, "close": 100.0},
        {"date": "20260105", "open": 100.0, "high": 101.0, "low": 99.0, "close": 100.0},
        {"date": "20260106", "open": 90.0, "high": 92.0, "low": 89.0, "close": 91.0},
    ]

    def fake_buy(
        ticker: str,
        candles: list[dict[str, Any]],
        settings: object,
        meta: dict[str, Any] | None = None,
    ) -> SimpleNamespace:
        del settings, meta
        return SimpleNamespace(
            ticker=ticker,
            candidate=(
                {"ticker": ticker, "eval_date": "20260102", "price_value": 100.0}
                if candles[-1]["date"] == "20260102"
                else None
            ),
        )

    def fake_sell(
        ticker: str,
        candles: list[dict[str, Any]],
        holding: dict[str, Any],
        settings: object,
    ) -> SimpleNamespace:
        del ticker, holding, settings
        return SimpleNamespace(
            action="HOLD",
            reasons=["hold"],
            eval_price=candles[-1]["close"],
            eval_date=candles[-1]["date"],
            stop_price=95.0,
            target_price=None,
        )

    result = run_historical_backtest(
        cfg=replace(Config(), min_history_bars=1),
        market_data={"AAPL.NAS": candles},
        run_config=BacktestRunConfig(
            start_date="2026-01-02",
            end_date="2026-01-06",
            intraday_exit_policy="conservative",
        ),
        evaluate_ticker_fn=fake_buy,
        evaluate_sell_signals_fn=fake_sell,
    )

    trade = result["trades"][0]
    assert trade["exit_action"] == "STOP_INTRADAY"
    assert trade["exit_price"] == pytest.approx(90.0)
    assert trade["exit_reasons"] == ["Intraday stop gap-through filled at open"]


def test_run_historical_backtest_rejects_fraction_out_of_range() -> None:
    with pytest.raises(ValueError, match="position_size_pct"):
        run_historical_backtest(
            cfg=replace(Config(), min_history_bars=1),
            market_data={"AAPL.NAS": _candles()},
            run_config=BacktestRunConfig(position_size_pct=25.0),
        )

    with pytest.raises(ValueError, match="partial_exit_fraction"):
        run_historical_backtest(
            cfg=replace(Config(), min_history_bars=1),
            market_data={"AAPL.NAS": _candles()},
            run_config=BacktestRunConfig(partial_exit_fraction=2.0),
        )


def test_run_historical_backtest_discloses_return_model_and_exposure() -> None:
    def fake_buy(
        ticker: str,
        candles: list[dict[str, Any]],
        settings: object,
        meta: dict[str, Any] | None = None,
    ) -> SimpleNamespace:
        del settings, meta
        return SimpleNamespace(
            ticker=ticker,
            candidate=(
                {"ticker": ticker, "eval_date": "20260102", "price_value": 102.0}
                if candles[-1]["date"] == "20260102"
                else None
            ),
        )

    def fake_sell(
        ticker: str,
        candles: list[dict[str, Any]],
        holding: dict[str, Any],
        settings: object,
    ) -> SimpleNamespace:
        del ticker, holding, settings
        return SimpleNamespace(
            action="HOLD",
            reasons=["hold"],
            eval_price=candles[-1]["close"],
            eval_date=candles[-1]["date"],
        )

    result = run_historical_backtest(
        cfg=replace(Config(), min_history_bars=1),
        market_data={"AAPL.NAS": _candles(), "MSFT.NAS": _candles()},
        run_config=BacktestRunConfig(position_size_pct=0.75),
        evaluate_ticker_fn=fake_buy,
        evaluate_sell_signals_fn=fake_sell,
    )

    assert result["summary"]["return_model"] == (
        "non_compounded_initial_equity_contribution"
    )
    assert result["summary"]["max_gross_exposure_pct"] == pytest.approx(1.5)
