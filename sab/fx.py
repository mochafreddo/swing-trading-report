from __future__ import annotations

import datetime as dt
import logging

from .config import Config
from .data.cache import load_json, save_json
from .data.kis_client import KISClient, KISClientError

SUFFIX_TO_EXCD = {
    "US": "NAS",
    "NASDAQ": "NAS",
    "NASD": "NAS",
    "NAS": "NAS",
    "NYSE": "NYS",
    "NYS": "NYS",
    "AMEX": "AMS",
    "AMS": "AMS",
}
FX_CACHE_KEY = "fx_usdkrw"
DEFAULT_SYMBOL = "SPY"
DEFAULT_EXCHANGE = "NAS"


def resolve_fx_rate(
    *,
    cfg: Config,
    ticker_currency: dict[str, str],
    tickers: list[str],
    kis_client: KISClient | None,
    logger: logging.Logger,
) -> tuple[float | None, str | None, list[str]]:
    """Resolve USD/KRW rate according to fx_mode."""

    failures: list[str] = []
    manual_rate = cfg.usd_krw_rate
    mode = (cfg.fx_mode or "manual").strip().lower()

    if mode == "off":
        return None, None, failures

    if mode != "kis":
        if manual_rate is None:
            msg = "FX_MODE=manual but USD_KRW_RATE/fx.usdkrw is missing; USD/KRW display disabled."
            logger.warning(msg)
            failures.append(msg)
            return None, None, failures
        return manual_rate, "manual", failures

    if not kis_client:
        msg = "FX_MODE=kis requires KIS provider; falling back to USD_KRW_RATE if available."
        logger.warning(msg)
        failures.append(msg)
        fallback_rate, fallback_note = _manual_fallback(manual_rate)
        return fallback_rate, fallback_note, failures

    symbol, exchange, symbol_label = _select_symbol(cfg, ticker_currency, tickers)

    cached_rate = _load_cached_rate(cfg.data_dir, cfg.fx_cache_ttl_minutes)
    if cached_rate:
        rate, cached_symbol, cached_exchange, age_minutes = cached_rate
        if rate is not None:
            label = _format_cache_label(
                cached_symbol or symbol, cached_exchange or exchange, age_minutes
            )
            logger.info("FX rate cache hit (%s)", label)
            return rate, label, failures

    try:
        detail = kis_client.overseas_price_detail(symbol=symbol, exchange=exchange)
    except KISClientError as exc:
        msg = f"FX_MODE=kis failed to fetch price-detail ({exc}); using cached/manual rate if available."
        logger.warning(msg)
        failures.append(msg)
        cached = _load_cached_rate(
            cfg.data_dir, cfg.fx_cache_ttl_minutes * 12
        )  # allow stale cache as last resort
        if cached:
            rate, cached_symbol, cached_exchange, age_minutes = cached
            if rate is not None:
                label = _format_cache_label(
                    cached_symbol or symbol,
                    cached_exchange or exchange,
                    age_minutes,
                )
                logger.info("Using stale FX cache (%s)", label)
                return rate, label, failures
        fallback_rate, fallback_note = _manual_fallback(manual_rate)
        return fallback_rate, fallback_note, failures

    rate = _to_float(detail.get("t_rate"))
    if rate is None:
        msg = "FX_MODE=kis response missing t_rate; using manual rate if available."
        logger.warning(msg)
        failures.append(msg)
        fallback_rate, fallback_note = _manual_fallback(manual_rate)
        return fallback_rate, fallback_note, failures

    _save_cached_rate(cfg.data_dir, rate, symbol, exchange)
    note = f"KIS live {symbol_label}"
    logger.info("FX rate fetched via KIS (%s): %.2f", symbol_label, rate)
    return rate, note, failures


def _manual_fallback(rate: float | None) -> tuple[float | None, str | None]:
    if rate is None:
        return None, None
    return rate, "manual fallback"


def _select_symbol(
    cfg: Config,
    ticker_currency: dict[str, str],
    tickers: list[str],
) -> tuple[str, str, str]:
    if cfg.fx_kis_symbol:
        base, suffix = _split_symbol(cfg.fx_kis_symbol)
        if base:
            exchange = _to_exchange(suffix) or DEFAULT_EXCHANGE
            return base, exchange, _format_symbol_label(base, exchange)

    for ticker in tickers:
        currency = ticker_currency.get(ticker, "KRW")
        if currency and currency.upper() == "USD":
            base, suffix = _split_symbol(ticker)
            if not base:
                continue
            exchange = _to_exchange(suffix) or DEFAULT_EXCHANGE
            return base, exchange, _format_symbol_label(base, exchange)

    # fallback symbol if no USD ticker is available
    base, suffix = _split_symbol(f"{DEFAULT_SYMBOL}.{DEFAULT_EXCHANGE}")
    exchange = _to_exchange(suffix) or DEFAULT_EXCHANGE
    return base, exchange, _format_symbol_label(base, exchange)


def _split_symbol(raw: str | None) -> tuple[str, str | None]:
    if not raw:
        return "", None
    text = raw.strip().upper()
    if "." not in text:
        return text, None
    base, suffix = text.rsplit(".", 1)
    return base.strip(), suffix.strip()


def _to_exchange(suffix: str | None) -> str | None:
    if not suffix:
        return None
    return SUFFIX_TO_EXCD.get(suffix.upper())


def _format_symbol_label(symbol: str, exchange: str) -> str:
    if not symbol:
        return exchange
    return f"{symbol}.{exchange}"


def _format_cache_label(symbol: str, exchange: str, age_minutes: float | None) -> str:
    label = f"KIS cache {_format_symbol_label(symbol, exchange)}"
    if age_minutes is not None:
        label += f" (~{int(age_minutes)}m)"
    return label


def _load_cached_rate(
    data_dir: str | None,
    ttl_minutes: float | None,
) -> tuple[float | None, str | None, str | None, float | None] | None:
    if not data_dir or ttl_minutes is None or ttl_minutes <= 0:
        return None
    cached = load_json(data_dir, FX_CACHE_KEY)
    if not isinstance(cached, dict):
        return None
    rate = _to_float(cached.get("rate"))
    fetched_at_raw = cached.get("fetched_at")
    symbol = cached.get("symbol")
    exchange = cached.get("exchange")
    if fetched_at_raw is None:
        return None
    try:
        fetched_at = dt.datetime.fromisoformat(fetched_at_raw)
    except ValueError:
        return None
    age = (dt.datetime.utcnow() - fetched_at).total_seconds() / 60.0
    if age > ttl_minutes:
        return None
    return rate, symbol, exchange, age


def _save_cached_rate(data_dir: str | None, rate: float, symbol: str, exchange: str) -> None:
    if not data_dir:
        return
    payload = {
        "rate": rate,
        "symbol": symbol,
        "exchange": exchange,
        "fetched_at": dt.datetime.utcnow().isoformat(),
    }
    save_json(data_dir, FX_CACHE_KEY, payload)


def _to_float(val: object | None) -> float | None:
    if val is None or val == "":
        return None
    try:
        return float(str(val).replace(",", ""))
    except (TypeError, ValueError):
        return None
