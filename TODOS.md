# TODOS

## Active

- None.

## Deferred

- Persist runtime-guard-skipped AI Brief scheduled runs as Reports artifacts only if owner-facing skip history becomes useful. Start from `.github/workflows/ai-brief.yml` guard outputs, define a separate artifact state, then add Storage/report_index writes.
- Reduce complexity in strategy signal evaluators with dedicated regression coverage first. Start with `sab/signals/hybrid_sell.py`, `sab/signals/hybrid_buy.py`, and `sab/signals/evaluator.py`; keep behavior-preserving extractions small because these paths directly affect trading decisions.
- Split `sab/ai_brief_sources.py` along provider normalization and validation boundaries if source-provider work resumes. Preserve the current offline/live URL-safety contracts while moving code into smaller modules.

## Completed

- 2026-05-23: AI Brief Phase 2 provider/eval suite completed.
  - KR scheduled source provider: `naver-news`
  - US scheduled source provider: `finnhub`
  - Decision note: `docs/ai-brief-us-source-provider-decision.md`
- 2026-05-22: Quiet Desk Assistant AI Brief state slice completed.
