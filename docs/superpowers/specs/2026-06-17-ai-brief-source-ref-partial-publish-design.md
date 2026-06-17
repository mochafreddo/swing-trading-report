# AI Brief Source Ref Partial Publish Design

상태: Accepted
Status: Approved design, pending written-spec review
Date: 2026-06-17
Scope: AI Brief OpenAI source contract, provider result normalization, scheduled publish behavior

## Context

The 2026-06-17 US scheduled AI Brief run generated local reports:

- `reports/2026-06-16.buy.json`
- `reports/2026-06-17.entry.json`
- `reports/2026-06-17.ai-brief.json`

The final scheduled status was `pipeline_failed` and `storage_key=null`. The paired
late-alert said `reason=pipeline_failed`, and the host wrapper also sent
`reason=scheduler_container_failed`.

The local AI Brief artifact showed the narrower failure:

```json
{
  "code": "model_provider_contract_error",
  "message": "OpenAI output watch candidate source url must be supplied in candidate.sources"
}
```

The source provider chain succeeded and supplied canonical source rows. The failure
happened after OpenAI returned watch-candidate source data that did not match the
allowed canonical source URLs for that candidate. The validator correctly blocked
untrusted source data, but one bad watch source caused the model provider result to
be treated as a system issue, which then failed the scheduled quality gate before
Storage upload and normal notification reconciliation.

This follows the earlier candidate/source expansion design from 2026-06-15. That
design expanded source coverage and kept final recommendations fail-closed when they
are not source-backed. This design closes the next boundary: the model must not be
responsible for re-creating trusted source objects.

## Problem

The current OpenAI contract asks the model to return source objects:

```json
{
  "sources": [
    {
      "title": "...",
      "url": "...",
      "published_at": "..."
    }
  ]
}
```

That makes the model copy security-sensitive provenance fields back across the trust
boundary. JSON schema can require `url`, but it cannot guarantee that the URL is
exactly one of the canonical URLs supplied by the source provider. The code validates
the returned source rows after the model call, but validation failures currently
raise a provider contract error for the whole result.

This creates two operational problems:

- A localized source reference error can block an otherwise usable scheduled AI Brief.
- The follow-up host failure alert makes an application quality failure look like a
  Docker or host outage.

## Goals

- Stop asking OpenAI to re-create trusted source objects.
- Let the model choose only from source references supplied by the local source catalog.
- Restore canonical source objects in local code before writing the report artifact.
- Isolate candidate-level source-reference errors so one bad candidate does not fail
  the whole provider result when the rest of the artifact remains valid.
- Preserve fail-closed behavior for final recommendations that are not sufficiently
  source-backed after sanitization.
- Preserve the existing public AI Brief artifact shape for consumers by continuing
  to write `sources[]` objects in final reports.
- Make partial publish behavior deterministic, visible, and test-covered.

## Non-Goals

- Do not relax URL safety, source freshness, ticker eligibility, role boundary, or
  automated-order language validation.
- Do not let AI invent sources, tickers, rankings, actions, or watch roles.
- Do not change Supabase schema or `report_index` shape.
- Do not change the public `recommendations[].sources[]` or
  `watch_candidates[].sources[]` artifact fields in this pass.
- Do not change Web UI layout in this pass.
- Do not implement diagnostic upload for quality-gate `FAIL` artifacts in this pass.
- Do not fix the wrapper `scheduler_container_failed` duplicate alert in this pass.
  Record it as follow-up operational cleanup.

## Constraints

- Scheduled success must still mean the final stored AI Brief passed the recommendation
  quality gate.
- Final recommendations must remain source-backed unless the existing evaluator policy
  explicitly allows a disclosed low-confidence unbacked recommendation.
- Watch-only source coverage remains diagnostic. A watch source-reference error should
  not by itself fail a source-backed recommendation report.
- Existing historical artifacts without source refs must continue to validate and render
  through the current `sources[]` object contract.
- Keep changes scoped to AI Brief provider normalization, artifact generation/evaluation
  behavior, tests, and documentation.

## Approved Approach

Use source references at the model boundary, then canonicalize and sanitize locally:

```text
source provider chain
  -> canonical source rows
  -> SourceReferenceCatalog assigns candidate-local source_id values
  -> OpenAI receives candidate.sources with source_id plus source metadata
  -> OpenAI returns source_refs only
  -> local post-processor resolves refs to canonical source rows
  -> candidate-level sanitizer drops or falls back only broken rows
  -> artifact writer emits existing sources[] objects
  -> evaluator decides scheduled publish eligibility
```

Alternatives considered:

- Keep source objects and strengthen prompts. This is small, but still relies on the
  model copying trusted data exactly.
- Source refs plus candidate-level isolation. This is the approved approach. It removes
  source-object copying and reduces failure blast radius while preserving final quality.
- Diagnostic publish for failed artifacts. This improves observability, but it expands
  report semantics and UI expectations beyond the root fix.

## Architecture

### SourceReferenceCatalog

Add a small provider-side helper that builds a deterministic source catalog from the
already validated candidate source rows.

Responsibilities:

- Assign stable source IDs per ticker, such as `SPGI.NYS:1`, `SPGI.NYS:2`,
  `SPGI.NYS:3`.
- Store source rows by `(ticker, source_id)`.
- Return model-facing source rows that include `source_id`, `title`, `url`, and
  `published_at`.
- Resolve returned source refs back to canonical source rows.
- Refuse cross-ticker refs even if an ID string is syntactically valid.

The source ID is local to one model request. It is not stored as a durable public ID
and does not need to survive across runs.

### OpenAiBriefProvider

The OpenAI request payload continues to include source titles and URLs as context, but
the output schema changes from source objects to refs:

```json
{
  "recommendations": [
    {
      "ticker": "AAPL.NAS",
      "rank": 1,
      "confidence": "LOW",
      "rationale": ["..."],
      "checklist": ["..."],
      "source_refs": ["AAPL.NAS:1"]
    }
  ],
  "watch_candidates": [
    {
      "ticker": "SPGI.NYS",
      "action": "WATCH",
      "reason": "...",
      "retrigger_conditions": ["..."],
      "source_refs": ["SPGI.NYS:1"]
    }
  ],
  "vetoed_candidates": [],
  "source_issues": []
}
```

The prompt should explicitly say:

- Choose source refs only from the same candidate's `sources[].source_id`.
- Do not return `title`, `url`, or `published_at`.
- Use an empty `source_refs` list only when there are no usable supplied sources for
  that ticker, and add a ticker-level `source_issues[]` row explaining why.

### ProviderResultSanitizer

Normalize parsed model output in two phases:

1. Structural validation for the whole result.
2. Candidate-level source-ref resolution and isolation.

Whole-result validation still rejects:

- Invalid JSON or missing top-level arrays.
- Tickers outside the eligible or watch sets.
- Watch tickers in recommendations or vetoes.
- Recommendable tickers in watch-only output.
- Invalid actions.
- Automated-order language.
- Rank values that cannot be interpreted safely.

Candidate-level source-ref validation handles:

- Unknown refs.
- Refs that belong to another ticker.
- Empty refs when the candidate has supplied sources and the model did not report a
  source issue.
- Canonical source rows that fail URL or freshness validation.

The sanitizer emits valid final provider rows plus additional source issues.

## Data Contract

### Model Input

Each candidate source row sent to OpenAI includes a `source_id`:

```json
{
  "ticker": "SPGI.NYS",
  "sources": [
    {
      "source_id": "SPGI.NYS:1",
      "title": "CNBC Daily Open: Iran framework signed but not delivered",
      "url": "https://finnhub.io/api/news?id=...",
      "published_at": "2026-06-16T02:12:37+00:00"
    }
  ]
}
```

### Model Output

OpenAI returns only `source_refs`:

```json
{
  "source_refs": ["SPGI.NYS:1"]
}
```

### Final Artifact

Final `sab.ai_brief.v1` artifacts keep the existing consumer-facing source shape:

```json
{
  "watch_candidates": [
    {
      "ticker": "SPGI.NYS",
      "action": "WATCH",
      "reason": "entry trigger is pending re-confirmation",
      "retrigger_conditions": ["price must satisfy the original entry trigger again"],
      "sources": [
        {
          "title": "CNBC Daily Open: Iran framework signed but not delivered",
          "url": "https://finnhub.io/api/news?id=...",
          "published_at": "2026-06-16T02:12:37+00:00"
        }
      ]
    }
  ]
}
```

### Diagnostics

Candidate-level source-ref problems are recorded as `source_issues[]` with `WARN`
severity unless they leave the artifact without required recommendation quality.

Suggested issue codes:

- `model_source_ref_invalid`: model returned refs not present in the candidate source
  catalog.
- `model_source_ref_missing`: model omitted refs for a candidate that had usable
  supplied sources.
- `model_unbacked_recommendation_dropped`: recommendation was dropped because it could
  not be source-backed.
- `model_watch_source_ref_invalid`: watch row source refs were invalid and the local
  fallback watch row was used.

System issues remain reserved for provider-wide failures that make the whole model
result untrustworthy.

## Error Handling

### Whole Provider Failure

Keep existing fail-closed provider behavior for errors that compromise the whole
result:

- HTTP failure, timeout, or non-JSON response.
- Parsed output is not an object.
- Required top-level arrays are missing or have the wrong type.
- Output includes ineligible tickers.
- Output crosses recommendation, veto, and watch role boundaries.
- Output contains automated-order language.
- Rank data is duplicated or cannot be safely normalized.

In these cases `run_ai_brief` records a `model_provider_*` system issue, writes an
empty recommendation artifact, and lets the scheduled quality gate decide failure.

### Candidate-Level Isolation

Recommendation source-ref errors are isolated to the affected recommendation:

- Drop that recommendation.
- Record a ticker-level source issue.
- Re-rank the remaining recommendations contiguously from 1 to N.
- Preserve valid vetoes and watch candidates.

Watch source-ref errors are isolated to the affected watch row:

- Replace the model watch row with the deterministic fallback watch row for that input
  candidate.
- Preserve canonical candidate sources from the input when available.
- Record a ticker-level source issue.

After sanitization, the report still goes through artifact validation and the
recommendation quality gate. If all recommendations were dropped while recommendable
candidates remain and no vetoes explain the decision, the existing
`recommendation_report_empty` quality failure remains the final result.

## Scheduled Publish Policy

The approved operating policy is partial publish:

- If candidate-level isolation produces an artifact that passes the recommendation
  quality gate, scheduled execution uploads it, records success markers, and sends the
  normal schedule notification.
- If the sanitized artifact fails the quality gate, scheduled execution blocks Storage
  upload and sends the existing late-alert.
- Watch-only source-ref errors alone do not block scheduled success when final
  recommendations are otherwise valid and source-backed.
- `NEEDS_REVIEW_WEAK_NEWS` remains visible through `brief_state` and notification/web
  rendering when the final artifact contains source or system issues.

This design intentionally does not alter the wrapper host-failure behavior. A follow-up
small change should stop the wrapper from sending `scheduler_container_failed` when the
container returns a structured application status such as `pipeline_failed`.

## Testing Plan

Provider tests:

- OpenAI request payload includes `source_id` on candidate source rows.
- OpenAI output schema requires `source_refs` and no longer asks for returned
  `title`, `url`, or `published_at`.
- Valid recommendation `source_refs` resolve to canonical `sources[]` rows.
- Valid watch `source_refs` resolve to canonical `sources[]` rows.
- Unknown recommendation refs drop only that recommendation and record
  `model_source_ref_invalid`.
- Unknown watch refs use deterministic fallback and record
  `model_watch_source_ref_invalid`.
- Cross-ticker refs are rejected as candidate-level source-ref errors.
- Rank normalization preserves contiguous ranks after dropped recommendations.
- Ineligible tickers and role boundary violations still raise provider contract errors.
- Automated-order language still raises provider contract errors.

AI Brief workflow tests:

- `run_ai_brief` writes a valid artifact when one recommendation is dropped but another
  remains source-backed.
- `run_ai_brief` writes a valid fallback watch row when watch refs are invalid.
- `source_issues[]`, summary counts, `brief_state`, and `brief_reason` stay
  deterministic after partial isolation.
- If all recommendations are dropped and recommendable candidates remain, the evaluator
  still fails with the existing empty-report quality issue.

Scheduled runner tests:

- Partial isolation followed by quality `PASS` uploads the AI Brief artifact and
  reconciles notifications.
- Partial isolation followed by quality `FAIL` keeps existing late-alert behavior.
- Whole provider failures still produce `pipeline_failed`.

Docs and contract tests:

- Update `docs/STRATEGY.md` with the source-ref model boundary contract.
- Update `docs/ARCHITECTURE.md` with source catalog and canonical restoration flow.
- Update `docs/operations.md` with source-ref diagnostics and partial publish rules.
- Keep artifact validation tests focused on final `sources[]` objects, not internal
  request-only source refs.

## Compatibility And Migration

- Existing artifacts keep the same final `sources[]` fields.
- Historical artifacts without source refs remain valid because source refs are only a
  provider request/response boundary detail.
- Manual `sab ai-brief` and scheduled `sab ai-brief-scheduled` use the same provider
  normalization path.
- No database migration is required.
- No web schema migration is required. New source issue codes render through the
  existing generic issue display.

## Acceptance Criteria

- The model is no longer asked to return trusted source objects.
- A model-returned bad watch source ref no longer fails an otherwise valid scheduled
  report.
- A model-returned bad recommendation source ref drops only that recommendation.
- Valid remaining recommendations are still required to be source-backed before
  scheduled success.
- Final artifacts continue to validate against `sab.ai_brief.v1`.
- The 2026-06-17 failure shape is covered by a regression test.
- The scheduled runner can upload and notify after partial isolation when the final
  quality gate passes.
- Documentation explains how to interpret `model_source_ref_*` diagnostics.

## Follow-Up

- Suppress or reclassify wrapper `scheduler_container_failed` host alerts when the
  container exits after a structured application failure such as `pipeline_failed`.
- Consider diagnostic upload for failed AI Brief artifacts only after the source-ref
  boundary is stable and report consumers can clearly distinguish diagnostic artifacts
  from successful scheduled reports.
