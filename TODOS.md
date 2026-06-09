# TODOS

## Active

- 2026-06-09: Swing-trader review follow-ups for the current
  `sma_ema_hybrid` strategy:
  - Gate or downgrade entries when `risk_alignment != aligned`; today the buy
    report warns on volatility wider than `sell.hybrid.stop_loss_pct_max`, but
    entry can still proceed if price/trigger checks pass.
  - Add stop-distance-based position sizing, including per-trade account risk,
    gross exposure, and currency-aware sizing; current portfolio guards cap
    count only (`max_active_holdings`, `max_new_entries_per_market`).
  - Preserve buy `pattern` into holdings/entry state so breakout-specific sell
    rules reliably identify failed breakout positions, not only holdings with
    manual `strategy`/`tags` markers.
  - Consider partial-exit actions such as `TRIM`/`SELL_PARTIAL`; current hybrid
    sell logic tightens protective stops at 5%/10% profit tiers but does not
    realize partial gains.
  - Use `quality_state` as an entry policy input, e.g. default `A -> ENTER`,
    `B -> REVIEW`, `C -> REVIEW/WATCH`, instead of letting all READY rows pass
    only on gap/trigger checks.
  - Revisit pattern-specific time stops; the current 30-session stop plus
    15-session grace may hold weak swing setups too long, especially failed
    breakouts.

## Deferred

- None.

## Completed

- 2026-06-05: Added optional live integration smoke coverage via
  `scripts/live_integration_smoke.py` and `just live-integration-smoke`, so
  local refactors can intentionally verify real RSS/source API/KIS market-data
  service boundaries when credentials and network access are available.
- 2026-06-05: Consolidated AI Brief entry-report market resolution in
  `sab/ai_brief_eval_common.py`, sharing the `KR`/`US` override and `MIXED`
  error-message contract across AI Brief generation, source evaluation,
  recommendation evaluation, and live source comparison.
- 2026-06-05: Completed the deferred long high-risk runtime refactor pass
  for `sab/scheduler/runner.py`, `sab/signals/hybrid_sell.py`, and
  `sab/entry.py`, adding final test-first seams for scheduler runner-role
  fail-closed dispatch, entry per-candidate evaluation/report payload assembly,
  and hybrid sell exit/trend orchestration.
- 2026-06-05: Extracted entry portfolio-guard orchestration from `run_entry`,
  with characterization coverage for config-derived market caps, existing
  holdings exclusion, row mutation, and blocked-market summary counts.
- 2026-06-05: Extracted scheduled AI Brief entry-step execution from
  `DefaultScheduledPipeline.run`, with characterization coverage for PRE_OPEN
  entry inputs, `HOLDINGS_FILE` suppression, and the single entry-report
  artifact path contract.
- 2026-06-05: Extracted scheduled AI Brief holdings-export step from
  `DefaultScheduledPipeline.run`, with characterization coverage for scheduler
  holdings snapshot path construction and Supabase export config propagation.
- 2026-06-05: Extracted scheduled AI Brief scan-step execution from
  `DefaultScheduledPipeline.run`, with characterization coverage for KIS/both
  scan inputs, `HOLDINGS_FILE` suppression, and the single buy-report artifact
  path contract.
- 2026-06-05: Extracted scheduled AI Brief pre-notification guard failure
  handling from `ScheduledAiBriefRunner._reconcile_notification`, with
  characterization coverage for late-alert context, storage-key preservation,
  and guard-failure result contract.
- 2026-06-05: Extracted scheduled AI Brief uploaded-artifact marker handling
  from `ScheduledAiBriefRunner._run_locked_pipeline`, with characterization
  coverage for artifact marker failure preserving storage key, schedule/runner
  alert context, and main-lock release.
- 2026-06-05: Extracted scheduled AI Brief run-context resolution from
  `ScheduledAiBriefRunner.run`, with characterization coverage for request
  normalization, generated attempt IDs, guard/session snapshot propagation,
  and preflight-free helper behavior.
- 2026-06-05: Extracted entry evaluation policy resolution from `run_entry`,
  with characterization coverage for source-report strategy/gap-ATR snapshot
  precedence and missing-gap-guard enablement.
- 2026-06-05: Extracted scheduled AI Brief non-trading guard handling from
  `ScheduledAiBriefRunner.run`, with characterization coverage that pipeline
  roles persist guard-noop skip artifacts without attempting report-index repair.
- 2026-06-05: Extracted hybrid sell extended time-stop judgment from
  `_apply_time_stop_rules`, with characterization coverage for P&L-floor
  failure, weak-trend failure, unavailable-trend no-op, threshold no-op,
  existing SELL preservation, and public pipeline application after grace.
- 2026-06-04: Extracted entry buy-report loading, candidate validation, and
  market grouping context from `run_entry`, with characterization coverage for
  market override filtering while preserving source candidate order.
- 2026-06-04: Extracted entry report persistence/upload handling from
  `run_entry`, with characterization coverage for mixed-market artifact date
  selection, report path callback ordering, and fatal missing-price upload skip.
- 2026-06-04: Extracted entry market candidate evaluation from `run_entry`,
  with characterization coverage for mixed-market source ordering, provider
  issue de-duplication, and missing-price issue ordering.
- 2026-06-04: Extracted hybrid sell rule pipeline orchestration from
  `evaluate_sell_signals_hybrid`, with characterization coverage for reason
  ordering, output field propagation, time-stop metadata, and corporate-action
  flags.
- 2026-06-04: Extracted hybrid sell profit/exit rule orchestration from
  `evaluate_sell_signals_hybrid`, with characterization coverage for custom
  stop priority, peak-based profit protection reason ordering, and display
  target propagation.
- 2026-06-04: Extracted hybrid sell initial evaluation context preparation from
  `evaluate_sell_signals_hybrid`, with characterization coverage for eval-date
  parsing, future-entry review state, missing-indicator message ordering,
  corporate-action candidate detection, and P&L normalization.
- 2026-06-04: Extracted hybrid sell completed-candle context resolution from
  `evaluate_sell_signals_hybrid`, with characterization coverage for
  `choose_eval_index` metadata, completed-candle slicing, and finite OHLC
  extraction.
- 2026-06-04: Extracted hybrid sell failed-breakout handling from
  `evaluate_sell_signals_hybrid`, with characterization coverage for breakout
  SELL promotion, missing entry/P&L no-op paths, non-breakout no-op, and
  existing SELL reason preservation.
- 2026-06-04: Revalidated the latest archived review findings from
  `docs/reviews/2026/review-2026-03-08.md` and
  `docs/reviews/2026/review-2026-03-06.md` against current code/docs. The
  cited scan raw-reference batching, report artifact dates, run dispatch
  locking, report pagination, holdings ticker contract, finite candle
  sanitizer, US holiday refresh TTL, and login-throttle fail-mode findings are
  already addressed, so no new active TODO was promoted.
- 2026-06-04: Clarified historical review archive handling in
  `docs/reviews/README.md` and tightened the related deferred policy in
  `TODOS.md`; review artifacts stay immutable unless a specific finding is
  revalidated and promoted.
- 2026-06-04: Extracted hybrid sell hard-stop band handling from
  `evaluate_sell_signals_hybrid`, with characterization coverage for max-loss
  SELL promotion, hard-stop REVIEW preservation, SELL priority preservation, and
  stop-override/no-entry-price no-op paths.
- 2026-06-04: Extracted hybrid sell corporate-action guard handling from
  `evaluate_sell_signals_hybrid`, with characterization coverage for
  manual-review promotion, flag propagation, and reason ordering.
- 2026-06-04: Extracted scheduled AI Brief locked-pipeline failure handling from
  `ScheduledAiBriefRunner._run_locked_pipeline`, with characterization coverage
  for main-lock release, late-alert emission, status propagation, and storage-key
  preservation.
- 2026-06-04: Expanded workflow-specific GitHub Actions failure recovery steps in
  `docs/runbook.md`, covering scan/sell, AI Brief scheduled/manual, cleanup,
  CI/audit, and mise lock sync triage.
- 2026-06-04: Extracted hybrid sell trend breakdown handling from
  `evaluate_sell_signals_hybrid`, with characterization coverage for review
  reason ordering and SELL-priority momentum/RSI escalation.
- 2026-06-04: Extracted hybrid sell profit protection handling from
  `evaluate_sell_signals_hybrid`, with characterization coverage for peak-based
  stop tightening, high-target SELL promotion, and reason ordering.
- 2026-06-04: Extracted entry artifact date metadata and mixed eval-date issue
  collection from `run_entry`, with characterization coverage for single-market
  and mixed-market date context plus eval-date preview/message contracts.
- 2026-06-04: Extracted hybrid sell exit override handling from
  `evaluate_sell_signals_hybrid`, with characterization coverage for parsed
  stop/target override state, stop-triggered SELL promotion, display target
  priority, and reason ordering.
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
