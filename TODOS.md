# TODOS

## AI Brief

### Phase 2 real provider and eval suite

**What:** Add real model/source providers for `ai-brief` with prompt/eval suites and provider timeout/failure contracts. First slice adds the OpenAI model provider and failure contract; second slice adds a local JSON source provider contract. External news/API source provider work remains.

**Why:** Fake provider only exercises the artifact contract; it does not validate recommendation quality, source collection quality, or prompt safety.

**Context:** Phase 1 is intentionally scoped to local artifact generation, fake provider output, and validator guardrails. OpenAI model judgment now starts from the Phase 1 fixtures and the `sab.ai_brief.v1` validator contract, with tests for timeout/failure handling, unknown ticker rejection, `SKIP`/`REVIEW` non-promotion, weak source disclosure, and financial-safety language. Local JSON source context can now be injected without expanding eligible tickers. Real article/news collection is still pending.

**Effort:** M
**Priority:** P1
**Depends on:** Phase 1 `ai-brief` artifact contract and validator tests merged.

### Supabase and web `ai_brief` support

**What:** Extend Supabase Storage/report_index and web report parsing/list/detail paths to support `ai_brief` artifacts.

**Why:** Phase 1 local artifacts will not appear in existing uploaded reports or the web UI because those paths currently accept only `buy`, `sell`, and `entry` report types.

**Context:** This was intentionally deferred from Phase 1 because it touches cross-stack boundaries such as report storage keys, Supabase indexing, web report key parsing, admin report readers, and report detail rendering. Add this only after the local artifact contract is stable and manual/notification usage confirms the web surface is valuable.

**Effort:** M
**Priority:** P2
**Depends on:** Phase 1 schema stability and notification/manual usage feedback.

## Completed

- 2026-05-05: AI Brief scheduled workflow slice - KR/US pre-open schedules with trading-session runtime guard and automatic notification delivery.
- 2026-05-05: AI Brief manual delivery slice - opt-in Telegram/Slack delivery from the manual ai-brief workflow after artifact upload.
- 2026-05-05: AI Brief manual workflow slice - manual GitHub Actions workflow_dispatch for single-market scan -> entry -> ai-brief, Actions artifact upload, and notification preview artifacts.
- 2026-05-05: AI Brief notification text slice - Telegram/Slack text builders for ai-brief artifacts, recommendation/empty-result/issue rendering, and notification text tests.
- 2026-05-05: Phase 2 first slice - OpenAI Responses model provider, CLI timeout option, provider failure artifacts, source-disclosure guardrails, and prompt-safety validator coverage.
- 2026-05-05: Phase 2 source contract slice - local JSON source provider, source URL trust-boundary checks, source provider failure artifacts, and CLI/docs coverage.
