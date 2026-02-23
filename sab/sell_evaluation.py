from __future__ import annotations

import math
from typing import Any

from .sell_types import _SellRuntime


def _build_sell_settings(cfg: Any, *, SellSettingsCls: Any) -> Any:
    return SellSettingsCls(
        atr_trail_multiplier=cfg.sell_atr_multiplier,
        time_stop_days=cfg.sell_time_stop_days,
        require_sma200=cfg.sell_require_sma200,
        ema_lengths=(cfg.sell_ema_short, cfg.sell_ema_long),
        rsi_period=cfg.sell_rsi_period,
        rsi_floor=cfg.sell_rsi_floor,
        rsi_floor_alt=cfg.sell_rsi_floor_alt,
        min_bars=max(cfg.sell_min_bars, 2),
    )


def _build_hybrid_sell_settings(cfg: Any, *, HybridSellSettingsCls: Any) -> Any:
    return HybridSellSettingsCls(
        profit_target_low=cfg.hybrid_sell.profit_target_low,
        profit_target_high=cfg.hybrid_sell.profit_target_high,
        partial_profit_floor=cfg.hybrid_sell.partial_profit_floor,
        ema_short_period=cfg.hybrid_sell.ema_short_period,
        ema_mid_period=cfg.hybrid_sell.ema_mid_period,
        sma_trend_period=cfg.hybrid_sell.sma_trend_period,
        rsi_period=cfg.hybrid_sell.rsi_period,
        stop_loss_pct_min=cfg.hybrid_sell.stop_loss_pct_min,
        stop_loss_pct_max=cfg.hybrid_sell.stop_loss_pct_max,
        failed_breakout_drop_pct=cfg.hybrid_sell.failed_breakout_drop_pct,
        min_bars=max(cfg.hybrid_sell.min_bars, 2),
        time_stop_days=cfg.hybrid_sell.time_stop_days,
        time_stop_grace_days=cfg.hybrid_sell.time_stop_grace_days,
        time_stop_profit_floor=cfg.hybrid_sell.time_stop_profit_floor,
    )


def _evaluate_holdings(
    runtime: _SellRuntime,
    *,
    SellSettingsCls: Any,
    HybridSellSettingsCls: Any,
    evaluate_sell_signals_fn: Any,
    evaluate_sell_signals_hybrid_fn: Any,
    SellReportRowCls: Any,
    split_symbol_and_suffix_fn: Any,
    exchange_from_suffix_fn: Any,
) -> list[Any]:
    results: list[Any] = []
    settings = _build_sell_settings(runtime.cfg, SellSettingsCls=SellSettingsCls)
    hybrid_settings = _build_hybrid_sell_settings(
        runtime.cfg, HybridSellSettingsCls=HybridSellSettingsCls
    )

    for holding in runtime.holdings:
        ticker = holding.ticker
        ticker_candles = runtime.market_data.get(ticker)
        if not ticker_candles:
            if ticker not in runtime.missing_logged:
                runtime.failures.append(
                    f"{ticker}: No market data available for sell evaluation"
                )
                runtime.missing_logged.add(ticker)
            continue

        _, suffix = split_symbol_and_suffix_fn(ticker)
        holding_dict = {
            "entry_price": holding.entry_price,
            "entry_date": holding.entry_date,
            "stop_override": holding.stop_override,
            "target_override": holding.target_override,
            "strategy": holding.strategy,
            "entry_currency": holding.entry_currency
            or runtime.ticker_currency.get(ticker),
            "currency": runtime.ticker_currency.get(ticker),
            "exchange": exchange_from_suffix_fn(suffix),
            "data_source": runtime.ticker_data_source.get(
                ticker, runtime.cfg.data_provider
            ),
            "data_dir": runtime.cfg.data_dir,
        }

        if runtime.cfg.sell_mode == "sma_ema_hybrid":
            evaluation = evaluate_sell_signals_hybrid_fn(
                ticker, ticker_candles, holding_dict, hybrid_settings
            )
        else:
            evaluation = evaluate_sell_signals_fn(
                ticker, ticker_candles, holding_dict, settings
            )

        entry_price = holding.entry_price or None
        if entry_price is not None and (
            isinstance(entry_price, float) and math.isnan(entry_price)
        ):
            entry_price = None

        reason_messages = [
            str(reason).strip().lower()
            for reason in getattr(evaluation, "reasons", [])
            if reason is not None
        ]
        has_invalid_candle_data = any(
            reason.startswith("invalid candle data") for reason in reason_messages
        )

        eval_price = getattr(evaluation, "eval_price", None)
        if eval_price is None and ticker_candles and not has_invalid_candle_data:
            eval_price = ticker_candles[-1].get("close")
        try:
            last_price = float(eval_price) if eval_price is not None else None
        except (TypeError, ValueError):
            last_price = None
        if (
            last_price is not None
            and isinstance(last_price, float)
            and math.isnan(last_price)
        ):
            last_price = None

        pnl_pct = None
        if entry_price is not None and entry_price != 0 and last_price is not None:
            try:
                pnl_pct = (last_price - entry_price) / entry_price
            except TypeError:
                pnl_pct = None

        currency: str | None = holding.entry_currency or runtime.ticker_currency.get(
            ticker
        )
        if currency:
            currency = currency.upper()

        eval_date = getattr(evaluation, "eval_date", None)
        if eval_date is None and ticker_candles:
            raw_date = ticker_candles[-1].get("date")
            if raw_date:
                eval_date = str(raw_date)

        results.append(
            SellReportRowCls(
                ticker=ticker,
                name=ticker,
                quantity=holding.quantity,
                entry_price=entry_price,
                entry_date=holding.entry_date,
                last_price=last_price,
                pnl_pct=pnl_pct,
                action=evaluation.action,
                reasons=evaluation.reasons,
                stop_price=evaluation.stop_price,
                target_price=evaluation.target_price,
                notes=holding.notes,
                currency=currency,
                eval_date=eval_date,
            )
        )

    order = {"SELL": 0, "REVIEW": 1, "HOLD": 2}
    results.sort(key=lambda row: (order.get(row.action, 99), row.ticker))
    return results


def _build_sell_mode_note(cfg: Any) -> str | None:
    if cfg.sell_mode != "sma_ema_hybrid":
        return None
    return (
        f"profit partial ≥{cfg.hybrid_sell.partial_profit_floor * 100:.1f}%, "
        f"target {cfg.hybrid_sell.profit_target_low * 100:.1f}–"
        f"{cfg.hybrid_sell.profit_target_high * 100:.1f}%, "
        f"stop {cfg.hybrid_sell.stop_loss_pct_min * 100:.1f}–"
        f"{cfg.hybrid_sell.stop_loss_pct_max * 100:.1f}%"
    )


def _write_sell_report(
    runtime: _SellRuntime,
    results: list[Any],
    *,
    write_sell_report_fn: Any,
) -> str:
    return write_sell_report_fn(
        report_dir=runtime.cfg.report_dir,
        provider=runtime.cfg.data_provider,
        evaluated=results,
        failures=runtime.failures,
        cache_hint=runtime.cache_hint,
        atr_trail_multiplier=runtime.cfg.sell_atr_multiplier,
        time_stop_days=runtime.cfg.sell_time_stop_days,
        fx_rate=runtime.fx_rate,
        fx_note=runtime.fx_note,
        sell_mode=runtime.cfg.sell_mode,
        sell_mode_note=_build_sell_mode_note(runtime.cfg),
    )
