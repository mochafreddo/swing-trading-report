상태: Backlog

# Operational Logging Readiness Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Raise the repository's operational logging readiness target from the audited 53/100 to at least 90/100.

**Architecture:** Add a small structured logging contract for Python and Next.js, then instrument the highest-risk runtime boundaries: CLI runs, web API routes, entry price fallback, scheduler state failures, upstream error sanitization, and notifications. Preserve trading/report behavior while improving correlation, redaction, and failure diagnosability.

**Tech Stack:** Python stdlib `logging`, pytest `caplog`, Next.js route handlers, Vitest spies, existing repository task runners.

---

### Task 1: Python Structured Logging Contract

**Files:**
- Create: `sab/observability.py`
- Modify: `sab/__main__.py`
- Test: `tests/test_logging_config.py`

- [ ] Add tests that `LOG_FORMAT=json` promotes structured `extra` fields and redacts sensitive keys.
- [ ] Implement `sab.observability` helpers for run ids, structured context, and redaction.
- [ ] Update `_JsonFormatter` to include safe structured fields.
- [ ] Run `UV_CACHE_DIR=.uv-cache uv run python -m pytest tests/test_logging_config.py -q`.

### Task 2: Python CLI Correlation

**Files:**
- Modify: `sab/scan.py`
- Modify: `sab/sell.py`
- Modify: `sab/entry.py`
- Modify: `sab/ai_brief.py`
- Test: targeted command tests using `caplog`

- [ ] Add failing tests for start/end logs containing `run_id`, `operation`, `market` or report path.
- [ ] Thread a generated `run_id` through each run function and include it in report/upload/error logs.
- [ ] Keep existing human-readable messages used by workflows where needed.
- [ ] Run relevant targeted pytest files.

### Task 3: Underlogged Python Failure Paths

**Files:**
- Modify: `sab/entry.py`
- Modify: `sab/data/cache.py`
- Modify: `sab/scheduler/runner.py`
- Test: `tests/test_entry_command.py`, `tests/test_scheduled_ai_brief_runner.py`, new cache test if needed

- [ ] Add failing tests for price lookup provider failures, cache read corruption, attempt marker failure, and repair skip exceptions.
- [ ] Log sanitized `price_lookup_failed`, `cache_load_failed`, and `scheduler_state_failed` events with correlation fields.
- [ ] Ensure intentional degraded behavior remains unchanged.
- [ ] Run targeted pytest files.

### Task 4: Upstream Error Redaction

**Files:**
- Modify: `sab/data/kis/auth.py`
- Modify: `sab/data/kis/quote.py`
- Modify: `sab/data/kis/ranking.py`
- Modify: `sab/data/kis/calendar.py`
- Modify: `sab/report/supabase_storage.py`
- Modify: `sab/scheduler/state.py`
- Modify: `sab/ai_brief_providers.py`
- Test: existing provider/storage tests plus redaction-specific tests

- [ ] Add tests where upstream response bodies contain token-like strings.
- [ ] Replace raw body propagation with bounded sanitized summaries.
- [ ] Preserve HTTP status and upstream error code when available.
- [ ] Run targeted pytest files.

### Task 5: Web API Request Logging Contract

**Files:**
- Create: `web/src/lib/server-log.ts`
- Create: `web/src/lib/api-route-logging.ts`
- Modify: API routes under `web/src/app/api`
- Test: route tests under `web/src/app/api/**/__tests__`

- [ ] Add Vitest tests that API success/failure emits JSON log with `request_id`, route, status, duration, and sanitized error.
- [ ] Implement a small route logging helper and structured `console.info/warn/error` wrapper.
- [ ] Instrument `run`, `reports`, `reports/detail`, `holdings`, holdings mutations, auth, and tickers routes.
- [ ] Run targeted web tests.

### Task 6: Notification Observability

**Files:**
- Modify: `sab/scheduler/runner.py`
- Modify: `.github/workflows/scan.yml`
- Modify: `.github/workflows/sell.yml`
- Modify: `.github/workflows/ai-brief.yml`
- Test: scheduler tests and workflow static checks where available

- [ ] Add log events for notification send start/success/failure/skip with channel and message count.
- [ ] Keep workflow secrets masked and avoid logging URLs/tokens.
- [ ] Run targeted scheduler tests and static workflow checks if available.

### Task 7: Verification and Re-score

**Files:**
- No production change unless verification exposes a gap.

- [ ] Re-run the original logging/exception search excluding generated coverage.
- [ ] Run targeted pytest/Vitest suites.
- [ ] Run `just quality` and `just ci-web` if feasible.
- [ ] Recompute the 8 scorecard metrics and confirm score is at least 90.
