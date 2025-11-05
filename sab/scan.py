from __future__ import annotations

import logging
from typing import Optional

from .config import Config, load_config, load_watchlist
from .data.kis_client import KISAuthError, KISClient, KISClientError, KISCredentials
from .data.cache import load_json, save_json
from .report.markdown import write_report
from .signals.evaluator import evaluate_ticker
from .screener import KISScreener, ScreenRequest


def _infer_env_from_base(base_url: str) -> str:
    return "demo" if "vts" in base_url.lower() else "real"


def run_scan(*, limit: Optional[int], watchlist_path: Optional[str], provider: Optional[str]) -> int:
    logger = logging.getLogger(__name__)
    cfg: Config = load_config(provider_override=provider, limit_override=limit)

    tickers = load_watchlist(watchlist_path)
    if cfg.screen_limit and tickers:
        tickers = tickers[: cfg.screen_limit]

    failures: list[str] = []
    market_data: dict[str, list[dict]] = {}
    cache_hint: Optional[str] = None
    fatal_failure = False

    kis_client: Optional[KISClient] = None

    if cfg.data_provider == "kis":
        if not (cfg.kis_app_key and cfg.kis_app_secret and cfg.kis_base_url):
            msg = (
                "KIS credentials missing. Set KIS_APP_KEY, KIS_APP_SECRET, KIS_BASE_URL in .env (see docs/kis-setup.md)."
            )
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
            kis_client = KISClient(creds, cache_dir=cfg.data_dir)
            cache_hint = kis_client.cache_status
    else:
        if cfg.screener_enabled:
            msg = "Screener currently supports KIS provider only."
            failures.append(msg)
            logger.error(msg)
            fatal_failure = True

    if cfg.screener_enabled:
        if not kis_client:
            msg = "Screener enabled but KIS client unavailable."
            failures.append(msg)
            logger.error(msg)
            fatal_failure = True
        else:
            req = ScreenRequest(limit=cfg.screener_limit)
            screener = KISScreener(kis_client)
            screen_result = screener.screen(req)
            tickers_from_screener = screen_result.tickers
            if not cfg.screener_only:
                if tickers:
                    logger.info("Screener combined with watchlist (%s tickers)", len(tickers))
                tickers = list(dict.fromkeys(tickers + tickers_from_screener))
            else:
                tickers = tickers_from_screener
            logger.info("Screener selected %s tickers", len(tickers_from_screener))

    if cfg.data_provider == "kis" and kis_client:
        for ticker in tickers:
            cache_key = f"candles_{ticker}"
            cached = load_json(cfg.data_dir, cache_key)
            if isinstance(cached, list) and cached:
                market_data[ticker] = cached
            try:
                candles = kis_client.daily_candles(ticker, count=200)
                if candles:
                    market_data[ticker] = candles
                    save_json(cfg.data_dir, cache_key, candles)
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
                    msg = f"{ticker}: {exc}"
                    failures.append(msg)
                    logger.error(msg)
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
    for ticker in tickers:
        candles = market_data.get(ticker)
        if not candles:
            continue
        result = evaluate_ticker(ticker, candles)
        if result.candidate:
            candidates.append(result.candidate)
        elif result.reason and result.reason != "Did not meet signal criteria":
            failures.append(f"{ticker}: {result.reason}")
            logger.warning("%s: %s", ticker, result.reason)

    candidates.sort(key=lambda c: c.get("score", 0.0), reverse=True)

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
    )

    logger.info("Report written to: %s", out_path)

    if fatal_failure:
        logger.error("Scan completed with fatal errors. See failures section in report.")
        return 1

    if failures:
        logger.warning("Scan completed with warnings. See report for details.")

    return 0
