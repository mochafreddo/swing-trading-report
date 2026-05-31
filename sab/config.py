from __future__ import annotations

import math
import os
from dataclasses import dataclass, field, replace
from typing import Any
from urllib.parse import urlparse

from .config_loader import ConfigLoadError, load_yaml_config
from .env_loader import env_flag, load_dotenv_if_available
from .holdings_loader import HoldingsData, load_holdings
from .tickers import (
    parse_ticker,
    validate_strict_holdings_ticker,
    validate_strict_us_ticker,
)


def _from_nested(d: dict[str, Any], path: str, default: Any = None) -> Any:
    current: Any = d
    for part in path.split("."):
        if not isinstance(current, dict) or part not in current:
            return default
        current = current[part]
    return current


def _has_secret_value(value: Any) -> bool:
    if value is None:
        return False
    if isinstance(value, str):
        return bool(value.strip())
    return True


_ENV_YAML_CONFLICT_BINDINGS: tuple[tuple[str, str], ...] = (
    ("DATA_PROVIDER", "data.provider"),
    ("SCREEN_LIMIT", "data.screen_limit"),
    ("REPORT_DIR", "data.report_dir"),
    ("DATA_DIR", "data.data_dir"),
    ("HOLDINGS_FILE", "files.holdings"),
    ("WATCHLIST_FILE", "files.watchlist"),
    ("UNIVERSE_MARKETS", "universe.markets"),
    ("SCREENER_ENABLED", "screener.enabled"),
    ("SCREENER_LIMIT", "screener.limit"),
    ("SCREENER_ONLY", "screener.only"),
    ("US_SCREENER_LIMIT", "screener.us_limit"),
    ("KIS_BASE_URL", "kis.base_url"),
    ("KIS_MIN_INTERVAL_MS", "kis.min_interval_ms"),
    (
        "MARKET_CACHE_STALE_SESSIONS_KR",
        "data.market_cache_stale_sessions.kr",
    ),
    (
        "MARKET_CACHE_STALE_SESSIONS_US",
        "data.market_cache_stale_sessions.us",
    ),
    ("STRATEGY_MODE", "strategy.mode"),
    ("USE_SMA200_FILTER", "strategy.use_sma200_filter"),
    ("USE_MARKET_REGIME_FILTER", "strategy.use_market_regime_filter"),
    ("GAP_ATR_MULTIPLIER", "strategy.gap_atr_multiplier"),
    ("MIN_DOLLAR_VOLUME", "screener.min_dollar_volume"),
    ("MIN_HISTORY_BARS", "strategy.min_history_bars"),
    ("EXCLUDE_ETF_ETN", "strategy.exclude_etf_etn"),
    ("REQUIRE_SLOPE_UP", "strategy.require_slope_up"),
    ("SCREENER_CACHE_TTL", "screener.cache_ttl_minutes"),
    ("MIN_PRICE", "screener.min_price"),
    ("RS_LOOKBACK_DAYS", "strategy.rs_lookback_days"),
    ("RS_BENCHMARK_RETURN", "strategy.rs_benchmark_return"),
    ("RS_BENCHMARK_TICKER_KR", "strategy.rs_benchmark_ticker_kr"),
    ("RS_BENCHMARK_TICKER_US", "strategy.rs_benchmark_ticker_us"),
    ("HYBRID_SMA_TREND_PERIOD", "strategy.hybrid.sma_trend_period"),
    ("HYBRID_EMA_SHORT_PERIOD", "strategy.hybrid.ema_short_period"),
    ("HYBRID_EMA_MID_PERIOD", "strategy.hybrid.ema_mid_period"),
    ("HYBRID_RSI_PERIOD", "strategy.hybrid.rsi_period"),
    ("HYBRID_RSI_ZONE_LOW", "strategy.hybrid.rsi_zone_low"),
    ("HYBRID_RSI_ZONE_HIGH", "strategy.hybrid.rsi_zone_high"),
    ("HYBRID_RSI_OVERSOLD_LOW", "strategy.hybrid.rsi_oversold_low"),
    ("HYBRID_RSI_OVERSOLD_HIGH", "strategy.hybrid.rsi_oversold_high"),
    ("HYBRID_PULLBACK_MAX_BARS", "strategy.hybrid.pullback_max_bars"),
    (
        "HYBRID_BREAKOUT_CONS_MIN_BARS",
        "strategy.hybrid.breakout_consolidation_min_bars",
    ),
    (
        "HYBRID_BREAKOUT_CONS_MAX_BARS",
        "strategy.hybrid.breakout_consolidation_max_bars",
    ),
    (
        "HYBRID_BREAKOUT_CONS_MAX_RANGE_PCT",
        "strategy.hybrid.breakout_consolidation_max_range_pct",
    ),
    ("HYBRID_VOLUME_LOOKBACK_DAYS", "strategy.hybrid.volume_lookback_days"),
    ("HYBRID_MAX_GAP_PCT", "strategy.hybrid.max_gap_pct"),
    ("HYBRID_USE_SMA60_FILTER", "strategy.hybrid.use_sma60_filter"),
    ("HYBRID_SMA60_PERIOD", "strategy.hybrid.sma60_period"),
    (
        "HYBRID_KR_BREAKOUT_NEEDS_CONFIRM",
        "strategy.hybrid.kr_breakout_requires_confirmation",
    ),
    ("SELL_MODE", "sell.mode"),
    ("SELL_ATR_MULTIPLIER", "sell.atr_trail_multiplier"),
    ("SELL_TIME_STOP_DAYS", "sell.time_stop_days"),
    ("SELL_REQUIRE_SMA200", "sell.require_sma200"),
    ("SELL_EMA_SHORT", "sell.ema_short"),
    ("SELL_EMA_LONG", "sell.ema_long"),
    ("SELL_RSI_PERIOD", "sell.rsi_period"),
    ("SELL_RSI_FLOOR", "sell.rsi_floor"),
    ("SELL_RSI_FLOOR_ALT", "sell.rsi_floor_alt"),
    ("SELL_MIN_BARS", "sell.min_bars"),
    ("HYBRID_SELL_PROFIT_TARGET_LOW", "sell.hybrid.profit_target_low"),
    ("HYBRID_SELL_PROFIT_TARGET_HIGH", "sell.hybrid.profit_target_high"),
    ("HYBRID_SELL_PARTIAL_PROFIT_FLOOR", "sell.hybrid.partial_profit_floor"),
    ("HYBRID_SELL_EMA_SHORT_PERIOD", "sell.hybrid.ema_short_period"),
    ("HYBRID_SELL_EMA_MID_PERIOD", "sell.hybrid.ema_mid_period"),
    ("HYBRID_SELL_SMA_TREND_PERIOD", "sell.hybrid.sma_trend_period"),
    ("HYBRID_SELL_RSI_PERIOD", "sell.hybrid.rsi_period"),
    ("HYBRID_SELL_STOP_LOSS_PCT_MIN", "sell.hybrid.stop_loss_pct_min"),
    ("HYBRID_SELL_STOP_LOSS_PCT_MAX", "sell.hybrid.stop_loss_pct_max"),
    (
        "HYBRID_SELL_FAILED_BREAKOUT_DROP_PCT",
        "sell.hybrid.failed_breakout_drop_pct",
    ),
    ("HYBRID_SELL_MIN_BARS", "sell.hybrid.min_bars"),
    ("HYBRID_SELL_TIME_STOP_DAYS", "sell.hybrid.time_stop_days"),
    ("HYBRID_SELL_TIME_STOP_GRACE_DAYS", "sell.hybrid.time_stop_grace_days"),
    (
        "HYBRID_SELL_TIME_STOP_PROFIT_FLOOR",
        "sell.hybrid.time_stop_profit_floor",
    ),
    ("USD_KRW_RATE", "fx.usdkrw"),
    ("FX_MODE", "fx.mode"),
    ("FX_CACHE_TTL", "fx.cache_ttl_minutes"),
    ("FX_KIS_SYMBOL", "fx.kis_symbol"),
    ("PORTFOLIO_MAX_ACTIVE_HOLDINGS", "portfolio.max_active_holdings"),
)


def _yaml_path_exists(yaml_cfg: dict[str, Any], path: str) -> bool:
    sentinel = object()
    return _from_nested(yaml_cfg, path, sentinel) is not sentinel


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
    breakout_consolidation_max_range_pct: float = 0.10
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
class PortfolioConfig:
    max_active_holdings: int | None = None
    max_new_entries_kr: int | None = None
    max_new_entries_us: int | None = None


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
    use_market_regime_filter: bool = False
    gap_atr_multiplier: float = 1.0
    min_dollar_volume: float = 0.0
    min_history_bars: int = 120
    exclude_etf_etn: bool = False
    require_slope_up: bool = False
    kis_min_interval_ms: float | None = None
    market_cache_stale_sessions_kr: int = 0
    market_cache_stale_sessions_us: int = 0
    screener_cache_ttl_minutes: float = 5.0
    min_price: float = 0.0
    rs_lookback_days: int = 20
    rs_benchmark_return: float | None = None
    rs_benchmark_ticker_kr: str | None = None
    rs_benchmark_ticker_us: str | None = None
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
    portfolio: PortfolioConfig = field(default_factory=PortfolioConfig)


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


_BOOL_TRUE_VALUES = frozenset({"1", "true", "yes", "y", "on"})
_BOOL_FALSE_VALUES = frozenset({"0", "false", "no", "n", "off"})


def _parse_bool_literal(value: Any) -> bool | None:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        normalized = value.strip().lower()
        if normalized in _BOOL_TRUE_VALUES:
            return True
        if normalized in _BOOL_FALSE_VALUES:
            return False
    return None


def _parse_bool(value: Any, default: bool = False) -> bool:
    parsed = _parse_bool_literal(value)
    if parsed is not None:
        return parsed
    if isinstance(value, str):
        return False
    if value is None:
        return default
    return bool(value)


def _parse_bool_strict(
    value: Any,
    *,
    default: bool,
    source: str,
    provided: bool,
) -> bool:
    if value is None:
        return default
    parsed = _parse_bool_literal(value)
    if parsed is not None:
        return parsed
    if provided:
        raise ConfigLoadError(
            f"Strict config parsing failed: {source} must be a boolean, got {value!r}."
        )
    return default


def _is_strict_config_mode() -> bool:
    if env_flag("GITHUB_ACTIONS") or env_flag("CI"):
        return True

    explicit = os.getenv("SAB_CONFIG_STRICT")
    if explicit is not None:
        return explicit.strip().lower() in {"1", "true", "yes", "y", "on"}
    return False


class _ConfigParser:
    def __init__(self, yaml_cfg: dict[str, Any], *, strict: bool) -> None:
        self._yaml_cfg = yaml_cfg
        self._strict = strict

    @property
    def strict(self) -> bool:
        return self._strict

    def from_yaml(self, path: str, default: Any = None) -> Any:
        return _from_nested(self._yaml_cfg, path, default)

    def has_yaml_path(self, path: str) -> bool:
        return _yaml_path_exists(self._yaml_cfg, path)

    def _coerce_numeric_or_default(
        self,
        *,
        key: str,
        path: str,
        default: float | int | None,
        parser: type[int] | type[float],
        expected_type: str,
        allow_none: bool = False,
    ) -> float | int | None:
        env_val = os.getenv(key)
        if env_val is not None:
            raw = env_val
            source = f"environment variable '{key}'"
            provided = True
        else:
            raw = self.from_yaml(path, default)
            source = f"config.yaml '{path}'"
            provided = self.has_yaml_path(path)

        if allow_none and raw is None:
            return None  # type: ignore[unreachable]

        try:
            return parser(raw)
        except (TypeError, ValueError) as err:
            if self._strict and provided:
                raise ConfigLoadError(
                    f"Strict config parsing failed: {source} must be {expected_type}, got {raw!r}."
                ) from err
            return default

    def env_bool(self, key: str, path: str, default: bool) -> bool:
        env_val = os.getenv(key)
        if env_val is not None:
            if self._strict:
                return _parse_bool_strict(
                    env_val,
                    default=default,
                    source=f"environment variable '{key}'",
                    provided=True,
                )
            return _parse_bool(env_val, default)
        raw = self.from_yaml(path, default)
        if self._strict:
            return _parse_bool_strict(
                raw,
                default=default,
                source=f"config.yaml '{path}'",
                provided=self.has_yaml_path(path),
            )
        return _parse_bool(raw, default)

    def env_int(self, key: str, path: str, default: int) -> int:
        parsed = self._coerce_numeric_or_default(
            key=key,
            path=path,
            default=default,
            parser=int,
            expected_type="an integer",
        )
        if parsed is None:
            return default
        return int(parsed)

    def env_float(self, key: str, path: str, default: float) -> float:
        parsed = self._coerce_numeric_or_default(
            key=key,
            path=path,
            default=default,
            parser=float,
            expected_type="a float",
        )
        if parsed is None:
            return default
        return float(parsed)

    def env_optional_float(self, key: str, path: str) -> float | None:
        parsed = self._coerce_numeric_or_default(
            key=key,
            path=path,
            default=None,
            parser=float,
            expected_type="a float",
            allow_none=True,
        )
        return None if parsed is None else float(parsed)

    def yaml_optional_float(self, path: str) -> float | None:
        raw = self.from_yaml(path)
        provided = self.has_yaml_path(path)
        if raw is None:
            return None
        try:
            return float(raw)
        except (TypeError, ValueError) as err:
            if self._strict and provided:
                raise ConfigLoadError(
                    f"Strict config parsing failed: config.yaml '{path}' must be a float, got {raw!r}."
                ) from err
            return None

    def env_str(self, key: str, path: str, default: str | None) -> str | None:
        env_val = os.getenv(key)
        if env_val is not None:
            return env_val
        value = self.from_yaml(path, default)
        if value is None:
            return default
        return str(value)


def _collect_env_yaml_conflicts(parser: _ConfigParser) -> list[str]:
    conflicts: set[str] = set()
    for env_key, yaml_path in _ENV_YAML_CONFLICT_BINDINGS:
        if os.getenv(env_key) is None:
            continue
        if parser.has_yaml_path(yaml_path):
            conflicts.add(f"{env_key} ({yaml_path})")
    return sorted(conflicts)


def _enforce_env_yaml_conflict_policy(parser: _ConfigParser) -> None:
    conflicts = _collect_env_yaml_conflicts(parser)
    if not conflicts:
        return
    raise ConfigLoadError(
        "Config conflict policy violation: duplicate keys are defined in both "
        ".env/environment and config.yaml: "
        f"{', '.join(conflicts)}. "
        "Keep each setting key in a single source. "
        "Resolve by removing one side of each duplicate key: keep secrets in "
        ".env/environment, keep non-secret defaults in config.yaml, or use a "
        "local YAML override such as config.local.yaml with "
        "SAB_CONFIG=config.local.yaml."
    )


@dataclass(frozen=True)
class _DataSection:
    provider: str
    screen_limit: int
    report_dir: str
    data_dir: str
    watchlist_path: str | None
    holdings_path: str | None
    screener_enabled: bool
    screener_limit: int
    screener_only: bool
    universe_markets: list[str]
    us_screener_defaults: list[str]
    us_screener_mode: str
    us_screener_metric: str
    us_screener_limit: int
    kis_app_key: str | None
    kis_app_secret: str | None
    kis_base_url: str | None
    kis_min_interval_ms: float | None
    market_cache_stale_sessions_kr: int
    market_cache_stale_sessions_us: int


@dataclass(frozen=True)
class _StrategySection:
    strategy_mode: str
    use_sma200_filter: bool
    use_market_regime_filter: bool
    gap_atr_multiplier: float
    min_dollar_volume: float
    min_history_bars: int
    exclude_etf_etn: bool
    require_slope_up: bool
    screener_cache_ttl_minutes: float
    min_price: float
    rs_lookback_days: int
    rs_benchmark_return: float | None
    rs_benchmark_ticker_kr: str | None
    rs_benchmark_ticker_us: str | None
    us_min_price: float | None
    us_min_dollar_volume: float | None
    hybrid: HybridStrategyConfig


@dataclass(frozen=True)
class _SellSection:
    sell_mode: str
    sell_atr_multiplier: float
    sell_time_stop_days: int
    sell_require_sma200: bool
    sell_ema_short: int
    sell_ema_long: int
    sell_rsi_period: int
    sell_rsi_floor: float
    sell_rsi_floor_alt: float
    sell_min_bars: int
    hybrid_sell: HybridSellConfig


@dataclass(frozen=True)
class _FxSection:
    usd_krw_rate: float | None
    fx_mode: str
    fx_cache_ttl_minutes: float
    fx_kis_symbol: str | None


@dataclass(frozen=True)
class _PortfolioSection:
    max_active_holdings: int | None
    max_new_entries_kr: int | None
    max_new_entries_us: int | None


def _create_config_parser() -> _ConfigParser:
    load_dotenv_if_available(override=False)
    yaml_cfg = load_yaml_config().raw
    return _ConfigParser(yaml_cfg, strict=_is_strict_config_mode())


def _enforce_secret_policy(parser: _ConfigParser) -> None:
    if _has_secret_value(parser.from_yaml("kis.app_key")) or _has_secret_value(
        parser.from_yaml("kis.app_secret")
    ):
        raise ConfigLoadError(
            "Security policy violation: do not store KIS credentials in YAML config. "
            "Remove 'kis.app_key'/'kis.app_secret' and set "
            "KIS_APP_KEY/KIS_APP_SECRET via environment variables."
        )


def _parse_data_section(
    parser: _ConfigParser,
    *,
    provider_override: str | None,
    limit_override: int | None,
    holdings_override: str | None,
    markets_override: list[str] | None,
) -> _DataSection:
    provider_raw = (
        provider_override
        or os.getenv("DATA_PROVIDER")
        or parser.from_yaml("data.provider", "kis")
        or "kis"
    )
    provider = str(provider_raw).lower()
    screen_limit_cfg = parser.env_int("SCREEN_LIMIT", "data.screen_limit", 30)
    screen_limit = limit_override if limit_override is not None else screen_limit_cfg

    holdings_path = holdings_override
    if holdings_path is None:
        holdings_path = parser.env_str("HOLDINGS_FILE", "files.holdings", None)
    watchlist_path = parser.env_str("WATCHLIST_FILE", "files.watchlist", None)

    if markets_override is not None:
        universe_markets = [
            market.strip().upper() for market in markets_override if market.strip()
        ]
    else:
        markets_env = os.getenv("UNIVERSE_MARKETS")
        if markets_env is not None:
            universe_markets = [
                market.strip().upper()
                for market in markets_env.split(",")
                if market.strip()
            ]
        else:
            raw_markets = parser.from_yaml("universe.markets", ["KR"]) or ["KR"]
            universe_markets = [
                str(market).strip().upper()
                for market in raw_markets
                if str(market).strip()
            ]

    us_screener_defaults_raw = parser.from_yaml("screener.us_defaults", []) or []
    us_screener_defaults: list[str] = []
    for idx, ticker_raw in enumerate(us_screener_defaults_raw):
        ticker_text = str(ticker_raw).strip()
        if not ticker_text:
            continue
        ticker_issue = validate_strict_us_ticker(ticker_text)
        if ticker_issue is not None:
            raise ConfigLoadError(
                "Invalid config value "
                f"'screener.us_defaults[{idx}]': {ticker_issue} "
                f"(got {ticker_raw!r})."
            )
        us_screener_defaults.append(parse_ticker(ticker_text).ticker)

    return _DataSection(
        provider=provider,
        screen_limit=screen_limit,
        report_dir=os.getenv("REPORT_DIR")
        or parser.from_yaml("data.report_dir", "reports"),
        data_dir=os.getenv("DATA_DIR") or parser.from_yaml("data.data_dir", "data"),
        watchlist_path=watchlist_path,
        holdings_path=holdings_path,
        screener_enabled=parser.env_bool("SCREENER_ENABLED", "screener.enabled", False),
        screener_limit=parser.env_int("SCREENER_LIMIT", "screener.limit", 20),
        screener_only=parser.env_bool("SCREENER_ONLY", "screener.only", False),
        universe_markets=universe_markets,
        us_screener_defaults=us_screener_defaults,
        us_screener_mode=str(
            parser.from_yaml("screener.us_mode", "defaults") or "defaults"
        )
        .strip()
        .lower(),
        us_screener_metric=str(
            parser.from_yaml("screener.us_metric", "volume") or "volume"
        )
        .strip()
        .lower(),
        us_screener_limit=parser.env_int("US_SCREENER_LIMIT", "screener.us_limit", 20),
        kis_app_key=os.getenv("KIS_APP_KEY"),
        kis_app_secret=os.getenv("KIS_APP_SECRET"),
        kis_base_url=_normalize_kis_base(
            os.getenv("KIS_BASE_URL") or parser.from_yaml("kis.base_url")
        ),
        kis_min_interval_ms=parser.env_optional_float(
            "KIS_MIN_INTERVAL_MS", "kis.min_interval_ms"
        ),
        market_cache_stale_sessions_kr=parser.env_int(
            "MARKET_CACHE_STALE_SESSIONS_KR",
            "data.market_cache_stale_sessions.kr",
            0,
        ),
        market_cache_stale_sessions_us=parser.env_int(
            "MARKET_CACHE_STALE_SESSIONS_US",
            "data.market_cache_stale_sessions.us",
            0,
        ),
    )


def _build_hybrid_strategy_config(parser: _ConfigParser) -> HybridStrategyConfig:
    return HybridStrategyConfig(
        sma_trend_period=parser.env_int(
            "HYBRID_SMA_TREND_PERIOD", "strategy.hybrid.sma_trend_period", 20
        ),
        ema_short_period=parser.env_int(
            "HYBRID_EMA_SHORT_PERIOD", "strategy.hybrid.ema_short_period", 10
        ),
        ema_mid_period=parser.env_int(
            "HYBRID_EMA_MID_PERIOD", "strategy.hybrid.ema_mid_period", 21
        ),
        rsi_period=parser.env_int(
            "HYBRID_RSI_PERIOD", "strategy.hybrid.rsi_period", 14
        ),
        rsi_zone_low=parser.env_float(
            "HYBRID_RSI_ZONE_LOW", "strategy.hybrid.rsi_zone_low", 45.0
        ),
        rsi_zone_high=parser.env_float(
            "HYBRID_RSI_ZONE_HIGH", "strategy.hybrid.rsi_zone_high", 60.0
        ),
        rsi_oversold_low=parser.env_float(
            "HYBRID_RSI_OVERSOLD_LOW", "strategy.hybrid.rsi_oversold_low", 30.0
        ),
        rsi_oversold_high=parser.env_float(
            "HYBRID_RSI_OVERSOLD_HIGH", "strategy.hybrid.rsi_oversold_high", 40.0
        ),
        pullback_max_bars=parser.env_int(
            "HYBRID_PULLBACK_MAX_BARS", "strategy.hybrid.pullback_max_bars", 10
        ),
        breakout_consolidation_min_bars=parser.env_int(
            "HYBRID_BREAKOUT_CONS_MIN_BARS",
            "strategy.hybrid.breakout_consolidation_min_bars",
            5,
        ),
        breakout_consolidation_max_bars=parser.env_int(
            "HYBRID_BREAKOUT_CONS_MAX_BARS",
            "strategy.hybrid.breakout_consolidation_max_bars",
            15,
        ),
        breakout_consolidation_max_range_pct=parser.env_float(
            "HYBRID_BREAKOUT_CONS_MAX_RANGE_PCT",
            "strategy.hybrid.breakout_consolidation_max_range_pct",
            0.10,
        ),
        volume_lookback_days=parser.env_int(
            "HYBRID_VOLUME_LOOKBACK_DAYS", "strategy.hybrid.volume_lookback_days", 5
        ),
        max_gap_pct=parser.env_float(
            "HYBRID_MAX_GAP_PCT", "strategy.hybrid.max_gap_pct", 0.05
        ),
        use_sma60_filter=parser.env_bool(
            "HYBRID_USE_SMA60_FILTER", "strategy.hybrid.use_sma60_filter", False
        ),
        sma60_period=parser.env_int(
            "HYBRID_SMA60_PERIOD", "strategy.hybrid.sma60_period", 60
        ),
        kr_breakout_requires_confirmation=parser.env_bool(
            "HYBRID_KR_BREAKOUT_NEEDS_CONFIRM",
            "strategy.hybrid.kr_breakout_requires_confirmation",
            True,
        ),
    )


def _resolve_mode_string(
    parser: _ConfigParser,
    env_key: str,
    yaml_path: str,
    default: str,
) -> str:
    """Resolve a mode-like string from env > YAML > literal default.

    Normalizes the result with ``str(...).strip().lower()`` so callers can pass
    it straight to ``_normalize_choice`` validators.
    """

    raw: Any = os.getenv(env_key)
    if raw is None:
        raw = parser.from_yaml(yaml_path, default)
    if raw is None:
        raw = default
    return str(raw).strip().lower()


def _parse_strategy_section(parser: _ConfigParser) -> _StrategySection:
    strategy_mode = _resolve_mode_string(
        parser, "STRATEGY_MODE", "strategy.mode", "ema_cross"
    )
    us_min_price = parser.yaml_optional_float("screener.us.min_price")
    us_min_dollar_volume = parser.yaml_optional_float("screener.us.min_dollar_volume")
    rs_benchmark_ticker_kr = _normalize_strategy_benchmark_ticker(
        parser.env_str(
            "RS_BENCHMARK_TICKER_KR",
            "strategy.rs_benchmark_ticker_kr",
            None,
        ),
        market="KR",
        path="strategy.rs_benchmark_ticker_kr",
    )
    rs_benchmark_ticker_us = _normalize_strategy_benchmark_ticker(
        parser.env_str(
            "RS_BENCHMARK_TICKER_US",
            "strategy.rs_benchmark_ticker_us",
            None,
        ),
        market="US",
        path="strategy.rs_benchmark_ticker_us",
    )

    return _StrategySection(
        strategy_mode=strategy_mode,
        use_sma200_filter=parser.env_bool(
            "USE_SMA200_FILTER", "strategy.use_sma200_filter", False
        ),
        use_market_regime_filter=parser.env_bool(
            "USE_MARKET_REGIME_FILTER", "strategy.use_market_regime_filter", False
        ),
        gap_atr_multiplier=parser.env_float(
            "GAP_ATR_MULTIPLIER", "strategy.gap_atr_multiplier", 1.0
        ),
        min_dollar_volume=parser.env_float(
            "MIN_DOLLAR_VOLUME", "screener.min_dollar_volume", 0.0
        ),
        min_history_bars=parser.env_int(
            "MIN_HISTORY_BARS", "strategy.min_history_bars", 120
        ),
        exclude_etf_etn=parser.env_bool(
            "EXCLUDE_ETF_ETN", "strategy.exclude_etf_etn", False
        ),
        require_slope_up=parser.env_bool(
            "REQUIRE_SLOPE_UP", "strategy.require_slope_up", False
        ),
        screener_cache_ttl_minutes=parser.env_float(
            "SCREENER_CACHE_TTL", "screener.cache_ttl_minutes", 5.0
        ),
        min_price=parser.env_float("MIN_PRICE", "screener.min_price", 0.0),
        rs_lookback_days=parser.env_int(
            "RS_LOOKBACK_DAYS", "strategy.rs_lookback_days", 20
        ),
        rs_benchmark_return=parser.env_optional_float(
            "RS_BENCHMARK_RETURN", "strategy.rs_benchmark_return"
        ),
        rs_benchmark_ticker_kr=rs_benchmark_ticker_kr,
        rs_benchmark_ticker_us=rs_benchmark_ticker_us,
        us_min_price=us_min_price,
        us_min_dollar_volume=us_min_dollar_volume,
        hybrid=_build_hybrid_strategy_config(parser),
    )


def _build_hybrid_sell_config(parser: _ConfigParser) -> HybridSellConfig:
    return HybridSellConfig(
        profit_target_low=parser.env_float(
            "HYBRID_SELL_PROFIT_TARGET_LOW", "sell.hybrid.profit_target_low", 0.05
        ),
        profit_target_high=parser.env_float(
            "HYBRID_SELL_PROFIT_TARGET_HIGH", "sell.hybrid.profit_target_high", 0.10
        ),
        partial_profit_floor=parser.env_float(
            "HYBRID_SELL_PARTIAL_PROFIT_FLOOR", "sell.hybrid.partial_profit_floor", 0.03
        ),
        ema_short_period=parser.env_int(
            "HYBRID_SELL_EMA_SHORT_PERIOD", "sell.hybrid.ema_short_period", 10
        ),
        ema_mid_period=parser.env_int(
            "HYBRID_SELL_EMA_MID_PERIOD", "sell.hybrid.ema_mid_period", 21
        ),
        sma_trend_period=parser.env_int(
            "HYBRID_SELL_SMA_TREND_PERIOD", "sell.hybrid.sma_trend_period", 20
        ),
        rsi_period=parser.env_int(
            "HYBRID_SELL_RSI_PERIOD", "sell.hybrid.rsi_period", 14
        ),
        stop_loss_pct_min=parser.env_float(
            "HYBRID_SELL_STOP_LOSS_PCT_MIN", "sell.hybrid.stop_loss_pct_min", 0.03
        ),
        stop_loss_pct_max=parser.env_float(
            "HYBRID_SELL_STOP_LOSS_PCT_MAX", "sell.hybrid.stop_loss_pct_max", 0.05
        ),
        failed_breakout_drop_pct=parser.env_float(
            "HYBRID_SELL_FAILED_BREAKOUT_DROP_PCT",
            "sell.hybrid.failed_breakout_drop_pct",
            0.03,
        ),
        min_bars=parser.env_int("HYBRID_SELL_MIN_BARS", "sell.hybrid.min_bars", 20),
        time_stop_days=parser.env_int(
            "HYBRID_SELL_TIME_STOP_DAYS", "sell.hybrid.time_stop_days", 0
        ),
        time_stop_grace_days=parser.env_int(
            "HYBRID_SELL_TIME_STOP_GRACE_DAYS", "sell.hybrid.time_stop_grace_days", 0
        ),
        time_stop_profit_floor=parser.env_float(
            "HYBRID_SELL_TIME_STOP_PROFIT_FLOOR",
            "sell.hybrid.time_stop_profit_floor",
            0.0,
        ),
    )


def _parse_sell_section(parser: _ConfigParser) -> _SellSection:
    sell_mode = _resolve_mode_string(parser, "SELL_MODE", "sell.mode", "generic")
    return _SellSection(
        sell_mode=sell_mode,
        sell_atr_multiplier=parser.env_float(
            "SELL_ATR_MULTIPLIER", "sell.atr_trail_multiplier", 1.0
        ),
        sell_time_stop_days=parser.env_int(
            "SELL_TIME_STOP_DAYS", "sell.time_stop_days", 10
        ),
        sell_require_sma200=parser.env_bool(
            "SELL_REQUIRE_SMA200", "sell.require_sma200", True
        ),
        sell_ema_short=parser.env_int("SELL_EMA_SHORT", "sell.ema_short", 20),
        sell_ema_long=parser.env_int("SELL_EMA_LONG", "sell.ema_long", 50),
        sell_rsi_period=parser.env_int("SELL_RSI_PERIOD", "sell.rsi_period", 14),
        sell_rsi_floor=parser.env_float("SELL_RSI_FLOOR", "sell.rsi_floor", 50.0),
        sell_rsi_floor_alt=parser.env_float(
            "SELL_RSI_FLOOR_ALT", "sell.rsi_floor_alt", 30.0
        ),
        sell_min_bars=parser.env_int("SELL_MIN_BARS", "sell.min_bars", 20),
        hybrid_sell=_build_hybrid_sell_config(parser),
    )


def _parse_fx_section(parser: _ConfigParser) -> _FxSection:
    fx_mode = _resolve_mode_string(parser, "FX_MODE", "fx.mode", "manual")
    fx_kis_symbol_raw = parser.env_str("FX_KIS_SYMBOL", "fx.kis_symbol", None)
    return _FxSection(
        usd_krw_rate=parser.env_optional_float("USD_KRW_RATE", "fx.usdkrw"),
        fx_mode=fx_mode,
        fx_cache_ttl_minutes=parser.env_float(
            "FX_CACHE_TTL", "fx.cache_ttl_minutes", 10.0
        ),
        fx_kis_symbol=fx_kis_symbol_raw.strip().upper() if fx_kis_symbol_raw else None,
    )


def _parse_optional_int(
    parser: _ConfigParser, *, path: str, env_key: str | None = None
) -> int | None:
    raw: Any
    source = f"config.yaml '{path}'"
    if env_key is not None and os.getenv(env_key) is not None:
        raw = os.getenv(env_key)
        source = f"environment variable '{env_key}'"
    else:
        raw = parser.from_yaml(path)

    if raw is None:
        return None

    if isinstance(raw, bool):
        raise ConfigLoadError(
            f"Invalid config value '{path}': {source} must be an integer or null, got {raw!r}."
        )

    try:
        return int(raw)
    except (TypeError, ValueError) as err:
        raise ConfigLoadError(
            f"Invalid config value '{path}': {source} must be an integer or null, got {raw!r}."
        ) from err


def _parse_portfolio_section(parser: _ConfigParser) -> _PortfolioSection:
    max_new_entries_per_market = parser.from_yaml(
        "portfolio.max_new_entries_per_market"
    )
    if max_new_entries_per_market is None:
        market_caps: dict[str, Any] = {}
    elif isinstance(max_new_entries_per_market, dict):
        market_caps = max_new_entries_per_market
    else:
        raise ConfigLoadError(
            "Invalid config value 'portfolio.max_new_entries_per_market': "
            "must be a mapping/object when provided."
        )

    unknown_market_keys = sorted(
        str(key) for key in market_caps if str(key).strip().upper() not in {"KR", "US"}
    )
    if unknown_market_keys:
        raise ConfigLoadError(
            "Invalid config value 'portfolio.max_new_entries_per_market': "
            f"unsupported market keys {unknown_market_keys!r}; expected only 'KR' and/or 'US'."
        )

    def _market_cap_value(market: str) -> int | None:
        for key, value in market_caps.items():
            if str(key).strip().upper() == market:
                if value is None:
                    return None
                if isinstance(value, bool):
                    raise ConfigLoadError(
                        "Invalid config value "
                        f"'portfolio.max_new_entries_per_market.{market}': "
                        f"must be an integer or null, got {value!r}."
                    )
                try:
                    return int(value)
                except (TypeError, ValueError) as err:
                    raise ConfigLoadError(
                        "Invalid config value "
                        f"'portfolio.max_new_entries_per_market.{market}': "
                        f"must be an integer or null, got {value!r}."
                    ) from err
        return None

    return _PortfolioSection(
        max_active_holdings=_parse_optional_int(
            parser,
            path="portfolio.max_active_holdings",
            env_key="PORTFOLIO_MAX_ACTIVE_HOLDINGS",
        ),
        max_new_entries_kr=_market_cap_value("KR"),
        max_new_entries_us=_market_cap_value("US"),
    )


def _normalize_choice(
    value: str,
    *,
    allowed: set[str],
    default: str,
    strict: bool,
    source_name: str,
) -> str:
    if value in allowed:
        return value
    if strict:
        allowed_values = ", ".join(sorted(allowed))
        raise ConfigLoadError(
            f"Strict config parsing failed: {source_name} must be one of {{{allowed_values}}}, got {value!r}."
        )
    return default


def _raise_range_error(path: str, detail: str) -> None:
    raise ConfigLoadError(f"Invalid config value '{path}': {detail}")


def _validate_positive(path: str, value: float) -> None:
    if not math.isfinite(value):
        _raise_range_error(path, f"must be finite (got {value!r})")
    if value <= 0:
        _raise_range_error(path, f"must be > 0 (got {value!r})")


def _validate_non_negative(path: str, value: float) -> None:
    if not math.isfinite(value):
        _raise_range_error(path, f"must be finite (got {value!r})")
    if value < 0:
        _raise_range_error(path, f"must be >= 0 (got {value!r})")


def _validate_rsi_threshold(path: str, value: float) -> None:
    if not math.isfinite(value):
        _raise_range_error(path, f"must be finite (got {value!r})")
    if value < 0 or value > 100:
        _raise_range_error(path, f"must be between 0 and 100 (got {value!r})")


def _validate_int_min(path: str, value: int, minimum: int = 1) -> None:
    if value < minimum:
        _raise_range_error(path, f"must be >= {minimum} (got {value!r})")


def _normalize_strategy_benchmark_ticker(
    value: str | None,
    *,
    market: str,
    path: str,
) -> str | None:
    text = str(value or "").strip().upper()
    if not text:
        return None

    if market == "US":
        ticker_issue = validate_strict_us_ticker(text)
        if ticker_issue is not None:
            raise ConfigLoadError(
                f"Invalid config value '{path}': {ticker_issue} (got {value!r})."
            )
        return parse_ticker(text).ticker

    ticker_issue = validate_strict_holdings_ticker(text)
    if ticker_issue is not None:
        raise ConfigLoadError(
            f"Invalid config value '{path}': {ticker_issue} (got {value!r})."
        )
    parsed = parse_ticker(text)
    if parsed.market != "KR":
        raise ConfigLoadError(
            f"Invalid config value '{path}': KR benchmark must be a KR ticker "
            f"(got {value!r})."
        )
    return parsed.ticker


def _validate_risk_ranges(*, strategy: _StrategySection, sell: _SellSection) -> None:
    _validate_positive("sell.atr_trail_multiplier", sell.sell_atr_multiplier)
    _validate_non_negative("sell.time_stop_days", float(sell.sell_time_stop_days))
    _validate_int_min("sell.ema_short", sell.sell_ema_short)
    _validate_int_min("sell.ema_long", sell.sell_ema_long)
    _validate_int_min("sell.rsi_period", sell.sell_rsi_period)
    _validate_non_negative("sell.rsi_floor", sell.sell_rsi_floor)
    _validate_non_negative("sell.rsi_floor_alt", sell.sell_rsi_floor_alt)
    _validate_int_min("sell.min_bars", sell.sell_min_bars)

    _validate_non_negative("strategy.gap_atr_multiplier", strategy.gap_atr_multiplier)
    _validate_non_negative("screener.min_price", strategy.min_price)
    _validate_non_negative("screener.min_dollar_volume", strategy.min_dollar_volume)
    if strategy.us_min_price is not None:
        _validate_non_negative("screener.us.min_price", strategy.us_min_price)
    if strategy.us_min_dollar_volume is not None:
        _validate_non_negative(
            "screener.us.min_dollar_volume", strategy.us_min_dollar_volume
        )
    _validate_int_min("strategy.min_history_bars", strategy.min_history_bars)
    _validate_int_min("strategy.rs_lookback_days", strategy.rs_lookback_days)

    hybrid_strategy = strategy.hybrid
    _validate_int_min(
        "strategy.hybrid.sma_trend_period", hybrid_strategy.sma_trend_period
    )
    _validate_int_min(
        "strategy.hybrid.ema_short_period", hybrid_strategy.ema_short_period
    )
    _validate_int_min("strategy.hybrid.ema_mid_period", hybrid_strategy.ema_mid_period)
    _validate_int_min("strategy.hybrid.rsi_period", hybrid_strategy.rsi_period)
    _validate_rsi_threshold(
        "strategy.hybrid.rsi_zone_low", hybrid_strategy.rsi_zone_low
    )
    _validate_rsi_threshold(
        "strategy.hybrid.rsi_zone_high", hybrid_strategy.rsi_zone_high
    )
    _validate_rsi_threshold(
        "strategy.hybrid.rsi_oversold_low", hybrid_strategy.rsi_oversold_low
    )
    _validate_rsi_threshold(
        "strategy.hybrid.rsi_oversold_high", hybrid_strategy.rsi_oversold_high
    )
    if hybrid_strategy.rsi_zone_low > hybrid_strategy.rsi_zone_high:
        _raise_range_error(
            "strategy.hybrid.rsi_zone_low",
            "must be <= strategy.hybrid.rsi_zone_high",
        )
    if hybrid_strategy.rsi_oversold_low > hybrid_strategy.rsi_oversold_high:
        _raise_range_error(
            "strategy.hybrid.rsi_oversold_low",
            "must be <= strategy.hybrid.rsi_oversold_high",
        )
    _validate_int_min(
        "strategy.hybrid.pullback_max_bars", hybrid_strategy.pullback_max_bars
    )
    _validate_int_min(
        "strategy.hybrid.breakout_consolidation_min_bars",
        hybrid_strategy.breakout_consolidation_min_bars,
    )
    _validate_int_min(
        "strategy.hybrid.breakout_consolidation_max_bars",
        hybrid_strategy.breakout_consolidation_max_bars,
    )
    if (
        hybrid_strategy.breakout_consolidation_min_bars
        > hybrid_strategy.breakout_consolidation_max_bars
    ):
        _raise_range_error(
            "strategy.hybrid.breakout_consolidation_min_bars",
            "must be <= strategy.hybrid.breakout_consolidation_max_bars",
        )
    _validate_positive(
        "strategy.hybrid.breakout_consolidation_max_range_pct",
        hybrid_strategy.breakout_consolidation_max_range_pct,
    )
    _validate_int_min(
        "strategy.hybrid.volume_lookback_days", hybrid_strategy.volume_lookback_days
    )
    _validate_non_negative("strategy.hybrid.max_gap_pct", hybrid_strategy.max_gap_pct)
    _validate_int_min("strategy.hybrid.sma60_period", hybrid_strategy.sma60_period)

    hybrid_sell = sell.hybrid_sell
    _validate_non_negative(
        "sell.hybrid.profit_target_low", hybrid_sell.profit_target_low
    )
    _validate_non_negative(
        "sell.hybrid.profit_target_high", hybrid_sell.profit_target_high
    )
    if hybrid_sell.profit_target_low > hybrid_sell.profit_target_high:
        _raise_range_error(
            "sell.hybrid.profit_target_low",
            "must be <= sell.hybrid.profit_target_high",
        )
    _validate_non_negative(
        "sell.hybrid.partial_profit_floor", hybrid_sell.partial_profit_floor
    )
    _validate_int_min("sell.hybrid.ema_short_period", hybrid_sell.ema_short_period)
    _validate_int_min("sell.hybrid.ema_mid_period", hybrid_sell.ema_mid_period)
    _validate_int_min("sell.hybrid.sma_trend_period", hybrid_sell.sma_trend_period)
    _validate_int_min("sell.hybrid.rsi_period", hybrid_sell.rsi_period)
    _validate_non_negative(
        "sell.hybrid.stop_loss_pct_min", hybrid_sell.stop_loss_pct_min
    )
    _validate_non_negative(
        "sell.hybrid.stop_loss_pct_max", hybrid_sell.stop_loss_pct_max
    )
    if hybrid_sell.stop_loss_pct_min > hybrid_sell.stop_loss_pct_max:
        _raise_range_error(
            "sell.hybrid.stop_loss_pct_min",
            "must be <= sell.hybrid.stop_loss_pct_max",
        )
    _validate_non_negative(
        "sell.hybrid.failed_breakout_drop_pct", hybrid_sell.failed_breakout_drop_pct
    )
    _validate_int_min("sell.hybrid.min_bars", hybrid_sell.min_bars)
    _validate_non_negative(
        "sell.hybrid.time_stop_days", float(hybrid_sell.time_stop_days)
    )
    _validate_non_negative(
        "sell.hybrid.time_stop_grace_days", float(hybrid_sell.time_stop_grace_days)
    )
    _validate_non_negative(
        "sell.hybrid.time_stop_profit_floor", hybrid_sell.time_stop_profit_floor
    )


def _validate_portfolio_ranges(portfolio: _PortfolioSection) -> None:
    if portfolio.max_active_holdings is not None:
        _validate_non_negative(
            "portfolio.max_active_holdings", float(portfolio.max_active_holdings)
        )
    if portfolio.max_new_entries_kr is not None:
        _validate_non_negative(
            "portfolio.max_new_entries_per_market.KR",
            float(portfolio.max_new_entries_kr),
        )
    if portfolio.max_new_entries_us is not None:
        _validate_non_negative(
            "portfolio.max_new_entries_per_market.US",
            float(portfolio.max_new_entries_us),
        )


def _validate_sections(
    *,
    data: _DataSection,
    strategy: _StrategySection,
    sell: _SellSection,
    fx: _FxSection,
    portfolio: _PortfolioSection,
    strict: bool,
) -> tuple[_DataSection, _StrategySection, _SellSection, _FxSection, _PortfolioSection]:
    validated_strategy = replace(
        strategy,
        strategy_mode=_normalize_choice(
            strategy.strategy_mode,
            allowed={"ema_cross", "sma_ema_hybrid"},
            default="ema_cross",
            strict=strict,
            source_name="STRATEGY_MODE/strategy.mode",
        ),
    )
    validated_sell = replace(
        sell,
        sell_mode=_normalize_choice(
            sell.sell_mode,
            allowed={"generic", "sma_ema_hybrid"},
            default="generic",
            strict=strict,
            source_name="SELL_MODE/sell.mode",
        ),
    )
    validated_fx = replace(
        fx,
        fx_mode=_normalize_choice(
            fx.fx_mode,
            allowed={"manual", "kis", "off"},
            default="manual",
            strict=strict,
            source_name="FX_MODE/fx.mode",
        ),
    )
    _validate_risk_ranges(strategy=validated_strategy, sell=validated_sell)
    _validate_portfolio_ranges(portfolio)
    return data, validated_strategy, validated_sell, validated_fx, portfolio


def _compose_config(
    *,
    data: _DataSection,
    strategy: _StrategySection,
    sell: _SellSection,
    fx: _FxSection,
    portfolio: _PortfolioSection,
) -> Config:
    return Config(
        data_provider=data.provider,
        kis_app_key=data.kis_app_key,
        kis_app_secret=data.kis_app_secret,
        kis_base_url=data.kis_base_url,
        screen_limit=data.screen_limit,
        report_dir=data.report_dir,
        data_dir=data.data_dir,
        watchlist_path=data.watchlist_path,
        screener_enabled=data.screener_enabled,
        screener_limit=data.screener_limit,
        screener_only=data.screener_only,
        strategy_mode=strategy.strategy_mode,
        use_sma200_filter=strategy.use_sma200_filter,
        use_market_regime_filter=strategy.use_market_regime_filter,
        gap_atr_multiplier=strategy.gap_atr_multiplier,
        min_dollar_volume=strategy.min_dollar_volume,
        min_history_bars=strategy.min_history_bars,
        exclude_etf_etn=strategy.exclude_etf_etn,
        require_slope_up=strategy.require_slope_up,
        kis_min_interval_ms=data.kis_min_interval_ms,
        market_cache_stale_sessions_kr=data.market_cache_stale_sessions_kr,
        market_cache_stale_sessions_us=data.market_cache_stale_sessions_us,
        screener_cache_ttl_minutes=strategy.screener_cache_ttl_minutes,
        min_price=strategy.min_price,
        rs_lookback_days=strategy.rs_lookback_days,
        rs_benchmark_return=strategy.rs_benchmark_return,
        rs_benchmark_ticker_kr=strategy.rs_benchmark_ticker_kr,
        rs_benchmark_ticker_us=strategy.rs_benchmark_ticker_us,
        holdings_path=data.holdings_path,
        sell_mode=sell.sell_mode,
        sell_atr_multiplier=sell.sell_atr_multiplier,
        sell_time_stop_days=sell.sell_time_stop_days,
        sell_require_sma200=sell.sell_require_sma200,
        sell_ema_short=sell.sell_ema_short,
        sell_ema_long=sell.sell_ema_long,
        sell_rsi_period=sell.sell_rsi_period,
        sell_rsi_floor=sell.sell_rsi_floor,
        sell_rsi_floor_alt=sell.sell_rsi_floor_alt,
        sell_min_bars=sell.sell_min_bars,
        universe_markets=data.universe_markets,
        us_screener_defaults=data.us_screener_defaults,
        us_screener_mode=data.us_screener_mode,
        us_screener_metric=data.us_screener_metric,
        us_screener_limit=data.us_screener_limit,
        usd_krw_rate=fx.usd_krw_rate,
        fx_mode=fx.fx_mode,
        fx_cache_ttl_minutes=fx.fx_cache_ttl_minutes,
        fx_kis_symbol=fx.fx_kis_symbol,
        us_min_price=strategy.us_min_price,
        us_min_dollar_volume=strategy.us_min_dollar_volume,
        hybrid=strategy.hybrid,
        hybrid_sell=sell.hybrid_sell,
        portfolio=PortfolioConfig(
            max_active_holdings=portfolio.max_active_holdings,
            max_new_entries_kr=portfolio.max_new_entries_kr,
            max_new_entries_us=portfolio.max_new_entries_us,
        ),
    )


def load_config(
    *,
    provider_override: str | None = None,
    limit_override: int | None = None,
    holdings_override: str | None = None,
    markets_override: list[str] | None = None,
) -> Config:
    parser = _create_config_parser()
    _enforce_env_yaml_conflict_policy(parser)
    _enforce_secret_policy(parser)

    data_section = _parse_data_section(
        parser,
        provider_override=provider_override,
        limit_override=limit_override,
        holdings_override=holdings_override,
        markets_override=markets_override,
    )
    strategy_section = _parse_strategy_section(parser)
    sell_section = _parse_sell_section(parser)
    fx_section = _parse_fx_section(parser)
    portfolio_section = _parse_portfolio_section(parser)

    (
        validated_data,
        validated_strategy,
        validated_sell,
        validated_fx,
        validated_portfolio,
    ) = _validate_sections(
        data=data_section,
        strategy=strategy_section,
        sell=sell_section,
        fx=fx_section,
        portfolio=portfolio_section,
        strict=parser.strict,
    )
    return _compose_config(
        data=validated_data,
        strategy=validated_strategy,
        sell=validated_sell,
        fx=validated_fx,
        portfolio=validated_portfolio,
    )


def load_watchlist(path: str | None) -> list[str]:
    if not path:
        return []
    if not os.path.exists(path):
        return []
    tickers: list[str] = []
    try:
        with open(path, encoding="utf-8") as f:
            for line_number, raw_line in enumerate(f, start=1):
                line_body = raw_line.split("#", 1)[0].strip()
                if not line_body:
                    continue
                ticker_issue = validate_strict_holdings_ticker(line_body)
                if ticker_issue is not None:
                    raise ConfigLoadError(
                        "Watchlist validation failed: "
                        f"invalid ticker {line_body!r} in '{path}' line {line_number} "
                        f"({ticker_issue})."
                    )
                tickers.append(parse_ticker(line_body).ticker)
    except OSError as exc:
        raise ConfigLoadError(f"Failed to read watchlist file '{path}': {exc}") from exc
    return tickers
