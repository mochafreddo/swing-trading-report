# Task 2 Report: Upload, Locking, And Failure Semantics

## Summary

- Added scheduled Sell AI Brief upload path when no artifact marker exists.
- Added attempt marker, main lock claim/release, local report validation, Supabase-storage upload protocol call, artifact marker write, notification send, sent marker, and success marker.
- Added lock ownership checks before upload, artifact marker dependent work, notification send, notification sent marker, and success marker.
- Added failure statuses for main lock contention, invalid local report, upload failure, and sent-marker failure.
- Preserved notification claim retention when the notification was sent but `notification:sent` marker write failed.

## RED

Command:

```bash
UV_CACHE_DIR=.uv-cache uv run python -m pytest -q tests/test_scheduled_sell_ai_brief_delivery.py
```

Result before implementation:

```text
5 failed, 6 passed
```

Expected failures covered upload path, lock contention, upload failure, invalid local artifact, and sent-marker failure.

## GREEN

Command:

```bash
UV_CACHE_DIR=.uv-cache uv run python -m pytest -q tests/test_scheduled_sell_ai_brief_delivery.py
```

Result:

```text
11 passed in 0.08s
```

Additional checks:

```bash
UV_CACHE_DIR=.uv-cache uv run ruff check sab/scheduler/sell_ai_brief_delivery.py tests/test_scheduled_sell_ai_brief_delivery.py
UV_CACHE_DIR=.uv-cache uv run ruff format --check sab/scheduler/sell_ai_brief_delivery.py tests/test_scheduled_sell_ai_brief_delivery.py
git diff --check
```

Results:

```text
All checks passed.
2 files already formatted.
git diff --check: no output
```

## Concerns

- Full `just quality` was not run; verification was scoped to the Task 2 runner and tests.

## Review Fix: Blank Upload Key And Reconcile Attempt Marker

### Summary

- Added upload key normalization after `upload_sell_ai_brief()` and before artifact marker, notification, or success marker work.
- Blank upload keys now return `upload_failed`, write no artifact/success marker, and send no notification.
- Added reconcile-only attempt marker recording before download/validation/notification/success work when an artifact marker already exists.
- Added focused regression tests for blank upload keys and reconcile attempt ordering.

### RED

Command:

```bash
UV_CACHE_DIR=.uv-cache uv run python -m pytest -q tests/test_scheduled_sell_ai_brief_delivery.py
```

Result before implementation:

```text
2 failed, 11 passed
```

Expected failures covered blank upload keys completing incorrectly and reconcile sends occurring before an attempt marker existed.

### GREEN

Commands:

```bash
UV_CACHE_DIR=.uv-cache uv run python -m pytest -q tests/test_scheduled_sell_ai_brief_delivery.py
UV_CACHE_DIR=.uv-cache uv run ruff check sab/scheduler/sell_ai_brief_delivery.py tests/test_scheduled_sell_ai_brief_delivery.py
UV_CACHE_DIR=.uv-cache uv run ruff format --check sab/scheduler/sell_ai_brief_delivery.py tests/test_scheduled_sell_ai_brief_delivery.py
```

Results:

```text
13 passed in 0.07s
All checks passed!
2 files already formatted
```

### Concerns

- Full `just quality` was not run; verification remained scoped to the Task 2 runner and touched code.
