# TODOS

## AI Brief

### Phase 2 real provider and eval suite

**What:** Add provider-specific news/API adapters and source-quality eval suites for `ai-brief`. The generic `http-json` source API adapter now covers the external API trust boundary; vendor-specific collection quality and eval coverage remain.

**Why:** Fake provider only exercises the artifact contract; it does not validate recommendation quality, source collection quality, or prompt safety.

**Context:** Phase 1 is intentionally scoped to local artifact generation, fake provider output, and validator guardrails. OpenAI model judgment now starts from the Phase 1 fixtures and the `sab.ai_brief.v1` validator contract, with tests for timeout/failure handling, unknown ticker rejection, `SKIP`/`REVIEW` non-promotion, weak source disclosure, and financial-safety language. Local JSON and generic external HTTP JSON source context can now be injected without expanding eligible tickers. Real vendor/news collection quality evaluation is still pending.

**Effort:** M
**Priority:** P1
**Depends on:** Phase 1 `ai-brief` artifact contract and validator tests merged.

## Completed

- 2026-05-05: Supabase/web AI Brief support - `ai-brief` Storage/report_index key contract, CLI/workflow upload, web Reports filter/detail rendering, and regression coverage.
- 2026-05-05: AI Brief scheduled workflow slice - KR/US pre-open schedules with trading-session runtime guard and automatic notification delivery.
- 2026-05-05: AI Brief manual delivery slice - opt-in Telegram/Slack delivery from the manual ai-brief workflow after artifact upload.
- 2026-05-05: AI Brief manual workflow slice - manual GitHub Actions workflow_dispatch for single-market scan -> entry -> ai-brief, Actions artifact upload, and notification preview artifacts.
- 2026-05-05: AI Brief notification text slice - Telegram/Slack text builders for ai-brief artifacts, recommendation/empty-result/issue rendering, and notification text tests.
- 2026-05-05: Phase 2 first slice - OpenAI Responses model provider, CLI timeout option, provider failure artifacts, source-disclosure guardrails, and prompt-safety validator coverage.
- 2026-05-05: Phase 2 source contract slice - local JSON source provider, source URL trust-boundary checks, source provider failure artifacts, and CLI/docs coverage.
- 2026-05-06: Phase 2 external source API slice - generic `http-json` source provider, source API timeout/failure artifact contract, workflow inputs/env wiring, and CLI/docs coverage.
