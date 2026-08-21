# Local Scheduled Pipelines And AI Brief Resilience Design

상태: Accepted for implementation planning
Status: Accepted for implementation planning
Date: 2026-06-26
Scope: scheduled trading pipeline operations, AI Brief model timeout resilience, local one-shot Docker runner logging, GitHub Actions role reduction

## Context

The 2026-06-26 US scheduled AI Brief failed in both local-primary and local-retry runs. The scan, holdings export, entry report, and source-provider chain completed. The failure boundary was the OpenAI model request:

```text
OpenAI request timed out
model_name=gpt-5.5
AI_BRIEF_MODEL_TIMEOUT_SECONDS=20
```

The same local scheduler path wrote local diagnostic AI Brief JSON artifacts, but the scheduled quality gate correctly blocked upload and notification because the final report had preselected candidates without recommendations or valid vetoes.

The scheduler is already local Docker based, but it is not a resident Docker scheduler. The current architecture is:

```text
macOS launchd -> host wrapper -> docker compose run --rm scheduler -> sab CLI
```

`docker-compose.scheduler.yml` sets `restart: "no"`, and `scripts/launchd/sab-ai-brief-wrapper.sh` runs `docker compose ... run --rm scheduler`. Container logs are therefore ephemeral. Operational logs are preserved by host-side launchd stdout/stderr paths and wrapper log files under `logs/launchd/`.

The user approved a broader direction:

- Keep one-shot Docker as the execution envelope.
- Fix AI Brief model timeout resilience and logging first.
- Add explicit timing measurement.
- Move trading scheduled jobs that currently rely on GitHub Actions toward local primary execution.
- Keep GitHub Actions for CI, audit, release, manual dispatch, monitor, and fallback rather than removing it completely.

## Problem

There are two related but separable operational problems.

First, the AI Brief model call has no timeout-only fallback model. A single slow primary model can consume the model timeout and produce an invalid scheduled artifact with `model_provider_timeout`, even when all upstream market/source data is healthy. The existing 20 second timeout is too tight for a larger model under the current prompt shape and source-backed candidate context.

Second, scheduled operations are split between local launchd/Docker and GitHub Actions. AI Brief already uses local primary with GitHub monitor/fallback, but `scan.yml`, `sell.yml`, and `cleanup.yml` still have GitHub scheduled triggers. GitHub schedule delay is the reason local scheduled AI Brief was introduced in the first place, so time-sensitive trading jobs should be evaluated for the same local primary pattern.

## Goals

- Preserve strict scheduled AI Brief quality gates.
- Increase AI Brief model-call resilience without publishing weak or empty reports.
- Add structured timing logs for source collection, model attempts, fallback decisions, pipeline stages, and total run duration.
- Add a manual latency probe that measures current model latency in the same Docker envelope without upload or notification.
- Make model timeout decisions deadline-aware so fallback does not start when the remaining market window cannot still support upload and notification.
- Keep one-shot Docker as the scheduled execution model unless measurement later proves resident Docker is worth the extra operational state.
- Make host-side logs the source of truth for one-shot container runs.
- Generalize local scheduled execution so `scan` and `sell` can move to local primary in controlled canary phases.
- Keep GitHub Actions as a safety net: CI, audit, release, manual dispatch, monitor, fallback, and rollback path.

## Non-Goals

- Do not replace launchd with an in-container cron daemon in this design.
- Do not move CI, release-please, dependency lock sync, or PR/security audit off GitHub Actions.
- Do not remove GitHub workflow_dispatch manual runs.
- Do not disable existing GitHub scheduled trading jobs until the matching local primary canary has produced stable evidence.
- Do not enable local scheduled `scan` or `sell` upload while GitHub scheduled primary can still upload without checking the same runtime state.
- Do not weaken AI Brief evaluator rules or publish reports with empty model judgment.
- Do not store raw OpenAI responses or secrets in logs.
- Do not introduce Kubernetes, Redis, a queue, or a new external scheduler.

## Approved Approach

Use a phased design.

1. AI Brief model resilience and observability.
2. One-shot Docker log retention and timing measurement.
3. Generic locked scheduled runner foundation for non-AI-Brief trading pipelines.
4. Local primary migration for GitHub scheduled trading jobs, starting with `scan`, then `sell`, only after GitHub scheduled jobs are converted to marker-aware monitor/fallback.
5. GitHub schedule role reduction after local canaries pass.

This keeps the direct incident fix small while creating a path to consolidate time-sensitive operations locally.

## Architecture

The target operating model is:

```text
launchd
  -> host scheduled wrapper
  -> one-shot Docker runner
  -> sab scheduled command
  -> Supabase runtime_state/report_index/storage
  -> Telegram required + Slack best-effort notification

GitHub Actions
  -> CI/audit/release/manual dispatch
  -> monitor/fallback during rollout
  -> rollback execution path
```

One-shot Docker remains the default because it gives every scheduled run a clean process boundary, picks up env/config changes on the next run, avoids resident scheduler liveness state, and keeps Docker daemon failure visible to the host wrapper.

Host logs, not Docker container logs, are the durable log surface.

## AI Brief Model Resilience

Add timeout-only model fallback for OpenAI AI Brief generation.

Configuration:

- `OPENAI_AI_BRIEF_MODEL`: primary model.
- `AI_BRIEF_MODEL_TIMEOUT_SECONDS`: primary model timeout. Recommended scheduled value: `60`.
- `OPENAI_AI_BRIEF_FALLBACK_MODEL`: optional fallback model. Recommended scheduled value: the last known stable smaller model, for example `gpt-5.4-mini`.
- `AI_BRIEF_MODEL_FALLBACK_TIMEOUT_SECONDS`: fallback model timeout. Recommended value: `30`.
- `AI_BRIEF_MODEL_TOTAL_TIMEOUT_SECONDS`: total model-attempt budget. Recommended value: `90`.

Fallback rules:

- Fallback only after `AiBriefProviderTimeoutError`.
- Do not fallback for missing API key, HTTP 401/403, HTTP 429, non-timeout request failures, invalid JSON, provider contract errors, or local validation errors.
- If primary and fallback both fail, preserve the existing `system_issues[]` behavior and fail the scheduled quality gate when the final report is not valid.
- The final artifact `model_name` should identify the model that produced the accepted provider result. If no model succeeds, preserve the primary model name and include system issues for the failed attempts.
- Implement fallback inside `run_ai_brief` before artifact construction. Do not implement fallback by rerunning the CLI after a timeout.
- Keep model attempts in memory and write exactly one final AI Brief artifact per `run_ai_brief` invocation.
- Include bounded model attempt metadata in the final artifact or summary only after defining the schema. The metadata must include model name, role, status, duration, and error code/type, but not raw prompts or raw model responses.
- Forward fallback configuration through every scheduled execution path, including local env files and GitHub `ai-brief.yml` monitor/fallback jobs. GitHub fallback must not remain primary-only unless it is explicitly documented as degraded rollback behavior.

Deadline rules:

- Scheduled AI Brief should derive a per-run deadline from the role window and hard cutoff policy.
- Each model attempt timeout is the minimum of the configured timeout, total model budget remaining, and run deadline remaining after reserving a publish margin.
- Do not start fallback unless the remaining deadline can cover the fallback timeout, quality gate, upload, and notification margin.
- If the fallback cannot start because the deadline is too close, record a structured deadline skip issue rather than starting work that cannot publish on time.

This avoids masking authorization/configuration problems while still recovering from transient model latency.

## Model Attempt Logging

Add structured logs around every model attempt.

Events:

- `ai_brief_model_attempt_started`
- `ai_brief_model_attempt_completed`
- `ai_brief_model_attempt_failed`
- `ai_brief_model_fallback_selected`
- `ai_brief_model_attempts_exhausted`

Required fields:

- `run_id`
- `operation`
- `market`
- `attempt_role`: `primary` or `fallback`
- `model_provider`
- `model_name`
- `timeout_seconds`
- `remaining_total_timeout_seconds`
- `ticker_count`
- `watch_count`
- `source_count`
- `duration_ms` for completed or failed attempts
- `recommendation_count`, `vetoed_count`, `watch_output_count` on success
- `error_type`, `retryable`, `fallback_next` on failure

Logs must not include the OpenAI API key, raw prompts, raw model response text, source article bodies, or unbounded candidate payloads.

## Pipeline Timing Logs

Add duration logs for both host-wrapper stages and in-container scheduler stages. Do not report host-only work as Python runner work.

Host wrapper events:

- `scheduled_host_wrapper_started`
- `scheduled_host_guard_completed`
- `scheduled_host_docker_preflight_completed`
- `scheduled_host_container_started`
- `scheduled_host_container_completed`
- `scheduled_host_wrapper_completed`

Host wrapper fields:

- wrapper start time
- guard duration
- Docker preflight duration
- one-shot command start time
- container command exit time
- total wrapper duration
- final status from the dedicated status file when available

Container runner events:

- `scheduled_pipeline_started`
- `scheduled_pipeline_stage_started`
- `scheduled_pipeline_stage_completed`
- `scheduled_pipeline_stage_failed`
- `scheduled_pipeline_completed`

Stage names:

- `guard`
- `scan`
- `holdings_export`
- `entry`
- `source_collect`
- `ai_brief_model`
- `quality_gate`
- `upload`
- `notification`
- `state_marker`

The scheduler should write a dedicated final status file, not rely only on stdout parsing.

Status file:

```text
logs/scheduled/{pipeline}/{YYYY-MM-DD}/{scope}-{role}-{attempt_id}.status.json
```

Rules:

- The wrapper passes the status file path to the container with an env var such as `SAB_SCHEDULER_STATUS_FILE`.
- The Python scheduler writes the status file atomically before exiting.
- The wrapper reads the status file to classify structured application failures.
- The existing final stdout JSON can remain for backward compatibility, but it should not be the only source of truth.
- Tests must cover non-last-line stdout JSON, stderr-only failures, missing status file, malformed status file, and successful status file parsing.

## One-Shot Log Retention

Keep one-shot Docker, but make logs easier to inspect.

Current launchd role logs remain supported:

- `logs/launchd/us.local-primary.out.log`
- `logs/launchd/us.local-primary.err.log`
- `logs/launchd/us.local-retry.out.log`
- `logs/launchd/us.local-retry.err.log`
- `logs/launchd/us.cutoff-alert.out.log`
- role-specific `*.guard.log` and `*.cmd.log`

Add attempt-scoped logs:

```text
logs/scheduled/{pipeline}/{YYYY-MM-DD}/{scope}-{role}-{attempt_id}.out.log
logs/scheduled/{pipeline}/{YYYY-MM-DD}/{scope}-{role}-{attempt_id}.err.log
logs/scheduled/{pipeline}/{YYYY-MM-DD}/{scope}-{role}-{attempt_id}.guard.log
logs/scheduled/{pipeline}/{YYYY-MM-DD}/{scope}-{role}-{attempt_id}.cmd.log
logs/scheduled/{pipeline}/{YYYY-MM-DD}/{scope}-{role}-{attempt_id}.status.json
logs/scheduled/{pipeline}/{YYYY-MM-DD}/{scope}-{role}-{attempt_id}.summary.json
```

The wrapper should continue streaming stdout/stderr to launchd while also writing the attempt-scoped files. `summary.json` should include status, attempt id, runner role, schedule role, scope, session date, started/finished timestamps, duration fields, and final scheduler status. It must not include secrets.

Secret-safety rules:

- `summary.json` is allowlist-only. It must never serialize env, argv objects, request payloads, source bodies, raw prompts, raw responses, or exception objects without field filtering.
- Attempt log files and directories should be created with restrictive permissions where the platform allows it.
- Host failure alerts should move token-bearing Telegram requests out of shell argv, for example into a small Python helper that reads credentials from environment and sends the request without logging them.
- `cmd.log` should show the reproducible command shape without env values.

Retention:

- Keep logs for at least 30 days by default.
- Retain failed-run summaries longer than successful stdout/stderr when possible.
- Add a documented cleanup command rather than silently deleting logs inside the scheduled path.

## Latency Measurement

Add an explicit manual measurement path. It must not run automatically on schedule.

The measurement should run with the same dependency image and env file resolution as production, but it should disable upload and notification. Current scheduled `--dry-run` is not sufficient because it returns before model execution; the probe needs its own entrypoint.

Entrypoint:

```text
uv run python -m sab ai-brief-latency-probe ...
```

The command may be implemented as a `sab` subcommand or a script, but it must not use `ai-brief-scheduled --dry-run` as the model execution path.

Minimum measurement output:

```text
logs/measurements/ai-brief-model-latency/{YYYY-MM-DD}.jsonl
```

Each JSONL row should include:

- timestamp
- market
- entry report path or source report path used
- model name
- timeout seconds
- attempt number
- status
- duration_ms
- recommendation_count
- vetoed_count
- watch_count
- error_type when failed

Default probe matrix:

- Primary model with 20, 30, and 60 second timeout limits.
- Fallback model with 30 second timeout.
- One repetition per model/timeout pair by default.
- At most three repetitions per model/timeout pair unless the operator passes an explicit override.

Because this uses live OpenAI API calls and can incur cost, it must require an explicit operator command. The command should have a dry-run style name that makes upload/notification absence obvious.

Safety limits:

- Print the exact planned live call count before running.
- Default to `article_reader=none`.
- Cap preselected candidates and source rows per ticker for probes.
- Refuse to run during active scheduled windows or while a matching scheduled lock is active, unless the operator passes an explicit force flag.
- Use isolated measurement output paths and never write normal report artifacts unless explicitly requested.
- Do not reuse a production scheduler container name for probes. Either remove the fixed `container_name` from the scheduler compose service or add a separate `scheduler-probe` service without a fixed `container_name`.

## Local Scheduled Pipeline Generalization

Create a general local scheduled wrapper and runner interface rather than duplicating AI Brief-specific shell logic for every pipeline.

Compatibility rule:

- Add a new generic wrapper, for example `scripts/launchd/sab-scheduled-wrapper.sh`.
- Keep the existing AI Brief wrapper as a backward-compatible shim until launchd plist migration is complete.
- Keep existing AI Brief state keys stable unless a dedicated migration is designed.
- The generic wrapper must support AI Brief without changing current launchd behavior before `scan` or `sell` is migrated.

Conceptual wrapper arguments:

```text
--pipeline ai-brief|scan|sell
--scope KR|US|MIXED
--schedule-role ROLE
--runner-role ROLE
--scheduled-tick HHMM|manual
--env-file PATH
--dry-run
```

Scope rules:

- `scope` is the idempotency and scheduling scope, not necessarily the report's internal market field.
- Existing AI Brief remains market-scoped and uses `KR` or `US`.
- Current scheduled `scan` defaults can be mixed-market, so generic `scan` state must support `MIXED` or the local scheduled scan must be split into separate `KR` and `US` runs before upload is enabled.
- Current scheduled `sell` should use `MIXED` unless or until holdings/report logic is split by market.
- Manual dispatch may keep existing `both` workflow input semantics, but manual runs must not satisfy scheduled success markers unless explicitly requested.

Pipeline behavior:

- `ai-brief`: keep the existing scheduled runner semantics, runtime_state keys, quality gate, upload, and notification reconciliation.
- `scan`: run `sab scan` with the configured provider/universe, upload the buy report, and send scheduled notification only after idempotency checks pass.
- `sell`: export holdings from Supabase, run `sab sell`, upload the sell report, and send scheduled notification only after idempotency checks pass.

For `scan` and `sell`, the first local implementation should preserve the current GitHub workflow behavior as closely as possible before adding new policy.

Upload boundary:

- Scheduled `scan` and `sell` must run inside a locked scheduled runner before upload is enabled.
- Generation steps must suppress direct CLI upload and direct scheduled notification.
- The locked runner performs the only scheduled upload after claiming the main lock and checking that no artifact marker already exists.
- The locked runner performs notification reconciliation after artifact upload.
- If a report artifact already exists but notification is missing, retry notification reconciliation before generating a new report.
- GitHub scheduled `scan` and `sell` must check the same runtime state before provider execution, upload, or notification.

## Idempotency For Scan And Sell

AI Brief already uses `runtime_state` as the source of truth for scheduled idempotency. `scan` and `sell` should gain equivalent scheduled state before GitHub scheduled primary is disabled.

Recommended keys:

```text
scheduled-{pipeline}:lock:{scope}:{session_date}
scheduled-{pipeline}:artifact:{scope}:{session_date}
scheduled-{pipeline}:notification:claim:{scope}:{session_date}
scheduled-{pipeline}:notification:sent:{scope}:{session_date}
scheduled-{pipeline}:success:{scope}:{session_date}
scheduled-{pipeline}:attempt:{scope}:{session_date}:{runner_role}:{attempt_id}
```

Do not reuse the current AI Brief-only `build_scheduler_state_key` unchanged for generic pipelines. Add a generic scheduled state key builder that accepts `pipeline` and `scope`, while keeping AI Brief compatibility keys intact.

Rules:

- A local primary and GitHub fallback must not generate duplicate uploaded artifacts for the same scope/session/pipeline.
- If an artifact exists but notification did not complete, retry notification reconciliation before generating a new report.
- `report_index` can help repair missing state, but runtime_state remains the primary idempotency source.
- Manual dispatch should use a distinct runner role or explicit override so it does not accidentally satisfy scheduled success checks.
- For canary, prefer shadow local generation without upload first. Enable local upload only after the GitHub scheduled job is marker-aware and cannot independently upload the same scope/session.

## GitHub Actions Role Reduction

Do not remove GitHub Actions. Reduce scheduled primary responsibility only after local evidence exists.

Keep on GitHub:

- `ci.yml`
- `audit.yml`
- `release-please.yml`
- `mise-lock-sync.yml`
- workflow_dispatch paths for scan, sell, cleanup, and AI Brief
- monitor/fallback/cutoff alert roles during rollout

Candidate local-primary migrations:

- `scan.yml` scheduled trigger
- `sell.yml` scheduled trigger

AI Brief already has local primary execution. Keep the scheduled `ai-brief.yml` monitor/fallback/cutoff roles during rollout. Reduce or remove those scheduled roles only after local observability, manual rollback, and an alternate missing-run alert path are proven.

Leave `cleanup.yml` on GitHub initially. Cleanup is not market-time-sensitive, and GitHub provides a useful audit trail for deletes. Consider local cleanup only after trading jobs have stable local logs and idempotency.

Before local upload is enabled for `scan` or `sell`, the matching GitHub scheduled job must be converted from primary execution to marker-aware monitor/fallback:

- Resolve schedule context and scope before dependency install/provider execution.
- Check success, artifact, notification, and attempt markers before running providers.
- Run the full pipeline only as an explicit fallback role after local primary is missing or failed and the lock can be claimed.
- Keep workflow_dispatch manual runs isolated from scheduled markers by default.
- Use runtime_state keys, not only GitHub workflow concurrency, to prevent duplicate uploads and notifications.

## Rollout Plan

Phase 1: AI Brief resilience.

- Increase scheduled AI Brief primary timeout recommendation to 60 seconds.
- Add timeout-only fallback model support.
- Add model attempt logs and stage duration logs.
- Add manual latency probe.
- Verify with unit tests and at least one explicit live measurement if the operator approves API-costing calls.

Phase 2: logging foundation.

- Add attempt-scoped logs and summary JSON for one-shot scheduled runs.
- Keep launchd role logs for compatibility.
- Add dedicated status JSON file handling.
- Document log lookup and retention.

Phase 3: generic scheduled runner foundation.

- Add generic wrapper while keeping the existing AI Brief wrapper as a compatibility path.
- Add generic state keys with `pipeline` and `scope`.
- Add locked upload/notification boundary for non-AI-Brief scheduled pipelines.
- Add GitHub scheduled monitor/fallback preflight behavior for scan/sell before local upload is enabled.

Phase 4: local `scan` canary.

- Start with local shadow generation without upload.
- Convert GitHub scheduled scan to marker-aware monitor/fallback.
- Enable local one-shot scheduled scan upload only after duplicate prevention is in place.
- After several successful local runs, switch GitHub scheduled scan to monitor/manual behavior or remove its scheduled cron.

Phase 5: local `sell` canary.

- Start with local shadow generation without upload.
- Preserve Supabase holdings export field contract.
- Convert GitHub scheduled sell to marker-aware monitor/fallback.
- Enable local one-shot scheduled sell upload only after duplicate prevention is in place.
- After successful local runs, switch GitHub scheduled sell to monitor/manual behavior or remove its scheduled cron.

Phase 6: reassess cleanup and resident Docker.

- Keep cleanup on GitHub unless delete audit requirements or GitHub schedule reliability change.
- Reconsider resident Docker only if measured one-shot startup overhead is large enough to affect market timing or operator experience.

## Error Handling

- Docker daemon unavailable remains a host failure and should alert from the host wrapper when notification credentials are available.
- Structured scheduler application failures should not be mislabeled as container launch failures. Wrapper classification should prefer dedicated status JSON over stdout scraping.
- Model timeouts are retryable only within the explicit fallback budget.
- Model fallback is skipped when the run deadline cannot still support publish.
- Provider auth/config/rate-limit failures are not fallback candidates.
- Quality gate failures remain fail-closed and block upload/success markers.
- Logs should distinguish host failure, application failure, quality failure, upload failure, and notification failure.
- Latency probes should fail closed when a scheduled lock/window conflict is detected, unless an explicit force flag is provided.

## Testing

AI Brief tests:

- Primary model timeout falls back to configured fallback model.
- Fallback is not attempted for non-timeout provider errors.
- Total model budget limits fallback timeout.
- Role/cutoff deadline limits fallback timeout and can skip fallback when publish margin is unavailable.
- Successful fallback sets final model metadata to the successful model.
- Fallback is performed inside one `run_ai_brief` invocation and writes exactly one final artifact.
- Failed primary and failed fallback produce visible system issues and fail the scheduled quality gate when the artifact has no valid judgment.
- Structured log events include attempt role, model name, duration, retryable, and fallback fields.
- GitHub scheduled AI Brief receives fallback model, fallback timeout, and total timeout environment variables.

Scheduler/wrapper tests:

- One-shot wrapper writes attempt-scoped stdout, stderr, command, guard, and summary files.
- Wrapper preserves launchd stdout/stderr streaming.
- Structured scheduler failure from status JSON is not classified as host/container launch failure.
- Wrapper handles status JSON that is not the last stdout line.
- Wrapper handles malformed/missing status JSON and stderr-only failures predictably.
- Host preflight failures still alert as host failures.
- Log paths reject unsafe scope/role/attempt values.
- Summary JSON is allowlist-only and does not contain env, argv, tokens, raw prompts, raw responses, or source bodies.
- Host alert transport avoids token-bearing command arguments.

Local pipeline tests:

- `scan` local primary uses the same upload/notification semantics as the existing workflow.
- `sell` local primary preserves Supabase holdings export fields, including `entry_pattern`.
- Local primary and GitHub fallback cannot both upload or notify for the same pipeline/scope/session.
- Artifact-only notification reconciliation does not regenerate reports.
- `MIXED` scope is represented consistently for scheduled scan/sell, or scheduled local upload rejects mixed-market execution until split-market support exists.
- Scheduled scan/sell generation suppresses direct CLI upload before the locked runner performs the single upload.
- GitHub scheduled scan/sell checks runtime_state before provider execution, upload, or notification.
- Manual dispatch does not create scheduled success markers by default.

Workflow tests:

- GitHub manual dispatch remains available.
- Scheduled cron removal or monitor-only conversion is covered by workflow tests.
- CI/audit/release workflows remain unchanged.

Latency probe tests:

- Probe command executes model calls without upload or notification.
- Probe refuses to run during active scheduled windows or locks unless forced.
- Probe prints planned live call count before execution.
- Probe defaults to article reader disabled and enforces candidate/source/repetition caps.
- Probe uses a non-conflicting compose service/container naming strategy.

Recommended verification for the first implementation slice:

```text
UV_CACHE_DIR=.uv-cache uv run python -m pytest -q tests/test_ai_brief.py tests/test_ai_brief_providers.py tests/test_notification_text.py tests/test_launchd_scheduler_wrapper.py
```

Broader pipeline migration slices should run the repository Python quality gate:

```text
just quality
```

## Documentation

Update these docs as implementation lands:

- `docs/configuration.md`
- `docs/config-reference.md`
- `docs/operations.md`
- `docs/deployment.md`
- `docs/local-docker-scheduler-plan.md`
- `docs/ARCHITECTURE.md` if the scheduled pipeline responsibilities change

No `docs/STRATEGY.md` update is required for Phase 1 because model fallback, timeouts, logging, and runner placement do not change trading signal logic.

If `scan` or `sell` scheduling policy changes market timing, update strategy or operations docs as appropriate.

## Acceptance Criteria

- Scheduled AI Brief no longer fails solely because the primary OpenAI model exceeds a 20 second timeout when a configured fallback model can produce a valid report within budget.
- AI Brief fallback is implemented inside artifact construction, writes one final artifact, and is deadline-aware.
- GitHub scheduled AI Brief fallback receives the same fallback model configuration as local scheduled AI Brief.
- Model attempt logs show duration, selected model, timeout, fallback decision, and final status.
- One-shot Docker runs have durable attempt-scoped host logs, dedicated status JSON, and summary JSON.
- Manual latency measurement can estimate current model response times without upload or notification, with explicit call-count, cap, and schedule-conflict controls.
- `scan` and `sell` have a documented path to local primary execution with idempotency before GitHub scheduled primary is disabled.
- `scan` and `sell` scheduled local upload cannot be enabled until upload is behind a claimed lock and GitHub scheduled jobs are marker-aware monitor/fallback jobs.
- Generic scheduled state supports a `scope` such as `MIXED`, or mixed scheduled runs are rejected before upload.
- GitHub Actions remains available for CI, audit, release, manual dispatch, monitor/fallback, and rollback.
- No secrets, raw prompts, raw model responses, or unbounded source bodies are written to logs.
