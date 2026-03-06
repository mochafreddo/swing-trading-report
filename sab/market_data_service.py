from __future__ import annotations

import datetime as dt
import os
from collections.abc import Callable

from . import market_data_pipeline
from .data.holiday_cache import HolidayEntry, load_cached_holidays, merge_holidays
from .data.kis_client import KISClientError
from .data.pykrx_client import PykrxClient
from .market_data_common import Candle, MarketDataDependencies
from .scan_types import _excd_from_suffix, _ScanRuntime, _split_overseas
from .sell_types import _exchange_from_suffix, _SellRuntime, _split_symbol_and_suffix

type _LegacyCacheKeysFn = Callable[[str, str, str | None], list[str]]
type _OnCandlesAppliedFn[TRuntime] = Callable[[TRuntime, str, list[Candle]], None]
type _BeforeKisCollectionFn[TRuntime] = Callable[[TRuntime], None]
type _PykrxClientKwargsFn[TRuntime] = Callable[[TRuntime], dict[str, str | None]]

_US_HOLIDAY_REFRESH_TTL = dt.timedelta(hours=12)
_US_HOLIDAY_REFRESH_WINDOW_DAYS = 10


def _current_utc_time() -> dt.datetime:
    return dt.datetime.now(dt.UTC)


def _holiday_cache_path(data_dir: str, market: str) -> str:
    return os.path.join(data_dir, f"holidays_{market.lower()}.json")


def _holiday_cache_age_hours(
    data_dir: str,
    market: str,
    *,
    now: dt.datetime,
) -> float | None:
    path = _holiday_cache_path(data_dir, market)
    try:
        mtime = os.path.getmtime(path)
    except OSError:
        return None
    return max(0.0, now.timestamp() - mtime) / 3600.0


def _format_cache_age_hours(age_hours: float | None) -> str:
    if age_hours is None:
        return "missing"
    return f"{age_hours:.2f}"


def scan_legacy_cache_keys(
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


class _BaseMarketDataService[TRuntime: market_data_pipeline._CollectionRuntime]:
    def __init__(self, *, deps: MarketDataDependencies) -> None:
        self._deps = deps

    def _initialize_provider(
        self,
        runtime: TRuntime,
        *,
        ensure_pykrx_client_fn: Callable[[TRuntime], PykrxClient | None],
        unsupported_provider_message: str | None,
        mark_fatal_on_unsupported: bool,
    ) -> None:
        market_data_pipeline.initialize_provider(
            runtime,
            KISCredentialsCls=self._deps.KISCredentialsCls,
            KISClientCls=self._deps.KISClientCls,
            ensure_pykrx_client_fn=ensure_pykrx_client_fn,
            infer_env_from_base_fn=self._deps.infer_env_from_base_fn,
            unsupported_provider_message=unsupported_provider_message,
            mark_fatal_on_unsupported=mark_fatal_on_unsupported,
        )

    def _ensure_pykrx_client(
        self,
        runtime: TRuntime,
        *,
        get_pykrx_error_fn: Callable[[TRuntime], str | None],
        set_pykrx_error_fn: Callable[[TRuntime, str], None],
        pykrx_client_kwargs_fn: _PykrxClientKwargsFn[TRuntime] | None = None,
        initialized_log_message: str,
    ) -> PykrxClient | None:
        return market_data_pipeline.ensure_pykrx_client(
            runtime,
            PykrxClientCls=self._deps.PykrxClientCls,
            get_pykrx_error_fn=get_pykrx_error_fn,
            set_pykrx_error_fn=set_pykrx_error_fn,
            pykrx_client_kwargs_fn=pykrx_client_kwargs_fn,
            initialized_log_message=initialized_log_message,
        )

    def _collect_from_kis(
        self,
        runtime: TRuntime,
        *,
        tickers: list[str],
        target_bars: int,
        adjusted: bool = True,
        split_symbol_and_suffix_fn: Callable[[str], tuple[str, str | None]],
        exchange_from_suffix_fn: Callable[[str | None], str | None],
        get_pykrx_error_fn: Callable[[TRuntime], str | None],
        ensure_pykrx_client_fn: Callable[[TRuntime], PykrxClient | None],
        legacy_cache_keys_fn: _LegacyCacheKeysFn | None = None,
        on_candles_applied_fn: _OnCandlesAppliedFn[TRuntime] | None = None,
        before_kis_collection_fn: _BeforeKisCollectionFn[TRuntime] | None = None,
    ) -> None:
        if before_kis_collection_fn is not None:
            before_kis_collection_fn(runtime)

        request = market_data_pipeline.KisCollectionRequest(
            tickers=tickers,
            target_bars=target_bars,
            load_json_fn=self._deps.load_json_fn,
            save_json_fn=self._deps.save_json_fn,
            ensure_pykrx_client_fn=ensure_pykrx_client_fn,
            split_symbol_and_suffix_fn=split_symbol_and_suffix_fn,
            exchange_from_suffix_fn=exchange_from_suffix_fn,
            get_pykrx_error_fn=get_pykrx_error_fn,
            adjusted=adjusted,
            legacy_cache_keys_fn=legacy_cache_keys_fn,
            on_candles_applied_fn=on_candles_applied_fn,
        )
        market_data_pipeline.collect_market_data_from_kis(
            runtime,
            request=request,
        )

    def _collect_from_pykrx(
        self,
        runtime: TRuntime,
        *,
        tickers: list[str],
        target_bars: int,
        adjusted: bool = True,
        on_candles_applied_fn: _OnCandlesAppliedFn[TRuntime] | None = None,
    ) -> None:
        request = market_data_pipeline.PykrxCollectionRequest(
            tickers=tickers,
            target_bars=target_bars,
            PykrxClientErrorCls=self._deps.PykrxClientErrorCls,
            adjusted=adjusted,
            on_candles_applied_fn=on_candles_applied_fn,
        )
        market_data_pipeline.collect_market_data_from_pykrx(
            runtime,
            request=request,
        )


class ScanMarketData(_BaseMarketDataService[_ScanRuntime]):
    def __init__(self, *, deps: MarketDataDependencies) -> None:
        super().__init__(deps=deps)
        self._provider_collectors: dict[
            str, Callable[[_ScanRuntime, list[str], int], None]
        ] = {
            "kis": self._collect_with_kis_provider,
            "pykrx": self._collect_with_pykrx_provider,
        }

    def initialize_provider(
        self, runtime: _ScanRuntime, *, screener_enabled: bool
    ) -> None:
        unsupported_msg = (
            "Screener currently supports KIS provider only."
            if screener_enabled
            else None
        )
        self._initialize_provider(
            runtime,
            ensure_pykrx_client_fn=self._ensure_scan_pykrx_client,
            unsupported_provider_message=unsupported_msg,
            mark_fatal_on_unsupported=screener_enabled,
        )

    def collect_market_data(self, runtime: _ScanRuntime) -> None:
        target_bars = max(runtime.cfg.min_history_bars, 200)
        tickers = list(runtime.tickers)
        provider = runtime.cfg.data_provider
        collector = self._provider_collectors.get(provider)
        if collector is None:
            if tickers:
                runtime.failures.append(f"Provider '{provider}' not yet implemented")
                runtime.fatal_failure = True
            return
        collector(runtime, tickers, target_bars)

    def _collect_with_kis_provider(
        self,
        runtime: _ScanRuntime,
        tickers: list[str],
        target_bars: int,
    ) -> None:
        if not runtime.kis_client:
            if tickers:
                runtime.failures.append("KIS provider is not initialized")
                runtime.fatal_failure = True
            return
        self._collect_from_kis(
            runtime,
            tickers=tickers,
            target_bars=target_bars,
            adjusted=True,
            split_symbol_and_suffix_fn=_split_overseas,
            exchange_from_suffix_fn=_excd_from_suffix,
            get_pykrx_error_fn=lambda state: state.pykrx_import_error,
            ensure_pykrx_client_fn=self._ensure_scan_pykrx_client,
            legacy_cache_keys_fn=scan_legacy_cache_keys,
            on_candles_applied_fn=self._update_latest_date,
            before_kis_collection_fn=self._refresh_us_holidays_if_needed,
        )

    def _collect_with_pykrx_provider(
        self,
        runtime: _ScanRuntime,
        tickers: list[str],
        target_bars: int,
    ) -> None:
        if not runtime.pykrx_client:
            if tickers:
                runtime.failures.append("PyKRX provider is not initialized")
                runtime.fatal_failure = True
            return
        self._collect_from_pykrx(
            runtime,
            tickers=tickers,
            target_bars=target_bars,
            adjusted=True,
            on_candles_applied_fn=self._update_latest_date,
        )

    def _ensure_scan_pykrx_client(
        self,
        runtime: _ScanRuntime,
    ) -> PykrxClient | None:
        return self._ensure_pykrx_client(
            runtime,
            get_pykrx_error_fn=lambda state: state.pykrx_import_error,
            set_pykrx_error_fn=lambda state, message: setattr(
                state, "pykrx_import_error", message
            ),
            initialized_log_message="PyKRX client initialized for fallback/provider usage",
        )

    def _refresh_us_holidays(self, runtime: _ScanRuntime) -> dict[str, HolidayEntry]:
        if runtime.kis_client is None:
            return {}
        now = _current_utc_time()
        age_hours = _holiday_cache_age_hours(runtime.cfg.data_dir, "US", now=now)
        try:
            start = now.strftime("%Y%m%d")
            end = (now + dt.timedelta(days=_US_HOLIDAY_REFRESH_WINDOW_DAYS)).strftime(
                "%Y%m%d"
            )
        except Exception:
            start = end = dt.date.today().strftime("%Y%m%d")

        runtime.logger.info(
            "Refreshing US holidays via KIS: %s -> %s (holiday_refresh_age_hours=%s, holiday_refresh_window_days=%s)",
            start,
            end,
            _format_cache_age_hours(age_hours),
            _US_HOLIDAY_REFRESH_WINDOW_DAYS,
        )
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
                    "US holiday API returned 404 (no entries from %s to %s)",
                    start,
                    end,
                )
                return {}
            runtime.logger.warning("Failed to refresh US holidays: %s", message)
            return {}

        runtime.logger.info(
            "US holiday API succeeded: %s rows for %s -> %s", len(items), start, end
        )
        if items:
            runtime.logger.debug("US holiday sample row: %s", items[0])
        return merge_holidays(runtime.cfg.data_dir, "US", items)

    def _refresh_us_holidays_if_needed(self, runtime: _ScanRuntime) -> None:
        if runtime.kis_client is None:
            return
        if "US" in runtime.cfg.universe_markets or any(
            currency.upper() == "USD" for currency in runtime.ticker_currency.values()
        ):
            now = _current_utc_time()
            age_hours = _holiday_cache_age_hours(runtime.cfg.data_dir, "US", now=now)
            ttl_hours = _US_HOLIDAY_REFRESH_TTL.total_seconds() / 3600.0
            cached_holidays = load_cached_holidays(runtime.cfg.data_dir, "US")
            if age_hours is not None and age_hours <= ttl_hours and cached_holidays:
                runtime.us_holidays_cache = cached_holidays
                runtime.logger.info(
                    "Skipping US holiday refresh (holiday_refresh_skipped=true, holiday_refresh_age_hours=%s, holiday_refresh_window_days=%s)",
                    _format_cache_age_hours(age_hours),
                    _US_HOLIDAY_REFRESH_WINDOW_DAYS,
                )
                return

            runtime.us_holidays_cache = self._refresh_us_holidays(runtime)
            if not runtime.us_holidays_cache:
                runtime.us_holidays_cache = cached_holidays

    @staticmethod
    def _update_latest_date(
        runtime: _ScanRuntime,
        ticker: str,
        candles: list[Candle],
    ) -> None:
        last_date = str(candles[-1].get("date") or "") if candles else ""
        if last_date:
            runtime.latest_dates[ticker] = last_date


class SellMarketData(_BaseMarketDataService[_SellRuntime]):
    def __init__(self, *, deps: MarketDataDependencies) -> None:
        super().__init__(deps=deps)
        self._provider_collectors: dict[
            str, Callable[[_SellRuntime, list[str], int], None]
        ] = {
            "kis": self._collect_with_kis_provider,
            "pykrx": self._collect_with_pykrx_provider,
        }

    def initialize_provider(self, runtime: _SellRuntime) -> None:
        self._initialize_provider(
            runtime,
            ensure_pykrx_client_fn=self._ensure_sell_pykrx_client,
            unsupported_provider_message="Provider '{provider}' not supported for sell command",
            mark_fatal_on_unsupported=True,
        )

    def collect_market_data(self, runtime: _SellRuntime, *, target_bars: int) -> None:
        tickers = list(runtime.unique_tickers)
        provider = runtime.cfg.data_provider
        collector = self._provider_collectors.get(provider)
        if collector is None:
            if tickers:
                runtime.failures.append(
                    f"Provider '{provider}' not supported for sell command"
                )
                runtime.fatal_failure = True
            return
        collector(runtime, tickers, target_bars)

    def _collect_with_kis_provider(
        self,
        runtime: _SellRuntime,
        tickers: list[str],
        target_bars: int,
    ) -> None:
        if not runtime.kis_client:
            if tickers:
                runtime.failures.append("KIS provider is not initialized")
                runtime.fatal_failure = True
            return
        self._collect_from_kis(
            runtime,
            tickers=tickers,
            target_bars=target_bars,
            adjusted=False,
            split_symbol_and_suffix_fn=_split_symbol_and_suffix,
            exchange_from_suffix_fn=_exchange_from_suffix,
            get_pykrx_error_fn=lambda state: state.pykrx_init_error,
            ensure_pykrx_client_fn=self._ensure_sell_pykrx_client,
        )

    def _collect_with_pykrx_provider(
        self,
        runtime: _SellRuntime,
        tickers: list[str],
        target_bars: int,
    ) -> None:
        if not runtime.pykrx_client:
            if tickers:
                runtime.failures.append("PyKRX provider is not initialized")
                runtime.fatal_failure = True
            return
        self._collect_from_pykrx(
            runtime,
            tickers=tickers,
            target_bars=target_bars,
            adjusted=False,
        )

    def _ensure_sell_pykrx_client(
        self,
        runtime: _SellRuntime,
    ) -> PykrxClient | None:
        return self._ensure_pykrx_client(
            runtime,
            get_pykrx_error_fn=lambda state: state.pykrx_init_error,
            set_pykrx_error_fn=lambda state, message: setattr(
                state, "pykrx_init_error", message
            ),
            pykrx_client_kwargs_fn=lambda state: {"cache_dir": state.cfg.data_dir},
            initialized_log_message="PyKRX client initialized",
        )


__all__ = [
    "ScanMarketData",
    "SellMarketData",
    "scan_legacy_cache_keys",
]
