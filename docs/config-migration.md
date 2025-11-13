# config.yaml Migration Guide

이 문서는 기존 `.env` 기반 설정을 `config.yaml`로 옮기는 과정을 간단히 정리합니다. 목표는 기본값/임계치를 한 곳에서 관리하고, 필요한 경우에만 환경변수로 덮어쓰는 형태를 만드는 것입니다.

## 1. 기본 원칙

- `config.yaml` → `.env` → CLI 순으로 우선순위가 적용됩니다. (CLI > .env > config)
- `.env`에만 존재하던 값은 아래 매핑에 맞춰 `config.yaml`에 추가합니다.
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
| `KIS_APP_KEY` | `kis.app_key` |
| `KIS_APP_SECRET` | `kis.app_secret` |
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

필요 시 해외 확장/추가 전략 항목은 동일한 방식으로 `config.yaml`에 정의합니다.

## 3. 마이그레이션 절차

1. `config.example.yaml`을 복사하여 `config.yaml` 생성.
2. 위 표를 참고해 `.env`에 있던 값을 `config.yaml`에 옮김.
3. `.env`에서는 비밀정보(KIS 키 등)만 유지하거나 실험용 값만 남김.
4. `SAB_CONFIG` 환경변수로 다른 경로(예: `~/.config/sab.yaml`)를 지정할 수 있습니다.
5. 실행: `uv run -m sab scan` (변경 사항이 즉시 반영되는지 확인).

## 4. 주의사항

- `pyyaml` 패키지가 필요합니다(`uv add pyyaml`). 설치 권한이 없으면 `.env` 방식만 사용하세요.
- 숫자/불리언 값은 YAML에서 타입으로 인식되므로 인용부호 없이 작성하세요.
- CLI 인자(`--limit`, `--screener-limit`, `--universe` 등)는 항상 최종 우선순위를 가집니다.
