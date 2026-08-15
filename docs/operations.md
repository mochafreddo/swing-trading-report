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
| Runtime locks/markers | Supabase `runtime_state` | scheduled AI Brief and scheduled Sell AI Brief checks |
| Decision Board shadow | local RunJournal + local canonical report | Web Decision Board lane, journal status CLI |
| Automation | GitHub Actions + local scheduler + Toss launchd runner | GitHub run logs, Docker scheduler logs, Toss launchd logs |
| Web console | local Docker `web` service | `/login` liveness, container logs |
| Secrets | `.env`, `.env.scheduler.local`, GitHub Secrets | Do not print values |

## Daily Checklist

| Check | Command/Place | Expected |
| --- | --- | --- |
| Web liveness | `curl -fsS -o /dev/null -w '%{http_code}\n' http://127.0.0.1:${WEB_HOST_PORT:-55300}/login` | `200` |
| Web page auth gate | `curl -fsSI -o /dev/null -w '%{http_code} %{redirect_url}\n' http://127.0.0.1:${WEB_HOST_PORT:-55300}/reports` | `307` to `/login?next=%2Freports` |
| Web container | `docker compose ps` | `sab-web` running |
| Latest workflows | `gh run list --limit 10` | scheduled jobs not repeatedly failing |
| Reports visible | Web `Reports` | latest `buy`/`sell`/`entry`/`ai-brief` as expected |
| Holdings visible | Web `Holdings` | active holdings match operator expectation |
| Toss daily auto-sync log | `tail -n 20 logs/launchd/toss-daily-auto-sync.out.log` | when enabled, latest run ends with `status=applied` or `status=unchanged` |
| Local env files | `git diff --cached --name-only -- .env '.env.*'` and `git ls-files --others --ignored --exclude-standard -- .env '.env.*'` | first command prints nothing; second may list local ignored env files that must stay untracked |

When checking local env files or logs for accidental secrets, use path/line-only
or redacted scanner output. Do not paste raw `.env`, GitHub token, Supabase key,
Slack webhook, Telegram token, KIS secret, Toss secret, or OpenAI key values into
docs, tickets, chat, or CI logs. If scanner output includes a value, replace the
value with `[REDACTED]` before sharing it.

## Weekly Checklist

| Check | Command/Place | Expected |
| --- | --- | --- |
| CI health | GitHub Actions `CI` | main branch green or known failure tracked |
| Cleanup workflow | `Report cleanup` run logs | positive retention, no suspicious delete count |
| Supabase table health | SQL checks below | required tables exist and RLS enabled |
| Runtime state growth | SQL checks below | expired rows not accumulating unexpectedly |
| Docs drift | `UV_CACHE_DIR=.uv-cache uv run python -m pytest tests/test_docs_state_contract.py -q` | PASS |
| Decision Board gate | local frozen manifest + session ledger | No retroactive threshold/version changes |

## Decision Board shadow operations

Decision Board는 기본 상태에서 production adapter와 schedule이 없으므로
`CONFIG_UNAVAILABLE`가 정상 fail-closed 결과입니다. 이를 운영 성공이나 20-session 표본으로
세지 않습니다. 승인된 adapter를 연결해 실제 평가를 시작한 뒤에는 ENTRY/HOLDING planned
slot을 모두 RunJournal에 결속하고 missed/stale를 삭제하지 않습니다.

운영자는 매 session 다음을 확인합니다.

- lane/run ID/expected UTC identity가 manifest와 일치하는가
- terminal 또는 missed/stale 상태가 하나만 존재하는가
- local report의 schema/hash/key identity가 유효한가
- 기존 후보/action 차이에 reason과 input/source diff가 있는가
- privacy, order, notification, existing-pipeline 영향이 0인가

최소 20 US 거래 session 뒤의 산식과 수동 졸업 검토는
[Decision Board shadow evaluation](decision-board-shadow-evaluation.md)을 기준으로 합니다.

## Logs And Health Checks

| Component | Check | Command |
| --- | --- | --- |
| Web prod container | process/logs | `docker compose ps` and `docker compose logs -f web` |
| Web dev container | process/logs | `docker compose --profile dev logs -f web-dev` |
| Web liveness | unauthenticated page | `curl -fsS -o /dev/null -w '%{http_code}\n' http://127.0.0.1:${WEB_HOST_PORT:-55300}/login` |
| Web page auth gate | unauthenticated protected page | `curl -fsSI -o /dev/null -w '%{http_code} %{redirect_url}\n' http://127.0.0.1:${WEB_HOST_PORT:-55300}/reports` |
| Scheduler one-shot | container logs | `docker compose -f docker-compose.yml -f docker-compose.scheduler.yml run --rm scheduler uv run python -m sab ai-brief-scheduled --market US --schedule-role github-fallback --runner-role github-fallback --scheduled-tick manual --dry-run` |
| Scheduled Sell AI Brief generation dry smoke | CLI parse / no side effects | `uv run python -m sab sell-ai-brief-generate-scheduled --scope MIXED --session-date "$(TZ=Asia/Seoul date +%F)" --runner-role local-primary --scheduled-tick manual --dry-run` |
| Scheduled Sell AI Brief runtime_state readiness | Toss freshness + sell markers | `UV_CACHE_DIR=.uv-cache uv run python scripts/verify_scheduled_sell_runtime_state.py --session-date "$(TZ=Asia/Seoul date +%F)"` |
| Scheduled Sell AI Brief generation live run | generic wrapper / runtime_state | `SAB_SELL_SCHEDULE_MODE=generation scripts/launchd/sab-scheduled-wrapper.sh --pipeline sell --scope MIXED` |
| Scheduled Sell AI Brief prebuilt delivery | generic wrapper / runtime_state | `SAB_SELL_SCHEDULE_MODE=delivery SELL_AI_BRIEF_REPORT_PATH=reports/2026-07-06.sell-ai-brief.json scripts/launchd/sab-scheduled-wrapper.sh --pipeline sell --scope MIXED` |
| Toss daily auto-sync | launchd logs | `tail -n 20 logs/launchd/toss-daily-auto-sync.out.log` and `tail -n 20 logs/launchd/toss-daily-auto-sync.err.log` |
| GitHub Actions | latest runs | `gh run list --limit 20` |
| Supabase reports | SQL/dashboard | `report_index`, Storage `reports` bucket |
| Supabase locks | SQL/dashboard | `runtime_state` rows prefixed `scheduled-ai-brief:` or `scheduled-sell:` |

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

Optional article reading is controlled by `AI_BRIEF_ARTICLE_READER`. Keep the
default `none` for metadata-only source-backed operation. Set `lightpanda` only
when the runner image/host has `lightpanda` on `PATH` and the operator wants
public source URL body checks. The reader does not bypass paywalls, CAPTCHA,
login, robots/bot blocks, or access controls; blocked/failed reads are preserved
as `source_issues[]` and may downgrade the brief to `NEEDS_REVIEW_WEAK_NEWS`.

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

If a run fails with `scheduled ai-brief quality gate failed`, treat it as a generated-report contract failure rather than a delivery outage. Inspect the paired entry report and AI Brief report for `system_issues[]`, `source_issues[]`, `source_provider_summary`, `watch_candidates[]`, `recommendations[].rank`, `vetoed_candidates[]`, article reader summary counts, and summary count drift before rerunning. A report with preselected model candidates but no recommendation and no veto is invalid even when source/system issues are present. The scheduled runner performs this quality gate before Storage upload, success marker creation, and notification reconciliation; the manual GitHub workflow uploads diagnostic GitHub artifacts first, then blocks Supabase upload and Telegram/Slack delivery on a quality `FAIL`.

`model_ineligible_veto_dropped` and `model_watch_veto_dropped` mean the model tried to place a ticker outside the eligible veto universe into `vetoed_candidates[]`; the provider dropped that row and kept it as a WARN source issue. These warnings do not by themselves fail scheduled publish, but if the model leaves no valid recommendation and no valid veto for preselected candidates, the recommendation quality gate still fails with `recommendation_report_empty`.

`model_source_ref_invalid`, `model_source_ref_missing`, `model_unbacked_recommendation_dropped`, `model_watch_source_ref_invalid`은 모델이 canonical source catalog의 ref를 제대로 선택하지 못했다는 뜻입니다. 이 진단이 `WARN`이고 최종 추천이 source-backed이면 scheduled run은 partial publish로 정상 업로드될 수 있습니다. 같은 진단 뒤 추천이 모두 제거되거나 source-backed ratio가 부족하면 기존처럼 quality `FAIL`로 처리됩니다.

과거 AI 검토를 피드백할 때는 AI Brief artifact의 `model_trace.request_hash`, `model_trace.source_catalog_hash`, `model_trace.request_status`, `model_trace.attempt_ids`, `model_trace.candidate_summaries[]`, `model_attempts[]`를 먼저 대조합니다. 구조화 로그의 `ai_brief_model_attempt_started`, `ai_brief_model_attempt_failed`, `ai_brief_model_attempt_completed`, `ai_brief_model_fallback_selected`, fallback skip 이벤트도 같은 prompt/source catalog hash를 남기므로, raw prompt나 source payload를 로그에 남기지 않고 어떤 모델 입력과 시도가 검토됐는지 추적할 수 있습니다.

Notification checks:

- AI Brief report Telegram messages are rich text and are sent with `parse_mode=HTML`. The GitHub workflow reads `ai-brief.telegram.txt`, splits it with `split_telegram_message_text()`, and sends each part separately.
- Scheduled AI Brief report notifications use the same HTML body and parse mode through `DefaultScheduledNotifier`; late alerts stay plain text.
- Skipped schedule Telegram messages use `ai-brief.skipped.telegram.txt` and remain plain text. Do not troubleshoot skipped notifications as HTML parse-mode failures.
- If a successful run uploaded an AI Brief artifact but no report notification arrived, check `notification:claim` and `notification:sent` runtime markers first, then the Telegram/Slack delivery step logs. Missing `TELEGRAM_BOT_TOKEN`, `TELEGRAM_CHAT_ID`, or `SLACK_WEBHOOK_URL` is a delivery configuration issue, not an AI Brief generation issue.
- The launchd host wrapper sends `scheduler_container_failed` only when the Docker scheduler command exits without a recognized structured scheduler status. If the scheduler prints a JSON status such as `pipeline_failed`, treat the app-level late-alert and local scheduler logs as the source of truth rather than diagnosing Docker first. Stdout capture setup or tee failures are tagged `scheduler_stdout_capture_failed`, which keeps wrapper-level diagnostics distinct from scheduler execution status.

Local log retention:

- Attempt-scoped scheduler logs are written under `logs/scheduled/ai-brief/YYYY-MM-DD/`.
- AI Brief model latency probe planning is available with `UV_CACHE_DIR=.uv-cache uv run python -m sab ai-brief-latency-probe --primary-model <model> --fallback-model <model> --repetitions 1`; it prints the planned live model call count before any operator-run measurement.
- Model latency measurement rows, when written by measurement tooling, use `logs/measurements/ai-brief-model-latency/YYYY-MM-DD.jsonl`.
- Both directories are local-only and gitignored. Keep the latest 30 calendar days during normal operation. Before deleting older files, dry-run the target list with `find logs/scheduled logs/measurements -type f -mtime +30 -print`; delete only after confirming there is no active incident or audit need.

NEEDS_CONFIRMATION: 운영 환경의 최종 알림 채널, late-alert 수신자, 수동 override 승인자는 코드로 확인할 수 없습니다.

## Scheduled Sell AI Brief Generation And Delivery

Scheduled Sell AI Brief has two explicit modes:

- Generation: `SAB_SELL_SCHEDULE_MODE=generation` checks Toss freshness, generates a fresh sell report and Sell AI Brief, evaluates quality, uploads artifacts, and sends Telegram through the delivery runner.
- Prebuilt delivery: `SAB_SELL_SCHEDULE_MODE=delivery` plus `SELL_AI_BRIEF_REPORT_PATH=...` validates and delivers an already-built `*.sell-ai-brief.json` artifact. It does not generate a sell report and it does not run `sell-ai-brief` generation.

Execution paths:

- Local generation CLI: `uv run python -m sab sell-ai-brief-generate-scheduled --scope MIXED --session-date YYYY-MM-DD --runner-role local-primary --scheduled-tick 0725`
- Runtime_state readiness check: `UV_CACHE_DIR=.uv-cache uv run python scripts/verify_scheduled_sell_runtime_state.py --session-date YYYY-MM-DD`
- launchd generic wrapper generation route: `SAB_SELL_SCHEDULE_MODE=generation scripts/launchd/sab-scheduled-wrapper.sh --pipeline sell --scope MIXED` (live run; not a smoke test)
- Local prebuilt delivery CLI: `uv run python -m sab sell-ai-brief-scheduled --sell-ai-brief-report reports/YYYY-MM-DD.sell-ai-brief.json --scope MIXED`
- launchd generic wrapper delivery route: `SAB_SELL_SCHEDULE_MODE=delivery SELL_AI_BRIEF_REPORT_PATH=reports/YYYY-MM-DD.sell-ai-brief.json scripts/launchd/sab-scheduled-wrapper.sh --pipeline sell --scope MIXED`
- Manual GitHub Actions: `.github/workflows/sell.yml` remains manual opt-in generation/upload/notification and is not the scheduled path

Runtime markers use the `scheduled-sell:` prefix and are keyed by `scope + session_date`:

- `scheduled-sell:blocked:*`: Toss freshness blocked normal generation
- `scheduled-sell:blocked-notification-lock:*`: single-owner claim for freshness-blocked Telegram delivery
- `scheduled-sell:notification:blocked-sent:*`: freshness-blocked Telegram already sent
- `scheduled-sell:generation-lock:*`: generation runner lock; separate from the delivery lock
- `scheduled-sell:generation:*`: generation runner produced and uploaded sell/Sell AI Brief artifacts
- `scheduled-sell:review-required:*`: generation quality gate returned `WARN`; normal delivery happened but needs review
- `scheduled-sell:attempt:*`: pre-lock observation marker for a delivery attempt
- `scheduled-sell:lock:*`: main delivery lock; only the lock owner may publish canonical artifact/notification success markers
- `scheduled-sell:artifact:*`: Storage upload plus `report_index` indexing completed for the artifact
- `scheduled-sell:notification:claim:*`: single-owner claim for Telegram delivery/reconciliation
- `scheduled-sell:notification:sent:*`: notification delivery finished for the uploaded artifact
- `scheduled-sell:success:*`: upload and notification contract completed for that scope/session

Gate order:

1. Generation mode requires `toss-sync:success:MIXED:<session_date>` with status `applied` or `unchanged`. Missing, stale, or invalid freshness sends only a "매도 AI Brief 보류" alert and writes no `scheduled-sell:success`.
2. Generation mode claims a renewable generation lock, exports the current Supabase active holdings snapshot to `data/scheduler/holdings.MIXED.<session_date>.yaml`, runs `sab sell --holdings <snapshot>`, runs `sab sell-ai-brief`, and evaluates the artifact with `scripts/eval_sell_ai_brief.py`.
3. Quality `FAIL` blocks Supabase upload and normal Telegram delivery. Quality `WARN` can deliver but records `review-required` and returns `completed_review_required`.
4. Only after quality is non-`FAIL` does generation upload the sell report, then delegate the Sell AI Brief artifact to the delivery runner.
5. The delivery runner revalidates the Sell AI Brief artifact with `validate_sell_ai_brief_artifact(...)`, uploads/indexes it, records `artifact`, sends Telegram, then records `notification:sent` and `success`.

Use `scripts/verify_scheduled_sell_runtime_state.py` before closing a blocked or repaired run. It reads scheduler credentials from `${SAB_SCHEDULER_ENV_FILE:-.env.scheduler.local}`, compares the scheduler Supabase URL with the web env URL, prints redacted `toss-sync:success:MIXED:<session_date>` and `scheduled-sell:*` marker status, exits `0` only when both Toss freshness and final `scheduled-sell:success` exist, exits `1` for queried-but-not-ready/blocked states, and exits `2` for configuration or runtime_state query failures.

Reconciliation rules:

- If `success` already exists, the runner no-ops.
- If `artifact` exists without `success`, the runner downloads the uploaded JSON by storage key and retries notification reconciliation instead of uploading a second copy.
- `artifact_invalid`, `artifact_marker_invalid`, `lock_lost_before_upload`, `notification_sent_marker_invalid`, `notification_sent_marker_failed`, and `upload_failed` are failure statuses. `dry_run`, `success_marker_skip`, `lock_held_skip`, `completed`, `completion_repaired`, `notification_claim_held`, and `notification_reconciled` are non-fatal delivery outcomes.
- Generation failures include `toss_freshness_missing`, `toss_freshness_stale`, `toss_freshness_invalid`, `sell_report_failed`, `sell_ai_brief_failed`, `quality_gate_failed`, and `upload_failed`. Treat freshness failures as holdings-data problems first, not model failures. If delegated delivery reports an existing completion such as `success_marker_skip`, `notification_reconciled`, or `completion_repaired`, generation exits non-fatally without writing a new `generation` marker for the current local sell report.

## Local Toss Daily Auto Sync

The Toss auto-sync launchd job calls the local web route
`/api/holdings/toss-sync/scheduled` before scheduled scan/sell judgment and
US AI Brief feedback paths. Current KST launch times are Tue-Sat `06:55`,
Tue-Sat `07:15`, and Mon-Fri `21:05`, `21:40`, `22:05`, `22:40`.
Keep the web container on the same root `.env` values as the runner for
`TOSS_SYNC_JOB_TOKEN` and `TOSS_SYNC_AUTO_APPLY_ENABLED`.

Operational checks:

```bash
tail -n 20 logs/launchd/toss-daily-auto-sync.out.log
tail -n 20 logs/launchd/toss-daily-auto-sync.err.log
```

Only `status=applied` and `status=unchanged` are successful runner outcomes;
those statuses also write `toss-sync:success:MIXED:<session_date>` for the
scheduled sell generation freshness gate. `applied` with quarantine evidence
is fresh enough for generation because preserved holdings become Sell `REVIEW`
rows through the Supabase-exported holdings snapshot passed into `sab sell`.
If those rows reappear in a later Toss snapshot, scheduled sync restores
them to `confirmed` and clears the missing-broker evidence. `disabled`,
`blocked`, `wipe_guard_blocked`, `marker_failed`, and `error` are fail-closed
outcomes; inspect the web container logs and the current Holdings page before
rerunning. Full setup and QA steps live in
[deployment.md](deployment.md#local-toss-holdings-auto-sync).

## GitHub Actions

| Workflow | Normal Signal | Failure Start Point |
| --- | --- | --- |
| `scan.yml` | manual run uploads and indexes a report; no scheduled trigger until marker-aware local upload is implemented | KIS credentials, provider availability, upload step, report `system_issues` |
| `sell.yml` | manual run loads Supabase holdings, generates sell/Sell AI Brief artifacts, and only sends Sell AI Brief Telegram when the manual input opts in; local scheduled generation uses the generic wrapper instead of GitHub schedule | holdings query, KIS/pykrx provider, sell-ai-brief quality gate, upload step |
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
