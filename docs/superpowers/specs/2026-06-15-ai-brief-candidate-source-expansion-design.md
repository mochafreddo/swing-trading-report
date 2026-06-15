# AI Brief Candidate And Source Expansion Design

Status: Approved design, pending written-spec review
Date: 2026-06-15
Scope: Scheduled and manual `sab ai-brief` candidate selection, source provider coverage, artifact/evaluator contracts

## Context

The 2026-06-15 US scheduled AI Brief run generated `reports/2026-06-15.entry.json` and `reports/2026-06-15.ai-brief.json`, then failed the scheduled quality gate because the only recommended candidate, `ELV.NYS`, had no usable sources. The root problem was narrower than the alert text:

- `sab ai-brief` only passed `entries[].action == "ENTER"` rows into the AI/model pipeline.
- The entry report had eight `READY` rows, but only one `ENTER` row.
- Benzinga was queried only for that single ticker and returned zero usable sources.

Live provider checks against the 2026-06-15 candidate set showed:

- Benzinga: `0/8` READY candidates covered, `0/7` trade-relevant candidates covered.
- Finnhub: `5/8` READY candidates covered, `4/7` trade-relevant candidates covered.
- Polygon: `POLYGON_API_KEY` was configured, but the provider returned HTTP 429 during the live check.
- Alpha Vantage and Marketaux tokens were not configured.

## Problem

The current AI Brief contract conflates "entry row is immediately allowed to enter" with "candidate is worth AI/news review." That is too narrow for swing trading. A portfolio cap or a volatility/manual-review flag can block automatic entry while still leaving a high-value swing candidate worth reviewing. Conversely, a failed trigger guard means the entry trigger is currently broken and should not compete in the same recommendation ranking.

The source provider path also has weak observability. A provider can succeed with zero sources for every ticker, producing no provider-level error and only surfacing as a downstream quality gate failure.

## Goals

- Expand AI/source pipeline coverage to swing-relevant `READY` candidates, not only `ENTER` candidates.
- Keep trading semantics clear by separating recommendable candidates from watch-only candidates.
- Reduce dependence on a single US news provider.
- Make zero-source and provider-fallback behavior visible in artifacts, logs, and quality gate failures.
- Preserve fail-closed behavior for scheduled success when final recommendations are not sufficiently source-backed.

## Non-Goals

- Do not turn AI Brief into a new signal generator.
- Do not allow AI to invent tickers or promote non-READY rows.
- Do not auto-enter or imply automated order execution.
- Do not remove existing single-provider CLI compatibility.
- Do not relax URL safety, freshness, DNS, or source cap validation.

## Design Overview

Use a broader candidate universe for source collection, then classify candidates into explicit AI roles:

- `recommendable`: eligible for model recommendation or model veto.
- `watch_only`: eligible for source/news context and watch explanation, but not final recommendation ranking.
- `excluded`: outside the AI/source pipeline.

Use a provider chain for source collection:

```text
finnhub -> benzinga-news -> polygon-news
```

Merge source results by ticker, track per-provider coverage, and continue past provider failures where it is safe to do so.

## Candidate Classification

### Recommendable

A row is recommendable when all base gates pass:

- `entry_state == "READY"`
- `entry_price_status == "available"`
- ticker is non-blank and belongs to the selected market

Then at least one trading-relevant condition must hold:

- `action == "ENTER"`
- `action == "SKIP"` and a reason starts with or equals `portfolio market cap reached`
- `action == "REVIEW"` and the reason indicates `risk_alignment=tight_stop_vs_volatility`

These candidates represent valid swing setups whose final action is blocked by portfolio policy or risk/manual-review policy, not by a broken setup.

### Watch-Only

A row is watch-only when the base gates pass and:

- `action == "SKIP"`
- a reason starts with or contains `hybrid trigger guard failed`

This row had a valid setup in the source buy report, but current entry price no longer satisfies the trigger. The model may summarize the watch condition, but the ticker must not appear in final `recommendations[]`.

### Excluded

A row is excluded when:

- `entry_state != "READY"`
- `entry_price_status != "available"`
- action is unknown
- the reason indicates price/data integrity failure
- the reason indicates gap guard breach unrelated to portfolio policy
- it does not match recommendable or watch-only rules

Excluded candidates remain visible as diagnostics but do not receive source enrichment or model ranking.

### 2026-06-15 Example

From `reports/2026-06-15.entry.json`:

- `recommendable`: `ELV.NYS`, `CAT.NYS`, `TSM.NYS`, `CIFR.NAS`, `IREN.NAS`, `COHR.NYS`, `ANET.NYS`
- `watch_only`: `MO.NYS`
- `excluded`: none from the eight READY rows

## Artifact Contract

Add new top-level fields to `sab.ai_brief.v1` artifacts:

```json
{
  "eligible_tickers": ["ELV.NYS", "CAT.NYS"],
  "watch_tickers": ["MO.NYS"],
  "recommendations": [],
  "vetoed_candidates": [],
  "watch_candidates": [],
  "excluded_candidates": [],
  "source_provider_summary": {}
}
```

Field meanings:

- `eligible_tickers`: recommendable candidate tickers after preselection and cap handling.
- `watch_tickers`: watch-only tickers.
- `recommendations`: final model recommendations, only from `eligible_tickers`.
- `vetoed_candidates`: eligible candidates the model chose not to recommend.
- `watch_candidates`: watch-only summaries and re-trigger conditions, only from `watch_tickers`.
- `excluded_candidates`: rows outside the AI/source pipeline, with concise reason codes.
- `cap_excluded_candidates`: recommendable rows beyond the AI preselection cap.
- `source_provider_summary`: source chain inputs, failures, per-provider coverage, and final merged coverage.

Existing consumers should continue to read `recommendations[]`, `vetoed_candidates[]`, `source_issues[]`, and `system_issues[]`. New UI and notification work can surface `watch_candidates[]` separately.

## Source Provider Chain

### Configuration

Keep existing single-provider behavior:

- `AI_BRIEF_SOURCE_PROVIDER_US=finnhub`
- `AI_BRIEF_SOURCE_PROVIDER=benzinga-news`
- `--source-provider polygon-news`

Add optional chain configuration:

- `AI_BRIEF_SOURCE_PROVIDER_CHAIN_US=finnhub,benzinga-news,polygon-news`
- `AI_BRIEF_SOURCE_PROVIDER_CHAIN_KR=naver-news`
- `AI_BRIEF_SOURCE_PROVIDER_CHAIN=finnhub,benzinga-news`

Market-specific chain config wins over global chain config. Chain config wins over single-provider config. If no chain is configured, the current single-provider path is used.

### Default US Chain

Use this recommended default chain for scheduled US runs:

```text
finnhub -> benzinga-news -> polygon-news
```

Rationale:

- Finnhub had the best observed coverage on the 2026-06-15 candidate set.
- Benzinga had zero observed coverage but can still provide incremental coverage on other days.
- Polygon key exists but returned HTTP 429, so it must be rate-limit aware and late in the chain.

The implementation should set or document `AI_BRIEF_SOURCE_PROVIDER_CHAIN_US=finnhub,benzinga-news,polygon-news` for the scheduled US environment. Manual CLI usage remains single-provider unless the operator explicitly passes or configures a chain.

### Merge Rules

- Run providers in chain order for the source universe: `recommendable + watch_only`.
- Preserve source URL safety, freshness, duplicate, future-time, DNS, and cap checks.
- Merge by ticker.
- Stop adding sources for a ticker once `MAX_SOURCES_PER_TICKER` is reached.
- Preserve provider provenance in `source_provider_summary`. If the source row schema is extended with provider metadata, consumers must treat that metadata as optional.
- Do not let a later provider replace already accepted sources unless deduplication requires it.

### Failure And Zero-Result Rules

- Provider auth/config failure: record provider-level `system_issues[]` and continue if later providers are configured.
- Provider HTTP 429: record provider-level issue, stop calling that provider for the rest of the run, and continue to the next provider.
- Provider timeout/HTTP/JSON failure: record provider-level issue and continue.
- Provider success with zero rows for a ticker: record ticker-level `source_issues[]` such as `benzinga_news_source_no_results`.
- Provider success with zero rows for every requested ticker: record provider-level coverage as `0/N`; this is not a transport failure.

`source_provider_summary` should include:

```json
{
  "chain": ["finnhub", "benzinga-news", "polygon-news"],
  "providers": [
    {"provider": "finnhub", "status": "success", "covered": 4, "total": 8},
    {"provider": "benzinga-news", "status": "success", "covered": 0, "total": 4},
    {"provider": "polygon-news", "status": "failed", "code": "http_429"}
  ],
  "final": {
    "recommendable_covered": 4,
    "recommendable_total": 7,
    "watch_covered": 1,
    "watch_total": 1
  }
}
```

## Model Provider Contract

The OpenAI request payload should distinguish candidate roles:

- `recommendable_candidates`: model may recommend or veto.
- `watch_candidates`: model may summarize, but must not rank as recommendations.

The model contract must require:

- recommendations only reference `recommendable_candidates`.
- watch summaries only reference `watch_candidates`.
- source URLs only come from each candidate's attached sources.
- candidates with no usable sources either remain unrecommended or carry explicit source issues.
- no automated-order wording.

The deterministic fake provider should be updated to exercise both roles.

## Evaluator And Quality Gate

The recommendation evaluator should derive expected AI roles from the entry report using the same classifier.

Validation rules:

- `eligible_tickers` must match expected recommendable tickers after preselection.
- `watch_tickers` must match expected watch-only tickers.
- `recommendations[].ticker` must be in `eligible_tickers`.
- `vetoed_candidates[].ticker` must be in `eligible_tickers`.
- `watch_candidates[].ticker` must be in `watch_tickers`.
- `excluded_candidates` and `cap_excluded_candidates` must match classifier output.
- summary counts must include watch counts.

Quality gate rules:

- Recommendation source-backed ratio remains fail-closed for scheduled success.
- Watch-only source coverage is reported but does not fail recommendation quality by itself.
- If there are recommendable candidates but all provider chain attempts fail, return `FAIL` with `source_provider_chain_failed`.
- If there are recommendable candidates but no final recommendation is source-backed, preserve `NEEDS_REVIEW_WEAK_NEWS` and fail scheduled success.
- If only watch-only candidates exist, use `brief_state="NEEDS_REVIEW_WATCH_ONLY"` and `brief_reason="watch_only_trigger_pending"` instead of a clean `NO_SIGNAL`.

## Notification And Web Display

Notifications should keep final recommendations first. Watch-only candidates should be shown separately as "watch / re-trigger" items, not mixed into the action list.

Web report detail should show:

- recommendable recommendations and vetoes
- watch-only candidates and their re-trigger conditions
- provider chain coverage summary
- ticker-level no-result source issues

## Testing Plan

Python tests:

- Candidate classifier maps `ENTER`, portfolio-cap `SKIP`, risk-alignment `REVIEW`, trigger-failed `SKIP`, and invalid rows to the expected roles.
- `run_ai_brief` passes recommendable and watch-only ticker sets into source loading.
- `run_ai_brief` writes `watch_tickers`, `watch_candidates`, and `source_provider_summary`.
- Provider chain merges sources by ticker and respects source caps.
- Provider chain records ticker-level no-result issues.
- Provider chain stops Polygon requests after HTTP 429 and records provider-level failure.
- Evaluator validates eligible/watch contracts and rejects cross-role recommendations.
- Scheduled quality gate still fails when final recommendations are not source-backed.

Docs/tests:

- Update `docs/STRATEGY.md` AI Brief contract.
- Update `docs/ARCHITECTURE.md` scheduled AI Brief flow.
- Update `docs/operations.md` runbook notes for provider chain diagnostics.
- Update web/notification tests if display contracts change in the same implementation slice.

## Compatibility And Migration

- Existing single-provider CLI and env behavior remains valid.
- Existing artifacts without `watch_tickers`, `watch_candidates`, or `source_provider_summary` should continue to render through fallback inference.
- The evaluator must validate new artifacts with the expanded recommendable/watch classifier. Legacy artifacts that lack all new fields may use the existing ENTER-only interpretation for historical reads and legacy fixtures.
- Scheduled runs should opt into provider chain only after tests cover provider failure isolation.

## Acceptance Criteria

- A 2026-06-15-style entry report produces seven recommendable candidates and one watch-only candidate before preselection caps.
- Source collection is attempted for both recommendable and watch-only tickers.
- Finnhub can supply sources even when Benzinga returns no rows.
- Benzinga zero-result cases are visible as no-result diagnostics, not silent success.
- Polygon HTTP 429 does not abort the whole chain.
- Scheduled AI Brief still fails closed when final recommendations do not satisfy the source-backed quality threshold.
