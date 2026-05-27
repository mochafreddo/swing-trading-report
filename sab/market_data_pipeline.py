from __future__ import annotations

import datetime as dt
import logging
import math
from collections.abc import Callable
from dataclasses import dataclass
from typing import Protocol
from zoneinfo import ZoneInfo

from .data.holiday_cache import load_cached_holidays
from .data.kis_client import KISAuthError, KISClient, KISClientError, KISCredentials
from .data.kr_calendar import load_kr_trading_calendar
from .data.pykrx_client import (
    PykrxClient,
    PykrxClientError,
    PykrxNotInstalledError,
)
from .data.us_calendar import load_us_trading_calendar
from .fx import SUFFIX_TO_EXCD
from .market_data_common import Candle
from .utils.market_time import us_early_close_time

type _LegacyCacheKeysFn = Callable[[str, str, str | None], list[str]]


class _CollectionConfig(Protocol):
    @property
    def data_dir(self) -> str: ...

    @property
    def data_provider(self) -> str: ...

    @property
    def market_cache_stale_sessions_kr(self) -> int: ...

    @property
    def market_cache_stale_sessions_us(self) -> int: ...

    @property
    def kis_app_key(self) -> str | None: ...

    @property
    def kis_app_secret(self) -> str | None: ...

    @property
    def kis_base_url(self) -> str | None: ...

    @property
    def kis_min_interval_ms(self) -> float | None: ...


class _CollectionRuntime(Protocol):
    @property
    def cfg(self) -> _CollectionConfig: ...

    @property
    def logger(self) -> logging.Logger: ...

    failures: list[str]
    fatal_failure: bool
    market_data: dict[str, list[Candle]]
    ticker_data_source: dict[str, str]
    pykrx_warning_added: bool
    kis_client: KISClient | None
    pykrx_client: PykrxClient | None
    cache_hint: str | None


type _OnCandlesAppliedFn[TRuntime: _CollectionRuntime] = Callable[
    [TRuntime, str, list[Candle]], None
]


class _CacheAwareRequest[TRuntime: _CollectionRuntime](Protocol):
    @property
    def save_json_fn(self) -> Callable[[str, str, list[Candle]], object]: ...

    @property
    def on_candles_applied_fn(self) -> _OnCandlesAppliedFn[TRuntime] | None: ...


@dataclass(frozen=True)
class _TickerTarget:
    ticker: str
    base_symbol: str
    exchange: str | None
    cache_key: str
    legacy_cache_keys: tuple[str, ...]


@dataclass(frozen=True)
class _CacheLookupResult:
    candles: list[Candle] | None
    cache_key: str | None
    market: str
    max_stale_sessions: int
    usable: bool = False
    stale_sessions: int | None = None
    rejection_reason: str | None = None

    @property
    def is_fresh(self) -> bool:
        return self.usable and (self.stale_sessions or 0) == 0

    @property
    def fallback_allowed(self) -> bool:
        return (
            self.usable and self.candles is not None and (self.stale_sessions or 0) > 0
        )


@dataclass(frozen=True)
class _ProviderCandleResult:
    candles: list[Candle]
    had_response: bool
    rejection_reason: str | None = None

    @property
    def fresh(self) -> bool:
        return bool(self.candles) and self.rejection_reason is None


@dataclass(frozen=True)
class KisCollectionRequest[TRuntime: _CollectionRuntime]:
    tickers: list[str]
    target_bars: int
    load_json_fn: Callable[[str, str], list[Candle] | None]
    save_json_fn: Callable[[str, str, list[Candle]], object]
    ensure_pykrx_client_fn: Callable[[TRuntime], PykrxClient | None]
    split_symbol_and_suffix_fn: Callable[[str], tuple[str, str | None]]
    exchange_from_suffix_fn: Callable[[str | None], str | None]
    get_pykrx_error_fn: Callable[[TRuntime], str | None]
    adjusted: bool = True
    legacy_cache_keys_fn: _LegacyCacheKeysFn | None = None
    on_candles_applied_fn: _OnCandlesAppliedFn[TRuntime] | None = None


@dataclass(frozen=True)
class PykrxCollectionRequest[TRuntime: _CollectionRuntime]:
    tickers: list[str]
    target_bars: int
    load_json_fn: Callable[[str, str], list[Candle] | None]
    save_json_fn: Callable[[str, str, list[Candle]], object]
    split_symbol_and_suffix_fn: Callable[[str], tuple[str, str | None]]
    exchange_from_suffix_fn: Callable[[str | None], str | None]
    PykrxClientErrorCls: type[Exception]
    adjusted: bool = True
    legacy_cache_keys_fn: _LegacyCacheKeysFn | None = None
    on_candles_applied_fn: _OnCandlesAppliedFn[TRuntime] | None = None


_NORMALIZED_SUFFIX_TO_EXCD = {
    "".join(ch for ch in key.upper() if ch.isalnum()): value
    for key, value in SUFFIX_TO_EXCD.items()
}
_KR_ZONE = ZoneInfo("Asia/Seoul")
_US_ZONE = ZoneInfo("America/New_York")
_MAX_SESSION_LOOKBACK_DAYS = 3700
_REQUIRED_CANDLE_FIELDS = ("open", "high", "low", "close", "volume")


def _canonical_split_symbol_and_suffix(ticker: str) -> tuple[str, str | None]:
    if "." not in ticker:
        return ticker.strip().upper(), None
    base, suffix = ticker.rsplit(".", 1)
    base_symbol = base.strip().upper()
    suffix_symbol = suffix.strip().upper()
    return base_symbol, suffix_symbol or None


def _canonical_exchange_from_suffix(suffix: str | None) -> str | None:
    if not suffix:
        return None
    norm = "".join(ch for ch in suffix.upper() if ch.isalnum())
    return _NORMALIZED_SUFFIX_TO_EXCD.get(norm)


def _build_cache_key(base_symbol: str, exchange: str | None, *, adjusted: bool) -> str:
    adjusted_prefix = "adj" if adjusted else "raw"
    if exchange:
        return f"candles_overseas_{adjusted_prefix}_{exchange}_{base_symbol}"
    return f"candles_{adjusted_prefix}_{base_symbol}"


def _ensure_aware_now(now: dt.datetime | None) -> dt.datetime:
    if now is None:
        return dt.datetime.now(dt.UTC)
    if now.tzinfo is None:
        return now.replace(tzinfo=dt.UTC)
    return now


def _parse_session_date(value: object) -> dt.date | None:
    text = str(value or "").strip().replace("-", "")
    if len(text) != 8 or not text.isdigit():
        return None
    try:
        return dt.datetime.strptime(text, "%Y%m%d").date()
    except ValueError:
        return None


def _market_from_exchange(exchange: str | None) -> str:
    return "US" if exchange else "KR"


def _load_market_holiday_dates(data_dir: str, market: str) -> set[dt.date]:
    base_holidays: dict[str, str]
    if market == "US":
        base_holidays = load_us_trading_calendar(data_dir)
    else:
        base_holidays = load_kr_trading_calendar(data_dir)

    closed_dates: set[dt.date] = set()
    for date_key in base_holidays:
        parsed = _parse_session_date(date_key)
        if parsed is not None:
            closed_dates.add(parsed)

    for date_key, entry in load_cached_holidays(data_dir, market).items():
        parsed = _parse_session_date(date_key)
        if parsed is None:
            continue
        if entry.is_open:
            closed_dates.discard(parsed)
        else:
            closed_dates.add(parsed)
    return closed_dates


def _is_trading_session(date_obj: dt.date, *, closed_dates: set[dt.date]) -> bool:
    if date_obj.weekday() >= 5:
        return False
    return date_obj not in closed_dates


def _find_previous_trading_session(
    start_date: dt.date, *, closed_dates: set[dt.date]
) -> dt.date | None:
    cursor = start_date
    for _ in range(_MAX_SESSION_LOOKBACK_DAYS):
        if _is_trading_session(cursor, closed_dates=closed_dates):
            return cursor
        cursor -= dt.timedelta(days=1)
    return None


def _latest_completed_session_date(
    *,
    market: str,
    now: dt.datetime,
    closed_dates: set[dt.date],
    data_dir: str | None = None,
) -> dt.date | None:
    zone = _US_ZONE if market == "US" else _KR_ZONE
    local_now = now.astimezone(zone)
    session_date = local_now.date()
    if market == "US":
        close_time = us_early_close_time(session_date, data_dir=data_dir) or dt.time(
            16, 0
        )
    else:
        close_time = dt.time(15, 30)

    if _is_trading_session(session_date, closed_dates=closed_dates):
        if local_now.time() >= close_time:
            return session_date
        return _find_previous_trading_session(
            session_date - dt.timedelta(days=1),
            closed_dates=closed_dates,
        )
    return _find_previous_trading_session(
        session_date - dt.timedelta(days=1),
        closed_dates=closed_dates,
    )


def _count_missing_sessions(
    *,
    latest_candle_date: dt.date,
    latest_completed_session: dt.date,
    closed_dates: set[dt.date],
) -> int:
    if latest_candle_date >= latest_completed_session:
        return 0
    missing = 0
    cursor = latest_candle_date + dt.timedelta(days=1)
    while cursor <= latest_completed_session:
        if _is_trading_session(cursor, closed_dates=closed_dates):
            missing += 1
        cursor += dt.timedelta(days=1)
    return missing


def _resolve_market_stale_limit(cfg: _CollectionConfig, *, market: str) -> int:
    raw = (
        cfg.market_cache_stale_sessions_us
        if market == "US"
        else cfg.market_cache_stale_sessions_kr
    )
    try:
        return max(0, int(raw))
    except TypeError, ValueError:
        return 0


def _evaluate_cache_staleness(
    *,
    candles: list[Candle],
    market: str,
    max_stale_sessions: int,
    closed_dates: set[dt.date],
    now: dt.datetime,
    data_dir: str | None = None,
) -> tuple[bool, int | None, str | None]:
    latest_raw = candles[-1].get("date") if candles else None
    latest_candle_date = _parse_session_date(latest_raw)
    if latest_candle_date is None:
        return (
            False,
            None,
            f"latest candle date is invalid ({latest_raw!r})",
        )

    latest_completed = _latest_completed_session_date(
        market=market,
        now=now,
        closed_dates=closed_dates,
        data_dir=None if market != "US" else data_dir,
    )
    if latest_completed is None:
        return True, 0, None

    stale_sessions = _count_missing_sessions(
        latest_candle_date=latest_candle_date,
        latest_completed_session=latest_completed,
        closed_dates=closed_dates,
    )
    if stale_sessions > max_stale_sessions:
        return (
            False,
            stale_sessions,
            f"stale by {stale_sessions} {market} sessions (max {max_stale_sessions})",
        )
    return True, stale_sessions, None


def _resolve_ticker_target(
    ticker: str,
    *,
    adjusted: bool,
    split_symbol_and_suffix_fn: Callable[[str], tuple[str, str | None]],
    exchange_from_suffix_fn: Callable[[str | None], str | None],
    legacy_cache_keys_fn: _LegacyCacheKeysFn | None = None,
) -> _TickerTarget:
    base_symbol, suffix = split_symbol_and_suffix_fn(ticker)
    canonical_base_symbol, canonical_suffix = _canonical_split_symbol_and_suffix(ticker)
    base_symbol = (base_symbol or "").strip().upper() or canonical_base_symbol
    suffix = (suffix or "").strip().upper() or canonical_suffix
    exchange = exchange_from_suffix_fn(suffix)
    if exchange is None:
        exchange = _canonical_exchange_from_suffix(suffix)
    elif isinstance(exchange, str):
        exchange = exchange.strip().upper() or None
    cache_key = _build_cache_key(base_symbol, exchange, adjusted=adjusted)
    legacy_cache_keys: tuple[str, ...] = ()
    if legacy_cache_keys_fn is not None:
        legacy_cache_keys = tuple(
            legacy_cache_keys_fn(ticker, base_symbol, exchange) or ()
        )
    return _TickerTarget(
        ticker=ticker,
        base_symbol=base_symbol,
        exchange=exchange,
        cache_key=cache_key,
        legacy_cache_keys=legacy_cache_keys,
    )


def _append_pykrx_warning_once(runtime: _CollectionRuntime, message: str) -> None:
    if runtime.pykrx_warning_added:
        return
    runtime.failures.append(message)
    runtime.pykrx_warning_added = True


def _is_adjusted_kwarg_type_error(exc: TypeError) -> bool:
    message = str(exc)
    return "unexpected keyword argument" in message and "adjusted" in message


def _daily_candles_with_optional_adjusted(
    client: KISClient | PykrxClient,
    symbol: str,
    *,
    count: int,
    adjusted: bool,
) -> list[Candle]:
    try:
        return client.daily_candles(symbol, count=count, adjusted=adjusted)
    except TypeError as type_exc:
        if not _is_adjusted_kwarg_type_error(type_exc):
            raise
        # Backward compatibility for stub/test clients that do not yet
        # expose the adjusted kwarg.
        return client.daily_candles(symbol, count=count)


def _trim_incomplete_candle_tail(
    candles: list[Candle],
    *,
    market: str,
    now: dt.datetime,
    closed_dates: set[dt.date],
    data_dir: str | None = None,
) -> tuple[list[Candle], int]:
    if not candles:
        return [], 0
    latest_completed = _latest_completed_session_date(
        market=market,
        now=now,
        closed_dates=closed_dates,
        data_dir=None if market != "US" else data_dir,
    )
    if latest_completed is None:
        return list(candles), 0

    trimmed = list(candles)
    removed_count = 0
    while trimmed:
        latest_raw = trimmed[-1].get("date")
        latest_date = _parse_session_date(latest_raw)
        if latest_date is None or latest_date <= latest_completed:
            break
        trimmed.pop()
        removed_count += 1
    return trimmed, removed_count


def _parse_finite_float(value: object) -> float | None:
    if isinstance(value, bool):
        return None
    if not isinstance(value, (int, float, str)):
        return None
    try:
        parsed = float(value)
    except TypeError, ValueError:
        return None
    if not math.isfinite(parsed):
        return None
    return parsed


def _sanitize_finite_candles(candles: list[Candle]) -> tuple[list[Candle], int]:
    sanitized: list[Candle] = []
    removed_count = 0

    for candle in candles:
        parsed_date = _parse_session_date(candle.get("date"))
        if parsed_date is None:
            removed_count += 1
            continue

        normalized_candle = dict(candle)
        normalized_candle["date"] = parsed_date.strftime("%Y%m%d")

        valid = True
        for field in _REQUIRED_CANDLE_FIELDS:
            parsed_value = _parse_finite_float(candle.get(field))
            if parsed_value is None:
                valid = False
                break
            normalized_candle[field] = parsed_value

        if not valid:
            removed_count += 1
            continue

        sanitized.append(normalized_candle)

    return sanitized, removed_count


def _load_cached_candles(
    runtime: _CollectionRuntime,
    *,
    ticker: str,
    cache_keys: tuple[str, ...],
    market: str,
    now: dt.datetime,
    closed_dates: set[dt.date],
    load_json_fn: Callable[[str, str], list[Candle] | None],
    save_json_fn: Callable[[str, str, list[Candle]], object],
) -> tuple[list[Candle] | None, str | None]:
    for cache_key in cache_keys:
        candidate = load_json_fn(runtime.cfg.data_dir, cache_key)
        if not (isinstance(candidate, list) and candidate):
            continue

        normalized_candidate, dropped_tail = _trim_incomplete_candle_tail(
            candidate,
            market=market,
            now=now,
            closed_dates=closed_dates,
            data_dir=runtime.cfg.data_dir,
        )
        normalized_candidate, dropped_invalid = _sanitize_finite_candles(
            normalized_candidate
        )
        if dropped_tail > 0:
            runtime.logger.info(
                "%s: Trimmed %s incomplete candle(s) from cache '%s'",
                ticker,
                dropped_tail,
                cache_key,
            )
        if dropped_invalid > 0:
            runtime.logger.warning(
                "%s: Dropped %s invalid candle(s) from cache '%s'",
                ticker,
                dropped_invalid,
                cache_key,
            )
        if dropped_tail > 0 or dropped_invalid > 0:
            try:
                save_json_fn(runtime.cfg.data_dir, cache_key, normalized_candidate)
            except Exception as exc:
                cache_msg = (
                    f"{ticker}: Failed to persist sanitized cache "
                    f"'{cache_key}' ({type(exc).__name__}: {exc})"
                )
                runtime.failures.append(cache_msg)
                runtime.logger.warning(cache_msg)
        if normalized_candidate:
            return normalized_candidate, cache_key
    return None, None


def _normalize_provider_candles(
    runtime: _CollectionRuntime,
    *,
    ticker: str,
    candles: list[Candle],
    market: str,
    now: dt.datetime,
    closed_dates: set[dt.date],
    source_label: str,
) -> list[Candle]:
    normalized_candles, dropped_tail = _trim_incomplete_candle_tail(
        candles,
        market=market,
        now=now,
        closed_dates=closed_dates,
        data_dir=runtime.cfg.data_dir,
    )
    normalized_candles, dropped_invalid = _sanitize_finite_candles(normalized_candles)
    if dropped_tail > 0:
        runtime.logger.info(
            "%s: Trimmed %s incomplete candle(s) from %s",
            ticker,
            dropped_tail,
            source_label,
        )
    if dropped_invalid > 0:
        runtime.logger.warning(
            "%s: Dropped %s invalid candle(s) from %s",
            ticker,
            dropped_invalid,
            source_label,
        )
    return normalized_candles


def _evaluate_provider_freshness(
    *,
    candles: list[Candle],
    market: str,
    closed_dates: set[dt.date],
    now: dt.datetime,
    data_dir: str | None = None,
) -> str | None:
    provider_fresh, _stale_sessions, rejection_reason = _evaluate_cache_staleness(
        candles=candles,
        market=market,
        max_stale_sessions=0,
        closed_dates=closed_dates,
        now=now,
        data_dir=data_dir,
    )
    if provider_fresh:
        return None
    return rejection_reason or "provider response is stale"


def _apply_cached_candles[TRuntime: _CollectionRuntime](
    runtime: TRuntime,
    *,
    ticker: str,
    candles: list[Candle] | None,
    request: _CacheAwareRequest[TRuntime],
    cached_key: str | None,
    target_cache_key: str,
    market: str,
    stale_sessions: int | None,
    max_stale_sessions: int,
) -> None:
    if not candles:
        return

    runtime.market_data[ticker] = candles
    runtime.ticker_data_source.setdefault(ticker, runtime.cfg.data_provider)
    if request.on_candles_applied_fn:
        request.on_candles_applied_fn(runtime, ticker, candles)

    if cached_key and cached_key != target_cache_key:
        try:
            request.save_json_fn(runtime.cfg.data_dir, target_cache_key, candles)
        except Exception as exc:
            migration_msg = (
                f"{ticker}: Failed to migrate cache key "
                f"'{cached_key}' -> '{target_cache_key}' ({exc})"
            )
            runtime.failures.append(migration_msg)
            runtime.logger.warning(migration_msg)

    runtime.logger.info(
        "Using cached candles for %s (market=%s, stale=%s/%s sessions)",
        ticker,
        market,
        stale_sessions or 0,
        max_stale_sessions,
    )


def _lookup_cached_candles(
    runtime: _CollectionRuntime,
    *,
    ticker: str,
    cache_keys: tuple[str, ...],
    market: str,
    max_stale_sessions: int,
    now: dt.datetime,
    closed_dates: set[dt.date],
    load_json_fn: Callable[[str, str], list[Candle] | None],
    save_json_fn: Callable[[str, str, list[Candle]], object],
) -> _CacheLookupResult:
    cached, cached_key = _load_cached_candles(
        runtime,
        ticker=ticker,
        cache_keys=cache_keys,
        market=market,
        now=now,
        closed_dates=closed_dates,
        load_json_fn=load_json_fn,
        save_json_fn=save_json_fn,
    )
    if not cached:
        return _CacheLookupResult(
            candles=None,
            cache_key=None,
            market=market,
            max_stale_sessions=max_stale_sessions,
        )

    cache_usable, stale_sessions, rejection_reason = _evaluate_cache_staleness(
        candles=cached,
        market=market,
        max_stale_sessions=max_stale_sessions,
        closed_dates=closed_dates,
        now=now,
        data_dir=runtime.cfg.data_dir,
    )
    return _CacheLookupResult(
        candles=cached,
        cache_key=cached_key,
        market=market,
        max_stale_sessions=max_stale_sessions,
        usable=cache_usable,
        stale_sessions=stale_sessions,
        rejection_reason=rejection_reason,
    )


def _apply_fresh_cache_if_available[TRuntime: _CollectionRuntime](
    runtime: TRuntime,
    *,
    ticker: str,
    request: _CacheAwareRequest[TRuntime],
    cache: _CacheLookupResult,
    target_cache_key: str,
) -> bool:
    if not cache.is_fresh:
        return False
    _apply_cached_candles(
        runtime,
        ticker=ticker,
        candles=cache.candles,
        request=request,
        cached_key=cache.cache_key,
        target_cache_key=target_cache_key,
        market=cache.market,
        stale_sessions=cache.stale_sessions,
        max_stale_sessions=cache.max_stale_sessions,
    )
    return True


def _apply_stale_cache_fallback[TRuntime: _CollectionRuntime](
    runtime: TRuntime,
    *,
    ticker: str,
    request: _CacheAwareRequest[TRuntime],
    cache: _CacheLookupResult,
    target_cache_key: str,
    warning_message: str,
    warning_args: tuple[object, ...] = (),
) -> bool:
    if not cache.fallback_allowed:
        return False
    _apply_cached_candles(
        runtime,
        ticker=ticker,
        candles=cache.candles,
        request=request,
        cached_key=cache.cache_key,
        target_cache_key=target_cache_key,
        market=cache.market,
        stale_sessions=cache.stale_sessions,
        max_stale_sessions=cache.max_stale_sessions,
    )
    runtime.logger.warning(warning_message, ticker, *warning_args)
    return True


def _message_with_cache_rejection(
    message: str,
    *,
    cache: _CacheLookupResult,
) -> str:
    if cache.rejection_reason:
        return f"{message} (cache unavailable: {cache.rejection_reason})"
    return message


def _record_provider_failure(
    runtime: _CollectionRuntime,
    *,
    message: str,
    cache: _CacheLookupResult,
    log_as_error: bool = False,
) -> None:
    full_message = _message_with_cache_rejection(message, cache=cache)
    runtime.failures.append(full_message)
    if log_as_error:
        runtime.logger.error(full_message)
    else:
        runtime.logger.warning(full_message)


def _handle_provider_rejection[TRuntime: _CollectionRuntime](
    runtime: TRuntime,
    *,
    ticker: str,
    request: _CacheAwareRequest[TRuntime],
    cache: _CacheLookupResult,
    target_cache_key: str,
    warning_message: str,
    failure_message: str,
    warning_args: tuple[object, ...] = (),
    log_failure_as_error: bool = False,
) -> None:
    if _apply_stale_cache_fallback(
        runtime,
        ticker=ticker,
        request=request,
        cache=cache,
        target_cache_key=target_cache_key,
        warning_message=warning_message,
        warning_args=warning_args,
    ):
        return
    _record_provider_failure(
        runtime,
        message=failure_message,
        cache=cache,
        log_as_error=log_failure_as_error,
    )


def _normalize_provider_result(
    runtime: _CollectionRuntime,
    *,
    ticker: str,
    candles: list[Candle] | None,
    market: str,
    now: dt.datetime,
    closed_dates: set[dt.date],
    source_label: str,
) -> _ProviderCandleResult:
    if not candles:
        return _ProviderCandleResult(candles=[], had_response=False)

    normalized_candles = _normalize_provider_candles(
        runtime,
        ticker=ticker,
        candles=candles,
        market=market,
        now=now,
        closed_dates=closed_dates,
        source_label=source_label,
    )
    if not normalized_candles:
        return _ProviderCandleResult(candles=[], had_response=True)

    provider_rejection_reason = _evaluate_provider_freshness(
        candles=normalized_candles,
        market=market,
        closed_dates=closed_dates,
        now=now,
        data_dir=runtime.cfg.data_dir,
    )
    return _ProviderCandleResult(
        candles=normalized_candles,
        had_response=True,
        rejection_reason=provider_rejection_reason,
    )


def _apply_provider_candles[TRuntime: _CollectionRuntime](
    runtime: TRuntime,
    *,
    ticker: str,
    candles: list[Candle],
    request: _CacheAwareRequest[TRuntime],
    target_cache_key: str,
    source: str,
    persist_source_label: str,
    fetched_log_message: str,
) -> None:
    runtime.market_data[ticker] = candles
    runtime.ticker_data_source[ticker] = source
    try:
        request.save_json_fn(runtime.cfg.data_dir, target_cache_key, candles)
    except Exception as exc:
        cache_msg = (
            f"{ticker}: Failed to persist cache '{target_cache_key}' "
            f"after successful {persist_source_label} fetch ({type(exc).__name__}: {exc})"
        )
        runtime.failures.append(cache_msg)
        runtime.logger.warning(cache_msg)
    if request.on_candles_applied_fn:
        request.on_candles_applied_fn(runtime, ticker, candles)
    runtime.logger.info(fetched_log_message, len(candles), ticker)


def ensure_pykrx_client[TRuntime: _CollectionRuntime](
    runtime: TRuntime,
    *,
    PykrxClientCls: type[PykrxClient],
    get_pykrx_error_fn: Callable[[TRuntime], str | None],
    set_pykrx_error_fn: Callable[[TRuntime, str], None],
    pykrx_client_kwargs_fn: Callable[[TRuntime], dict[str, str | None]] | None = None,
    initialized_log_message: str,
) -> PykrxClient | None:
    if runtime.pykrx_client is not None:
        return runtime.pykrx_client
    if get_pykrx_error_fn(runtime):
        return None

    kwargs = pykrx_client_kwargs_fn(runtime) if pykrx_client_kwargs_fn else {}
    cache_dir = kwargs.get("cache_dir")
    try:
        runtime.pykrx_client = PykrxClientCls(cache_dir=cache_dir)
        runtime.logger.info(initialized_log_message)
        return runtime.pykrx_client
    except PykrxNotInstalledError as exc:
        set_pykrx_error_fn(runtime, str(exc))
        runtime.logger.warning("PyKRX unavailable: %s", exc)
    except PykrxClientError as exc:
        set_pykrx_error_fn(runtime, str(exc))
        runtime.logger.error("PyKRX init failed: %s", exc)
    return None


def initialize_provider[TRuntime: _CollectionRuntime](
    runtime: TRuntime,
    *,
    KISCredentialsCls: type[KISCredentials],
    KISClientCls: type[KISClient],
    ensure_pykrx_client_fn: Callable[[TRuntime], PykrxClient | None],
    infer_env_from_base_fn: Callable[[str], str],
    unsupported_provider_message: str | None = None,
    mark_fatal_on_unsupported: bool = False,
) -> None:
    cfg = runtime.cfg
    if cfg.data_provider == "kis":
        app_key = cfg.kis_app_key
        app_secret = cfg.kis_app_secret
        base_url = cfg.kis_base_url
        if not (app_key and app_secret and base_url):
            msg = "KIS credentials missing. Set KIS_APP_KEY, KIS_APP_SECRET, KIS_BASE_URL in .env (see docs/kis-setup.md)."
            runtime.failures.append(msg)
            runtime.logger.error(msg)
            runtime.fatal_failure = True
            return

        creds = KISCredentialsCls(
            app_key=app_key,
            app_secret=app_secret,
            base_url=base_url,
            env=infer_env_from_base_fn(base_url),
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

    if unsupported_provider_message:
        msg = unsupported_provider_message.format(provider=cfg.data_provider)
        runtime.failures.append(msg)
        runtime.logger.error(msg)
        if mark_fatal_on_unsupported:
            runtime.fatal_failure = True


def collect_market_data_from_kis[TRuntime: _CollectionRuntime](
    runtime: TRuntime,
    *,
    request: KisCollectionRequest[TRuntime],
    now_fn: Callable[[], dt.datetime] | None = None,
) -> None:
    if runtime.kis_client is None:
        return

    now = _ensure_aware_now(now_fn() if now_fn else None)
    holiday_dates_by_market: dict[str, set[dt.date]] = {}

    for ticker in request.tickers:
        target = _resolve_ticker_target(
            ticker,
            adjusted=request.adjusted,
            split_symbol_and_suffix_fn=request.split_symbol_and_suffix_fn,
            exchange_from_suffix_fn=request.exchange_from_suffix_fn,
            legacy_cache_keys_fn=request.legacy_cache_keys_fn,
        )
        market = _market_from_exchange(target.exchange)
        max_stale_sessions = _resolve_market_stale_limit(runtime.cfg, market=market)

        closed_dates = holiday_dates_by_market.get(market)
        if closed_dates is None:
            closed_dates = _load_market_holiday_dates(runtime.cfg.data_dir, market)
            holiday_dates_by_market[market] = closed_dates

        cache = _lookup_cached_candles(
            runtime,
            ticker=ticker,
            cache_keys=(target.cache_key, *target.legacy_cache_keys),
            market=market,
            max_stale_sessions=max_stale_sessions,
            now=now,
            closed_dates=closed_dates,
            load_json_fn=request.load_json_fn,
            save_json_fn=request.save_json_fn,
        )
        if _apply_fresh_cache_if_available(
            runtime,
            ticker=ticker,
            request=request,
            cache=cache,
            target_cache_key=target.cache_key,
        ):
            continue

        try:
            if target.exchange:
                try:
                    candles = runtime.kis_client.overseas_daily_candles(
                        symbol=target.base_symbol,
                        exchange=target.exchange,
                        count=request.target_bars,
                        adjusted=request.adjusted,
                    )
                except TypeError as type_exc:
                    if not _is_adjusted_kwarg_type_error(type_exc):
                        raise
                    # Backward compatibility for stub/test clients that
                    # do not yet expose the adjusted kwarg.
                    candles = runtime.kis_client.overseas_daily_candles(
                        symbol=target.base_symbol,
                        exchange=target.exchange,
                        count=request.target_bars,
                    )
            else:
                candles = _daily_candles_with_optional_adjusted(
                    runtime.kis_client,
                    target.base_symbol,
                    count=request.target_bars,
                    adjusted=request.adjusted,
                )
            provider_result = _normalize_provider_result(
                runtime,
                ticker=ticker,
                candles=candles,
                market=market,
                now=now,
                closed_dates=closed_dates,
                source_label="provider response",
            )
            if not provider_result.had_response:
                _handle_provider_rejection(
                    runtime,
                    ticker=ticker,
                    request=request,
                    cache=cache,
                    target_cache_key=target.cache_key,
                    warning_message="%s: Provider returned no data; used stale cache fallback",
                    failure_message=f"{ticker}: No candle data returned",
                )
                continue

            if not provider_result.candles:
                _handle_provider_rejection(
                    runtime,
                    ticker=ticker,
                    request=request,
                    cache=cache,
                    target_cache_key=target.cache_key,
                    warning_message=(
                        "%s: Provider returned only incomplete or invalid candles; "
                        "used stale cache fallback"
                    ),
                    failure_message=(
                        f"{ticker}: No complete and finite candle data returned"
                    ),
                )
                continue

            if provider_result.rejection_reason is not None:
                _handle_provider_rejection(
                    runtime,
                    ticker=ticker,
                    request=request,
                    cache=cache,
                    target_cache_key=target.cache_key,
                    warning_message="%s: Provider returned stale candles (%s); used stale cache fallback",
                    failure_message=(
                        f"{ticker}: Provider returned stale candles "
                        f"({provider_result.rejection_reason})"
                    ),
                    warning_args=(provider_result.rejection_reason,),
                )
                continue

            _apply_provider_candles(
                runtime,
                ticker=ticker,
                candles=provider_result.candles,
                request=request,
                target_cache_key=target.cache_key,
                source="kis",
                persist_source_label="KIS",
                fetched_log_message="Fetched %s candles for %s",
            )
        except (KISClientError, KISAuthError) as exc:
            if _apply_stale_cache_fallback(
                runtime,
                ticker=ticker,
                request=request,
                cache=cache,
                target_cache_key=target.cache_key,
                warning_message="%s: KIS error (%s); used stale cache fallback",
                warning_args=(exc,),
            ):
                continue

            fallback_client = request.ensure_pykrx_client_fn(runtime)
            fallback_error = request.get_pykrx_error_fn(runtime)
            if fallback_client is not None and target.exchange is None:
                try:
                    fallback_candles = _daily_candles_with_optional_adjusted(
                        fallback_client,
                        target.base_symbol,
                        count=request.target_bars,
                        adjusted=request.adjusted,
                    )
                except PykrxClientError as py_exc:
                    fallback_client = None
                    fallback_error = str(py_exc)
                else:
                    fallback_result = _normalize_provider_result(
                        runtime,
                        ticker=ticker,
                        candles=fallback_candles,
                        market=market,
                        now=now,
                        closed_dates=closed_dates,
                        source_label="PyKRX fallback",
                    )
                    if fallback_result.fresh:
                        runtime.market_data[ticker] = fallback_result.candles
                        runtime.ticker_data_source[ticker] = "pykrx"
                        if request.on_candles_applied_fn:
                            request.on_candles_applied_fn(
                                runtime, ticker, fallback_result.candles
                            )
                        runtime.logger.warning(
                            "%s: KIS error (%s); used PyKRX fallback (%s candles)",
                            ticker,
                            exc,
                            len(fallback_result.candles),
                        )
                        runtime.failures.append(
                            f"{ticker}: KIS error ({exc}); used PyKRX fallback"
                        )
                        _append_pykrx_warning_once(
                            runtime,
                            "Warning: PyKRX fallback data is end-of-day and may differ from KIS.",
                        )
                        continue
                    if not fallback_result.had_response:
                        fallback_error = "No data from PyKRX"
                        fallback_client = None
                    elif not fallback_result.candles:
                        fallback_error = "No complete and finite candle data from PyKRX"
                        fallback_client = None
                    elif fallback_result.rejection_reason is not None:
                        fallback_error = (
                            "PyKRX returned stale candles "
                            f"({fallback_result.rejection_reason})"
                        )
                        fallback_client = None
                        if _apply_stale_cache_fallback(
                            runtime,
                            ticker=ticker,
                            request=request,
                            cache=cache,
                            target_cache_key=target.cache_key,
                            warning_message=(
                                "%s: PyKRX fallback returned stale candles (%s); "
                                "used stale cache fallback"
                            ),
                            warning_args=(fallback_result.rejection_reason,),
                        ):
                            continue
            elif target.exchange:
                fallback_error = "Overseas symbol; no PyKRX fallback"

            msg = f"{ticker}: {exc}"
            if (fallback_client is None or target.exchange) and fallback_error:
                msg += f" (PyKRX fallback unavailable: {fallback_error})"
            msg = _message_with_cache_rejection(msg, cache=cache)
            runtime.failures.append(msg)
            runtime.logger.error(msg)


def collect_market_data_from_pykrx[TRuntime: _CollectionRuntime](
    runtime: TRuntime,
    *,
    request: PykrxCollectionRequest[TRuntime],
    now_fn: Callable[[], dt.datetime] | None = None,
) -> None:
    if runtime.pykrx_client is None:
        return

    now = _ensure_aware_now(now_fn() if now_fn else None)
    closed_dates = _load_market_holiday_dates(runtime.cfg.data_dir, "KR")

    for ticker in request.tickers:
        target = _resolve_ticker_target(
            ticker,
            adjusted=request.adjusted,
            split_symbol_and_suffix_fn=request.split_symbol_and_suffix_fn,
            exchange_from_suffix_fn=request.exchange_from_suffix_fn,
            legacy_cache_keys_fn=request.legacy_cache_keys_fn,
        )
        if target.exchange is not None:
            msg = f"{ticker}: PyKRX provider supports KR tickers only"
            runtime.failures.append(msg)
            runtime.logger.error(msg)
            continue

        max_stale_sessions = _resolve_market_stale_limit(runtime.cfg, market="KR")
        cache = _lookup_cached_candles(
            runtime,
            ticker=ticker,
            cache_keys=(target.cache_key, *target.legacy_cache_keys),
            market="KR",
            max_stale_sessions=max_stale_sessions,
            now=now,
            closed_dates=closed_dates,
            load_json_fn=request.load_json_fn,
            save_json_fn=request.save_json_fn,
        )
        if _apply_fresh_cache_if_available(
            runtime,
            ticker=ticker,
            request=request,
            cache=cache,
            target_cache_key=target.cache_key,
        ):
            continue

        try:
            candles = _daily_candles_with_optional_adjusted(
                runtime.pykrx_client,
                target.base_symbol,
                count=request.target_bars,
                adjusted=request.adjusted,
            )
        except request.PykrxClientErrorCls as exc:
            _handle_provider_rejection(
                runtime,
                ticker=ticker,
                request=request,
                cache=cache,
                target_cache_key=target.cache_key,
                warning_message="%s: PyKRX error (%s); used stale cache fallback",
                failure_message=f"{ticker}: PyKRX error ({exc})",
                warning_args=(exc,),
                log_failure_as_error=True,
            )
            continue

        provider_result = _normalize_provider_result(
            runtime,
            ticker=ticker,
            candles=candles,
            market="KR",
            now=now,
            closed_dates=closed_dates,
            source_label="PyKRX provider response",
        )
        if not provider_result.had_response:
            _handle_provider_rejection(
                runtime,
                ticker=ticker,
                request=request,
                cache=cache,
                target_cache_key=target.cache_key,
                warning_message="%s: PyKRX returned no data; used stale cache fallback",
                failure_message=f"{ticker}: PyKRX returned no data",
            )
            continue

        if not provider_result.candles:
            _handle_provider_rejection(
                runtime,
                ticker=ticker,
                request=request,
                cache=cache,
                target_cache_key=target.cache_key,
                warning_message=(
                    "%s: PyKRX returned only incomplete or invalid candles; "
                    "used stale cache fallback"
                ),
                failure_message=(
                    f"{ticker}: PyKRX returned no complete and finite candle data"
                ),
            )
            continue

        if provider_result.rejection_reason is not None:
            _handle_provider_rejection(
                runtime,
                ticker=ticker,
                request=request,
                cache=cache,
                target_cache_key=target.cache_key,
                warning_message="%s: PyKRX returned stale candles (%s); used stale cache fallback",
                failure_message=(
                    f"{ticker}: PyKRX returned stale candles "
                    f"({provider_result.rejection_reason})"
                ),
                warning_args=(provider_result.rejection_reason,),
            )
            continue

        _apply_provider_candles(
            runtime,
            ticker=ticker,
            candles=provider_result.candles,
            request=request,
            target_cache_key=target.cache_key,
            source="pykrx",
            persist_source_label="PyKRX",
            fetched_log_message="Fetched %s candles via PyKRX for %s",
        )

    if request.tickers:
        _append_pykrx_warning_once(
            runtime,
            "Warning: PyKRX provider data is end-of-day and may lag intraday feeds.",
        )
