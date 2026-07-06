# Scheduled Sell AI Brief Delivery Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add marker-aware scheduled Sell AI Brief delivery so a generated Sell AI Brief artifact can be uploaded, indexed, and notified once per sell session without duplicate Telegram alerts.

**Architecture:** Build a narrow sibling scheduled runner for Sell AI Brief delivery instead of generalizing `ScheduledAiBriefRunner`. It uses `scheduled-sell:*` runtime_state keys from `build_scheduled_state_key()`, uploads through the existing report uploader, validates `sab.sell_ai_brief.v1` before notification, and reconciles existing artifact/notification markers before doing work.

**Tech Stack:** Python 3.14, `uv`, pytest, Supabase `runtime_state`, existing `sab sell-ai-brief` report contract, existing Telegram HTML notification renderer.

## Global Constraints

- Do not bypass `upload_report_artifact()` / `maybe_upload_report_artifact()` for Supabase Storage and `report_index`.
- Do not send Telegram before a non-empty `sell-ai-brief` storage key has been returned by the uploader.
- Do not regenerate or re-upload when a `scheduled-sell:artifact:<scope>:<session_date>` marker already exists; reconcile notification only.
- Do not send Telegram unless a `scheduled-sell:notification:claim:<scope>:<session_date>` lock is acquired.
- If Telegram sends but the `notification:sent` marker write fails, keep the notification claim held so retries do not duplicate a partial multi-message send.
- Use `scheduled-sell:*` markers for Sell AI Brief delivery scope, not `scheduled-ai-brief:*`.
- Keep the manual `.github/workflows/sell.yml` path manual-only; scheduled delivery belongs in local marker-aware Python code.
- Preserve existing public behavior unless this plan explicitly changes it.

---

## File Structure

- Create `sab/scheduler/sell_ai_brief_delivery.py`: focused scheduled Sell AI Brief delivery runner, request/result dataclasses, storage/notifier protocols, default storage/notifier adapters.
- Modify `sab/scheduler/__init__.py`: export the new runner entry point only if the package already exports similar scheduler surfaces.
- Modify `sab/__main__.py`: add `sell-ai-brief-scheduled` CLI that accepts an existing `--sell-ai-brief-report`, `--scope`, `--session-date`, `--runner-role`, `--scheduled-tick`, optional `--attempt-id`, `--run-url`, and `--dry-run`.
- Modify `scripts/launchd/sab-scheduled-wrapper.sh`: route `--pipeline sell --scope MIXED` to the new CLI only when `SELL_AI_BRIEF_REPORT_PATH` is provided; keep other pipelines disabled unless already implemented.
- Add `tests/test_scheduled_sell_ai_brief_delivery.py`: runner behavior and marker invariants with fake state/storage/notifier.
- Extend `tests/test_cli_dispatch.py`: CLI dispatch for `sell-ai-brief-scheduled`.
- Extend `tests/test_launchd_scheduler_wrapper.py`: generic wrapper dispatch for scheduled sell-ai-brief delivery.
- Update `docs/ARCHITECTURE.md`, `docs/operations.md`, `docs/api.md`, and `TODOS.md`.

---

### Task 1: Scheduled Sell AI Brief Delivery Runner

**Files:**
- Create: `sab/scheduler/sell_ai_brief_delivery.py`
- Test: `tests/test_scheduled_sell_ai_brief_delivery.py`

**Interfaces:**
- Consumes: `build_scheduled_state_key(pipeline="sell", ...)`, `RuntimeStateEntry`, `RuntimeStateLockClaim`, `validate_sell_ai_brief_artifact()`, `build_sell_ai_brief_telegram_report_text()`.
- Produces: `ScheduledSellAiBriefDeliveryRequest`, `ScheduledSellAiBriefDeliveryResult`, `ScheduledSellAiBriefDeliveryRunner.run()`.

- [ ] **Step 1: Write failing tests for dry-run, success skip, and artifact reconciliation**

Add fake state/storage/notifier helpers and tests:

```python
def test_scheduled_sell_ai_brief_delivery_dry_run_does_not_touch_state() -> None:
    state = _FakeStateStore()
    runner = _runner(state=state)

    result = runner.run(_request(dry_run=True))

    assert result.status == "dry_run"
    assert state.upserted == []
    assert state.claims == []


def test_scheduled_sell_ai_brief_delivery_skips_when_success_marker_exists() -> None:
    state = _FakeStateStore()
    state.entries[_key("success")] = RuntimeStateEntry(
        state_key=_key("success"),
        state_payload={"storageKey": "2026/07/2026-07-06.sell-ai-brief.json"},
        expires_at="",
    )
    notifier = _FakeNotifier()
    runner = _runner(state=state, notifier=notifier)

    result = runner.run(_request())

    assert result.status == "success_marker_skip"
    assert notifier.sent == []


def test_scheduled_sell_ai_brief_delivery_reconciles_existing_artifact_once() -> None:
    report = _sell_ai_brief_report()
    state = _FakeStateStore()
    state.entries[_key("artifact")] = RuntimeStateEntry(
        state_key=_key("artifact"),
        state_payload={"storageKey": "2026/07/2026-07-06.sell-ai-brief.json"},
        expires_at="",
    )
    storage = _FakeStorage(downloads={"2026/07/2026-07-06.sell-ai-brief.json": report})
    notifier = _FakeNotifier()
    runner = _runner(state=state, storage=storage, notifier=notifier)

    result = runner.run(_request())

    assert result.status == "notification_reconciled"
    assert storage.uploads == []
    assert notifier.sent == [("2026/07/2026-07-06.sell-ai-brief.json", report)]
    assert _key("notification:sent") in state.entries
    assert _key("success") in state.entries
```

Run:

```bash
UV_CACHE_DIR=.uv-cache uv run python -m pytest -q tests/test_scheduled_sell_ai_brief_delivery.py
```

Expected: fail because the module does not exist.

- [ ] **Step 2: Implement request/result types and marker key helpers**

Create the new module with:

```python
@dataclass(frozen=True)
class ScheduledSellAiBriefDeliveryRequest:
    sell_ai_brief_report_path: str
    scope: str = "MIXED"
    session_date: str = ""
    runner_role: str = "local-primary"
    scheduled_tick: str = "manual"
    attempt_id: str | None = None
    run_url: str = ""
    dry_run: bool = False


@dataclass(frozen=True)
class ScheduledSellAiBriefDeliveryResult:
    status: str
    session_date: str
    storage_key: str | None = None
```

Add a private `_state_key(kind, scope, session_date, runner_role=None, attempt_id=None)` wrapper around `build_scheduled_state_key(pipeline="sell", ...)`.

- [ ] **Step 3: Implement success/artifact/notification reconciliation**

Implement `ScheduledSellAiBriefDeliveryRunner.run()` enough to pass the tests:

1. Normalize `scope` to `KR|US|MIXED`.
2. Resolve `session_date` from request or `report.report_date`.
3. Return `dry_run` before state access.
4. Check `success`; if present, return `success_marker_skip`.
5. Check `artifact`; if present, call `_reconcile_notification()`.
6. `_reconcile_notification()` claims `notification:claim`, downloads and validates the report, sends Telegram through the notifier, writes `notification:sent`, then writes `success`.

- [ ] **Step 4: Run tests and commit**

```bash
UV_CACHE_DIR=.uv-cache uv run python -m pytest -q tests/test_scheduled_sell_ai_brief_delivery.py
git add sab/scheduler/sell_ai_brief_delivery.py tests/test_scheduled_sell_ai_brief_delivery.py
git commit -m "feat(scheduler): 예약 Sell AI Brief 전달 러너 추가"
```

---

### Task 2: Upload, Locking, And Failure Semantics

**Files:**
- Modify: `sab/scheduler/sell_ai_brief_delivery.py`
- Test: `tests/test_scheduled_sell_ai_brief_delivery.py`

**Interfaces:**
- Consumes: Task 1 runner.
- Produces: exactly-once upload and notification failure semantics.

- [ ] **Step 1: Write failing tests for upload path, lock contention, upload failure, quality/validation failure, and sent-marker failure**

Add tests:

```python
def test_scheduled_sell_ai_brief_delivery_uploads_then_marks_artifact_then_notifies() -> None:
    state = _FakeStateStore()
    storage = _FakeStorage(upload_key="2026/07/2026-07-06.sell-ai-brief.json")
    notifier = _FakeNotifier()
    runner = _runner(state=state, storage=storage, notifier=notifier)

    result = runner.run(_request())

    assert result.status == "completed"
    assert storage.uploads == ["reports/2026-07-06.sell-ai-brief.json"]
    assert _key("artifact") in state.entries
    assert _key("notification:sent") in state.entries
    assert _key("success") in state.entries
    assert notifier.sent


def test_scheduled_sell_ai_brief_delivery_lock_contention_skips_without_upload() -> None:
    state = _FakeStateStore(acquire_main_lock=False)
    storage = _FakeStorage()
    runner = _runner(state=state, storage=storage)

    result = runner.run(_request())

    assert result.status == "lock_held_skip"
    assert storage.uploads == []


def test_scheduled_sell_ai_brief_delivery_upload_failure_blocks_markers_and_notification() -> None:
    state = _FakeStateStore()
    storage = _FakeStorage(upload_error=RuntimeError("index down"))
    notifier = _FakeNotifier()
    runner = _runner(state=state, storage=storage, notifier=notifier)

    result = runner.run(_request())

    assert result.status == "upload_failed"
    assert _key("artifact") not in state.entries
    assert _key("success") not in state.entries
    assert notifier.sent == []


def test_scheduled_sell_ai_brief_delivery_invalid_report_blocks_upload() -> None:
    runner = _runner(report={"type": "sell-ai-brief", "schema": "broken"})

    result = runner.run(_request())

    assert result.status == "artifact_invalid"


def test_scheduled_sell_ai_brief_delivery_keeps_claim_when_sent_marker_fails() -> None:
    state = _FakeStateStore(fail_upsert_kinds={"notification:sent"})
    notifier = _FakeNotifier()
    runner = _runner(state=state, notifier=notifier)

    result = runner.run(_request())

    assert result.status == "notification_sent_marker_failed"
    assert notifier.sent
    assert _key("notification:claim") in state.held_locks
```

- [ ] **Step 2: Implement main lock, attempt marker, upload, and failure states**

Implement:

1. Attempt marker for runner roles before work.
2. Main lock using `kind="lock"`.
3. Validate local report before upload.
4. Upload through storage protocol.
5. Write artifact marker only after upload returns storage key.
6. Recheck lock ownership before artifact marker, notification send, `notification:sent`, and `success`.
7. Release main lock in `finally`.
8. Keep notification claim held on `notification_sent_marker_failed`; release it for all other non-sent outcomes.

- [ ] **Step 3: Run tests and commit**

```bash
UV_CACHE_DIR=.uv-cache uv run python -m pytest -q tests/test_scheduled_sell_ai_brief_delivery.py
git add sab/scheduler/sell_ai_brief_delivery.py tests/test_scheduled_sell_ai_brief_delivery.py
git commit -m "fix(scheduler): Sell AI Brief 예약 전달 중복을 차단"
```

---

### Task 3: CLI And Wrapper Integration

**Files:**
- Modify: `sab/__main__.py`
- Modify: `scripts/launchd/sab-scheduled-wrapper.sh`
- Test: `tests/test_cli_dispatch.py`
- Test: `tests/test_launchd_scheduler_wrapper.py`

**Interfaces:**
- Consumes: `run_scheduled_sell_ai_brief_delivery(request=...)`.
- Produces: `python -m sab sell-ai-brief-scheduled`.

- [ ] **Step 1: Write failing CLI dispatch test**

Add a dispatch test that parses:

```bash
sell-ai-brief-scheduled --sell-ai-brief-report reports/2026-07-06.sell-ai-brief.json --scope MIXED --session-date 2026-07-06 --runner-role local-primary --scheduled-tick manual --attempt-id try-1 --run-url https://example.test/run --dry-run
```

Assert the monkeypatched runner receives those exact values and returns its exit code.

- [ ] **Step 2: Add CLI parser and handler**

In `sab/__main__.py`, add `sell-ai-brief-scheduled` parser and `_run_scheduled_sell_ai_brief_command()` that calls the new runner entry point.

- [ ] **Step 3: Write wrapper dispatch test**

Add a launchd wrapper test that runs:

```bash
SELL_AI_BRIEF_REPORT_PATH=reports/2026-07-06.sell-ai-brief.json scripts/launchd/sab-scheduled-wrapper.sh --pipeline sell --scope MIXED
```

with command execution intercepted in the existing wrapper test style, and assert it invokes `uv run python -m sab sell-ai-brief-scheduled`.

- [ ] **Step 4: Implement wrapper route**

Keep `scan` and `ai-brief` behavior unchanged. For `--pipeline sell --scope MIXED`, require `SELL_AI_BRIEF_REPORT_PATH`, derive default `session_date` from `SAB_SESSION_DATE` or UTC date, and execute:

```bash
uv run python -m sab sell-ai-brief-scheduled \
  --sell-ai-brief-report "${SELL_AI_BRIEF_REPORT_PATH}" \
  --scope "${scope}" \
  --session-date "${session_date}" \
  --runner-role "${SAB_RUNNER_ROLE:-local-primary}" \
  --scheduled-tick "${SAB_SCHEDULED_TICK:-manual}" \
  --attempt-id "${SAB_ATTEMPT_ID:-}" \
  --run-url "${SAB_RUN_URL:-}"
```

- [ ] **Step 5: Run tests and commit**

```bash
UV_CACHE_DIR=.uv-cache uv run python -m pytest -q tests/test_cli_dispatch.py::test_dispatch_command_routes_scheduled_sell_ai_brief_options tests/test_launchd_scheduler_wrapper.py -k scheduled
git add sab/__main__.py scripts/launchd/sab-scheduled-wrapper.sh tests/test_cli_dispatch.py tests/test_launchd_scheduler_wrapper.py
git commit -m "feat(cli): 예약 Sell AI Brief 전달 명령 추가"
```

---

### Task 4: Documentation, TODO Closure, And Gates

**Files:**
- Modify: `docs/ARCHITECTURE.md`
- Modify: `docs/operations.md`
- Modify: `docs/api.md`
- Modify: `TODOS.md`

**Interfaces:**
- Consumes: Tasks 1-3 behavior.
- Produces: operator-facing contract and closed TODO entry.

- [ ] **Step 1: Update docs**

Document:

1. `sell-ai-brief-scheduled` CLI.
2. `scheduled-sell:*` markers: `attempt`, `lock`, `artifact`, `notification:claim`, `notification:sent`, `success`.
3. The upload-before-notify and quality/validation gates.
4. Manual `sell.yml` remains opt-in manual delivery.

- [ ] **Step 2: Move TODO item to completed**

Move `Scheduled Sell AI Brief delivery` from `Deferred` to `Completed` with the current date and a concise completion note.

- [ ] **Step 3: Run focused and broad gates**

```bash
UV_CACHE_DIR=.uv-cache uv run python -m pytest -q tests/test_scheduled_sell_ai_brief_delivery.py tests/test_cli_dispatch.py tests/test_launchd_scheduler_wrapper.py tests/test_scheduled_generic_state.py tests/test_notification_text.py -k 'sell_ai_brief or scheduled'
just quality
```

- [ ] **Step 4: Commit**

```bash
git add docs/ARCHITECTURE.md docs/operations.md docs/api.md TODOS.md
git commit -m "docs(scheduler): 예약 Sell AI Brief 전달 계약 문서화"
```

