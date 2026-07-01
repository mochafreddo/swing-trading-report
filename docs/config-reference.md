# Config and Environment Reference

상태: Accepted (reference)

대상: 로컬 개발자, 운영자, 자동화 에이전트

이 문서는 `config.yaml`과 환경변수의 전체 override 계약을 코드 기준으로 정리하는 deep reference입니다. 신규 개발자/운영자는 먼저 [configuration.md](configuration.md)를 읽고, 매일 쓰는 시크릿 템플릿은 루트 [`.env.example`](../.env.example)을 우선하세요.

## 문서 상태

### 현재 제공

- `sab/config.py`의 env ↔ YAML binding, 웹 런타임 env, scheduled AI Brief env를 현재 기준으로 요약합니다.
- 민감정보 값은 예시로도 기록하지 않습니다.

### 실험

- 자동 생성 reference는 아직 없습니다. 이 문서는 수동 관리하며, binding이 바뀌면 함께 갱신합니다.

### 백로그

- `sab/config.py`의 `_ENV_YAML_CONFLICT_BINDINGS`에서 이 표를 생성하는 정적 검사/문서 생성기를 추가할 수 있습니다.

### 폐기 후보

- 모든 override를 `.env.example`에 복제하는 방식은 채택하지 않습니다. `.env.example`은 시크릿/주요 런타임 변수 중심으로 유지합니다.

## 기본 원칙

- 시크릿과 환경별 값은 `.env` 또는 런타임 환경변수에 둡니다.
- 비시크릿 기본값과 전략/스크리너/리스크 임계치는 `config.yaml`에 둡니다.
- 아래 "CLI config override" 표의 env와 YAML path는 같은 논리 키입니다. 둘을 동시에 정의하면 conflict policy에 따라 실패합니다.
- CLI 인자는 env/YAML보다 더 좁은 실행 단위 override입니다. 예: `sab scan --limit 30`, `sab sell --holdings path`.
- `SAB_CONFIG`는 YAML 파일 경로를 바꿉니다. 기본값은 `config.yaml`입니다.
- `SAB_CONFIG_STRICT=true`는 로컬에서도 CI/GitHub Actions와 같은 strict parsing을 강제합니다.
- `.env`는 `sab`가 로드합니다. `direnv`는 `.env`를 자동 로드하지 않고 `.envrc.local`만 source합니다.
- Direct web scripts preload the repository root `.env` before validation.
- `web/.env` is not a supported env file for this project.

## 파일별 역할

| 파일 | 역할 | 커밋 여부 |
| --- | --- | --- |
| `.env.example` | 필요한 시크릿/주요 env 템플릿 | 커밋 |
| `.env` | 로컬 시크릿과 환경별 값 | 커밋 금지 |
| `web/.env` | unsupported local duplicate; do not create | 커밋 금지 |
| `.env.scheduler.local` | 로컬 Docker scheduled AI Brief wrapper용 시크릿 | 커밋 금지 |
| `.envrc.local` | direnv 개인 override | 커밋 금지 |
| `config.yaml` | 저장소 기본 비시크릿 config | 커밋 |
| `config.example.yaml` | 예시 config와 설명 | 커밋 |
| `config.local.yaml` | 개인 실험용 config override | 커밋 금지 |

## Runtime Secrets And App Env

| Env | 쓰는 곳 | 비고 |
| --- | --- | --- |
| `KIS_APP_KEY`, `KIS_APP_SECRET` | CLI/GitHub Actions/scheduler KIS 호출 | YAML 저장 금지 |
| `SUPABASE_URL` | web, CLI upload, scheduler, GitHub Actions | Supabase 프로젝트 URL |
| `SUPABASE_SECRET_KEY` | server-side Supabase 접근 | 권장 server-side key. holdings select/export, `replace_holdings_v1`, `holdings_add_buy_v1`, report upload/index write를 실행할 수 있어야 하며 배포 smoke는 실제 configured key로 검증합니다. |
| `SUPABASE_SERVICE_ROLE_KEY` | server-side Supabase 접근 | legacy fallback. 사용 시 `SUPABASE_SECRET_KEY`와 같은 holdings projection/RPC/write capability가 필요합니다. |
| `SUPABASE_REPORTS_BUCKET` | report upload/web 조회 | 기본 `reports` |
| `SAB_UPLOAD_REPORTS` | 로컬 CLI upload | true면 로컬 scan/sell/entry/ai-brief 업로드 |
| `SAB_SUPPRESS_REPORT_UPLOADS` | CLI/workflow report upload helper | true면 현재 process의 report upload를 강제로 비활성화. 별도 품질 게이트 이후 upload step이 있는 생성 단계에서만 사용 |
| `SAB_BASIC_AUTH_USER`, `SAB_BASIC_AUTH_PASS` | web login | 관리자 계정 |
| `SAB_SESSION_SECRET` | web session cookie 서명 | 32자 이상 |
| `SAB_LOGIN_MAX_ATTEMPTS` | web login throttle | 기본 5 |
| `SAB_LOGIN_WINDOW_SECONDS` | web login throttle | 기본 900 |
| `SAB_LOGIN_BLOCK_SECONDS` | web login throttle | 기본 900 |
| `SAB_LOGIN_THROTTLE_FAIL_MODE` | web login throttle | `strict` 기본, `degrade` 선택 |
| `SAB_RUNTIME_STATE_STORE` | web runtime state | 테스트 외 기본 `supabase`, 선택 `memory` |
| `SAB_ENFORCE_LOCAL_REQUEST` | web local request guard | `0`이면 완화 |
| `WEB_BIND_HOST` | direct `pnpm run dev/start` | 기본 `127.0.0.1` |
| `SAB_ALLOW_NON_LOOPBACK_BIND` | startup bind guard | non-loopback bind 허용 시 `1` |
| `WEB_HOST_PORT`, `WEB_DEV_HOST_PORT` | Docker Compose port publish | 기본 `55300`, `55301` |
| `SAB_EXTERNAL_FETCH_TIMEOUT_MS` | web server outbound fetch | 기본 10000 |
| `RUN_DISPATCH_ENABLED` | web `/api/run` | `1` 활성, `0` 비활성 |
| `GITHUB_OWNER`, `GITHUB_REPO`, `GITHUB_PAT` | web `/api/run` | `RUN_DISPATCH_ENABLED=1`이면 필수 |
| `SAB_RUN_DISPATCH_LOCK_TTL_SECONDS` | web `/api/run` duplicate lock | 기본 30 |
| `REPORT_RETENTION_DAYS` | web display / cleanup workflow | 기본 30 |
| `REPORT_SEARCH_WINDOW` | web report ticker search | 기본 100, 코드에서 min/max 적용 |
| `TOSS_INVEST_CLIENT_ID`, `TOSS_INVEST_CLIENT_SECRET` | web `/api/holdings/toss-sync` | Toss Open API OAuth client credentials. 서버 전용이며 커밋 금지 |
| `TOSS_INVEST_ACCOUNT` | web `/api/holdings/toss-sync` | `X-Tossinvest-Account`에 쓰는 accountSeq. 실제 계좌 식별자는 커밋 금지 |
| `TOSS_INVEST_BASE_URL` | web `/api/holdings/toss-sync` | 기본 `https://openapi.tossinvest.com` |
| `TOSS_SYNC_SOURCE`, `TOSS_SYNC_QA_FIXTURE_ENABLED` | web `/api/holdings/toss-sync/scheduled` | QA-only fixture source. 운영/live sync에서는 unset. `fixture`는 `TOSS_SYNC_QA_FIXTURE_ENABLED=1`과 local Supabase URL일 때만 허용 |
| `TOSS_SYNC_JOB_TOKEN` | web `/api/holdings/toss-sync/scheduled`, local runner | Local scheduled Toss sync Bearer token. root `.env`에 저장해 Docker Compose web 컨테이너와 `scripts/toss_daily_auto_sync.sh`가 같은 값을 읽게 함. 커밋 금지 |
| `TOSS_SYNC_AUTO_APPLY_ENABLED` | web `/api/holdings/toss-sync/scheduled` | `1`일 때만 scheduled auto-apply write 허용. 그 외 값은 fetch/write 없이 `disabled` 반환. scheduled write는 create/update only이며 delete diff는 `delete_guard_blocked`/`wipe_guard_blocked` |
| `TELEGRAM_BOT_TOKEN`, `TELEGRAM_CHAT_ID` | scheduled/Actions notification | 알림 사용 시 필요 |
| `SLACK_WEBHOOK_URL` | scheduled/Actions notification | 선택 |
| `SAB_SCHEDULER_ENV_FILE` | Docker scheduler env_file | 기본 `.env.scheduler.local` |
| `OPENAI_API_KEY` | `sab ai-brief --model-provider openai` | scheduled AI Brief에서 필요 |
| `OPENAI_AI_BRIEF_MODEL` | OpenAI primary model | CLI `--model-name`으로도 지정 가능 |
| `OPENAI_AI_BRIEF_FALLBACK_MODEL` | OpenAI fallback model after retryable primary timeout | primary와 달라야 함 |
| `AI_BRIEF_MODEL_TIMEOUT_SECONDS` | OpenAI primary model timeout | 선택. 양의 finite 숫자만 허용. scheduled 권장값 60 |
| `AI_BRIEF_MODEL_FALLBACK_TIMEOUT_SECONDS` | OpenAI fallback model timeout | 선택. 양의 finite 숫자만 허용. scheduled 권장값 30 |
| `AI_BRIEF_MODEL_TOTAL_TIMEOUT_SECONDS` | OpenAI total model-attempt timeout budget | 선택. primary와 fallback의 남은 timeout을 cap. scheduled 권장값 90 |
| `AI_BRIEF_SOURCE_API_URL` | `http-json` source provider | HTTPS URL 필요 |
| `AI_BRIEF_SOURCE_API_URL_KR`, `AI_BRIEF_SOURCE_API_URL_US` | scheduled provider URL | GitHub Actions variable 용도 |
| `AI_BRIEF_SOURCE_API_TOKEN` | `http-json` source provider | 실행 URL이 `AI_BRIEF_SOURCE_API_URL`, `_KR`, `_US` 중 하나와 일치할 때만 Bearer 전송 |
| `AI_BRIEF_SOURCE_TIMEOUT_SECONDS` | source provider timeout | 선택 |
| `AI_BRIEF_ARTICLE_READER` | AI Brief article reader | 선택. `none` 기본. `lightpanda`는 runner `PATH`에 binary가 있어야 하며, source discovery 뒤 선택된 공개 기사 URL을 public fetch로 읽어 `article_read` 메타데이터를 붙임. 접근 제어 우회는 하지 않음 |
| `AI_BRIEF_ARTICLE_READER_MAX_URLS` | AI Brief article reader cap | 선택. 기본 8, 0이면 reader 비활성 |
| `AI_BRIEF_ARTICLE_READER_TIMEOUT_SECONDS` | AI Brief article reader timeout | 선택. 양의 finite 숫자만 허용 |
| `AI_BRIEF_ARTICLE_READER_MAX_EXCERPT_CHARS` | AI Brief article excerpt cap | 선택. 기본 1200, 전체 본문은 저장하지 않음 |
| `AI_BRIEF_SOURCE_PROVIDER_CHAIN_KR`, `AI_BRIEF_SOURCE_PROVIDER_CHAIN_US`, `AI_BRIEF_SOURCE_PROVIDER_CHAIN` | scheduled/source provider chain | market chain > global chain > single-provider fallback. 일반 `sab ai-brief`는 명시 `--source-provider`/source path/API URL이 없을 때만 env chain 사용 |
| `AI_BRIEF_SOURCE_PROVIDER_KR`, `AI_BRIEF_SOURCE_PROVIDER_US`, `AI_BRIEF_SOURCE_PROVIDER` | scheduled source provider | market-specific 값 우선 |
| `FINNHUB_API_KEY` | `finnhub` source provider | US-only |
| `POLYGON_API_KEY` | `polygon-news` source provider | US-only |
| `ALPHA_VANTAGE_API_KEY` | `alpha-vantage-news` source provider | US-only |
| `MARKETAUX_API_TOKEN` | `marketaux-news` source provider | US-only |
| `BENZINGA_API_TOKEN` | `benzinga-news` source provider | US-only |
| `NAVER_CLIENT_ID`, `NAVER_CLIENT_SECRET` | `naver-news` source provider | KR-only |
| `LOG_LEVEL`, `LOG_FORMAT`, `LOG_DATEFMT`, `LOG_TZ` | CLI logging | `LOG_FORMAT=json`, `LOG_TZ=utc` 지원 |
| `ENTRY_FATAL_MISSING_PRICE_RATIO` | `sab entry` | `entry_check.fatal_missing_price_ratio`, 0.0-1.0, active default 0.0; env override only when no YAML config is loaded |
| `PORTFOLIO_MAX_NEW_ENTRIES_KR`, `PORTFOLIO_MAX_NEW_ENTRIES_US` | `sab entry` | `portfolio.max_new_entries_per_market.KR/US`; env override only when the selected YAML config omits the matching market cap |
| `SAB_DATA_DIR` | calendar/eval helper lower-level override | 일반 config는 `DATA_DIR`/`data.data_dir` 우선 |
| `SAB_USE_PMC_CALENDAR` | trading calendar optional path | 기본 enabled, calendar extra 필요 가능 |

## CLI Config Override Bindings

아래 표는 `sab/config.py`의 `_ENV_YAML_CONFLICT_BINDINGS` 기준입니다. 같은 행의 env와 YAML path를 동시에 설정하지 마세요.

| Env | YAML path | 설명 |
| --- | --- | --- |
| `DATA_PROVIDER` | `data.provider` | 기본 market data provider (`kis`/`pykrx`) |
| `SCREEN_LIMIT` | `data.screen_limit` | 최종 평가 ticker cap |
| `REPORT_DIR` | `data.report_dir` | 로컬 report 출력 디렉터리 |
| `DATA_DIR` | `data.data_dir` | 로컬 cache/state 디렉터리 |
| `HOLDINGS_FILE` | `files.holdings` | holdings 파일 경로 |
| `WATCHLIST_FILE` | `files.watchlist` | watchlist 파일 경로 |
| `UNIVERSE_MARKETS` | `universe.markets` | `KR,US` 형식 market list |
| `SCREENER_ENABLED` | `screener.enabled` | screener 활성화 |
| `SCREENER_LIMIT` | `screener.limit` | KR screener top-N |
| `SCREENER_ONLY` | `screener.only` | screener-only legacy flag |
| `US_SCREENER_LIMIT` | `screener.us_limit` | US screener top-N |
| `KIS_BASE_URL` | `kis.base_url` | KIS base URL |
| `KIS_MIN_INTERVAL_MS` | `kis.min_interval_ms` | KIS 호출 간 최소 간격 |
| `MARKET_CACHE_STALE_SESSIONS_KR` | `data.market_cache_stale_sessions.kr` | KR stale cache fallback 허용치 |
| `MARKET_CACHE_STALE_SESSIONS_US` | `data.market_cache_stale_sessions.us` | US stale cache fallback 허용치 |
| `STRATEGY_MODE` | `strategy.mode` | buy strategy mode |
| `USE_SMA200_FILTER` | `strategy.use_sma200_filter` | SMA200 필터 |
| `USE_MARKET_REGIME_FILTER` | `strategy.use_market_regime_filter` | market regime 필터 |
| `MARKET_REGIME_UNAVAILABLE_POLICY` | `strategy.market_regime_unavailable_policy` | benchmark unavailable 시 market regime 처리 정책 |
| `GAP_ATR_MULTIPLIER` | `strategy.gap_atr_multiplier` | gap ATR multiplier |
| `MIN_DOLLAR_VOLUME` | `screener.min_dollar_volume` | 공통 최소 거래대금 |
| `MIN_HISTORY_BARS` | `strategy.min_history_bars` | 최소 히스토리 봉 수 |
| `EXCLUDE_ETF_ETN` | `strategy.exclude_etf_etn` | ETF/ETN 제외 |
| `REQUIRE_SLOPE_UP` | `strategy.require_slope_up` | `ema_cross` EMA slope 필터 |
| `SCREENER_CACHE_TTL` | `screener.cache_ttl_minutes` | screener cache TTL |
| `MIN_PRICE` | `screener.min_price` | 공통 최소 가격 |
| `RS_LOOKBACK_DAYS` | `strategy.rs_lookback_days` | RS lookback |
| `RS_BENCHMARK_RETURN` | `strategy.rs_benchmark_return` | static benchmark return |
| `RS_BENCHMARK_TICKER_KR` | `strategy.rs_benchmark_ticker_kr` | KR RS benchmark ticker |
| `RS_BENCHMARK_TICKER_US` | `strategy.rs_benchmark_ticker_us` | US RS benchmark ticker |
| `HYBRID_SMA_TREND_PERIOD` | `strategy.hybrid.sma_trend_period` | hybrid buy SMA trend period |
| `HYBRID_EMA_SHORT_PERIOD` | `strategy.hybrid.ema_short_period` | hybrid buy EMA short period |
| `HYBRID_EMA_MID_PERIOD` | `strategy.hybrid.ema_mid_period` | hybrid buy EMA mid period |
| `HYBRID_RSI_PERIOD` | `strategy.hybrid.rsi_period` | hybrid buy RSI period |
| `HYBRID_RSI_ZONE_LOW` | `strategy.hybrid.rsi_zone_low` | hybrid RSI zone lower bound |
| `HYBRID_RSI_ZONE_HIGH` | `strategy.hybrid.rsi_zone_high` | hybrid RSI zone upper bound |
| `HYBRID_RSI_OVERSOLD_LOW` | `strategy.hybrid.rsi_oversold_low` | hybrid oversold lower bound |
| `HYBRID_RSI_OVERSOLD_HIGH` | `strategy.hybrid.rsi_oversold_high` | hybrid oversold upper bound |
| `HYBRID_PULLBACK_MAX_BARS` | `strategy.hybrid.pullback_max_bars` | pullback max bars |
| `HYBRID_BREAKOUT_CONS_MIN_BARS` | `strategy.hybrid.breakout_consolidation_min_bars` | breakout base min bars |
| `HYBRID_BREAKOUT_CONS_MAX_BARS` | `strategy.hybrid.breakout_consolidation_max_bars` | breakout base max bars |
| `HYBRID_BREAKOUT_CONS_MAX_RANGE_PCT` | `strategy.hybrid.breakout_consolidation_max_range_pct` | breakout base max range |
| `HYBRID_VOLUME_LOOKBACK_DAYS` | `strategy.hybrid.volume_lookback_days` | volume confirmation lookback |
| `HYBRID_MAX_GAP_PCT` | `strategy.hybrid.max_gap_pct` | hybrid max signal gap |
| `HYBRID_USE_SMA60_FILTER` | `strategy.hybrid.use_sma60_filter` | optional SMA60 filter |
| `HYBRID_SMA60_PERIOD` | `strategy.hybrid.sma60_period` | SMA60 period |
| `HYBRID_KR_BREAKOUT_NEEDS_CONFIRM` | `strategy.hybrid.kr_breakout_requires_confirmation` | KR breakout confirmation |
| `SELL_MODE` | `sell.mode` | sell mode |
| `SELL_ATR_MULTIPLIER` | `sell.atr_trail_multiplier` | generic sell ATR trail multiplier |
| `SELL_TIME_STOP_DAYS` | `sell.time_stop_days` | generic sell time stop |
| `SELL_REQUIRE_SMA200` | `sell.require_sma200` | generic sell SMA200 context |
| `SELL_EMA_SHORT` | `sell.ema_short` | generic sell short EMA |
| `SELL_EMA_LONG` | `sell.ema_long` | generic sell long EMA |
| `SELL_RSI_PERIOD` | `sell.rsi_period` | generic sell RSI period |
| `SELL_RSI_FLOOR` | `sell.rsi_floor` | generic sell review floor |
| `SELL_RSI_FLOOR_ALT` | `sell.rsi_floor_alt` | generic sell hard floor |
| `SELL_MIN_BARS` | `sell.min_bars` | sell minimum bars |
| `HYBRID_SELL_PROFIT_TARGET_LOW` | `sell.hybrid.profit_target_low` | hybrid sell low target |
| `HYBRID_SELL_PROFIT_TARGET_HIGH` | `sell.hybrid.profit_target_high` | hybrid sell high target |
| `HYBRID_SELL_PARTIAL_PROFIT_FLOOR` | `sell.hybrid.partial_profit_floor` | hybrid sell break-even/protection floor |
| `HYBRID_SELL_EMA_SHORT_PERIOD` | `sell.hybrid.ema_short_period` | hybrid sell EMA short period |
| `HYBRID_SELL_EMA_MID_PERIOD` | `sell.hybrid.ema_mid_period` | hybrid sell EMA mid period |
| `HYBRID_SELL_SMA_TREND_PERIOD` | `sell.hybrid.sma_trend_period` | hybrid sell SMA trend period |
| `HYBRID_SELL_RSI_PERIOD` | `sell.hybrid.rsi_period` | hybrid sell RSI period |
| `HYBRID_SELL_STOP_LOSS_PCT_MIN` | `sell.hybrid.stop_loss_pct_min` | hybrid sell soft stop bound |
| `HYBRID_SELL_STOP_LOSS_PCT_MAX` | `sell.hybrid.stop_loss_pct_max` | hybrid sell hard stop bound |
| `HYBRID_SELL_FAILED_BREAKOUT_DROP_PCT` | `sell.hybrid.failed_breakout_drop_pct` | failed breakout loss threshold |
| `HYBRID_SELL_MIN_BARS` | `sell.hybrid.min_bars` | hybrid sell min bars |
| `HYBRID_SELL_TIME_STOP_DAYS` | `sell.hybrid.time_stop_days` | hybrid sell time stop |
| `HYBRID_SELL_TIME_STOP_GRACE_DAYS` | `sell.hybrid.time_stop_grace_days` | hybrid sell time stop grace |
| `HYBRID_SELL_TIME_STOP_PROFIT_FLOOR` | `sell.hybrid.time_stop_profit_floor` | hybrid sell time stop profit floor |
| `ENTRY_FATAL_MISSING_PRICE_RATIO` | `entry_check.fatal_missing_price_ratio` | entry price 누락 fatal 임계치 |
| `USD_KRW_RATE` | `fx.usdkrw` | manual/fallback USDKRW |
| `FX_MODE` | `fx.mode` | `kis`/`manual`/`off` |
| `FX_CACHE_TTL` | `fx.cache_ttl_minutes` | FX cache TTL |
| `FX_KIS_SYMBOL` | `fx.kis_symbol` | representative US ticker for KIS FX |
| `PORTFOLIO_MAX_ACTIVE_HOLDINGS` | `portfolio.max_active_holdings` | entry portfolio active holdings cap |
| `PORTFOLIO_MAX_NEW_ENTRIES_KR` | `portfolio.max_new_entries_per_market.KR` | KR 신규 entry cap |
| `PORTFOLIO_MAX_NEW_ENTRIES_US` | `portfolio.max_new_entries_per_market.US` | US 신규 entry cap |

## YAML-Only Config Notes

These settings are currently YAML-only in `config.yaml`:

- `screener.us.min_price`
- `screener.us.min_dollar_volume`
- `screener.us_mode`
- `screener.us_metric`
- `screener.us_defaults`
- `portfolio.exposure_limits[]` (`dimension`, `value`, `max_active`; dimensions: `currency`, `sector`, `theme`, `beta_bucket`, `correlation_bucket`, `tag`)
- `sell.hybrid.pattern_time_stops.<pattern>.time_stop_days`
- `sell.hybrid.pattern_time_stops.<pattern>.time_stop_grace_days`
- `sell.hybrid.pattern_time_stops.<pattern>.time_stop_profit_floor`

If these need environment overrides later, update `sab/config.py`, `.env.example`, this document, and the relevant config tests in the same change.

`sell.hybrid.pattern_time_stops` keys must be one of the structured hybrid entry
patterns: `trend_pullback_bounce`, `swing_high_breakout`, or
`rsi_oversold_reversal`. Omitted fields inherit the global
`sell.hybrid.time_stop_*` value. The repository default shortens
`swing_high_breakout` to `15` sessions plus `5` grace sessions with a `1%`
profit floor, while other patterns use the global hybrid time-stop settings.
