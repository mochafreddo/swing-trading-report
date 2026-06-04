# TODOS

## Active

- None.

## Deferred

- 2026-06-02: Expand workflow-specific GitHub Actions failure recovery steps in
  `docs/runbook.md` when recurring failure modes are confirmed.
- 2026-06-02: Review historical `docs/reviews/2026/*` artifacts only if they are
  promoted from archived evidence to active maintenance docs.
- 2026-06-01: Refactor long high-risk runtime functions in small, test-first
  steps, starting with `sab/scheduler/runner.py`,
  `sab/signals/hybrid_sell.py`, and `sab/entry.py`.
- 2026-06-01: Consolidate duplicated market normalization rules after agreeing on
  a shared error-message contract for `KR`, `US`, and `MIXED` handling.
- 2026-06-01: Add an optional live smoke-check path for external RSS/API/market
  data integrations so local refactors can verify real service boundaries when
  credentials and network access are intentionally available.

## Completed

- 2026-06-04: Extracted scheduled AI Brief locked-pipeline upload precheck
  handling from `ScheduledAiBriefRunner._run_locked_pipeline`, with
  characterization coverage for lock renewal, pre-upload runtime guard skip
  artifact persistence, main-lock release, and late-alert emission.
- 2026-06-04: Extracted scheduled AI Brief notification claim handling from
  `ScheduledAiBriefRunner._reconcile_notification`, with characterization
  coverage for claim key, attempt-based owner token, schedule payload, and held
  claim result.
- 2026-06-04: Extracted scheduled AI Brief main-lock claim handling from
  `ScheduledAiBriefRunner.run`, with characterization coverage for lock key,
  attempt-based owner token, and claim payload.
- 2026-06-03: Documented production/remote Supabase recovery completion criteria
  in `docs/runbook.md`, covering migration/security, Storage, `report_index`,
  holdings, `runtime_state`, and user-facing verification.
- 2026-06-03: Extracted scheduled AI Brief artifact marker recording from the
  locked pipeline path, with characterization coverage for storage key,
  runner-origin, attempt, report-date, and run-url marker payload.
- 2026-06-03: Extracted the scheduled AI Brief main-lock pipeline/upload/
  notification path from `ScheduledAiBriefRunner.run`, with characterization
  coverage for completion, provider propagation, artifact marking, notification,
  and main-lock release.
- 2026-06-03: Extracted scheduled AI Brief runtime-guard skip result handling
  from `ScheduledAiBriefRunner.run`, with regression coverage for late-alert
  preservation when skip artifact upload fails.
- 2026-06-03: Extended `scripts/launchd/verify-sab-ai-brief.sh` with a
  shared-policy launchd timing drift check before bootstrap, backed by
  regression coverage for matching and intentionally drifted plist schedules.
- 2026-06-03: Consolidated scheduled AI Brief schedule policy in
  `sab/scheduler/schedule_policy.py` so runner windows, GitHub Actions schedule
  mapping, launchd plist timing, tests, and docs share one policy contract when
  cutoff/fallback times change.
- 2026-06-03: Clarified the scheduler regression test that intentionally keeps
  the stale `0926` cutoff tick to prove old cutoff candidates no-op during the
  GitHub fallback grace period.
- 2026-06-03: Added local `just workflow-audit` for GitHub Actions workflow
  validation via Docker `rhysd/actionlint:1.7.12`, so workflow edits can be
  checked without a globally installed `actionlint` binary.
- 2026-06-03: GitHub Actions `github-fallback` queue-delay policy decided as a
  bounded 4-minute role-window end grace, allowing queued fallback starts before
  09:29 ET while keeping PRE_OPEN and runtime_state duplicate-report guards.
- 2026-06-03: Codex/local web checks now force the mise-pinned Node.js runtime
  through a shared `justfile` `web_tool_path` prefix. This avoids Codex Node
  native addon loading failures for `@rolldown/binding-darwin-arm64` and
  `@next/swc-darwin-arm64`.
- 2026-06-02: First test-first scheduler runner refactor step completed:
  pipeline attempt marker recording and existing/repaired artifact reconciliation
  split out of `ScheduledAiBriefRunner.run`.
- 2026-05-31: AI Brief source report validation/row normalization and source URL/DNS safety boundaries split out of `sab/ai_brief_sources.py` with offline/live URL-safety contracts preserved.
- 2026-05-31: AI Brief vendor source row normalizers split into `sab/ai_brief_source_normalizers.py` with source-provider regression coverage preserved.
- 2026-05-31: Runtime-guard-skipped scheduled AI Brief runs are persisted as separate `ai-brief-skip` Reports artifacts with Storage/`report_index` writes.
- 2026-05-23: AI Brief Phase 2 provider/eval suite completed.
  - KR scheduled source provider: `naver-news`
  - US scheduled source provider: `finnhub`
  - Decision note: `docs/ai-brief-us-source-provider-decision.md`
- 2026-05-22: Quiet Desk Assistant AI Brief state slice completed.
