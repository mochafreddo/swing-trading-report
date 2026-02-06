from __future__ import annotations

import datetime as dt
import logging
import math
from dataclasses import dataclass, field
from typing import Any

from .config import Config, load_config, load_watchlist
from .config_loader import ConfigLoadError
from .data.cache import load_json, save_json
from .data.holiday_cache import HolidayEntry, lookup_holiday, merge_holidays
from .data.kis_client import KISAuthError, KISClient, KISClientError, KISCredentials
from .data.pykrx_client import (
    PykrxClient,
    PykrxClientError,
    PykrxNotInstalledError,
)
from .fx import resolve_fx_rate
from .holdings_loader import HoldingsLoadError
from .report.markdown import write_report
from .screener import KISScreener, ScreenRequest
from .screener.kis_overseas_screener import (
    KISOverseasScreener as KUS,
)
from .screener.kis_overseas_screener import (
    ScreenRequest as KUSReq,
)
from .screener.overseas_screener import ScreenRequest as USScreenRequest
from .screener.overseas_screener import USSimpleScreener as USScreener
from .signals.evaluator import EvaluationSettings, evaluate_ticker
from .signals.hybrid_buy import (
    HybridEvaluationSettings,
    evaluate_ticker_hybrid,
)
from .utils.market_time import us_market_status, us_session_info


def _infer_env_from_base(base_url: str) -> str:
    return "demo" if "vts" in base_url.lower() else "real"


def _format_ny_now_for_log(session_info: dict[str, object]) -> str:
    ny_now = session_info.get("ny_now")
    if isinstance(ny_now, dt.datetime):
        return ny_now.isoformat(timespec="seconds")
    if ny_now is None:
        return "-"
    return str(ny_now)


US_SUFFIXES = {"US", "NASDAQ", "NASD", "NAS", "NYSE", "NYS", "AMEX", "AMS"}


def _infer_currency(ticker: str) -> str:
    suffix = None
    if "." in ticker:
        suffix = ticker.rsplit(".", 1)[1].strip().upper()
    if suffix in US_SUFFIXES:
        return "USD"
    return "KRW"


def _to_float(value: Any) -> float | None:
    try:
        if value is None:
            return None
        val = float(value)
        if math.isnan(val):
            return None
        return val
    except (TypeError, ValueError):
        return None


def _apply_currency_display(
    candidate: dict[str, Any],
    fx_rate: float | None,
    fx_meta_note: str | None,
) -> None:
    currency = candidate.get("currency", "KRW")
    price_value = _to_float(candidate.get("price_value"))
    if price_value is None:
        candidate["price"] = candidate.get("price", "-")
        return

    if currency == "USD":
        display = f"${price_value:,.2f}"
        if fx_rate:
            converted = price_value * fx_rate
            candidate["price_converted"] = converted
            note = f"1 USD ≈ ₩{fx_rate:,.0f}"
            if fx_meta_note:
                note += f" ({fx_meta_note})"
            candidate["fx_note"] = note
            display += f" (₩{converted:,.0f})"
        candidate["price"] = display
    else:
        candidate["price"] = f"₩{price_value:,.0f}"


def _split_overseas(ticker: str) -> tuple[str, str | None]:
    # Accept formats: SYMBOL.US (default NASD), SYMBOL.NASD/NYSE/AMEX
    if "." not in ticker:
        return ticker, None
    base, suffix = ticker.rsplit(".", 1)
    return base.strip().upper(), suffix.strip().upper()


def _excd_from_suffix(suffix: str | None) -> str | None:
    if not suffix:
        return None
    mapping = {
        # KIS EXCD codes: NAS (NASDAQ), NYS (NYSE), AMS (AMEX)
        "US": "NAS",
        "NASDAQ": "NAS",
        "NASD": "NAS",
        "NAS": "NAS",
        "NYSE": "NYS",
        "NYS": "NYS",
        "AMEX": "AMS",
        "AMS": "AMS",
    }
    return mapping.get(suffix)


def _coerce_nday(value: object) -> int:
    if isinstance(value, bool):
        return int(value)
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        return int(value)
    if isinstance(value, str):
        try:
            return int(value)
        except ValueError:
            return 1
    return 1


@dataclass
class _ScanRuntime:
    cfg: Config
    logger: logging.Logger
    tickers: list[str]
    failures: list[str] = field(default_factory=list)
    market_data: dict[str, list[dict[str, Any]]] = field(default_factory=dict)
    ticker_data_source: dict[str, str] = field(default_factory=dict)
    cache_hint: str | None = None
    fatal_failure: bool = False
    kis_client: KISClient | None = None
    pykrx_client: PykrxClient | None = None
    pykrx_import_error: str | None = None
    pykrx_warning_added: bool = False
    screener_meta_map: dict[str, dict[str, Any]] = field(default_factory=dict)
    ticker_currency: dict[str, str] = field(default_factory=dict)
    fx_rate: float | None = None
    fx_meta_note: str | None = None
    us_holidays_cache: dict[str, HolidayEntry] = field(default_factory=dict)
    latest_dates: dict[str, str] = field(default_factory=dict)
    candidates: list[dict[str, Any]] = field(default_factory=list)


def _load_scan_tickers(cfg: Config, watchlist_path: str | None) -> list[str]:
    resolved_watchlist_path = watchlist_path or cfg.watchlist_path or "watchlist.txt"
    tickers = load_watchlist(resolved_watchlist_path)
    if cfg.screen_limit and tickers:
        return tickers[: cfg.screen_limit]
    return tickers


def _resolve_screener_flags(cfg: Config, universe: str | None) -> tuple[bool, bool]:
    if universe == "watchlist":
        return False, False
    if universe == "screener":
        return True, True
    if universe == "both":
        return True, False
    screener_enabled = cfg.screener_enabled
    screener_only = cfg.screener_only if screener_enabled else False
    return screener_enabled, screener_only


def _ensure_pykrx_client(runtime: _ScanRuntime) -> PykrxClient | None:
    if runtime.pykrx_client is not None:
        return runtime.pykrx_client
    if runtime.pykrx_import_error:
        return None
    try:
        runtime.pykrx_client = PykrxClient()
        runtime.logger.info("PyKRX client initialized for fallback/provider usage")
        return runtime.pykrx_client
    except PykrxNotInstalledError as exc:
        runtime.pykrx_import_error = str(exc)
        runtime.logger.warning("PyKRX unavailable: %s", exc)
    except PykrxClientError as exc:
        runtime.pykrx_import_error = str(exc)
        runtime.logger.error("PyKRX init failed: %s", exc)
    return None


def _initialize_provider(runtime: _ScanRuntime, *, screener_enabled: bool) -> None:
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

    if screener_enabled:
        msg = "Screener currently supports KIS provider only."
        runtime.failures.append(msg)
        runtime.logger.error(msg)
        runtime.fatal_failure = True


def _run_kr_screener(
    runtime: _ScanRuntime, *, screener_limit: int, screener_only: bool
) -> int:
    if "KR" not in runtime.cfg.universe_markets or runtime.kis_client is None:
        return 0

    req = ScreenRequest(
        limit=screener_limit,
        min_price=runtime.cfg.min_price,
        min_dollar_volume=runtime.cfg.min_dollar_volume,
    )
    screener = KISScreener(
        runtime.kis_client,
        cache_dir=runtime.cfg.data_dir,
        cache_ttl_minutes=runtime.cfg.screener_cache_ttl_minutes,
    )
    screen_result = screener.screen(req)
    kr_tickers = screen_result.tickers
    runtime.screener_meta_map.update(screen_result.metadata.get("by_ticker", {}))
    cache_status = screen_result.metadata.get("cache_status", "refresh")

    if not screener_only:
        if runtime.tickers:
            runtime.logger.info(
                "Screener combined with watchlist (%s tickers)", len(runtime.tickers)
            )
        runtime.tickers = list(dict.fromkeys(runtime.tickers + kr_tickers))
    else:
        runtime.tickers = kr_tickers

    runtime.logger.info(
        "KR screener selected %s tickers (cache: %s)",
        len(kr_tickers),
        cache_status,
    )
    return len(kr_tickers)


def _run_us_screener(
    runtime: _ScanRuntime, *, screener_limit: int, screener_only: bool
) -> int:
    if "US" not in runtime.cfg.universe_markets or runtime.kis_client is None:
        return 0

    cfg = runtime.cfg
    us_tickers: list[str] = []
    us_source: str | None = None
    us_nday_used: int | None = None

    session_info = us_session_info(data_dir=cfg.data_dir)
    preferred_nday = _coerce_nday(session_info.get("preferred_nday", 1))
    fallback_ndays = (
        [n for n in range(1, 6) if n != preferred_nday]
        if preferred_nday != 0
        else [n for n in range(1, 6)]
    )
    ny_now_str = _format_ny_now_for_log(session_info)
    runtime.logger.info(
        "US session state=%s holiday=%s preferred_nday=%s ny_now=%s",
        session_info.get("state"),
        session_info.get("is_holiday"),
        preferred_nday,
        ny_now_str,
    )

    if cfg.us_screener_mode == "kis":
        try:
            kscr = KUS(runtime.kis_client)
            kres = kscr.screen(
                KUSReq(
                    limit=cfg.us_screener_limit or screener_limit,
                    metric=cfg.us_screener_metric,
                    nday=preferred_nday,
                    fallback_ndays=fallback_ndays,
                )
            )
            us_tickers = kres.tickers
            us_nday_used = kres.metadata.get("nday_used")
            runtime.screener_meta_map.update(kres.metadata.get("by_ticker", {}))
            if us_tickers:
                us_source = "kis_overseas_rank"
                runtime.logger.info(
                    "US KIS screener used nday=%s (tried=%s, state=%s)",
                    kres.metadata.get("nday_used"),
                    kres.metadata.get("nday_tried"),
                    session_info.get("state"),
                )
            else:
                runtime.logger.warning(
                    "US KIS screener returned 0 tickers; falling back to defaults if configured"
                )
        except Exception as exc:
            runtime.logger.warning(
                "US KIS screener failed (%s); falling back to defaults", exc
            )

    if not us_tickers and cfg.us_screener_defaults:
        us_scr = USScreener(cfg.us_screener_defaults)
        us_res = us_scr.screen(USScreenRequest(limit=screener_limit))
        us_tickers = us_res.tickers
        if us_tickers:
            us_source = (
                "us_defaults (fallback)"
                if cfg.us_screener_mode == "kis"
                else "us_defaults"
            )
            if cfg.us_screener_mode == "kis":
                runtime.logger.info(
                    "US defaults list used as fallback (%s tickers)", len(us_tickers)
                )
        else:
            runtime.logger.warning(
                "US defaults list configured but returned zero tickers; US universe skipped"
            )
    elif not us_tickers:
        runtime.logger.warning(
            "US screener produced no tickers and no defaults configured; US universe skipped"
        )

    if not screener_only:
        runtime.tickers = list(dict.fromkeys(runtime.tickers + us_tickers))
    else:
        # if screener_only but both KR and US enabled, prefer combined
        runtime.tickers = list(dict.fromkeys(us_tickers + (runtime.tickers or [])))

    runtime.logger.info(
        "US screener selected %s tickers (mode=%s, source=%s, nday=%s, state=%s)",
        len(us_tickers),
        cfg.us_screener_mode,
        us_source or "none",
        us_nday_used,
        session_info.get("state"),
    )
    return len(us_tickers)


def _run_screeners(
    runtime: _ScanRuntime,
    *,
    screener_enabled: bool,
    screener_only: bool,
    screener_limit: int,
) -> None:
    if not screener_enabled:
        return
    if not runtime.kis_client:
        msg = "Screener enabled but KIS client unavailable."
        runtime.failures.append(msg)
        runtime.logger.error(msg)
        runtime.fatal_failure = True
        return

    total_added = 0
    total_added += _run_kr_screener(
        runtime,
        screener_limit=screener_limit,
        screener_only=screener_only,
    )
    total_added += _run_us_screener(
        runtime,
        screener_limit=screener_limit,
        screener_only=screener_only,
    )
    if total_added == 0:
        runtime.logger.warning(
            "Screener enabled but no markets selected or no defaults configured for US"
        )


def _resolve_scan_fx(runtime: _ScanRuntime) -> None:
    runtime.ticker_currency = {
        ticker: _infer_currency(ticker) for ticker in runtime.tickers
    }
    resolved_rate, resolved_note, fx_messages = resolve_fx_rate(
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


def _refresh_us_holidays(runtime: _ScanRuntime) -> dict[str, HolidayEntry]:
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
    return merge_holidays(runtime.cfg.data_dir, "US", items)


def _collect_market_data_from_kis(runtime: _ScanRuntime) -> None:
    cfg = runtime.cfg
    if runtime.kis_client is None:
        return

    if "US" in cfg.universe_markets or any(
        currency.upper() == "USD" for currency in runtime.ticker_currency.values()
    ):
        runtime.us_holidays_cache = _refresh_us_holidays(runtime)

    for ticker in runtime.tickers:
        base_symbol, suffix = _split_overseas(ticker)
        exchange = _excd_from_suffix(suffix)
        cache_key = (
            f"candles_overseas_{exchange}_{base_symbol}"
            if exchange
            else f"candles_{ticker}"
        )
        cached = load_json(cfg.data_dir, cache_key)
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
                save_json(cfg.data_dir, cache_key, candles)
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

            fallback_client = _ensure_pykrx_client(runtime)
            fallback_error: str | None = None
            if fallback_client is not None and not exchange:
                # PyKRX only supports KR tickers, skip if overseas
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


def _collect_market_data_from_pykrx(runtime: _ScanRuntime) -> None:
    if runtime.pykrx_client is None:
        return

    for ticker in runtime.tickers:
        try:
            candles = runtime.pykrx_client.daily_candles(
                ticker, count=max(runtime.cfg.min_history_bars, 200)
            )
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


def _collect_market_data(runtime: _ScanRuntime) -> None:
    provider = runtime.cfg.data_provider
    if provider == "kis" and runtime.kis_client:
        _collect_market_data_from_kis(runtime)
        return
    if provider == "pykrx" and runtime.pykrx_client:
        _collect_market_data_from_pykrx(runtime)
        return
    if runtime.tickers:
        runtime.failures.append(f"Provider '{provider}' not yet implemented")
        runtime.fatal_failure = True


def _evaluate_candidates(runtime: _ScanRuntime) -> None:
    cfg = runtime.cfg
    eval_settings = EvaluationSettings(
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
    hybrid_settings = HybridEvaluationSettings(
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
    )

    for ticker in runtime.tickers:
        ticker_candles = runtime.market_data.get(ticker)
        if not ticker_candles:
            continue

        meta = dict(runtime.screener_meta_map.get(ticker, {}))
        meta["currency"] = runtime.ticker_currency.get(ticker, "KRW")
        _, suffix = _split_overseas(ticker)
        if "exchange" not in meta:
            meta["exchange"] = _excd_from_suffix(suffix)
        data_source = runtime.ticker_data_source.get(ticker, cfg.data_provider)
        meta["data_source"] = data_source
        meta["provider"] = data_source
        meta["data_dir"] = cfg.data_dir
        if runtime.fx_rate is not None:
            meta["usd_krw_rate"] = runtime.fx_rate

        if cfg.strategy_mode == "sma_ema_hybrid":
            result_hybrid = evaluate_ticker_hybrid(
                ticker, ticker_candles, hybrid_settings, meta
            )
            if result_hybrid.candidate:
                runtime.candidates.append(result_hybrid.candidate)
            elif (
                result_hybrid.reason
                and result_hybrid.reason != "Did not meet hybrid signal criteria"
            ):
                runtime.failures.append(f"{ticker}: {result_hybrid.reason}")
                runtime.logger.warning("%s: %s", ticker, result_hybrid.reason)
            continue

        result = evaluate_ticker(ticker, ticker_candles, eval_settings, meta)
        if result.candidate:
            runtime.candidates.append(result.candidate)
        elif result.reason and result.reason != "Did not meet signal criteria":
            runtime.failures.append(f"{ticker}: {result.reason}")
            runtime.logger.warning("%s: %s", ticker, result.reason)


def _decorate_candidates(runtime: _ScanRuntime) -> None:
    runtime.candidates.sort(key=lambda c: c.get("score_value", 0.0), reverse=True)
    for candidate in runtime.candidates:
        _apply_currency_display(candidate, runtime.fx_rate, runtime.fx_meta_note)
        if candidate.get("currency", "KRW").upper() != "USD":
            continue

        holiday_entry: HolidayEntry | None = None
        date_key = runtime.latest_dates.get(candidate.get("ticker", ""))
        if date_key:
            holiday_entry = runtime.us_holidays_cache.get(date_key)
            if not holiday_entry:
                try:
                    date_obj = dt.datetime.strptime(date_key, "%Y%m%d").date()
                    holiday_entry = lookup_holiday(runtime.cfg.data_dir, "US", date_obj)
                except ValueError:
                    holiday_entry = None

        if holiday_entry:
            status = "Open" if holiday_entry.is_open else "Holiday"
            note = holiday_entry.note or ""
            candidate["market_status"] = f"US {status}{(' - ' + note) if note else ''}"
        else:
            candidate["market_status"] = f"US market {us_market_status()}"


def _write_scan_report(runtime: _ScanRuntime) -> str:
    return write_report(
        report_dir=runtime.cfg.report_dir,
        provider=runtime.cfg.data_provider,
        universe_count=len(runtime.tickers),
        candidates=runtime.candidates,
        failures=runtime.failures,
        cache_hint=runtime.cache_hint,
        report_type="buy",
        strategy_mode=runtime.cfg.strategy_mode,
    )


def run_scan(
    *,
    limit: int | None,
    watchlist_path: str | None,
    provider: str | None,
    screener_limit: int | None = None,
    universe: str | None = None,
) -> int:
    logger = logging.getLogger(__name__)
    try:
        cfg: Config = load_config(provider_override=provider, limit_override=limit)
    except (ConfigLoadError, HoldingsLoadError) as exc:
        logger.error("Configuration loading failed: %s", exc)
        return 1

    runtime = _ScanRuntime(
        cfg=cfg,
        logger=logger,
        tickers=_load_scan_tickers(cfg, watchlist_path),
    )
    effective_screener_limit: int = (
        cfg.screener_limit if screener_limit is None else screener_limit
    )
    screener_enabled, screener_only = _resolve_screener_flags(cfg, universe)

    _initialize_provider(runtime, screener_enabled=screener_enabled)
    _run_screeners(
        runtime,
        screener_enabled=screener_enabled,
        screener_only=screener_only,
        screener_limit=effective_screener_limit,
    )
    _resolve_scan_fx(runtime)
    _collect_market_data(runtime)

    if not runtime.tickers:
        msg = "No tickers provided (watchlist empty or missing)"
        runtime.failures.append(msg)
        runtime.logger.error(msg)
        runtime.fatal_failure = True

    _evaluate_candidates(runtime)
    _decorate_candidates(runtime)

    if runtime.tickers and not runtime.market_data:
        runtime.fatal_failure = True
        runtime.logger.error("Failed to retrieve market data for requested tickers")

    out_path = _write_scan_report(runtime)
    runtime.logger.info("Buy report written to: %s", out_path)

    if runtime.fatal_failure:
        runtime.logger.error(
            "Scan completed with fatal errors. See failures section in report."
        )
        return 1
    if runtime.failures:
        runtime.logger.warning("Scan completed with warnings. See report for details.")
    return 0
