from __future__ import annotations

import datetime as dt
import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, replace
from typing import Any

from .config import Config, load_config
from .report.backtest_report import write_backtest_report
from .signals.evaluator import EvaluationSettings, evaluate_ticker
from .signals.hybrid_buy import HybridEvaluationSettings, evaluate_ticker_hybrid
from .signals.hybrid_sell import HybridSellSettings, evaluate_sell_signals_hybrid
from .signals.sell_rules import SellSettings, evaluate_sell_signals
from .tickers import infer_currency_from_ticker, parse_ticker
from .utils.numeric import to_finite_float


@dataclass(frozen=True)
class BacktestRunConfig:
    start_date: str | None = None
    end_date: str | None = None
    transaction_cost_bps: float = 0.0
    slippage_bps: float = 0.0
    position_size_pct: float = 1.0
    partial_exit_fraction: float = 0.5
    intraday_exit_policy: str = "conservative"
    close_open_at_end: bool = True
    initial_equity: float = 1.0
    assumptions: Mapping[str, Any] | None = None


@dataclass(frozen=True)
class _OpenPosition:
    ticker: str
    entry_signal_date: dt.date
    entry_date: dt.date
    entry_index: int
    entry_price: float
    entry_signal_price: float | None
    entry_pattern: str | None
    entry_reasons: list[Any]
    currency: str
    remaining_fraction: float


@dataclass(frozen=True)
class _IntradayExit:
    action: str
    price: float
    reasons: list[str]


_OHLC_FIELDS = ("open", "high", "low", "close")


def _parse_date(value: Any) -> dt.date | None:
    text = str(value or "").strip()
    if not text:
        return None
    compact = text.replace("-", "")
    if len(compact) != 8 or not compact.isdigit():
        return None
    try:
        return dt.datetime.strptime(compact, "%Y%m%d").date()
    except ValueError:
        return None


def _date_iso(value: dt.date | None) -> str | None:
    return value.isoformat() if value is not None else None


def _coerce_ohlcv_rows(rows: Sequence[Any]) -> list[dict[str, Any]]:
    coerced: list[dict[str, Any]] = []
    for row in rows:
        coerced.append(dict(row) if isinstance(row, Mapping) else {"_invalid_row": row})
    return coerced


def _parse_bound_date(value: str | None, *, field_name: str) -> dt.date | None:
    text = str(value or "").strip()
    if not text:
        return None
    parsed = _parse_date(text)
    if parsed is None:
        raise ValueError(f"{field_name} must be YYYY-MM-DD or YYYYMMDD")
    return parsed


def _validate_fraction(value: float, *, field_name: str) -> float:
    parsed = to_finite_float(value)
    if parsed is None or parsed < 0.0 or parsed > 1.0:
        raise ValueError(f"{field_name} must be between 0 and 1")
    return parsed


def _normalize_ticker_list(
    tickers: str | list[str] | tuple[str, ...] | None,
) -> list[str]:
    if tickers is None:
        return []
    raw_items = tickers.split(",") if isinstance(tickers, str) else list(tickers)
    normalized: list[str] = []
    seen: set[str] = set()
    for item in raw_items:
        text = str(item or "").strip()
        if not text:
            continue
        ticker = parse_ticker(text).ticker
        if ticker in seen:
            continue
        seen.add(ticker)
        normalized.append(ticker)
    return normalized


def load_ohlcv_json(
    path: str,
    *,
    tickers: str | list[str] | tuple[str, ...] | None = None,
) -> dict[str, list[dict[str, Any]]]:
    with open(path, encoding="utf-8") as fp:
        raw = json.load(fp)

    requested = _normalize_ticker_list(tickers)
    if isinstance(raw, list):
        if len(requested) != 1:
            raise ValueError("list OHLCV data requires exactly one --tickers value")
        return {requested[0]: _coerce_ohlcv_rows(raw)}

    if not isinstance(raw, dict):
        raise ValueError("OHLCV data file must contain a ticker mapping or row list")

    raw_symbols = raw.get("symbols")
    if isinstance(raw_symbols, dict):
        raw = raw_symbols
    elif isinstance(raw.get("candles"), list):
        if len(requested) != 1:
            raise ValueError(
                "single candles payload requires exactly one --tickers value"
            )
        return {requested[0]: _coerce_ohlcv_rows(raw["candles"])}

    data_by_ticker: dict[str, list[dict[str, Any]]] = {}
    requested_set = set(requested)
    for raw_ticker, rows in raw.items():
        if not isinstance(rows, list):
            continue
        ticker = parse_ticker(str(raw_ticker)).ticker
        if requested_set and ticker not in requested_set:
            continue
        data_by_ticker[ticker] = _coerce_ohlcv_rows(rows)
    return data_by_ticker


def _build_evaluation_settings(cfg: Config) -> EvaluationSettings:
    return EvaluationSettings(
        use_sma200_filter=cfg.use_sma200_filter,
        gap_atr_multiplier=cfg.gap_atr_multiplier,
        min_dollar_volume=cfg.min_dollar_volume,
        us_min_dollar_volume=cfg.us_min_dollar_volume,
        min_history_bars=cfg.min_history_bars,
        exclude_etf_etn=cfg.exclude_etf_etn,
        require_slope_up=cfg.require_slope_up,
        rs_lookback_days=cfg.rs_lookback_days,
        rs_benchmark_return=cfg.rs_benchmark_return,
        min_price=cfg.min_price,
        us_min_price=cfg.us_min_price,
    )


def _build_hybrid_evaluation_settings(cfg: Config) -> HybridEvaluationSettings:
    return HybridEvaluationSettings(
        sma_trend_period=cfg.hybrid.sma_trend_period,
        ema_short_period=cfg.hybrid.ema_short_period,
        ema_mid_period=cfg.hybrid.ema_mid_period,
        rsi_period=cfg.hybrid.rsi_period,
        rsi_zone_low=cfg.hybrid.rsi_zone_low,
        rsi_zone_high=cfg.hybrid.rsi_zone_high,
        rsi_oversold_low=cfg.hybrid.rsi_oversold_low,
        rsi_oversold_high=cfg.hybrid.rsi_oversold_high,
        pullback_max_bars=cfg.hybrid.pullback_max_bars,
        breakout_consolidation_min_bars=cfg.hybrid.breakout_consolidation_min_bars,
        breakout_consolidation_max_bars=cfg.hybrid.breakout_consolidation_max_bars,
        breakout_consolidation_max_range_pct=(
            cfg.hybrid.breakout_consolidation_max_range_pct
        ),
        volume_lookback_days=cfg.hybrid.volume_lookback_days,
        max_gap_pct=cfg.hybrid.max_gap_pct,
        use_sma60_filter=cfg.hybrid.use_sma60_filter,
        sma60_period=cfg.hybrid.sma60_period,
        kr_breakout_requires_confirmation=cfg.hybrid.kr_breakout_requires_confirmation,
        gap_atr_multiplier=cfg.gap_atr_multiplier,
        min_history_bars=cfg.min_history_bars,
        min_price=cfg.min_price,
        us_min_price=cfg.us_min_price,
        min_dollar_volume=cfg.min_dollar_volume,
        us_min_dollar_volume=cfg.us_min_dollar_volume,
        exclude_etf_etn=cfg.exclude_etf_etn,
        rs_lookback_days=cfg.rs_lookback_days,
        rs_benchmark_return=cfg.rs_benchmark_return,
        sell_stop_loss_pct_max=cfg.hybrid_sell.stop_loss_pct_max,
    )


def _build_sell_settings(cfg: Config) -> SellSettings:
    return SellSettings(
        atr_trail_multiplier=cfg.sell_atr_multiplier,
        time_stop_days=cfg.sell_time_stop_days,
        require_sma200=cfg.sell_require_sma200,
        ema_lengths=(cfg.sell_ema_short, cfg.sell_ema_long),
        rsi_period=cfg.sell_rsi_period,
        rsi_floor=cfg.sell_rsi_floor,
        rsi_floor_alt=cfg.sell_rsi_floor_alt,
        min_bars=max(cfg.sell_min_bars, 2),
    )


def _build_hybrid_sell_settings(cfg: Config) -> HybridSellSettings:
    return HybridSellSettings(
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
        pattern_time_stops={
            pattern: {
                "time_stop_days": override.time_stop_days,
                "time_stop_grace_days": override.time_stop_grace_days,
                "time_stop_profit_floor": override.time_stop_profit_floor,
            }
            for pattern, override in cfg.hybrid_sell.pattern_time_stops.items()
        },
    )


def _meta_for_ticker(cfg: Config, ticker: str) -> dict[str, Any]:
    parsed = parse_ticker(ticker)
    return {
        "currency": infer_currency_from_ticker(ticker),
        "exchange": parsed.exchange,
        "data_source": "historical_json",
        "provider": "historical_json",
        "data_dir": cfg.data_dir,
    }


def _candidate_is_enterable(
    candidate: Mapping[str, Any], *, strategy_mode: str
) -> bool:
    entry_state = candidate.get("entry_state")
    if entry_state is not None and str(entry_state).strip().upper() != "READY":
        return False
    quality_state = candidate.get("quality_state")
    if strategy_mode == "sma_ema_hybrid" and quality_state is not None:
        return str(quality_state).strip().upper() == "A"
    return True


def _candidate_reasons(candidate: Mapping[str, Any]) -> list[Any]:
    reasons = candidate.get("reasons")
    return list(reasons) if isinstance(reasons, list) else []


def _evaluate_buy_signal(
    *,
    cfg: Config,
    ticker: str,
    candles: list[dict[str, Any]],
    meta: dict[str, Any],
    eval_settings: EvaluationSettings,
    hybrid_eval_settings: HybridEvaluationSettings,
    evaluate_ticker_fn: Any,
    evaluate_ticker_hybrid_fn: Any,
) -> Any:
    if cfg.strategy_mode == "sma_ema_hybrid":
        return evaluate_ticker_hybrid_fn(ticker, candles, hybrid_eval_settings, meta)
    return evaluate_ticker_fn(ticker, candles, eval_settings, meta)


def _evaluate_sell_signal(
    *,
    cfg: Config,
    ticker: str,
    candles: list[dict[str, Any]],
    holding: dict[str, Any],
    sell_settings: SellSettings,
    hybrid_sell_settings: HybridSellSettings,
    evaluate_sell_signals_fn: Any,
    evaluate_sell_signals_hybrid_fn: Any,
) -> Any:
    if cfg.sell_mode == "sma_ema_hybrid":
        return evaluate_sell_signals_hybrid_fn(
            ticker, candles, holding, hybrid_sell_settings
        )
    return evaluate_sell_signals_fn(ticker, candles, holding, sell_settings)


def _normalize_backtest_candles(
    *,
    ticker: str,
    rows: Sequence[Any],
    issues: list[str],
) -> list[dict[str, Any]]:
    normalized: list[tuple[dt.date, dict[str, Any]]] = []
    seen_dates: set[dt.date] = set()

    for row_index, raw_row in enumerate(rows, start=1):
        if not isinstance(raw_row, Mapping):
            issues.append(f"{ticker}: row {row_index}: invalid row shape")
            continue
        row = dict(raw_row)
        row_date = _parse_date(row.get("date"))
        if row_date is None:
            issues.append(f"{ticker}: row {row_index}: invalid date")
            continue
        if row_date in seen_dates:
            issues.append(f"{ticker}: {_date_iso(row_date)}: duplicate date")
            continue

        values: dict[str, float] = {}
        invalid_field: str | None = None
        for field in _OHLC_FIELDS:
            parsed = to_finite_float(row.get(field))
            if parsed is None or parsed <= 0.0:
                invalid_field = field
                break
            values[field] = parsed
        if invalid_field is not None:
            issue_label = (
                "invalid entry open"
                if invalid_field == "open"
                else f"invalid {invalid_field}"
            )
            issues.append(f"{ticker}: {_date_iso(row_date)}: {issue_label}")
            continue

        low = values["low"]
        high = values["high"]
        if (
            low > high
            or values["open"] < low
            or values["open"] > high
            or values["close"] < low
            or values["close"] > high
        ):
            issues.append(f"{ticker}: {_date_iso(row_date)}: invalid OHLC range")
            continue

        seen_dates.add(row_date)
        normalized.append((row_date, row))

    normalized.sort(key=lambda item: item[0])
    return [row for _, row in normalized]


def _bounded_fraction(value: float, *, default: float) -> float:
    parsed = to_finite_float(value)
    if parsed is None:
        return default
    return min(max(parsed, 0.0), 1.0)


def _normalize_intraday_exit_policy(value: str | None) -> str:
    policy = str(value or "").strip().lower().replace("-", "_")
    if policy in {"none", "conservative", "stop_first", "target_first"}:
        return policy
    return "conservative"


def _trade_return(
    *,
    entry_price: float,
    exit_price: float,
    transaction_cost_bps: float,
) -> float:
    if entry_price <= 0:
        return 0.0
    gross_return = (exit_price - entry_price) / entry_price
    round_trip_cost = max(transaction_cost_bps, 0.0) * 2.0 / 10_000.0
    return gross_return - round_trip_cost


def _apply_entry_slippage(price: float, slippage_bps: float) -> float:
    return price * (1.0 + max(slippage_bps, 0.0) / 10_000.0)


def _apply_exit_slippage(price: float, slippage_bps: float) -> float:
    return price * (1.0 - max(slippage_bps, 0.0) / 10_000.0)


def _build_holding(position: _OpenPosition, cfg: Config) -> dict[str, Any]:
    parsed = parse_ticker(position.ticker)
    return {
        "entry_price": position.entry_price,
        "entry_date": _date_iso(position.entry_date),
        "entry_pattern": position.entry_pattern,
        "strategy": cfg.sell_mode,
        "tags": [position.entry_pattern] if position.entry_pattern else [],
        "entry_currency": position.currency,
        "currency": position.currency,
        "exchange": parsed.exchange,
        "data_source": "historical_json",
        "data_dir": cfg.data_dir,
    }


def _resolve_intraday_exit(
    *,
    candle: Mapping[str, Any],
    sell_result: Any,
    policy: str,
) -> _IntradayExit | None:
    normalized_policy = _normalize_intraday_exit_policy(policy)
    if normalized_policy == "none":
        return None

    low = to_finite_float(candle.get("low"))
    high = to_finite_float(candle.get("high"))
    open_price = to_finite_float(candle.get("open"))
    stop_price = to_finite_float(getattr(sell_result, "stop_price", None))
    target_price = to_finite_float(getattr(sell_result, "target_price", None))
    if low is None or high is None:
        return None

    def stop_exit(default_reason: str) -> _IntradayExit:
        assert stop_price is not None
        if open_price is not None and open_price > 0 and open_price <= stop_price:
            return _IntradayExit(
                action="STOP_INTRADAY",
                price=open_price,
                reasons=["Intraday stop gap-through filled at open"],
            )
        return _IntradayExit(
            action="STOP_INTRADAY",
            price=stop_price,
            reasons=[default_reason],
        )

    def target_exit(default_reason: str) -> _IntradayExit:
        assert target_price is not None
        if open_price is not None and open_price > 0 and open_price >= target_price:
            return _IntradayExit(
                action="TARGET_INTRADAY",
                price=open_price,
                reasons=["Intraday target gap-through filled at open"],
            )
        return _IntradayExit(
            action="TARGET_INTRADAY",
            price=target_price,
            reasons=[default_reason],
        )

    stop_hit = stop_price is not None and stop_price > 0 and low <= stop_price
    target_hit = target_price is not None and target_price > 0 and high >= target_price
    if stop_hit and target_hit:
        assert stop_price is not None
        assert target_price is not None
        if open_price is not None and open_price > 0 and open_price <= stop_price:
            return stop_exit("Intraday stop gap-through filled at open")
        if open_price is not None and open_price > 0 and open_price >= target_price:
            return target_exit("Intraday target gap-through filled at open")
        if normalized_policy in {"conservative", "stop_first"}:
            return stop_exit(
                "Intraday stop/target policy "
                f"{normalized_policy} chose stop before target"
            )
        return target_exit(
            "Intraday stop/target policy target_first chose target before stop"
        )
    if stop_hit:
        return stop_exit("Intraday stop touched")
    if target_hit:
        return target_exit("Intraday target touched")
    return None


def _close_trade(
    *,
    position: _OpenPosition,
    exit_date: dt.date,
    exit_index: int,
    exit_price: float,
    exit_action: str,
    exit_reasons: list[str],
    transaction_cost_bps: float,
    quantity_fraction: float,
    remaining_fraction_after_exit: float,
    status: str = "closed",
) -> dict[str, Any]:
    net_return = _trade_return(
        entry_price=position.entry_price,
        exit_price=exit_price,
        transaction_cost_bps=transaction_cost_bps,
    )
    return {
        "ticker": position.ticker,
        "status": status,
        "entry_signal_date": _date_iso(position.entry_signal_date),
        "entry_date": _date_iso(position.entry_date),
        "entry_price": position.entry_price,
        "entry_signal_price": position.entry_signal_price,
        "entry_pattern": position.entry_pattern,
        "entry_reasons": position.entry_reasons,
        "exit_date": _date_iso(exit_date),
        "exit_price": exit_price,
        "exit_action": exit_action,
        "exit_reasons": exit_reasons,
        "return_pct": net_return,
        "return_contribution_pct": net_return * quantity_fraction,
        "quantity_fraction": quantity_fraction,
        "remaining_fraction_after_exit": remaining_fraction_after_exit,
        "holding_period_days": (exit_date - position.entry_date).days,
        "holding_period_bars": max(exit_index - position.entry_index, 0),
    }


def _open_trade_snapshot(
    *,
    position: _OpenPosition,
    last_date: dt.date,
    last_price: float,
    transaction_cost_bps: float,
) -> dict[str, Any]:
    unrealized_return = _trade_return(
        entry_price=position.entry_price,
        exit_price=last_price,
        transaction_cost_bps=transaction_cost_bps,
    )
    return {
        "ticker": position.ticker,
        "status": "open",
        "entry_signal_date": _date_iso(position.entry_signal_date),
        "entry_date": _date_iso(position.entry_date),
        "entry_price": position.entry_price,
        "entry_signal_price": position.entry_signal_price,
        "entry_pattern": position.entry_pattern,
        "entry_reasons": position.entry_reasons,
        "exit_date": None,
        "exit_price": None,
        "exit_action": None,
        "exit_reasons": [],
        "return_pct": None,
        "unrealized_return_pct": unrealized_return,
        "quantity_fraction": position.remaining_fraction,
        "remaining_fraction_after_exit": position.remaining_fraction,
        "holding_period_days": (last_date - position.entry_date).days,
        "holding_period_bars": None,
    }


def _mark_to_market_event(
    *,
    position: _OpenPosition,
    mark_date: dt.date,
    candle: Mapping[str, Any],
    transaction_cost_bps: float,
) -> dict[str, Any] | None:
    mark_price = to_finite_float(candle.get("low"))
    if mark_price is None or mark_price <= 0:
        mark_price = to_finite_float(candle.get("close"))
    if mark_price is None or mark_price <= 0:
        return None
    mark_return = _trade_return(
        entry_price=position.entry_price,
        exit_price=mark_price,
        transaction_cost_bps=transaction_cost_bps,
    )
    return {
        "ticker": position.ticker,
        "date": _date_iso(mark_date),
        "return_contribution_pct": mark_return * position.remaining_fraction,
        "quantity_fraction": position.remaining_fraction,
        "mark_price": mark_price,
        "mark_price_basis": "low",
    }


def _sort_date_text(value: Any) -> tuple[dt.date, str]:
    parsed = _parse_date(value)
    return (parsed or dt.date.max, str(value or ""))


def _build_summary(
    trades: list[dict[str, Any]],
    *,
    initial_equity: float,
    mark_events: list[dict[str, Any]] | None = None,
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    closed = [
        trade for trade in trades if trade.get("status") in {"closed", "partial_closed"}
    ]
    returns = [
        float(trade["return_pct"])
        for trade in closed
        if to_finite_float(trade.get("return_pct")) is not None
    ]
    wins = [value for value in returns if value > 0]
    losses = [value for value in returns if value <= 0]

    base_equity = initial_equity if initial_equity > 0 else 1.0
    peak = base_equity
    max_drawdown = 0.0
    equity_curve: list[dict[str, Any]] = [
        {"date": None, "equity": base_equity, "drawdown_pct": 0.0}
    ]

    closed_events: list[dict[str, Any]] = []
    total_closed_contribution = 0.0
    for sequence, trade in enumerate(closed):
        contribution_pct = to_finite_float(trade.get("return_contribution_pct"))
        if contribution_pct is None:
            return_pct = to_finite_float(trade.get("return_pct"))
            quantity_fraction = to_finite_float(trade.get("quantity_fraction")) or 1.0
            contribution_pct = (
                return_pct * quantity_fraction if return_pct is not None else None
            )
        if contribution_pct is None:
            continue
        total_closed_contribution += contribution_pct
        closed_events.append(
            {
                "date": trade.get("exit_date"),
                "ticker": trade.get("ticker"),
                "sequence": sequence,
                "return_contribution_pct": contribution_pct,
            }
        )

    closed_by_date: dict[str, float] = {}
    for event in sorted(
        closed_events,
        key=lambda item: (
            _sort_date_text(item.get("date")),
            str(item.get("ticker") or ""),
            int(item.get("sequence") or 0),
        ),
    ):
        date_text = str(event.get("date") or "")
        if not date_text:
            continue
        closed_by_date[date_text] = closed_by_date.get(date_text, 0.0) + float(
            event["return_contribution_pct"]
        )

    marks_by_date: dict[str, float] = {}
    exposure_by_date: dict[str, float] = {}
    for event in mark_events or []:
        date_text = str(event.get("date") or "")
        if not date_text:
            continue
        contribution = to_finite_float(event.get("return_contribution_pct")) or 0.0
        quantity = to_finite_float(event.get("quantity_fraction")) or 0.0
        marks_by_date[date_text] = marks_by_date.get(date_text, 0.0) + contribution
        exposure_by_date[date_text] = exposure_by_date.get(date_text, 0.0) + quantity

    running_closed_contribution = 0.0
    curve_dates = sorted(
        set(closed_by_date) | set(marks_by_date),
        key=lambda value: _sort_date_text(value),
    )
    for date_text in curve_dates:
        running_closed_contribution += closed_by_date.get(date_text, 0.0)
        equity = base_equity * (
            1.0 + running_closed_contribution + marks_by_date.get(date_text, 0.0)
        )
        peak = max(peak, equity)
        drawdown = (equity - peak) / peak if peak > 0 else 0.0
        max_drawdown = min(max_drawdown, drawdown)
        equity_curve.append(
            {
                "date": date_text,
                "equity": equity,
                "drawdown_pct": drawdown,
            }
        )

    avg_holding_days = None
    holding_days = [
        float(trade["holding_period_days"])
        for trade in closed
        if to_finite_float(trade.get("holding_period_days")) is not None
    ]
    if holding_days:
        avg_holding_days = sum(holding_days) / len(holding_days)

    summary = {
        "trade_count": len(trades),
        "closed_trade_count": len(closed),
        "open_trade_count": len(trades) - len(closed),
        "win_rate": (len(wins) / len(returns)) if returns else None,
        "total_return_pct": total_closed_contribution if initial_equity > 0 else None,
        "return_model": "non_compounded_initial_equity_contribution",
        "max_gross_exposure_pct": max(exposure_by_date.values(), default=0.0),
        "avg_return_pct": (sum(returns) / len(returns)) if returns else None,
        "best_return_pct": max(returns) if returns else None,
        "worst_return_pct": min(returns) if returns else None,
        "max_drawdown_pct": max_drawdown,
        "avg_holding_period_days": avg_holding_days,
        "winning_trade_count": len(wins),
        "losing_trade_count": len(losses),
    }
    return summary, equity_curve


def _execution_assumptions(
    run_config: BacktestRunConfig,
    *,
    intraday_policy: str | None = None,
) -> dict[str, Any]:
    resolved_policy = intraday_policy or _normalize_intraday_exit_policy(
        run_config.intraday_exit_policy
    )
    return {
        "entry_execution": "next_open",
        "exit_execution": (
            "signal_close" if resolved_policy == "none" else "intraday_ohlc"
        ),
        "position_size_pct": _bounded_fraction(
            run_config.position_size_pct,
            default=1.0,
        ),
        "partial_exit_fraction": _bounded_fraction(
            run_config.partial_exit_fraction,
            default=0.5,
        ),
        "intraday_exit_policy": resolved_policy,
    }


def _config_snapshot(cfg: Config, run_config: BacktestRunConfig) -> dict[str, Any]:
    intraday_policy = _normalize_intraday_exit_policy(run_config.intraday_exit_policy)
    execution = _execution_assumptions(run_config, intraday_policy=intraday_policy)
    return {
        "strategy_mode": cfg.strategy_mode,
        "sell_mode": cfg.sell_mode,
        "min_history_bars": cfg.min_history_bars,
        "gap_atr_multiplier": cfg.gap_atr_multiplier,
        "min_dollar_volume": cfg.min_dollar_volume,
        "rs_lookback_days": cfg.rs_lookback_days,
        "sell_min_bars": cfg.sell_min_bars,
        "hybrid": {
            "sma_trend_period": cfg.hybrid.sma_trend_period,
            "ema_short_period": cfg.hybrid.ema_short_period,
            "ema_mid_period": cfg.hybrid.ema_mid_period,
            "rsi_period": cfg.hybrid.rsi_period,
            "volume_lookback_days": cfg.hybrid.volume_lookback_days,
            "max_gap_pct": cfg.hybrid.max_gap_pct,
            "use_sma60_filter": cfg.hybrid.use_sma60_filter,
        },
        "hybrid_sell": {
            "profit_target_low": cfg.hybrid_sell.profit_target_low,
            "profit_target_high": cfg.hybrid_sell.profit_target_high,
            "partial_profit_floor": cfg.hybrid_sell.partial_profit_floor,
            "stop_loss_pct_min": cfg.hybrid_sell.stop_loss_pct_min,
            "stop_loss_pct_max": cfg.hybrid_sell.stop_loss_pct_max,
            "failed_breakout_drop_pct": cfg.hybrid_sell.failed_breakout_drop_pct,
            "time_stop_days": cfg.hybrid_sell.time_stop_days,
            "time_stop_grace_days": cfg.hybrid_sell.time_stop_grace_days,
            "time_stop_profit_floor": cfg.hybrid_sell.time_stop_profit_floor,
        },
        "backtest": {
            **execution,
            "force_close_open_at_end": run_config.close_open_at_end,
            "transaction_cost_bps": run_config.transaction_cost_bps,
            "slippage_bps": run_config.slippage_bps,
            "initial_equity": run_config.initial_equity,
        },
    }


def _build_assumptions(
    *,
    run_config: BacktestRunConfig,
    symbols: list[str],
) -> dict[str, Any]:
    assumptions: dict[str, Any] = {
        "data_source": {"status": "not_provided"},
        "universe": {
            "status": "derived_from_data_file",
            "symbols": sorted(symbols),
        },
        "benchmark": {"status": "not_configured"},
        "survivorship": {"status": "not_provided"},
        "execution": _execution_assumptions(run_config),
    }
    for key, value in (run_config.assumptions or {}).items():
        if isinstance(value, Mapping):
            base = assumptions.get(str(key))
            merged = dict(base) if isinstance(base, Mapping) else {}
            merged.update(dict(value))
            if "status" not in value:
                merged["status"] = "provided"
            assumptions[str(key)] = merged
        else:
            assumptions[str(key)] = value
    return assumptions


def run_historical_backtest(
    *,
    cfg: Config,
    market_data: Mapping[str, list[dict[str, Any]]],
    run_config: BacktestRunConfig | None = None,
    evaluate_ticker_fn: Any = evaluate_ticker,
    evaluate_ticker_hybrid_fn: Any = evaluate_ticker_hybrid,
    evaluate_sell_signals_fn: Any = evaluate_sell_signals,
    evaluate_sell_signals_hybrid_fn: Any = evaluate_sell_signals_hybrid,
) -> dict[str, Any]:
    run_config = run_config or BacktestRunConfig()
    start = _parse_bound_date(run_config.start_date, field_name="start_date")
    end = _parse_bound_date(run_config.end_date, field_name="end_date")
    if start is not None and end is not None and start > end:
        raise ValueError("start_date must be on or before end_date")
    position_size_pct = _validate_fraction(
        run_config.position_size_pct,
        field_name="position_size_pct",
    )
    partial_exit_fraction = _validate_fraction(
        run_config.partial_exit_fraction,
        field_name="partial_exit_fraction",
    )
    intraday_exit_policy = _normalize_intraday_exit_policy(
        run_config.intraday_exit_policy
    )

    eval_settings = _build_evaluation_settings(cfg)
    hybrid_eval_settings = _build_hybrid_evaluation_settings(cfg)
    sell_settings = _build_sell_settings(cfg)
    hybrid_sell_settings = _build_hybrid_sell_settings(cfg)

    trades: list[dict[str, Any]] = []
    mark_events: list[dict[str, Any]] = []
    issues: list[str] = []
    all_dates: list[dt.date] = []
    symbols: list[str] = []
    markets: set[str] = set()

    for raw_ticker, raw_candles in sorted(market_data.items()):
        ticker = parse_ticker(raw_ticker).ticker
        candles = _normalize_backtest_candles(
            ticker=ticker,
            rows=raw_candles,
            issues=issues,
        )
        if not candles:
            issues.append(f"{ticker}: no valid OHLCV rows")
            continue
        symbols.append(ticker)
        markets.add(parse_ticker(ticker).market)
        dated_rows = [(_parse_date(row.get("date")), row) for row in candles]
        valid_dates = [date for date, _ in dated_rows if date is not None]
        all_dates.extend(valid_dates)
        position: _OpenPosition | None = None
        pending_candidate: tuple[int, dt.date, Mapping[str, Any]] | None = None
        meta = _meta_for_ticker(cfg, ticker)
        currency = str(meta.get("currency") or infer_currency_from_ticker(ticker))

        for idx, (current_date, candle) in enumerate(dated_rows):
            if current_date is None:
                continue
            if end is not None and current_date > end:
                break

            if (
                pending_candidate is not None
                and position is None
                and idx > pending_candidate[0]
                and (start is None or current_date >= start)
            ):
                entry_open = to_finite_float(candle.get("open"))
                if entry_open is not None and entry_open > 0:
                    _, signal_date, entry_candidate = pending_candidate
                    position = _OpenPosition(
                        ticker=ticker,
                        entry_signal_date=signal_date,
                        entry_date=current_date,
                        entry_index=idx,
                        entry_price=_apply_entry_slippage(
                            entry_open, run_config.slippage_bps
                        ),
                        entry_signal_price=to_finite_float(
                            entry_candidate.get("price_value")
                        ),
                        entry_pattern=(
                            str(entry_candidate.get("pattern")).strip()
                            if entry_candidate.get("pattern") is not None
                            else None
                        ),
                        entry_reasons=_candidate_reasons(entry_candidate),
                        currency=currency,
                        remaining_fraction=position_size_pct,
                    )
                    if position.remaining_fraction <= 0:
                        position = None
                    pending_candidate = None
                else:
                    _, signal_date, _ = pending_candidate
                    issues.append(
                        f"{ticker}: {_date_iso(current_date)}: invalid entry open; "
                        f"signal from {_date_iso(signal_date)} remains pending"
                    )

            if start is not None and current_date < start:
                continue

            prefix = candles[: idx + 1]
            if position is not None:
                holding = _build_holding(position, cfg)
                previous_sell_result = None
                if intraday_exit_policy != "none" and idx > position.entry_index:
                    previous_prefix = candles[:idx]
                    previous_sell_result = _evaluate_sell_signal(
                        cfg=cfg,
                        ticker=ticker,
                        candles=previous_prefix,
                        holding=holding,
                        sell_settings=sell_settings,
                        hybrid_sell_settings=hybrid_sell_settings,
                        evaluate_sell_signals_fn=evaluate_sell_signals_fn,
                        evaluate_sell_signals_hybrid_fn=evaluate_sell_signals_hybrid_fn,
                    )
                sell_result = _evaluate_sell_signal(
                    cfg=cfg,
                    ticker=ticker,
                    candles=prefix,
                    holding=holding,
                    sell_settings=sell_settings,
                    hybrid_sell_settings=hybrid_sell_settings,
                    evaluate_sell_signals_fn=evaluate_sell_signals_fn,
                    evaluate_sell_signals_hybrid_fn=evaluate_sell_signals_hybrid_fn,
                )
                action = str(getattr(sell_result, "action", "") or "").upper()
                intraday_exit = (
                    _resolve_intraday_exit(
                        candle=candle,
                        sell_result=previous_sell_result,
                        policy=intraday_exit_policy,
                    )
                    if previous_sell_result is not None
                    else None
                )
                if intraday_exit is not None:
                    trades.append(
                        _close_trade(
                            position=position,
                            exit_date=current_date,
                            exit_index=idx,
                            exit_price=_apply_exit_slippage(
                                intraday_exit.price, run_config.slippage_bps
                            ),
                            exit_action=intraday_exit.action,
                            exit_reasons=intraday_exit.reasons,
                            transaction_cost_bps=run_config.transaction_cost_bps,
                            quantity_fraction=position.remaining_fraction,
                            remaining_fraction_after_exit=0.0,
                        )
                    )
                    position = None
                elif action in {"SELL", "SELL_PARTIAL"}:
                    eval_price = to_finite_float(
                        getattr(sell_result, "eval_price", None)
                    )
                    if eval_price is None:
                        eval_price = to_finite_float(candle.get("close"))
                    if eval_price is not None and eval_price > 0:
                        if action == "SELL_PARTIAL":
                            quantity_fraction = (
                                position.remaining_fraction * partial_exit_fraction
                            )
                        else:
                            quantity_fraction = position.remaining_fraction
                        if quantity_fraction <= 0:
                            continue
                        quantity_fraction = min(
                            quantity_fraction,
                            position.remaining_fraction,
                        )
                        remaining_fraction = max(
                            position.remaining_fraction - quantity_fraction,
                            0.0,
                        )
                        status = (
                            "partial_closed"
                            if action == "SELL_PARTIAL" and remaining_fraction > 1e-9
                            else "closed"
                        )
                        reasons = [
                            str(reason)
                            for reason in getattr(sell_result, "reasons", []) or []
                        ]
                        trades.append(
                            _close_trade(
                                position=position,
                                exit_date=current_date,
                                exit_index=idx,
                                exit_price=_apply_exit_slippage(
                                    eval_price, run_config.slippage_bps
                                ),
                                exit_action=action,
                                exit_reasons=reasons,
                                transaction_cost_bps=run_config.transaction_cost_bps,
                                quantity_fraction=quantity_fraction,
                                remaining_fraction_after_exit=remaining_fraction,
                                status=status,
                            )
                        )
                        position = (
                            replace(position, remaining_fraction=remaining_fraction)
                            if remaining_fraction > 1e-9
                            else None
                        )
                if position is not None:
                    mark_event = _mark_to_market_event(
                        position=position,
                        mark_date=current_date,
                        candle=candle,
                        transaction_cost_bps=run_config.transaction_cost_bps,
                    )
                    if mark_event is not None:
                        mark_events.append(mark_event)

            if position is None and pending_candidate is None:
                buy_result = _evaluate_buy_signal(
                    cfg=cfg,
                    ticker=ticker,
                    candles=prefix,
                    meta=meta,
                    eval_settings=eval_settings,
                    hybrid_eval_settings=hybrid_eval_settings,
                    evaluate_ticker_fn=evaluate_ticker_fn,
                    evaluate_ticker_hybrid_fn=evaluate_ticker_hybrid_fn,
                )
                raw_candidate = getattr(buy_result, "candidate", None)
                if isinstance(raw_candidate, Mapping) and _candidate_is_enterable(
                    raw_candidate, strategy_mode=cfg.strategy_mode
                ):
                    pending_candidate = (idx, current_date, raw_candidate)

        if position is not None:
            last_date: dt.date | None = None
            last_row: dict[str, Any] | None = None
            last_idx: int | None = None
            for idx in range(len(dated_rows) - 1, -1, -1):
                candidate_date, row = dated_rows[idx]
                if candidate_date is None:
                    continue
                if end is not None and candidate_date > end:
                    continue
                last_date = candidate_date
                last_row = row
                last_idx = idx
                break
            if last_date is not None and last_row is not None and last_idx is not None:
                last_close = to_finite_float(last_row.get("close"))
                if last_close is not None and last_close > 0:
                    if run_config.close_open_at_end:
                        trades.append(
                            _close_trade(
                                position=position,
                                exit_date=last_date,
                                exit_index=last_idx,
                                exit_price=_apply_exit_slippage(
                                    last_close, run_config.slippage_bps
                                ),
                                exit_action="END_OF_BACKTEST",
                                exit_reasons=["End of backtest period"],
                                transaction_cost_bps=(run_config.transaction_cost_bps),
                                quantity_fraction=position.remaining_fraction,
                                remaining_fraction_after_exit=0.0,
                            )
                        )
                    else:
                        trades.append(
                            _open_trade_snapshot(
                                position=position,
                                last_date=last_date,
                                last_price=last_close,
                                transaction_cost_bps=(run_config.transaction_cost_bps),
                            )
                        )

        if pending_candidate is not None:
            _, signal_date, _ = pending_candidate
            issues.append(
                f"{ticker}: pending entry from {_date_iso(signal_date)} "
                "never found a valid next open"
            )

    trades.sort(key=lambda trade: (str(trade.get("entry_date") or ""), trade["ticker"]))
    summary, equity_curve = _build_summary(
        trades,
        initial_equity=run_config.initial_equity,
        mark_events=mark_events,
    )
    period_start = start or (min(all_dates) if all_dates else None)
    period_end = end or (max(all_dates) if all_dates else None)
    return {
        "period": {
            "start_date": _date_iso(period_start),
            "end_date": _date_iso(period_end),
        },
        "symbols": sorted(symbols),
        "markets": sorted(markets),
        "summary": summary,
        "trades": trades,
        "equity_curve": equity_curve,
        "issues": issues,
        "assumptions": _build_assumptions(
            run_config=run_config,
            symbols=symbols,
        ),
        "config_snapshot": _config_snapshot(cfg, run_config),
    }


def _load_assumptions_file(path: str | None) -> dict[str, Any]:
    if not path:
        return {}
    with open(path, encoding="utf-8") as fp:
        raw = json.load(fp)
    if not isinstance(raw, dict):
        raise ValueError("backtest assumptions file must contain a JSON object")
    return dict(raw)


def _resolve_runtime_config(
    *,
    strategy_mode: str | None,
    sell_mode: str | None,
    report_dir: str | None,
) -> Config:
    cfg = load_config()
    overrides: dict[str, Any] = {}
    if strategy_mode:
        overrides["strategy_mode"] = strategy_mode
    if sell_mode:
        overrides["sell_mode"] = sell_mode
    if report_dir:
        overrides["report_dir"] = report_dir
    if overrides:
        cfg = replace(cfg, **overrides)
    return cfg


def run_backtest(
    *,
    data_file_path: str,
    tickers: str | list[str] | tuple[str, ...] | None = None,
    start_date: str | None = None,
    end_date: str | None = None,
    strategy_mode: str | None = None,
    sell_mode: str | None = None,
    report_dir: str | None = None,
    transaction_cost_bps: float = 0.0,
    slippage_bps: float = 0.0,
    position_size_pct: float = 1.0,
    partial_exit_fraction: float = 0.5,
    intraday_exit_policy: str = "conservative",
    assumptions_file_path: str | None = None,
    close_open_at_end: bool = True,
    evaluate_ticker_fn: Any = evaluate_ticker,
    evaluate_ticker_hybrid_fn: Any = evaluate_ticker_hybrid,
    evaluate_sell_signals_fn: Any = evaluate_sell_signals,
    evaluate_sell_signals_hybrid_fn: Any = evaluate_sell_signals_hybrid,
) -> int:
    cfg = _resolve_runtime_config(
        strategy_mode=strategy_mode,
        sell_mode=sell_mode,
        report_dir=report_dir,
    )
    data = load_ohlcv_json(data_file_path, tickers=tickers)
    run_config = BacktestRunConfig(
        start_date=start_date,
        end_date=end_date,
        transaction_cost_bps=transaction_cost_bps,
        slippage_bps=slippage_bps,
        position_size_pct=position_size_pct,
        partial_exit_fraction=partial_exit_fraction,
        intraday_exit_policy=intraday_exit_policy,
        close_open_at_end=close_open_at_end,
        assumptions=_load_assumptions_file(assumptions_file_path),
    )
    result = run_historical_backtest(
        cfg=cfg,
        market_data=data,
        run_config=run_config,
        evaluate_ticker_fn=evaluate_ticker_fn,
        evaluate_ticker_hybrid_fn=evaluate_ticker_hybrid_fn,
        evaluate_sell_signals_fn=evaluate_sell_signals_fn,
        evaluate_sell_signals_hybrid_fn=evaluate_sell_signals_hybrid_fn,
    )
    out_path = write_backtest_report(
        report_dir=cfg.report_dir,
        result=result,
        artifact_date=result["period"]["end_date"],
    )
    print(out_path)
    return 0


__all__ = [
    "BacktestRunConfig",
    "load_ohlcv_json",
    "run_backtest",
    "run_historical_backtest",
]
