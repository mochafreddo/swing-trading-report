from __future__ import annotations

import logging
import math
from typing import Any

from .config import Config, load_config
from .data.cache import load_json, save_json
from .data.kis_client import KISAuthError, KISClient, KISClientError, KISCredentials
from .data.pykrx_client import (
    PykrxClient,
    PykrxClientError,
    PykrxNotInstalledError,
)
from .fx import SUFFIX_TO_EXCD, resolve_fx_rate
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


US_SUFFIXES = {_normalize_suffix(s) for s in SUFFIX_TO_EXCD.keys()}


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


def run_sell(*, provider: str | None) -> int:
    logger = logging.getLogger(__name__)
    cfg: Config = load_config(provider_override=provider)

    holdings = cfg.holdings.holdings
    if not holdings:
        logger.warning("No holdings configured. Generating empty sell report.")

    tickers = [h.ticker for h in holdings if h.ticker]
    unique_tickers = list(dict.fromkeys(tickers))

    ticker_currency: dict[str, str] = {}
    for holding in holdings:
        if not holding.ticker:
            continue
        currency = (holding.entry_currency or "").strip().upper()
        if not currency:
            currency = _infer_currency_from_ticker(holding.ticker)
        ticker_currency[holding.ticker] = currency

    failures: list[str] = []
    market_data: dict[str, list[dict[str, Any]]] = {}
    ticker_data_source: dict[str, str] = {}
    cache_hint: str | None = None
    fatal_failure = False

    kis_client: KISClient | None = None
    pykrx_client: PykrxClient | None = None
    pykrx_init_error: str | None = None
    pykrx_warning_added = False
    missing_logged: set[str] = set()

    def ensure_pykrx_client() -> PykrxClient | None:
        nonlocal pykrx_client, pykrx_init_error
        if pykrx_client is not None:
            return pykrx_client
        if pykrx_init_error:
            return None
        try:
            pykrx_client = PykrxClient(cache_dir=cfg.data_dir)
            logger.info("PyKRX client initialized")
            return pykrx_client
        except PykrxNotInstalledError as exc:
            pykrx_init_error = str(exc)
            logger.warning("PyKRX unavailable: %s", exc)
        except PykrxClientError as exc:
            pykrx_init_error = str(exc)
            logger.error("PyKRX init failed: %s", exc)
        return None

    if cfg.data_provider == "kis":
        if not (cfg.kis_app_key and cfg.kis_app_secret and cfg.kis_base_url):
            msg = "KIS credentials missing. Set KIS_APP_KEY, KIS_APP_SECRET, KIS_BASE_URL in .env (see docs/kis-setup.md)."
            failures.append(msg)
            logger.error(msg)
            fatal_failure = True
        else:
            creds = KISCredentials(
                app_key=cfg.kis_app_key,
                app_secret=cfg.kis_app_secret,
                base_url=cfg.kis_base_url,
                env=_infer_env_from_base(cfg.kis_base_url),
            )
            min_interval = None
            if cfg.kis_min_interval_ms is not None:
                min_interval = max(0.0, cfg.kis_min_interval_ms / 1000.0)
            kis_client = KISClient(creds, cache_dir=cfg.data_dir, min_interval=min_interval)
            cache_hint = kis_client.cache_status
    elif cfg.data_provider == "pykrx":
        client = ensure_pykrx_client()
        if client is None:
            msg = "PyKRX provider selected but pykrx package is unavailable. Install with 'uv add pykrx'."
            failures.append(msg)
            logger.error(msg)
            fatal_failure = True
        else:
            pykrx_client = client
            cache_hint = "pykrx"
    else:
        failures.append(f"Provider '{cfg.data_provider}' not supported for sell command")
        logger.error("Unsupported provider '%s'", cfg.data_provider)
        fatal_failure = True

    target_bars = max(cfg.min_history_bars, 200)

    fx_rate: float | None = None
    fx_note: str | None = None
    if unique_tickers:
        resolved_rate, resolved_note, fx_messages = resolve_fx_rate(
            cfg=cfg,
            ticker_currency=ticker_currency,
            tickers=unique_tickers,
            kis_client=kis_client,
            logger=logger,
        )
        fx_rate = resolved_rate
        fx_note = resolved_note
        if fx_messages:
            failures.extend(fx_messages)

    if cfg.data_provider == "kis" and kis_client:
        for ticker in unique_tickers:
            base_symbol, suffix = _split_symbol_and_suffix(ticker)
            exch = _exchange_from_suffix(suffix)
            cache_key = (
                f"candles_overseas_{exch}_{base_symbol}" if exch else f"candles_{base_symbol}"
            )
            cached = load_json(cfg.data_dir, cache_key)
            if isinstance(cached, list) and cached:
                market_data[ticker] = cached
                ticker_data_source.setdefault(ticker, cfg.data_provider)
            try:
                if exch:
                    candles = kis_client.overseas_daily_candles(
                        symbol=base_symbol, exchange=exch, count=target_bars
                    )
                else:
                    candles = kis_client.daily_candles(base_symbol, count=target_bars)
                if candles:
                    market_data[ticker] = candles
                    ticker_data_source[ticker] = "kis"
                    save_json(cfg.data_dir, cache_key, candles)
                    logger.info("Fetched %s candles for %s", len(candles), ticker)
                else:
                    msg = f"{ticker}: No candle data returned"
                    failures.append(msg)
                    logger.warning(msg)
            except (KISClientError, KISAuthError) as exc:
                if ticker in market_data:
                    msg = f"{ticker}: API error, using cached data ({exc})"
                    failures.append(msg)
                    logger.warning(msg)
                else:
                    fallback_client = ensure_pykrx_client()
                    fallback_error = pykrx_init_error
                    if fallback_client is not None and not exch:
                        # PyKRX supports KR tickers only
                        try:
                            candles = fallback_client.daily_candles(base_symbol, count=target_bars)
                        except PykrxClientError as py_exc:
                            fallback_client = None
                            fallback_error = str(py_exc)
                        else:
                            if candles:
                                market_data[ticker] = candles
                                ticker_data_source[ticker] = "pykrx"
                                logger.warning(
                                    "%s: KIS error (%s); used PyKRX fallback (%s candles)",
                                    ticker,
                                    exc,
                                    len(candles),
                                )
                                failures.append(f"{ticker}: KIS error ({exc}); used PyKRX fallback")
                                if not pykrx_warning_added:
                                    failures.append(
                                        "Warning: PyKRX fallback data is end-of-day and may differ from KIS."
                                    )
                                    pykrx_warning_added = True
                                continue
                            fallback_error = "No data from PyKRX"
                            fallback_client = None
                    msg = f"{ticker}: {exc}"
                    if (fallback_client is None or exch) and fallback_error:
                        msg += f" (PyKRX fallback unavailable: {fallback_error})"
                    failures.append(msg)
                    logger.error(msg)
    elif cfg.data_provider == "pykrx" and pykrx_client:
        for ticker in unique_tickers:
            try:
                candles = pykrx_client.daily_candles(ticker, count=target_bars)
            except PykrxClientError as exc:
                msg = f"{ticker}: PyKRX error ({exc})"
                failures.append(msg)
                logger.error(msg)
                continue

            if candles:
                market_data[ticker] = candles
                ticker_data_source[ticker] = "pykrx"
                logger.info("Fetched %s candles via PyKRX for %s", len(candles), ticker)
            else:
                msg = f"{ticker}: PyKRX returned no data"
                failures.append(msg)
                logger.warning(msg)

        if unique_tickers and not pykrx_warning_added:
            failures.append(
                "Warning: PyKRX provider data is end-of-day and may lag intraday feeds."
            )
            pykrx_warning_added = True

    results: list[SellReportRow] = []
    order = {"SELL": 0, "REVIEW": 1, "HOLD": 2}

    settings = SellSettings(
        atr_trail_multiplier=cfg.sell_atr_multiplier,
        time_stop_days=cfg.sell_time_stop_days,
        require_sma200=cfg.sell_require_sma200,
        ema_lengths=(cfg.sell_ema_short, cfg.sell_ema_long),
        rsi_period=cfg.sell_rsi_period,
        rsi_floor=cfg.sell_rsi_floor,
        rsi_floor_alt=cfg.sell_rsi_floor_alt,
        min_bars=max(cfg.sell_min_bars, 2),
    )

    hybrid_settings = HybridSellSettings(
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
    )

    for holding in holdings:
        ticker = holding.ticker
        candles = market_data.get(ticker)
        if not candles:
            if ticker not in missing_logged:
                failures.append(f"{ticker}: No market data available for sell evaluation")
                missing_logged.add(ticker)
            continue
        holding_dict = {
            "entry_price": holding.entry_price,
            "entry_date": holding.entry_date,
            "stop_override": holding.stop_override,
            "target_override": holding.target_override,
            "strategy": holding.strategy,
            "entry_currency": holding.entry_currency or ticker_currency.get(ticker),
            "currency": ticker_currency.get(ticker),
            "exchange": _exchange_from_suffix(suffix),
            "data_source": ticker_data_source.get(ticker, cfg.data_provider),
        }
        if cfg.sell_mode == "sma_ema_hybrid":
            evaluation: HybridSellEvaluation | SellEvaluation = evaluate_sell_signals_hybrid(
                ticker,
                candles,
                holding_dict,
                hybrid_settings,
            )
        else:
            evaluation = evaluate_sell_signals(
                ticker,
                candles,
                holding_dict,
                settings,
            )
        entry_price = holding.entry_price or None
        if entry_price is not None and (isinstance(entry_price, float) and math.isnan(entry_price)):
            entry_price = None

        eval_price = getattr(evaluation, "eval_price", None)
        if eval_price is None and candles:
            eval_price = candles[-1].get("close")
        try:
            last_price = float(eval_price) if eval_price is not None else None
        except (TypeError, ValueError):
            last_price = None
        if last_price is not None and isinstance(last_price, float) and math.isnan(last_price):
            last_price = None

        pnl_pct = None
        if entry_price and entry_price != 0 and last_price not in (None, 0):
            try:
                pnl_pct = (last_price - entry_price) / entry_price
            except TypeError:
                pnl_pct = None

        currency = holding.entry_currency or ticker_currency.get(ticker)
        if currency:
            currency = currency.upper()

        eval_date = getattr(evaluation, "eval_date", None)
        if eval_date is None and candles:
            raw_date = candles[-1].get("date")
            if raw_date:
                eval_date = str(raw_date)

        row = SellReportRow(
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
        results.append(row)

    results.sort(key=lambda r: (order.get(r.action, 99), r.ticker))

    sell_mode_note: str | None = None
    if cfg.sell_mode == "sma_ema_hybrid":
        sell_mode_note = (
            f"profit {cfg.hybrid_sell.profit_target_low * 100:.1f}–"
            f"{cfg.hybrid_sell.profit_target_high * 100:.1f}%, "
            f"stop {cfg.hybrid_sell.stop_loss_pct_min * 100:.1f}–"
            f"{cfg.hybrid_sell.stop_loss_pct_max * 100:.1f}%"
        )

    out_path = write_sell_report(
        report_dir=cfg.report_dir,
        provider=cfg.data_provider,
        evaluated=results,
        failures=failures,
        cache_hint=cache_hint,
        atr_trail_multiplier=cfg.sell_atr_multiplier,
        time_stop_days=cfg.sell_time_stop_days,
        fx_rate=fx_rate,
        fx_note=fx_note,
        sell_mode=cfg.sell_mode,
        sell_mode_note=sell_mode_note,
    )

    logger.info("Sell report written to: %s", out_path)

    if fatal_failure:
        logger.error("Sell evaluation completed with fatal errors. See report for details.")
        return 1

    if failures:
        logger.warning("Sell evaluation completed with warnings. See report for details.")

    return 0


__all__ = ["run_sell"]
