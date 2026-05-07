# 런북 — CLI + Web 운영 가이드

상태: Accepted (운영 runbook)

로컬에서 CLI와 웹 UI를 실행/디버그/운영하기 위한 실무 지침입니다.

## 문서 상태

### 현재 제공

- CLI `scan`/`sell`/`entry`/`ai-brief` 실행, AI Brief source payload 수집/평가, 웹 prod/dev 실행, Holdings Add Buy, YAML import/export, scan/sell Run 트리거를 현재 다룹니다.
- schedule 기반 알림, 수동/scheduled AI brief workflow와 알림 발송, branch protection 운영 절차도 현재 runbook 범위에 포함합니다.

### 실험

- 별도 운영 실험 절차는 두지 않습니다. 파라미터 실험은 replay fixture와 회귀 테스트로 검증합니다.

### 백로그

- `entry` workflow_dispatch와 웹 `Run` 탭 연결
- branch protection stage1 복귀와 stage2 signed commit 적용

### 폐기 후보

- 구식 기본값(`SAB_LOGIN_THROTTLE_FAIL_MODE=degrade`) 기준 설명은 유지하지 않습니다.

## 설치/준비

- uv 설치: `curl -LsSf https://astral.sh/uv/install.sh | sh`
- 의존성 동기화: `UV_CACHE_DIR=.uv-cache uv lock -U && UV_CACHE_DIR=.uv-cache uv sync --all-groups`
- (선택) 반복 명령 실행기: `just --list`
- toolchain 동기화: `mise install` (도구 버전 변경 시 `mise lock --platform linux-x64,macos-arm64 && mise install`)
  - (선택) direnv 사용:
    - zsh 훅: `echo 'eval "$(direnv hook zsh)"' >> ~/.zshrc`
    - 프로젝트 최초 1회: `direnv allow .`
    - 기본값은 `.envrc`에서 관리, 개인 오버라이드는 `.envrc.local` 사용(`.envrc.local.example` 참고)
    - `.env`는 direnv가 아니라 애플리케이션(`sab`)이 로드
  - 설정:
    - `config.yaml` 생성(기본값은 `config.example.yaml` 참고)
    - `.env`에는 v1.1 필수 키를 작성:
      - KIS: `KIS_APP_KEY`, `KIS_APP_SECRET`, (선택) `KIS_BASE_URL`
      - Supabase: `SUPABASE_URL`, `SUPABASE_SECRET_KEY`(권장), `SUPABASE_SERVICE_ROLE_KEY`(레거시 폴백)
      - Web(기본): `SAB_BASIC_AUTH_USER`, `SAB_BASIC_AUTH_PASS`, `SAB_SESSION_SECRET`, (표시용) `REPORT_RETENTION_DAYS`
      - Run 트리거(선택): `RUN_DISPATCH_ENABLED`(기본 `0`), `GITHUB_OWNER`, `GITHUB_REPO`, `GITHUB_PAT` (`RUN_DISPATCH_ENABLED=1`일 때 필수)
        - 하위 호환: `RUN_DISPATCH_ENABLED`가 비어 있고 `GITHUB_*` 3종이 모두 설정된 기존 환경은 자동 활성
      - Web 로그인 제한(선택): `SAB_LOGIN_MAX_ATTEMPTS`, `SAB_LOGIN_WINDOW_SECONDS`, `SAB_LOGIN_BLOCK_SECONDS`
      - 로그인 스로틀 장애 정책(선택): `SAB_LOGIN_THROTTLE_FAIL_MODE` (`degrade`/`strict`, 기본 `strict`)
      - 런타임 상태 저장소(선택): `SAB_RUNTIME_STATE_STORE` (`supabase`/`memory`, 기본은 테스트 외 `supabase`)
      - Entry 종료 임계치(선택): `ENTRY_FATAL_MISSING_PRICE_RATIO` (0.0~1.0, 기본 `1.0`)
        - `0.0`은 누락이 1건이라도 있으면 실패로 해석
      - Web 로컬 실행(선택): `WEB_HOST_PORT`(prod, 기본 `55300`), `WEB_DEV_HOST_PORT`(dev, 기본 `55301`)
      - Notify(자동 실행/AI Brief 수동 opt-in 및 schedule): `TELEGRAM_BOT_TOKEN`, `TELEGRAM_CHAT_ID`, `SLACK_WEBHOOK_URL`
      - AI Brief OpenAI provider(scheduled AI Brief는 필요): `OPENAI_API_KEY`, `OPENAI_AI_BRIEF_MODEL`, `AI_BRIEF_MODEL_TIMEOUT_SECONDS`
      - AI Brief 외부 source API provider(선택): `AI_BRIEF_SOURCE_API_URL`, `AI_BRIEF_SOURCE_API_TOKEN`, `AI_BRIEF_SOURCE_TIMEOUT_SECONDS`
    - `config.yaml`과 `.env`에 동일 키를 중복 정의하지 않기(충돌 시 실패)
    - 선택: `uv sync --extra pykrx`로 KR 폴백/프로바이더 활성화
- 런타임:
  - Python 3.14+
  - Node.js + pnpm (버전 기준: `web/Dockerfile`, `web/package.json`)
  - 권장: `mise install`로 toolchain 동기화(`mise.lock` 기준)
  - 권장: `eval "$(mise activate zsh)"` 또는 `mise x -- <cmd>`로 mise 환경에서 실행
  - Docker Desktop + Docker Compose
- Supabase(권장):
  - 보유 목록/리포트/실행 이력은 Supabase(Postgres/Storage)를 단일 소스로 사용합니다.
  - GitHub Actions 런너가 자동 실행할 때도 동일한 Supabase를 사용합니다.
  - 로컬 `supabase/config.toml`은 idle Docker 사용량 절감을 위해 `realtime`, `studio`, `inbucket`, `analytics`를 기본 비활성화합니다.
  - 기본 앱 경로는 Postgres/Storage/runtime_state만 사용합니다. Studio/Realtime/메일 테스트가 필요한 경우에만 해당 서비스를 임시로 다시 켭니다.

## 웹 UI 로컬 실행(Next.js + Docker)

- 기본 운영 기준:
  - `web` 서비스는 이미지 빌드 시 `pnpm run build`를 수행하고, 런타임 엔트리는 `pnpm run start`만 실행합니다.
  - 당분간 운영 범위는 `localhost/127.0.0.1` 단일 사용자 노출만 지원합니다(외부 공개 배포 비대상).
  - direct 실행에서 `SAB_ENFORCE_LOCAL_REQUEST=0`와 non-loopback bind를 함께 쓰면 시작 단계에서 차단됩니다.
  - Docker Compose의 `WEB_BIND_HOST=0.0.0.0`는 컨테이너 내부 바인딩일 뿐이며, 호스트 publish가 `127.0.0.1:${WEB_HOST_PORT}:3000`이면 지원 경로입니다.
  - 로컬 Supabase는 idle 리소스 절감을 위해 최소 프로필(`realtime`, `studio`, `inbucket`, `analytics` 비활성화)을 기본값으로 둡니다.
- 전환 직후 1회 정리:
  - `docker compose down --remove-orphans && docker compose up -d --build web`
- 일반 재기동:
  - `docker compose up -d --build web`
- 개발 모드(HMR):
  - `docker compose --profile dev up -d --build web-dev`
- 개발 모드 중지:
  - `docker compose stop web-dev`
- 강제 재생성(문제 시):
  - `docker compose stop web`
  - `docker compose rm -f web`
  - `docker compose up -d --build web`
- 로그 확인(prod):
  - `docker compose logs -f web`
- 로그 확인(dev):
  - `docker compose --profile dev logs -f web-dev`
- 중지:
  - `docker compose stop web`
- 접속(prod):
  - `http://localhost:${WEB_HOST_PORT}` (기본값 `55300`)
- 접속(dev):
  - `http://localhost:${WEB_DEV_HOST_PORT}` (기본값 `55301`)
- 인증:
  - `/login` 페이지에서 관리자 계정(`SAB_BASIC_AUTH_USER/PASS`)으로 로그인하면 HttpOnly 세션 쿠키가 발급됩니다.
- 포트 변경(prod):
  - `.env`에 `WEB_HOST_PORT=55444` 설정 후 `docker compose up -d --build web`
- 포트 변경(dev):
  - `.env`에 `WEB_DEV_HOST_PORT=55445` 설정 후 `docker compose --profile dev up -d --build web-dev`
- 기본 화면:
  - `Reports`: Storage 리포트 목록/상세/검색
  - `Holdings`: Supabase `holdings` CRUD
  - `Run`: scan/sell `workflow_dispatch` 실행 트리거

## 보유 목록(holdings)

- 보유 목록은 **웹 UI(Next.js)에서 CRUD**로 관리합니다(단일 사용자 기준).
- `quantity<=0` 항목은 Holdings UI에서 비활성으로 취급되며, 기본은 숨김이고 토글로 표시할 수 있습니다.
- `holdings` ticker 계약은 앱/DB 모두 동일하며, `.US` 같은 모호 suffix는 허용되지 않습니다. 기존 `.US` row가 있으면 관련 Supabase migration은 수동 정리 전까지 실패합니다.
- 추가매수 API(`POST /api/holdings/[ticker]/add-buy`)는 UUID 형식 `Idempotency-Key` 헤더를 필수로 요구하며, 동일 키-다른 payload는 `409`(`code=IDEMPOTENCY_KEY_PAYLOAD_MISMATCH`)로 차단합니다.
- `sab sell`/`sell.yml`은 `quantity>0` 활성 보유분만 평가합니다.
- 멱등 이벤트 정리 스케줄: `holdings-add-buy-events-cleanup` (`30 3 * * `*, UTC)에서 `public.cleanup_holdings_add_buy_events(interval '90 days', 500)`를 호출합니다.
  - 정리 대상: `processed=true AND created_at < now()-90d` 또는 `processed=false AND updated_at < now()-90d`
  - fail-closed 정책: `pg_cron` 미활성 환경에서는 스케줄 보강 마이그레이션이 실패하도록 강제합니다(무음 누락 방지).
- 스케줄 점검 SQL(Supabase SQL Editor):
  - cron 확장 확인: `select to_regnamespace('cron') as cron_schema;`
  - 등록 확인: `select jobid, jobname, schedule, command, active from cron.job where jobname = 'holdings-add-buy-events-cleanup';`
  - 수동 실행: `select public.cleanup_holdings_add_buy_events(interval '90 days', 500);`
  - 적체 점검(미처리): `select count(*) from public.holdings_add_buy_events where processed = false and updated_at < now() - interval '90 days';`
  - 최근 실행 이력: `select runid, jobid, status, return_message, start_time, end_time from cron.job_run_details where jobid = (select jobid from cron.job where jobname = 'holdings-add-buy-events-cleanup' limit 1) order by start_time desc limit 20;`
- Supabase 반영 체크리스트(원격 프로젝트):
  1. 백업/복구 경로 확인
    - `supabase db dump --linked --schema public --file backup-before-add-buy-cleanup.sql`
  2. 링크 상태 확인(최초 1회 또는 프로젝트 변경 시)
    - `supabase link --project-ref <PROJECT_REF>`
  3. 마이그레이션 차이 점검
    - `supabase migration list`
    - 이번 릴리스에 포함되는 파일:
      - `supabase/migrations/20260304002000_add_holdings_add_buy_idempotency.sql`
      - `supabase/migrations/20260304003000_schedule_add_buy_event_cleanup_cron.sql`
      - `supabase/migrations/20260304004000_expand_add_buy_cleanup_to_stale_unprocessed.sql`
      - `supabase/migrations/20260304005000_require_add_buy_cleanup_cron.sql`
  4. 적용 전 dry-run
    - `supabase db push --dry-run`
  5. 원격 적용
    - `supabase db push`
  6. 적용 후 즉시 검증(SQL Editor)
    - 함수 정의 확인: `select pg_get_functiondef('public.cleanup_holdings_add_buy_events(interval, integer)'::regprocedure);`
    - 정리 대상 건수 확인: `select count(*) from public.holdings_add_buy_events where (processed = true and created_at < now() - interval '90 days') or (processed = false and updated_at < now() - interval '90 days');`
    - 크론 등록/활성 확인: `select jobid, jobname, schedule, command, active from cron.job where jobname = 'holdings-add-buy-events-cleanup';`
## 자주 쓰는 실행

- Buy 스캔(KR+US 스크리너 + 워치리스트)
  - `UV_CACHE_DIR=.uv-cache uv run -m sab scan --universe both`
- Buy 스캔(스크리너만, 상위 20)
  - `UV_CACHE_DIR=.uv-cache uv run -m sab scan --universe screener --screener-limit 20`
- 보유 매도/보류 평가
  - `UV_CACHE_DIR=.uv-cache uv run -m sab sell`
- just 레시피(동일 동작)
  - `just scan --universe both`
  - `just sell`
  - `just ai-brief-source-collect --feed-catalog feeds.json --output captured.sources.json`
  - `just ai-brief-source-eval --entry-report reports/example.entry.json --source-report captured.sources.json`
  - `just quality`
  - `just check`
  - `just precommit-all`
  - `just ci-python`
  - `just ci-web` (비밀 없는 고정 CI placeholder env 사용)
- 웹 UI(Next.js)
  - `docker compose up -d --build web`
  - 접속(prod): `http://localhost:${WEB_HOST_PORT}` (기본값 `55300`)
  - 개발 모드(HMR): `docker compose --profile dev up -d --build web-dev`
  - 접속(dev): `http://localhost:${WEB_DEV_HOST_PORT}` (기본값 `55301`)
  - 또는 웹 디렉터리에서 직접 실행: `pnpm install && pnpm run dev`
  - Holdings 화면의 `Export YAML` 버튼으로 전체 holdings를 `holdings.yaml`로 다운로드할 수 있습니다.
  - Holdings 사이드바 import 패널은 선택한 `holdings.yaml`에 대해 dry-run diff(create/update/delete/unchanged)를 먼저 보여준 뒤, `Apply Import`로 **Replace All** 적용을 수행합니다.
  - import는 파일에 없는 ticker를 삭제합니다. 백업 복구 용도이므로 apply 전 dry-run 결과를 반드시 확인하세요.
- 자동 실행(GitHub Actions)
  - `schedule`로 scan/sell을 실행하고, 결과를 Supabase에 저장합니다.
  - 알림은 자동 실행일 때만 전송합니다.
  - 텔레그램: 리포트 본문(매수 후보/매도·점검 후보 상위 5건 + 나머지 개수)을 전송합니다.
  - 슬랙: 기존 key=value 요약 포맷을 유지합니다.
- AI Brief 수동/scheduled 실행(GitHub Actions)
  - `.github/workflows/ai-brief.yml`은 `workflow_dispatch`와 KR/US 장전 schedule을 지원합니다.
  - 단일 `market=KR|US`에 대해 scan → Supabase holdings snapshot → entry → ai-brief를 순서대로 실행합니다.
  - scheduled 실행은 KR `30 22 * * 0-4` UTC, US `30 12 * * 1-5` UTC에서 시작합니다.
  - scheduled 실행은 장일+`PRE_OPEN` 런타임 가드가 통과할 때만 dependency install, scan, entry, ai-brief, 알림 단계를 진행합니다.
  - scheduled 기본값은 `provider=kis`, `universe=both`, `entry_mode=PRE_OPEN`, `model_provider=openai`, `send_notifications=true`입니다.
  - `AI_BRIEF_SOURCE_API_URL` 변수가 설정되어 있으면 scheduled 실행은 `source_provider=http-json`로 외부 source API context를 함께 주입합니다. 수동 실행에서는 `source_provider=http-json`과 `source_api_url` 입력을 사용합니다.
  - `http-json` source API는 HTTPS URL만 허용하며 local/private host와 redirect 응답은 거부됩니다. API는 `{"schema":"sab.ai_brief_source_request.v1","tickers":[...],"max_sources_per_ticker":3,"freshness_hours":72}`를 POST로 받고, `sources[]` row(`ticker`, `title`, HTTP(S) `url`, offset 포함 `published_at`)를 반환해야 합니다. source 시간은 72시간 이내이고 15분 넘는 미래 시간이면 무시됩니다. API token secret은 실행 URL이 설정된 `AI_BRIEF_SOURCE_API_URL` 변수와 일치할 때만 Bearer 토큰으로 전송합니다.
  - RSS/Atom/RDF feed에서 source payload를 만들 때는 `just ai-brief-source-collect --feed-catalog <feeds.json> --output <sources.json>`를 사용합니다. feed catalog는 ticker별 로컬 파일 경로(`path`/`feed_path`) 또는 live HTTPS feed URL(`url`/`feed_url`) 중 정확히 하나를 담고, 도구는 fresh source만 ticker별 최대 3건까지 `sab.ai_brief_sources.v1` payload로 출력합니다.
    - catalog 예: `{"schema":"sab.ai_brief_source_feed_catalog.v1","feeds":[{"ticker":"AAPL.NAS","path":"aapl.rss"}]}`
    - live URL catalog 예: `{"schema":"sab.ai_brief_source_feed_catalog.v1","feeds":[{"ticker":"AAPL.NAS","url":"https://example.com/aapl.xml"}]}`
    - live feed URL은 HTTPS만 허용하고 userinfo, local/private host, redirect, 1MB 초과 응답을 거부합니다. `--feed-timeout-seconds` 기본값은 10초이며, HTTP/timeout/invalid feed는 전체 실패가 아니라 ticker별 `issues[]` WARN으로 남습니다.
  - scheduled AI Brief의 운영 source 경로는 계속 `AI_BRIEF_SOURCE_API_URL` 기반 `http-json`을 사용합니다. 유료/벤더별 JSON API adapter는 SAB 내부 SDK가 아니라 이 외부 source API 경계 뒤에서 운영하는 후속 작업입니다. captured/live feed `sources[]` payload 품질은 `just ai-brief-source-eval --entry-report <entry.json> --source-report <sources.json>`로 점검합니다. `market=MIXED` entry report는 `--market KR|US`를 함께 지정합니다.
  - 결과물은 Actions artifact(`buy`, `entry`, `ai-brief` JSON과 Slack/Telegram preview 텍스트)로 남기고, AI Brief 리포트는 Supabase Storage/`report_index`에도 업로드합니다.
  - 수동 실행에서 `send_notifications=true`를 선택하면 생성된 preview 텍스트를 Telegram/Slack으로 실제 발송합니다. 기본값은 `false`입니다.
  - 관련 secret이 없으면 발송 단계는 skip하며 workflow 자체는 계속 성공할 수 있습니다.
  - `provider=pykrx`는 `market=KR`, `universe=watchlist`, `entry_mode=AFTER_CLOSE` 조합에서만 허용합니다.
- Audit 실행(GitHub Actions)
  - 감사 워크플로: `.github/workflows/audit.yml`
  - 트리거: `pull_request`, `workflow_dispatch`, 매주 월요일 11:00 UTC(`0 11 * * 1`)
  - Job:
    - `workflow_audit`: `rhysd/actionlint`로 워크플로 YAML 정합성 검사
    - `security_audit`: `aquasecurity/trivy-action`으로 `vuln,secret` 통합 검사
  - 차단 기준: `HIGH,CRITICAL` 발견 시 실패(`ignore-unfixed=true`)
  - 산출물: `trivy-results.json` 아티팩트(성공/실패와 무관하게 업로드)
- 로컬 CLI 업로드(선택)
  - 기본은 로컬 파일 생성만 수행합니다.
  - `scan`/`sell`을 로컬에서 Supabase로 올리려면 `SAB_UPLOAD_REPORTS=true`를 설정합니다.
  - `entry`는 `SAB_UPLOAD_REPORTS=true` 또는 `sab entry --upload`로 Storage/`report_index` 업로드를 수행할 수 있습니다.
  - `ai-brief`는 `SAB_UPLOAD_REPORTS=true` 또는 `sab ai-brief --upload`로 Storage/`report_index` 업로드를 수행할 수 있습니다.

## Audit 수동 점검

- 빠른 점검:
  - `trivy fs .`
- CI 동일 정책 점검:
  - `trivy fs --scanners vuln,secret --severity HIGH,CRITICAL --ignore-unfixed --format json --output trivy-results.json .`
- 취약점 예외:
  - `.trivyignore`에 임시 예외만 등록
  - 항목별 만료일/사유 주석 필수
  - 만료된 예외는 즉시 삭제

## PR 차단 기준(브랜치 보호)

- `main` 브랜치 보호 규칙은 classic branch protection으로 관리합니다.
- 현재 운영 모드는 임시 `solo-dev`로, `main` 직접 push를 허용합니다.
- `required_status_checks=null`, `required_pull_request_reviews=null` 상태입니다.
- `enforce_admins=true`로 관리자 우회를 차단합니다.
- `allow_force_pushes=false`, `allow_deletions=false`는 유지합니다.
- PR 기반 운영으로 복귀 시 `docs/governance/main-branch-protection.stage1.payload.json`을 적용하고,
- 아래 4개 Required status checks를 복원합니다:
  - `Ruff + Mypy + Pytest (Python 3.14)`
  - `Next.js Web (Lint + Typecheck + Test + Build)`
  - `workflow_audit`
  - `security_audit`
- 모드 전환/동기화 절차와 2단계 상향 기준은 `docs/governance/main-branch-protection.md`를 따릅니다.

## 파일/경로

- 로컬 리포트(개발/디버그): `reports/YYYY-MM-DD.buy.json`, `...sell.json`, `...entry.json`, `...ai-brief.json`(중복 시 `-1`)
- Storage 오브젝트 키(공식 보관): `YYYY/MM/YYYY-MM-DD.buy.json`, `...sell.json`, `...entry.json`, `...ai-brief.json`(중복 시 `-1`, `-2`, ...)
- Storage 업로드 MIME: `contentType=application/json`으로 고정(`reports` 버킷 정책)
- 키 규칙 구현: `sab/report/storage_key.py`의 `build_report_storage_key`
- 캐시/상태: `data/`(KIS 토큰, 캔들, 스크리너 캐시)
- 보유 목록(공식 소스): Supabase Postgres `holdings` 테이블
- 선택 백업 파일: `holdings.yaml`(웹 UI import/export 용도, export는 inactive row까지 포함)

## 문제 해결

- 토큰 오류/401: `KIS_APP_KEY/SECRET/BASE_URL` 확인, `data/kis_token_`* 삭제로 강제 갱신(24시간 정책 유의)
- 레이트리밋 `EGW00201`: `KIS_MIN_INTERVAL_MS`(예: 500–1000) 증가 후 재시도. 스크리너 TTL도 호출 수 절감에 도움
- 히스토리 부족: `MIN_HISTORY_BARS=200+` 권장, 누적 수집으로 보완. 신규상장 등은 기준 미달 가능
- US 심볼: `SYMBOL.NAS/NYS/AMS`(또는 동의어 `NASDAQ/NYSE/AMEX`)처럼 거래소를 명시해 사용. `.US`는 입력에서 허용되지 않음. US에는 PyKRX 폴백이 적용되지 않음
- US 클래스 심볼: `BRK.B.NYS`가 캐노니컬이며, `BRK/B.NYS` 입력은 내부에서 `BRK.B.NYS`로 정규화
- KIS 클래스 심볼 호환: 내부 캐노니컬은 dot(`BRK.B`)를 유지하고, KIS 호출에서는 `invalid symbol(msg_cd=SYMB0001)`일 때에만 dot/slash 대체 표기를 1회 시도합니다. 그 외 오류(레이트리밋/토큰/서버)는 즉시 실패하며, 성공 형태는 런타임에 기억합니다.
- US 스크리너: `screener.us_mode=kis`는 자동 폴백 없이 fail-closed. `--universe screener`에서는 즉시 실패, `--universe both`에서는 watchlist는 유지하고 US 스크리너만 건너뜀
- watchlist 로딩: `--universe watchlist|both`에서 watchlist 파일이 없으면 즉시 실패합니다. `--universe screener`에서는 watchlist를 로드하지 않습니다.
- 환율/통화: `FX_MODE=kis`(기본)로 설정하면 KIS 해외 현재가상세에서 `t_rate`를 받아 자동 환율을 적용하고, `FX_CACHE_TTL`분 동안 캐시합니다. 실패 시 `USD_KRW_RATE` 값으로 폴백하거나, 값이 없으면 리포트 Appendix에 경고를 남깁니다.
- 휴장일: 미국 휴일 정보는 KIS `countries-holiday` API를 조회해 `data/holidays_us.json`에 캐시합니다.
  - 파일이 없거나 12시간 TTL을 넘긴 경우에만 재조회하며, 기본 refresh 구간은 10일입니다.
  - 파일을 삭제하면 다음 실행 시 자동 갱신됩니다.

## 확장

- RS 벤치마크: `strategy.rs_benchmark_ticker_kr` / `strategy.rs_benchmark_ticker_us`로 시장별 benchmark ticker를 지정하면, scan이 adjusted benchmark 시계열을 직접 조회해 `rs_benchmark_return`을 동적으로 계산합니다.
- Entry 체크: buy report의 `entry_reference_close_raw_value`가 있으면 raw/live 가격 기준으로 자동 gap guard를 적용하고, reference close가 없거나 basis가 없는 레거시 candidate는 `REVIEW`로 처리합니다.
