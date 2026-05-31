# TODOS

## Active

- None.

## Deferred

- Continue splitting `sab/ai_brief_sources.py` along report validation and URL/DNS safety boundaries if source-provider work resumes. Vendor row normalizers now live in `sab/ai_brief_source_normalizers.py`; preserve the current offline/live URL-safety contracts while moving the remaining code into smaller modules.

## Completed

- 2026-05-31: AI Brief vendor source row normalizers split into `sab/ai_brief_source_normalizers.py` with source-provider regression coverage preserved.
- 2026-05-31: Runtime-guard-skipped scheduled AI Brief runs are persisted as separate `ai-brief-skip` Reports artifacts with Storage/`report_index` writes.
- 2026-05-23: AI Brief Phase 2 provider/eval suite completed.
  - KR scheduled source provider: `naver-news`
  - US scheduled source provider: `finnhub`
  - Decision note: `docs/ai-brief-us-source-provider-decision.md`
- 2026-05-22: Quiet Desk Assistant AI Brief state slice completed.
