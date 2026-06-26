# Local Scheduled Pipelines Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make scheduled AI Brief resilient to primary OpenAI timeouts, add durable one-shot runner observability, and prepare scan/sell local-primary migration without duplicate uploads or notifications.

**Architecture:** Implement the incident fix first inside `run_ai_brief`, before artifact construction, so fallback writes exactly one final artifact. Then add scheduler status/logging surfaces and a manual latency probe. Only after those safety boundaries exist, add generic scheduled state/wrapper foundations and keep scan/sell local upload behind a locked runner plus marker-aware GitHub fallback.

**Tech Stack:** Python 3.14, `uv`, pytest, GitHub Actions YAML, Bash launchd wrappers, Docker Compose, Supabase `runtime_state`, existing `sab` CLI.

---

## Scope And Sequencing

This plan covers the approved spec at `docs/superpowers/specs/2026-06-26-local-scheduled-pipelines-design.md`.

The work is intentionally gated:

1. Tasks 1-4 fix the direct AI Brief timeout incident.
2. Tasks 5-7 add status/logging/probe observability without changing scan/sell production behavior.
3. Tasks 8-10 add generic scheduled foundations but do not enable scan/sell local upload.
4. Tasks 11-12 convert scan/sell scheduled jobs toward safe local-primary rollout. Do not start these until Tasks 1-10 are merged and stable.

Do not enable scheduled scan/sell local upload until the matching GitHub scheduled workflow is marker-aware and cannot upload independently.

## File Structure

Core AI Brief fallback:

- Modify `sab/ai_brief.py`: normalize fallback env, build model attempt configs, run attempts in memory, write one final artifact.
- Modify `sab/ai_brief_providers.py`: no provider behavior change expected; use existing `AiBriefProviderTimeoutError`.
- Modify `tests/test_ai_brief.py`: fallback config normalization, fallback orchestration, metadata, one-artifact behavior.

Scheduled deadline and workflow propagation:

- Modify `sab/scheduler/schedule_policy.py`: expose role-window deadline helper.
- Modify `sab/scheduler/runner.py`: compute/passthrough model deadline and write status file.
- Modify `sab/__main__.py`: add CLI/env plumbing only where needed.
- Modify `.github/workflows/ai-brief.yml`: forward fallback model env vars.
- Modify `tests/test_scheduled_ai_brief_runner.py`, `tests/test_scheduled_ai_brief_schedule_policy.py`, `tests/test_ai_brief_workflow.py`, `tests/test_cli_dispatch.py`.

One-shot logging and host status:

- Create `sab/scheduler/status_file.py`: atomic status JSON writer.
- Create `sab/scheduler/host_alert.py`: secret-safe Telegram host alert helper.
- Modify `scripts/launchd/sab-ai-brief-wrapper.sh`: attempt-scoped paths, status-file env, status parsing.
- Modify `tests/test_launchd_scheduler_wrapper.py`: status file, non-last-line stdout, stderr handling, secret-safe alert.

Latency probe:

- Create `sab/ai_brief_latency_probe.py`: bounded live probe runner.
- Modify `sab/__main__.py`: add `ai-brief-latency-probe` command.
- Modify `docker-compose.scheduler.yml`: remove fixed scheduler `container_name` so probe runs cannot collide with the one-shot service.
- Add `tests/test_ai_brief_latency_probe.py`.

Generic scheduled foundation:

- Create `sab/scheduler/generic_state.py`: `scope`-based generic scheduled state keys.
- Create `scripts/launchd/sab-scheduled-wrapper.sh`: initial generic wrapper with argument validation and disabled execution.
- Add `tests/test_scheduled_generic_state.py`.
- Modify `tests/test_launchd_scheduler_wrapper.py`.

Scan/sell migration safety:

- Add tests before implementation under `tests/test_scheduled_scan_sell_contract.py` and focused workflow tests.
- Modify `.github/workflows/scan.yml` and `.github/workflows/sell.yml` only after generic state tests pass.
- Add implementation modules only when turning on real local scan/sell runners; do not hide this inside the AI Brief fallback slice.

---

### Task 1: Add AI Brief Fallback Configuration And Attempt Types

**Files:**
- Modify: `sab/ai_brief.py`
- Test: `tests/test_ai_brief.py`

- [ ] **Step 1: Write failing tests for fallback config normalization**

Add tests near the existing model timeout env tests in `tests/test_ai_brief.py`.

```python
def test_ai_brief_reads_fallback_model_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("OPENAI_AI_BRIEF_FALLBACK_MODEL", "gpt-5.4-mini")
    config = ai_brief._build_model_attempt_configs(
        provider="openai",
        primary_model_name="gpt-5.5",
        primary_timeout_seconds=60.0,
        fallback_model_name=None,
        fallback_timeout_seconds=None,
        total_timeout_seconds=None,
    )

    assert [attempt.role for attempt in config] == ["primary", "fallback"]
    assert config[0].model_name == "gpt-5.5"
    assert config[0].timeout_seconds == 60.0
    assert config[1].model_name == "gpt-5.4-mini"
    assert config[1].timeout_seconds == pytest.approx(30.0)


def test_ai_brief_rejects_invalid_total_model_timeout(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("AI_BRIEF_MODEL_TOTAL_TIMEOUT_SECONDS", "0")

    with pytest.raises(ValueError, match="model_total_timeout_seconds must be positive"):
        ai_brief._normalize_model_total_timeout_seconds(None)
```

- [ ] **Step 2: Run tests and verify they fail**

Run:

```bash
UV_CACHE_DIR=.uv-cache uv run python -m pytest -q tests/test_ai_brief.py -k 'fallback_model_env or total_model_timeout'
```

Expected: FAIL because `_build_model_attempt_configs` and `_normalize_model_total_timeout_seconds` do not exist.

- [ ] **Step 3: Add model attempt dataclasses and env normalization**

In `sab/ai_brief.py`, add imports and helpers near `_normalize_model_timeout_seconds`.

```python
@dataclass(frozen=True)
class _ModelAttemptConfig:
    role: str
    model_name: str
    timeout_seconds: float


@dataclass(frozen=True)
class _ModelAttemptRecord:
    role: str
    model_name: str
    timeout_seconds: float
    status: str
    duration_ms: int
    error_type: str | None = None
    retryable: bool | None = None


def _normalize_model_total_timeout_seconds(value: float | None) -> float | None:
    if value is None:
        value = _read_env_float(
            "AI_BRIEF_MODEL_TOTAL_TIMEOUT_SECONDS",
            error_message="AI_BRIEF_MODEL_TOTAL_TIMEOUT_SECONDS must be a number",
        )
    if value is None:
        return None
    if not math.isfinite(value) or value <= 0:
        raise ValueError("model_total_timeout_seconds must be positive")
    return float(value)


def _normalize_fallback_model_timeout_seconds(value: float | None) -> float:
    if value is None:
        value = _read_env_float(
            "AI_BRIEF_MODEL_FALLBACK_TIMEOUT_SECONDS",
            error_message="AI_BRIEF_MODEL_FALLBACK_TIMEOUT_SECONDS must be a number",
        )
    if value is None:
        return 30.0
    if not math.isfinite(value) or value <= 0:
        raise ValueError("model_fallback_timeout_seconds must be positive")
    return float(value)


def _fallback_model_name(provider: str, value: str | None) -> str | None:
    if provider != _MODEL_PROVIDER_OPENAI:
        return None
    raw = value if value is not None else os.getenv("OPENAI_AI_BRIEF_FALLBACK_MODEL")
    text = str(raw or "").strip()
    return text or None


def _build_model_attempt_configs(
    *,
    provider: str,
    primary_model_name: str,
    primary_timeout_seconds: float,
    fallback_model_name: str | None,
    fallback_timeout_seconds: float | None,
    total_timeout_seconds: float | None,
) -> list[_ModelAttemptConfig]:
    attempts = [
        _ModelAttemptConfig(
            role="primary",
            model_name=primary_model_name,
            timeout_seconds=primary_timeout_seconds,
        )
    ]
    fallback_name = _fallback_model_name(provider, fallback_model_name)
    if fallback_name is None or fallback_name == primary_model_name:
        return attempts
    fallback_timeout = _normalize_fallback_model_timeout_seconds(
        fallback_timeout_seconds
    )
    if total_timeout_seconds is not None:
        fallback_timeout = min(fallback_timeout, total_timeout_seconds)
    attempts.append(
        _ModelAttemptConfig(
            role="fallback",
            model_name=fallback_name,
            timeout_seconds=fallback_timeout,
        )
    )
    return attempts
```

Also add `from dataclasses import dataclass` at the top of `sab/ai_brief.py`.

- [ ] **Step 4: Run tests and verify they pass**

Run:

```bash
UV_CACHE_DIR=.uv-cache uv run python -m pytest -q tests/test_ai_brief.py -k 'fallback_model_env or total_model_timeout'
```

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add sab/ai_brief.py tests/test_ai_brief.py
git commit -m "feat(ai-brief): 모델 fallback 설정을 정규화"
```

---

### Task 2: Run Primary And Fallback Model Attempts Inside One Artifact Build

**Files:**
- Modify: `sab/ai_brief.py`
- Test: `tests/test_ai_brief.py`

- [ ] **Step 1: Write failing tests for timeout fallback and one final artifact**

Add a small provider double in `tests/test_ai_brief.py`.

```python
class _TimeoutThenSuccessProviderFactory:
    def __init__(self) -> None:
        self.calls: list[tuple[str, float]] = []

    def __call__(
        self,
        *,
        model_provider: str,
        model_name: str,
        model_timeout_seconds: float,
    ) -> object:
        self.calls.append((model_name, model_timeout_seconds))
        if len(self.calls) == 1:
            class TimeoutProvider:
                def build_recommendations(self, **_: object) -> object:
                    raise ai_brief.AiBriefProviderTimeoutError("OpenAI request timed out")

            return TimeoutProvider()

        class SuccessProvider:
            def build_recommendations(self, **_: object) -> object:
                return ai_brief.AiBriefProviderResult(
                    recommendations=[],
                    source_issues=[],
                    vetoed_candidates=[
                        {
                            "ticker": "AAPL.NAS",
                            "reason": "fallback model vetoed the candidate",
                        }
                    ],
                    watch_candidates=[],
                )

        return SuccessProvider()
```

Use the existing `_write_entry_report` helper in `tests/test_ai_brief.py`; it already creates one recommendable `AAPL.NAS` row and one review-only row.

```python
def test_run_ai_brief_falls_back_after_model_timeout(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    entry_report = _write_entry_report(
        tmp_path,
        ticker="AAPL.NAS",
        action="ENTER",
        market="US",
    )
    factory = _TimeoutThenSuccessProviderFactory()
    written_paths: list[str] = []
    monkeypatch.setenv("OPENAI_API_KEY", "test-key")
    monkeypatch.setenv("OPENAI_AI_BRIEF_FALLBACK_MODEL", "gpt-5.4-mini")
    monkeypatch.setattr(ai_brief, "_build_provider", factory)

    status = ai_brief.run_ai_brief(
        entry_report_path=str(entry_report),
        buy_report_path=None,
        market="US",
        model_provider="openai",
        model_name="gpt-5.5",
        model_timeout_seconds=60.0,
        report_path_callback=written_paths.append,
    )

    assert status == 0
    assert factory.calls == [("gpt-5.5", 60.0), ("gpt-5.4-mini", 30.0)]
    assert len(written_paths) == 1
    payload = json.loads(Path(written_paths[0]).read_text(encoding="utf-8"))
    assert payload["model_name"] == "gpt-5.4-mini"
    assert payload["model_attempts"][0]["status"] == "timeout"
    assert payload["model_attempts"][1]["status"] == "success"
```

- [ ] **Step 2: Run test and verify it fails**

Run:

```bash
UV_CACHE_DIR=.uv-cache uv run python -m pytest -q tests/test_ai_brief.py::test_run_ai_brief_falls_back_after_model_timeout
```

Expected: FAIL because fallback orchestration and `model_attempts` do not exist.

- [ ] **Step 3: Implement model attempt runner**

Add helper in `sab/ai_brief.py` near `_build_provider`.

```python
def _attempt_record_dict(record: _ModelAttemptRecord) -> dict[str, object]:
    payload: dict[str, object] = {
        "role": record.role,
        "model_name": record.model_name,
        "timeout_seconds": record.timeout_seconds,
        "status": record.status,
        "duration_ms": record.duration_ms,
    }
    if record.error_type is not None:
        payload["error_type"] = record.error_type
    if record.retryable is not None:
        payload["retryable"] = record.retryable
    return payload


def _run_model_attempts(
    *,
    model_provider: str,
    attempts: list[_ModelAttemptConfig],
    recommendable_candidates: list[dict[str, object]],
    watch_candidates: list[dict[str, object]],
    run_id: str,
    operation: str,
    market: str,
) -> tuple[AiBriefProviderResult | None, str, list[_ModelAttemptRecord], AiBriefProviderError | None]:
    records: list[_ModelAttemptRecord] = []
    last_error: AiBriefProviderError | None = None
    for index, attempt in enumerate(attempts):
        started = time.monotonic()
        logger.info(
            "AI brief model attempt started",
            extra={
                "event": "ai_brief_model_attempt_started",
                "run_id": run_id,
                "operation": operation,
                "market": market,
                "attempt_role": attempt.role,
                "model_provider": model_provider,
                "model_name": attempt.model_name,
                "timeout_seconds": attempt.timeout_seconds,
                "ticker_count": len(recommendable_candidates),
                "watch_count": len(watch_candidates),
            },
        )
        try:
            provider = _build_provider(
                model_provider=model_provider,
                model_name=attempt.model_name,
                model_timeout_seconds=attempt.timeout_seconds,
            )
            result = provider.build_recommendations(
                recommendable_candidates=recommendable_candidates,
                watch_candidates=watch_candidates,
            )
        except AiBriefProviderError as exc:
            duration_ms = int((time.monotonic() - started) * 1000)
            retryable = _model_provider_retryable(exc)
            fallback_next = (
                retryable
                and isinstance(exc, AiBriefProviderTimeoutError)
                and index + 1 < len(attempts)
            )
            status = "timeout" if isinstance(exc, AiBriefProviderTimeoutError) else "failed"
            records.append(
                _ModelAttemptRecord(
                    role=attempt.role,
                    model_name=attempt.model_name,
                    timeout_seconds=attempt.timeout_seconds,
                    status=status,
                    duration_ms=duration_ms,
                    error_type=type(exc).__name__,
                    retryable=retryable,
                )
            )
            logger.error(
                "AI brief model attempt failed: %s",
                exc,
                extra={
                    "event": "ai_brief_model_attempt_failed",
                    "run_id": run_id,
                    "operation": operation,
                    "market": market,
                    "attempt_role": attempt.role,
                    "model_provider": model_provider,
                    "model_name": attempt.model_name,
                    "duration_ms": duration_ms,
                    "error_type": type(exc).__name__,
                    "retryable": retryable,
                    "fallback_next": fallback_next,
                },
            )
            last_error = exc
            if fallback_next:
                logger.warning(
                    "AI brief model fallback selected",
                    extra={
                        "event": "ai_brief_model_fallback_selected",
                        "run_id": run_id,
                        "operation": operation,
                        "market": market,
                        "from_model_name": attempt.model_name,
                        "to_model_name": attempts[index + 1].model_name,
                    },
                )
                continue
            return None, attempt.model_name, records, exc

        duration_ms = int((time.monotonic() - started) * 1000)
        records.append(
            _ModelAttemptRecord(
                role=attempt.role,
                model_name=attempt.model_name,
                timeout_seconds=attempt.timeout_seconds,
                status="success",
                duration_ms=duration_ms,
            )
        )
        logger.info(
            "AI brief model attempt completed",
            extra={
                "event": "ai_brief_model_attempt_completed",
                "run_id": run_id,
                "operation": operation,
                "market": market,
                "attempt_role": attempt.role,
                "model_provider": model_provider,
                "model_name": attempt.model_name,
                "duration_ms": duration_ms,
                "recommendation_count": len(result.recommendations),
                "vetoed_count": len(result.vetoed_candidates),
                "watch_output_count": len(result.watch_candidates),
            },
        )
        return result, attempt.model_name, records, None
    return None, attempts[0].model_name, records, last_error
```

Add `import time` at the top of `sab/ai_brief.py`.

- [ ] **Step 4: Wire helper into `run_ai_brief`**

Replace the provider call block in `run_ai_brief` with:

```python
model_total_timeout_seconds = _normalize_model_total_timeout_seconds(None)
attempt_configs = _build_model_attempt_configs(
    provider=normalized_model_provider,
    primary_model_name=normalized_model_name,
    primary_timeout_seconds=normalized_model_timeout_seconds,
    fallback_model_name=None,
    fallback_timeout_seconds=None,
    total_timeout_seconds=model_total_timeout_seconds,
)
provider_result, effective_model_name, model_attempts, provider_error = _run_model_attempts(
    model_provider=normalized_model_provider,
    attempts=attempt_configs,
    recommendable_candidates=preselected_candidates,
    watch_candidates=watch_candidates,
    run_id=run_id,
    operation=operation,
    market=target_market,
)
if provider_result is not None:
    recommendations = provider_result.recommendations
    source_issues = [*source_provider_issues, *provider_result.source_issues]
    vetoed_candidates = provider_result.vetoed_candidates
    model_watch_candidates = provider_result.watch_candidates
    normalized_model_name = effective_model_name
else:
    assert provider_error is not None
    recommendations = []
    source_issues = source_provider_issues
    vetoed_candidates = []
    model_watch_candidates = _fallback_watch_candidates(watch_candidates)
    system_issues.append(_provider_system_issue(provider_error))
```

Add to the final artifact:

```python
"model_attempts": [_attempt_record_dict(record) for record in model_attempts],
```

- [ ] **Step 5: Run targeted tests**

Run:

```bash
UV_CACHE_DIR=.uv-cache uv run python -m pytest -q tests/test_ai_brief.py::test_run_ai_brief_falls_back_after_model_timeout
```

Expected: PASS.

- [ ] **Step 6: Add and run non-timeout no-fallback test**

Add:

```python
def test_run_ai_brief_does_not_fallback_on_contract_error(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    entry_report = _write_entry_report(
        tmp_path,
        ticker="AAPL.NAS",
        action="ENTER",
        market="US",
    )
    calls: list[str] = []

    def build_provider(**kwargs: object) -> object:
        calls.append(str(kwargs["model_name"]))

        class BadProvider:
            def build_recommendations(self, **_: object) -> object:
                raise ai_brief.AiBriefProviderContractError("bad model JSON")

        return BadProvider()

    monkeypatch.setenv("OPENAI_API_KEY", "test-key")
    monkeypatch.setenv("OPENAI_AI_BRIEF_FALLBACK_MODEL", "gpt-5.4-mini")
    monkeypatch.setattr(ai_brief, "_build_provider", build_provider)

    status = ai_brief.run_ai_brief(
        entry_report_path=str(entry_report),
        buy_report_path=None,
        market="US",
        model_provider="openai",
        model_name="gpt-5.5",
        model_timeout_seconds=60.0,
    )

    assert status == 0
    assert calls == ["gpt-5.5"]
```

Run:

```bash
UV_CACHE_DIR=.uv-cache uv run python -m pytest -q tests/test_ai_brief.py -k 'falls_back_after_model_timeout or does_not_fallback_on_contract_error'
```

Expected: PASS.

- [ ] **Step 7: Commit**

```bash
git add sab/ai_brief.py tests/test_ai_brief.py
git commit -m "feat(ai-brief): timeout 시 fallback 모델을 시도"
```

---

### Task 3: Make Fallback Deadline-Aware In Scheduled Runs

**Files:**
- Modify: `sab/ai_brief.py`
- Modify: `sab/scheduler/schedule_policy.py`
- Modify: `sab/scheduler/runner.py`
- Test: `tests/test_scheduled_ai_brief_runner.py`
- Test: `tests/test_ai_brief.py`

- [ ] **Step 1: Write failing test for deadline skip**

Add to `tests/test_ai_brief.py`:

```python
def test_ai_brief_skips_fallback_when_deadline_budget_is_too_small(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    entry_report = _write_entry_report(
        tmp_path,
        ticker="AAPL.NAS",
        action="ENTER",
        market="US",
    )
    calls: list[str] = []

    def build_provider(**kwargs: object) -> object:
        calls.append(str(kwargs["model_name"]))

        class TimeoutProvider:
            def build_recommendations(self, **_: object) -> object:
                raise ai_brief.AiBriefProviderTimeoutError("OpenAI request timed out")

        return TimeoutProvider()

    monkeypatch.setenv("OPENAI_API_KEY", "test-key")
    monkeypatch.setenv("OPENAI_AI_BRIEF_FALLBACK_MODEL", "gpt-5.4-mini")
    monkeypatch.setattr(ai_brief, "_build_provider", build_provider)

    status = ai_brief.run_ai_brief(
        entry_report_path=str(entry_report),
        buy_report_path=None,
        market="US",
        model_provider="openai",
        model_name="gpt-5.5",
        model_timeout_seconds=60.0,
        model_deadline_remaining_seconds=20.0,
        model_publish_margin_seconds=15.0,
    )

    assert status == 0
    assert calls == ["gpt-5.5"]
```

- [ ] **Step 2: Run test and verify it fails**

Run:

```bash
UV_CACHE_DIR=.uv-cache uv run python -m pytest -q tests/test_ai_brief.py::test_ai_brief_skips_fallback_when_deadline_budget_is_too_small
```

Expected: FAIL because `run_ai_brief` has no deadline parameters.

- [ ] **Step 3: Add deadline parameters to `run_ai_brief`**

Update the function signature:

```python
def run_ai_brief(
    *,
    entry_report_path: str,
    buy_report_path: str | None,
    market: str | None,
    model_provider: str | None,
    model_name: str | None,
    model_timeout_seconds: float | None = None,
    model_deadline_remaining_seconds: float | None = None,
    model_publish_margin_seconds: float = 15.0,
    ...
) -> int:
```

Update `_run_model_attempts` to skip fallback when:

```python
remaining_after_margin = (
    None
    if model_deadline_remaining_seconds is None
    else model_deadline_remaining_seconds - model_publish_margin_seconds
)
if (
    fallback_next
    and remaining_after_margin is not None
    and attempts[index + 1].timeout_seconds > remaining_after_margin
):
    fallback_next = False
```

Record a final `_ModelAttemptRecord` with `status="deadline_skipped"` for the fallback candidate.

- [ ] **Step 4: Expose deadline remaining from scheduler**

In `sab/scheduler/schedule_policy.py`, add:

```python
def role_deadline_at(market: str, schedule_role: str, now: dt.datetime) -> dt.datetime | None:
    normalized_market = _normalize_market(market)
    normalized_role = _normalize_role(schedule_role)
    window = role_window(normalized_market, normalized_role)
    if window is None:
        return None
    zone = market_zone(normalized_market)
    local_now = now.astimezone(zone)
    deadline_local = dt.datetime.combine(
        local_now.date(),
        window.end,
        tzinfo=zone,
    ) + role_window_end_grace(normalized_market, normalized_role)
    return deadline_local.astimezone(dt.UTC)
```

In `sab/scheduler/runner.py`, compute before dispatch:

```python
deadline_at = schedule_policy.role_deadline_at(
    market=market,
    schedule_role=schedule_role,
    now=now,
)
model_deadline_remaining_seconds = (
    None
    if deadline_at is None
    else max(0.0, (deadline_at - self._now_fn()).total_seconds())
)
```

Pass `model_deadline_remaining_seconds` through the scheduled pipeline into `run_ai_brief`.

- [ ] **Step 5: Run targeted tests**

Run:

```bash
UV_CACHE_DIR=.uv-cache uv run python -m pytest -q tests/test_ai_brief.py::test_ai_brief_skips_fallback_when_deadline_budget_is_too_small tests/test_scheduled_ai_brief_schedule_policy.py
```

Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add sab/ai_brief.py sab/scheduler/schedule_policy.py sab/scheduler/runner.py tests/test_ai_brief.py tests/test_scheduled_ai_brief_schedule_policy.py tests/test_scheduled_ai_brief_runner.py
git commit -m "feat(ai-brief): fallback 시각을 장전 deadline에 맞춤"
```

---

### Task 4: Forward Fallback Configuration Through CLI And GitHub Scheduled Fallback

**Files:**
- Modify: `sab/__main__.py`
- Modify: `.github/workflows/ai-brief.yml`
- Test: `tests/test_cli_dispatch.py`
- Test: `tests/test_ai_brief_workflow.py`

- [ ] **Step 1: Write failing workflow test**

In `tests/test_ai_brief_workflow.py`, extend `test_ai_brief_workflow_scheduled_runs_use_monitor_fallback_context`:

```python
assert scheduled_job_env["OPENAI_AI_BRIEF_FALLBACK_MODEL"] == "${{ vars.OPENAI_AI_BRIEF_FALLBACK_MODEL }}"
assert scheduled_job_env["AI_BRIEF_MODEL_FALLBACK_TIMEOUT_SECONDS"] == "${{ vars.AI_BRIEF_MODEL_FALLBACK_TIMEOUT_SECONDS }}"
assert scheduled_job_env["AI_BRIEF_MODEL_TOTAL_TIMEOUT_SECONDS"] == "${{ vars.AI_BRIEF_MODEL_TOTAL_TIMEOUT_SECONDS }}"
```

- [ ] **Step 2: Run workflow test and verify it fails**

Run:

```bash
UV_CACHE_DIR=.uv-cache uv run python -m pytest -q tests/test_ai_brief_workflow.py::test_ai_brief_workflow_scheduled_runs_use_monitor_fallback_context
```

Expected: FAIL because env keys are missing.

- [ ] **Step 3: Add workflow env keys**

In `.github/workflows/ai-brief.yml`, under scheduled job env near `OPENAI_AI_BRIEF_MODEL`, add:

```yaml
OPENAI_AI_BRIEF_FALLBACK_MODEL: ${{ vars.OPENAI_AI_BRIEF_FALLBACK_MODEL }}
AI_BRIEF_MODEL_FALLBACK_TIMEOUT_SECONDS: ${{ vars.AI_BRIEF_MODEL_FALLBACK_TIMEOUT_SECONDS }}
AI_BRIEF_MODEL_TOTAL_TIMEOUT_SECONDS: ${{ vars.AI_BRIEF_MODEL_TOTAL_TIMEOUT_SECONDS }}
```

- [ ] **Step 4: Add CLI dispatch coverage for env-driven fallback**

Do not add fallback-specific CLI arguments. In `tests/test_cli_dispatch.py`, keep the scheduled request object unchanged and add this assertion to the scheduled AI Brief dispatch test:

```python
assert not hasattr(request, "fallback_model")
assert not hasattr(request, "fallback_timeout_seconds")
```

This keeps fallback config env-driven and avoids leaking model settings into runtime state payloads.

- [ ] **Step 5: Run tests**

Run:

```bash
UV_CACHE_DIR=.uv-cache uv run python -m pytest -q tests/test_ai_brief_workflow.py tests/test_cli_dispatch.py
```

Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add .github/workflows/ai-brief.yml tests/test_ai_brief_workflow.py tests/test_cli_dispatch.py
git commit -m "fix(ai-brief): GitHub fallback에 모델 fallback 설정 전달"
```

---

### Task 5: Add Dedicated Scheduler Status JSON

**Files:**
- Create: `sab/scheduler/status_file.py`
- Modify: `sab/scheduler/runner.py`
- Test: `tests/test_scheduled_ai_brief_runner.py`

- [ ] **Step 1: Write failing status-file tests**

Add to `tests/test_scheduled_ai_brief_runner.py`:

```python
def test_run_scheduled_ai_brief_writes_status_file(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    status_file = tmp_path / "status.json"
    monkeypatch.setenv("SAB_SCHEDULER_STATUS_FILE", str(status_file))

    result = scheduler_runner.ScheduledAiBriefResult(
        status="pipeline_failed",
        session_date="2026-06-26",
        storage_key=None,
    )
    scheduler_runner._write_scheduled_status_file(result)

    payload = json.loads(status_file.read_text(encoding="utf-8"))
    assert payload == {
        "status": "pipeline_failed",
        "session_date": "2026-06-26",
        "storage_key": None,
    }
```

- [ ] **Step 2: Run test and verify it fails**

Run:

```bash
UV_CACHE_DIR=.uv-cache uv run python -m pytest -q tests/test_scheduled_ai_brief_runner.py::test_run_scheduled_ai_brief_writes_status_file
```

Expected: FAIL because `_write_scheduled_status_file` does not exist.

- [ ] **Step 3: Create status writer**

Create `sab/scheduler/status_file.py`:

```python
from __future__ import annotations

import json
import os
from pathlib import Path
from tempfile import NamedTemporaryFile
from typing import Mapping


def write_status_json(path: str | os.PathLike[str], payload: Mapping[str, object]) -> None:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    with NamedTemporaryFile(
        "w",
        encoding="utf-8",
        dir=target.parent,
        prefix=f".{target.name}.",
        delete=False,
    ) as tmp:
        json.dump(dict(payload), tmp, ensure_ascii=False, sort_keys=True)
        tmp.write("\n")
        tmp_path = Path(tmp.name)
    tmp_path.replace(target)
```

In `sab/scheduler/runner.py`, add:

```python
def _scheduled_status_payload(result: ScheduledAiBriefResult) -> dict[str, object]:
    return {
        "status": result.status,
        "session_date": result.session_date,
        "storage_key": result.storage_key,
    }


def _write_scheduled_status_file(result: ScheduledAiBriefResult) -> None:
    path = os.getenv("SAB_SCHEDULER_STATUS_FILE")
    if not path:
        return
    status_file.write_status_json(path, _scheduled_status_payload(result))
```

Call `_write_scheduled_status_file(result)` in `run_scheduled_ai_brief` before printing stdout JSON.

- [ ] **Step 4: Run targeted tests**

Run:

```bash
UV_CACHE_DIR=.uv-cache uv run python -m pytest -q tests/test_scheduled_ai_brief_runner.py::test_run_scheduled_ai_brief_writes_status_file
```

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add sab/scheduler/status_file.py sab/scheduler/runner.py tests/test_scheduled_ai_brief_runner.py
git commit -m "feat(scheduler): 상태 JSON 파일을 원자적으로 기록"
```

---

### Task 6: Make Launchd Wrapper Use Attempt-Scoped Logs And Status JSON

**Files:**
- Modify: `scripts/launchd/sab-ai-brief-wrapper.sh`
- Modify: `tests/test_launchd_scheduler_wrapper.py`

- [ ] **Step 1: Write failing wrapper tests**

Add tests:

```python
def test_launchd_wrapper_uses_status_file_before_stdout_tail(tmp_path: Path) -> None:
    status_path = tmp_path / "logs" / "scheduled" / "ai-brief" / "2026-06-26" / "US-local-primary-0810.status.json"
    result, alerts_path = _run_wrapper_with_stubs(
        tmp_path,
        docker_script=(
            "#!/usr/bin/env bash\n"
            'if [[ "$1" == "info" ]]; then exit 0; fi\n'
            'printf \'%s\\n\' \'{"status": "pipeline_failed", "storage_key": null}\' > "$SAB_SCHEDULER_STATUS_FILE"\n'
            "printf '%s\\n' 'diagnostic line after json'\n"
            "exit 1\n"
        ),
        extra_env={"EXPECTED_STATUS_PATH_FRAGMENT": status_path.name},
    )

    assert result.returncode == 1
    assert not alerts_path.exists()


def test_launchd_wrapper_writes_attempt_scoped_command_log(tmp_path: Path) -> None:
    result, _ = _run_wrapper_with_stubs(
        tmp_path,
        docker_script=(
            "#!/usr/bin/env bash\n"
            'if [[ "$1" == "info" ]]; then exit 0; fi\n'
            'printf \'%s\\n\' \'{"status": "success", "storage_key": "reports/x.json"}\' > "$SAB_SCHEDULER_STATUS_FILE"\n'
            "exit 0\n"
        ),
    )

    assert result.returncode == 0
    cmd_logs = list((tmp_path / "logs" / "scheduled").glob("**/*.cmd.log"))
    assert cmd_logs
    assert "TELEGRAM_BOT_TOKEN" not in cmd_logs[0].read_text(encoding="utf-8")
```

- [ ] **Step 2: Run tests and verify they fail**

Run:

```bash
UV_CACHE_DIR=.uv-cache uv run python -m pytest -q tests/test_launchd_scheduler_wrapper.py -k 'status_file or attempt_scoped_command'
```

Expected: FAIL because wrapper still scrapes last stdout and writes role-scoped cmd logs only.

- [ ] **Step 3: Update wrapper path setup**

In `scripts/launchd/sab-ai-brief-wrapper.sh`, after `attempt_id=...`, add:

```bash
session_date="$(date -u +%Y-%m-%d)"
attempt_log_dir="logs/scheduled/ai-brief/${session_date}"
mkdir -p "${attempt_log_dir}"
attempt_log_prefix="${attempt_log_dir}/${market}-${schedule_role}-${attempt_id}"
attempt_stdout="${attempt_log_prefix}.out.log"
attempt_stderr="${attempt_log_prefix}.err.log"
attempt_guard_log="${attempt_log_prefix}.guard.log"
attempt_cmd_log="${attempt_log_prefix}.cmd.log"
attempt_status_file="${attempt_log_prefix}.status.json"
attempt_summary_file="${attempt_log_prefix}.summary.json"
```

Keep role-scoped `logs/launchd/...` files for compatibility, but write guard/cmd to attempt-scoped paths too.

- [ ] **Step 4: Pass status file into container**

Change command execution to:

```bash
SAB_SCHEDULER_ENV_FILE="${SAB_SCHEDULER_ENV_FILE}" \
SAB_SCHEDULER_STATUS_FILE="${attempt_status_file}" \
"${cmd[@]}" > "${container_pipe}" 2> "${attempt_stderr}" || container_status=$?
```

Also pipe stdout to both temp capture and attempt stdout:

```bash
tee "${container_stdout}" "${attempt_stdout}" < "${container_pipe}" &
```

- [ ] **Step 5: Parse status file first**

Add:

```bash
extract_scheduler_status_file() {
  local status_file="$1"
  [[ -r "${status_file}" ]] || return 1
  sed -nE 's/.*"status"[[:space:]]*:[[:space:]]*"([^"]+)".*/\1/p' "${status_file}" | tail -n 1
}
```

Then replace failure status extraction:

```bash
scheduler_status="$(extract_scheduler_status_file "${attempt_status_file}" || extract_scheduler_status "${container_stdout}" || true)"
```

- [ ] **Step 6: Write allowlist summary JSON**

At the end of wrapper before exit, write valid JSON with Python so shell quoting never corrupts values:

```bash
python - "${attempt_summary_file}" "${attempt_id}" "${market}" "${schedule_role}" "${runner_role}" "${scheduler_status:-unknown}" <<'PY'
import json
import sys

path, attempt_id, market, schedule_role, runner_role, status = sys.argv[1:]
with open(path, "w", encoding="utf-8") as out:
    json.dump(
        {
            "attempt_id": attempt_id,
            "market": market,
            "schedule_role": schedule_role,
            "runner_role": runner_role,
            "status": status,
        },
        out,
        separators=(",", ":"),
    )
    out.write("\n")
PY
```

- [ ] **Step 7: Run wrapper tests**

Run:

```bash
UV_CACHE_DIR=.uv-cache uv run python -m pytest -q tests/test_launchd_scheduler_wrapper.py
```

Expected: PASS.

- [ ] **Step 8: Commit**

```bash
git add scripts/launchd/sab-ai-brief-wrapper.sh tests/test_launchd_scheduler_wrapper.py
git commit -m "feat(scheduler): launchd 실행 로그를 attempt 단위로 보존"
```

---

### Task 7: Add Manual AI Brief Latency Probe

**Files:**
- Create: `sab/ai_brief_latency_probe.py`
- Modify: `sab/__main__.py`
- Modify: `docker-compose.scheduler.yml`
- Test: `tests/test_ai_brief_latency_probe.py`
- Test: `tests/test_cli_dispatch.py`
- Test: `tests/test_launchd_scheduler_wrapper.py`

- [ ] **Step 1: Write failing probe unit tests**

Create `tests/test_ai_brief_latency_probe.py`.

```python
from __future__ import annotations

import json
from pathlib import Path

import pytest

from sab import ai_brief_latency_probe


def test_probe_plan_defaults_to_bounded_call_count() -> None:
    plan = ai_brief_latency_probe.build_probe_plan(
        primary_model="gpt-5.5",
        fallback_model="gpt-5.4-mini",
        repetitions=1,
    )

    assert [item.timeout_seconds for item in plan] == [20.0, 30.0, 60.0, 30.0]
    assert sum(item.repetitions for item in plan) == 4


def test_probe_rejects_repetition_above_default_cap() -> None:
    with pytest.raises(ValueError, match="repetitions must be <= 3"):
        ai_brief_latency_probe.build_probe_plan(
            primary_model="gpt-5.5",
            fallback_model="gpt-5.4-mini",
            repetitions=4,
        )


def test_probe_writes_jsonl_without_upload(tmp_path: Path) -> None:
    output = tmp_path / "latency.jsonl"
    ai_brief_latency_probe.write_probe_row(
        output,
        {
            "timestamp": "2026-06-26T12:00:00Z",
            "market": "US",
            "model_name": "gpt-5.5",
            "timeout_seconds": 20.0,
            "attempt_number": 1,
            "status": "success",
            "duration_ms": 1234,
            "recommendation_count": 1,
            "vetoed_count": 0,
            "watch_count": 0,
        },
    )

    payload = json.loads(output.read_text(encoding="utf-8"))
    assert payload["status"] == "success"
    assert "OPENAI_API_KEY" not in output.read_text(encoding="utf-8")
```

- [ ] **Step 2: Run tests and verify they fail**

Run:

```bash
UV_CACHE_DIR=.uv-cache uv run python -m pytest -q tests/test_ai_brief_latency_probe.py
```

Expected: FAIL because module does not exist.

- [ ] **Step 3: Create probe module**

Create `sab/ai_brief_latency_probe.py`.

```python
from __future__ import annotations

import datetime as dt
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Mapping


@dataclass(frozen=True)
class ProbeItem:
    model_name: str
    timeout_seconds: float
    repetitions: int


def build_probe_plan(
    *,
    primary_model: str,
    fallback_model: str | None,
    repetitions: int,
) -> list[ProbeItem]:
    if repetitions < 1 or repetitions > 3:
        raise ValueError("repetitions must be <= 3 and >= 1")
    plan = [
        ProbeItem(primary_model, 20.0, repetitions),
        ProbeItem(primary_model, 30.0, repetitions),
        ProbeItem(primary_model, 60.0, repetitions),
    ]
    if fallback_model:
        plan.append(ProbeItem(fallback_model, 30.0, repetitions))
    return plan


def default_output_path(now: dt.datetime | None = None) -> Path:
    current = now or dt.datetime.now(dt.UTC)
    return Path("logs/measurements/ai-brief-model-latency") / f"{current.date().isoformat()}.jsonl"


def write_probe_row(path: Path, row: Mapping[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(dict(row), ensure_ascii=False, sort_keys=True))
        handle.write("\n")


def run_probe(*, primary_model: str, fallback_model: str | None, repetitions: int) -> int:
    plan = build_probe_plan(
        primary_model=primary_model,
        fallback_model=fallback_model,
        repetitions=repetitions,
    )
    print(f"planned_live_model_call_count={sum(item.repetitions for item in plan)}")
    return 0
```

- [ ] **Step 4: Add CLI command**

In `sab/__main__.py`, add parser:

```python
probe = sub.add_parser(
    "ai-brief-latency-probe",
    help="Measure AI Brief model latency without upload or notification",
)
probe.add_argument("--primary-model", required=True)
probe.add_argument("--fallback-model", default=None)
probe.add_argument("--repetitions", type=int, default=1)
```

Add dispatch:

```python
def _run_ai_brief_latency_probe_command(ns: argparse.Namespace) -> int:
    return ai_brief_latency_probe.run_probe(
        primary_model=ns.primary_model,
        fallback_model=ns.fallback_model,
        repetitions=ns.repetitions,
    )
```

Add to handlers:

```python
"ai-brief-latency-probe": _run_ai_brief_latency_probe_command,
```

- [ ] **Step 5: Remove probe container collision**

In `docker-compose.scheduler.yml`, delete:

```yaml
    container_name: sab-ai-brief-scheduler
```

Update `tests/test_launchd_scheduler_wrapper.py::test_scheduler_compose_has_one_shot_runner_service` so it asserts the scheduler service has `restart: "no"` and does not define `container_name`.

- [ ] **Step 6: Run tests**

Run:

```bash
UV_CACHE_DIR=.uv-cache uv run python -m pytest -q tests/test_ai_brief_latency_probe.py tests/test_cli_dispatch.py tests/test_launchd_scheduler_wrapper.py
```

Expected: PASS.

- [ ] **Step 7: Commit**

```bash
git add sab/ai_brief_latency_probe.py sab/__main__.py docker-compose.scheduler.yml tests/test_ai_brief_latency_probe.py tests/test_cli_dispatch.py tests/test_launchd_scheduler_wrapper.py
git commit -m "feat(ai-brief): 모델 latency probe 명령 추가"
```

---

### Task 8: Add Generic Scheduled State Scope Keys Without Changing AI Brief Keys

**Files:**
- Create: `sab/scheduler/generic_state.py`
- Test: `tests/test_scheduled_generic_state.py`

- [ ] **Step 1: Write failing generic state tests**

Create `tests/test_scheduled_generic_state.py`.

```python
from __future__ import annotations

import pytest

from sab.scheduler.generic_state import build_scheduled_state_key


def test_generic_scheduled_state_key_supports_mixed_scope() -> None:
    assert (
        build_scheduled_state_key(
            pipeline="scan",
            kind="success",
            scope="mixed",
            session_date="2026-06-26",
        )
        == "scheduled-scan:success:MIXED:2026-06-26"
    )


def test_generic_scheduled_state_key_rejects_unknown_scope() -> None:
    with pytest.raises(ValueError, match="scope must be KR, US, or MIXED"):
        build_scheduled_state_key(
            pipeline="scan",
            kind="success",
            scope="both",
            session_date="2026-06-26",
        )
```

- [ ] **Step 2: Run tests and verify they fail**

Run:

```bash
UV_CACHE_DIR=.uv-cache uv run python -m pytest -q tests/test_scheduled_generic_state.py
```

Expected: FAIL because module does not exist.

- [ ] **Step 3: Create generic state module**

Create `sab/scheduler/generic_state.py`.

```python
from __future__ import annotations


_ALLOWED_PIPELINES = {"scan", "sell", "ai-brief"}
_ALLOWED_SCOPES = {"KR", "US", "MIXED"}


def _normalize_token(value: str, *, field_name: str) -> str:
    text = str(value or "").strip()
    if not text or any(char in text for char in ":\n\r/\\"):
        raise ValueError(f"{field_name} must be a non-empty safe token")
    return text


def _normalize_pipeline(pipeline: str) -> str:
    text = _normalize_token(pipeline, field_name="pipeline").lower()
    if text not in _ALLOWED_PIPELINES:
        raise ValueError("pipeline must be ai-brief, scan, or sell")
    return text


def _normalize_scope(scope: str) -> str:
    text = _normalize_token(scope, field_name="scope").upper()
    if text not in _ALLOWED_SCOPES:
        raise ValueError("scope must be KR, US, or MIXED")
    return text


def build_scheduled_state_key(
    *,
    pipeline: str,
    kind: str,
    scope: str,
    session_date: str,
    runner_role: str | None = None,
    attempt_id: str | None = None,
) -> str:
    normalized_pipeline = _normalize_pipeline(pipeline)
    normalized_kind = _normalize_token(kind, field_name="kind").lower()
    normalized_scope = _normalize_scope(scope)
    normalized_session_date = _normalize_token(
        session_date,
        field_name="session_date",
    )
    parts = [
        f"scheduled-{normalized_pipeline}",
        normalized_kind,
        normalized_scope,
        normalized_session_date,
    ]
    if runner_role is not None:
        parts.append(_normalize_token(runner_role, field_name="runner_role"))
    if attempt_id is not None:
        parts.append(_normalize_token(attempt_id, field_name="attempt_id"))
    return ":".join(parts)
```

- [ ] **Step 4: Run tests**

Run:

```bash
UV_CACHE_DIR=.uv-cache uv run python -m pytest -q tests/test_scheduled_generic_state.py tests/test_scheduled_ai_brief_state.py
```

Expected: PASS. Existing AI Brief key tests must remain unchanged.

- [ ] **Step 5: Commit**

```bash
git add sab/scheduler/generic_state.py tests/test_scheduled_generic_state.py
git commit -m "feat(scheduler): 범용 scheduled state key 추가"
```

---

### Task 9: Add Initial Generic Wrapper And Preserve AI Brief Wrapper Compatibility

**Files:**
- Create: `scripts/launchd/sab-scheduled-wrapper.sh`
- Modify: `tests/test_launchd_scheduler_wrapper.py`

- [ ] **Step 1: Write failing generic wrapper compatibility test**

Add:

```python
def test_generic_scheduled_wrapper_exists_without_replacing_ai_brief_wrapper() -> None:
    generic = Path("scripts/launchd/sab-scheduled-wrapper.sh")
    ai_brief = Path("scripts/launchd/sab-ai-brief-wrapper.sh")

    assert generic.is_file()
    assert ai_brief.is_file()
    text = generic.read_text(encoding="utf-8")
    assert "--pipeline" in text
    assert "--scope" in text
    assert "ai-brief|scan|sell" in text
```

- [ ] **Step 2: Run test and verify it fails**

Run:

```bash
UV_CACHE_DIR=.uv-cache uv run python -m pytest -q tests/test_launchd_scheduler_wrapper.py::test_generic_scheduled_wrapper_exists_without_replacing_ai_brief_wrapper
```

Expected: FAIL because the generic wrapper does not exist.

- [ ] **Step 3: Add initial generic wrapper**

Create `scripts/launchd/sab-scheduled-wrapper.sh`:

```bash
#!/usr/bin/env bash
set -euo pipefail

pipeline=""
scope=""

usage() {
  printf '%s\n' "usage: $0 --pipeline ai-brief|scan|sell --scope KR|US|MIXED [pipeline-specific args]" >&2
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --pipeline)
      pipeline="${2:-}"
      shift 2
      ;;
    --scope)
      scope="${2:-}"
      shift 2
      ;;
    *)
      break
      ;;
  esac
done

case "${pipeline}" in
  ai-brief|scan|sell) ;;
  *)
    usage
    exit 2
    ;;
esac

case "${scope}" in
  KR|US|MIXED) ;;
  *)
    usage
    exit 2
    ;;
esac

printf 'generic scheduled wrapper requires pipeline-specific execution for pipeline=%s scope=%s\n' "${pipeline}" "${scope}" >&2
exit 2
```

Make it executable:

```bash
chmod 755 scripts/launchd/sab-scheduled-wrapper.sh
```

- [ ] **Step 4: Run test**

Run:

```bash
UV_CACHE_DIR=.uv-cache uv run python -m pytest -q tests/test_launchd_scheduler_wrapper.py::test_generic_scheduled_wrapper_exists_without_replacing_ai_brief_wrapper
```

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add scripts/launchd/sab-scheduled-wrapper.sh tests/test_launchd_scheduler_wrapper.py
git commit -m "feat(scheduler): 범용 launchd wrapper 골격 추가"
```

---

### Task 10: Add Scan/Sell Shadow-Only Local Runner Contract Tests

**Files:**
- Create: `tests/test_scheduled_scan_sell_contract.py`
- Create: `sab/scheduler/pipeline_contract.py`

- [ ] **Step 1: Write failing contract tests**

Create `tests/test_scheduled_scan_sell_contract.py`.

```python
from __future__ import annotations

import pytest

from sab.scheduler.pipeline_contract import ScheduledPipelineMode, validate_upload_enabled


def test_scan_local_canary_starts_shadow_only() -> None:
    assert ScheduledPipelineMode.SHADOW.value == "shadow"


def test_scan_upload_requires_marker_aware_github_fallback() -> None:
    with pytest.raises(ValueError, match="marker-aware GitHub fallback"):
        validate_upload_enabled(
            pipeline="scan",
            mode=ScheduledPipelineMode.UPLOAD,
            github_marker_aware=False,
        )


def test_sell_upload_allowed_after_marker_aware_fallback() -> None:
    validate_upload_enabled(
        pipeline="sell",
        mode=ScheduledPipelineMode.UPLOAD,
        github_marker_aware=True,
    )
```

- [ ] **Step 2: Run tests and verify they fail**

Run:

```bash
UV_CACHE_DIR=.uv-cache uv run python -m pytest -q tests/test_scheduled_scan_sell_contract.py
```

Expected: FAIL because module does not exist.

- [ ] **Step 3: Add contract module**

Create `sab/scheduler/pipeline_contract.py`:

```python
from __future__ import annotations

from enum import Enum


class ScheduledPipelineMode(str, Enum):
    SHADOW = "shadow"
    UPLOAD = "upload"


def validate_upload_enabled(
    *,
    pipeline: str,
    mode: ScheduledPipelineMode,
    github_marker_aware: bool,
) -> None:
    normalized_pipeline = str(pipeline or "").strip().lower()
    if normalized_pipeline not in {"scan", "sell"}:
        raise ValueError("pipeline must be scan or sell")
    if mode is ScheduledPipelineMode.UPLOAD and not github_marker_aware:
        raise ValueError(
            "scheduled scan/sell upload requires marker-aware GitHub fallback"
        )
```

- [ ] **Step 4: Run tests**

Run:

```bash
UV_CACHE_DIR=.uv-cache uv run python -m pytest -q tests/test_scheduled_scan_sell_contract.py
```

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add sab/scheduler/pipeline_contract.py tests/test_scheduled_scan_sell_contract.py
git commit -m "feat(scheduler): scan sell 업로드 전환 계약 추가"
```

---

### Task 11: Convert GitHub Scan Schedule To Marker-Aware Preflight Before Local Upload

**Files:**
- Modify: `.github/workflows/scan.yml`
- Test: `tests/test_scan_workflow.py`

- [ ] **Step 1: Write failing workflow preflight test**

Create `tests/test_scan_workflow.py`.

```python
from __future__ import annotations

import yaml
from pathlib import Path


def _workflow() -> dict[str, object]:
    return yaml.safe_load(Path(".github/workflows/scan.yml").read_text(encoding="utf-8"))


def test_scheduled_scan_checks_runtime_state_before_provider_execution() -> None:
    workflow = _workflow()
    steps = workflow["jobs"]["scan"]["steps"]
    names = [step.get("name") for step in steps]

    preflight_index = names.index("Scheduled runtime_state preflight")
    install_index = names.index("Install dependencies")
    run_index = names.index("Run scan")

    assert preflight_index < install_index < run_index
```

- [ ] **Step 2: Run test and verify it fails**

Run:

```bash
UV_CACHE_DIR=.uv-cache uv run python -m pytest -q tests/test_scan_workflow.py
```

Expected: FAIL because the preflight step is missing.

- [ ] **Step 3: Add scheduled preflight ordering gate without changing upload behavior**

In `.github/workflows/scan.yml`, add a scheduled-only preflight step before dependency install:

```yaml
- name: Scheduled runtime_state preflight
  if: github.event_name == 'schedule'
  env:
    SUPABASE_URL: ${{ secrets.SUPABASE_URL }}
    SUPABASE_SECRET_KEY: ${{ secrets.SUPABASE_SECRET_KEY }}
  run: |
    set -euo pipefail
    echo "scheduled scan runtime_state preflight: marker-aware conversion required before local upload"
```

This task only establishes ordering and test coverage. Do not disable current scheduled scan yet.

- [ ] **Step 4: Run workflow tests**

Run:

```bash
UV_CACHE_DIR=.uv-cache uv run python -m pytest -q tests/test_scan_workflow.py tests/test_workflow_holdings_loading.py
```

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add .github/workflows/scan.yml tests/test_scan_workflow.py
git commit -m "chore(ci): scan scheduled preflight 순서 고정"
```

---

### Task 12: Convert GitHub Sell Schedule To Marker-Aware Preflight Before Local Upload

**Files:**
- Modify: `.github/workflows/sell.yml`
- Test: `tests/test_sell_workflow.py`

- [ ] **Step 1: Write failing workflow preflight test**

Create `tests/test_sell_workflow.py`.

```python
from __future__ import annotations

import yaml
from pathlib import Path


def _workflow() -> dict[str, object]:
    return yaml.safe_load(Path(".github/workflows/sell.yml").read_text(encoding="utf-8"))


def test_scheduled_sell_checks_runtime_state_before_holdings_and_provider_execution() -> None:
    workflow = _workflow()
    steps = workflow["jobs"]["sell"]["steps"]
    names = [step.get("name") for step in steps]

    preflight_index = names.index("Scheduled runtime_state preflight")
    holdings_index = names.index("Load holdings from Supabase")
    install_index = names.index("Install dependencies")
    run_index = names.index("Run sell")

    assert preflight_index < install_index < holdings_index < run_index
```

- [ ] **Step 2: Run test and verify it fails**

Run:

```bash
UV_CACHE_DIR=.uv-cache uv run python -m pytest -q tests/test_sell_workflow.py
```

Expected: FAIL because the preflight step is missing.

- [ ] **Step 3: Add scheduled preflight ordering gate without changing upload behavior**

In `.github/workflows/sell.yml`, add before dependency install:

```yaml
- name: Scheduled runtime_state preflight
  if: github.event_name == 'schedule'
  env:
    SUPABASE_URL: ${{ secrets.SUPABASE_URL }}
    SUPABASE_SECRET_KEY: ${{ secrets.SUPABASE_SECRET_KEY }}
  run: |
    set -euo pipefail
    echo "scheduled sell runtime_state preflight: marker-aware conversion required before local upload"
```

Do not disable current scheduled sell yet.

- [ ] **Step 4: Run workflow test**

Run:

```bash
UV_CACHE_DIR=.uv-cache uv run python -m pytest -q tests/test_sell_workflow.py
```

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add .github/workflows/sell.yml tests/test_sell_workflow.py
git commit -m "chore(ci): sell scheduled preflight 순서 고정"
```

---

## Final Verification

After all tasks in a batch pass, run:

```bash
just quality
```

Expected: all Python quality checks pass.

For workflow-only batches, also run:

```bash
UV_CACHE_DIR=.uv-cache uv run python -m pytest -q tests/test_ai_brief_workflow.py tests/test_scan_workflow.py tests/test_sell_workflow.py tests/test_workflow_holdings_loading.py
```

Expected: PASS.

Do not run live OpenAI latency probes unless the operator explicitly approves API-costing calls.
