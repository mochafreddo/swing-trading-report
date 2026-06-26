# Local Scheduled Pipelines And AI Brief Resilience Design

상태: Accepted for implementation planning
Status: Accepted for implementation planning
Date: 2026-06-26
Scope: scheduled trading pipeline operations, AI Brief model timeout resilience, local one-shot Docker runner logging, GitHub Actions role reduction

## Context

The 2026-06-26 US scheduled AI Brief failed in both local-primary and local-retry
runs. The scan, holdings export, entry report, and source-provider chain completed.
The failure boundary was the OpenAI model request:

```text
OpenAI request timed out
model_name=gpt-5.5
AI_BRIEF_MODEL_TIMEOUT_SECONDS=20
```

The same local scheduler path wrote local diagnostic AI Brief JSON artifacts, but the
scheduled quality gate correctly blocked upload and notification because the final
report had preselected candidates without recommendations or valid vetoes.

The scheduler is already local Docker based, but it is not a resident Docker
scheduler. The current architecture is:

```text
macOS launchd -> host wrapper -> docker compose run --rm scheduler -> sab CLI
```

`docker-compose.scheduler.yml` sets `restart: "no"`, and
`scripts/launchd/sab-ai-brief-wrapper.sh` runs `docker compose ... run --rm
scheduler`. Container logs are therefore ephemeral. Operational logs are preserved by
host-side launchd stdout/stderr paths and wrapper log files under `logs/launchd/`.

The user approved a broader direction:

- Keep one-shot Docker as the execution envelope.
- Fix AI Brief model timeout resilience and logging first.
- Add explicit timing measurement.
- Move trading scheduled jobs that currently rely on GitHub Actions toward local
  primary execution.
- Keep GitHub Actions for CI, audit, release, manual dispatch, monitor, and fallback
  rather than removing it completely.

## Problem

There are two related but separable operational problems.

First, the AI Brief model call has no timeout-only fallback model. A single slow
primary model can consume the model timeout and produce an invalid scheduled artifact
with `model_provider_timeout`, even when all upstream market/source data is healthy.
The existing 20 second timeout is too tight for a larger model under the current
prompt shape and source-backed candidate context.

Second, scheduled operations are split between local launchd/Docker and GitHub
Actions. AI Brief already uses local primary with GitHub monitor/fallback, but
`scan.yml`, `sell.yml`, and `cleanup.yml` still have GitHub scheduled triggers.
GitHub schedule delay is the reason local scheduled AI Brief was introduced in the
first place, so time-sensitive trading jobs should be evaluated for the same local
primary pattern.

## Goals

- Preserve strict scheduled AI Brief quality gates.
- Increase AI Brief model-call resilience without publishing weak or empty reports.
- Add structured timing logs for source collection, model attempts, fallback
  decisions, pipeline stages, and total run duration.
- Add a manual latency probe that measures current model latency in the same Docker
  envelope without upload or notification.
- Keep one-shot Docker as the scheduled execution model unless measurement later
  proves resident Docker is worth the extra operational state.
- Make host-side logs the source of truth for one-shot container runs.
- Generalize local scheduled execution so `scan` and `sell` can move to local primary
  in controlled canary phases.
- Keep GitHub Actions as a safety net: CI, audit, release, manual dispatch, monitor,
  fallback, and rollback path.

## Non-Goals

- Do not replace launchd with an in-container cron daemon in this design.
- Do not move CI, release-please, dependency lock sync, or PR/security audit off
  GitHub Actions.
- Do not remove GitHub workflow_dispatch manual runs.
- Do not disable existing GitHub scheduled trading jobs until the matching local
  primary canary has produced stable evidence.
- Do not weaken AI Brief evaluator rules or publish reports with empty model
  judgment.
- Do not store raw OpenAI responses or secrets in logs.
- Do not introduce Kubernetes, Redis, a queue, or a new external scheduler.

## Approved Approach

Use a phased design.

1. AI Brief model resilience and observability.
2. One-shot Docker log retention and timing measurement.
3. Local primary migration for GitHub scheduled trading jobs, starting with `scan`,
   then `sell`.
4. GitHub schedule role reduction after local canaries pass.

This keeps the direct incident fix small while creating a path to consolidate
time-sensitive operations locally.

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

One-shot Docker remains the default because it gives every scheduled run a clean
process boundary, picks up env/config changes on the next run, avoids resident
scheduler liveness state, and keeps Docker daemon failure visible to the host wrapper.

Host logs, not Docker container logs, are the durable log surface.

## AI Brief Model Resilience

Add timeout-only model fallback for OpenAI AI Brief generation.

Configuration:

- `OPENAI_AI_BRIEF_MODEL`: primary model.
- `AI_BRIEF_MODEL_TIMEOUT_SECONDS`: primary model timeout. Recommended scheduled
  value: `60`.
- `OPENAI_AI_BRIEF_FALLBACK_MODEL`: optional fallback model. Recommended scheduled
  value: the last known stable smaller model, for example `gpt-5.4-mini`.
- `AI_BRIEF_MODEL_FALLBACK_TIMEOUT_SECONDS`: fallback model timeout. Recommended
  value: `30`.
- `AI_BRIEF_MODEL_TOTAL_TIMEOUT_SECONDS`: total model-attempt budget. Recommended
  value: `90`.

Fallback rules:

- Fallback only after `AiBriefProviderTimeoutError`.
- Do not fallback for missing API key, HTTP 401/403, HTTP 429, non-timeout request
  failures, invalid JSON, provider contract errors, or local validation errors.
- If primary and fallback both fail, preserve the existing `system_issues[]` behavior
  and fail the scheduled quality gate when the final report is not valid.
- The final artifact `model_name` should identify the model that produced the accepted
  provider result. If no model succeeds, preserve the primary model name and include
  system issues for the failed attempts.

This avoids masking authorization/configuration problems while still recovering from
transient model latency.

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

Logs must not include the OpenAI API key, raw prompts, raw model response text, source
article bodies, or unbounded candidate payloads.

## Pipeline Timing Logs

Add duration logs for scheduled runner stages.

Events:

- `scheduled_pipeline_started`
- `scheduled_pipeline_stage_started`
- `scheduled_pipeline_stage_completed`
- `scheduled_pipeline_stage_failed`
- `scheduled_pipeline_completed`

Stage names:

- `guard`
- `docker_preflight`
- `scan`
- `holdings_export`
- `entry`
- `source_collect`
- `ai_brief_model`
- `quality_gate`
- `upload`
- `notification`
- `state_marker`

The wrapper should also record host-side timing:

- wrapper start time
- Docker preflight duration
- one-shot command start time
- container command exit time
- total wrapper duration

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
logs/scheduled/{pipeline}/{YYYY-MM-DD}/{market}-{role}-{attempt_id}.out.log
logs/scheduled/{pipeline}/{YYYY-MM-DD}/{market}-{role}-{attempt_id}.err.log
logs/scheduled/{pipeline}/{YYYY-MM-DD}/{market}-{role}-{attempt_id}.summary.json
```

The wrapper should continue streaming stdout/stderr to launchd while also writing the
attempt-scoped files. `summary.json` should include status, attempt id, runner role,
schedule role, market, session date, started/finished timestamps, duration fields, and
final scheduler status. It must not include secrets.

Retention:

- Keep logs for at least 30 days by default.
- Retain failed-run summaries longer than successful stdout/stderr when possible.
- Add a documented cleanup command rather than silently deleting logs inside the
  scheduled path.

## Latency Measurement

Add an explicit manual measurement path. It must not run automatically on schedule.

The measurement should run inside the same scheduler Docker envelope and use the same
env file resolution as production, but it should disable upload and notification.

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
- One to three repetitions per model/timeout pair.

Because this uses live OpenAI API calls and can incur cost, it must require an
explicit operator command. The command should have a dry-run style name that makes
upload/notification absence obvious.

## Local Scheduled Pipeline Generalization

Create a general local scheduled wrapper and runner interface rather than duplicating
AI Brief-specific shell logic for every pipeline.

Conceptual wrapper arguments:

```text
--pipeline ai-brief|scan|sell
--market KR|US|both
--schedule-role ROLE
--runner-role ROLE
--scheduled-tick HHMM|manual
--env-file PATH
--dry-run
```

Pipeline behavior:

- `ai-brief`: keep the existing scheduled runner semantics, runtime_state keys,
  quality gate, upload, and notification reconciliation.
- `scan`: run `sab scan` with the configured provider/universe, upload the buy report,
  and send scheduled notification only after idempotency checks pass.
- `sell`: export holdings from Supabase, run `sab sell`, upload the sell report, and
  send scheduled notification only after idempotency checks pass.

For `scan` and `sell`, the first local implementation should preserve the current
GitHub workflow behavior as closely as possible before adding new policy.

## Idempotency For Scan And Sell

AI Brief already uses `runtime_state` as the source of truth for scheduled
idempotency. `scan` and `sell` should gain equivalent scheduled state before GitHub
scheduled primary is disabled.

Recommended keys:

```text
scheduled-{pipeline}:lock:{market}:{session_date}
scheduled-{pipeline}:artifact:{market}:{session_date}
scheduled-{pipeline}:notification:claim:{market}:{session_date}
scheduled-{pipeline}:notification:sent:{market}:{session_date}
scheduled-{pipeline}:success:{market}:{session_date}
scheduled-{pipeline}:attempt:{market}:{session_date}:{runner_role}:{attempt_id}
```

Rules:

- A local primary and GitHub fallback must not generate duplicate uploaded artifacts
  for the same market/session/pipeline.
- If an artifact exists but notification did not complete, retry notification
  reconciliation before generating a new report.
- `report_index` can help repair missing state, but runtime_state remains the primary
  idempotency source.
- Manual dispatch should use a distinct runner role or explicit override so it does
  not accidentally satisfy scheduled success checks.

## GitHub Actions Role Reduction

Do not remove GitHub Actions. Reduce scheduled primary responsibility only after local
evidence exists.

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

AI Brief already has local primary execution. Keep the scheduled `ai-brief.yml`
monitor/fallback/cutoff roles during rollout. Reduce or remove those scheduled roles
only after local observability, manual rollback, and an alternate missing-run alert
path are proven.

Leave `cleanup.yml` on GitHub initially. Cleanup is not market-time-sensitive, and
GitHub provides a useful audit trail for deletes. Consider local cleanup only after
trading jobs have stable local logs and idempotency.

## Rollout Plan

Phase 1: AI Brief resilience.

- Increase scheduled AI Brief primary timeout recommendation to 60 seconds.
- Add timeout-only fallback model support.
- Add model attempt logs and stage duration logs.
- Add manual latency probe.
- Verify with unit tests and at least one explicit live measurement if the operator
  approves API-costing calls.

Phase 2: logging foundation.

- Add attempt-scoped logs and summary JSON for one-shot scheduled runs.
- Keep launchd role logs for compatibility.
- Document log lookup and retention.

Phase 3: local `scan` canary.

- Add local one-shot scheduled scan path.
- Keep GitHub scheduled scan enabled at first, but use runtime_state to prevent
  duplicate upload/notification.
- After several successful local runs, switch GitHub scheduled scan to monitor/manual
  behavior or remove its scheduled cron.

Phase 4: local `sell` canary.

- Add local one-shot scheduled sell path.
- Preserve Supabase holdings export field contract.
- Keep GitHub scheduled sell enabled at first, with duplicate prevention.
- After successful local runs, switch GitHub scheduled sell to monitor/manual behavior
  or remove its scheduled cron.

Phase 5: reassess cleanup and resident Docker.

- Keep cleanup on GitHub unless delete audit requirements or GitHub schedule
  reliability change.
- Reconsider resident Docker only if measured one-shot startup overhead is large
  enough to affect market timing or operator experience.

## Error Handling

- Docker daemon unavailable remains a host failure and should alert from the host
  wrapper when notification credentials are available.
- Structured scheduler application failures should not be mislabeled as container
  launch failures.
- Model timeouts are retryable only within the explicit fallback budget.
- Provider auth/config/rate-limit failures are not fallback candidates.
- Quality gate failures remain fail-closed and block upload/success markers.
- Logs should distinguish host failure, application failure, quality failure, upload
  failure, and notification failure.

## Testing

AI Brief tests:

- Primary model timeout falls back to configured fallback model.
- Fallback is not attempted for non-timeout provider errors.
- Total model budget limits fallback timeout.
- Successful fallback sets final model metadata to the successful model.
- Failed primary and failed fallback produce visible system issues and fail the
  scheduled quality gate when the artifact has no valid judgment.
- Structured log events include attempt role, model name, duration, retryable, and
  fallback fields.

Scheduler/wrapper tests:

- One-shot wrapper writes attempt-scoped stdout, stderr, command, guard, and summary
  files.
- Wrapper preserves launchd stdout/stderr streaming.
- Structured scheduler failure is not classified as host/container launch failure.
- Host preflight failures still alert as host failures.
- Log paths reject unsafe market/role/attempt values.

Local pipeline tests:

- `scan` local primary uses the same upload/notification semantics as the existing
  workflow.
- `sell` local primary preserves Supabase holdings export fields, including
  `entry_pattern`.
- Local primary and GitHub fallback cannot both upload or notify for the same
  pipeline/market/session.
- Artifact-only notification reconciliation does not regenerate reports.

Workflow tests:

- GitHub manual dispatch remains available.
- Scheduled cron removal or monitor-only conversion is covered by workflow tests.
- CI/audit/release workflows remain unchanged.

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

No `docs/STRATEGY.md` update is required for Phase 1 because model fallback,
timeouts, logging, and runner placement do not change trading signal logic.

If `scan` or `sell` scheduling policy changes market timing, update strategy or
operations docs as appropriate.

## Acceptance Criteria

- Scheduled AI Brief no longer fails solely because the primary OpenAI model exceeds a
  20 second timeout when a configured fallback model can produce a valid report within
  budget.
- Model attempt logs show duration, selected model, timeout, fallback decision, and
  final status.
- One-shot Docker runs have durable attempt-scoped host logs and summary JSON.
- Manual latency measurement can estimate current model response times without upload
  or notification.
- `scan` and `sell` have a documented path to local primary execution with
  idempotency before GitHub scheduled primary is disabled.
- GitHub Actions remains available for CI, audit, release, manual dispatch,
  monitor/fallback, and rollback.
- No secrets, raw prompts, raw model responses, or unbounded source bodies are written
  to logs.
