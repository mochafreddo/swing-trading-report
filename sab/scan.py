from __future__ import annotations

import datetime as dt
import logging
import math
from typing import Any

from .config import Config, load_config, load_watchlist
from .data.cache import load_json, save_json
from .data.holiday_cache import HolidayEntry, lookup_holiday, merge_holidays
from .data.kis_client import KISAuthError, KISClient, KISClientError, KISCredentials
from .data.pykrx_client import (
    PykrxClient,
    PykrxClientError,
    PykrxNotInstalledError,
)
from .fx import resolve_fx_rate
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
from .utils.market_time import us_market_status


def _infer_env_from_base(base_url: str) -> str:
    return "demo" if "vts" in base_url.lower() else "real"


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


def run_scan(
    *,
    limit: int | None,
    watchlist_path: str | None,
    provider: str | None,
    screener_limit: int | None = None,
    universe: str | None = None,
) -> int:
    logger = logging.getLogger(__name__)
    cfg: Config = load_config(provider_override=provider, limit_override=limit)

    resolved_watchlist_path = watchlist_path or cfg.watchlist_path or "watchlist.txt"
    tickers = load_watchlist(resolved_watchlist_path)
    if cfg.screen_limit and tickers:
        tickers = tickers[: cfg.screen_limit]

    failures: list[str] = []
    market_data: dict[str, list[dict]] = {}
    cache_hint: str | None = None
    fatal_failure = False

    kis_client: KISClient | None = None
    pykrx_client: PykrxClient | None = None
    pykrx_import_error: str | None = None
    pykrx_warning_added = False
    screener_meta_map: dict[str, dict[str, Any]] = {}

    def ensure_pykrx_client() -> PykrxClient | None:
        nonlocal pykrx_client, pykrx_import_error
        if pykrx_client is not None:
            return pykrx_client
        if pykrx_import_error:
            return None
        try:
            pykrx_client = PykrxClient()
            logger.info("PyKRX client initialized for fallback/provider usage")
            return pykrx_client
        except PykrxNotInstalledError as exc:
            pykrx_import_error = str(exc)
            logger.warning("PyKRX unavailable: %s", exc)
        except PykrxClientError as exc:
            pykrx_import_error = str(exc)
            logger.error("PyKRX init failed: %s", exc)
        return None

    if screener_limit is None:
        screener_limit = cfg.screener_limit

    if universe == "watchlist":
        screener_enabled = False
        screener_only = False
    elif universe == "screener":
        screener_enabled = True
        screener_only = True
    elif universe == "both":
        screener_enabled = True
        screener_only = False
    else:
        screener_enabled = cfg.screener_enabled
        screener_only = cfg.screener_only if screener_enabled else False

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
        if screener_enabled:
            msg = "Screener currently supports KIS provider only."
            failures.append(msg)
            logger.error(msg)
            fatal_failure = True

    if screener_enabled:
        if not kis_client:
            msg = "Screener enabled but KIS client unavailable."
            failures.append(msg)
            logger.error(msg)
            fatal_failure = True
        else:
            total_added = 0
            # KR screener
            if "KR" in cfg.universe_markets:
                req = ScreenRequest(
                    limit=screener_limit,
                    min_price=cfg.min_price,
                    min_dollar_volume=cfg.min_dollar_volume,
                )
                screener = KISScreener(
                    kis_client,
                    cache_dir=cfg.data_dir,
                    cache_ttl_minutes=cfg.screener_cache_ttl_minutes,
                )
                screen_result = screener.screen(req)
                kr_tickers = screen_result.tickers
                screener_meta_map.update(screen_result.metadata.get("by_ticker", {}))
                cache_status = screen_result.metadata.get("cache_status", "refresh")
                if not screener_only:
                    if tickers:
                        logger.info("Screener combined with watchlist (%s tickers)", len(tickers))
                    tickers = list(dict.fromkeys(tickers + kr_tickers))
                else:
                    tickers = kr_tickers
                total_added += len(kr_tickers)
                logger.info(
                    "KR screener selected %s tickers (cache: %s)", len(kr_tickers), cache_status
                )

            # US screener (simple defaults)
            if "US" in cfg.universe_markets:
                us_tickers: list[str] = []
                us_source: str | None = None
                if cfg.us_screener_mode == "kis":
                    try:
                        kscr = KUS(kis_client)
                        kres = kscr.screen(
                            KUSReq(
                                limit=cfg.us_screener_limit or screener_limit,
                                metric=cfg.us_screener_metric,
                            )
                        )
                        us_tickers = kres.tickers
                        if us_tickers:
                            us_source = "kis_overseas_rank"
                        else:
                            logger.warning(
                                "US KIS screener returned 0 tickers; falling back to defaults if configured"
                            )
                    except Exception as exc:
                        logger.warning("US KIS screener failed (%s); falling back to defaults", exc)
                if not us_tickers and cfg.us_screener_defaults:
                    us_scr = USScreener(cfg.us_screener_defaults)
                    us_res = us_scr.screen(USScreenRequest(limit=screener_limit))
                    us_tickers = us_res.tickers
                    if us_tickers:
                        fallback_label = (
                            "us_defaults (fallback)"
                            if cfg.us_screener_mode == "kis"
                            else "us_defaults"
                        )
                        us_source = fallback_label
                        if cfg.us_screener_mode == "kis":
                            logger.info(
                                "US defaults list used as fallback (%s tickers)", len(us_tickers)
                            )
                    else:
                        logger.warning(
                            "US defaults list configured but returned zero tickers; US universe skipped"
                        )
                elif not us_tickers:
                    logger.warning(
                        "US screener produced no tickers and no defaults configured; US universe skipped"
                    )
                if not screener_only:
                    tickers = list(dict.fromkeys(tickers + us_tickers))
                else:
                    # if screener_only but both KR and US enabled, prefer combined
                    tickers = list(dict.fromkeys(us_tickers + (tickers or [])))
                total_added += len(us_tickers)
                logger.info(
                    "US screener selected %s tickers (mode=%s, source=%s)",
                    len(us_tickers),
                    cfg.us_screener_mode,
                    us_source or "none",
                )

            if total_added == 0:
                logger.warning(
                    "Screener enabled but no markets selected or no defaults configured for US"
                )

    def _split_overseas(t: str) -> tuple[str, str | None]:
        # Accept formats: SYMBOL.US (default NASD), SYMBOL.NASD/NYSE/AMEX
        if "." not in t:
            return t, None
        base, suff = t.rsplit(".", 1)
        return base.strip().upper(), suff.strip().upper()

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
        return mapping.get(suffix, None)

    ticker_currency: dict[str, str] = {t: _infer_currency(t) for t in tickers}
    fx_rate: float | None = None
    fx_meta_note: str | None = None
    resolved_rate, resolved_note, fx_messages = resolve_fx_rate(
        cfg=cfg,
        ticker_currency=ticker_currency,
        tickers=tickers,
        kis_client=kis_client,
        logger=logger,
    )
    fx_rate = resolved_rate
    fx_meta_note = resolved_note
    if fx_messages:
        failures.extend(fx_messages)

    us_holidays_cache: dict[str, HolidayEntry] = {}
    latest_dates: dict[str, str] = {}

    def refresh_us_holidays() -> dict[str, HolidayEntry]:
        if not kis_client:
            return {}
        try:
            now = dt.datetime.now()
            start = now.strftime("%Y%m%d")
            end = (now + dt.timedelta(days=30)).strftime("%Y%m%d")
        except Exception:
            start = end = dt.date.today().strftime("%Y%m%d")
        try:
            items = kis_client.overseas_holidays(
                country_code="US",
                start_date=start,
                end_date=end,
            )
        except KISClientError as exc:
            msg = str(exc)
            if "HTTP 404" in msg:
                logger.info("US holiday API returned 404 (no entries from %s to %s)", start, end)
                return {}
            logger.warning("Failed to refresh US holidays: %s", msg)
            return {}
        return merge_holidays(cfg.data_dir, "US", items)

    if cfg.data_provider == "kis" and kis_client:
        # Preload US holiday cache once when needed
        if "US" in cfg.universe_markets or any(
            ticker_currency[t].upper() == "USD" for t in ticker_currency
        ):
            us_holidays_cache = refresh_us_holidays()
        for ticker in tickers:
            base_symbol, suffix = _split_overseas(ticker)
            exch = _excd_from_suffix(suffix)
            # Cache key reflects market to avoid collisions
            cache_key = f"candles_overseas_{exch}_{base_symbol}" if exch else f"candles_{ticker}"
            cached = load_json(cfg.data_dir, cache_key)
            if isinstance(cached, list) and cached:
                market_data[ticker] = cached
                last_date = str(cached[-1].get("date") or "")
                if last_date:
                    latest_dates[ticker] = last_date
            try:
                if exch:
                    candles = kis_client.overseas_daily_candles(
                        symbol=base_symbol, exchange=exch, count=max(cfg.min_history_bars, 200)
                    )
                else:
                    candles = kis_client.daily_candles(
                        base_symbol, count=max(cfg.min_history_bars, 200)
                    )
                if candles:
                    market_data[ticker] = candles
                    save_json(cfg.data_dir, cache_key, candles)
                    last_date = str(candles[-1].get("date") or "")
                    if last_date:
                        latest_dates[ticker] = last_date
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
                    fallback_error: str | None = None
                    if fallback_client is not None and not exch:
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
                                market_data[ticker] = candles
                                last_date = str(candles[-1].get("date") or "")
                                if last_date:
                                    latest_dates[ticker] = last_date
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
                    else:
                        fallback_error = (
                            pykrx_import_error if not exch else "Overseas symbol; no PyKRX fallback"
                        )

                    msg = f"{ticker}: {exc}"
                    if fallback_client is None and fallback_error:
                        msg += f" ({fallback_error})"
                    failures.append(msg)
                    logger.error(msg)
    elif cfg.data_provider == "pykrx" and pykrx_client:
        for ticker in tickers:
            try:
                candles = pykrx_client.daily_candles(ticker, count=max(cfg.min_history_bars, 200))
            except PykrxClientError as exc:
                msg = f"{ticker}: PyKRX error ({exc})"
                failures.append(msg)
                logger.error(msg)
                continue

            if candles:
                market_data[ticker] = candles
                logger.info("Fetched %s candles via PyKRX for %s", len(candles), ticker)
                last_date = str(candles[-1].get("date") or "")
                if last_date:
                    latest_dates[ticker] = last_date
            else:
                msg = f"{ticker}: PyKRX returned no data"
                failures.append(msg)
                logger.warning(msg)

        if tickers and not pykrx_warning_added:
            failures.append(
                "Warning: PyKRX provider data is end-of-day and may lag intraday feeds."
            )
            pykrx_warning_added = True
    else:
        if tickers:
            failures.append(f"Provider '{cfg.data_provider}' not yet implemented")
            fatal_failure = True

    if not tickers:
        msg = "No tickers provided (watchlist empty or missing)"
        failures.append(msg)
        logger.error(msg)
        fatal_failure = True

    candidates = []
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
    for ticker in tickers:
        candles = market_data.get(ticker)
        if not candles:
            continue
        meta = dict(screener_meta_map.get(ticker, {}))
        meta["currency"] = ticker_currency.get(ticker, "KRW")
        if fx_rate is not None:
            meta["usd_krw_rate"] = fx_rate
        result = evaluate_ticker(ticker, candles, eval_settings, meta)
        if result.candidate:
            candidates.append(result.candidate)
        elif result.reason and result.reason != "Did not meet signal criteria":
            failures.append(f"{ticker}: {result.reason}")
            logger.warning("%s: %s", ticker, result.reason)

    candidates.sort(key=lambda c: c.get("score_value", 0.0), reverse=True)

    for candidate in candidates:
        _apply_currency_display(candidate, fx_rate, fx_meta_note)
        if candidate.get("currency", "KRW").upper() == "USD":
            holiday_entry: HolidayEntry | None = None
            date_key = latest_dates.get(candidate.get("ticker", ""))
            if date_key:
                holiday_entry = us_holidays_cache.get(date_key)
                if not holiday_entry:
                    try:
                        date_obj = dt.datetime.strptime(date_key, "%Y%m%d").date()
                        holiday_entry = lookup_holiday(cfg.data_dir, "US", date_obj)
                    except ValueError:
                        holiday_entry = None
            if holiday_entry:
                status = "Open" if holiday_entry.is_open else "Holiday"
                note = holiday_entry.note or ""
                candidate["market_status"] = f"US {status}{(' - ' + note) if note else ''}"
            else:
                candidate["market_status"] = f"US market {us_market_status()}"

    if tickers and not market_data:
        fatal_failure = True
        logger.error("Failed to retrieve market data for requested tickers")

    out_path = write_report(
        report_dir=cfg.report_dir,
        provider=cfg.data_provider,
        universe_count=len(tickers),
        candidates=candidates,
        failures=failures,
        cache_hint=cache_hint,
        report_type="buy",
    )

    logger.info("Buy report written to: %s", out_path)

    if fatal_failure:
        logger.error("Scan completed with fatal errors. See failures section in report.")
        return 1

    if failures:
        logger.warning("Scan completed with warnings. See report for details.")

    return 0
