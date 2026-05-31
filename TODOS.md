# TODOS

## Active

- None.

## Deferred

- 2026-06-01: Refactor long high-risk runtime functions in small, test-first
  steps, starting with `sab/scheduler/runner.py`,
  `sab/signals/hybrid_sell.py`, and `sab/entry.py`.
- 2026-06-01: Consolidate duplicated market normalization rules after agreeing on
  a shared error-message contract for `KR`, `US`, and `MIXED` handling.
- 2026-06-01: Add an optional live smoke-check path for external RSS/API/market
  data integrations so local refactors can verify real service boundaries when
  credentials and network access are intentionally available.

## Completed

- 2026-05-31: AI Brief source report validation/row normalization and source URL/DNS safety boundaries split out of `sab/ai_brief_sources.py` with offline/live URL-safety contracts preserved.
- 2026-05-31: AI Brief vendor source row normalizers split into `sab/ai_brief_source_normalizers.py` with source-provider regression coverage preserved.
- 2026-05-31: Runtime-guard-skipped scheduled AI Brief runs are persisted as separate `ai-brief-skip` Reports artifacts with Storage/`report_index` writes.
- 2026-05-23: AI Brief Phase 2 provider/eval suite completed.
  - KR scheduled source provider: `naver-news`
  - US scheduled source provider: `finnhub`
  - Decision note: `docs/ai-brief-us-source-provider-decision.md`
- 2026-05-22: Quiet Desk Assistant AI Brief state slice completed.
