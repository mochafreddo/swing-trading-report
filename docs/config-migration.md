# config.yaml Migration Guide

이 문서는 기존 `.env` 기반 설정을 `config.yaml`로 옮기는 과정을 간단히 정리합니다. 목표는 기본값/임계치를 한 곳에서 관리하고, 필요한 경우에만 환경변수로 덮어쓰는 형태를 만드는 것입니다.

## 1. 기본 원칙

- `config.yaml` → `.env` → CLI 순으로 우선순위가 적용됩니다. (CLI > .env > config)
- `.env`에만 존재하던 값은 아래 매핑에 맞춰 `config.yaml`에 추가합니다.
- 시크릿(`KIS_APP_KEY`, `KIS_APP_SECRET`)은 YAML에 저장하지 않고 `.env`/환경변수로만 관리합니다.
- 환경변수는 즉시 적용/실험용으로 유지하되, 장기 기본값은 `config.yaml`에 기록합니다.
- 다른 경로의 설정 파일을 쓰고 싶다면 `SAB_CONFIG=/path/to/file.yaml` 을 지정하세요.

## 2. 매핑 표

| .env 키 | config.yaml 경로 |
|---------|------------------|
| `DATA_PROVIDER` | `data.provider` |
| `SCREEN_LIMIT` | `data.screen_limit` |
| `REPORT_DIR` | `data.report_dir` |
| `DATA_DIR` | `data.data_dir` |
| `HOLDINGS_FILE` | `files.holdings` |
| `WATCHLIST_FILE` | `files.watchlist` |
| `KIS_BASE_URL` | `kis.base_url` |
| `KIS_MIN_INTERVAL_MS` | `kis.min_interval_ms` |
| `SCREENER_ENABLED` | `screener.enabled` |
| `SCREENER_LIMIT` | `screener.limit` |
| `SCREENER_ONLY` | `screener.only` |
| `SCREENER_CACHE_TTL` | `screener.cache_ttl_minutes` |
| `MIN_PRICE` | `screener.min_price` |
| `MIN_DOLLAR_VOLUME` | `screener.min_dollar_volume` |
| `USE_SMA200_FILTER` | `strategy.use_sma200_filter` |
| `REQUIRE_SLOPE_UP` | `strategy.require_slope_up` |
| `GAP_ATR_MULTIPLIER` | `strategy.gap_atr_multiplier` |
| `MIN_HISTORY_BARS` | `strategy.min_history_bars` |
| `EXCLUDE_ETF_ETN` | `strategy.exclude_etf_etn` |
| `RS_LOOKBACK_DAYS` | `strategy.rs_lookback_days` |
| `RS_BENCHMARK_RETURN` | `strategy.rs_benchmark_return` |
| `ENTRY_CHECK_ENABLED` | `entry_check.enabled` |
| `UNIVERSE_MARKETS` | `universe.markets` (리스트) |
| `US_SCREENER_LIMIT` | `screener.us_limit` |
| (없음) | `screener.us.min_price` (USD 기준) |
| (없음) | `screener.us.min_dollar_volume` (USD 기준) |
| `FX_MODE` | `fx.mode` |
| `FX_CACHE_TTL` | `fx.cache_ttl_minutes` |
| `FX_KIS_SYMBOL` | `fx.kis_symbol` |
| `USD_KRW_RATE` | `fx.usdkrw` |
| `SELL_ATR_MULTIPLIER` | `sell.atr_trail_multiplier` |
| `SELL_TIME_STOP_DAYS` | `sell.time_stop_days` |
| `SELL_REQUIRE_SMA200` | `sell.require_sma200` |
| `SELL_EMA_SHORT` | `sell.ema_short` |
| `SELL_EMA_LONG` | `sell.ema_long` |
| `SELL_RSI_PERIOD` | `sell.rsi_period` |
| `SELL_RSI_FLOOR` | `sell.rsi_floor` |
| `SELL_RSI_FLOOR_ALT` | `sell.rsi_floor_alt` |
| `SELL_MIN_BARS` | `sell.min_bars` |
| `SELL_MODE` | `sell.mode` |
| `HYBRID_SELL_PROFIT_TARGET_LOW` | `sell.hybrid.profit_target_low` |
| `HYBRID_SELL_PROFIT_TARGET_HIGH` | `sell.hybrid.profit_target_high` |
| `HYBRID_SELL_PARTIAL_PROFIT_FLOOR` | `sell.hybrid.partial_profit_floor` |
| `HYBRID_SELL_EMA_SHORT_PERIOD` | `sell.hybrid.ema_short_period` |
| `HYBRID_SELL_EMA_MID_PERIOD` | `sell.hybrid.ema_mid_period` |
| `HYBRID_SELL_SMA_TREND_PERIOD` | `sell.hybrid.sma_trend_period` |
| `HYBRID_SELL_RSI_PERIOD` | `sell.hybrid.rsi_period` |
| `HYBRID_SELL_STOP_LOSS_PCT_MIN` | `sell.hybrid.stop_loss_pct_min` |
| `HYBRID_SELL_STOP_LOSS_PCT_MAX` | `sell.hybrid.stop_loss_pct_max` |
| `HYBRID_SELL_FAILED_BREAKOUT_DROP_PCT` | `sell.hybrid.failed_breakout_drop_pct` |
| `HYBRID_SELL_MIN_BARS` | `sell.hybrid.min_bars` |
| `HYBRID_SELL_TIME_STOP_DAYS` | `sell.hybrid.time_stop_days` |
| `HYBRID_SELL_TIME_STOP_GRACE_DAYS` | `sell.hybrid.time_stop_grace_days` |
| `HYBRID_SELL_TIME_STOP_PROFIT_FLOOR` | `sell.hybrid.time_stop_profit_floor` |
| `STRATEGY_MODE` | `strategy.mode` |
| `HYBRID_SMA_TREND_PERIOD` | `strategy.hybrid.sma_trend_period` |
| `HYBRID_EMA_SHORT_PERIOD` | `strategy.hybrid.ema_short_period` |
| `HYBRID_EMA_MID_PERIOD` | `strategy.hybrid.ema_mid_period` |
| `HYBRID_RSI_PERIOD` | `strategy.hybrid.rsi_period` |
| `HYBRID_RSI_ZONE_LOW` | `strategy.hybrid.rsi_zone_low` |
| `HYBRID_RSI_ZONE_HIGH` | `strategy.hybrid.rsi_zone_high` |
| `HYBRID_RSI_OVERSOLD_LOW` | `strategy.hybrid.rsi_oversold_low` |
| `HYBRID_RSI_OVERSOLD_HIGH` | `strategy.hybrid.rsi_oversold_high` |
| `HYBRID_PULLBACK_MAX_BARS` | `strategy.hybrid.pullback_max_bars` |
| `HYBRID_BREAKOUT_CONS_MIN_BARS` | `strategy.hybrid.breakout_consolidation_min_bars` |
| `HYBRID_BREAKOUT_CONS_MAX_BARS` | `strategy.hybrid.breakout_consolidation_max_bars` |
| `HYBRID_VOLUME_LOOKBACK_DAYS` | `strategy.hybrid.volume_lookback_days` |
| `HYBRID_MAX_GAP_PCT` | `strategy.hybrid.max_gap_pct` |
| `HYBRID_USE_SMA60_FILTER` | `strategy.hybrid.use_sma60_filter` |
| `HYBRID_SMA60_PERIOD` | `strategy.hybrid.sma60_period` |
| `HYBRID_KR_BREAKOUT_NEEDS_CONFIRM` | `strategy.hybrid.kr_breakout_requires_confirmation` |

필요 시 해외 확장/추가 전략 항목은 동일한 방식으로 `config.yaml`에 정의합니다.

## 3. 마이그레이션 절차

1. `config.example.yaml`을 복사하여 `config.yaml` 생성.
2. 위 표를 참고해 비시크릿 설정만 `config.yaml`에 옮김.
3. `.env`에서는 비밀정보(KIS 키 등)와 실험용 값을 관리.
4. `SAB_CONFIG` 환경변수로 다른 경로(예: `~/.config/sab.yaml`)를 지정할 수 있습니다.
5. 실행: `uv run -m sab scan` (변경 사항이 즉시 반영되는지 확인).

## 4. 주의사항

- `pyyaml` 패키지가 필요합니다(`uv add pyyaml`). 설치 권한이 없으면 `.env` 방식만 사용하세요.
- `kis.app_key`, `kis.app_secret` 키가 YAML에 있으면 보안 정책 위반으로 실행이 실패합니다.
- 숫자/불리언 값은 YAML에서 타입으로 인식되므로 인용부호 없이 작성하세요.
- CLI 인자(`--limit`, `--screener-limit`, `--universe` 등)는 항상 최종 우선순위를 가집니다.
