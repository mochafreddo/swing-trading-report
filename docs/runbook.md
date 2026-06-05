# 런북 — CLI + Web 운영 가이드

상태: Accepted (운영 runbook)

로컬에서 CLI와 웹 UI를 실행/디버그/운영하기 위한 실무 지침입니다.

## 문서 상태

### 현재 제공

- CLI `scan`/`sell`/`entry`/`ai-brief` 실행, AI Brief source payload 수집/평가/live 비교, 선택 live integration smoke, 웹 prod/dev 실행, Holdings Add Buy, YAML import/export, scan/sell Run 트리거를 현재 다룹니다.
- schedule 기반 알림, 수동/scheduled AI brief workflow와 알림 발송, branch protection 운영 절차도 현재 runbook 범위에 포함합니다.

### 실험

- 별도 운영 실험 절차는 두지 않습니다. 파라미터 실험은 replay fixture와 회귀 테스트로 검증합니다.

### 백로그

- standalone `entry` workflow_dispatch와 웹 `Run` 탭 연결
- branch protection stage1 복귀와 stage2 signed commit 적용

### 폐기 후보

- 구식 기본값(`SAB_LOGIN_THROTTLE_FAIL_MODE=degrade`) 기준 설명은 유지하지 않습니다.

## 설치/준비

- uv 설치: `curl -LsSf https://astral.sh/uv/install.sh | sh`
- 의존성 동기화: `UV_CACHE_DIR=.uv-cache uv sync --all-groups`
- 잠금 파일 갱신(필요할 때만): `UV_CACHE_DIR=.uv-cache uv lock`
- 의존성 버전 상향(업그레이드 목적일 때만): `UV_CACHE_DIR=.uv-cache uv lock --upgrade`
- (선택) 반복 명령 실행기: `just --list`
- toolchain 동기화: `mise install` (도구 버전 변경 시 `mise lock --platform linux-x64,macos-arm64 && mise install`)
  - (선택) direnv 사용:
    - zsh 훅: `echo 'eval "$(direnv hook zsh)"' >> ~/.zshrc`
    - 프로젝트 최초 1회: `direnv allow .`
    - 기본값은 `.envrc`에서 관리, 개인 오버라이드는 `.envrc.local` 사용(`.envrc.local.example` 참고)
    - `.env`는 direnv가 아니라 애플리케이션(`sab`)이 로드
  - 설정:
    - `config.yaml` 확인:
      - 이 저장소는 기본 `config.yaml`을 버전관리에 포함합니다.
      - 다른 엔드포인트/임계치를 쓰는 로컬 실험은 `config.local.yaml` + `SAB_CONFIG=config.local.yaml`처럼 분리합니다.
      - 권장 샘플은 `config.example.yaml` 참고
      - 생략/invalid mode의 런타임 폴백은 하위 호환 기본값 사용
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
      - 로컬 scheduled AI Brief wrapper(비시크릿): `SAB_SCHEDULER_ENV_FILE=.env.scheduler.local`
      - AI Brief OpenAI provider(scheduled AI Brief는 필요): `OPENAI_API_KEY`, `OPENAI_AI_BRIEF_MODEL`, `AI_BRIEF_MODEL_TIMEOUT_SECONDS`
      - AI Brief 외부 source API provider(선택): `AI_BRIEF_SOURCE_API_URL`, `AI_BRIEF_SOURCE_API_URL_KR`, `AI_BRIEF_SOURCE_API_URL_US`, `AI_BRIEF_SOURCE_API_TOKEN`, `AI_BRIEF_SOURCE_TIMEOUT_SECONDS`
      - AI Brief Finnhub source provider(선택, US-only): `FINNHUB_API_KEY`
      - AI Brief Polygon News source provider(선택, US-only): `POLYGON_API_KEY`
      - AI Brief Alpha Vantage News source provider(선택, US-only): `ALPHA_VANTAGE_API_KEY`
      - AI Brief Marketaux News source provider(선택, US-only): `MARKETAUX_API_TOKEN`
      - AI Brief Benzinga News source provider(선택, US-only): `BENZINGA_API_TOKEN`
      - AI Brief Naver News source provider(선택, KR-only): `NAVER_CLIENT_ID`, `NAVER_CLIENT_SECRET`
      - AI Brief scheduled 기본 source provider(선택, repository variable): 시장별 `AI_BRIEF_SOURCE_PROVIDER_KR=naver-news`, `AI_BRIEF_SOURCE_PROVIDER_US=finnhub|polygon-news|alpha-vantage-news|marketaux-news|benzinga-news` 권장. 전역 fallback으로 `AI_BRIEF_SOURCE_PROVIDER=...`도 지원. 2026-05-23 기준 운영 기본값은 `AI_BRIEF_SOURCE_PROVIDER_US=finnhub`입니다. Polygon/Benzinga는 backup/comparison provider로 유지하지만 기본값으로 승격하려면 live comparison과 source/recommendation eval을 다시 통과해야 합니다. 근거와 follow-up은 `docs/ai-brief-us-source-provider-decision.md`를 참고합니다.
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

## 원격 Supabase 복구 기준

원격/production Supabase 장애 후에는 "프로젝트가 다시 응답한다"만으로 복구 완료로 보지 않습니다. 아래 기준을 모두 통과하거나, 통과하지 못한 항목을 장애 기록에 명시해야 합니다.

- 복구 전 확인:
  - Supabase 프로젝트 ref가 의도한 원격 프로젝트인지 확인합니다. 프로젝트 ref/URL은 운영자 개인 환경에서 확인하고 문서나 로그에 비밀값을 남기지 않습니다.
  - 데이터 변경 복구를 시작하기 전에는 가능한 경우 public schema dump를 먼저 남깁니다: `supabase db dump --linked --schema public --file backup-before-supabase-recovery.sql`
  - `runtime_state` marker 삭제는 중복 리포트/중복 Telegram 발송을 만들 수 있으므로, owner/TTL/Storage object를 확인한 뒤 필요한 key만 삭제합니다. `success`와 `notification:sent` marker는 의도적인 재처리가 아니면 유지합니다.
- 마이그레이션/보안 기준:
  - `supabase migration list`에서 원격이 저장소 migration과 동기화되어야 합니다.
  - SQL Editor에서 필수 테이블과 RLS/권한 상태를 확인합니다. 기대값은 `holdings`, `report_index`, `runtime_state`가 모두 존재하고, RLS/force RLS가 켜져 있으며, `anon`/`authenticated`의 직접 권한 row가 없는 상태입니다.
    ```sql
    select table_name
    from information_schema.tables
    where table_schema = 'public'
      and table_name in ('holdings', 'report_index', 'runtime_state')
    order by table_name;

    select tablename, rowsecurity, forcerowsecurity
    from pg_tables
    where schemaname = 'public'
      and tablename in ('holdings', 'report_index', 'runtime_state')
    order by tablename;

    select grantee, table_name, privilege_type
    from information_schema.role_table_grants
    where table_schema = 'public'
      and table_name in ('holdings', 'report_index', 'runtime_state')
      and grantee in ('anon', 'authenticated')
    order by table_name, grantee, privilege_type;
    ```
- Storage 기준:
  - `reports` bucket이 private이고 JSON 업로드만 허용해야 합니다.
    ```sql
    select id, public, allowed_mime_types
    from storage.buckets
    where id = 'reports';
    ```
  - 최근 object key는 `YYYY/MM/YYYY-MM-DD(.n).buy|sell|entry|ai-brief|ai-brief-skip.json` 규칙을 따라야 합니다.
    ```sql
    select name, created_at, updated_at
    from storage.objects
    where bucket_id = 'reports'
    order by created_at desc
    limit 20;
    ```
- `report_index`/Storage 정합성 기준:
  - `report_index.report_type`은 `buy`, `sell`, `entry`, `ai-brief`, `ai-brief-skip`만 있어야 합니다.
  - 아래 두 mismatch 쿼리는 모두 0행이어야 합니다. 오래된 수동 object나 의도적으로 삭제한 리포트가 있으면 장애 기록에 예외로 남깁니다.
    ```sql
    select report_type, count(*) as rows, max(report_date) as latest_report_date
    from public.report_index
    group by report_type
    order by report_type;

    select ri.report_key
    from public.report_index as ri
    left join storage.objects as objects
      on objects.bucket_id = 'reports'
     and objects.name = ri.report_key
    where objects.name is null
    order by ri.report_date desc, ri.report_key desc
    limit 20;

    select objects.name
    from storage.objects as objects
    left join public.report_index as ri
      on ri.report_key = objects.name
    where objects.bucket_id = 'reports'
      and objects.name ~ '^\d{4}/\d{2}/\d{4}-\d{2}-\d{2}(?:-\d+)?\.(buy|sell|entry|ai-brief|ai-brief-skip)\.json$'
      and ri.report_key is null
    order by objects.created_at desc
    limit 20;
    ```
- Holdings 기준:
  - active row(`quantity > 0`)가 웹 Holdings 화면과 일치해야 합니다.
  - ticker 계약 위반 row가 없어야 합니다. 특히 `.US` suffix는 복구 대상 데이터에 남기지 않습니다.
    ```sql
    select count(*) filter (where quantity > 0) as active_rows,
           count(*) as total_rows,
           max(updated_at) as latest_update
    from public.holdings;

    select ticker
    from public.holdings
    where ticker ~* '\.US$'
       or not (
         ticker ~ '^\d{6}$'
         or ticker ~ '^[A-Z][A-Z0-9]*(\.[ABC])?\.(NAS|NYS|AMS)$'
       )
    order by ticker;
    ```
- `runtime_state`/scheduler 기준:
  - lock RPC 변경, migration 복구, 또는 scheduled AI Brief 중복 실행 의심 후에는 `just runtime-state-lock-smoke`가 통과해야 합니다.
  - scheduled AI Brief 복구 완료는 당일 session date에 `artifact` 또는 `skip-artifact` marker가 있고, 정상 알림 경로에서는 `notification:sent`와 `success` marker가 함께 있을 때로 봅니다.
    ```sql
    select state_key, state_payload, expires_at, updated_at
    from public.runtime_state
    where state_key like 'scheduled-ai-brief:%'
    order by updated_at desc
    limit 30;

    select count(*) as expired_rows
    from public.runtime_state
    where expires_at <= now();
    ```
- 사용자 관점 복구 확인:
  - 웹 `/login` liveness가 `200`을 반환하고, 로그인 후 `Reports`와 `Holdings`가 로드되어야 합니다.
  - 최근 GitHub Actions 또는 로컬 scheduled run이 Storage 업로드와 `report_index` upsert를 성공해야 합니다. GitHub Actions에서는 이 경로가 fail-closed이므로 업로드/upsert 실패 run을 성공으로 간주하지 않습니다.

## 웹 UI 로컬 실행(Next.js + Docker)

- 기본 운영 기준:
  - `web` 서비스는 이미지 빌드 시 `pnpm run build`를 수행하고, 런타임 엔트리는 `pnpm run start`만 실행합니다.
  - 당분간 운영 범위는 `localhost/127.0.0.1` 단일 사용자 노출만 지원합니다(외부 공개 배포 비대상).
  - direct 실행에서 non-loopback bind는 `SAB_ALLOW_NON_LOOPBACK_BIND=1` 없이 시작 단계에서 차단됩니다.
  - Docker Compose의 `WEB_BIND_HOST=0.0.0.0`는 명시적 override가 필요한 컨테이너 내부 바인딩이며, 호스트 publish가 `127.0.0.1:${WEB_HOST_PORT}:3000`이면 지원 경로입니다.
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
- 헬스체크/복구 확인:
  - 컨테이너 상태: `docker compose ps`(`sab-web`가 `running`인지) / 상세는 `docker inspect sab-web`
  - liveness 프로브: `curl -fsS -o /dev/null -w '%{http_code}\n' http://127.0.0.1:${WEB_HOST_PORT}/login` → `200` 기대. `/login`만 비인증 접근 가능하며, 보호 라우트(`/api/*`, 콘솔 페이지)는 인증 없으면 302 redirect 또는 401이므로 liveness 용도로 쓰지 않습니다.
  - 로그: `docker compose logs -f web`(에러/기동 완료 로그 확인)
  - 재시작: `docker compose up -d --build web`(문제 시 강제 재생성은 위 "강제 재생성" 절차)
  - 복구 확인: 위 liveness 프로브가 다시 `200`을 반환하고, 브라우저에서 `/login` 로그인 후 `Reports`가 로드되는지 확인
  - 참고: 현재 `web` 서비스에는 전용 health 엔드포인트와 compose `healthcheck:` 블록이 없습니다. 따라서 `docker compose ps`는 `healthy`가 아닌 `running`만 표시하며, 실제 정상 여부는 위 `/login` 프로브로 판단합니다.

## 보유 목록(holdings)

- 보유 목록은 **웹 UI(Next.js)에서 CRUD**로 관리합니다(단일 사용자 기준).
- `quantity<=0` 항목은 Holdings UI에서 비활성으로 취급되며, 기본은 숨김이고 토글로 표시할 수 있습니다.
- `holdings` ticker 계약은 앱/DB 모두 동일하며, `.US` 같은 모호 suffix는 허용되지 않습니다. 기존 `.US` row가 있으면 관련 Supabase migration은 수동 정리 전까지 실패합니다.
- 추가매수 API(`POST /api/holdings/[ticker]/add-buy`)는 UUID 형식 `Idempotency-Key` 헤더를 필수로 요구하며, 동일 키-다른 payload는 `409`(`code=IDEMPOTENCY_KEY_PAYLOAD_MISMATCH`)로 차단합니다.
- `sab sell`/`sell.yml`은 `quantity>0` 활성 보유분만 평가합니다.
- 멱등 이벤트 정리 스케줄: `holdings-add-buy-events-cleanup` (cron `30 3 * * *`, UTC)에서 `public.cleanup_holdings_add_buy_events(interval '90 days', 500)`를 호출합니다.
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
  - `UV_CACHE_DIR=.uv-cache uv run python -m sab scan --universe both`
- Buy 스캔(스크리너만, 상위 20)
  - `UV_CACHE_DIR=.uv-cache uv run python -m sab scan --universe screener --screener-limit 20`
- 보유 매도/보류 평가
  - `UV_CACHE_DIR=.uv-cache uv run python -m sab sell`
- just 레시피(동일 동작)
  - `just scan --universe both`
  - `just sell`
  - `just ai-brief-source-collect --feed-catalog feeds.json --output captured.sources.json`
  - `just ai-brief-source-eval --entry-report reports/example.entry.json --source-report captured.sources.json`
  - `just ai-brief-source-eval --entry-report reports/example.entry.json --compare-source-report finnhub=finnhub.sources.json --compare-source-report polygon=polygon.sources.json --compare-source-report av=alpha-vantage.sources.json --compare-source-report marketaux=marketaux.sources.json --compare-source-report benzinga=benzinga.sources.json --compare-source-report naver=naver.sources.json --now 2026-05-06T12:00:00+00:00 --pretty`
  - `just ai-brief-source-live-compare --entry-report reports/example.entry.json --provider finnhub=finnhub --provider polygon=polygon-news --provider benzinga=benzinga-news --market US --pretty`
  - `just live-integration-smoke --entry-report reports/example.entry.json --source-provider finnhub=finnhub --kis-token --kis-overseas-price-ticker AAPL.NAS --pretty`
  - `just ai-brief-eval --entry-report reports/YYYY-MM-DD.entry.json --ai-brief-report reports/YYYY-MM-DD.ai-brief.json`
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
  - 텔레그램: 리포트 본문(scan 진입 가능 후보 전체를 Telegram 한도에 맞춰 분할 전송, sell 매도·점검 후보 상위 5건 + 나머지 개수)을 전송합니다.
  - 슬랙: 기존 key=value 요약 포맷을 유지합니다.
- AI Brief 수동 실행(GitHub Actions)
  - `.github/workflows/ai-brief.yml`의 `workflow_dispatch`는 단일 `market=KR|US`에 대해 scan → Supabase holdings snapshot → entry → ai-brief를 순서대로 실행합니다.
  - 수동 실행에서는 `source_provider=none|local-json|http-json|finnhub|polygon-news|alpha-vantage-news|marketaux-news|benzinga-news|naver-news` 입력을 사용합니다.
  - `finnhub` source provider는 `FINNHUB_API_KEY` secret으로 Finnhub Company News를 ticker별 1회 조회합니다. v1은 US ticker만 지원하며 `AAPL.NAS`는 `AAPL`, `BRK.B.NYS`는 `BRK.B`로 요청하고, KR ticker는 요청하지 않은 채 `source_issues[]` WARN으로 남깁니다. 반환 row의 `headline`/`url`/Unix `datetime`은 기존 source row 계약으로 정규화되며, freshness/future-time/duplicate/cap/URL safety/DNS 검증을 통과한 row만 AI Brief 입력에 들어갑니다.
  - `polygon-news` source provider는 `POLYGON_API_KEY` secret으로 Polygon.io Stocks News endpoint(`https://api.polygon.io/v2/reference/news`)를 ticker별 1회 조회합니다. v1은 US ticker만 지원하며 `AAPL.NAS`는 `AAPL`, `BRK.B.NYS`는 `BRK.B`로 요청하고, KR ticker는 요청하지 않은 채 `source_issues[]` WARN으로 남깁니다. 요청은 `ticker`, `limit=10`, `order=desc`, `sort=published_utc`로 보내며 API key는 `Authorization: Bearer` header로만 전송합니다. 반환 row의 `title`/`article_url`/`published_utc`는 기존 source row 계약으로 정규화되며, freshness/future-time/duplicate/cap/URL safety/DNS 검증을 통과한 row만 AI Brief 입력에 들어갑니다. Polygon은 backup/comparison provider로 유지하지만, 무료 REST tier는 낮은 request/minute 제한에 걸릴 수 있으므로 반복 비교는 간격을 두거나 plan을 확인합니다.
  - `alpha-vantage-news` source provider는 `ALPHA_VANTAGE_API_KEY` secret으로 Alpha Vantage `NEWS_SENTIMENT` endpoint(`https://www.alphavantage.co/query`)를 ticker별 1회 조회합니다. v1은 US ticker만 지원하며 `AAPL.NAS`는 `AAPL`, `BRK.B.NYS`는 `BRK.B`로 요청하고, KR ticker는 요청하지 않은 채 `source_issues[]` WARN으로 남깁니다. 요청은 `function=NEWS_SENTIMENT`, `tickers`, `time_from=<now-72h UTC>`, `sort=LATEST`, `limit=10`으로 보내며 반환 row의 `feed[].title`/`feed[].url`/`feed[].time_published`는 기존 source row 계약으로 정규화됩니다.
  - `marketaux-news` source provider는 `MARKETAUX_API_TOKEN` secret으로 Marketaux Finance & Market News endpoint(`https://api.marketaux.com/v1/news/all`)를 ticker별 1회 조회합니다. v1은 US ticker만 지원하며 `AAPL.NAS`는 `AAPL`, `BRK.B.NYS`는 `BRK.B`로 요청하고, KR ticker는 요청하지 않은 채 `source_issues[]` WARN으로 남깁니다. 요청은 `symbols`, `countries=us`, `language=en`, `filter_entities=true`, `must_have_entities=true`, `published_after=<now-72h UTC>`, `limit=10`으로 보내며 반환 row의 `data[].title`/`data[].url`/`data[].published_at`은 기존 source row 계약으로 정규화됩니다.
  - `benzinga-news` source provider는 `BENZINGA_API_TOKEN` secret으로 Benzinga News endpoint(`https://api.benzinga.com/api/v2/news`)를 ticker별 1회 조회합니다. v1은 US ticker만 지원하며 `AAPL.NAS`는 `AAPL`, `BRK.B.NYS`는 `BRK.B`로 요청하고, KR ticker는 요청하지 않은 채 `source_issues[]` WARN으로 남깁니다. 요청은 `token`, `tickers`, `pageSize=10`, `displayOutput=headline`, `sort=created:desc`, `publishedSince=<now-72h UTC Unix>`로 보내며 반환 row의 `title`/`url`/`created` 또는 `updated`는 기존 source row 계약으로 정규화됩니다.
  - `naver-news` source provider는 `NAVER_CLIENT_ID`/`NAVER_CLIENT_SECRET` secrets로 Naver Search API 뉴스 endpoint(`https://openapi.naver.com/v1/search/news.json`)를 ticker별 1회 조회합니다. v1은 KR ticker만 지원하며 buy report 회사명을 검색어로 우선 사용하고, 없으면 6자리 ticker를 사용합니다. 요청은 `display=10`, `start=1`, `sort=date`로 보냅니다. US ticker는 요청하지 않은 채 `source_issues[]` WARN으로 남깁니다. 반환 row의 `title`(HTML 제거), `originallink` 또는 `link`, `pubDate`는 기존 source row 계약으로 정규화되며, freshness/future-time/duplicate/cap/URL safety/DNS 검증을 통과한 row만 AI Brief 입력에 들어갑니다.
  - RSS/Atom/RDF feed에서 source payload를 만들 때는 `just ai-brief-source-collect --feed-catalog <feeds.json> --output <sources.json>`를 사용합니다. feed catalog는 ticker별 로컬 파일 경로(`path`/`feed_path`) 또는 live HTTPS feed URL(`url`/`feed_url`) 중 정확히 하나를 담고, 도구는 fresh source만 ticker별 최대 3건까지 `sab.ai_brief_sources.v1` payload로 출력합니다.
    - catalog 예: `{"schema":"sab.ai_brief_source_feed_catalog.v1","feeds":[{"ticker":"AAPL.NAS","path":"aapl.rss"}]}`
    - live URL catalog 예: `{"schema":"sab.ai_brief_source_feed_catalog.v1","feeds":[{"ticker":"AAPL.NAS","url":"https://example.com/aapl.xml"}]}`
    - 로컬 feed 파일은 네트워크/DNS 없이 처리하며 item URL의 literal local/private IP와 localhost를 거부합니다. live feed URL은 HTTPS만 허용하고 userinfo, DNS 기반 local/private host, redirect, 1MB 초과 응답을 거부합니다. `--feed-timeout-seconds` 기본값은 10초이며, HTTP/timeout/invalid feed는 전체 실패가 아니라 ticker별 `issues[]` WARN으로 남습니다.
  - 로컬/live feed `sources[]` payload 품질은 `just ai-brief-source-eval --entry-report <entry.json> --source-report <sources.json>`로 점검합니다. 여러 캡처 payload를 비교하려면 `--compare-source-report <label=path>`를 2개 이상 지정합니다. `market=MIXED` entry report는 `--market KR|US`를 함께 지정합니다.
  - live provider 자체를 비교하려면 `just ai-brief-source-live-compare --entry-report <entry.json> --provider <label=provider>`를 사용합니다. provider는 `http-json`, `finnhub`, `polygon-news`, `alpha-vantage-news`, `marketaux-news`, `benzinga-news`, `naver-news`를 지원하며 2개 이상 지정해야 합니다. `market=MIXED` entry report는 `--market KR|US`를 함께 지정합니다. `http-json`에는 `--source-api-url <label=url>`을 지정하고, URL 없는 `http-json` provider가 정확히 하나면 `AI_BRIEF_SOURCE_API_URL`을 사용합니다. 각 provider 결과는 `sab.ai_brief_sources.v1` payload로 저장되고, provider 실패는 해당 payload의 top-level `ERROR` issue로 남아 비교 결과에서 FAIL로 표시됩니다. Captured payload와 최종 summary에는 provider별 `duration_ms`와 fastest leader가 포함됩니다.
  - 로컬 refactor 뒤 실제 외부 경계를 확인해야 하고 자격 증명/네트워크 사용을 의도적으로 허용한 경우 `just live-integration-smoke`를 사용합니다. 예: `just live-integration-smoke --entry-report <entry.json> --source-provider finnhub=finnhub --kis-token --kis-overseas-price-ticker AAPL.NAS --pretty`. 이 smoke는 선택한 RSS feed catalog, 단일 또는 복수 source provider, KIS token/price/daily candle endpoint만 호출합니다. `FAIL` check가 있으면 exit 1, `WARN`만 있으면 exit 0이며, 출력 JSON에는 source/candle count, status, sample key 같은 진단 정보만 남기고 secret 값은 포함하지 않습니다.
  - 생성된 `*.ai-brief.json` recommendation artifact 품질은 `just ai-brief-eval --entry-report <entry.json> --ai-brief-report <ai-brief.json>`로 점검합니다. 이 평가는 네트워크/secret 없이 entry 후보 정합성, summary count, rank, source-backed ratio, source 없는 추천의 confidence 안전성을 확인합니다.
  - 새 AI Brief artifact는 top-level `brief_state`/`brief_reason`을 포함합니다. `NO_SIGNAL/no_enter_candidates`면 Telegram은 “오늘은 볼 종목 없음. 쉬어도 됨”을 보내고, `FINAL_JUDGMENT/source_backed_final`이면 source-backed 후보 1-3개를 보여주며, `NEEDS_REVIEW_WEAK_NEWS`면 “뉴스 근거 약함, 기술 신호만 있음” 또는 모델/시스템 보류 문구와 issue 요약을 보냅니다.
  - 결과물은 Actions artifact(`buy`, `entry`, `ai-brief` JSON과 Slack/Telegram preview 텍스트)로 남기고, AI Brief 리포트는 Supabase Storage/`report_index`에도 업로드합니다.
  - 수동 실행에서 `send_notifications=true`를 선택하면 생성된 preview 텍스트를 Telegram/Slack으로 실제 발송합니다. 기본값은 `false`입니다.
  - 관련 secret이 없으면 발송 단계는 skip하며 workflow 자체는 계속 성공할 수 있습니다.
  - `provider=pykrx`는 `market=KR`, `universe=watchlist`, `entry_mode=AFTER_CLOSE` 조합에서만 허용합니다.
- AI Brief scheduled 실행(로컬 Docker primary + GitHub monitor/fallback)
  - US canary 기준 primary는 로컬 Mac의 `launchd` → `scripts/launchd/sab-ai-brief-wrapper.sh` → `docker compose -f docker-compose.yml -f docker-compose.scheduler.yml run --rm scheduler ...` 순서로 실행합니다.
  - scheduled 시간 정책의 단일 소스는 `sab/scheduler/schedule_policy.py`입니다. cutoff/fallback/monitor tick이나 role window를 바꿀 때는 이 파일을 먼저 수정하고, runner guard, GitHub Actions cron mapping, launchd plist timing은 정책 계약 테스트로 맞춥니다.
  - GitHub Actions `resolve_context` job은 dependency-free boundary로 유지합니다. 이 job은 checkout 후 stdlib-only 정책 모듈만 import해 off-window 후보를 빠르게 no-op 처리하고, `mise`/`uv sync`와 실제 runtime guard는 `scheduled_ai_brief` job에서만 수행합니다.
  - scheduled 기본값은 `provider=kis`, `universe=both`, `entry_mode=PRE_OPEN`, `model_provider=openai`, `send_notifications=true`입니다.
  - scheduled 실행은 시장별 `AI_BRIEF_SOURCE_PROVIDER_KR`/`AI_BRIEF_SOURCE_PROVIDER_US` repository variable이 있으면 해당 값을 source provider로 사용합니다. 시장별 값이 없으면 전역 `AI_BRIEF_SOURCE_PROVIDER`, 시장별 `AI_BRIEF_SOURCE_API_URL_KR`/`AI_BRIEF_SOURCE_API_URL_US`, 전역 `AI_BRIEF_SOURCE_API_URL`, `none` 순서로 fallback합니다.
  - 2026-05-23 기준 US scheduled default는 `AI_BRIEF_SOURCE_PROVIDER_US=finnhub`입니다. `POLYGON_API_KEY`와 `BENZINGA_API_TOKEN`도 backup/comparison 후보로 구성되어 있지만, Polygon은 현재 evidence set에서 freshness coverage 부족 및 HTTP 429가 확인됐고 Benzinga는 current candidate raw response가 빈 배열이어서 기본값으로 쓰지 않습니다. 장애 시 `AI_BRIEF_SOURCE_PROVIDER_US`를 unset하거나 다른 검증된 US provider로 바꾼 뒤 live comparison과 recommendation eval을 다시 실행합니다.
  - `http-json` source API는 HTTPS URL만 허용하며 local/private host와 redirect 응답은 거부됩니다. API는 `{"schema":"sab.ai_brief_source_request.v1","tickers":[...],"max_sources_per_ticker":3,"freshness_hours":72}`를 POST로 받고, `sources[]` row(`ticker`, `title`, HTTP(S) `url`, offset 포함 `published_at`)를 반환해야 합니다. source row URL도 DNS 검증을 포함해 local/private host를 가리킬 수 없고, source 시간은 72시간 이내이고 15분 넘는 미래 시간이면 무시됩니다. API token secret은 실행 URL이 설정된 전역 또는 시장별 `AI_BRIEF_SOURCE_API_URL` 변수와 일치할 때만 Bearer 토큰으로 전송합니다.
  - wrapper는 `sab ai-brief-scheduled --guard-only`로 role window를 먼저 확인합니다. Window 밖 candidate는 env file, Docker daemon, secret preflight, 실패 알림 없이 exit 0입니다.
  - Docker one-shot runner 수동 dry-run:
    - `SAB_SCHEDULER_ENV_FILE=.env.scheduler.local just ai-brief-scheduled-docker --market US --schedule-role local-primary --runner-role local-primary --scheduled-tick 0810 --dry-run`
  - 로컬 Python runner 수동 dry-run:
    - `just ai-brief-scheduled-local --market US --schedule-role local-primary --runner-role local-primary --scheduled-tick 0810 --dry-run`
  - `--dry-run`은 role window/env/preflight 확인용입니다. `runtime_state` lock/claim RPC를 실제로 호출하지 않으므로 Supabase lock 정상 동작 검증으로 쓰지 않습니다.
  - 원격 Supabase `runtime_state` lock RPC smoke:
    - 새 Supabase migration 적용 후, 다음 scheduled window 전 `just runtime-state-lock-smoke`를 실행합니다.
    - 실행에는 `SUPABASE_URL`과 server-side `SUPABASE_SECRET_KEY` 또는 `SUPABASE_SERVICE_ROLE_KEY`가 필요합니다. 명령은 service-role secret을 출력하지 않아야 합니다.
    - 성공 기준: synthetic `scheduled-ai-brief:test-lock:*` key로 첫 claim은 `acquired=true`, 중복 claim은 `acquired=false`, wrong-owner `check`/`renew`/`release`는 `false`, correct-owner `check`/`renew`/`release`는 `true`, release 후 re-claim은 다시 `acquired=true`입니다.
    - script는 실패 중간에도 `finally` cleanup release를 시도합니다. 실패 후 Supabase에 synthetic key가 남아 있으면 owner/TTL을 확인한 뒤 삭제합니다.
  - launchd plist 후보는 `scripts/launchd/com.mochafreddo.sab.ai-brief.us.*.plist`입니다. 서로 다른 role은 서로 다른 plist를 사용하고, 같은 role의 EDT/EST candidate tick만 한 plist에 함께 둡니다.
  - 설치 전 검증:
    - plist의 absolute repo/env/log path를 현재 머신에 맞게 확인합니다.
    - `scripts/launchd/verify-sab-ai-brief.sh`
    - 위 스크립트는 plist 구문, shared schedule policy 대비 launchd timing drift, wrapper shell syntax, compose 구조를 함께 확인합니다.
    - 정책 계약 테스트: `UV_CACHE_DIR=.uv-cache uv run python -m pytest tests/test_scheduled_ai_brief_schedule_policy.py tests/test_ai_brief_workflow.py tests/test_launchd_scheduler_wrapper.py -q`
    - `plutil -lint scripts/launchd/com.mochafreddo.sab.ai-brief.us.local-primary.plist`
    - `.env.scheduler.local`이 아직 없으면 compose 구조 검증에는 `SAB_SCHEDULER_ENV_FILE=.env.example docker compose -f docker-compose.yml -f docker-compose.scheduler.yml config`를 사용합니다.
  - enable:
    - `launchctl bootstrap gui/$(id -u) scripts/launchd/com.mochafreddo.sab.ai-brief.us.local-primary.plist`
    - retry/cutoff plist도 같은 방식으로 bootstrap합니다.
    - `launchctl print gui/$(id -u)/com.mochafreddo.sab.ai-brief.us.local-primary`
  - disable:
    - `launchctl bootout gui/$(id -u)/com.mochafreddo.sab.ai-brief.us.local-primary`
    - retry/cutoff plist도 같은 방식으로 bootout합니다.
  - 로그:
    - wrapper command log: `logs/launchd/US-local-primary.cmd.log`
    - stdout/stderr: plist의 `StandardOutPath`/`StandardErrorPath`
    - Docker job: `docker compose -f docker-compose.yml -f docker-compose.scheduler.yml logs scheduler`
  - 수동 재실행:
    - 같은 session date에 `success` marker가 있으면 runner는 조용히 skip합니다.
    - artifact marker만 있고 notification sent marker가 없으면 report를 재생성하지 않고 Telegram reconciliation만 시도합니다.
    - 강제 재처리는 Supabase `runtime_state` marker 삭제가 필요하므로 먼저 storage object와 Telegram 중복 발송 가능성을 확인합니다.
  - GitHub scheduled job은 US canary 동안 `early-monitor`, `github-fallback`, `cutoff-alert`만 수행합니다. `github-fallback`도 같은 `runtime_state` lock/artifact/notification marker를 사용합니다.
  - `github-fallback`의 명목 role window는 08:55 <= t < 09:25 ET입니다. GitHub Actions queue delay로 09:25 이후에 runner가 시작되는 경우에만 4분 bounded grace를 적용해 09:29 ET 전까지 `resolve_context`와 runner role guard를 통과시킵니다. 이 grace는 fallback job이 `runtime_state` lock/artifact/success guard까지 도달하게 하는 용도이며, `trading_session=true`와 `session_state=PRE_OPEN` guard는 시작/entry/upload/notification 직전에 계속 적용됩니다.
  - Pipeline runner가 거래일/세션 runtime guard에서 중단되면 `reports/YYYY-MM-DD(.n).ai-brief-skip.json`을 만들고 Supabase Storage/`report_index`에 `ai-brief-skip` 타입으로 업로드합니다. 이 artifact는 `skip_state=RUNTIME_GUARD_SKIPPED`, `skip_reason`, `session_state`, `expected_state`, `trading_session`, `local_time`, `run_url`을 남기며 정상 `ai-brief` 판단 상태와 분리됩니다. 같은 session date의 중복 skip artifact는 `runtime_state`의 `skip-artifact` marker와 `skip-artifact:claim` lock으로 막습니다.
  - rollback:
    1. launchd job을 `bootout`합니다.
    2. `docker ps`로 실행 중 scheduler container가 없는지 확인합니다.
    3. `.github/workflows/ai-brief.yml` schedule을 이전 primary schedule로 되돌립니다.
    4. 당일 `runtime_state`의 lock/claim marker는 owner/TTL을 확인하고, notification sent/success marker는 중복 발송 여부를 판단한 뒤 유지/삭제합니다.
    5. `runtime_state` lock RPC hotfix 문제가 의심되면 이전 장애 정의(`column reference "expires_at" is ambiguous`)로 되돌리지 말고 alias-qualified `create or replace function` hotfix를 다시 적용합니다.
    6. 재등록 전 `just runtime-state-lock-smoke`를 통과시켜 claim/duplicate/wrong-owner/correct-owner/release/re-claim 경로를 확인합니다.
- Audit 실행(GitHub Actions)
  - 감사 워크플로: `.github/workflows/audit.yml`
  - 트리거: `pull_request`, `workflow_dispatch`, 매주 월요일 11:00 UTC(`0 11 * * 1`)
  - Job:
    - `workflow_audit`: `rhysd/actionlint`로 워크플로 YAML 정합성 검사
    - `security_audit`: `aquasecurity/trivy-action`으로 `vuln,secret` 통합 검사
  - 차단 기준: `HIGH,CRITICAL` 발견 시 실패(`ignore-unfixed=false`)
  - 산출물: `trivy-gate-results-<run_id>` / `trivy-report-results-<run_id>` 아티팩트(성공/실패와 무관하게 업로드)
- 로컬 CLI 업로드(선택)
  - 기본은 로컬 파일 생성만 수행합니다.
  - `scan`/`sell`을 로컬에서 Supabase로 올리려면 `SAB_UPLOAD_REPORTS=true`를 설정합니다.
  - `entry`는 `SAB_UPLOAD_REPORTS=true` 또는 `sab entry --upload`로 Storage/`report_index` 업로드를 수행할 수 있습니다.
  - `ai-brief`는 `SAB_UPLOAD_REPORTS=true` 또는 `sab ai-brief --upload`로 Storage/`report_index` 업로드를 수행할 수 있습니다.

## GitHub Actions 실패 복구

Actions 실패는 먼저 실패한 workflow/job/step을 기준으로 분류합니다. 원인을
분류하기 전에는 반복 재실행하지 않습니다.

- 공통 triage:
  - Actions run summary에서 workflow 파일, event(`schedule`/`workflow_dispatch`/`pull_request`/`push`), 실패 job, 첫 실패 step을 기록합니다.
  - CLI로 볼 때는 `gh run view <run-id> --log-failed`를 사용합니다. 로그를 공유할 때는 secret, token, webhook URL, Supabase project URL을 포함하지 않습니다.
  - workflow YAML을 고쳤다면 `just workflow-audit`로 먼저 재현합니다.
  - Python 변경이 원인 후보면 `just quality`, web 변경이 원인 후보면 `just ci-web`로 로컬 재현을 우선합니다.
- Supabase 업로드/`report_index` fail-closed:
  - GitHub Actions의 `scan`/`sell`/`entry`/`ai-brief` 업로드 경로는 Storage 업로드 또는 `report_index` upsert 실패를 성공으로 취급하지 않습니다.
  - 로그에 `Supabase report upload failed`, `failed to upload report object`, `report_index`, `cleanup_failed`가 보이면 먼저 위 "원격 Supabase 복구 기준"의 Storage/`report_index` mismatch 쿼리와 `runtime_state` 기준을 확인합니다.
  - object는 생겼지만 `report_index`가 없거나, index만 남은 경우에는 mismatch 쿼리 결과를 장애 기록에 남기고 같은 workflow를 재실행합니다. key 생성기는 중복 suffix를 처리하므로 기존 object를 임의 삭제하지 않습니다.
- 알림 단계:
  - `scan`/`sell` schedule의 Telegram/Slack 전송 step은 `continue-on-error`입니다. 알림 실패만으로는 리포트 생성/업로드 실패로 보지 않습니다.
  - 알림을 수동 재전송하기 전에는 해당 run의 `uploaded_key`와 Storage/`report_index` row가 있는지 확인합니다.

### `scan.yml` (`Scan pipeline`)

- 주요 실패 지점:
  - `Resolve workflow inputs`: `provider`/`universe` 조합 오류입니다. `provider=pykrx`는 `universe=KR`만 허용하고 실제 scan은 watchlist 경로를 씁니다.
  - `Validate pykrx watchlist`: watchlist가 비어 있거나 경로가 틀린 상태입니다.
  - `Run scan`: KIS credential/provider 오류, KIS rate limit/server 오류, watchlist/screener 데이터 실패, 또는 Supabase 업로드 fail-closed가 원인입니다.
  - `Upload generated report artifact`: `reports/*.buy.json`이 없거나 경로 추출이 실패한 상태입니다.
- 복구:
  - `Buy report written to:`가 로그에 없으면 입력, provider, KIS secret, watchlist/screener 상태를 고친 뒤 같은 입력으로 `workflow_dispatch`를 재실행합니다.
  - `Buy report written to:`는 있으나 `Buy report uploaded to Supabase:`가 없고 run이 실패했으면 Supabase 복구 기준을 먼저 확인한 뒤 재실행합니다.
  - 성공 확인은 Actions artifact `scan-report-<run_id>`, 로그의 `Buy report uploaded to Supabase: <key>`, 웹 `Reports`의 buy 리포트 로드입니다.

### `sell.yml` (`Sell pipeline`)

- 주요 실패 지점:
  - `Load holdings from Supabase`: `SUPABASE_URL`/`SUPABASE_SECRET_KEY`, publishable key 사용, REST 권한, 또는 holdings row 계약 위반입니다.
  - `Run sell`: KIS/provider 오류, holdings normalization 오류, 시장 데이터 누락 fatal, 또는 Supabase 업로드 fail-closed가 원인입니다.
- 복구:
  - holdings 로드 실패는 workflow를 고치기 전에 SQL Editor와 웹 `Holdings`에서 active row, ticker 형식, `entry_currency`, `quantity`, `entry_price`를 확인합니다.
  - `Sell report written to:` 이후 업로드 실패가 나면 Storage/`report_index` mismatch를 먼저 확인하고 같은 provider로 재실행합니다.
  - 성공 확인은 Actions artifact `sell-report-<run_id>`, 로그의 `Sell report uploaded to Supabase: <key>`, 웹 `Reports`의 sell 리포트 로드입니다.

### `ai-brief.yml` scheduled (`resolve_context` + `scheduled_ai_brief`)

- `resolve_context`의 `should_run=false`는 off-window no-op입니다. 이 경우 `scheduled_ai_brief` job이 생성되지 않아도 정상입니다.
- `scheduled_ai_brief` 실패 분류:
  - lock 미획득, 기존 artifact marker, 기존 `success` marker는 중복 실행 방지입니다. `runtime_state` marker와 Storage object를 확인하고 강제 재처리하지 않습니다.
  - `guard_failed_before_upload` 또는 skip artifact 생성은 PRE_OPEN/session guard가 실행 직전 막은 것입니다. `ai-brief-skip` Storage object와 `report_index` row를 확인합니다.
  - `upload_failed` 또는 `skip_artifact_upload_failed`는 Supabase 복구 기준을 먼저 확인합니다. `success`/`notification:sent` marker는 중복 발송 판단 전 삭제하지 않습니다.
  - `artifact_uploaded_notification_deferred`는 report artifact가 이미 있고 알림 reconcile만 남은 상태입니다. artifact marker를 삭제하지 말고 같은 session date의 notification marker만 확인합니다.
- 복구:
  - scheduled role을 그대로 복구해야 하면 GitHub `workflow_dispatch`가 아니라 로컬 scheduled runner 경로를 사용합니다. 예: `SAB_SCHEDULER_ENV_FILE=.env.scheduler.local just ai-brief-scheduled-docker --market US --schedule-role github-fallback --runner-role github-fallback --scheduled-tick 0855`.
  - 단순 수동 AI Brief가 목적이면 `workflow_dispatch`를 사용하되, 이는 scheduled `runtime_state` marker 복구가 아니라 별도 manual artifact 생성으로 기록합니다.
  - 성공 확인은 같은 session date의 `artifact` 또는 `skip-artifact`, 정상 발송 경로의 `notification:sent`/`success` marker, Storage/`report_index` row, Telegram 본문입니다.

### `ai-brief.yml` manual (`ai_brief`)

- 주요 실패 지점:
  - `Resolve workflow inputs`: `provider=pykrx`는 `market=KR`, `universe=watchlist`, `entry_mode=AFTER_CLOSE` 조합만 허용합니다.
  - `Run scan`/`Run entry`/`Run AI brief`: 앞 단계 artifact가 없으면 뒤 단계는 복구 대상이 아니라 원인 step을 먼저 고칩니다.
  - source provider 실패는 provider별 secret/API quota/URL safety/DNS/freshness 문제를 `source_issues[]`와 step log에서 확인합니다.
- 복구:
  - 입력 조합 또는 provider secret을 고친 뒤 같은 `workflow_dispatch` 입력으로 재실행합니다.
  - `send_notifications=false`가 기본값이므로 알림 미발송은 실패가 아닙니다.
  - 생성된 `*.ai-brief.json`은 `just ai-brief-eval --entry-report <entry.json> --ai-brief-report <ai-brief.json>`로 품질을 확인합니다.

### `cleanup.yml` (`Report cleanup`)

- scheduled cleanup은 `dry_run=false`로 실행하므로 실패 후에는 삭제 경계를 먼저 확인합니다.
- 복구:
  - 수동 재실행은 항상 `workflow_dispatch` + `dry_run=true` + 같은 `retention_days`로 시작합니다.
  - 로그의 `[cleanup] listed_count`, `pattern_matched_count`, `expired_count`, `dangling_index_count`, `index_delete_target_count`를 장애 기록에 남깁니다.
  - 예상 대상과 일치할 때만 `dry_run=false`로 재실행합니다. retention을 낮춰 삭제를 강제하지 않습니다.
  - 부분 삭제나 REST 실패가 의심되면 위 Storage/`report_index` mismatch 쿼리로 정합성을 확인합니다.

### `ci.yml`, `audit.yml`, `mise-lock-sync.yml`

- `ci.yml`:
  - `Ruff + Mypy + Pytest` 실패는 `just quality`로 재현합니다.
  - `Next.js Web (Lint + Typecheck + Test + Build)` 실패는 `just ci-web`로 재현합니다.
  - `Validate toolchain versions` 또는 `mise.lock changed during CI setup` 실패는 `mise lock --platform linux-x64,macos-arm64 && mise install` 후 lockfile diff를 커밋합니다.
- `audit.yml`:
  - `workflow_audit` 실패는 `just workflow-audit`로 재현하고, GitHub Actions `run: |` heredoc 들여쓰기와 shellcheck 경고를 우선 확인합니다.
  - `security_audit` 실패는 `trivy-gate-results-<run_id>` artifact를 확인합니다. 의존성 업그레이드가 원칙이며, `.trivyignore` 예외는 만료일/사유를 적은 임시 예외만 허용합니다.
- `mise-lock-sync.yml`:
  - Renovate의 `mise.toml` PR에서만 동작합니다. `Commit and push` 실패가 나면 로컬에서 lockfile을 갱신해 같은 PR 브랜치에 커밋합니다.
  - `Re-trigger CI` 실패는 lockfile 생성 실패가 아닙니다. CI run 상태를 별도로 확인합니다.

## Audit 수동 점검

- Workflow YAML 점검:
  - `just workflow-audit`
  - 로컬 recipe는 CI `workflow_audit`와 맞춘 `rhysd/actionlint:1.7.12` Docker image를 사용합니다.
- 빠른 점검:
  - `trivy fs .`
- CI 동일 정책 점검:
  - `trivy fs --scanners vuln,secret --severity HIGH,CRITICAL --ignore-unfixed=false --format json --output trivy-gate-results.json .`
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
- 아래 4개 Required status checks를 복원합니다(실제 CI job 이름과 정확히 일치해야 함):
  - `Ruff + Mypy + Pytest`
  - `Next.js Web (Lint + Typecheck + Test + Build)`
  - `workflow_audit`
  - `security_audit`
- 모드 전환/동기화 절차와 2단계 상향 기준은 `docs/governance/main-branch-protection.md`를 따릅니다.

## 파일/경로

- 로컬 리포트(개발/디버그): `reports/YYYY-MM-DD.buy.json`, `...sell.json`, `...entry.json`, `...ai-brief.json`, `...ai-brief-skip.json`(중복 시 `-1`)
- Storage 오브젝트 키(공식 보관): `YYYY/MM/YYYY-MM-DD.buy.json`, `...sell.json`, `...entry.json`, `...ai-brief.json`, `...ai-brief-skip.json`(중복 시 `-1`, `-2`, ...)
- Storage 업로드 MIME: `contentType=application/json`으로 고정(`reports` 버킷 정책)
- 키 규칙 구현: `sab/report/storage_key.py`의 `build_report_storage_key`
- 캐시/상태: `data/`(KIS 토큰, 캔들, 스크리너 캐시)
- 보유 목록(공식 소스): Supabase Postgres `holdings` 테이블
- 선택 백업 파일: `holdings.yaml`(웹 UI import/export 용도, export는 inactive row까지 포함)

## 문제 해결

- 토큰 오류/401: `KIS_APP_KEY/SECRET/BASE_URL` 확인, `data/kis_token_`* 삭제로 강제 갱신(24시간 정책 유의)
- 레이트리밋 `EGW00201`: `KIS_MIN_INTERVAL_MS`(예: 500–1000) 증가 후 재시도. 스크리너 TTL도 호출 수 절감에 도움
- KR KIS 스크리너 서버 오류(예: `volume-rank` `EGW00316`): `--universe both`에서는 KR 스크리너를 건너뛰고 watchlist/US 평가를 계속합니다. `--universe screener`에서는 후보 소스가 없어질 수 있으므로 fail-closed로 실패합니다.
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

## 컴포넌트별 빠른 장애 참조

장애 시 "어디를 보고 / 어떻게 되살리고 / 무엇으로 복구를 확인하는지"의 진입점입니다. 상세 절차는 각 행이 가리키는 위 섹션을 따릅니다.

| 컴포넌트 | 로그 위치 | 헬스체크 | 재시작/재실행 | 복구 확인 | 담당 |
| --- | --- | --- | --- | --- | --- |
| 웹 UI (`sab-web`) | `docker compose logs -f web` | `curl .../login` → `200`, `docker compose ps` | `docker compose up -d --build web` | `/login` 재진입 + `Reports` 로드 | 로컬(단일 사용자) |
| scheduled AI Brief (로컬 primary) | `logs/launchd/US-local-primary.cmd.log`, plist `StandardOut/ErrorPath`, `docker compose -f docker-compose.yml -f docker-compose.scheduler.yml logs scheduler` | Telegram 발송 + Supabase `runtime_state` marker(`success`/`notification:sent`) | `launchctl bootout`/`bootstrap` 또는 `just ai-brief-scheduled-docker ... --dry-run` | Supabase Storage/`report_index` artifact + Telegram 본문 | macOS `launchd`(호스트) |
| GitHub Actions (`scan`/`sell`/`cleanup`, ai-brief monitor/fallback) | Actions run logs + run summary | Actions run 상태(성공/실패), `github-fallback` lock marker | 웹 `Run` 탭 또는 GitHub `workflow_dispatch` 재실행 | Supabase 업로드 + `report_index` upsert 성공 | GitHub Actions |
| Supabase (Postgres/Storage/`runtime_state`) | Supabase 대시보드 로그, `cron.job_run_details` | 위 "원격 Supabase 복구 기준"의 SQL Editor 점검 쿼리 + `just runtime-state-lock-smoke` | managed(재기동 대상 아님) | Storage/`report_index` mismatch 0행 + marker 쿼리 + `Reports`/`Holdings` 로드 | 원격 Supabase 프로젝트 |
| CLI (`scan`/`sell`/`entry`/`ai-brief`) | stdout(`LOG_LEVEL`로 상세도 조정) | 종료 코드 + `reports/*.json` 생성 여부 | `just scan`/`sell`/`entry` 또는 `uv run python -m sab ...` 재실행 | `reports/YYYY-MM-DD.*.json` 생성 + (업로드 시) Storage 반영 | 로컬 |

## 확장

- RS 벤치마크: `strategy.rs_benchmark_ticker_kr` / `strategy.rs_benchmark_ticker_us`로 시장별 benchmark ticker를 지정하면, scan이 adjusted benchmark 시계열을 직접 조회해 `rs_benchmark_return`을 동적으로 계산합니다.
- Entry 체크: buy report의 `entry_reference_close_raw_value`가 있으면 raw/live 가격 기준으로 자동 gap guard를 적용하고, reference close가 없거나 basis가 없는 레거시 candidate는 `REVIEW`로 처리합니다.
