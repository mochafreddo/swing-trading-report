# Configuration

상태: Accepted (설정 가이드)

이 문서는 `.env`, `config.yaml`, Docker Compose, GitHub Actions, web runtime에서 사용하는 환경변수와 설정 파일을 코드 기준으로 정리합니다. 실제 값은 문서에 쓰지 말고 placeholder만 사용하세요.

## 문서 상태

### 현재 제공

- 주요 환경변수의 required/default/example/used by를 제공합니다.
- 전체 CLI config override binding은 [config-reference.md](config-reference.md)에 유지합니다.

### 실험

- 자동 생성 configuration reference는 아직 없습니다.

### 백로그

- `sab/config.py`의 binding에서 표를 생성하는 정적 문서 생성기를 추가할 수 있습니다.

### 폐기 후보

- 모든 config override를 `.env.example`에 중복 복제하는 방식은 유지하지 않습니다.

## 파일 역할

| File | Purpose | Commit |
| --- | --- | --- |
| `.env.example` | 주요 env template | yes |
| `.env` | 로컬 시크릿/환경별 값 | no |
| `.env.scheduler.local` | 로컬 scheduled AI Brief Docker env file | no |
| `.envrc.local` | direnv 개인 override | no |
| `config.yaml` | 저장소 기본 비시크릿 config | yes |
| `config.example.yaml` | 예시 config와 설명 | yes |
| `config.local.yaml` | 개인 실험용 config override | no |

## 기본 원칙

- 시크릿은 `.env`, GitHub Secrets, 운영 환경변수에 둡니다.
- 전략 threshold, screener 기본값, 비시크릿 경로는 `config.yaml`에 둡니다.
- 같은 논리 키를 `.env`와 `config.yaml`에 동시에 정의하면 fail-closed로 실패합니다.
- CLI option은 단일 실행에만 적용하는 가장 좁은 override입니다.
- `.env`는 `sab`가 로드합니다. `direnv`는 `.env`를 자동 로드하지 않습니다.

## 환경변수 표

| Variable | Required | Default | Example | Used By | Description | Notes |
|---|---:|---|---|---|---|---|
| `KIS_APP_KEY` | yes for KIS calls | none | `replace-with-kis-app-key` | `sab`, GitHub Actions, scheduler | KIS Open API app key | Secret. Do not commit. |
| `KIS_APP_SECRET` | yes for KIS calls | none | `replace-with-kis-app-secret` | `sab`, GitHub Actions, scheduler | KIS Open API app secret | Secret. Do not commit. |
| `KIS_BASE_URL` | no | `config.yaml` `kis.base_url` | `https://openapi.koreainvestment.com:9443` | `sab` | KIS endpoint override | Env/YAML conflict binding. Scheduled GitHub fallback does not forward `vars.KIS_BASE_URL`; change committed config intentionally. Scheduler runtime env override only works when the selected YAML config omits `kis.base_url`. |
| `KIS_MIN_INTERVAL_MS` | no | `config.yaml` `kis.min_interval_ms` | `200` | `sab` | Minimum KIS request interval | Env/YAML conflict binding. Use for rate-limit tuning. |
| `SUPABASE_URL` | yes for web/upload | none | `https://example.supabase.co` | web, `sab` upload, workflows, scheduler | Supabase project URL | Do not expose real internal URL in docs. |
| `SUPABASE_SECRET_KEY` | yes for server access | none | `sb_secret_replace_me` | web, workflows, scheduler | Recommended server-side Supabase key | Publishable key is rejected in server paths. The configured key must be able to run holdings selects, `replace_holdings_v1`, `holdings_add_buy_v1`, report upload/index writes, and scheduled holdings export. Deployment smoke should prove the exact configured key works. |
| `SUPABASE_SERVICE_ROLE_KEY` | fallback | none | `replace-with-service-role-key` | web, workflows, scheduler | Legacy server-side Supabase key fallback | Secret. Prefer `SUPABASE_SECRET_KEY`. If used, it must have the same holdings projection/RPC/write capability as `SUPABASE_SECRET_KEY`. |
| `SUPABASE_REPORTS_BUCKET` | no | `reports` | `reports` | web, `sab` upload | Storage bucket for report JSON | Bucket should be private. |
| `SAB_UPLOAD_REPORTS` | no | `false` | `true` | `sab` CLI | Upload local reports to Supabase | Local CLI otherwise writes files only. |
| `SAB_SUPPRESS_REPORT_UPLOADS` | no | `false` | `true` | `sab` CLI, workflows | Suppress report uploads in the current process | Overrides local/GitHub Actions upload detection and forced uploads. Use only for generation steps that have a separate gated upload. |
| `SAB_BASIC_AUTH_USER` | yes for web | none | `admin` | web | Admin login username | Required by `web/scripts/validate-env.mjs`. |
| `SAB_BASIC_AUTH_PASS` | yes for web | none | `replace-with-password` | web | Admin login password | Secret. |
| `SAB_SESSION_SECRET` | yes for web | none | `replace-with-32-plus-char-secret` | web | HMAC session cookie secret | Must be at least 32 chars. |
| `SAB_LOGIN_MAX_ATTEMPTS` | no | `5` | `5` | web | Login throttle attempts | See `web/src/lib/login-throttle.ts`. |
| `SAB_LOGIN_WINDOW_SECONDS` | no | `900` | `900` | web | Login throttle window | Seconds. |
| `SAB_LOGIN_BLOCK_SECONDS` | no | `900` | `900` | web | Login block duration | Seconds. |
| `SAB_LOGIN_THROTTLE_FAIL_MODE` | no | `strict` | `strict` | web | Supabase throttle failure mode | `strict` or `degrade`. |
| `SAB_RUNTIME_STATE_STORE` | no | `supabase` outside tests | `supabase` | web, scheduler | Runtime state backend | `memory` only for tests/local fallback. |
| `SAB_ENFORCE_LOCAL_REQUEST` | no | enabled | `0` | web | Local request guard override | Disable only behind trusted boundary. |
| `WEB_BIND_HOST` | no | `127.0.0.1` direct | `127.0.0.1` | web direct run | Direct Next.js bind host | Compose uses internal `0.0.0.0` with loopback host publish. |
| `SAB_ALLOW_NON_LOOPBACK_BIND` | no | unset | `1` | web startup guard | Allows non-loopback direct bind | Not a complete remote security model. |
| `WEB_HOST_PORT` | no | `55300` | `55300` | Docker Compose | Host port for `web` | Published to `127.0.0.1`. |
| `WEB_DEV_HOST_PORT` | no | `55301` | `55301` | Docker Compose | Host port for `web-dev` | Published to `127.0.0.1`. |
| `SAB_EXTERNAL_FETCH_TIMEOUT_MS` | no | `10000` | `10000` | web | Server outbound fetch timeout | Milliseconds. |
| `RUN_DISPATCH_ENABLED` | no | disabled | `1` | web `/api/run` | Enables GitHub workflow dispatch | Must be `0` or `1` in env validation. |
| `GITHUB_OWNER` | required when dispatch enabled | none | `owner` | web `/api/run` | GitHub owner for workflow dispatch | No real owner needed in docs. |
| `GITHUB_REPO` | required when dispatch enabled | none | `swing-trading-report` | web `/api/run` | GitHub repo for workflow dispatch | Ref is fixed to `main`. |
| `GITHUB_PAT` | required when dispatch enabled | none | `replace-with-github-token` | web `/api/run` | GitHub token for workflow dispatch | Secret. Server-only. |
| `REPORT_RETENTION_DAYS` | no | `30` | `30` | web, cleanup workflow | Retention days display/cleanup input | Cleanup workflow validates positive integer. |
| `REPORT_SEARCH_WINDOW` | no | `100` | `100` | web reports | Ticker search scan window | Code clamps min/max. |
| `MARKET_REGIME_UNAVAILABLE_POLICY` | no | `config.yaml` `strategy.market_regime_unavailable_policy` | `block_market` | `sab scan` | Market regime unavailable policy | Env/YAML conflict binding. |
| `TELEGRAM_BOT_TOKEN` | no | none | `replace-with-token` | workflows, scheduler | Telegram notification token | Secret. |
| `TELEGRAM_CHAT_ID` | no | none | `replace-with-chat-id` | workflows, scheduler | Telegram chat id | Treat as sensitive. |
| `SLACK_WEBHOOK_URL` | no | none | `https://hooks.slack.com/...` | workflows, scheduler | Slack notification webhook | Secret/internal URL; do not publish real value. |
| `SAB_SCHEDULER_ENV_FILE` | no | `.env.scheduler.local` | `.env.scheduler.local` | Docker scheduler | Env file path for one-shot scheduler | File is ignored by git. |
| `OPENAI_API_KEY` | required for OpenAI brief | none | `replace-with-openai-key` | `sab ai-brief`, scheduler | OpenAI model provider API key | Secret. |
| `OPENAI_AI_BRIEF_MODEL` | no | CLI model name | `gpt-...` | `sab ai-brief` | OpenAI model fallback | NEEDS_CONFIRMATION: production default model policy. |
| `AI_BRIEF_MODEL_TIMEOUT_SECONDS` | no | provider default | `20` | `sab ai-brief` | Model timeout | Positive finite number. |
| `AI_BRIEF_SOURCE_API_URL` | required for `http-json` provider | none | `https://source.example/api` | `sab ai-brief` | External source API URL | HTTPS only; no internal real URL in docs. |
| `AI_BRIEF_SOURCE_API_URL_KR` | no | none | `https://source.example/kr` | scheduled workflow | KR scheduled source API URL | GitHub variable. |
| `AI_BRIEF_SOURCE_API_URL_US` | no | none | `https://source.example/us` | scheduled workflow | US scheduled source API URL | GitHub variable. |
| `AI_BRIEF_SOURCE_API_TOKEN` | no | none | `replace-with-source-token` | source provider | Bearer token for matching configured source API URL | Secret. Only sent when the request URL matches `AI_BRIEF_SOURCE_API_URL`, `_KR`, or `_US`. |
| `AI_BRIEF_SOURCE_TIMEOUT_SECONDS` | no | provider default | `10` | source providers | Source provider timeout | Positive number. |
| `AI_BRIEF_SOURCE_PROVIDER_CHAIN_KR` | no | global chain/single-provider fallback | `naver-news` | scheduled runner | KR scheduled source provider chain | Market-specific chain wins over global chain and single-provider env. |
| `AI_BRIEF_SOURCE_PROVIDER_CHAIN_US` | no | global chain/single-provider fallback | `finnhub,benzinga-news,polygon-news` | scheduled workflow, scheduled runner | US scheduled source provider chain | Each provider's secret must be configured when that provider appears in the chain. |
| `AI_BRIEF_SOURCE_PROVIDER_CHAIN` | no | single-provider fallback | `finnhub,benzinga-news` | `sab ai-brief`, scheduled runner | Global source provider chain fallback | Used only when no explicit single provider/source path/API URL overrides it. |
| `AI_BRIEF_SOURCE_PROVIDER_KR` | no | global provider/API URL fallback | `naver-news` | scheduled workflow | KR scheduled source provider | GitHub variable. |
| `AI_BRIEF_SOURCE_PROVIDER_US` | no | global provider/API URL fallback | `finnhub` | scheduled workflow | US scheduled source provider | Current docs identify Finnhub as default single-provider fallback. |
| `AI_BRIEF_SOURCE_PROVIDER` | no | API URL fallback | `finnhub` | scheduled workflow | Global source provider fallback | Market-specific wins. |
| `FINNHUB_API_KEY` | provider-specific | none | `replace-with-finnhub-key` | `finnhub` | US news provider key | Secret. US-only. |
| `POLYGON_API_KEY` | provider-specific | none | `replace-with-polygon-key` | `polygon-news` | US news provider key | Secret. US-only. |
| `ALPHA_VANTAGE_API_KEY` | provider-specific | none | `replace-with-alpha-vantage-key` | `alpha-vantage-news` | US news provider key | Secret. US-only. |
| `MARKETAUX_API_TOKEN` | provider-specific | none | `replace-with-marketaux-token` | `marketaux-news` | US news provider token | Secret. US-only. |
| `BENZINGA_API_TOKEN` | provider-specific | none | `replace-with-benzinga-token` | `benzinga-news` | US news provider token | Secret. US-only. |
| `NAVER_CLIENT_ID` | provider-specific | none | `replace-with-naver-client-id` | `naver-news` | KR news provider client id | Secret. KR-only. |
| `NAVER_CLIENT_SECRET` | provider-specific | none | `replace-with-naver-client-secret` | `naver-news` | KR news provider client secret | Secret. KR-only. |
| `LOG_LEVEL` | no | `INFO` | `INFO` | CLI | Logging level | `sab/__main__.py`. |
| `LOG_FORMAT` | no | text format | `json` | CLI/scheduler | Logging format | Scheduler compose sets JSON. |
| `LOG_DATEFMT` | no | ISO-like default | `%Y-%m-%dT%H:%M:%S%z` | CLI | Logging date format | Optional. |
| `LOG_TZ` | no | `local` | `utc` | CLI/scheduler | Log timezone | `local` or `utc`. |
| `ENTRY_FATAL_MISSING_PRICE_RATIO` | no | active default `0.0` | `0.0` | `sab entry` | Missing entry price fatal threshold | Operational safety key. When YAML config is loaded, configure this in YAML; env override is accepted only when no YAML config is loaded. 0.0 means any missing price fails. |
| `SAB_CONFIG` | no | `config.yaml` | `config.local.yaml` | `sab` | Config file path override | Do not commit local config. |
| `SAB_CONFIG_STRICT` | no | true in CI/GHA | `true` | `sab` | Strict config parsing | Recommended for reproducing CI locally. |

## Config YAML

`config.yaml` is committed and contains non-secret defaults such as provider, report/data directories, screener thresholds, strategy parameters, sell rules, entry check settings, universe markets, holdings/watchlist file names, and FX mode.

YAML mapping keys must be unique at every level; duplicate keys fail closed instead of letting a later key mask an earlier safety setting. Empty top-level `strategy:` and `entry_check:` sections are rejected instead of falling back to code defaults. Valid nested safety values are accepted, but `null` or invalid values are rejected, for example `fatal_missing_price_ratio: null` under `entry_check:`.

Use `config.local.yaml` plus `SAB_CONFIG=config.local.yaml` for local experiments that should not be committed. When any YAML config is loaded, omitted operational safety keys inherit the active safety defaults: `strategy.use_market_regime_filter=true`, `strategy.market_regime_unavailable_policy=block_market`, and `entry_check.fatal_missing_price_ratio=0.0`. Environment overrides for those operational safety keys are rejected while YAML config is loaded, even if the YAML omits the key; set them explicitly in YAML when the local experiment intentionally changes the safety posture. With no YAML config loaded, the same active safety defaults still apply unless an explicit env override is set.

## Secret handling

```env
DATABASE_URL=postgres://user:password@localhost:5432/app
API_BASE_URL=https://example.internal
JWT_SECRET=replace-with-secure-random-value
```

The example above is a placeholder style only. Do not copy real internal URLs, DB credentials, tokens, personal email, phone numbers, cookies, private keys, or customer names into docs.

## Validation

```bash
UV_CACHE_DIR=.uv-cache uv run python -m pytest tests/test_config_secret_policy.py tests/test_config_conflict_policy.py tests/test_config_validation_layers.py tests/test_runtime_config_contract.py tests/test_env_example_v11.py -q
pnpm --dir web run build
```

`pnpm --dir web run build` requires valid or CI-placeholder web env values.
