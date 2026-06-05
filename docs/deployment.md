# Deployment

상태: Accepted (배포 가이드)

이 문서는 현재 저장소가 지원하는 배포/운영 반영 경로를 정리합니다. 현재 확정된 운영 모델은 로컬 Docker 웹 콘솔, GitHub Actions 자동 실행, Supabase Postgres/Storage, 로컬 Docker scheduled AI Brief입니다.

## 문서 상태

### 현재 제공

- 로컬 Docker web 배포, Supabase migration, GitHub Actions workflow 운영, scheduled AI Brief 배포 절차를 제공합니다.
- 빌드/검증/롤백/배포 후 확인 명령을 제공합니다.

### 실험

- 외부 공개 웹 배포는 실험/지원 범위가 아닙니다.

### 백로그

- 원격 배포 플랫폼, 도메인, TLS, SSO, multi-user 운영 정책은 별도 설계가 필요합니다.
- 배포 체크리스트 자동화 스크립트.

### 폐기 후보

- 인증/host guard 없이 Next.js를 외부 공개하는 절차는 유지하지 않습니다.

## Deployment Surfaces

| Surface | Files | Deployment Unit | Notes |
| --- | --- | --- | --- |
| Python CLI | `sab/`, `pyproject.toml`, `uv.lock` | local/Actions `uv sync` + `python -m sab` | GitHub Actions and scheduler use this path. |
| Web console | `web/`, `docker-compose.yml`, `web/Dockerfile` | Docker image + `pnpm run start` | Host publish is loopback by default. |
| Scheduled AI Brief | `docker-compose.scheduler.yml`, `scripts/launchd/`, `sab/scheduler/` | one-shot Docker scheduler + launchd wrapper | Uses `.env.scheduler.local`. |
| Supabase DB | `supabase/migrations/` | migration set | RLS/RPC/table contracts live here. |
| GitHub automation | `.github/workflows/*.yml` | workflow definitions | Schedules and manual dispatch. |

## Build Commands

```bash
just quality
just ci-web
```

Local direct equivalents:

```bash
UV_CACHE_DIR=.uv-cache uv run ruff check .
UV_CACHE_DIR=.uv-cache uv run ruff format --check .
UV_CACHE_DIR=.uv-cache uv run mypy --config-file pyproject.toml
UV_CACHE_DIR=.uv-cache uv run python -m pytest -q
pnpm --dir web run lint
pnpm --dir web run format:check
pnpm --dir web run typecheck
pnpm --dir web run test:coverage
pnpm --dir web run build
```

`just ci-web` injects secret-free placeholder env for web build. Direct `pnpm --dir web run build` needs valid placeholder or local env values.

CI parity note: `.github/workflows/ci.yml` runs Python tests with coverage gate:
`UV_CACHE_DIR=.uv-cache uv run python -m pytest -q --cov=sab --cov-report=term --cov-fail-under=70`.

## Pre-Deployment Checklist

| Check | Command | Required |
| --- | --- | ---: |
| Tool versions synced | `mise install` | yes |
| Python dependencies synced | `UV_CACHE_DIR=.uv-cache uv sync --all-extras --all-groups` | yes for local validation |
| Python quality | `just quality` | yes for Python changes |
| Web quality | `just ci-web` | yes for web changes |
| Docs state/link contract | `UV_CACHE_DIR=.uv-cache uv run python -m pytest tests/test_docs_state_contract.py -q` | yes for docs changes |
| Git status reviewed | `git status --short` | yes |
| Secret scan by review | inspect changed docs/config only | yes |
| Supabase project target confirmed | operator local check | NEEDS_CONFIRMATION |

NEEDS_CONFIRMATION: 원격 Supabase 프로젝트 ref, 운영 승인자, 배포 window, rollback 승인 채널은 코드로 확인할 수 없습니다.

## Web Deployment: Local Docker

```bash
docker compose up -d --build web
```

Check:

```bash
docker compose ps
curl -fsS -o /dev/null -w '%{http_code}\n' http://127.0.0.1:${WEB_HOST_PORT:-55300}/login
```

Expected liveness result is `200`. `/login` proves the Next.js server is responding; it does not prove authenticated Supabase-backed pages are healthy.

Development profile:

```bash
docker compose --profile dev up -d --build web-dev
```

Stop:

```bash
docker compose stop web
docker compose --profile dev stop web-dev
```

Force recreate if build/start state is corrupted:

```bash
docker compose stop web
docker compose rm -f web
docker compose up -d --build web
```

## Supabase Deployment

Migration files are in `supabase/migrations/`. Apply migrations only after confirming the target project locally.

```bash
supabase migration list
supabase db push
```

NEEDS_CONFIRMATION: 이 저장소에는 Supabase CLI project link target과 운영 project ref를 문서화하지 않습니다. 운영자는 로컬 Supabase CLI 상태 또는 Supabase dashboard에서 대상 프로젝트를 직접 확인해야 합니다.

Post-migration checks:

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
```

## GitHub Actions Deployment

Workflow files are deployed by committing to the repository default branch.

| Workflow | Trigger | Purpose |
| --- | --- | --- |
| `.github/workflows/ci.yml` | push/PR/manual | Ruff, Mypy, Pytest, web lint/typecheck/test/build |
| `.github/workflows/scan.yml` | weekday schedule + manual | buy report scan/upload/notify |
| `.github/workflows/sell.yml` | weekday schedule + manual | holdings snapshot + sell report/upload/notify |
| `.github/workflows/ai-brief.yml` | weekday schedule + manual | manual AI Brief, local-primary monitor, GitHub fallback, cutoff alert |
| `.github/workflows/cleanup.yml` | daily schedule + manual | Storage/report_index retention cleanup |
| `.github/workflows/audit.yml` | weekly + manual | workflow/security audit |
| `.github/workflows/mise-lock-sync.yml` | manual | tool lock sync |
| `.github/workflows/release-please.yml` | push/manual | release automation |

Manual dispatch examples:

```bash
gh workflow run scan.yml -f provider=kis -f universe=both
gh workflow run sell.yml -f provider=kis
gh workflow run cleanup.yml -f dry_run=true -f retention_days=30
```

Do not print GitHub token values in logs or docs.

## Scheduled AI Brief Deployment

The local primary path is a macOS `launchd` host wrapper that runs a one-shot Docker scheduler service.

```bash
docker compose -f docker-compose.yml -f docker-compose.scheduler.yml run --rm scheduler uv run python -m sab ai-brief-scheduled --market US --schedule-role github-fallback --runner-role github-fallback --scheduled-tick manual --dry-run
```

The scheduler reads `${SAB_SCHEDULER_ENV_FILE:-.env.scheduler.local}`. Keep that file uncommitted.

NEEDS_CONFIRMATION: 설치된 launchd plist label, load/unload 명령, 운영 사용자의 LaunchAgents 경로는 코드만으로 확정하지 않습니다. `scripts/launchd/`와 로컬 환경을 함께 확인해야 합니다.

## Rollback

| Surface | Rollback Action | Notes |
| --- | --- | --- |
| Docs only | revert docs commit | No runtime migration. |
| Web Docker image | checkout previous commit and `docker compose up -d --build web` | Verify `/login` and authenticated pages. |
| Python CLI | checkout previous commit and resync with `uv sync` | Existing generated reports remain. |
| GitHub Actions | revert workflow commit | Manual workflow runs already started cannot be unsent. |
| Supabase migration | restore from backup or forward-fix migration | NEEDS_CONFIRMATION: destructive rollback policy. |
| Scheduled AI Brief | unload/disable launchd job or stop scheduler container | Confirm runtime_state markers before rerun. |

## Post-Deployment Verification

```bash
docker compose ps
curl -fsS -o /dev/null -w '%{http_code}\n' http://127.0.0.1:${WEB_HOST_PORT:-55300}/login
gh run list --limit 10
```

Authenticated browser checks:

- Login succeeds.
- `Reports` list loads from `report_index`.
- Report detail loads a Storage JSON object.
- `Holdings` list loads active and inactive rows as expected.
- `Run` tab is disabled when `RUN_DISPATCH_ENABLED=0`, or dispatches when required GitHub env is present.

## Failed Deployment Checks

| Symptom | First Check |
| --- | --- |
| Web container exits | `docker compose logs web` |
| `/login` not `200` | host port, `WEB_HOST_PORT`, container state |
| Build fails env validation | `web/scripts/validate-env.mjs` required vars |
| Reports page errors | Supabase URL/key, bucket, `report_index` rows |
| Workflow dispatch fails | `RUN_DISPATCH_ENABLED`, `GITHUB_OWNER`, `GITHUB_REPO`, `GITHUB_PAT` |
| Scheduled run duplicates or skips | `runtime_state` keys and scheduler role/window policy |
