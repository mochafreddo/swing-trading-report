from __future__ import annotations

import datetime as dt
from typing import Any

from .data.holiday_cache import HolidayEntry
from .data.kis_client import KISAuthError, KISClientError
from .data.pykrx_client import PykrxClientError, PykrxNotInstalledError
from .scan_types import _ScanRuntime


def _ensure_pykrx_client(
    runtime: _ScanRuntime,
    *,
    PykrxClientCls: Any,
) -> Any | None:
    if runtime.pykrx_client is not None:
        return runtime.pykrx_client
    if runtime.pykrx_import_error:
        return None
    try:
        runtime.pykrx_client = PykrxClientCls()
        runtime.logger.info("PyKRX client initialized for fallback/provider usage")
        return runtime.pykrx_client
    except PykrxNotInstalledError as exc:
        runtime.pykrx_import_error = str(exc)
        runtime.logger.warning("PyKRX unavailable: %s", exc)
    except PykrxClientError as exc:
        runtime.pykrx_import_error = str(exc)
        runtime.logger.error("PyKRX init failed: %s", exc)
    return None


def _initialize_provider(
    runtime: _ScanRuntime,
    *,
    screener_enabled: bool,
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

    if screener_enabled:
        msg = "Screener currently supports KIS provider only."
        runtime.failures.append(msg)
        runtime.logger.error(msg)
        runtime.fatal_failure = True


def _resolve_scan_fx(
    runtime: _ScanRuntime,
    *,
    resolve_fx_rate_fn: Any,
    infer_currency_fn: Any,
) -> None:
    runtime.ticker_currency = {
        ticker: infer_currency_fn(ticker) for ticker in runtime.tickers
    }
    resolved_rate, resolved_note, fx_messages = resolve_fx_rate_fn(
        cfg=runtime.cfg,
        ticker_currency=runtime.ticker_currency,
        tickers=runtime.tickers,
        kis_client=runtime.kis_client,
        logger=runtime.logger,
    )
    runtime.fx_rate = resolved_rate
    runtime.fx_meta_note = resolved_note
    if fx_messages:
        runtime.failures.extend(fx_messages)


def _refresh_us_holidays(
    runtime: _ScanRuntime,
    *,
    merge_holidays_fn: Any,
) -> dict[str, HolidayEntry]:
    if runtime.kis_client is None:
        return {}
    try:
        now = dt.datetime.now()
        start = now.strftime("%Y%m%d")
        end = (now + dt.timedelta(days=30)).strftime("%Y%m%d")
    except Exception:
        start = end = dt.date.today().strftime("%Y%m%d")

    runtime.logger.info("Refreshing US holidays via KIS: %s -> %s", start, end)
    try:
        items = runtime.kis_client.overseas_holidays(
            country_code="US",
            start_date=start,
            end_date=end,
        )
    except KISClientError as exc:
        message = str(exc)
        if "HTTP 404" in message:
            runtime.logger.info(
                "US holiday API returned 404 (no entries from %s to %s)", start, end
            )
            return {}
        runtime.logger.warning("Failed to refresh US holidays: %s", message)
        return {}

    runtime.logger.info(
        "US holiday API succeeded: %s rows for %s -> %s", len(items), start, end
    )
    if items:
        runtime.logger.debug("US holiday sample row: %s", items[0])
    return merge_holidays_fn(runtime.cfg.data_dir, "US", items)


def _collect_market_data_from_kis(
    runtime: _ScanRuntime,
    *,
    load_json_fn: Any,
    save_json_fn: Any,
    refresh_us_holidays_fn: Any,
    ensure_pykrx_client_fn: Any,
    split_overseas_fn: Any,
    excd_from_suffix_fn: Any,
) -> None:
    cfg = runtime.cfg
    if runtime.kis_client is None:
        return

    if "US" in cfg.universe_markets or any(
        currency.upper() == "USD" for currency in runtime.ticker_currency.values()
    ):
        runtime.us_holidays_cache = refresh_us_holidays_fn(runtime)

    for ticker in runtime.tickers:
        base_symbol, suffix = split_overseas_fn(ticker)
        exchange = excd_from_suffix_fn(suffix)
        cache_key = (
            f"candles_overseas_{exchange}_{base_symbol}"
            if exchange
            else f"candles_{ticker}"
        )
        cached = load_json_fn(cfg.data_dir, cache_key)
        if isinstance(cached, list) and cached:
            runtime.market_data[ticker] = cached
            runtime.ticker_data_source.setdefault(ticker, cfg.data_provider)
            last_date = str(cached[-1].get("date") or "")
            if last_date:
                runtime.latest_dates[ticker] = last_date

        try:
            if exchange:
                candles = runtime.kis_client.overseas_daily_candles(
                    symbol=base_symbol,
                    exchange=exchange,
                    count=max(cfg.min_history_bars, 200),
                )
            else:
                candles = runtime.kis_client.daily_candles(
                    base_symbol, count=max(cfg.min_history_bars, 200)
                )
            if candles:
                runtime.market_data[ticker] = candles
                runtime.ticker_data_source[ticker] = "kis"
                save_json_fn(cfg.data_dir, cache_key, candles)
                last_date = str(candles[-1].get("date") or "")
                if last_date:
                    runtime.latest_dates[ticker] = last_date
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
            fallback_error: str | None = None
            if fallback_client is not None and not exchange:
                try:
                    candles = fallback_client.daily_candles(
                        base_symbol, count=max(cfg.min_history_bars, 200)
                    )
                except PykrxClientError as py_exc:
                    fallback_client = None
                    fallback_error = str(py_exc)
                else:
                    if candles:
                        runtime.market_data[ticker] = candles
                        runtime.ticker_data_source[ticker] = "pykrx"
                        last_date = str(candles[-1].get("date") or "")
                        if last_date:
                            runtime.latest_dates[ticker] = last_date
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
            else:
                fallback_error = (
                    runtime.pykrx_import_error
                    if not exchange
                    else "Overseas symbol; no PyKRX fallback"
                )

            msg = f"{ticker}: {exc}"
            if fallback_client is None and fallback_error:
                msg += f" ({fallback_error})"
            runtime.failures.append(msg)
            runtime.logger.error(msg)


def _collect_market_data_from_pykrx(
    runtime: _ScanRuntime, *, PykrxClientErrorCls: Any
) -> None:
    if runtime.pykrx_client is None:
        return

    for ticker in runtime.tickers:
        try:
            candles = runtime.pykrx_client.daily_candles(
                ticker, count=max(runtime.cfg.min_history_bars, 200)
            )
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
            last_date = str(candles[-1].get("date") or "")
            if last_date:
                runtime.latest_dates[ticker] = last_date
        else:
            msg = f"{ticker}: PyKRX returned no data"
            runtime.failures.append(msg)
            runtime.logger.warning(msg)

    if runtime.tickers and not runtime.pykrx_warning_added:
        runtime.failures.append(
            "Warning: PyKRX provider data is end-of-day and may lag intraday feeds."
        )
        runtime.pykrx_warning_added = True


def _collect_market_data(
    runtime: _ScanRuntime,
    *,
    collect_market_data_from_kis_fn: Any,
    collect_market_data_from_pykrx_fn: Any,
) -> None:
    provider = runtime.cfg.data_provider
    if provider == "kis" and runtime.kis_client:
        collect_market_data_from_kis_fn(runtime)
        return
    if provider == "pykrx" and runtime.pykrx_client:
        collect_market_data_from_pykrx_fn(runtime)
        return
    if runtime.tickers:
        runtime.failures.append(f"Provider '{provider}' not yet implemented")
        runtime.fatal_failure = True
