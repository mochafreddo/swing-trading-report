from __future__ import annotations

from typing import Any

from .config import Config
from .scan_types import _ScanRuntime


def _load_scan_tickers(
    cfg: Config,
    watchlist_path: str | None,
    *,
    load_watchlist_fn: Any,
) -> list[str]:
    resolved_watchlist_path = watchlist_path or cfg.watchlist_path or "watchlist.txt"
    tickers = load_watchlist_fn(resolved_watchlist_path)
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


def _run_kr_screener(
    runtime: _ScanRuntime,
    *,
    screener_limit: int,
    screener_only: bool,
    ScreenRequestCls: Any,
    KISScreenerCls: Any,
) -> int:
    if "KR" not in runtime.cfg.universe_markets or runtime.kis_client is None:
        return 0

    req = ScreenRequestCls(
        limit=screener_limit,
        min_price=runtime.cfg.min_price,
        min_dollar_volume=runtime.cfg.min_dollar_volume,
    )
    screener = KISScreenerCls(
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
    runtime: _ScanRuntime,
    *,
    screener_limit: int,
    screener_only: bool,
    KUSCls: Any,
    KUSReqCls: Any,
    USScreenerCls: Any,
    USScreenRequestCls: Any,
    us_session_info_fn: Any,
    coerce_nday_fn: Any,
    format_ny_now_for_log_fn: Any,
) -> int:
    if "US" not in runtime.cfg.universe_markets or runtime.kis_client is None:
        return 0

    cfg = runtime.cfg
    us_tickers: list[str] = []
    us_source: str | None = None
    us_nday_used: int | None = None

    session_info = us_session_info_fn(data_dir=cfg.data_dir)
    preferred_nday = coerce_nday_fn(session_info.get("preferred_nday", 1))
    fallback_ndays = (
        [n for n in range(1, 6) if n != preferred_nday]
        if preferred_nday != 0
        else [n for n in range(1, 6)]
    )
    ny_now_str = format_ny_now_for_log_fn(session_info)
    runtime.logger.info(
        "US session state=%s holiday=%s preferred_nday=%s ny_now=%s",
        session_info.get("state"),
        session_info.get("is_holiday"),
        preferred_nday,
        ny_now_str,
    )

    if cfg.us_screener_mode == "kis":
        try:
            kscr = KUSCls(runtime.kis_client)
            kres = kscr.screen(
                KUSReqCls(
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
        us_scr = USScreenerCls(cfg.us_screener_defaults)
        us_res = us_scr.screen(USScreenRequestCls(limit=screener_limit))
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
    ScreenRequestCls: Any,
    KISScreenerCls: Any,
    KUSCls: Any,
    KUSReqCls: Any,
    USScreenerCls: Any,
    USScreenRequestCls: Any,
    us_session_info_fn: Any,
    coerce_nday_fn: Any,
    format_ny_now_for_log_fn: Any,
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
        ScreenRequestCls=ScreenRequestCls,
        KISScreenerCls=KISScreenerCls,
    )
    total_added += _run_us_screener(
        runtime,
        screener_limit=screener_limit,
        screener_only=screener_only,
        KUSCls=KUSCls,
        KUSReqCls=KUSReqCls,
        USScreenerCls=USScreenerCls,
        USScreenRequestCls=USScreenRequestCls,
        us_session_info_fn=us_session_info_fn,
        coerce_nday_fn=coerce_nday_fn,
        format_ny_now_for_log_fn=format_ny_now_for_log_fn,
    )
    if total_added == 0:
        runtime.logger.warning(
            "Screener enabled but no markets selected or no defaults configured for US"
        )
