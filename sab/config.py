from __future__ import annotations

import os
from dataclasses import dataclass, field
from typing import Any, Optional, overload
from urllib.parse import urlparse

from .config_loader import load_yaml_config
from .holdings_loader import HoldingsData, load_holdings


def _from_nested(d: dict[str, Any], path: str, default: Any = None) -> Any:
    current: Any = d
    for part in path.split("."):
        if not isinstance(current, dict) or part not in current:
            return default
        current = current[part]
    return current


def _load_dotenv_if_available() -> None:
    try:
        from dotenv import load_dotenv  # type: ignore

        load_dotenv(override=False)
    except Exception:
        # dotenv is optional; ignore if missing
        pass


@dataclass(frozen=True)
class Config:
    data_provider: str = "kis"  # or pykrx
    kis_app_key: Optional[str] = None
    kis_app_secret: Optional[str] = None
    kis_base_url: Optional[str] = None
    screen_limit: int = 30
    report_dir: str = "reports"
    data_dir: str = "data"
    watchlist_path: Optional[str] = None
    screener_enabled: bool = False
    screener_limit: int = 20
    screener_only: bool = False
    use_sma200_filter: bool = False
    gap_atr_multiplier: float = 1.0
    min_dollar_volume: float = 0.0
    min_history_bars: int = 120
    exclude_etf_etn: bool = False
    require_slope_up: bool = False
    kis_min_interval_ms: Optional[float] = None
    screener_cache_ttl_minutes: float = 5.0
    min_price: float = 0.0
    rs_lookback_days: int = 20
    rs_benchmark_return: float = 0.0
    holdings_path: Optional[str] = None
    holdings: HoldingsData = field(default_factory=lambda: load_holdings(None))
    sell_atr_multiplier: float = 1.0
    sell_time_stop_days: int = 10
    sell_require_sma200: bool = True
    sell_ema_short: int = 20
    sell_ema_long: int = 50
    sell_rsi_period: int = 14
    sell_rsi_floor: float = 50.0
    sell_rsi_floor_alt: float = 30.0
    sell_min_bars: int = 20
    universe_markets: list[str] = field(default_factory=lambda: ["KR"])  # e.g., ["KR", "US"]
    us_screener_defaults: list[str] = field(default_factory=list)
    us_screener_mode: str = "defaults"  # 'defaults' or 'kis'
    us_screener_metric: str = "volume"  # 'volume' | 'market_cap' | 'value'
    us_screener_limit: int = 20
    usd_krw_rate: Optional[float] = None
    fx_mode: str = "manual"  # 'manual' | 'kis' | 'off'
    fx_cache_ttl_minutes: float = 10.0
    fx_kis_symbol: Optional[str] = None
    # Per-market thresholds
    us_min_price: Optional[float] = None
    us_min_dollar_volume: Optional[float] = None


def _normalize_kis_base(url: Optional[str]) -> Optional[str]:
    if not url:
        return None

    url = url.strip()
    if not url:
        return None

    if not url.startswith("http://") and not url.startswith("https://"):
        url = f"https://{url}"

    parsed = urlparse(url)
    if not parsed.scheme or not parsed.hostname:
        return url.rstrip("/")

    host = parsed.hostname.lower()
    port = parsed.port
    if port is None:
        if "openapivts" in host:
            port = 29443
        else:
            port = 9443

    netloc = parsed.hostname if port in (80, 443) else f"{parsed.hostname}:{port}"
    normalized = f"{parsed.scheme}://{netloc}"
    return normalized.rstrip("/")


def load_config(
    *,
    provider_override: Optional[str] = None,
    limit_override: Optional[int] = None,
) -> Config:
    yaml_cfg = load_yaml_config().raw
    _load_dotenv_if_available()

    def from_yaml(path: str, default: Any = None) -> Any:
        return _from_nested(yaml_cfg, path, default)

    def parse_bool(val: Any, default: bool = False) -> bool:
        if isinstance(val, bool):
            return val
        if isinstance(val, str):
            return val.strip().lower() in {"1", "true", "yes", "y", "on"}
        if val is None:
            return default
        return bool(val)

    def parse_int(val: Any, default: int) -> int:
        try:
            return int(val)
        except (TypeError, ValueError):
            return default

    @overload
    def parse_float(val: Any, default: float) -> float:
        ...

    @overload
    def parse_float(val: Any, default: None) -> float | None:
        ...

    def parse_float(val: Any, default: float | None) -> float | None:
        try:
            return float(val)
        except (TypeError, ValueError):
            return default

    def env_bool(key: str, path: str, default: bool) -> bool:
        env_val = os.getenv(key)
        if env_val is not None:
            return parse_bool(env_val, default)
        return parse_bool(from_yaml(path, default), default)

    def env_int(key: str, path: str, default: int) -> int:
        env_val = os.getenv(key)
        if env_val is not None:
            return parse_int(env_val, default)
        return parse_int(from_yaml(path, default), default)

    def env_float(key: str, path: str, default: float) -> float:
        env_val = os.getenv(key)
        if env_val is not None:
            return parse_float(env_val, default)
        return parse_float(from_yaml(path, default), default)

    def env_str(key: str, path: str, default: Optional[str]) -> Optional[str]:
        env_val = os.getenv(key)
        if env_val is not None:
            return env_val
        val = from_yaml(path, default)
        if val is None:
            return default
        return str(val)

    provider = (
        provider_override
        or os.getenv("DATA_PROVIDER")
        or from_yaml("data.provider", "kis")
        or "kis"
    )
    provider = provider.lower()
    screen_limit_cfg = env_int("SCREEN_LIMIT", "data.screen_limit", 30)

    screen_limit = limit_override if limit_override is not None else screen_limit_cfg

    screener_enabled = env_bool("SCREENER_ENABLED", "screener.enabled", False)
    screener_limit = env_int("SCREENER_LIMIT", "screener.limit", 20)
    screener_only = env_bool("SCREENER_ONLY", "screener.only", False)

    use_sma200_filter = env_bool("USE_SMA200_FILTER", "strategy.use_sma200_filter", False)
    require_slope_up = env_bool("REQUIRE_SLOPE_UP", "strategy.require_slope_up", False)
    exclude_etf_etn = env_bool("EXCLUDE_ETF_ETN", "strategy.exclude_etf_etn", False)

    gap_atr_multiplier = env_float("GAP_ATR_MULTIPLIER", "strategy.gap_atr_multiplier", 1.0)
    min_dollar_volume = env_float("MIN_DOLLAR_VOLUME", "screener.min_dollar_volume", 0.0)
    min_history_bars = env_int("MIN_HISTORY_BARS", "strategy.min_history_bars", 120)

    kis_min_interval_ms = None
    _ms_env = os.getenv("KIS_MIN_INTERVAL_MS")
    if _ms_env is not None:
        try:
            kis_min_interval_ms = float(_ms_env)
        except ValueError:
            kis_min_interval_ms = None
    else:
        kis_min_interval_ms = parse_float(from_yaml("kis.min_interval_ms"), None)  # type: ignore[arg-type]

    screener_cache_ttl_minutes = env_float("SCREENER_CACHE_TTL", "screener.cache_ttl_minutes", 5.0)
    min_price = env_float("MIN_PRICE", "screener.min_price", 0.0)
    rs_lookback_days = env_int("RS_LOOKBACK_DAYS", "strategy.rs_lookback_days", 20)
    rs_benchmark_return = env_float("RS_BENCHMARK_RETURN", "strategy.rs_benchmark_return", 0.0)

    holdings_path = env_str("HOLDINGS_FILE", "files.holdings", None)
    watchlist_path = env_str("WATCHLIST_FILE", "files.watchlist", None)
    holdings_data = load_holdings(holdings_path)

    # Universe markets (KR,US)
    markets_env = os.getenv("UNIVERSE_MARKETS")
    if markets_env is not None:
        universe_markets = [m.strip().upper() for m in markets_env.split(",") if m.strip()]
    else:
        raw_markets = from_yaml("universe.markets", ["KR"]) or ["KR"]
        universe_markets = [str(m).strip().upper() for m in raw_markets if str(m).strip()]

    # US screener defaults (yaml-only)
    us_screener_defaults_raw = from_yaml("screener.us_defaults", []) or []
    us_screener_defaults = [
        str(t).strip().upper() for t in us_screener_defaults_raw if str(t).strip()
    ]
    us_screener_mode = str(from_yaml("screener.us_mode", "defaults") or "defaults").strip().lower()
    us_screener_metric = str(from_yaml("screener.us_metric", "volume") or "volume").strip().lower()
    us_screener_limit = env_int("US_SCREENER_LIMIT", "screener.us_limit", 20)
    usd_krw_rate: Optional[float] = None
    env_fx = os.getenv("USD_KRW_RATE")
    if env_fx is not None:
        try:
            usd_krw_rate = float(env_fx)
        except (TypeError, ValueError):
            usd_krw_rate = None
    else:
        fx_yaml = from_yaml("fx.usdkrw")
        if fx_yaml is not None:
            try:
                usd_krw_rate = float(fx_yaml)
            except (TypeError, ValueError):
                usd_krw_rate = None

    fx_mode_raw = os.getenv("FX_MODE") or from_yaml("fx.mode", "manual") or "manual"
    fx_mode = str(fx_mode_raw).strip().lower()
    if fx_mode not in {"manual", "kis", "off"}:
        fx_mode = "manual"
    fx_cache_ttl_minutes = env_float("FX_CACHE_TTL", "fx.cache_ttl_minutes", 10.0)
    fx_kis_symbol_raw = env_str("FX_KIS_SYMBOL", "fx.kis_symbol", None)
    fx_kis_symbol = fx_kis_symbol_raw.strip().upper() if fx_kis_symbol_raw else None

    # Per-market thresholds (USD units for US)
    us_min_price = None
    _us_min_price_yaml = from_yaml("screener.us.min_price")
    if _us_min_price_yaml is not None:
        try:
            us_min_price = float(_us_min_price_yaml)
        except (TypeError, ValueError):
            us_min_price = None

    us_min_dollar_volume = None
    _us_min_dv_yaml = from_yaml("screener.us.min_dollar_volume")
    if _us_min_dv_yaml is not None:
        try:
            us_min_dollar_volume = float(_us_min_dv_yaml)
        except (TypeError, ValueError):
            us_min_dollar_volume = None

    sell_atr_multiplier = env_float("SELL_ATR_MULTIPLIER", "sell.atr_trail_multiplier", 1.0)
    sell_time_stop_days = env_int("SELL_TIME_STOP_DAYS", "sell.time_stop_days", 10)
    sell_require_sma200 = env_bool("SELL_REQUIRE_SMA200", "sell.require_sma200", True)
    sell_ema_short = env_int("SELL_EMA_SHORT", "sell.ema_short", 20)
    sell_ema_long = env_int("SELL_EMA_LONG", "sell.ema_long", 50)
    sell_rsi_period = env_int("SELL_RSI_PERIOD", "sell.rsi_period", 14)
    sell_rsi_floor = env_float("SELL_RSI_FLOOR", "sell.rsi_floor", 50.0)
    sell_rsi_floor_alt = env_float("SELL_RSI_FLOOR_ALT", "sell.rsi_floor_alt", 30.0)
    sell_min_bars = env_int("SELL_MIN_BARS", "sell.min_bars", 20)

    return Config(
        data_provider=provider,
        kis_app_key=os.getenv("KIS_APP_KEY") or from_yaml("kis.app_key"),
        kis_app_secret=os.getenv("KIS_APP_SECRET") or from_yaml("kis.app_secret"),
        kis_base_url=_normalize_kis_base(os.getenv("KIS_BASE_URL") or from_yaml("kis.base_url")),
        screen_limit=screen_limit,
        report_dir=os.getenv("REPORT_DIR") or from_yaml("data.report_dir", "reports"),
        data_dir=os.getenv("DATA_DIR") or from_yaml("data.data_dir", "data"),
        watchlist_path=watchlist_path,
        screener_enabled=screener_enabled,
        screener_limit=screener_limit,
        screener_only=screener_only,
        use_sma200_filter=use_sma200_filter,
        gap_atr_multiplier=gap_atr_multiplier,
        min_dollar_volume=min_dollar_volume,
        min_history_bars=min_history_bars,
        exclude_etf_etn=exclude_etf_etn,
        require_slope_up=require_slope_up,
        kis_min_interval_ms=kis_min_interval_ms,
        screener_cache_ttl_minutes=screener_cache_ttl_minutes,
        min_price=min_price,
        rs_lookback_days=rs_lookback_days,
        rs_benchmark_return=rs_benchmark_return,
        holdings_path=holdings_path,
        holdings=holdings_data,
        sell_atr_multiplier=sell_atr_multiplier,
        sell_time_stop_days=sell_time_stop_days,
        sell_require_sma200=sell_require_sma200,
        sell_ema_short=sell_ema_short,
        sell_ema_long=sell_ema_long,
        sell_rsi_period=sell_rsi_period,
        sell_rsi_floor=sell_rsi_floor,
        sell_rsi_floor_alt=sell_rsi_floor_alt,
        sell_min_bars=sell_min_bars,
        universe_markets=universe_markets,
        us_screener_defaults=us_screener_defaults,
        us_screener_mode=us_screener_mode,
        us_screener_metric=us_screener_metric,
        us_screener_limit=us_screener_limit,
        usd_krw_rate=usd_krw_rate,
        fx_mode=fx_mode,
        fx_cache_ttl_minutes=fx_cache_ttl_minutes,
        fx_kis_symbol=fx_kis_symbol,
        us_min_price=us_min_price,
        us_min_dollar_volume=us_min_dollar_volume,
    )


def load_watchlist(path: Optional[str]) -> list[str]:
    if not path:
        return []
    if not os.path.exists(path):
        return []
    with open(path, "r", encoding="utf-8") as f:
        tickers: list[str] = []
        for line in f:
            t = line.strip()
            if not t or t.startswith("#"):
                continue
            tickers.append(t)
    return tickers
