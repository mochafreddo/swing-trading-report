# Operations

상태: Accepted (운영 가이드)

이 문서는 운영자가 매일/매주/장애 시 어디서부터 확인할지 정리한 시작점입니다. 상세 배포 절차는 [deployment.md](deployment.md), 증상별 대응은 [troubleshooting.md](troubleshooting.md)를 기준으로 합니다.

## 문서 상태

### 현재 제공

- 웹 콘솔, GitHub Actions, Supabase, scheduled AI Brief, report cleanup의 운영 체크리스트와 로그/헬스체크 시작점을 제공합니다.

### 실험

- 외부 APM/alerting 플랫폼 연동은 문서화된 현재 운영 범위가 아닙니다.

### 백로그

- 운영 대시보드 알림 threshold와 온콜/승인 체계 문서화.
- Supabase backup/restore 실제 runbook의 승인자/명령 표준화.

### 폐기 후보

- 개인 로컬 메모에만 남은 장애 대응 절차는 운영 기준으로 취급하지 않습니다.

## Operating Model

| Area | Current Source Of Truth | Operator Start Point |
| --- | --- | --- |
| Reports | Supabase Storage `reports` + `report_index` | Web `Reports`, workflow logs |
| Holdings | Supabase `holdings` | Web `Holdings`, SQL checks |
| Runtime locks/markers | Supabase `runtime_state` | scheduled AI Brief checks |
| Automation | GitHub Actions + local scheduler | GitHub run logs, Docker scheduler logs |
| Web console | local Docker `web` service | `/login` liveness, container logs |
| Secrets | `.env`, `.env.scheduler.local`, GitHub Secrets | Do not print values |

## Daily Checklist

| Check | Command/Place | Expected |
| --- | --- | --- |
| Web liveness | `curl -fsS -o /dev/null -w '%{http_code}\n' http://127.0.0.1:${WEB_HOST_PORT:-55300}/login` | `200` |
| Web container | `docker compose ps` | `sab-web` running |
| Latest workflows | `gh run list --limit 10` | scheduled jobs not repeatedly failing |
| Reports visible | Web `Reports` | latest `buy`/`sell`/`entry`/`ai-brief` as expected |
| Holdings visible | Web `Holdings` | active holdings match operator expectation |
| Local uncommitted secrets | `git status --short` | no secret files staged |

## Weekly Checklist

| Check | Command/Place | Expected |
| --- | --- | --- |
| CI health | GitHub Actions `CI` | main branch green or known failure tracked |
| Cleanup workflow | `Report cleanup` run logs | positive retention, no suspicious delete count |
| Supabase table health | SQL checks below | required tables exist and RLS enabled |
| Runtime state growth | SQL checks below | expired rows not accumulating unexpectedly |
| Docs drift | `UV_CACHE_DIR=.uv-cache uv run python -m pytest tests/test_docs_state_contract.py -q` | PASS |

## Logs And Health Checks

| Component | Check | Command |
| --- | --- | --- |
| Web prod container | process/logs | `docker compose ps` and `docker compose logs -f web` |
| Web dev container | process/logs | `docker compose --profile dev logs -f web-dev` |
| Web liveness | unauthenticated page | `curl -fsS -o /dev/null -w '%{http_code}\n' http://127.0.0.1:${WEB_HOST_PORT:-55300}/login` |
| Scheduler one-shot | container logs | `docker compose -f docker-compose.yml -f docker-compose.scheduler.yml run --rm scheduler uv run python -m sab ai-brief-scheduled --market US --schedule-role github-fallback --runner-role github-fallback --scheduled-tick manual --dry-run` |
| GitHub Actions | latest runs | `gh run list --limit 20` |
| Supabase reports | SQL/dashboard | `report_index`, Storage `reports` bucket |
| Supabase locks | SQL/dashboard | `runtime_state` rows prefixed `scheduled-ai-brief:` |

## Scheduled AI Brief

Scheduled AI Brief has two cooperating paths:

- Local primary: macOS `launchd` wrapper runs the Docker scheduler.
- GitHub fallback/monitor: `.github/workflows/ai-brief.yml` runs monitor, fallback, and cutoff alert roles.

The scheduled 기본값 for source providers is market-specific where possible.
Prefer a chain when multiple provider credentials are configured; keep the
single-provider variables as fallback/rollback controls.

| Market | Preferred Variable | Current Documented Default Candidate | Fallback Variable | Notes |
| --- | --- | --- | --- | --- |
| KR | `AI_BRIEF_SOURCE_PROVIDER_CHAIN_KR` | `naver-news` | `AI_BRIEF_SOURCE_PROVIDER_KR` | Requires Naver credentials. GitHub scheduled fallback currently dispatches US roles only; local scheduler still resolves KR chain. |
| US | `AI_BRIEF_SOURCE_PROVIDER_CHAIN_US` | `finnhub,benzinga-news,polygon-news` | `AI_BRIEF_SOURCE_PROVIDER_US=finnhub` | Finnhub remains first because live evidence was strongest; Benzinga/Polygon are fallback/diagnostic coverage attempts. |
| fallback | `AI_BRIEF_SOURCE_PROVIDER_CHAIN` | provider-specific | `AI_BRIEF_SOURCE_PROVIDER` | Used when market-specific value is absent. |

Operational checks:

```sql
select state_key, state_payload, expires_at, updated_at
from public.runtime_state
where state_key like 'scheduled-ai-brief:%'
order by updated_at desc
limit 30;

select report_type, count(*) as rows, max(report_date) as latest_report_date
from public.report_index
where report_type in ('ai-brief', 'ai-brief-skip')
group by report_type
order by report_type;
```

If a run creates `ai-brief-skip`, inspect `skip_state`, `skip_reason`, `session_date`, and `run_url` before rerunning. Do not delete runtime markers unless the operator intentionally wants deduped work to reprocess.

If a run fails with `scheduled ai-brief quality gate failed`, treat it as a generated-report contract failure rather than a delivery outage. Inspect the paired entry report and AI Brief report for `system_issues[]`, `source_issues[]`, `source_provider_summary`, `watch_candidates[]`, `recommendations[].rank`, `vetoed_candidates[]`, and summary count drift before rerunning. A report with preselected recommendable candidates but no recommendation and no veto is invalid even when source/system issues are present. The scheduled runner performs this quality gate before Storage upload, success marker creation, and notification reconciliation; the manual GitHub workflow uploads diagnostic GitHub artifacts first, then blocks Supabase upload and Telegram/Slack delivery on a quality `FAIL`.

Notification checks:

- AI Brief report Telegram messages are rich text and are sent with `parse_mode=HTML`. The GitHub workflow reads `ai-brief.telegram.txt`, splits it with `split_telegram_message_text()`, and sends each part separately.
- Scheduled AI Brief report notifications use the same HTML body and parse mode through `DefaultScheduledNotifier`; late alerts stay plain text.
- Skipped schedule Telegram messages use `ai-brief.skipped.telegram.txt` and remain plain text. Do not troubleshoot skipped notifications as HTML parse-mode failures.
- If a successful run uploaded an AI Brief artifact but no report notification arrived, check `notification:claim` and `notification:sent` runtime markers first, then the Telegram/Slack delivery step logs. Missing `TELEGRAM_BOT_TOKEN`, `TELEGRAM_CHAT_ID`, or `SLACK_WEBHOOK_URL` is a delivery configuration issue, not an AI Brief generation issue.

NEEDS_CONFIRMATION: 운영 환경의 최종 알림 채널, late-alert 수신자, 수동 override 승인자는 코드로 확인할 수 없습니다.

## GitHub Actions

| Workflow | Normal Signal | Failure Start Point |
| --- | --- | --- |
| `scan.yml` | report uploaded and indexed; scheduled empty-universe reports require issue review | KIS credentials, provider availability, upload step, report `system_issues` |
| `sell.yml` | Supabase holdings snapshot then sell report | holdings query, KIS/pykrx provider, upload step |
| `ai-brief.yml` | manual artifact passes recommendation quality gate before Supabase upload and opt-in notifications; scheduled artifact/skip marker after runtime_state guard and quality gate | context resolve, runtime_state lock, source/model provider, recommendation quality gate, gated Supabase upload step |
| `cleanup.yml` | cleanup summary counts | retention input, bucket guard, delete target counts |
| `ci.yml` | Python and web checks green | first failing job logs |
| `audit.yml` | workflow/security audit green | actionlint/shellcheck/security finding logs |

## Supabase Checks

Required tables:

```sql
select table_name
from information_schema.tables
where table_schema = 'public'
  and table_name in ('holdings', 'report_index', 'runtime_state')
order by table_name;
```

RLS state:

```sql
select tablename, rowsecurity, forcerowsecurity
from pg_tables
where schemaname = 'public'
  and tablename in ('holdings', 'report_index', 'runtime_state')
order by tablename;
```

Reports bucket:

```sql
select id, public, allowed_mime_types
from storage.buckets
where id = 'reports';
```

Index/Storage mismatch sample:

```sql
select ri.report_key
from public.report_index as ri
left join storage.objects as objects
  on objects.bucket_id = 'reports'
 and objects.name = ri.report_key
where objects.name is null
order by ri.report_date desc, ri.report_key desc
limit 20;
```

## Backup And Recovery

- Before manual Supabase recovery, dump the public schema when possible.
- Keep Storage report object keys and `report_index.report_key` aligned.
- Do not paste real project refs, DB credentials, URLs, or service keys into docs, tickets, or logs.

```bash
supabase db dump --linked --schema public --file backup-before-recovery.sql
```

NEEDS_CONFIRMATION: backup retention, restore authority, and production restore drill schedule are not derivable from the repository.

## Escalation

Use this order when the owner/channel is unknown:

1. Confirm whether the issue is local web, GitHub Actions, Supabase, market data provider, or source/model provider.
2. Preserve logs and report keys without secrets.
3. Stop duplicate-producing automation if runtime_state lock/marker integrity is uncertain.
4. Record `NEEDS_CONFIRMATION` for any human owner, approval, or vendor escalation path not known from code.

NEEDS_CONFIRMATION: named escalation owners and service vendor support channels.
