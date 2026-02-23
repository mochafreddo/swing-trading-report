from __future__ import annotations

import datetime as dt
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any
from zoneinfo import ZoneInfo

from .data.holiday_cache import load_cached_holidays
from .data.kis_client import KISAuthError, KISClientError
from .data.kr_calendar import load_kr_trading_calendar
from .data.pykrx_client import PykrxClientError, PykrxNotInstalledError
from .data.us_calendar import load_us_trading_calendar
from .fx import SUFFIX_TO_EXCD

type _LegacyCacheKeysFn = Callable[[str, str, str | None], list[str]]
type _OnCandlesAppliedFn = Callable[[Any, str, list[dict[str, Any]]], None]


@dataclass(frozen=True)
class _TickerTarget:
    ticker: str
    base_symbol: str
    exchange: str | None
    cache_key: str
    legacy_cache_keys: tuple[str, ...]


_NORMALIZED_SUFFIX_TO_EXCD = {
    "".join(ch for ch in key.upper() if ch.isalnum()): value
    for key, value in SUFFIX_TO_EXCD.items()
}
_KR_ZONE = ZoneInfo("Asia/Seoul")
_US_ZONE = ZoneInfo("America/New_York")
_MAX_SESSION_LOOKBACK_DAYS = 3700


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


def _build_cache_key(base_symbol: str, exchange: str | None) -> str:
    if exchange:
        return f"candles_overseas_{exchange}_{base_symbol}"
    return f"candles_{base_symbol}"


def _ensure_aware_now(now: dt.datetime | None) -> dt.datetime:
    if now is None:
        return dt.datetime.now(dt.UTC)
    if now.tzinfo is None:
        return now.replace(tzinfo=dt.UTC)
    return now


def _parse_session_date(value: Any) -> dt.date | None:
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
) -> dt.date | None:
    zone = _US_ZONE if market == "US" else _KR_ZONE
    close_time = dt.time(16, 0) if market == "US" else dt.time(15, 30)
    local_now = now.astimezone(zone)
    session_date = local_now.date()

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


def _resolve_market_stale_limit(cfg: Any, *, market: str) -> int:
    attr = (
        "market_cache_stale_sessions_us"
        if market == "US"
        else "market_cache_stale_sessions_kr"
    )
    raw = getattr(cfg, attr, 1)
    try:
        return max(0, int(raw))
    except (TypeError, ValueError):
        return 1


def _evaluate_cache_staleness(
    *,
    candles: list[dict[str, Any]],
    market: str,
    max_stale_sessions: int,
    closed_dates: set[dt.date],
    now: dt.datetime,
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
    cache_key = _build_cache_key(base_symbol, exchange)
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


def _append_pykrx_warning_once(runtime: Any, message: str) -> None:
    if runtime.pykrx_warning_added:
        return
    runtime.failures.append(message)
    runtime.pykrx_warning_added = True


def ensure_pykrx_client(
    runtime: Any,
    *,
    PykrxClientCls: Any,
    get_pykrx_error_fn: Callable[[Any], str | None],
    set_pykrx_error_fn: Callable[[Any, str], None],
    pykrx_client_kwargs_fn: Callable[[Any], dict[str, Any]] | None = None,
    initialized_log_message: str,
) -> Any | None:
    if runtime.pykrx_client is not None:
        return runtime.pykrx_client
    if get_pykrx_error_fn(runtime):
        return None

    kwargs = pykrx_client_kwargs_fn(runtime) if pykrx_client_kwargs_fn else {}
    try:
        runtime.pykrx_client = PykrxClientCls(**kwargs)
        runtime.logger.info(initialized_log_message)
        return runtime.pykrx_client
    except PykrxNotInstalledError as exc:
        set_pykrx_error_fn(runtime, str(exc))
        runtime.logger.warning("PyKRX unavailable: %s", exc)
    except PykrxClientError as exc:
        set_pykrx_error_fn(runtime, str(exc))
        runtime.logger.error("PyKRX init failed: %s", exc)
    return None


def initialize_provider(
    runtime: Any,
    *,
    KISCredentialsCls: Any,
    KISClientCls: Any,
    ensure_pykrx_client_fn: Callable[[Any], Any | None],
    infer_env_from_base_fn: Callable[[str], str],
    unsupported_provider_message: str | None = None,
    mark_fatal_on_unsupported: bool = False,
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

    if unsupported_provider_message:
        msg = unsupported_provider_message.format(provider=cfg.data_provider)
        runtime.failures.append(msg)
        runtime.logger.error(msg)
        if mark_fatal_on_unsupported:
            runtime.fatal_failure = True


def collect_market_data_from_kis(
    runtime: Any,
    *,
    tickers: list[str],
    target_bars: int,
    load_json_fn: Callable[[str, str], Any],
    save_json_fn: Callable[[str, str, Any], None],
    ensure_pykrx_client_fn: Callable[[Any], Any | None],
    split_symbol_and_suffix_fn: Callable[[str], tuple[str, str | None]],
    exchange_from_suffix_fn: Callable[[str | None], str | None],
    get_pykrx_error_fn: Callable[[Any], str | None],
    legacy_cache_keys_fn: _LegacyCacheKeysFn | None = None,
    on_candles_applied_fn: _OnCandlesAppliedFn | None = None,
    now_fn: Callable[[], dt.datetime] | None = None,
) -> None:
    if runtime.kis_client is None:
        return

    now = _ensure_aware_now(now_fn() if now_fn else None)
    holiday_dates_by_market: dict[str, set[dt.date]] = {}

    for ticker in tickers:
        target = _resolve_ticker_target(
            ticker,
            split_symbol_and_suffix_fn=split_symbol_and_suffix_fn,
            exchange_from_suffix_fn=exchange_from_suffix_fn,
            legacy_cache_keys_fn=legacy_cache_keys_fn,
        )
        market = _market_from_exchange(target.exchange)
        max_stale_sessions = _resolve_market_stale_limit(runtime.cfg, market=market)
        cache_keys = (target.cache_key, *target.legacy_cache_keys)
        cached: Any = None
        cached_key: str | None = None
        cached_stale_sessions: int | None = None
        cache_rejection_reason: str | None = None
        for cache_key in cache_keys:
            candidate = load_json_fn(runtime.cfg.data_dir, cache_key)
            if isinstance(candidate, list) and candidate:
                cached = candidate
                cached_key = cache_key
                break
        if isinstance(cached, list) and cached:
            closed_dates = holiday_dates_by_market.get(market)
            if closed_dates is None:
                closed_dates = _load_market_holiday_dates(runtime.cfg.data_dir, market)
                holiday_dates_by_market[market] = closed_dates
            (
                cache_usable,
                cached_stale_sessions,
                cache_rejection_reason,
            ) = _evaluate_cache_staleness(
                candles=cached,
                market=market,
                max_stale_sessions=max_stale_sessions,
                closed_dates=closed_dates,
                now=now,
            )
            if cache_usable:
                runtime.market_data[ticker] = cached
                runtime.ticker_data_source.setdefault(ticker, runtime.cfg.data_provider)
                if on_candles_applied_fn:
                    on_candles_applied_fn(runtime, ticker, cached)
                if cached_key and cached_key != target.cache_key:
                    try:
                        save_json_fn(runtime.cfg.data_dir, target.cache_key, cached)
                    except Exception as exc:
                        migration_msg = (
                            f"{ticker}: Failed to migrate cache key "
                            f"'{cached_key}' -> '{target.cache_key}' ({exc})"
                        )
                        runtime.failures.append(migration_msg)
                        runtime.logger.warning(migration_msg)

        try:
            if target.exchange:
                candles = runtime.kis_client.overseas_daily_candles(
                    symbol=target.base_symbol,
                    exchange=target.exchange,
                    count=target_bars,
                )
            else:
                candles = runtime.kis_client.daily_candles(
                    target.base_symbol,
                    count=target_bars,
                )
            if candles:
                runtime.market_data[ticker] = candles
                runtime.ticker_data_source[ticker] = "kis"
                save_json_fn(runtime.cfg.data_dir, target.cache_key, candles)
                if on_candles_applied_fn:
                    on_candles_applied_fn(runtime, ticker, candles)
                runtime.logger.info("Fetched %s candles for %s", len(candles), ticker)
            else:
                msg = f"{ticker}: No candle data returned"
                if cache_rejection_reason:
                    msg += f" (cache unavailable: {cache_rejection_reason})"
                runtime.failures.append(msg)
                runtime.logger.warning(msg)
        except (KISClientError, KISAuthError) as exc:
            if ticker in runtime.market_data:
                stale_note = ""
                if cached_stale_sessions is not None:
                    stale_note = (
                        f", stale={cached_stale_sessions}/{max_stale_sessions} "
                        f"{market} sessions"
                    )
                msg = f"{ticker}: API error, using cached data{stale_note} ({exc})"
                runtime.failures.append(msg)
                runtime.logger.warning(msg)
                continue

            fallback_client = ensure_pykrx_client_fn(runtime)
            fallback_error = get_pykrx_error_fn(runtime)
            if fallback_client is not None and target.exchange is None:
                try:
                    candles = fallback_client.daily_candles(
                        target.base_symbol,
                        count=target_bars,
                    )
                except PykrxClientError as py_exc:
                    fallback_client = None
                    fallback_error = str(py_exc)
                else:
                    if candles:
                        runtime.market_data[ticker] = candles
                        runtime.ticker_data_source[ticker] = "pykrx"
                        if on_candles_applied_fn:
                            on_candles_applied_fn(runtime, ticker, candles)
                        runtime.logger.warning(
                            "%s: KIS error (%s); used PyKRX fallback (%s candles)",
                            ticker,
                            exc,
                            len(candles),
                        )
                        runtime.failures.append(
                            f"{ticker}: KIS error ({exc}); used PyKRX fallback"
                        )
                        _append_pykrx_warning_once(
                            runtime,
                            "Warning: PyKRX fallback data is end-of-day and may differ from KIS.",
                        )
                        continue
                    fallback_error = "No data from PyKRX"
                    fallback_client = None
            elif target.exchange:
                fallback_error = "Overseas symbol; no PyKRX fallback"

            msg = f"{ticker}: {exc}"
            if (fallback_client is None or target.exchange) and fallback_error:
                msg += f" (PyKRX fallback unavailable: {fallback_error})"
            if cache_rejection_reason:
                msg += f" (cache unavailable: {cache_rejection_reason})"
            runtime.failures.append(msg)
            runtime.logger.error(msg)


def collect_market_data_from_pykrx(
    runtime: Any,
    *,
    tickers: list[str],
    target_bars: int,
    PykrxClientErrorCls: Any,
    on_candles_applied_fn: _OnCandlesAppliedFn | None = None,
) -> None:
    if runtime.pykrx_client is None:
        return

    for ticker in tickers:
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
            if on_candles_applied_fn:
                on_candles_applied_fn(runtime, ticker, candles)
            runtime.logger.info(
                "Fetched %s candles via PyKRX for %s", len(candles), ticker
            )
        else:
            msg = f"{ticker}: PyKRX returned no data"
            runtime.failures.append(msg)
            runtime.logger.warning(msg)

    if tickers:
        _append_pykrx_warning_once(
            runtime,
            "Warning: PyKRX provider data is end-of-day and may lag intraday feeds.",
        )


def collect_market_data(
    runtime: Any,
    *,
    tickers: list[str],
    collect_market_data_from_kis_fn: Callable[[Any], None],
    collect_market_data_from_pykrx_fn: Callable[[Any], None],
    unsupported_provider_message: str
    | None = "Provider '{provider}' not yet implemented",
    mark_fatal_on_unsupported: bool = True,
) -> None:
    provider = runtime.cfg.data_provider
    if provider == "kis" and runtime.kis_client:
        collect_market_data_from_kis_fn(runtime)
        return
    if provider == "pykrx" and runtime.pykrx_client:
        collect_market_data_from_pykrx_fn(runtime)
        return
    if tickers and unsupported_provider_message:
        runtime.failures.append(unsupported_provider_message.format(provider=provider))
        if mark_fatal_on_unsupported:
            runtime.fatal_failure = True
