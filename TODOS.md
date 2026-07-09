# TODOS

## Active

### Observe first KST scheduled Sell AI Brief generation run

**What:** Recover and inspect the first real launchd `com.mochafreddo.sab.sell-ai-brief.generation` success run after the 2026-07-08 `toss_freshness_missing` blocked result.

**Why:** `US after-close scheduled Sell AI Brief` should stay deferred until the KST morning runner has produced, quality-gated, uploaded, and notified a real artifact at least once.

**Context:** The 2026-07-07 smoke installed and loaded the LaunchAgent, verified dry-run/config/tests, restored the Toss freshness marker, and fixed the local sell-specific source chain config. A live run with the real portfolio was blocked by local external-data export policy, while a synthetic AAPL no-upload run verified the external source/OpenAI path. The first observed 2026-07-08 KST run correctly failed closed: Toss auto-sync returned `status=blocked incoming=5 create=2 update=0 delete=4 unchanged=3 blocked=4`, so Sell AI Brief generation returned `toss_freshness_missing` and sent only the blocked Telegram. Root cause 1 was scheduled Toss sync treating every missing holding as a destructive delete candidate and therefore not writing `toss-sync:success:MIXED:<session_date>`; PR #210 fixed that by preserving non-empty delete diffs as durable `broker_state=not_seen_in_toss` quarantine evidence. Root cause 2 was scheduled Sell AI Brief generation gating on Supabase Toss freshness while still reading local/config holdings; PR #211 fixed that by exporting the current Supabase active holdings snapshot and passing it to `sab sell --holdings`, and by making manual workflow exports reuse the same holdings exporter. Before closing this TODO, observe a real weekday 07:25 KST launchd tick that writes `toss-sync:success:MIXED:<session_date>` plus `scheduled-sell:success:MIXED:<session_date>` or a quality-gated review-required result. Check `logs/launchd/sell-ai-brief.generation.{out,err}.log`, `logs/launchd/toss-daily-auto-sync.out.log`, `toss-sync:success:MIXED:<session_date>`, and `scheduled-sell:*:MIXED:<session_date>`.

**Effort:** S
**Priority:** P1
**Depends on:** PR #210/#211 deployed; resolve any remaining Toss blocked rows; run `scripts/verify_scheduled_sell_runtime_state.py` against the target session; then observe the next weekday 07:25 KST launchd tick.

## Deferred

### Type runtime_state domain and payload boundaries

**What:** Split high-value `runtime_state` domains into typed tables/RPCs, or
add explicit `state_domain`/`state_kind` columns, CHECK constraints,
domain-specific writers, shared key builders, and contract tests for all
runtime_state writes.

**Why:** Scheduler markers, Toss freshness, dispatch locks, login throttling,
and caches currently share one untyped `state_key text primary key` plus JSONB
payload table. A wrong prefix, TTL, or payload shape can silently break
freshness, duplicate detection, run dispatch, or notification reconciliation.

**Context:** Product review `ARCH-003` found that `runtime_state` has become a
cross-domain coordination bus without typed boundaries. PR #210/#211 fixed the
immediate scheduled Toss/Sell freshness failure, but the broader coordination
surface still depends on string-key discipline and scattered payload contracts.

**Effort:** M-L
**Priority:** P2
**Depends on:** Stable first KST scheduled Sell AI Brief generation observation.

### Harden scheduled Sell AI Brief generation retry boundaries

**What:** Add continuous generation-lock renewal across long scheduled Sell AI
Brief runs and record intermediate upload markers so retries can recover after
a partial sell report upload or delegated delivery failure without duplicate or
ambiguous artifacts.

**Why:** Long KIS/model/source/delivery work can approach lock TTL boundaries,
and a retry after partial upload should not create a second sell report for the
same session.

**Context:** Reliability review found pre-existing generation resilience debt
outside the PR #210/#211 fix path: generation renews around phases rather than
continuously, and sell report upload does not have a separate recoverable marker
before delegated Sell AI Brief delivery finishes.

**Effort:** M
**Priority:** P2
**Depends on:** Stable first KST scheduled Sell AI Brief generation observation.

### Consolidate AI Brief provider shared helpers

**What:** Finish consolidating duplicated AI Brief provider helper logic across
the general AI Brief and Sell AI Brief provider paths.

**Why:** Provider parsing, validation, source-summary, and model-call helper
logic is only partially shared. Keeping parallel implementations raises the
chance that future provider behavior, validation, or telemetry fixes land in one
path but not the other.

**Context:** Code-quality review `CQ-001` found that the newer shared helpers
are not fully adopted by `sab/ai_brief_providers.py` and the sell-specific
provider path. This is not a PR #210/#211 release blocker, but it is worth
tracking before the provider surface grows again.

**Effort:** M
**Priority:** P3
**Depends on:** Stable Sell AI Brief V1 behavior and no active provider outage.

### Split scheduled AI Brief orchestration hotspots

**What:** Continue extracting focused components from the scheduled AI Brief and
scheduled Sell AI Brief orchestration runners, especially around phase
execution, marker reconciliation, upload/delivery handoff, and failure handling.

**Why:** Large orchestration runners make lock/marker/idempotency bugs harder to
review and increase the risk that future scheduling changes mix unrelated
concerns.

**Context:** Code-quality review `CQ-002` found that scheduled AI Brief
orchestration remains concentrated in large runner modules despite prior
incremental refactors. Keep this as deferred maintenance after the first KST
scheduled Sell AI Brief generation has proven stable.

**Effort:** M-L
**Priority:** P3
**Depends on:** Stable first KST scheduled Sell AI Brief generation observation.

### HOLD/watch explanations for Sell AI Brief V2

**What:** Decide whether `HOLD` rows should enter a V2 Sell AI Brief `hold_watch` or drilldown-only role.

**Why:** V1 keeps Telegram focused on `SELL`, `SELL_PARTIAL`, and `REVIEW`; later, operators may still want occasional explanations for why quiet holdings stayed quiet.

**Context:** The 2026-07-02 design deliberately excluded `HOLD` from model-reviewed judgments to keep the first Telegram useful and short. Revisit after account-readiness, stop/target override context, and source-backed sell judgments are stable enough to avoid turning every holding into noisy model commentary.

**Effort:** M
**Priority:** P3
**Depends on:** Manual Sell AI Brief V1 adoption and account/readiness context.

### US after-close scheduled Sell AI Brief

**What:** Add a separate US after-close scheduled Sell AI Brief generation window.

**Why:** The first scheduled sell automation should stay focused on the KST morning Toss-sync ritual; US after-close timing needs its own session policy, duplicate-notification handling, and operational window.

**Context:** The 2026-07-06 scheduled Sell AI Brief generation review chose to ship KST morning `MIXED` first and defer US after-close automation. Revisit after the local generation runner, freshness marker, lock renewal, quality-gate, upload, and Telegram idempotency behavior have run successfully in the morning workflow.

**Effort:** M
**Priority:** P3
**Depends on:** Stable KST morning scheduled Sell AI Brief generation.

### Align app-console typography with Evidence Ledger V1

**What:** Keep `Inter` as the V1 app-console font, alias display usage toward
body typography, and remove hero-scale display treatment from authenticated
console pages.

**Why:** The V1 design system prioritizes scan speed and trust over expressive
display typography, and `web/src/lib/__tests__/font-build-contract.test.ts`
currently locks the local font variable contract.

**Context:** The 2026-07-07 Evidence Ledger design review decided not to add a
new type pairing in V1. Future display typography can be revisited after the
light-first shell, Reports proof, and component vocabulary are stable.

**Effort:** S
**Priority:** P2
**Depends on:** App shell/token implementation slice for Evidence Ledger V1.

### Metrics mobile card density pass

**What:** Reduce the one-column stream of repeated metric cards on mobile after
the 2026-07-07 `/design-review`.

**Why:** Metrics preserves the correct task order, but the mobile view is still a
long sequence of similarly weighted cards. Operators need faster scanning of
run quality, coverage, fallback, and issue trends.

**Context:** The 2026-07-07 design review fixed higher-impact Reports/Holdings
mobile task ordering first. Revisit Metrics with grouping or denser chart
summaries rather than adding more decorative card chrome.

**Effort:** M
**Priority:** P3
**Depends on:** No dependency.

### Investigate web CSS preload warning

**What:** Investigate the repeated browser warning for an unused preloaded
Next.js CSS chunk in the local web UI.

**Why:** It did not block the 2026-07-07 design fixes, but preload warnings can
hide real performance regressions and make browser QA noisier.

**Context:** `/design-review` observed the same warning across Reports,
Holdings, Metrics, and Run after rebuilt local Docker verification. Treat this
as performance-polish unless it starts affecting load timing or visual flashes.

**Effort:** S
**Priority:** P3
**Depends on:** No dependency.

- 2026-06-20: Run a follow-up authenticated `/design-review` on the internal
  console pages after admin credentials or browser cookies are available. The
  2026-06-22 QA pass verified unauthenticated Next proxy redirects for reports,
  holdings, metrics, and run, but authenticated Supabase-backed page states
  still need visual audit with real credentials or browser auth state.
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

- 2026-07-09: Fixed scheduled Sell AI Brief generation so Toss freshness and
  sell input share the same Supabase source of truth. PR #211 exports the
  current Supabase active holdings snapshot to `data/scheduler/` before
  `sab sell`, fails closed instead of falling back to local `holdings.yaml`,
  makes manual sell/ai-brief workflows reuse the shared holdings exporter, and
  preserves broker quarantine evidence through web holdings YAML import/export.
- 2026-07-08: Reworked scheduled Toss auto-sync so non-empty delete diffs no longer block freshness or delete holdings. Missing broker rows are preserved with `broker_state=not_seen_in_toss`, first/last missing dates, count, and diff hash evidence; scheduled markers include quarantine counts; Sell reports emit those holdings as `REVIEW`; Sell AI Brief keeps them out of model-ranked candidates while preserving a `broker_state_review_candidates` audit list.
- 2026-07-08: Added repo-root `DESIGN.md` as the Evidence Ledger UI/interaction/visual source of truth, linked it from `docs/README.md`, and added the synthetic self-contained Reports proof mock at `docs/design/reports-evidence-ledger-proof.html`. The first implementation slice intentionally avoided `web/src/**`; app shell/tokens and Reports React refactors remain follow-up PRs.
- 2026-07-07: Documented scheduled Sell AI Brief source provider chain examples in `.env.example` and `docs/configuration.md`, and added regression checks so sell-specific US/MIXED chain examples stay aligned. This prevents local scheduler envs from configuring only `AI_BRIEF_SOURCE_PROVIDER_CHAIN_US` and leaving `sab sell-ai-brief` to resolve `none` for sell generation.
- 2026-07-07: Added `sab backtest` as a local historical OHLCV replay runner.
  It reuses the existing buy/sell signal evaluators over date-prefix candles,
  enters on the next available open after an enterable EOD buy signal, exits on
  sell evaluator actions, applies `SELL_PARTIAL` as a partial close, supports
  previous-prefix daily-OHLC stop/target path policies with gap-through open
  fills, position-size fractions, transaction costs/slippage, optional
  end-of-period force close, validated OHLCV issues, and writes
  `*.backtest.json` with trades, win rate, return, drawdown, holding-period,
  gross exposure, period/symbol, assumptions, and config snapshots for
  profitability and parameter-sensitivity research.
- 2026-07-06: Added scheduled Sell AI Brief generation behind the local generic wrapper with explicit `SAB_SELL_SCHEDULE_MODE=generation`, Toss freshness marker gating, sell/Sell AI Brief typed report helpers, quality-gated sell upload, delegated Sell AI Brief delivery, blocked-freshness notifications, and review-required handling for Sell AI Brief eval WARN.
- 2026-07-06: Completed marker-aware scheduled Sell AI Brief delivery for prebuilt `*.sell-ai-brief.json` artifacts via `sab sell-ai-brief-scheduled` and the launchd generic wrapper route when `SELL_AI_BRIEF_REPORT_PATH` is set, using `scheduled-sell:*` upload/index-before-notify markers and notification reconciliation. Manual `sell.yml` remains opt-in delivery only.
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
