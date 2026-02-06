from __future__ import annotations

import logging
import math
from dataclasses import dataclass, field
from typing import Any

from .config import Config, load_config
from .config_loader import ConfigLoadError
from .data.cache import load_json, save_json
from .data.kis_client import KISAuthError, KISClient, KISClientError, KISCredentials
from .data.pykrx_client import (
    PykrxClient,
    PykrxClientError,
    PykrxNotInstalledError,
)
from .fx import SUFFIX_TO_EXCD, resolve_fx_rate
from .holdings_loader import HoldingsLoadError
from .report.sell_report import SellReportRow, write_sell_report
from .signals.hybrid_sell import (
    HybridSellEvaluation,
    HybridSellSettings,
    evaluate_sell_signals_hybrid,
)
from .signals.sell_rules import SellEvaluation, SellSettings, evaluate_sell_signals


def _infer_env_from_base(base_url: str) -> str:
    return "demo" if "vts" in base_url.lower() else "real"


def _normalize_suffix(suffix: str | None) -> str:
    if not suffix:
        return ""
    return "".join(ch for ch in suffix.upper() if ch.isalnum())


US_SUFFIXES = {_normalize_suffix(s) for s in SUFFIX_TO_EXCD}


def _split_symbol_and_suffix(ticker: str) -> tuple[str, str | None]:
    if "." not in ticker:
        return ticker.strip().upper(), None
    base, suffix = ticker.rsplit(".", 1)
    return base.strip().upper(), suffix.strip().upper()


def _exchange_from_suffix(suffix: str | None) -> str | None:
    if not suffix:
        return None
    norm = _normalize_suffix(suffix)
    for key, value in SUFFIX_TO_EXCD.items():
        if _normalize_suffix(key) == norm:
            return value
    return SUFFIX_TO_EXCD.get(norm)


def _infer_currency_from_ticker(ticker: str) -> str:
    _, suffix = _split_symbol_and_suffix(ticker)
    norm = _normalize_suffix(suffix)
    if norm in US_SUFFIXES:
        return "USD"
    return "KRW"


@dataclass
class _SellRuntime:
    cfg: Config
    logger: logging.Logger
    holdings: list[Any]
    unique_tickers: list[str]
    ticker_currency: dict[str, str]
    failures: list[str] = field(default_factory=list)
    market_data: dict[str, list[dict[str, Any]]] = field(default_factory=dict)
    ticker_data_source: dict[str, str] = field(default_factory=dict)
    cache_hint: str | None = None
    fatal_failure: bool = False
    kis_client: KISClient | None = None
    pykrx_client: PykrxClient | None = None
    pykrx_init_error: str | None = None
    pykrx_warning_added: bool = False
    missing_logged: set[str] = field(default_factory=set)
    fx_rate: float | None = None
    fx_note: str | None = None


def _build_sell_runtime(cfg: Config, logger: logging.Logger) -> _SellRuntime:
    holdings = cfg.holdings.holdings
    if not holdings:
        logger.warning("No holdings configured. Generating empty sell report.")

    tickers = [holding.ticker for holding in holdings if holding.ticker]
    unique_tickers = list(dict.fromkeys(tickers))

    ticker_currency: dict[str, str] = {}
    for holding in holdings:
        if not holding.ticker:
            continue
        entry_currency = (holding.entry_currency or "").strip().upper()
        if not entry_currency:
            entry_currency = _infer_currency_from_ticker(holding.ticker)
        ticker_currency[holding.ticker] = entry_currency

    return _SellRuntime(
        cfg=cfg,
        logger=logger,
        holdings=holdings,
        unique_tickers=unique_tickers,
        ticker_currency=ticker_currency,
    )


def _ensure_pykrx_client(runtime: _SellRuntime) -> PykrxClient | None:
    if runtime.pykrx_client is not None:
        return runtime.pykrx_client
    if runtime.pykrx_init_error:
        return None
    try:
        runtime.pykrx_client = PykrxClient(cache_dir=runtime.cfg.data_dir)
        runtime.logger.info("PyKRX client initialized")
        return runtime.pykrx_client
    except PykrxNotInstalledError as exc:
        runtime.pykrx_init_error = str(exc)
        runtime.logger.warning("PyKRX unavailable: %s", exc)
    except PykrxClientError as exc:
        runtime.pykrx_init_error = str(exc)
        runtime.logger.error("PyKRX init failed: %s", exc)
    return None


def _initialize_provider(runtime: _SellRuntime) -> None:
    cfg = runtime.cfg
    if cfg.data_provider == "kis":
        if not (cfg.kis_app_key and cfg.kis_app_secret and cfg.kis_base_url):
            msg = "KIS credentials missing. Set KIS_APP_KEY, KIS_APP_SECRET, KIS_BASE_URL in .env (see docs/kis-setup.md)."
            runtime.failures.append(msg)
            runtime.logger.error(msg)
            runtime.fatal_failure = True
            return

        creds = KISCredentials(
            app_key=cfg.kis_app_key,
            app_secret=cfg.kis_app_secret,
            base_url=cfg.kis_base_url,
            env=_infer_env_from_base(cfg.kis_base_url),
        )
        min_interval = None
        if cfg.kis_min_interval_ms is not None:
            min_interval = max(0.0, cfg.kis_min_interval_ms / 1000.0)
        runtime.kis_client = KISClient(
            creds, cache_dir=cfg.data_dir, min_interval=min_interval
        )
        runtime.cache_hint = runtime.kis_client.cache_status
        return

    if cfg.data_provider == "pykrx":
        client = _ensure_pykrx_client(runtime)
        if client is None:
            msg = (
                "PyKRX provider selected but pykrx package is unavailable. "
                "Install with 'uv sync --extra pykrx'."
            )
            runtime.failures.append(msg)
            runtime.logger.error(msg)
            runtime.fatal_failure = True
            return
        runtime.pykrx_client = client
        runtime.cache_hint = "pykrx"
        return

    runtime.failures.append(
        f"Provider '{cfg.data_provider}' not supported for sell command"
    )
    runtime.logger.error("Unsupported provider '%s'", cfg.data_provider)
    runtime.fatal_failure = True


def _resolve_sell_fx(runtime: _SellRuntime) -> None:
    if not runtime.unique_tickers:
        return
    resolved_rate, resolved_note, fx_messages = resolve_fx_rate(
        cfg=runtime.cfg,
        ticker_currency=runtime.ticker_currency,
        tickers=runtime.unique_tickers,
        kis_client=runtime.kis_client,
        logger=runtime.logger,
    )
    runtime.fx_rate = resolved_rate
    runtime.fx_note = resolved_note
    if fx_messages:
        runtime.failures.extend(fx_messages)


def _collect_market_data_from_kis(runtime: _SellRuntime, *, target_bars: int) -> None:
    if runtime.kis_client is None:
        return

    for ticker in runtime.unique_tickers:
        base_symbol, suffix = _split_symbol_and_suffix(ticker)
        exchange = _exchange_from_suffix(suffix)
        cache_key = (
            f"candles_overseas_{exchange}_{base_symbol}"
            if exchange
            else f"candles_{base_symbol}"
        )
        cached = load_json(runtime.cfg.data_dir, cache_key)
        if isinstance(cached, list) and cached:
            runtime.market_data[ticker] = cached
            runtime.ticker_data_source.setdefault(ticker, runtime.cfg.data_provider)

        try:
            if exchange:
                candles = runtime.kis_client.overseas_daily_candles(
                    symbol=base_symbol,
                    exchange=exchange,
                    count=target_bars,
                )
            else:
                candles = runtime.kis_client.daily_candles(
                    base_symbol, count=target_bars
                )
            if candles:
                runtime.market_data[ticker] = candles
                runtime.ticker_data_source[ticker] = "kis"
                save_json(runtime.cfg.data_dir, cache_key, candles)
                runtime.logger.info("Fetched %s candles for %s", len(candles), ticker)
            else:
                msg = f"{ticker}: No candle data returned"
                runtime.failures.append(msg)
                runtime.logger.warning(msg)
        except (KISClientError, KISAuthError) as exc:
            if ticker in runtime.market_data:
                msg = f"{ticker}: API error, using cached data ({exc})"
                runtime.failures.append(msg)
                runtime.logger.warning(msg)
                continue

            fallback_client = _ensure_pykrx_client(runtime)
            fallback_error = runtime.pykrx_init_error
            if fallback_client is not None and not exchange:
                # PyKRX supports KR tickers only.
                try:
                    candles = fallback_client.daily_candles(
                        base_symbol, count=target_bars
                    )
                except PykrxClientError as py_exc:
                    fallback_client = None
                    fallback_error = str(py_exc)
                else:
                    if candles:
                        runtime.market_data[ticker] = candles
                        runtime.ticker_data_source[ticker] = "pykrx"
                        runtime.logger.warning(
                            "%s: KIS error (%s); used PyKRX fallback (%s candles)",
                            ticker,
                            exc,
                            len(candles),
                        )
                        runtime.failures.append(
                            f"{ticker}: KIS error ({exc}); used PyKRX fallback"
                        )
                        if not runtime.pykrx_warning_added:
                            runtime.failures.append(
                                "Warning: PyKRX fallback data is end-of-day and may differ from KIS."
                            )
                            runtime.pykrx_warning_added = True
                        continue
                    fallback_error = "No data from PyKRX"
                    fallback_client = None

            msg = f"{ticker}: {exc}"
            if (fallback_client is None or exchange) and fallback_error:
                msg += f" (PyKRX fallback unavailable: {fallback_error})"
            runtime.failures.append(msg)
            runtime.logger.error(msg)


def _collect_market_data_from_pykrx(runtime: _SellRuntime, *, target_bars: int) -> None:
    if runtime.pykrx_client is None:
        return

    for ticker in runtime.unique_tickers:
        try:
            candles = runtime.pykrx_client.daily_candles(ticker, count=target_bars)
        except PykrxClientError as exc:
            msg = f"{ticker}: PyKRX error ({exc})"
            runtime.failures.append(msg)
            runtime.logger.error(msg)
            continue

        if candles:
            runtime.market_data[ticker] = candles
            runtime.ticker_data_source[ticker] = "pykrx"
            runtime.logger.info(
                "Fetched %s candles via PyKRX for %s", len(candles), ticker
            )
        else:
            msg = f"{ticker}: PyKRX returned no data"
            runtime.failures.append(msg)
            runtime.logger.warning(msg)

    if runtime.unique_tickers and not runtime.pykrx_warning_added:
        runtime.failures.append(
            "Warning: PyKRX provider data is end-of-day and may lag intraday feeds."
        )
        runtime.pykrx_warning_added = True


def _collect_market_data(runtime: _SellRuntime, *, target_bars: int) -> None:
    if runtime.cfg.data_provider == "kis" and runtime.kis_client:
        _collect_market_data_from_kis(runtime, target_bars=target_bars)
        return
    if runtime.cfg.data_provider == "pykrx" and runtime.pykrx_client:
        _collect_market_data_from_pykrx(runtime, target_bars=target_bars)


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
    )


def _evaluate_holdings(runtime: _SellRuntime) -> list[SellReportRow]:
    results: list[SellReportRow] = []
    settings = _build_sell_settings(runtime.cfg)
    hybrid_settings = _build_hybrid_sell_settings(runtime.cfg)

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

        _, suffix = _split_symbol_and_suffix(ticker)
        holding_dict = {
            "entry_price": holding.entry_price,
            "entry_date": holding.entry_date,
            "stop_override": holding.stop_override,
            "target_override": holding.target_override,
            "strategy": holding.strategy,
            "entry_currency": holding.entry_currency
            or runtime.ticker_currency.get(ticker),
            "currency": runtime.ticker_currency.get(ticker),
            "exchange": _exchange_from_suffix(suffix),
            "data_source": runtime.ticker_data_source.get(
                ticker, runtime.cfg.data_provider
            ),
            "data_dir": runtime.cfg.data_dir,
        }

        if runtime.cfg.sell_mode == "sma_ema_hybrid":
            evaluation: HybridSellEvaluation | SellEvaluation = (
                evaluate_sell_signals_hybrid(
                    ticker, ticker_candles, holding_dict, hybrid_settings
                )
            )
        else:
            evaluation = evaluate_sell_signals(
                ticker, ticker_candles, holding_dict, settings
            )

        entry_price = holding.entry_price or None
        if entry_price is not None and (
            isinstance(entry_price, float) and math.isnan(entry_price)
        ):
            entry_price = None
        eval_price = getattr(evaluation, "eval_price", None)
        if eval_price is None and ticker_candles:
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
        if (
            entry_price
            and entry_price != 0
            and last_price is not None
            and last_price != 0
        ):
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
            SellReportRow(
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


def _build_sell_mode_note(cfg: Config) -> str | None:
    if cfg.sell_mode != "sma_ema_hybrid":
        return None
    return (
        f"profit partial ≥{cfg.hybrid_sell.partial_profit_floor * 100:.1f}%, "
        f"target {cfg.hybrid_sell.profit_target_low * 100:.1f}–"
        f"{cfg.hybrid_sell.profit_target_high * 100:.1f}%, "
        f"stop {cfg.hybrid_sell.stop_loss_pct_min * 100:.1f}–"
        f"{cfg.hybrid_sell.stop_loss_pct_max * 100:.1f}%"
    )


def _write_sell_report(runtime: _SellRuntime, results: list[SellReportRow]) -> str:
    return write_sell_report(
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


def run_sell(*, provider: str | None) -> int:
    logger = logging.getLogger(__name__)
    try:
        cfg: Config = load_config(provider_override=provider)
    except (ConfigLoadError, HoldingsLoadError) as exc:
        logger.error("Configuration loading failed: %s", exc)
        return 1

    runtime = _build_sell_runtime(cfg, logger)
    _initialize_provider(runtime)
    _resolve_sell_fx(runtime)
    _collect_market_data(runtime, target_bars=max(cfg.min_history_bars, 200))
    results = _evaluate_holdings(runtime)

    out_path = _write_sell_report(runtime, results)
    logger.info("Sell report written to: %s", out_path)

    if runtime.fatal_failure:
        logger.error(
            "Sell evaluation completed with fatal errors. See report for details."
        )
        return 1
    if runtime.failures:
        logger.warning(
            "Sell evaluation completed with warnings. See report for details."
        )
    return 0


__all__ = ["run_sell"]
