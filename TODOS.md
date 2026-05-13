# TODOS

## AI Brief

### Phase 2 real provider and eval suite

**What:** Expand provider-specific live news/API adapters for `ai-brief`. The generic `http-json` source API adapter covers the external API trust boundary, offline source-quality evals cover collected payload quality, RSS/Atom/RDF local/live HTTPS feed collection covers vendor-neutral payload generation, Finnhub covers the first paid/vendor-specific US Company News adapter, Naver News covers the first KR vendor-specific news adapter, and offline source eval can now compare multiple captured payloads; broader live vendor comparison and recommendation-quality evaluation coverage remain.

**Why:** Fake provider only exercises the artifact contract; it does not validate recommendation quality, source collection quality, or prompt safety.

**Context:** Phase 1 is intentionally scoped to local artifact generation, fake provider output, and validator guardrails. OpenAI model judgment now starts from the Phase 1 fixtures and the `sab.ai_brief.v1` validator contract, with tests for timeout/failure handling, unknown ticker rejection, `SKIP`/`REVIEW` non-promotion, weak source disclosure, and financial-safety language. Local JSON, generic external HTTP JSON, Finnhub Company News, and Naver News source context can now be injected without expanding eligible tickers. Collected source payloads can be evaluated offline for freshness, eligibility, cap, duplicate URL, and coverage quality, and multiple captured payloads can be compared against the same entry candidates without live provider calls. RSS/Atom/RDF local files and live HTTPS feed URLs can be converted into compatible `sources[]` payloads without secrets; URL failures are ticker-level WARN issues. Finnhub v1 is intentionally US-only and Naver News v1 is intentionally KR-only, so broader live vendor comparison remains pending.

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
- 2026-05-06: Phase 2 source eval slice - offline AI Brief source payload quality evaluator, deterministic fixtures, script/just entrypoint, and docs coverage.
- 2026-05-06: Phase 2 source collector slice - RSS/Atom/RDF captured-feed source payload builder, deterministic feed fixtures, script/just entrypoint, eval compatibility tests, and docs coverage.
- 2026-05-07: Phase 2 live RSS feed URL collection slice - HTTPS feed URL catalog rows, safe bounded fetch, ticker-level WARN issues, CLI timeout option, tests, and docs coverage.
- 2026-05-12: Phase 2 Finnhub source provider slice - US-only Finnhub Company News adapter, ticker symbol mapping, workflow variable/secret wiring, provider failure artifacts, tests, and docs coverage.
- 2026-05-13: Phase 2 Naver News source provider slice - KR-only Naver Search API News adapter, buy-report company-name query enrichment, workflow secret wiring, provider failure artifacts, tests, and docs coverage.
- 2026-05-13: Phase 2 source eval comparison slice - offline multi-provider captured payload comparison, aggregate status/leaders summary, CLI parser validation, tests, and docs coverage.
