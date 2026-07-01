# final-fix-3 report

## Summary

Fixed the final whole-branch review findings by making the launchd runner deterministic from any caller cwd and by splitting ticker-directory lookup failure handling between manual preview and scheduled auto-apply.

## Files changed

- `scripts/toss_daily_auto_sync.sh`
- `tests/test_toss_daily_auto_sync.py`
- `web/src/lib/toss/holdings-sync-service.ts`
- `web/src/lib/__tests__/toss-holdings-sync-service.test.ts`

## What changed

### 1. launchd runner cwd hardening

- Added `cd "${repo_root}"` before `uv run python -` in `scripts/toss_daily_auto_sync.sh`.
- Extended the runner test harness so the stubbed `uv` captures its working directory.
- Added a regression test that launches the script from a non-repo cwd and asserts the `uv` invocation still runs from the repository root.

### 2. Scheduled auto-apply fail-closed behavior

- Added `TossHoldingsSyncPreviewOptions` with `tickerDirectoryLookupFailureMode?: "ignore" | "throw"`.
- Kept manual/dry-run preview behavior degraded by default with `"ignore"`, so ticker-directory lookup exceptions still fall back to unresolved rows.
- Changed `runScheduledTossAutoApply()` to build its preview with `"throw"`, so ticker-directory lookup exceptions now propagate to the scheduled route catch path and return the existing `status: "error"` / HTTP 500 response.
- Added focused service tests covering both behaviors.

## Test output

### `UV_CACHE_DIR=.uv-cache uv run python -m pytest tests/test_toss_daily_auto_sync.py -q`

```text
..........                                                               [100%]
10 passed in 4.74s
```

### `bash -n scripts/toss_daily_auto_sync.sh`

```text
(no output, exit 0)
```

### `pnpm --dir web run test -- web/src/lib/__tests__/toss-holdings-sync-service.test.ts web/src/app/api/holdings/toss-sync/scheduled/__tests__/route.test.ts`

```text
$ vitest run -- web/src/lib/__tests__/toss-holdings-sync-service.test.ts web/src/app/api/holdings/toss-sync/scheduled/__tests__/route.test.ts

 RUN  v4.1.6 /Users/mochafreddo/GitHub/swing-trading-report/web


 Test Files  87 passed (87)
      Tests  528 passed (528)
   Start at  17:11:27
   Duration  1.91s (transform 4.16s, setup 0ms, import 8.59s, tests 1.34s, environment 1.75s)
```

### `pnpm --dir web run typecheck`

```text
$ next typegen && tsc --noEmit
Generating route types...
✓ Types generated successfully
```

## Concerns

- None.
