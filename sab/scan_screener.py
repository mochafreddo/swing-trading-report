from __future__ import annotations

from typing import Any

from .config import Config
from .data.kis_client import KISClientError
from .scan_types import _ScanRuntime
from .tickers import parse_ticker, validate_strict_us_ticker


def _clear_non_screener_baseline_if_needed(
    runtime: _ScanRuntime, *, screener_only: bool
) -> None:
    if not screener_only or not runtime.tickers:
        return
    # Keep existing tickers only when they are already seeded by a screener call.
    if bool(getattr(runtime, "screener_seeded", False)):
        return
    runtime.logger.info(
        "Screener-only mode: ignoring watchlist baseline (%s tickers)",
        len(runtime.tickers),
    )
    runtime.tickers = []


def _load_scan_tickers(
    cfg: Config,
    watchlist_path: str | None,
    *,
    load_watchlist_fn: Any,
) -> list[str]:
    resolved_watchlist_path = watchlist_path or cfg.watchlist_path or "watchlist.txt"
    return load_watchlist_fn(resolved_watchlist_path)  # type: ignore[no-any-return]


def _enforce_ticker_limit(
    runtime: _ScanRuntime,
    *,
    ticker_limit: int | None,
) -> None:
    if ticker_limit is None or ticker_limit <= 0:
        return
    if len(runtime.tickers) <= ticker_limit:
        return

    before = len(runtime.tickers)
    runtime.tickers = runtime.tickers[:ticker_limit]
    if runtime.screener_meta_map:
        runtime.screener_meta_map = {
            ticker: runtime.screener_meta_map[ticker]
            for ticker in runtime.tickers
            if ticker in runtime.screener_meta_map
        }
    runtime.logger.info(
        "Ticker universe capped to %s after watchlist/screener merge (%s -> %s)",
        ticker_limit,
        before,
        len(runtime.tickers),
    )


def _normalize_us_screener_tickers(
    runtime: _ScanRuntime,
    *,
    tickers: list[str],
    source: str,
) -> list[str]:
    normalized_tickers: list[str] = []
    for idx, ticker_raw in enumerate(tickers):
        ticker_text = str(ticker_raw).strip()
        ticker_issue = validate_strict_us_ticker(ticker_text)
        if ticker_issue is not None:
            message = (
                "US screener validation failed: "
                f"source={source}, index={idx}, ticker={ticker_raw!r} ({ticker_issue})"
            )
            runtime.failures.append(message)
            runtime.logger.error(message)
            runtime.fatal_failure = True
            return []
        normalized_tickers.append(parse_ticker(ticker_text).ticker)
    return normalized_tickers


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
    _clear_non_screener_baseline_if_needed(runtime, screener_only=screener_only)
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
    try:
        screen_result = screener.screen(req)
    except KISClientError as exc:
        message = f"KR KIS screener failed ({exc})"
        runtime.failures.append(message)
        if screener_only:
            runtime.logger.error(message)
            runtime.fatal_failure = True
        else:
            runtime.logger.warning(
                "KR KIS screener failed; skipping KR screener for safety (%s)",
                exc,
            )
        return 0
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
        runtime.screener_seeded = bool(runtime.tickers)

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
    screener_limit_from_cli: bool = False,
    screener_only: bool,
    KUSCls: Any,
    KUSReqCls: Any,
    USScreenerCls: Any,
    USScreenRequestCls: Any,
    us_session_info_fn: Any,
    coerce_nday_fn: Any,
    format_ny_now_for_log_fn: Any,
) -> int:
    _clear_non_screener_baseline_if_needed(runtime, screener_only=screener_only)
    if "US" not in runtime.cfg.universe_markets or runtime.kis_client is None:
        return 0

    cfg = runtime.cfg
    if screener_limit_from_cli:
        us_limit = screener_limit
    else:
        us_limit = cfg.us_screener_limit or screener_limit
    us_tickers: list[str] = []
    us_source: str | None = None
    us_nday_used: int | None = None

    session_info = us_session_info_fn(data_dir=cfg.data_dir)
    preferred_nday = coerce_nday_fn(session_info.get("preferred_nday", 1))
    fallback_ndays = (
        [n for n in range(1, 6) if n != preferred_nday]
        if preferred_nday != 0
        else list(range(1, 6))
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
                    limit=us_limit,
                    metric=cfg.us_screener_metric,
                    nday=preferred_nday,
                    fallback_ndays=fallback_ndays,
                )
            )
            us_tickers = kres.tickers
            us_nday_used = kres.metadata.get("nday_used")
            by_ticker_raw = kres.metadata.get("by_ticker", {})
            if isinstance(by_ticker_raw, dict):
                canonical_by_ticker: dict[str, Any] = {}
                for ticker_key, ticker_meta in by_ticker_raw.items():
                    ticker_text = str(ticker_key).strip()
                    if not ticker_text:
                        continue
                    canonical_key = parse_ticker(ticker_text).ticker
                    if isinstance(ticker_meta, dict):
                        canonical_by_ticker[canonical_key] = dict(ticker_meta)
                    else:
                        canonical_by_ticker[canonical_key] = {}
                runtime.screener_meta_map.update(canonical_by_ticker)
            if us_tickers:
                us_source = "kis_overseas_rank"
                runtime.logger.info(
                    "US KIS screener used nday=%s (tried=%s, state=%s)",
                    kres.metadata.get("nday_used"),
                    kres.metadata.get("nday_tried"),
                    session_info.get("state"),
                )
        except ValueError as exc:
            message = f"US KIS screener validation failed ({exc})"
            runtime.failures.append(message)
            if screener_only:
                runtime.logger.error(message)
                runtime.fatal_failure = True
            else:
                runtime.logger.warning(
                    "US KIS screener validation failed; "
                    "skipping US screener for safety (%s)",
                    exc,
                )
            return 0
        except Exception as exc:
            message = f"US KIS screener failed ({exc})"
            runtime.failures.append(message)
            if screener_only:
                runtime.logger.error(message)
                runtime.fatal_failure = True
            else:
                runtime.logger.warning(
                    "US KIS screener failed; skipping US screener for safety (%s)",
                    exc,
                )
            return 0

        if not us_tickers:
            message = (
                "US KIS screener returned 0 tickers; skipping US screener for safety"
            )
            runtime.failures.append(message)
            if screener_only:
                runtime.logger.error(message)
                runtime.fatal_failure = True
            else:
                runtime.logger.warning(message)
            return 0

    if cfg.us_screener_mode != "kis" and not us_tickers and cfg.us_screener_defaults:
        us_scr = USScreenerCls(cfg.us_screener_defaults)
        us_res = us_scr.screen(USScreenRequestCls(limit=us_limit))
        us_tickers = us_res.tickers
        if us_tickers:
            us_source = "us_defaults"
        else:
            runtime.logger.warning(
                "US defaults list configured but returned zero tickers; US universe skipped"
            )
    elif not us_tickers:
        runtime.logger.warning(
            "US screener produced no tickers and no defaults configured; US universe skipped"
        )

    if us_tickers:
        us_tickers = _normalize_us_screener_tickers(
            runtime,
            tickers=us_tickers,
            source=us_source or cfg.us_screener_mode,
        )
        if runtime.fatal_failure:
            return 0

    if not screener_only:
        runtime.tickers = list(dict.fromkeys(runtime.tickers + us_tickers))
    else:
        runtime.tickers = list(dict.fromkeys(runtime.tickers + us_tickers))
        runtime.screener_seeded = bool(runtime.tickers)

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
    screener_limit_from_cli: bool = False,
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
    _clear_non_screener_baseline_if_needed(runtime, screener_only=screener_only)
    if screener_only:
        runtime.screener_seeded = False

    total_added = 0
    total_added += _run_kr_screener(
        runtime,
        screener_limit=screener_limit,
        screener_only=screener_only,
        ScreenRequestCls=ScreenRequestCls,
        KISScreenerCls=KISScreenerCls,
    )
    if runtime.fatal_failure:
        return
    total_added += _run_us_screener(
        runtime,
        screener_limit=screener_limit,
        screener_limit_from_cli=screener_limit_from_cli,
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
