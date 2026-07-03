# TODOS

## Active

## Deferred

### Scheduled Sell AI Brief delivery

**What:** Add marker-aware scheduled delivery for Sell AI Brief after the manual V1 is stable.

**Why:** Sell AI Brief Telegram delivery needs runtime_state/upload/notification markers before scheduled alerts are safe; the current scheduled sell workflow intentionally fails early until marker-aware local upload exists.

**Context:** The 2026-07-02 Sell AI Brief engineering review scoped V1 to manual `sab sell-ai-brief --sell-report ...` plus Telegram judgment. A production scheduled path should either repair `.github/workflows/sell.yml` with idempotent upload/notification markers or route Sell AI Brief through the local marker-aware scheduler pattern used by scheduled AI Brief. Duplicate sell alerts are worse than deferring scheduled delivery.

**Effort:** L
**Priority:** P2
**Depends on:** Manual Sell AI Brief V1 artifact, Telegram formatter, and upload/report_index support.

### HOLD/watch explanations for Sell AI Brief V2

**What:** Decide whether `HOLD` rows should enter a V2 Sell AI Brief `hold_watch` or drilldown-only role.

**Why:** V1 keeps Telegram focused on `SELL`, `SELL_PARTIAL`, and `REVIEW`; later, operators may still want occasional explanations for why quiet holdings stayed quiet.

**Context:** The 2026-07-02 design deliberately excluded `HOLD` from model-reviewed judgments to keep the first Telegram useful and short. Revisit after account-readiness, stop/target override context, and source-backed sell judgments are stable enough to avoid turning every holding into noisy model commentary.

**Effort:** M
**Priority:** P3
**Depends on:** Manual Sell AI Brief V1 adoption and account/readiness context.

- 2026-06-22: Design and implement a historical swing backtest runner for
  profitability and parameter-sensitivity research, covering data source,
  sample period, universe, benchmark/regime alignment, survivorship assumptions,
  EOD entry timing, stop/target approximation, transaction costs, slippage, and
  output metrics. The 2026-06-22 replay matrix intentionally covers
  deterministic rule semantics only.
- 2026-06-20: Run a follow-up authenticated `/design-review` on the internal
  console pages after admin credentials or browser cookies are available. The
  2026-06-22 QA pass verified unauthenticated Next proxy redirects for reports,
  holdings, metrics, and run, but authenticated Supabase-backed page states
  still need visual audit with real credentials or browser auth state.
- 2026-06-20: Plan a focused typography pass for the web UI. `Inter` remains
  the primary body font because `web/src/lib/__tests__/font-build-contract.test.ts`
  currently locks the existing local font variables; a future pass should pick a
  more distinctive operations-console type pairing and update that contract
  deliberately.
- 2026-06-19: Create a repo-wide `DESIGN.md` with `/design-consultation` after
  Toss holdings sync is implemented or as a separate design-system cleanup.
  The Toss Sync plan now documents the existing Holdings UI vocabulary locally,
  but future UI work should not need to rediscover panel, spacing, responsive,
  and state rules from code each time.
- 2026-06-19: Add redacted Toss holdings snapshot upload only after the first
  local-only Toss sync lands and real Toss fixture redaction tests prove that
  account identifiers, bearer tokens, and sensitive raw response fields cannot
  leak into Supabase Storage. First implementation keeps raw snapshots local and
  stores only redacted summary/hash metadata in runtime state.
- 2026-06-19: Add a Toss-powered account readiness layer after broker-backed
  holdings sync is stable, covering NAV, buying power, sellable quantity,
  stop-distance position sizing, exposure, and downside amount/portfolio-percent
  context. Keep this out of the first holdings sync PR to avoid mixing state sync
  with risk-budget decisions.
- 2026-06-09: Add stop-distance-based position sizing, including per-trade account risk, gross exposure, and currency-aware sizing. The 2026-06-18 swing-trader and investment reviews revalidated this as the top decision-readiness gap. Deferred while buy/portfolio state is manually maintained without Toss Securities API; revisit with an optional holdings/account-risk snapshot contract.

## Completed

- 2026-06-23: Normalized `sma_ema_hybrid` volume confirmation semantics so breakout, pullback, and reversal compare the signal candle to the preceding N-day average; added focused detector regressions and strategy documentation.
- 2026-06-23: Added env/YAML-conflict-bound `PORTFOLIO_MAX_NEW_ENTRIES_KR` and `PORTFOLIO_MAX_NEW_ENTRIES_US` overrides for `portfolio.max_new_entries_per_market.KR/US`, while documenting the safer `config.local.yaml` workflow when committed YAML already owns the caps. `portfolio.exposure_limits[]` remains YAML-only.
- 2026-06-22: Validated the `sma_ema_hybrid` quality `A` medium/long trend-filter question and kept the default unchanged. `quality_state=A` remains READY + positive relative strength + aligned risk rather than requiring SMA60/SMA200 by default; operators who want a stricter local stance should enable the existing `HYBRID_USE_SMA60_FILTER=true` hard filter, while SMA60/SMA200 default quality changes remain dependent on historical backtest/parameter-sensitivity evidence.
- 2026-06-22: Expanded deterministic scan replay coverage with case metadata and a KR/US swing-threshold matrix covering rising/sideways/falling regimes, high-volatility tight-stop warnings, strong/weak relative strength, gap rejection, market-regime blocking, and major hybrid patterns. This validates rule semantics and report regression behavior, not parameter profitability.
- 2026-06-22: Restored the Next.js 16 page auth gate through `web/src/proxy.ts`, keeping protected pages behind `/login?next=...` before render and adding regression coverage for unauthenticated `/reports` redirects.
- 2026-06-22: Cleaned up replay expected-artifact updater failures so invalid case paths exit with a concise stderr error instead of a full traceback, with subprocess regression coverage.
- 2026-06-21: Separated AI Brief candidate roles into `executable`, `blocked_but_valid`, `watch_only`, and `excluded`. Artifacts now keep legacy `recommendable_count` as the executable+blocked aggregate while adding role-specific counts/ticker arrays, provider recommendations preserve `candidate_role`/`entry_action`/`candidate_role_reason`, and Telegram/Slack/web copy shows execution-ready and blocked/manual-review candidates separately.
- 2026-06-21: Made stop/target reporting explicit as decision guidance rather than execution guarantees or account-loss limits. Buy/sell reports now emit `risk_disclosure`, scan/sell Telegram text and web report views show gap/slippage caveats, buy candidates emit structured `risk_stop_price_value`/`risk_target_price_value`, and entry rows emit `downside_risk` with amount plus portfolio percent/bps when position size and portfolio value are available.
- 2026-06-21: Added portfolio exposure controls beyond count-based entry caps. `portfolio.exposure_limits[]` now supports currency, sector, theme, beta bucket, correlation bucket, and tag bucket caps across existing active holdings plus newly accepted entry rows; entry reports emit `portfolio_exposure_buckets`, exposure cap blocks are counted in `summary.portfolio_blocked_by_exposure`, AI Brief preserves the buckets, web report detail shows an `Exposure` column, and docs describe the holdings tag-prefix convention.
- 2026-06-21: Added entry liquidity exit-capacity reporting tied to intended position size. Entry rows now emit `liquidity_exit_capacity` with ADV percent and normal/stressed exit-day estimates when position value and average traded value are available, preserve missing-size/liquidity plus small-cap/event-driven/crowded warnings in `liquidity_warnings`, remove the liquidity-unavailable readiness reason only when capacity is calculable, carry the fields through AI Brief provider input/final rows, and show them in the web report detail `Exit Capacity` column.
- 2026-06-21: Added entry report investment-readiness fields separate from technical `quality_state`. New entry rows now emit `implementation_ready=false`, `investment_readiness="CONTEXT_REQUIRED"`, and missing-context reasons for NAV/risk budget, liquidity exit capacity, portfolio exposure, and source/fundamental context; AI Brief provider input plus final recommendation/watch rows preserve those fields with manual-review caveats, web report detail shows readiness, and strategy/API/architecture docs clarify that `ENTER` and `quality_state=A` are technical setup labels rather than execution-ready account decisions.
- 2026-06-18: Added a `/favicon.ico` route for the local web UI, returning a cacheable SVG favicon so browser QA on `/login` no longer reports the missing favicon 404.
- 2026-06-18: Applied the remaining `sma_ema_hybrid` swing-trader review follow-ups: `sab entry` now requires `quality_state=A` for automatic hybrid `ENTER`, and hybrid sell supports pattern-specific time-stop overrides with a shorter default for `swing_high_breakout`.
- 2026-06-18: Added `SELL_PARTIAL` for `sma_ema_hybrid` low/high profit target tiers, including sell report ordering, Telegram notification inclusion/display, and strategy documentation, so profit tiers can now suggest partial exits instead of only tightening stops.
- 2026-06-18: Preserved buy `pattern` as holdings `entry_pattern` across Python YAML loading, Supabase holdings storage, scheduled export, web holdings create/edit/import/export, and recent buy candidate selection, so `sma_ema_hybrid` failed-breakout sell rules no longer depend on manual `strategy`/`tags` markers.
- 2026-06-09: Downgraded `sma_ema_hybrid` entry candidates with explicit non-`aligned` `risk_alignment` to `REVIEW`, so volatility/unknown-risk buy warnings cannot become automatic `ENTER` rows just because price, gap, and trigger checks pass.
- 2026-06-05: Added optional live integration smoke coverage via `scripts/live_integration_smoke.py` and `just live-integration-smoke`, so local refactors can intentionally verify real RSS/source API/KIS market-data service boundaries when credentials and network access are available.
- 2026-06-05: Consolidated AI Brief entry-report market resolution in `sab/ai_brief_eval_common.py`, sharing the `KR`/`US` override and `MIXED` error-message contract across AI Brief generation, source evaluation, recommendation evaluation, and live source comparison.
- 2026-06-05: Completed the deferred long high-risk runtime refactor pass for `sab/scheduler/runner.py`, `sab/signals/hybrid_sell.py`, and `sab/entry.py`, adding final test-first seams for scheduler runner-role fail-closed dispatch, entry per-candidate evaluation/report payload assembly, and hybrid sell exit/trend orchestration.
- 2026-06-05: Extracted entry portfolio-guard orchestration from `run_entry`, with characterization coverage for config-derived market caps, existing holdings exclusion, row mutation, and blocked-market summary counts.
- 2026-06-05: Extracted scheduled AI Brief entry-step execution from `DefaultScheduledPipeline.run`, with characterization coverage for PRE_OPEN entry inputs, `HOLDINGS_FILE` suppression, and the single entry-report artifact path contract.
- 2026-06-05: Extracted scheduled AI Brief holdings-export step from `DefaultScheduledPipeline.run`, with characterization coverage for scheduler holdings snapshot path construction and Supabase export config propagation.
- 2026-06-05: Extracted scheduled AI Brief scan-step execution from `DefaultScheduledPipeline.run`, with characterization coverage for KIS/both scan inputs, `HOLDINGS_FILE` suppression, and the single buy-report artifact path contract.
- 2026-06-05: Extracted scheduled AI Brief pre-notification guard failure handling from `ScheduledAiBriefRunner._reconcile_notification`, with characterization coverage for late-alert context, storage-key preservation, and guard-failure result contract.
- 2026-06-05: Extracted scheduled AI Brief uploaded-artifact marker handling from `ScheduledAiBriefRunner._run_locked_pipeline`, with characterization coverage for artifact marker failure preserving storage key, schedule/runner alert context, and main-lock release.
- 2026-06-05: Extracted scheduled AI Brief run-context resolution from `ScheduledAiBriefRunner.run`, with characterization coverage for request normalization, generated attempt IDs, guard/session snapshot propagation, and preflight-free helper behavior.
- 2026-06-05: Extracted entry evaluation policy resolution from `run_entry`, with characterization coverage for source-report strategy/gap-ATR snapshot precedence and missing-gap-guard enablement.
- 2026-06-05: Extracted scheduled AI Brief non-trading guard handling from `ScheduledAiBriefRunner.run`, with characterization coverage that pipeline roles persist guard-noop skip artifacts without attempting report-index repair.
- 2026-06-05: Extracted hybrid sell extended time-stop judgment from `_apply_time_stop_rules`, with characterization coverage for P&L-floor failure, weak-trend failure, unavailable-trend no-op, threshold no-op, existing SELL preservation, and public pipeline application after grace.
- 2026-06-04: Extracted entry buy-report loading, candidate validation, and market grouping context from `run_entry`, with characterization coverage for market override filtering while preserving source candidate order.
- 2026-06-04: Extracted entry report persistence/upload handling from `run_entry`, with characterization coverage for mixed-market artifact date selection, report path callback ordering, and fatal missing-price upload skip.
- 2026-06-04: Extracted entry market candidate evaluation from `run_entry`, with characterization coverage for mixed-market source ordering, provider issue de-duplication, and missing-price issue ordering.
- 2026-06-04: Extracted hybrid sell rule pipeline orchestration from `evaluate_sell_signals_hybrid`, with characterization coverage for reason ordering, output field propagation, time-stop metadata, and corporate-action flags.
- 2026-06-04: Extracted hybrid sell profit/exit rule orchestration from `evaluate_sell_signals_hybrid`, with characterization coverage for custom stop priority, peak-based profit protection reason ordering, and display target propagation.
- 2026-06-04: Extracted hybrid sell initial evaluation context preparation from `evaluate_sell_signals_hybrid`, with characterization coverage for eval-date parsing, future-entry review state, missing-indicator message ordering, corporate-action candidate detection, and P&L normalization.
- 2026-06-04: Extracted hybrid sell completed-candle context resolution from `evaluate_sell_signals_hybrid`, with characterization coverage for `choose_eval_index` metadata, completed-candle slicing, and finite OHLC extraction.
- 2026-06-04: Extracted hybrid sell failed-breakout handling from `evaluate_sell_signals_hybrid`, with characterization coverage for breakout SELL promotion, missing entry/P&L no-op paths, non-breakout no-op, and existing SELL reason preservation.
- 2026-06-04: Revalidated the latest archived review findings from `docs/reviews/2026/review-2026-03-08.md` and `docs/reviews/2026/review-2026-03-06.md` against current code/docs. The cited scan raw-reference batching, report artifact dates, run dispatch locking, report pagination, holdings ticker contract, finite candle sanitizer, US holiday refresh TTL, and login-throttle fail-mode findings are already addressed, so no new active TODO was promoted.
- 2026-06-04: Clarified historical review archive handling in `docs/reviews/README.md` and tightened the related deferred policy in `TODOS.md`; review artifacts stay immutable unless a specific finding is revalidated and promoted.
- 2026-06-04: Extracted hybrid sell hard-stop band handling from `evaluate_sell_signals_hybrid`, with characterization coverage for max-loss SELL promotion, hard-stop REVIEW preservation, SELL priority preservation, and stop-override/no-entry-price no-op paths.
- 2026-06-04: Extracted hybrid sell corporate-action guard handling from `evaluate_sell_signals_hybrid`, with characterization coverage for manual-review promotion, flag propagation, and reason ordering.
- 2026-06-04: Extracted scheduled AI Brief locked-pipeline failure handling from `ScheduledAiBriefRunner._run_locked_pipeline`, with characterization coverage for main-lock release, late-alert emission, status propagation, and storage-key preservation.
- 2026-06-04: Expanded workflow-specific GitHub Actions failure recovery steps in `docs/runbook.md`, covering scan/sell, AI Brief scheduled/manual, cleanup, CI/audit, and mise lock sync triage.
- 2026-06-04: Extracted hybrid sell trend breakdown handling from `evaluate_sell_signals_hybrid`, with characterization coverage for review reason ordering and SELL-priority momentum/RSI escalation.
- 2026-06-04: Extracted hybrid sell profit protection handling from `evaluate_sell_signals_hybrid`, with characterization coverage for peak-based stop tightening, high-target SELL promotion, and reason ordering.
- 2026-06-04: Extracted entry artifact date metadata and mixed eval-date issue collection from `run_entry`, with characterization coverage for single-market and mixed-market date context plus eval-date preview/message contracts.
- 2026-06-04: Extracted hybrid sell exit override handling from `evaluate_sell_signals_hybrid`, with characterization coverage for parsed stop/target override state, stop-triggered SELL promotion, display target priority, and reason ordering.
- 2026-06-04: Extracted scheduled AI Brief locked-pipeline upload precheck handling from `ScheduledAiBriefRunner._run_locked_pipeline`, with characterization coverage for lock renewal, pre-upload runtime guard skip artifact persistence, main-lock release, and late-alert emission.
- 2026-06-04: Extracted scheduled AI Brief notification claim handling from `ScheduledAiBriefRunner._reconcile_notification`, with characterization coverage for claim key, attempt-based owner token, schedule payload, and held claim result.
- 2026-06-04: Extracted scheduled AI Brief main-lock claim handling from `ScheduledAiBriefRunner.run`, with characterization coverage for lock key, attempt-based owner token, and claim payload.
- 2026-06-03: Documented production/remote Supabase recovery completion criteria in `docs/runbook.md`, covering migration/security, Storage, `report_index`, holdings, `runtime_state`, and user-facing verification.
- 2026-06-03: Extracted scheduled AI Brief artifact marker recording from the locked pipeline path, with characterization coverage for storage key, runner-origin, attempt, report-date, and run-url marker payload.
- 2026-06-03: Extracted the scheduled AI Brief main-lock pipeline/upload/notification path from `ScheduledAiBriefRunner.run`, with characterization coverage for completion, provider propagation, artifact marking, notification, and main-lock release.
- 2026-06-03: Extracted scheduled AI Brief runtime-guard skip result handling from `ScheduledAiBriefRunner.run`, with regression coverage for late-alert preservation when skip artifact upload fails.
- 2026-06-03: Extended `scripts/launchd/verify-sab-ai-brief.sh` with a shared-policy launchd timing drift check before bootstrap, backed by regression coverage for matching and intentionally drifted plist schedules.
- 2026-06-03: Consolidated scheduled AI Brief schedule policy in `sab/scheduler/schedule_policy.py` so runner windows, GitHub Actions schedule mapping, launchd plist timing, tests, and docs share one policy contract when cutoff/fallback times change.
- 2026-06-03: Clarified the scheduler regression test that intentionally keeps the stale `0926` cutoff tick to prove old cutoff candidates no-op during the GitHub fallback grace period.
- 2026-06-03: Added local `just workflow-audit` for GitHub Actions workflow validation via Docker `rhysd/actionlint:1.7.12`, so workflow edits can be checked without a globally installed `actionlint` binary.
- 2026-06-03: GitHub Actions `github-fallback` queue-delay policy decided as a bounded 4-minute role-window end grace, allowing queued fallback starts before 09:29 ET while keeping PRE_OPEN and runtime_state duplicate-report guards.
- 2026-06-03: Codex/local web checks now force the mise-pinned Node.js runtime through a shared `justfile` `web_tool_path` prefix. This avoids Codex Node native addon loading failures for `@rolldown/binding-darwin-arm64` and `@next/swc-darwin-arm64`.
- 2026-06-02: First test-first scheduler runner refactor step completed: pipeline attempt marker recording and existing/repaired artifact reconciliation split out of `ScheduledAiBriefRunner.run`.
- 2026-05-31: AI Brief source report validation/row normalization and source URL/DNS safety boundaries split out of `sab/ai_brief_sources.py` with offline/live URL-safety contracts preserved.
- 2026-05-31: AI Brief vendor source row normalizers split into `sab/ai_brief_source_normalizers.py` with source-provider regression coverage preserved.
- 2026-05-31: Runtime-guard-skipped scheduled AI Brief runs are persisted as separate `ai-brief-skip` Reports artifacts with Storage/`report_index` writes.
- 2026-05-23: AI Brief Phase 2 provider/eval suite completed.
  - KR scheduled source provider: `naver-news`
  - US scheduled source provider: `finnhub`
  - Decision note: `docs/ai-brief-us-source-provider-decision.md`
- 2026-05-22: Quiet Desk Assistant AI Brief state slice completed.
