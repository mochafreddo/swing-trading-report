# AI Brief Model Contract And Host Alert Design

상태: Accepted
Status: Accepted for implementation planning
Date: 2026-06-24
Scope: AI Brief OpenAI output contract, provider result normalization, scheduled quality gate behavior, launchd host-failure alert classification

## Context

The 2026-06-24 US scheduled AI Brief local-primary run produced:

- `reports/2026-06-23.buy.json`
- `reports/2026-06-24.entry.json`
- `reports/2026-06-24.ai-brief.json`

The local-retry run produced:

- `reports/2026-06-23-1.buy.json`
- `reports/2026-06-24-1.entry.json`
- `reports/2026-06-24-1.ai-brief.json`

Both runs reached scan, holdings export, entry evaluation, and source-provider collection. Finnhub covered both recommendable tickers. The failure happened after OpenAI returned structured output:

```text
OpenAI output vetoed_candidates[0].ticker must be eligible
```

The valid preselected AI Brief ticker universe for both runs was:

```json
["MO.NYS", "RTX.NYS"]
```

`run_ai_brief` correctly converted the provider contract error into an AI Brief artifact with a `system_issues[]` row, no recommendations, and no valid vetoes. The scheduled quality gate then failed the artifact before Storage upload, success marker creation, and notification reconciliation. That is correct fail-closed behavior.

The launchd wrapper then added a second alert:

```text
[SAB][ai-brief][host-failure]
reason=scheduler_container_failed
```

That host-failure message is misleading in this case. Docker and the scheduler container started. The application returned a structured `pipeline_failed` status.

This design follows the candidate role split from 2026-06-15 and the source-ref partial publish design from 2026-06-17. Source-ref failures are already isolated at candidate level when the final artifact remains valid. Unknown veto tickers need the same kind of blast-radius control.

## Problem

The OpenAI JSON schema currently says `ticker` is a string for:

- `recommendations[].ticker`
- `vetoed_candidates[].ticker`
- `watch_candidates[].ticker`

The prompt tells the model not to create new tickers, and local validation rejects unknown tickers. That protects the final report, but it still lets one invalid `vetoed_candidates[]` row turn the whole provider result into a system issue. In a scheduled run, an `ERROR` system issue becomes a quality gate `FAIL`.

The wrapper has a separate problem. It treats every non-zero scheduler container exit as `scheduler_container_failed`, even when the scheduler printed a structured application status such as `pipeline_failed`.

## Goals

- Make the model boundary stricter by constraining ticker fields to the request-local ticker universe whenever the OpenAI JSON schema can express that.
- Keep local validation as the authority. Schema constraints reduce bad output, but do not replace validation.
- Isolate invalid `vetoed_candidates[]` rows when a row names a ticker outside the eligible veto universe.
- Preserve fail-closed scheduled behavior when, after sanitization, eligible candidates have no recommendation and no valid veto.
- Preserve hard failures for malformed top-level output, invalid action values, unsafe automated-order language, invalid ranks, and source data that cannot be trusted.
- Stop sending wrapper `scheduler_container_failed` host alerts for structured scheduler application failures.
- Keep host-failure alerts for actual host/wrapper failures such as unreadable env file, Docker daemon unavailable, command invocation failure with no structured scheduler status, and guard preflight failure before the Docker scheduler run.

## Non-Goals

- Do not store raw OpenAI responses in this pass.
- Do not relax URL safety, source freshness, source-ref allowlists, role boundaries, or automated-order language checks.
- Do not change Supabase schema, `report_index`, or public report storage layout.
- Do not change Web UI behavior in this pass.
- Do not retry model calls in this pass.
- Do not make a quality-gate `FAIL` publish a normal AI Brief notification.

## Approved Approach

Use two defenses at the model boundary and one operational cleanup at the wrapper boundary:

1. Build the OpenAI structured-output schema from the request-local candidate ticker sets.
2. Sanitize invalid veto rows into warning diagnostics instead of turning the whole provider result into a system issue.
3. Teach the launchd wrapper to distinguish structured scheduler application failures from host/container launch failures.

This keeps scheduled success strict while making failure modes more accurate.

## Model Schema Design

Change `_build_openai_request_payload` and `_openai_result_schema` so the schema builder receives ordered ticker lists:

- `eligible_tickers`: tickers from `recommendable_candidates`
- `watch_tickers`: tickers from `watch_candidates`

Schema rules:

- `recommendations[].ticker` uses `enum: eligible_tickers` when eligible tickers are present.
- `vetoed_candidates[].ticker` uses `enum: eligible_tickers` when eligible tickers are present.
- `watch_candidates[].ticker` uses `enum: watch_tickers` when watch tickers are present.
- If a role has an empty ticker list, its array gets `maxItems: 0` and the item ticker schema stays a plain string. This avoids emitting an empty enum while still telling the model that no rows are allowed for that role.

The request payload should also include compact explicit ticker lists in the user content:

```json
{
  "eligible_tickers": ["MO.NYS", "RTX.NYS"],
  "watch_tickers": []
}
```

The prompt should say:

- `recommendations[].ticker` and `vetoed_candidates[].ticker` must be one of `eligible_tickers`.
- `watch_candidates[].ticker` must be one of `watch_tickers`.
- If there are no eligible tickers, return empty `recommendations` and `vetoed_candidates`.
- If there are no watch tickers, return empty `watch_candidates`.
- Never put excluded entry-report rows in `recommendations`, `vetoed_candidates`, or `watch_candidates`.

## Provider Normalization Design

Add request-local veto sanitization after parsing `vetoed_candidates` and before constructing `AiBriefProviderResult`.

The sanitizer should produce:

- `valid_vetoed_candidates`: rows whose ticker is in `eligible_tickers`
- `model_output_issues`: WARN rows appended to existing `source_issues`

Use source issues rather than a new artifact field because the current artifact contract already treats `source_issues[]` as non-fatal model/provider diagnostics when severity is `WARN`. Introducing `model_issues[]` would require report schema, web, notification, storage, and evaluator changes beyond this fix.

Issue codes:

- `model_ineligible_veto_dropped`: `vetoed_candidates[]` row named a ticker outside `eligible_tickers`.
- `model_watch_veto_dropped`: `vetoed_candidates[]` row named a ticker from `watch_tickers`.

Both issues use `severity: "WARN"` and include the offending ticker. The message should be safe and concise:

```text
model returned vetoed candidate outside eligible_tickers and the row was dropped
```

Invalid veto action values and blank reasons remain hard contract errors. Those are not harmless candidate selection mistakes; they mean the row itself is malformed even after ticker sanitization.

Recommendation ticker validation remains fail-closed. If the model recommends an unknown ticker, raise `AiBriefProviderContractError`. Recommendations are executable output, so silent dropping could hide an unsafe action. The existing provider already drops some recommendation rows for invalid source refs, but ticker eligibility is the first authorization boundary and should stay hard.

Watch candidate ticker validation remains fail-closed for `watch_candidates[]` because the model is expected to summarize the exact watch-only input rows in order. The existing evaluator validates this contract, and watch output is not the cause of the 2026-06-24 failure.

## Quality Gate Behavior

Do not weaken the scheduled quality gate.

After invalid veto rows are dropped, the evaluator keeps these existing rules:

- `ERROR` system issues fail.
- Artifact schema mismatches fail.
- Eligible preselected candidates with no recommendations and no valid vetoes fail with `recommendation_report_empty`.
- Source-backed ratio requirements still apply to final recommendations.
- `WARN` source issues are visible but do not fail scheduled success by themselves when a valid source-backed recommendation report remains.

This means the exact 2026-06-24 output shape would still fail scheduled success if the model only returned an invalid veto and no valid recommendation. The difference is that the failure would be classified as an empty valid model judgment plus a warning diagnostic, not as a whole provider contract crash.

## Wrapper Alert Design

The wrapper should preserve scheduler stdout, inspect the final structured status, and send `scheduler_container_failed` only when the scheduler did not provide a recognized application status.

Implementation shape:

1. Capture scheduler stdout to a temporary file while still streaming it to launchd stdout.
2. If the Docker command exits zero, keep current behavior.
3. If it exits non-zero, read the last non-empty stdout line.
4. If the line is JSON with a `status` field that matches a known scheduler status, exit with the same failure code without sending host-failure.
5. If no structured status is found, send `scheduler_container_failed`.

The first implementation should recognize every status in `sab.scheduler.runner`'s `_FAILED_STATUSES` set:

```text
attempt_marker_failed
guard_failed
guard_failed_before_upload
guard_failed_before_notification
pipeline_failed
upload_failed
artifact_marker_failed
artifact_marker_invalid
entry_failure_artifact_claim_held
late_alert_send_failed
late_alert_sent_marker_failed
lock_lost_before_upload
skip_artifact_upload_failed
source_config_invalid
unsupported_runner_role
```

The wrapper should not import Python project code. Keep the status allowlist duplicated in the shell script, with a regression test that fails if the important `pipeline_failed` case regresses. This keeps the host preflight path simple and avoids starting Python just to classify a failure alert.

## Data Flow

```text
entry report
  -> classify recommendable/watch/excluded candidates
  -> source provider chain
  -> OpenAI schema built with request-local ticker enums
  -> OpenAI response
  -> provider normalization
      -> invalid veto rows dropped to WARN source_issues
      -> valid recommendations/vetoes/watch rows kept
  -> AI Brief artifact
  -> recommendation quality gate
      -> pass: upload, marker, notification reconciliation
      -> fail: pipeline_failed late-alert, no normal publish
  -> launchd wrapper
      -> structured app status: no scheduler_container_failed
      -> host/container failure without app status: host-failure alert
```

## Testing Plan

Provider tests:

- Request schema includes ticker enums for non-empty eligible/watch sets.
- Request schema uses `maxItems: 0` for empty role arrays.
- Unknown veto ticker is dropped and produces `model_ineligible_veto_dropped` WARN source issue.
- Watch ticker in `vetoed_candidates[]` is dropped and produces `model_watch_veto_dropped` WARN source issue.
- Blank veto ticker, invalid veto action, and blank veto reason remain hard contract errors.
- Unknown recommendation ticker still raises `AiBriefProviderContractError`.

AI Brief workflow tests:

- `run_ai_brief` with an unknown veto writes no `system_issues[]`, writes a WARN source issue, and writes no invalid veto row.
- If that leaves no recommendations and no valid vetoes for an eligible report, `evaluate_ai_brief_recommendation_report` returns `FAIL` with `recommendation_report_empty`.

Scheduler tests:

- A scheduled pipeline whose AI Brief artifact has only an invalid dropped veto still fails the quality gate before upload.
- A scheduled pipeline with a valid source-backed recommendation plus one invalid dropped veto can pass the quality gate.

Wrapper tests:

- `scripts/launchd/sab-ai-brief-wrapper.sh` does not send `scheduler_container_failed` when the scheduler command exits non-zero after printing `{"status": "pipeline_failed", "storage_key": null}`.
- The wrapper still sends `scheduler_container_failed` when the command exits non-zero without a parseable structured scheduler status.
- The wrapper still sends `docker_daemon_unavailable` when Docker preflight fails.

Documentation tests:

- Update `docs/operations.md` to explain `model_ineligible_veto_dropped`, `model_watch_veto_dropped`, and the wrapper status split.
- Update `docs/ARCHITECTURE.md` if implementation changes the scheduled AI Brief flow description.

## Rollout And Compatibility

- Historical AI Brief artifacts remain valid. No migration is required.
- The public AI Brief artifact shape remains unchanged.
- New WARN source issue codes may appear in reports and notifications wherever source/model diagnostics are already displayed.
- Scheduled success remains conservative. This design reduces false system issues and false host alerts, not quality requirements.

## Acceptance Criteria

- The OpenAI request schema constrains ticker fields to request-local role tickers.
- Invalid veto tickers no longer produce `model_provider_contract_error`.
- Invalid veto rows never appear in final `vetoed_candidates[]`.
- Invalid veto diagnostics are visible as WARN source issues.
- The 2026-06-24 failure class no longer creates a misleading `scheduler_container_failed` wrapper alert when the scheduler prints `pipeline_failed`.
- Actual host/container launch failures still produce host-failure alerts.
- Targeted Python and wrapper tests pass.
