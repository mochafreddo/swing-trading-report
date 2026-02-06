from __future__ import annotations

import os
from dataclasses import dataclass, field
from typing import Any, overload
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
class HybridStrategyConfig:
    sma_trend_period: int = 20
    ema_short_period: int = 10
    ema_mid_period: int = 21
    rsi_period: int = 14
    rsi_zone_low: float = 45.0
    rsi_zone_high: float = 60.0
    rsi_oversold_low: float = 30.0
    rsi_oversold_high: float = 40.0
    pullback_max_bars: int = 10
    breakout_consolidation_min_bars: int = 5
    breakout_consolidation_max_bars: int = 15
    volume_lookback_days: int = 5
    max_gap_pct: float = 0.05
    use_sma60_filter: bool = False
    sma60_period: int = 60
    kr_breakout_requires_confirmation: bool = True


@dataclass(frozen=True)
class HybridSellConfig:
    profit_target_low: float = 0.05
    profit_target_high: float = 0.10
    partial_profit_floor: float = 0.03
    ema_short_period: int = 10
    ema_mid_period: int = 21
    sma_trend_period: int = 20
    rsi_period: int = 14
    stop_loss_pct_min: float = 0.03
    stop_loss_pct_max: float = 0.05
    failed_breakout_drop_pct: float = 0.03
    min_bars: int = 20
    time_stop_days: int = 0
    time_stop_grace_days: int = 0
    time_stop_profit_floor: float = 0.0


@dataclass(frozen=True)
class Config:
    data_provider: str = "kis"  # or pykrx
    kis_app_key: str | None = None
    kis_app_secret: str | None = None
    kis_base_url: str | None = None
    screen_limit: int = 30
    report_dir: str = "reports"
    data_dir: str = "data"
    watchlist_path: str | None = None
    screener_enabled: bool = False
    screener_limit: int = 20
    screener_only: bool = False
    strategy_mode: str = "ema_cross"
    use_sma200_filter: bool = False
    gap_atr_multiplier: float = 1.0
    min_dollar_volume: float = 0.0
    min_history_bars: int = 120
    exclude_etf_etn: bool = False
    require_slope_up: bool = False
    kis_min_interval_ms: float | None = None
    screener_cache_ttl_minutes: float = 5.0
    min_price: float = 0.0
    rs_lookback_days: int = 20
    rs_benchmark_return: float = 0.0
    holdings_path: str | None = None
    holdings: HoldingsData = field(default_factory=lambda: load_holdings(None))
    sell_mode: str = "generic"
    sell_atr_multiplier: float = 1.0
    sell_time_stop_days: int = 10
    sell_require_sma200: bool = True
    sell_ema_short: int = 20
    sell_ema_long: int = 50
    sell_rsi_period: int = 14
    sell_rsi_floor: float = 50.0
    sell_rsi_floor_alt: float = 30.0
    sell_min_bars: int = 20
    universe_markets: list[str] = field(
        default_factory=lambda: ["KR"]
    )  # e.g., ["KR", "US"]
    us_screener_defaults: list[str] = field(default_factory=list)
    us_screener_mode: str = "defaults"  # 'defaults' or 'kis'
    us_screener_metric: str = "volume"  # 'volume' | 'market_cap' | 'value'
    us_screener_limit: int = 20
    usd_krw_rate: float | None = None
    fx_mode: str = "manual"  # 'manual' | 'kis' | 'off'
    fx_cache_ttl_minutes: float = 10.0
    fx_kis_symbol: str | None = None
    # Per-market thresholds
    us_min_price: float | None = None
    us_min_dollar_volume: float | None = None
    hybrid: HybridStrategyConfig = field(default_factory=HybridStrategyConfig)
    hybrid_sell: HybridSellConfig = field(default_factory=HybridSellConfig)


def _normalize_kis_base(url: str | None) -> str | None:
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
        port = 29443 if "openapivts" in host else 9443

    netloc = parsed.hostname if port in (80, 443) else f"{parsed.hostname}:{port}"
    normalized = f"{parsed.scheme}://{netloc}"
    return normalized.rstrip("/")


def load_config(
    *,
    provider_override: str | None = None,
    limit_override: int | None = None,
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
    def parse_float(val: Any, default: float) -> float: ...

    @overload
    def parse_float(val: Any, default: None) -> float | None: ...

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

    def env_str(key: str, path: str, default: str | None) -> str | None:
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

    use_sma200_filter = env_bool(
        "USE_SMA200_FILTER", "strategy.use_sma200_filter", False
    )
    require_slope_up = env_bool("REQUIRE_SLOPE_UP", "strategy.require_slope_up", False)
    exclude_etf_etn = env_bool("EXCLUDE_ETF_ETN", "strategy.exclude_etf_etn", False)

    gap_atr_multiplier = env_float(
        "GAP_ATR_MULTIPLIER", "strategy.gap_atr_multiplier", 1.0
    )
    min_dollar_volume = env_float(
        "MIN_DOLLAR_VOLUME", "screener.min_dollar_volume", 0.0
    )
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

    screener_cache_ttl_minutes = env_float(
        "SCREENER_CACHE_TTL", "screener.cache_ttl_minutes", 5.0
    )
    min_price = env_float("MIN_PRICE", "screener.min_price", 0.0)
    rs_lookback_days = env_int("RS_LOOKBACK_DAYS", "strategy.rs_lookback_days", 20)
    rs_benchmark_return = env_float(
        "RS_BENCHMARK_RETURN", "strategy.rs_benchmark_return", 0.0
    )

    # Strategy mode and hybrid strategy tuning
    strategy_mode_raw = (
        os.getenv("STRATEGY_MODE")
        or from_yaml("strategy.mode", "ema_cross")
        or "ema_cross"
    )
    strategy_mode = str(strategy_mode_raw).strip().lower()
    if strategy_mode not in {"ema_cross", "sma_ema_hybrid"}:
        strategy_mode = "ema_cross"

    hybrid_sma_trend_period = env_int(
        "HYBRID_SMA_TREND_PERIOD", "strategy.hybrid.sma_trend_period", 20
    )
    hybrid_ema_short_period = env_int(
        "HYBRID_EMA_SHORT_PERIOD", "strategy.hybrid.ema_short_period", 10
    )
    hybrid_ema_mid_period = env_int(
        "HYBRID_EMA_MID_PERIOD", "strategy.hybrid.ema_mid_period", 21
    )
    hybrid_rsi_period = env_int("HYBRID_RSI_PERIOD", "strategy.hybrid.rsi_period", 14)
    hybrid_rsi_zone_low = env_float(
        "HYBRID_RSI_ZONE_LOW", "strategy.hybrid.rsi_zone_low", 45.0
    )
    hybrid_rsi_zone_high = env_float(
        "HYBRID_RSI_ZONE_HIGH", "strategy.hybrid.rsi_zone_high", 60.0
    )
    hybrid_rsi_oversold_low = env_float(
        "HYBRID_RSI_OVERSOLD_LOW", "strategy.hybrid.rsi_oversold_low", 30.0
    )
    hybrid_rsi_oversold_high = env_float(
        "HYBRID_RSI_OVERSOLD_HIGH", "strategy.hybrid.rsi_oversold_high", 40.0
    )
    hybrid_pullback_max_bars = env_int(
        "HYBRID_PULLBACK_MAX_BARS", "strategy.hybrid.pullback_max_bars", 10
    )
    hybrid_breakout_cons_min_bars = env_int(
        "HYBRID_BREAKOUT_CONS_MIN_BARS",
        "strategy.hybrid.breakout_consolidation_min_bars",
        5,
    )
    hybrid_breakout_cons_max_bars = env_int(
        "HYBRID_BREAKOUT_CONS_MAX_BARS",
        "strategy.hybrid.breakout_consolidation_max_bars",
        15,
    )
    hybrid_volume_lookback_days = env_int(
        "HYBRID_VOLUME_LOOKBACK_DAYS", "strategy.hybrid.volume_lookback_days", 5
    )
    hybrid_max_gap_pct = env_float(
        "HYBRID_MAX_GAP_PCT", "strategy.hybrid.max_gap_pct", 0.05
    )
    hybrid_use_sma60_filter = env_bool(
        "HYBRID_USE_SMA60_FILTER", "strategy.hybrid.use_sma60_filter", False
    )
    hybrid_sma60_period = env_int(
        "HYBRID_SMA60_PERIOD", "strategy.hybrid.sma60_period", 60
    )
    hybrid_kr_breakout_needs_confirm = env_bool(
        "HYBRID_KR_BREAKOUT_NEEDS_CONFIRM",
        "strategy.hybrid.kr_breakout_requires_confirmation",
        True,
    )

    hybrid_cfg = HybridStrategyConfig(
        sma_trend_period=hybrid_sma_trend_period,
        ema_short_period=hybrid_ema_short_period,
        ema_mid_period=hybrid_ema_mid_period,
        rsi_period=hybrid_rsi_period,
        rsi_zone_low=hybrid_rsi_zone_low,
        rsi_zone_high=hybrid_rsi_zone_high,
        rsi_oversold_low=hybrid_rsi_oversold_low,
        rsi_oversold_high=hybrid_rsi_oversold_high,
        pullback_max_bars=hybrid_pullback_max_bars,
        breakout_consolidation_min_bars=hybrid_breakout_cons_min_bars,
        breakout_consolidation_max_bars=hybrid_breakout_cons_max_bars,
        volume_lookback_days=hybrid_volume_lookback_days,
        max_gap_pct=hybrid_max_gap_pct,
        use_sma60_filter=hybrid_use_sma60_filter,
        sma60_period=hybrid_sma60_period,
        kr_breakout_requires_confirmation=hybrid_kr_breakout_needs_confirm,
    )

    # Sell mode and hybrid sell tuning
    sell_mode_raw = (
        os.getenv("SELL_MODE") or from_yaml("sell.mode", "generic") or "generic"
    )
    sell_mode = str(sell_mode_raw).strip().lower()
    if sell_mode not in {"generic", "sma_ema_hybrid"}:
        sell_mode = "generic"

    hybrid_sell_profit_low = env_float(
        "HYBRID_SELL_PROFIT_TARGET_LOW", "sell.hybrid.profit_target_low", 0.05
    )
    hybrid_sell_profit_high = env_float(
        "HYBRID_SELL_PROFIT_TARGET_HIGH", "sell.hybrid.profit_target_high", 0.10
    )
    hybrid_sell_partial_floor = env_float(
        "HYBRID_SELL_PARTIAL_PROFIT_FLOOR", "sell.hybrid.partial_profit_floor", 0.03
    )
    hybrid_sell_ema_short = env_int(
        "HYBRID_SELL_EMA_SHORT_PERIOD", "sell.hybrid.ema_short_period", 10
    )
    hybrid_sell_ema_mid = env_int(
        "HYBRID_SELL_EMA_MID_PERIOD", "sell.hybrid.ema_mid_period", 21
    )
    hybrid_sell_sma_trend = env_int(
        "HYBRID_SELL_SMA_TREND_PERIOD", "sell.hybrid.sma_trend_period", 20
    )
    hybrid_sell_rsi_period = env_int(
        "HYBRID_SELL_RSI_PERIOD", "sell.hybrid.rsi_period", 14
    )
    hybrid_sell_stop_loss_min = env_float(
        "HYBRID_SELL_STOP_LOSS_PCT_MIN", "sell.hybrid.stop_loss_pct_min", 0.03
    )
    hybrid_sell_stop_loss_max = env_float(
        "HYBRID_SELL_STOP_LOSS_PCT_MAX", "sell.hybrid.stop_loss_pct_max", 0.05
    )
    hybrid_sell_failed_bo_drop = env_float(
        "HYBRID_SELL_FAILED_BREAKOUT_DROP_PCT",
        "sell.hybrid.failed_breakout_drop_pct",
        0.03,
    )
    hybrid_sell_min_bars = env_int("HYBRID_SELL_MIN_BARS", "sell.hybrid.min_bars", 20)
    hybrid_sell_time_stop = env_int(
        "HYBRID_SELL_TIME_STOP_DAYS", "sell.hybrid.time_stop_days", 0
    )
    hybrid_sell_time_stop_grace = env_int(
        "HYBRID_SELL_TIME_STOP_GRACE_DAYS", "sell.hybrid.time_stop_grace_days", 0
    )
    hybrid_sell_time_stop_profit_floor = env_float(
        "HYBRID_SELL_TIME_STOP_PROFIT_FLOOR", "sell.hybrid.time_stop_profit_floor", 0.0
    )

    hybrid_sell_cfg = HybridSellConfig(
        profit_target_low=hybrid_sell_profit_low,
        profit_target_high=hybrid_sell_profit_high,
        partial_profit_floor=hybrid_sell_partial_floor,
        ema_short_period=hybrid_sell_ema_short,
        ema_mid_period=hybrid_sell_ema_mid,
        sma_trend_period=hybrid_sell_sma_trend,
        rsi_period=hybrid_sell_rsi_period,
        stop_loss_pct_min=hybrid_sell_stop_loss_min,
        stop_loss_pct_max=hybrid_sell_stop_loss_max,
        failed_breakout_drop_pct=hybrid_sell_failed_bo_drop,
        min_bars=hybrid_sell_min_bars,
        time_stop_days=hybrid_sell_time_stop,
        time_stop_grace_days=hybrid_sell_time_stop_grace,
        time_stop_profit_floor=hybrid_sell_time_stop_profit_floor,
    )

    holdings_path = env_str("HOLDINGS_FILE", "files.holdings", None)
    watchlist_path = env_str("WATCHLIST_FILE", "files.watchlist", None)
    holdings_data = load_holdings(holdings_path)

    # Universe markets (KR,US)
    markets_env = os.getenv("UNIVERSE_MARKETS")
    if markets_env is not None:
        universe_markets = [
            m.strip().upper() for m in markets_env.split(",") if m.strip()
        ]
    else:
        raw_markets = from_yaml("universe.markets", ["KR"]) or ["KR"]
        universe_markets = [
            str(m).strip().upper() for m in raw_markets if str(m).strip()
        ]

    # US screener defaults (yaml-only)
    us_screener_defaults_raw = from_yaml("screener.us_defaults", []) or []
    us_screener_defaults = [
        str(t).strip().upper() for t in us_screener_defaults_raw if str(t).strip()
    ]
    us_screener_mode = (
        str(from_yaml("screener.us_mode", "defaults") or "defaults").strip().lower()
    )
    us_screener_metric = (
        str(from_yaml("screener.us_metric", "volume") or "volume").strip().lower()
    )
    us_screener_limit = env_int("US_SCREENER_LIMIT", "screener.us_limit", 20)
    usd_krw_rate: float | None = None
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

    sell_atr_multiplier = env_float(
        "SELL_ATR_MULTIPLIER", "sell.atr_trail_multiplier", 1.0
    )
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
        kis_base_url=_normalize_kis_base(
            os.getenv("KIS_BASE_URL") or from_yaml("kis.base_url")
        ),
        screen_limit=screen_limit,
        report_dir=os.getenv("REPORT_DIR") or from_yaml("data.report_dir", "reports"),
        data_dir=os.getenv("DATA_DIR") or from_yaml("data.data_dir", "data"),
        watchlist_path=watchlist_path,
        screener_enabled=screener_enabled,
        screener_limit=screener_limit,
        screener_only=screener_only,
        strategy_mode=strategy_mode,
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
        sell_mode=sell_mode,
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
        hybrid=hybrid_cfg,
        hybrid_sell=hybrid_sell_cfg,
    )


def load_watchlist(path: str | None) -> list[str]:
    if not path:
        return []
    if not os.path.exists(path):
        return []
    with open(path, encoding="utf-8") as f:
        tickers: list[str] = []
        for line in f:
            t = line.strip()
            if not t or t.startswith("#"):
                continue
            tickers.append(t)
    return tickers
