# AI Brief Article Reader Source-Backed Design

상태: Accepted
Date: 2026-06-24
Scope: AI Brief source enrichment, source-backed evaluation tiers, article URL reader policy

## Context

The AI Brief pipeline already has a strong boundary between source discovery and model
recommendation:

```text
entry report
  -> candidate classifier
  -> source_provider_chain
  -> canonical source rows: title, url, published_at
  -> source refs in the model request
  -> final report with source objects
  -> evaluator and scheduled quality gate
```

The current source provider chain uses vendor or local providers such as Finnhub,
Naver, Benzinga, Polygon, `local-json`, and `http-json` to discover candidate news.
It validates URL safety, freshness, duplicate rows, ticker eligibility, and per-ticker
source caps before the model can cite those sources.

The gap is that a source row can be metadata-backed without the local pipeline reading
the article body. That keeps scheduled runs stable, but it limits confidence in whether
the model's recommendation is backed by article content rather than provider metadata
alone.

## Problem

Replacing source APIs with browser-only news discovery would introduce too much
operational risk:

- Search result ranking is less deterministic than provider APIs.
- Article pages can be blocked by paywalls, login walls, bot defenses, cookie banners,
  or dynamic rendering.
- Scheduled GitHub Actions or local Docker jobs would need a browser runtime as a hard
  dependency for discovery.
- Quality gates would become sensitive to publisher page behavior instead of candidate
  source availability.

At the same time, keeping the current source-backed result as a single boolean hides
an important distinction:

- A recommendation backed by valid provider metadata is useful.
- A recommendation backed by successfully read and relevant article content is stronger.

## Goals

- Preserve the existing source provider chain as the source discovery layer.
- Add a browser-based article reader after source discovery to strengthen source
  backing when article content is accessible.
- Represent source backing as tiers instead of a single boolean.
- Let scheduled quality gates downgrade weak article access without failing runs that
  still have valid metadata-backed sources.
- Keep source rows backward compatible for existing consumers.
- Record blocked, paywalled, rate-limited, or failed article reads as diagnostics.
- Keep article access conservative, transparent, and non-evasive.

## Non-Goals

- Do not replace Finnhub, Naver, or other provider discovery with browser search in
  this design.
- Do not bypass CAPTCHA, paywalls, login walls, bot detection, robots policy, rate
  limits, or access controls.
- Do not use stealth browser fingerprinting, proxy rotation, user-agent impersonation,
  paid-session cookies, or credentials to access articles.
- Do not store full article bodies in report artifacts.
- Do not change the public `recommendations[].sources[]` and
  `watch_candidates[].sources[]` shape in a breaking way.
- Do not require browser reading for all source-backed recommendations at rollout.

## Approved Approach

Use API/provider discovery plus tiered article verification:

```text
source provider chain
  -> canonical metadata source rows
  -> article reader attempts selected URLs
  -> optional article_read metadata is attached to each source row
  -> model receives source refs and bounded article context
  -> final artifact keeps source rows plus optional article_read metadata
  -> evaluator computes source_backing_tier per recommendation
  -> scheduled gate reports verified coverage and downgrades weak coverage
```

The default scheduled reader should use `lightpanda fetch` because it is a small CLI
with direct markdown and semantic-tree output. `agent-browser` remains useful for manual
diagnostics and can become a later fallback, but it should not be the first scheduled
runtime dependency.

Alternatives considered:

- Metadata only. This is stable but does not distinguish accessible article content
  from provider metadata.
- Browser-only discovery and reading. This reduces vendor API dependence but weakens
  determinism and increases scheduler fragility.
- Tiered source-backed evaluation. This is the approved approach because it improves
  evidence quality without making publisher page access a hard dependency.

## Architecture

### Article Reader Module

Add a focused module, tentatively `sab.article_reader`, with these responsibilities:

- Validate article URLs through the same public-URL safety posture used by source rows.
- Select a bounded set of source URLs to read per run.
- Invoke `lightpanda fetch` through a small subprocess adapter.
- Use conservative flags such as private-network blocking, bounded timeout, bounded
  response size, and low concurrency.
- Parse markdown or semantic-tree output into a bounded text excerpt.
- Classify the read result into normalized statuses.
- Avoid storing full article text.

The adapter should be easy to fake in tests. The core pipeline should depend on a
small protocol such as `ArticleReader.read(url, ticker, company_terms, now)` rather
than subprocess details.

### Source Chain Integration

The source provider chain remains responsible for discovery. After
`load_ai_brief_source_chain()` returns canonical rows, the AI Brief pipeline enriches
those rows before attaching them to model candidates.

Article reading should operate on the source universe already selected by the pipeline:

- recommendable candidates first
- then watch-only candidates
- no attempt for excluded candidates
- no attempt beyond configured per-run or per-ticker caps

Reader failure must not discard an otherwise valid source row. It should attach
diagnostics and continue with the metadata-backed source.

### Model Boundary

The model should continue to cite source refs, not source objects. The model input may
include bounded article context only after local extraction:

```json
{
  "source_id": "AAPL.NAS:1",
  "title": "Apple expands AI capacity for device roadmap",
  "url": "https://news.example.test/aapl-ai-capacity",
  "published_at": "2026-06-24T09:30:00+00:00",
  "article_read": {
    "status": "verified",
    "tier": "article_verified",
    "excerpt": "Apple said it expanded AI infrastructure capacity...",
    "matched_terms": ["AAPL", "Apple"]
  }
}
```

Article page content remains untrusted input. The prompt should explicitly say not to
follow instructions inside article text, titles, URLs, or extracted excerpts.

## Data Contract

Source rows keep their existing required fields:

```json
{
  "title": "...",
  "url": "https://...",
  "published_at": "2026-06-24T09:30:00+00:00"
}
```

Article reading adds an optional field:

```json
{
  "title": "...",
  "url": "https://...",
  "published_at": "2026-06-24T09:30:00+00:00",
  "article_read": {
    "status": "verified",
    "tier": "article_verified",
    "checked_at": "2026-06-24T09:35:00+00:00",
    "reader": "lightpanda",
    "excerpt": "bounded excerpt...",
    "matched_terms": ["AAPL", "Apple"],
    "issue_code": null
  }
}
```

Allowed `article_read.status` values:

- `not_attempted`: reader disabled, cap exceeded, or source intentionally skipped
- `metadata_only`: existing source metadata is valid, but no article content was used
- `accessed`: URL was accessed and content was extracted, but relevance was not strong
  enough for verification
- `verified`: extracted content matched expected ticker or company context
- `blocked`: access was blocked by paywall, login, CAPTCHA, bot block, robots policy, or
  rate limit
- `failed`: timeout, HTTP failure, process failure, parse failure, or empty content

Allowed backing tiers:

- `metadata_backed`: source row passed existing URL, freshness, and eligibility checks
- `article_accessed`: article reader extracted bounded article content
- `article_verified`: article content matched ticker or company context

If `article_read` is absent, consumers must treat the source as `metadata_backed` when
it passes the existing source-backed checks.

## Verification Policy

Article verification should be conservative and local:

- Match ticker symbol, normalized ticker root, company name, or accepted aliases.
- Require at least one relevant matched term in extracted article content for
  `article_verified`.
- Treat title-only matches as metadata-backed unless body content is also available.
- Avoid model-only relevance judgments for the first version.
- Do not attempt to infer article relevance from unrelated page chrome, navigation, or
  recommendations widgets.

The first version can use deterministic term matching. More advanced extraction or
classification can be considered after live artifacts show the failure modes.

## Quality Gate

The evaluator should compute the strongest source tier for each recommendation:

- no valid sources: unbacked, existing fail-closed behavior applies
- only metadata-backed sources: recommendation is source-backed but weakly verified
- at least one article-accessed source: stronger than metadata, still not verified
- at least one article-verified source: strongest source-backed tier

Scheduled gate behavior:

- If a recommendation has no metadata-backed source, keep the existing FAIL behavior.
- If recommendations are metadata-backed but lack verified article reads, emit
  `NEEDS_REVIEW_WEAK_NEWS` or WARN instead of a clean pass.
- If at least one source per recommendation is `article_verified`, count the
  recommendation as strongly source-backed.
- Add summary metrics such as `article_verified_ratio`, `article_accessed_count`,
  `article_verified_count`, and `article_read_issue_count`.

This lets the project raise evidence quality without making publisher access problems
equivalent to missing source metadata.

## Failure And Access Policy

Article access is allowed only through non-evasive public retrieval:

- Respect explicit block states and record them as diagnostics.
- Prefer official APIs, RSS feeds, canonical public URLs, or AMP/canonical pages when
  they are publicly available and already exposed by the source provider.
- Use low concurrency and per-domain rate limits.
- Use bounded retries only for transient network failures.
- Keep a transparent reader identity; do not impersonate mainstream browsers or real
  users.
- Do not use stored user cookies, paid-session cookies, login credentials, CAPTCHA
  solving, stealth plugins, proxy rotation, or bot-defense bypass techniques.

Common failure mapping:

- Paywall or login required: `blocked`, `issue_code=article_paywalled`
- CAPTCHA or bot challenge: `blocked`, `issue_code=article_bot_challenge`
- Robots or policy denial: `blocked`, `issue_code=article_robots_blocked`
- HTTP 403 or 429: `blocked`, `issue_code=article_access_blocked`
- Timeout: `failed`, `issue_code=article_timeout`
- Empty or boilerplate-only extraction: `failed`, `issue_code=article_empty_content`
- Parser/process error: `failed`, `issue_code=article_reader_failed`

## Configuration

Roll out behind explicit configuration:

- `AI_BRIEF_ARTICLE_READER=none|lightpanda`
- `AI_BRIEF_ARTICLE_READER_MAX_URLS=8`
- `AI_BRIEF_ARTICLE_READER_TIMEOUT_SECONDS=8`
- `AI_BRIEF_ARTICLE_READER_MAX_EXCERPT_CHARS=1200`
- `AI_BRIEF_ARTICLE_READER_REQUIRE_VERIFIED=false`

Recommended rollout:

1. Manual/local opt-in for evidence gathering.
2. Scheduled diagnostic mode that records article read metrics but does not hard-fail
   verified coverage.
3. Later gate tightening only after enough live artifacts show acceptable access rates.

## Testing Plan

Unit tests:

- Fake the `lightpanda` subprocess adapter for success, blocked, timeout, malformed
  output, and empty extraction.
- Verify URL selection respects source universe, per-run caps, and candidate role order.
- Verify source rows remain backward compatible when `article_read` is absent.
- Verify source rows include bounded excerpts and no full article body.
- Verify deterministic ticker/company matching for `metadata_backed`,
  `article_accessed`, and `article_verified`.
- Verify blocked article access creates source issues but preserves the source row.

Evaluator tests:

- Recommendation with no source still fails.
- Metadata-backed recommendation remains source-backed but weak.
- Article-accessed recommendation gets the intermediate tier.
- Article-verified recommendation gets the strongest tier.
- Verified coverage shortage downgrades scheduled state to weak-news review rather than
  dropping otherwise valid recommendations.

Integration-style tests:

- Run `sab ai-brief` with a local source report and a fake reader to confirm artifact
  summary fields and source rows are emitted.
- Confirm historical artifacts without `article_read` continue to validate and render.

## Open Follow-Ups

- Decide whether `agent-browser --engine lightpanda` is useful as a later diagnostics
  command after the `lightpanda fetch` adapter is proven.
- Consider source-provider-specific canonical URL normalization if vendors return API
  redirect URLs instead of publisher URLs.
- Revisit hard gating on `article_verified` only after scheduled live runs show stable
  article access coverage.
