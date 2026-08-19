# API

상태: Accepted (API/인터페이스 가이드)

이 문서는 현재 코드 기준의 CLI 서브커맨드와 로컬 웹 API route 계약을 정리합니다. 웹 API는 로컬 관리자 콘솔 내부 API이며, 공개 외부 API로 안정성/호환성을 보장하지 않습니다.

## 문서 상태

### 현재 제공

- `sab` CLI subcommand, 주요 option, 산출물 계약을 제공합니다.
- Next.js `web/src/app/api/**/route.ts` 기준 웹 API route, 인증 경계, 요청/응답 형태를 제공합니다.

### 실험

- OpenAPI/Swagger 문서는 아직 없습니다.
- 웹 API contract 자동 생성은 구현되어 있지 않습니다.

### 백로그

- `web/src/lib/schemas.ts`에서 API 요청 schema 표를 자동 생성하는 문서화 스크립트.
- standalone `entry` workflow dispatch API.

### 폐기 후보

- 인증 없이 Storage object를 직접 list/download하는 초기 웹 API 가정은 현재 계약이 아닙니다.

## Authentication Boundary

| Surface | Auth | Notes |
| --- | --- | --- |
| CLI `sab` | local environment credentials | `.env`/GitHub Secrets/Docker env에서 KIS, Supabase, provider secret을 읽습니다. |
| Web pages | admin session cookie + Next proxy redirect | `/login`에서 `SAB_BASIC_AUTH_USER/PASS`로 로그인합니다. 보호 page는 `web/src/proxy.ts`에서 렌더링 전에 `/login?next=...`로 리다이렉트합니다. |
| Web APIs | admin session + same-origin/local request guard | `/api/auth/login`과 `/api/auth/logout`를 제외한 API route는 `enforceAdminApiGuard`를 사용합니다. |
| GitHub workflow dispatch | server-side `GITHUB_PAT` | `RUN_DISPATCH_ENABLED=1`일 때만 `/api/run`이 dispatch합니다. |

`/login` page는 liveness 확인용으로 비인증 접근이 가능하지만, 보호 API의 정상 여부를 의미하지 않습니다. 보호 page auth gate는 `/reports`, `/holdings`, `/metrics`, `/run`이 비인증 상태에서 `307` redirect를 반환하는지로 smoke합니다.

## CLI Interface

```bash
UV_CACHE_DIR=.uv-cache uv run python -m sab <command> [options]
```

| Command | Purpose | Key Options | Output |
| --- | --- | --- | --- |
| `scan` | watchlist/screener universe를 평가해 buy report 생성 | `--limit`, `--watchlist`, `--provider kis|pykrx`, `--screener-limit`, `--universe watchlist|screener|both`, `--markets KR,US` | `reports/YYYY-MM-DD(-n).buy.json` |
| `sell` | active holdings 평가 후 sell report 생성 | `--provider kis|pykrx`, `--holdings <path>` | `reports/YYYY-MM-DD(-n).sell.json` |
| `entry` | buy report 후보의 다음 세션 진입 조건 평가 | `--buy-report`, `--provider kis|pykrx`, `--mode PRE_OPEN|INTRADAY|AFTER_CLOSE`, `--market KR|US`, `--upload` | `reports/YYYY-MM-DD(-n).entry.json` |
| `backtest` | 로컬 historical OHLCV JSON을 기존 buy/sell signal evaluator로 prefix replay해 거래/성과 report 생성 | `--data-file`, `--tickers`, `--start-date`, `--end-date`, `--strategy-mode ema_cross|sma_ema_hybrid`, `--sell-mode generic|sma_ema_hybrid`, `--report-dir`, `--transaction-cost-bps`, `--slippage-bps`, `--position-size-pct`, `--partial-exit-fraction`, `--intraday-exit-policy none|conservative|stop_first|target_first`, `--assumptions-file`, `--no-close-open-at-end` | `reports/YYYY-MM-DD(-n).backtest.json` |
| `ai-brief` | entry report의 executable/blocked/watch 후보를 AI brief로 요약 | `--entry-report`, `--market`, `--buy-report`, `--model-provider fake|openai`, `--model-name`, `--model-timeout-seconds`, `--source-provider`, `--source-report`, `--source-api-url`, `--source-timeout-seconds`, `--article-reader none|lightpanda`, `--article-reader-max-urls`, `--article-reader-timeout-seconds`, `--article-reader-max-excerpt-chars`, `--upload`, `--report-date` | `reports/YYYY-MM-DD(-n).ai-brief.json` |
| `sell-ai-brief` | sell report의 SELL/SELL_PARTIAL/REVIEW 후보를 AI 판단/이유와 최신 source context로 요약 | `--sell-report`, `--model-provider fake|openai`, `--model-name`, `--model-timeout-seconds`, `--source-provider`, `--source-report`, `--source-api-url`, `--source-timeout-seconds`, `--article-reader none|lightpanda`, `--article-reader-max-urls`, `--article-reader-timeout-seconds`, `--article-reader-max-excerpt-chars`, `--upload`, `--report-date` | `reports/YYYY-MM-DD(-n).sell-ai-brief.json` |
| `ai-brief-scheduled` | runtime_state guard와 marker를 사용하는 scheduled runner | `--market`, `--schedule-role`, `--runner-role`, `--scheduled-tick`, `--attempt-id`, `--run-url`, `--source-provider`, `--model-provider`, `--dry-run`, `--guard-only` | `ai-brief` 또는 `ai-brief-skip` report, runtime_state marker |
| `sell-ai-brief-generate-scheduled` | Toss freshness marker를 확인한 뒤 sell report와 Sell AI Brief를 생성, 품질 평가, 업로드, 전달 | `--scope MIXED`, `--session-date`, `--runner-role`, `--scheduled-tick`, `--attempt-id`, `--run-url`, `--provider`, `--model-provider`, `--model-name`, `--dry-run` | stdout status JSON, sell/Sell AI Brief reports, `scheduled-sell:*` runtime_state marker |
| `sell-ai-brief-scheduled` | 기존 Sell AI Brief artifact를 validation + upload/index + notify 순서로 전달/재조정 | `--sell-ai-brief-report`, `--scope KR|US|MIXED`, `--session-date`, `--runner-role`, `--scheduled-tick`, `--attempt-id`, `--run-url`, `--dry-run` | stdout status JSON, `scheduled-sell:*` runtime_state marker, optional Storage/report_index delivery |
| `ai-brief-latency-probe` | AI Brief primary/fallback 모델 호출 수와 반복 횟수 계획을 확인 | `--primary-model`, `--fallback-model`, `--repetitions 1..3` | stdout `planned_live_model_call_count=<n>`; upload/notification 없음 |
| `decision-board` | local notification-free Decision Board shadow seam | `--run-kind`, `--run-id`, `--idempotency-key`, `--created-at`, `--sealed-input-hash`, `--upload-mode`, `--report-dir` | production adapter 미연결 기본 상태에서는 `CONFIG_UNAVAILABLE`, exit 2 |
| `decision-board-shadow-live` | explicit credentialed Decision Board live-shadow adapter | `decision-board` + required manifest/hash/input-ledger/expected-action-ledger bundle | user approval signature, slot/runtime/ledger/sealed snapshot hash·item membership이 다르면 `PREPARATION_INVALID`; snapshot/provider config가 없으면 `CONFIG_UNAVAILABLE`; 검증된 manifest hash는 report metadata에 기록; schedule/notification 없음 |
| `decision-board-shadow-gate-validate` | frozen 20-session gate manifest 검증 | `--manifest`, `--require-approved`, approved validation 시 `--input-ledger`, `--expected-action-ledger` | sanitized proposal/approved summary와 canonical hash; invalid/approval pending은 exit 2 |
| `decision-board-shadow-case-prepare` | owner-only case spec에서 canonical sealed snapshot과 private case-plan 생성 | `--manifest`, owner-only absolute `--case-spec`, 새 absolute `--output-dir` | mode `0600` 파일과 sanitized hash/count만 생성; upload/approval signature/network/schedule 없음 |
| `decision-board-shadow-ledger-prepare` | redacted case-plan에서 private canonical ledger 두 개 생성 | `--manifest`, owner-only absolute `--case-plan`, 새 absolute `--output-dir` | mode `0600` ledger와 sanitized hash/count만 생성; approval signature/network/schedule 없음 |
| `decision-board-journal-status` | bounded sanitized RunJournal 조회 | `--journal-dir`, `--status`, `--limit`, `--scan-limit`, `--max-record-bytes`, `--max-output-bytes` | public journal status JSON |
| `decision-board-journal-reconcile` | missed/stale local slot 기록 | `--journal-dir`, `--run-kind`, `--expected-at`, `--run-id`, `--now`, `--grace-seconds`, `--stale-seconds` | reconciled public journal JSON |
| `decision-board-journal-run` | one-shot runner를 local journal로 감싸기 | journal identity/policy, manifest/hash/input-ledger/expected-action-ledger bundle, `--dry-run`, `-- <runner argv>` | bound manifest hash/slot/runtime/ledger/input 검증 뒤 STARTED/terminal journal observation |

`scripts/launchd/build_decision_board_shadow_dry_run_package.py`는 validated gate manifest의 한
session을 ENTRY/HOLDING disabled plist 두 개로 렌더링합니다. `--session`, absolute
`--journal-dir`, 새 `--output-dir`가 필요하며 생성물에는 schedule/auto-start가 없습니다.

## Report Artifacts

| Report Type | Local Pattern | Supabase Storage Pattern | Index Source |
| --- | --- | --- | --- |
| `buy` | `reports/YYYY-MM-DD(-n).buy.json` | `YYYY/MM/YYYY-MM-DD(-n).buy.json` | `report_index` |
| `sell` | `reports/YYYY-MM-DD(-n).sell.json` | `YYYY/MM/YYYY-MM-DD(-n).sell.json` | `report_index` |
| `entry` | `reports/YYYY-MM-DD(-n).entry.json` | `YYYY/MM/YYYY-MM-DD(-n).entry.json` | `report_index` |
| `backtest` | `reports/YYYY-MM-DD(-n).backtest.json` | local-only | local file |
| `ai-brief` | `reports/YYYY-MM-DD(-n).ai-brief.json` | `YYYY/MM/YYYY-MM-DD(-n).ai-brief.json` | `report_index` |
| `ai-brief-skip` | `reports/YYYY-MM-DD(-n).ai-brief-skip.json` | `YYYY/MM/YYYY-MM-DD(-n).ai-brief-skip.json` | `report_index` |
| `sell-ai-brief` | `reports/YYYY-MM-DD(-n).sell-ai-brief.json` | `YYYY/MM/YYYY-MM-DD(-n).sell-ai-brief.json` | `report_index` |
| `decision-board` | `reports/YYYY-MM-DD.decision-board.{entry|holding}.<run_id>.<64hex>.json` | `YYYY/MM/<local filename>` | `report_index` with exact run identity |

### Buy/Sell Risk Disclosure Notes

- New `buy` and `sell` artifacts include top-level `risk_disclosure`. The payload marks stop/target-related fields as `meaning="decision_guide_only"`, with `execution_caveat="gap_slippage_may_exceed_guide"` and `account_loss_caveat="not_account_loss_limit"`.
- Buy candidates expose structured stop/target guide values as `risk_stop_price_value`, `risk_target_price_value`, `risk_price_basis="adjusted"`, and `risk_guide_meaning="decision_guide_only"`. These fields are calculation aids and do not change the legacy display string `risk_guide`.
- Sell reports keep row-level `stop_price` and `target_price` as guide values. Overrides still determine those guide prices when present.

### Entry Artifact Notes

- New `entry.entries[]` rows include `implementation_ready=false`, `investment_readiness="CONTEXT_REQUIRED"`, and `investment_readiness_reasons[]`. `action=ENTER` and hybrid `quality_state=A` remain technical setup labels until NAV/risk budget, intended-size liquidity/exit capacity, portfolio exposure, and source/fundamental context are checked by a separate layer.
- `entry.entries[].liquidity_exit_capacity` records intended-size exit capacity when source candidate data is available. With `status="available"`, it includes position value, average traded value, ADV percent, normal/stressed participation rates, and normal/stressed estimated exit days. Missing intended size or liquidity data leaves an explicit unavailable status and keeps `liquidity_exit_capacity_unavailable` in readiness reasons.
- `entry.entries[].liquidity_warnings[]` preserves missing-size/liquidity warnings plus small-cap, event-driven, and crowded-name exit-risk flags when source candidates provide those flags. The reports UI shows these fields in the entry table's `Exit Capacity` column.
- `entry.entries[].downside_risk` records guide-based downside when source candidate stop guidance and intended position value are available. With `status="available"`, it includes entry price, stop price, optional target price, position loss amount/percent, optional portfolio value/loss percent/bps, and caveat `stop_target_decision_guide_only_gap_slippage_may_exceed`. When the source guide basis is `adjusted`, entry converts stop/target values to raw entry-price basis before calculating this payload.
- `entry.entries[].portfolio_exposure_buckets[]` records normalized exposure buckets such as `currency=USD`, `sector=semiconductor`, or `theme=ai-megacap`. Configured `portfolio.exposure_limits[]` can turn an otherwise technical `ENTER` row into `SKIP` with a `portfolio exposure cap reached (...)` reason; `entry.summary.portfolio_blocked_by_exposure` counts those blocks.
- AI Brief model input and final recommendation/watch rows preserve those readiness fields when they are present in the source entry report. Recommendations with context-required readiness also carry an explicit rationale/checklist caveat.
- AI Brief also preserves `liquidity_exit_capacity`, `liquidity_warnings`, `downside_risk`, and `portfolio_exposure_buckets` from entry rows into provider input and final recommendation/watch rows.

### Backtest Artifact Notes

- `backtest` artifacts are local-only research outputs. They are not uploaded to Supabase Storage or indexed in `report_index`.
- Input data is a local JSON file containing either a ticker-to-candle mapping, `{ "symbols": { ... } }`, `{ "candles": [...] }` with one `--tickers` value, or a row list with one `--tickers` value. Candle rows use the normal daily OHLCV fields. The runner records row-level `issues[]` for invalid dates, duplicate dates, non-positive OHLC values, and invalid OHLC ranges, and it rejects malformed period bounds instead of silently widening the period.
- The runner replays each ticker by passing historical candle prefixes into the existing buy evaluator selected by `--strategy-mode` and sell evaluator selected by `--sell-mode`.
- Entry execution is next available candle open after an enterable EOD buy signal. Hybrid buy candidates must be `entry_state=READY`; when `quality_state` is present, `sma_ema_hybrid` requires `quality_state=A`.
- Exit execution uses the sell evaluator's signal-day close for `SELL`. `SELL_PARTIAL` closes `--partial-exit-fraction` of the remaining position and keeps the rest open.
- `--intraday-exit-policy` controls daily-OHLC stop/target approximation when the previous completed sell-evaluator prefix returns `stop_price`/`target_price`; this avoids applying same-day trailing guide changes to earlier same-day lows. `conservative` and `stop_first` choose stop before target when both are touched in one candle; `target_first` chooses target first; `none` disables intraday path approximation. Gap-through stop/target hits fill at the candle open.
- `--position-size-pct` records the account-equity fraction allocated to each new position and weights `summary.total_return_pct` by closed quantity. `summary.return_model=non_compounded_initial_equity_contribution` means this is a closed-lot contribution metric, not a compounded portfolio NAV series. `summary.max_gross_exposure_pct` reports the maximum simultaneous marked exposure. `--transaction-cost-bps` subtracts bps per side from closed-lot return, and `--slippage-bps` moves entry up and exit down. Open positions are force-closed at the period end by default; `--no-close-open-at-end` leaves them as `status=open`.
- `equity_curve` is ordered by date and includes conservative low-price mark-to-market events for open positions so `summary.max_drawdown_pct` captures intratrade drawdown, not only drawdown observed at trade close.
- `--assumptions-file` is an optional JSON object copied into `assumptions`. Use it to record data vendor, point-in-time universe, benchmark, survivorship policy, corporate-action adjustment policy, and other research inputs that the local runner cannot infer from OHLCV alone.
- Reports include `period`, `symbols`, `trades`, `summary.win_rate`, `summary.total_return_pct`, `summary.max_drawdown_pct`, holding-period fields, `equity_curve`, `assumptions`, `issues`, and `config_snapshot`.

### AI Brief Artifact Notes

- `ai-brief.summary` includes `entry_count`, `recommendable_count`, `executable_count`, `blocked_but_valid_count`, `watch_count`, `preselected_count`, `recommendation_count`, `excluded_count`, `vetoed_count`, `cap_excluded_count`, `source_issue_count`, and `system_issue_count`.
- `executable_tickers[]` records source entry rows whose original action was `ENTER`. `blocked_but_valid_tickers[]` records technically valid model candidates whose original action was portfolio-blocked `SKIP` or tight-stop/risk-review `REVIEW`. Their counts add up to `recommendable_count`.
- `eligible_tickers[]` is the preselected model-input ticker list after the 5-candidate cap across executable plus blocked-but-valid candidates. `watch_tickers[]` is tracked separately and never contributes to recommendation rank.
- `recommendations[]` is capped at 3 rows. Its `rank` values must match the displayed array order as contiguous `1..N`, and recommendation text must avoid automated order/execution language. Recommendation rows preserve `candidate_role`, `entry_action`, and `candidate_role_reason` so model `action=ENTER` does not hide an original `SKIP` or `REVIEW` entry action.
- `watch_candidates[]` records watch-only candidates with `action=WATCH`, manual reason, retrigger conditions, and optional source rows. It is displayed separately from `recommendations[]`.
- `vetoed_candidates[]` records `eligible_tickers[]` candidates that the model did not recommend. It is displayed separately from `recommendations[]` in notifications and the web report detail view.
- `source_provider_summary` records the configured source chain, provider-level `status|covered|total`, and final model-candidate/watch coverage. A chain of `none` has no provider rows and zero final coverage.
- When the article reader is enabled, recommendation/watch source rows may include `article_read`. Valid statuses are `not_attempted`, `metadata_only`, `accessed`, `verified`, `blocked`, and `failed`. Valid tiers are `metadata_backed`, `article_accessed`, and `article_verified`.
- `ai-brief.summary` then also includes `article_read_attempted_count`, `article_accessed_count`, `article_verified_count`, and `article_read_issue_count`. `not_attempted` rows are not counted as attempts. `blocked`/`failed` rows use `metadata_backed`, include `issue_code`, and appear in `source_issues[]`.
- `lightpanda` navigation-failure markdown such as `# Navigation failed` is treated as `failed`/`article_reader_failed`, not as article content. The reader records bounded excerpts only and does not bypass paywalls, CAPTCHA, login, robots/bot blocks, or access controls.
- OpenAI model output uses request-local `source_refs` internally, but final artifacts keep canonical `sources[]` objects. `model_source_ref_invalid`, `model_source_ref_missing`, `model_unbacked_recommendation_dropped`, and `model_watch_source_ref_invalid` may appear in `source_issues[]` when local normalization isolates a candidate-level source-ref problem. `model_ineligible_veto_dropped` and `model_watch_veto_dropped` may appear when a model returns an invalid `vetoed_candidates[]` row outside the eligible veto universe; the row is dropped and does not count toward `vetoed_count`.
- `model_trace` records model provenance for feedback and replay: `model_trace_id`, prompt/output schema versions, `request_hash`, `source_catalog_hash`, `request_status`, provider/model, artifact context, candidate summaries, source counts, and model attempt IDs. Recommendation, veto, and watch rows include `model_trace_id` plus either `candidate_id` or `candidate_ids`; `candidate_ids` is used when duplicate same-ticker candidates make a model output ambiguous. Candidate summaries preserve the model-output status and request-local source refs that were available to the model. Invalid source-ref issues preserve the returned `source_refs` and, when applicable, `invalid_source_refs`.
- `brief_state` is one of `NO_SIGNAL`, `NEEDS_REVIEW_WATCH_ONLY`, `FINAL_JUDGMENT`, or `NEEDS_REVIEW_WEAK_NEWS`. `NO_SIGNAL` means no executable/blocked or watch candidates; `NEEDS_REVIEW_WATCH_ONLY` means only trigger-pending watch candidates remain.
- `scripts/eval_ai_brief_recommendations.py` is the offline recommendation quality gate. The manual GitHub AI Brief workflow and scheduled runner treat `FAIL` as a stop before normal notification/success handling.

### Sell AI Brief Artifact Notes

- `sell-ai-brief.summary` includes `evaluated_count`, `actionable_count`, `preselected_count`, `judgment_count`, `broker_state_review_count`, `excluded_hold_count`, `unsupported_action_count`, `vetoed_count`, `cap_excluded_count`, `source_issue_count`, and `system_issue_count`.
- `actionable_tickers[]` records source sell rows whose original action was `SELL`, `SELL_PARTIAL`, or non-broker-state `REVIEW`. `HOLD` rows are preserved only in `excluded_hold_candidates[]`. Rows with `broker_state=not_seen_in_toss` are preserved in `broker_state_review_candidates[]` with their missing-broker evidence and are excluded from model ranking.
- `judgments[]` is capped by the 5-row model input cap and must preserve the source `sell_action`. The model may explain, defer, or veto a candidate, but it may not add tickers, convert `HOLD` rows, or change the deterministic sell action.
- `source_provider_summary`, source row freshness/URL validation, optional `article_read`, and OpenAI request-local `source_refs` follow the same source safety boundary used by AI Brief.
- `brief_state` is one of `NO_ACTION`, `FINAL_JUDGMENT`, `NEEDS_REVIEW_WEAK_NEWS`, or `MODEL_OR_SYSTEM_ISSUE`. `NO_ACTION` means there were no actionable sell rows, so no model call is attempted.
- `scripts/eval_sell_ai_brief.py` is the offline quality gate for this artifact. It checks source sell alignment, broker-state review exclusion, HOLD exclusion, unsupported/cap rows, summary counts, source-backed ratio, action preservation, and automated-order language.
- Manual `.github/workflows/sell.yml` keeps this gate in front of force upload and Telegram delivery. `send_sell_ai_brief_notifications=true` is still an opt-in manual delivery input, not a scheduled trigger.

### Scheduled Sell AI Brief Generation And Delivery Notes

- `sell-ai-brief-generate-scheduled` is the scheduled generation path. It is currently `MIXED` only and requires a matching `toss-sync:success:MIXED:<sessionDate>` marker with status `applied` or `unchanged`; otherwise it writes blocked markers, sends only the freshness-blocked notification, and exits non-zero.
- Generation claims a `scheduled-sell:generation-lock:*` lock, exports the current Supabase active holdings snapshot to `data/scheduler/holdings.MIXED.<sessionDate>.yaml`, runs `sab sell --holdings <snapshot>` with report upload suppressed, runs `sab sell-ai-brief`, evaluates the artifact with `scripts/eval_sell_ai_brief.py`, uploads the sell report only after non-`FAIL` quality, then delegates Sell AI Brief upload/Telegram reconciliation to the delivery runner, which uses its own `scheduled-sell:lock:*`.
- Generation statuses include `dry_run`, `success_marker_skip`, `toss_freshness_missing`, `toss_freshness_stale`, `toss_freshness_invalid`, `lock_held_skip`, `lock_lost_before_upload`, `sell_report_failed`, `sell_ai_brief_failed`, `quality_gate_failed`, `upload_failed`, delegated delivery failure statuses, delegated existing-delivery statuses such as `notification_reconciled` and `completion_repaired`, `delivery_failed`, `delivery_lock_held`, `completed`, and `completed_review_required`.
- A quality `WARN` can complete delivery but records `scheduled-sell:review-required:*` and returns `completed_review_required`; a quality `FAIL` blocks upload and normal Telegram delivery.
- `sell-ai-brief-scheduled` consumes an existing `*.sell-ai-brief.json` artifact. It does not build a sell report and it does not run `sell-ai-brief` generation.
- The runner validates the local or downloaded artifact with `validate_sell_ai_brief_artifact(...)`, then uploads it to Supabase Storage and upserts `report_index`, and only then attempts Telegram delivery.
- Runtime coordination uses `scheduled-sell:*` markers: `blocked`, `blocked-notification-lock`, `notification:blocked-sent`, `generation-lock`, `generation`, `review-required`, plus delivery `attempt`, `lock`, `artifact`, `notification:claim`, `notification:sent`, and `success`.
- If `success` already exists, the command returns a skip status. If `artifact` exists without `success`, the command reconciles notification from the uploaded storage object instead of re-uploading a second artifact.
- `sell-ai-brief-generate-scheduled` exits non-zero for freshness failures, generation/evaluation/upload failures, and delegated delivery failures. Dry-run, lock-held skip, existing delivery completion, and `completed`/`completed_review_required` outcomes stay zero.
- `sell-ai-brief-scheduled` delivery exits non-zero only for `artifact_invalid`, `artifact_marker_invalid`, `lock_lost_before_upload`, `notification_sent_marker_invalid`, `notification_sent_marker_failed`, and `upload_failed`. Skip/reconciliation outcomes stay zero to preserve idempotent scheduler retries.

### Notification Text Contracts

- AI Brief and Sell AI Brief Telegram report notifications use Telegram HTML rich text. The body is decision-first, Korean-first for operator-facing explanation text, and uses only `<b>`, `<code>`, and `<a>` tags. Source article titles, tickers, enum values, issue codes, URLs, and storage keys remain original/untranslated.
- Report-derived values are HTML-escaped, normalized to single-line text where needed, and length-bounded before rendering. Unsafe, malformed, too-long, or whitespace/control-character HTTP(S) `run_url` values are not emitted as Telegram links.
- GitHub Actions and the scheduled notifier split the AI Brief Telegram report body with `split_telegram_message_text()` and send each part through `sendMessage` with `parse_mode=HTML` and web previews disabled. Sell AI Brief uses the same Telegram-safe renderer contract when its artifact is notified.
- AI Brief skipped notifications, scan/sell Telegram notifications, host late alerts, and Slack summaries remain plain text. Scan/sell Telegram notifications append the same stop/target decision-guide caveat used in report artifacts when rows are shown. Slack keeps the key-value summary format.

## Web API Routes

| Method | Path | Purpose | Request Contract | Response/Status |
| --- | --- | --- | --- | --- |
| `POST` | `/api/auth/login` | 관리자 로그인 | JSON `{ "username": string, "password": string }` | `200 { "ok": true }`, sets HttpOnly session cookie |
| `POST` | `/api/auth/logout` | 관리자 로그아웃 | no body required | `200 { "ok": true }`, clears session cookie |
| `GET` | `/api/reports` | report_index 목록 조회 | query `type=all|buy|sell|entry|ai-brief|ai-brief-skip|sell-ai-brief|decision-board`; Decision Board는 exact `runKind=ENTRY|HOLDING`; `q`, `limit=1..200`, `refresh=true|false` | `ReportsListResponse` |
| `GET` | `/api/reports/detail` | Storage JSON 상세 조회 | query `key=<storage-key>`, `refresh=true|false`; Decision Board는 exact bytes/schema/hash/key/public projection 검증 | report JSON 또는 sanitized 422 |
| `GET` | `/api/reports/decision-board-journal` | optional local RunJournal warning projection | no body; fixed-argv bounded helper | public missed/stale envelope 또는 safe unavailable |
| `POST` | `/api/run` | `scan.yml`/`sell.yml` workflow_dispatch | scan: `{ "workflow":"scan", "provider":"kis|pykrx", "universe":"KR|US|both" }`; sell: `{ "workflow":"sell", "provider":"kis|pykrx" }` | `202 WorkflowDispatchResult` |
| `GET` | `/api/holdings` | holdings 목록 | query `limit=1..200`, optional `cursor` | `{ items, nextCursor, hasMore }` |
| `POST` | `/api/holdings` | holding 생성 | `HoldingMutationInput` with required `ticker` | `201 HoldingRecord` |
| `PATCH` | `/api/holdings/[ticker]` | holding 수정 | at least one mutable holding field | `200 HoldingRecord` |
| `DELETE` | `/api/holdings/[ticker]` | holding 삭제 | no body required | `200 { "deleted": true, "ticker": string }` |
| `POST` | `/api/holdings/[ticker]/add-buy` | 추가매수 원자 갱신 | header `Idempotency-Key: <uuid>`, JSON `{ "buy_quantity": number, "buy_price": number, "buy_date"?: "YYYY-MM-DD" }` | `200 HoldingRecord`; mismatch `409` |
| `PATCH`/`DELETE` | `/api/holdings/[...ticker]` | class ticker alias route | same as `[ticker]` | same as `[ticker]` |
| `POST` | `/api/holdings/add-buy/[...ticker]` | class ticker add-buy alias route | same as `[ticker]/add-buy` | same as `[ticker]/add-buy` |
| `GET` | `/api/holdings/yaml` | holdings YAML export | no body required | YAML snapshot payload |
| `POST` | `/api/holdings/yaml` | holdings YAML import dry-run/apply | JSON `{ "document": string, "apply": boolean }` | `{ mode, summary }` |
| `POST` | `/api/holdings/toss-sync` | Toss Securities holdings dry-run/apply | dry-run: `{ "mode": "dry-run" }`; apply: `{ "mode": "apply", "diffHash": "sha256:4444444444444444444444444444444444444444444444444444444444444444" }` | `{ mode, diffHash, applyBlocked, summary, changes, blockedRows, targetRows }`; apply may return `409` for blocked/stale diffs |
| `POST` | `/api/holdings/toss-sync/scheduled` | Local scheduled Toss holdings auto-apply | `{ "mode": "auto-apply", "sessionDate"?: "YYYY-MM-DD" }` with `Authorization: Bearer <TOSS_SYNC_JOB_TOKEN>` from a local request | `{ mode: "auto-apply", status, diffHash, applyBlocked, summary, changes, blockedRows, targetRows, quarantinedCount, quarantinedTickers }`; `status` is `applied`, `unchanged`, `disabled`, `blocked`, `wipe_guard_blocked`, `marker_failed`, or `error` |
| `GET` | `/api/tickers/search` | ticker directory 검색 | query `q=1..120 chars`, `limit=1..50` | ticker search payload |
| `GET` | `/api/tickers/recent-candidates` | 최근 buy 후보 | query `limitReports=1..50`, `limitCandidates=1..100` | recent candidate payload with `pattern: string \| null` per candidate |

### Holdings Contract Notes

- `HoldingRecord`/current snapshots include nullable `entry_pattern: string | null`.
- `HoldingMutationInput` accepts optional `entry_pattern?: string | null`. A non-null `entry_pattern` create/patch payload must include `quantity > 0` in the same payload. Explicit `entry_pattern: null` clears without requiring quantity. If a mutation owns `quantity: 0`, persistence normalizes `entry_pattern` to `null`.
- YAML import/replace-all inputs are the only path where an omitted active `entry_pattern` key can mean preserve-existing. YAML export always owns the key, including `entry_pattern: null`.
- Add Buy remains quantity-only. `/api/holdings/[ticker]/add-buy` does not accept marker fields such as `entry_pattern`; the RPC preserves existing active markers and clears stale markers when reactivating `quantity=0` rows.
- `/api/tickers/search` remains ticker/name-only. `/api/tickers/recent-candidates` reads the latest buy report candidates and returns `{ ticker, name, pattern }`, where invalid or missing buy-report patterns are normalized to `null`.
- `/api/holdings/toss-sync` fetches Toss holdings with server-side credentials, normalizes safe rows into the holdings snapshot contract, preserves app-owned metadata for matched rows, and returns a grouped reconciliation with a deterministic `diffHash`. US symbols without an existing holding suffix first use the fresh ticker directory when it has same-base candidates. Only when the directory has no candidate for that symbol may the server use the private, externally SHA-256-bound `toss-sync-reviewed-mapping.v1` registry. Ambiguous directory candidates remain blocked and are not overridden. Missing/invalid approval metadata, duplicate registry symbols, unsupported evidence sources, or Polygon MIC/suffix mismatches fail closed. The registry is local input only and performs no provider call during dry-run or apply. Blocked rows such as unknown enum values, invalid decimals, or unresolved US exchange suffixes set `applyBlocked=true`. The browser displays these rows in the Holdings Toss Sync panel and does not receive Toss access tokens, account identifiers, or registry bytes.
- Apply refetches Toss and Supabase, recomputes the diff/hash, rejects blocked or stale diffs with `409`, and calls the Supabase replace-all RPC with an expected current holdings snapshot so the RPC can reject write-time races with `409`.
- The scheduled route is for local non-browser jobs. It requires a local request and `TOSS_SYNC_JOB_TOKEN`, respects `TOSS_SYNC_AUTO_APPLY_ENABLED`, and writes only when no rows are blocked. A non-empty Toss snapshot may omit existing holdings; scheduled sync preserves those holdings and marks them `broker_state=not_seen_in_toss` with durable first/last seen dates, count, and `diffHash` evidence instead of deleting rows. If a previously quarantined holding reappears in Toss, the same sync path clears the broker evidence back to `confirmed`. An empty Toss snapshot that would wipe existing rows still returns `wipe_guard_blocked`. After `applied` or `unchanged`, the route writes `toss-sync:success:MIXED:<sessionDate>` including `quarantinedCount`/`quarantinedTickers` so scheduled sell generation can trust freshness and still surface missing-broker rows for manual review from the Supabase-exported holdings snapshot. If that marker write fails, the route returns `marker_failed` and the local Toss runner exits non-zero. Manual reviewed `/api/holdings/toss-sync` apply remains the path for destructive deletes.

## Ticker Contract

| Market | Format | Example | Notes |
| --- | --- | --- | --- |
| KR | six digits | `005930` | KRX code. |
| US | symbol + exchange suffix | `AAPL.NAS`, `BRK.B.NYS` | Supported suffixes: `.NAS`, `.NYS`, `.AMS`. |

`.US` suffix is intentionally rejected because it is ambiguous.

## Request Examples

```bash
curl -sS -X POST http://127.0.0.1:55300/api/auth/login \
  -H 'Content-Type: application/json' \
  -d '{"username":"admin","password":"replace-with-password"}'
```

```bash
curl -sS 'http://127.0.0.1:55300/api/reports?type=buy&limit=30'
```

```bash
curl -sS -X POST http://127.0.0.1:55300/api/run \
  -H 'Content-Type: application/json' \
  -d '{"workflow":"scan","provider":"kis","universe":"both"}'
```

The examples above require a valid authenticated session cookie in normal browser/API use. They are shape examples, not a complete authentication walkthrough.

## Error Handling

| Condition | Typical Status | Notes |
| --- | ---: | --- |
| Missing/invalid admin session | `401` or redirect from page proxy | Protected API route guard. |
| Same-origin/local guard failure | `403` | Local-console hardening. |
| Schema validation failure | `400` | Zod schema errors are returned as request errors. |
| GitHub dispatch disabled | `503`/feature disabled response | Depends on `/api/run` branch. |
| Supabase upstream error | matching upstream status or `500` | Route logs include request metadata, not secrets. |
| Add-buy idempotency payload mismatch | `409` | Same idempotency key with different payload. |

## Source Of Truth

- CLI options: `sab/__main__.py`
- Web request schemas: `web/src/lib/schemas.ts`
- Web page auth proxy: `web/src/proxy.ts`
- Web route implementations: `web/src/app/api/**/route.ts`
- Shared response types: `web/src/lib/types.ts`
- Supabase schema/RPC: `supabase/migrations/`

## Verification

```bash
UV_CACHE_DIR=.uv-cache uv run python -m sab --help
pnpm --dir web run test:coverage
```

NOT_RUN: 이 문서 작성 중 CLI와 web test 전체를 실행하지 않았다면 최종 보고서에 별도로 기록합니다.
