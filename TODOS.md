# TODOS

## AI Brief

### Phase 2 real provider and eval suite

**What:** Add real model/source providers for `ai-brief` with prompt/eval suites and provider timeout/failure contracts.

**Why:** Fake provider only exercises the artifact contract; it does not validate recommendation quality, source collection quality, or prompt safety.

**Context:** Phase 1 is intentionally scoped to local artifact generation, fake provider output, and validator guardrails. When real article/news collection and GPT-style model judgment are added, the work must include eval cases for unknown ticker rejection, `SKIP`/`REVIEW` non-promotion, weak source disclosure, and financial-safety language. Start from the Phase 1 fixtures and the `sab.ai_brief.v1` validator contract.

**Effort:** M
**Priority:** P1
**Depends on:** Phase 1 `ai-brief` artifact contract and validator tests merged.

### Notification and scheduled workflow

**What:** Build Telegram/Slack text from `ai-brief` artifacts, add manual workflow dispatch, then add KR/US scheduled runs with runtime guards.

**Why:** The product goal is a timely trading assistant that tells the user when entry candidates are worth reviewing, not just a local JSON generator.

**Context:** Phase 1 excludes notification delivery and workflow orchestration. The safe sequence is local artifact stability, notification text builder with tests, manual workflow dispatch, and only then KR/US schedules using market/session runtime guards. Avoid scheduled noise until manual artifacts are useful.

**Effort:** M
**Priority:** P1
**Depends on:** Phase 1 artifact contract, one useful manual artifact sample, and notification text tests.

### Supabase and web `ai_brief` support

**What:** Extend Supabase Storage/report_index and web report parsing/list/detail paths to support `ai_brief` artifacts.

**Why:** Phase 1 local artifacts will not appear in existing uploaded reports or the web UI because those paths currently accept only `buy`, `sell`, and `entry` report types.

**Context:** This was intentionally deferred from Phase 1 because it touches cross-stack boundaries such as report storage keys, Supabase indexing, web report key parsing, admin report readers, and report detail rendering. Add this only after the local artifact contract is stable and manual/notification usage confirms the web surface is valuable.

**Effort:** M
**Priority:** P2
**Depends on:** Phase 1 schema stability and notification/manual usage feedback.

## Completed
