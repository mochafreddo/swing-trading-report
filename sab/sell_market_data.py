from __future__ import annotations

from typing import Any

from .data.kis_client import KISAuthError, KISClientError
from .data.pykrx_client import PykrxClientError, PykrxNotInstalledError
from .sell_types import _SellRuntime


def _ensure_pykrx_client(runtime: _SellRuntime, *, PykrxClientCls: Any) -> Any | None:
    if runtime.pykrx_client is not None:
        return runtime.pykrx_client
    if runtime.pykrx_init_error:
        return None
    try:
        runtime.pykrx_client = PykrxClientCls(cache_dir=runtime.cfg.data_dir)
        runtime.logger.info("PyKRX client initialized")
        return runtime.pykrx_client
    except PykrxNotInstalledError as exc:
        runtime.pykrx_init_error = str(exc)
        runtime.logger.warning("PyKRX unavailable: %s", exc)
    except PykrxClientError as exc:
        runtime.pykrx_init_error = str(exc)
        runtime.logger.error("PyKRX init failed: %s", exc)
    return None


def _initialize_provider(
    runtime: _SellRuntime,
    *,
    KISCredentialsCls: Any,
    KISClientCls: Any,
    ensure_pykrx_client_fn: Any,
    infer_env_from_base_fn: Any,
) -> None:
    cfg = runtime.cfg
    if cfg.data_provider == "kis":
        if not (cfg.kis_app_key and cfg.kis_app_secret and cfg.kis_base_url):
            msg = "KIS credentials missing. Set KIS_APP_KEY, KIS_APP_SECRET, KIS_BASE_URL in .env (see docs/kis-setup.md)."
            runtime.failures.append(msg)
            runtime.logger.error(msg)
            runtime.fatal_failure = True
            return

        creds = KISCredentialsCls(
            app_key=cfg.kis_app_key,
            app_secret=cfg.kis_app_secret,
            base_url=cfg.kis_base_url,
            env=infer_env_from_base_fn(cfg.kis_base_url),
        )
        min_interval = None
        if cfg.kis_min_interval_ms is not None:
            min_interval = max(0.0, cfg.kis_min_interval_ms / 1000.0)
        runtime.kis_client = KISClientCls(
            creds, cache_dir=cfg.data_dir, min_interval=min_interval
        )
        runtime.cache_hint = runtime.kis_client.cache_status
        runtime.logger.info(
            "KIS token cache status=%s (env=%s, cache_dir=%s)",
            runtime.kis_client.cache_status or "unknown",
            creds.env,
            cfg.data_dir,
        )
        return

    if cfg.data_provider == "pykrx":
        client = ensure_pykrx_client_fn(runtime)
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


def _resolve_sell_fx(runtime: _SellRuntime, *, resolve_fx_rate_fn: Any) -> None:
    if not runtime.unique_tickers:
        return
    resolved_rate, resolved_note, fx_messages = resolve_fx_rate_fn(
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


def _collect_market_data_from_kis(
    runtime: _SellRuntime,
    *,
    target_bars: int,
    load_json_fn: Any,
    save_json_fn: Any,
    ensure_pykrx_client_fn: Any,
    split_symbol_and_suffix_fn: Any,
    exchange_from_suffix_fn: Any,
) -> None:
    if runtime.kis_client is None:
        return

    for ticker in runtime.unique_tickers:
        base_symbol, suffix = split_symbol_and_suffix_fn(ticker)
        exchange = exchange_from_suffix_fn(suffix)
        cache_key = (
            f"candles_overseas_{exchange}_{base_symbol}"
            if exchange
            else f"candles_{base_symbol}"
        )
        cached = load_json_fn(runtime.cfg.data_dir, cache_key)
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
                save_json_fn(runtime.cfg.data_dir, cache_key, candles)
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

            fallback_client = ensure_pykrx_client_fn(runtime)
            fallback_error = runtime.pykrx_init_error
            if fallback_client is not None and not exchange:
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


def _collect_market_data_from_pykrx(
    runtime: _SellRuntime,
    *,
    target_bars: int,
    PykrxClientErrorCls: Any,
) -> None:
    if runtime.pykrx_client is None:
        return

    for ticker in runtime.unique_tickers:
        try:
            candles = runtime.pykrx_client.daily_candles(ticker, count=target_bars)
        except PykrxClientErrorCls as exc:
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


def _collect_market_data(
    runtime: _SellRuntime,
    *,
    target_bars: int,
    collect_market_data_from_kis_fn: Any,
    collect_market_data_from_pykrx_fn: Any,
) -> None:
    if runtime.cfg.data_provider == "kis" and runtime.kis_client:
        collect_market_data_from_kis_fn(runtime, target_bars=target_bars)
        return
    if runtime.cfg.data_provider == "pykrx" and runtime.pykrx_client:
        collect_market_data_from_pykrx_fn(runtime, target_bars=target_bars)
