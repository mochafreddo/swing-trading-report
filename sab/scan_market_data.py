from __future__ import annotations

import datetime as dt
from typing import Any

from .data.holiday_cache import HolidayEntry
from .data.kis_client import KISClientError
from .market_data_pipeline import collect_market_data as _collect_market_data_shared
from .market_data_pipeline import (
    collect_market_data_from_kis as _collect_market_data_from_kis_shared,
)
from .market_data_pipeline import (
    collect_market_data_from_pykrx as _collect_market_data_from_pykrx_shared,
)
from .market_data_pipeline import ensure_pykrx_client as _ensure_pykrx_client_shared
from .market_data_pipeline import initialize_provider as _initialize_provider_shared
from .scan_types import _ScanRuntime


def _ensure_pykrx_client(
    runtime: _ScanRuntime,
    *,
    PykrxClientCls: Any,
) -> Any | None:
    return _ensure_pykrx_client_shared(
        runtime,
        PykrxClientCls=PykrxClientCls,
        get_pykrx_error_fn=lambda state: state.pykrx_import_error,
        set_pykrx_error_fn=lambda state, message: setattr(
            state, "pykrx_import_error", message
        ),
        initialized_log_message="PyKRX client initialized for fallback/provider usage",
    )


def _initialize_provider(
    runtime: _ScanRuntime,
    *,
    screener_enabled: bool,
    KISCredentialsCls: Any,
    KISClientCls: Any,
    ensure_pykrx_client_fn: Any,
    infer_env_from_base_fn: Any,
) -> None:
    unsupported_msg = (
        "Screener currently supports KIS provider only." if screener_enabled else None
    )
    _initialize_provider_shared(
        runtime,
        KISCredentialsCls=KISCredentialsCls,
        KISClientCls=KISClientCls,
        ensure_pykrx_client_fn=ensure_pykrx_client_fn,
        infer_env_from_base_fn=infer_env_from_base_fn,
        unsupported_provider_message=unsupported_msg,
        mark_fatal_on_unsupported=screener_enabled,
    )


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


def _scan_legacy_cache_keys(
    ticker: str, base_symbol: str, exchange: str | None
) -> list[str]:
    legacy_key = f"candles_{ticker}"
    canonical_key = (
        f"candles_overseas_{exchange}_{base_symbol}"
        if exchange
        else f"candles_{base_symbol}"
    )
    if legacy_key == canonical_key:
        return []
    return [legacy_key]


def _update_latest_date(
    runtime: _ScanRuntime, ticker: str, candles: list[dict[str, Any]]
) -> None:
    last_date = str(candles[-1].get("date") or "") if candles else ""
    if last_date:
        runtime.latest_dates[ticker] = last_date


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
    _collect_market_data_from_kis_shared(
        runtime,
        tickers=runtime.tickers,
        target_bars=max(cfg.min_history_bars, 200),
        load_json_fn=load_json_fn,
        save_json_fn=save_json_fn,
        ensure_pykrx_client_fn=ensure_pykrx_client_fn,
        split_symbol_and_suffix_fn=split_overseas_fn,
        exchange_from_suffix_fn=excd_from_suffix_fn,
        get_pykrx_error_fn=lambda state: state.pykrx_import_error,
        legacy_cache_keys_fn=_scan_legacy_cache_keys,
        on_candles_applied_fn=_update_latest_date,
    )


def _collect_market_data_from_pykrx(
    runtime: _ScanRuntime, *, PykrxClientErrorCls: Any
) -> None:
    _collect_market_data_from_pykrx_shared(
        runtime,
        tickers=runtime.tickers,
        target_bars=max(runtime.cfg.min_history_bars, 200),
        PykrxClientErrorCls=PykrxClientErrorCls,
        on_candles_applied_fn=_update_latest_date,
    )


def _collect_market_data(
    runtime: _ScanRuntime,
    *,
    collect_market_data_from_kis_fn: Any,
    collect_market_data_from_pykrx_fn: Any,
) -> None:
    _collect_market_data_shared(
        runtime,
        tickers=runtime.tickers,
        collect_market_data_from_kis_fn=collect_market_data_from_kis_fn,
        collect_market_data_from_pykrx_fn=collect_market_data_from_pykrx_fn,
    )
