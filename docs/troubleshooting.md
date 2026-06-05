# Troubleshooting

상태: Accepted (장애 대응 가이드)

증상별로 어디서부터 확인할지 정리합니다. 실제 운영 시에는 비밀값을 출력하지 말고, 로그/명령 결과를 공유할 때 토큰, 내부 URL, 개인 정보, 고객 정보를 제거하세요.

## 문서 상태

### 현재 제공

- 로컬 웹, Supabase, KIS/PyKRX, GitHub Actions, scheduled AI Brief, cleanup 문제의 첫 확인 명령과 복구 방향을 제공합니다.

### 실험

- 자동 진단 스크립트는 아직 없습니다.

### 백로그

- 증상별 로그 패턴을 구조화해 `just doctor` 같은 진단 명령으로 묶을 수 있습니다.

### 폐기 후보

- 보호 API를 unauthenticated curl로 직접 호출해 헬스체크로 쓰는 방식은 유지하지 않습니다.

## Symptom: Web container exits during startup

### Possible Causes

- Required web env is missing or invalid.
- `SAB_SESSION_SECRET` is shorter than 32 characters.
- Supabase server key is missing or a publishable key was used on a server path.
- Port binding conflicts with another process.

### Checks

```bash
docker compose ps
docker compose logs web
```

### Resolution

```bash
cp .env.example .env
# Fill only local placeholder values and secrets in .env.
docker compose up -d --build web
```

### Escalation

NEEDS_CONFIRMATION: if valid env and loopback port are confirmed but startup still fails, decide whether to inspect local Docker Desktop, Next.js build output, or Supabase availability first.

## Symptom: `/login` liveness is not `200`

### Possible Causes

- `web` container is not running.
- `WEB_HOST_PORT` is different from the expected default.
- The container started but Next.js did not bind correctly.

### Checks

```bash
docker compose ps
printf '%s\n' "${WEB_HOST_PORT:-55300}"
curl -fsS -o /dev/null -w '%{http_code}\n' http://127.0.0.1:${WEB_HOST_PORT:-55300}/login
docker compose logs web
```

### Resolution

```bash
docker compose up -d --build web
```

If the container state is stale:

```bash
docker compose stop web
docker compose rm -f web
docker compose up -d --build web
```

### Escalation

NEEDS_CONFIRMATION: local host firewall/proxy diagnosis is environment-specific.

## Symptom: Login succeeds but Reports or Holdings fail to load

### Possible Causes

- Supabase URL/key is missing or invalid.
- Storage `reports` bucket is missing or public/private policy differs from expectation.
- `report_index` or `holdings` table migration was not applied.
- Runtime key is publishable instead of server-side secret.

### Checks

```bash
docker compose logs web
```

```sql
select table_name
from information_schema.tables
where table_schema = 'public'
  and table_name in ('holdings', 'report_index', 'runtime_state')
order by table_name;

select id, public, allowed_mime_types
from storage.buckets
where id = 'reports';
```

### Resolution

- Confirm Supabase env with placeholders only; do not print actual values.
- Apply pending migrations if the target project is confirmed.
- Regenerate/upload a report if `report_index` is empty by design.

### Escalation

NEEDS_CONFIRMATION: target Supabase project, migration approval, and data recovery owner.

## Symptom: `sab scan` or `sab sell` fails on KIS authentication or rate limits

### Possible Causes

- `KIS_APP_KEY` or `KIS_APP_SECRET` is missing/invalid.
- `KIS_BASE_URL` conflicts between `.env` and `config.yaml`.
- KIS rate limit needs a larger `KIS_MIN_INTERVAL_MS`.
- Market is closed or provider response is incomplete.

### Checks

```bash
UV_CACHE_DIR=.uv-cache uv run python -m sab scan --provider kis --limit 5
UV_CACHE_DIR=.uv-cache uv run python -m sab sell --provider kis
```

### Resolution

- Keep KIS secrets only in `.env` or GitHub Secrets.
- Remove duplicate logical config between `.env` and `config.yaml`.
- Increase `kis.min_interval_ms` in `config.yaml` or use `KIS_MIN_INTERVAL_MS` for a one-off environment override, not both.

### Escalation

NEEDS_CONFIRMATION: KIS account/API status and vendor support path are external to this repository.

## Symptom: `pykrx` scan rejects US or mixed universe

### Possible Causes

- `pykrx` provider supports KR-only scan dispatch in the web route policy.
- `/api/run` validates provider/universe before GitHub dispatch.

### Checks

```bash
UV_CACHE_DIR=.uv-cache uv run python -m sab scan --provider pykrx --markets KR
```

### Resolution

Use `provider=kis` for `US` or `both` universe, or restrict `pykrx` to `KR`.

### Escalation

NEEDS_CONFIRMATION: adding US support to a non-KIS provider is a product/architecture decision.

## Symptom: `/api/run` fails or returns disabled/validation error

### Possible Causes

- `RUN_DISPATCH_ENABLED=0`.
- `GITHUB_OWNER`, `GITHUB_REPO`, or `GITHUB_PAT` is missing when dispatch is enabled.
- `pykrx` was requested with unsupported universe.
- Same-origin/local request guard rejected the request.

### Checks

```bash
docker compose logs web
```

Verify configuration shape without printing secret values.

### Resolution

- Set `RUN_DISPATCH_ENABLED=1` only when server-side GitHub env is configured.
- Use payloads from [api.md](api.md).
- Keep `GITHUB_PAT` server-only.

### Escalation

NEEDS_CONFIRMATION: GitHub token scope and repository dispatch policy must be confirmed by the maintainer.

## Symptom: GitHub workflow uploads report but report is missing from web list

### Possible Causes

- Storage upload succeeded but `report_index` upsert failed.
- Report key format did not match current pattern.
- Web cache is stale.

### Checks

```bash
gh run list --limit 10
```

```sql
select report_type, report_key, report_date, created_at
from public.report_index
order by report_date desc, report_key desc
limit 20;
```

### Resolution

- Inspect the upload/upsert step in the workflow log.
- Use the web `refresh` path or wait for cache TTL.
- Backfill `report_index` only with an audited script or migration.

### Escalation

NEEDS_CONFIRMATION: report_index backfill ownership and accepted recovery path.

## Symptom: Scheduled AI Brief is skipped, duplicated, or notification is missing

### Possible Causes

- Role/window guard rejected the run.
- `runtime_state` lock or marker already exists.
- Local primary and GitHub fallback raced, but dedupe prevented duplicate output.
- Source/model provider env is missing.
- Source provider env is unsupported, or `http-json` source API URL is missing,
  non-HTTPS, includes userinfo, targets a local/private literal host, has an
  invalid port, or contains whitespace/control chars. Scheduler returns
  `source_config_invalid` before scan/entry.
- Notification token/webhook is missing.

### Checks

```sql
select state_key, state_payload, expires_at, updated_at
from public.runtime_state
where state_key like 'scheduled-ai-brief:%'
order by updated_at desc
limit 30;

select report_type, report_key, summary, created_at
from public.report_index
where report_type in ('ai-brief', 'ai-brief-skip')
order by created_at desc
limit 20;
```

```bash
gh run list --workflow ai-brief.yml --limit 10
docker compose -f docker-compose.yml -f docker-compose.scheduler.yml run --rm scheduler uv run python -m sab ai-brief-scheduled --market US --schedule-role github-fallback --runner-role github-fallback --scheduled-tick manual --guard-only
```

### Resolution

- Treat `ai-brief-skip` as an artifact, not a silent failure.
- Do not delete `success`, `artifact`, `skip-artifact`, or `notification:sent` markers unless intentionally rerunning.
- Confirm `OPENAI_API_KEY` and market source provider env exist in the scheduler/GitHub environment.
- For `source_config_invalid`, inspect scheduler logs for
  `scheduled_ai_brief_source_config_invalid`; it includes provider/API URL
  origin metadata but does not log the source API URL value.

### Escalation

NEEDS_CONFIRMATION: notification owner, late-alert policy, and rerun approval.

## Symptom: Cleanup workflow wants to delete too much

### Possible Causes

- `retention_days` input is too small.
- Bucket is not `reports` or key pattern assumptions differ.
- Old manual objects exist outside current report key convention.

### Checks

```bash
gh workflow run cleanup.yml -f dry_run=true -f retention_days=30
```

Review cleanup output counts:

- `listed_count`
- `pattern_matched_count`
- `expired_count`
- `deleted_count`
- `index_delete_target_count`
- `dangling_index_count`

### Resolution

Run cleanup in dry-run first. Do not run destructive cleanup until counts match the intended retention window.

### Escalation

NEEDS_CONFIRMATION: retention exception policy and manual object ownership.

## Symptom: Docs state contract fails

### Possible Causes

- New Markdown file lacks `상태:` in the first six lines.
- Operational doc is missing document state sections.
- `docs/README.md` links a missing file.
- A backlog/archive document was moved without updating tests.

### Checks

```bash
UV_CACHE_DIR=.uv-cache uv run python -m pytest tests/test_docs_state_contract.py -q
```

### Resolution

- Add `상태: Accepted|Backlog|Archive|Superseded` metadata.
- Add `## 문서 상태` with `현재 제공`, `실험`, `백로그`, `폐기 후보` sections for operational docs.
- Update `docs/README.md` and `tests/test_docs_state_contract.py` together when the document taxonomy changes.

### Escalation

No escalation needed for normal docs taxonomy fixes.
