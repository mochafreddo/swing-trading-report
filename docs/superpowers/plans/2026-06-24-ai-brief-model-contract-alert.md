# AI Brief Model Contract Alert Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Prevent invalid OpenAI veto tickers from becoming provider-wide system errors and stop the launchd wrapper from mislabeling structured scheduler failures as host/container failures.

**Architecture:** Add request-local ticker constraints to the OpenAI structured-output schema, then keep local normalization authoritative by dropping invalid veto rows into WARN diagnostics. Preserve scheduled fail-closed quality gates, and split launchd wrapper alerts between structured application failures and real host/container launch failures.

**Tech Stack:** Python 3.14, pytest, uv, Bash launchd wrapper, Docker Compose scheduler, existing `sab` AI Brief provider/evaluator/scheduler modules.

## Global Constraints

- Do not store raw OpenAI responses in this pass.
- Do not relax URL safety, source freshness, source-ref allowlists, role boundaries, or automated-order language checks.
- Do not change Supabase schema, `report_index`, or public report storage layout.
- Do not change Web UI behavior in this pass.
- Do not retry model calls in this pass.
- Do not make a quality-gate `FAIL` publish a normal AI Brief notification.
- Scheduled success must remain conservative: eligible candidates with no recommendation and no valid veto still fail.
- Commit messages must be Korean Conventional Commits.

---

## File Structure

- Modify `sab/ai_brief_providers.py`
  - Build OpenAI schema with request-local ticker enums.
  - Add invalid veto sanitizer that appends WARN source issues.
  - Keep recommendation/watch hard validation unchanged.
- Modify `tests/test_ai_brief_providers.py`
  - Cover schema ticker enums, empty role arrays, invalid veto drops, and remaining hard veto errors.
- Modify `tests/test_ai_brief.py`
  - Update OpenAI workflow artifact expectations for unknown veto rows.
- Modify `tests/test_ai_brief_eval.py`
  - Cover evaluator behavior after invalid veto rows are sanitized away.
- Modify `tests/test_scheduled_ai_brief_runner.py`
  - Keep scheduled quality gate behavior explicit for FAIL and WARN cases.
- Modify `scripts/launchd/sab-ai-brief-wrapper.sh`
  - Capture scheduler stdout and suppress host-failure for structured app failure statuses.
- Modify `tests/test_launchd_scheduler_wrapper.py`
  - Add executable wrapper tests with stubbed `uv`, `docker`, and `curl`.
- Modify `docs/operations.md`
  - Document `model_ineligible_veto_dropped`, `model_watch_veto_dropped`, and host alert classification.
- Modify `docs/ARCHITECTURE.md`
  - Update scheduled AI Brief flow if the implementation text currently implies all non-zero wrapper exits are host failures.

---

### Task 1: OpenAI Schema Ticker Constraints

**Files:**
- Modify: `sab/ai_brief_providers.py`
- Modify: `tests/test_ai_brief_providers.py`

**Interfaces:**
- Consumes: `_candidate_ticker_order(candidates: list[dict[str, object]]) -> list[str]`
- Produces: `_openai_result_schema(*, eligible_tickers: list[str], watch_tickers: list[str]) -> dict[str, _JsonValue]`
- Produces: `_build_openai_request_payload(..., eligible_tickers: list[str], watch_tickers: list[str]) -> dict[str, _JsonValue]`

- [ ] **Step 1: Write failing provider schema tests**

Add these tests after `test_openai_payload_adds_source_ids_and_schema_uses_source_refs` in `tests/test_ai_brief_providers.py`:

```python
def test_openai_schema_constrains_tickers_by_candidate_role() -> None:
    session = _CapturingSession(
        {
            "recommendations": [],
            "vetoed_candidates": [
                {
                    "ticker": "AAPL.NAS",
                    "action": "SKIP",
                    "reason": "source risk",
                }
            ],
            "watch_candidates": [
                {
                    "ticker": "MSFT.NAS",
                    "action": "WATCH",
                    "reason": "trigger pending",
                    "retrigger_conditions": ["price back above trigger"],
                    "source_refs": ["MSFT.NAS:1"],
                }
            ],
            "source_issues": [],
        }
    )
    provider = OpenAiBriefProvider(
        model_name="gpt-test",
        api_key="test-key",
        timeout_seconds=1.0,
        session=session,
    )

    provider.build_recommendations(
        recommendable_candidates=[_candidate("AAPL.NAS", role="recommendable")],
        watch_candidates=[_candidate("MSFT.NAS", role="watch_only")],
    )

    request = session.requests[0]["json"]
    assert isinstance(request, dict)
    user_payload = json.loads(str(request["input"][1]["content"]))
    assert user_payload["eligible_tickers"] == ["AAPL.NAS"]
    assert user_payload["watch_tickers"] == ["MSFT.NAS"]

    schema = request["text"]["format"]["schema"]
    recommendation_ticker = schema["properties"]["recommendations"]["items"][
        "properties"
    ]["ticker"]
    veto_ticker = schema["properties"]["vetoed_candidates"]["items"]["properties"][
        "ticker"
    ]
    watch_ticker = schema["properties"]["watch_candidates"]["items"]["properties"][
        "ticker"
    ]
    assert recommendation_ticker == {"type": "string", "enum": ["AAPL.NAS"]}
    assert veto_ticker == {"type": "string", "enum": ["AAPL.NAS"]}
    assert watch_ticker == {"type": "string", "enum": ["MSFT.NAS"]}


def test_openai_schema_disallows_empty_role_arrays() -> None:
    session = _CapturingSession(
        {
            "recommendations": [],
            "vetoed_candidates": [],
            "watch_candidates": [
                {
                    "ticker": "MSFT.NAS",
                    "action": "WATCH",
                    "reason": "trigger pending",
                    "retrigger_conditions": ["price back above trigger"],
                    "source_refs": ["MSFT.NAS:1"],
                }
            ],
            "source_issues": [],
        }
    )
    provider = OpenAiBriefProvider(
        model_name="gpt-test",
        api_key="test-key",
        timeout_seconds=1.0,
        session=session,
    )

    provider.build_recommendations(
        recommendable_candidates=[],
        watch_candidates=[_candidate("MSFT.NAS", role="watch_only")],
    )

    request = session.requests[0]["json"]
    assert isinstance(request, dict)
    schema = request["text"]["format"]["schema"]
    assert schema["properties"]["recommendations"]["maxItems"] == 0
    assert schema["properties"]["vetoed_candidates"]["maxItems"] == 0
    assert "enum" not in schema["properties"]["recommendations"]["items"][
        "properties"
    ]["ticker"]
    assert schema["properties"]["watch_candidates"]["items"]["properties"][
        "ticker"
    ] == {"type": "string", "enum": ["MSFT.NAS"]}
```

- [ ] **Step 2: Run tests to verify they fail**

Run:

```bash
UV_CACHE_DIR=.uv-cache uv run python -m pytest \
  tests/test_ai_brief_providers.py::test_openai_schema_constrains_tickers_by_candidate_role \
  tests/test_ai_brief_providers.py::test_openai_schema_disallows_empty_role_arrays -q
```

Expected: FAIL because the request user payload has no `eligible_tickers`/`watch_tickers`, schema ticker fields have no enum, and empty role arrays have no `maxItems: 0`.

- [ ] **Step 3: Implement dynamic ticker schema**

In `OpenAiBriefProvider.build_recommendations`, compute ordered ticker lists after `_candidate_role_ticker_sets` succeeds:

```python
eligible_ticker_order = _candidate_ticker_order(recommendable_candidates)
watch_ticker_order = _candidate_ticker_order(watch_candidates)
request_payload = _build_openai_request_payload(
    model_name=self.model_name,
    recommendable_candidates=recommendable_source_catalog.model_candidates(
        recommendable_candidates
    ),
    watch_candidates=watch_source_catalog.model_candidates(watch_candidates),
    eligible_tickers=eligible_ticker_order,
    watch_tickers=watch_ticker_order,
)
```

Change `_build_openai_request_payload` signature:

```python
def _build_openai_request_payload(
    *,
    model_name: str,
    recommendable_candidates: list[dict[str, object]],
    watch_candidates: list[dict[str, object]],
    eligible_tickers: list[str],
    watch_tickers: list[str],
) -> dict[str, _JsonValue]:
```

Add explicit ticker lists to the user JSON:

```python
"eligible_tickers": eligible_tickers,
"watch_tickers": watch_tickers,
```

Add helper functions near `_openai_result_schema`:

```python
def _ticker_schema(tickers: list[str]) -> dict[str, _JsonValue]:
    if tickers:
        return {"type": "string", "enum": list(tickers)}
    return {"type": "string"}


def _role_array_schema(
    *,
    items: dict[str, _JsonValue],
    allowed_tickers: list[str],
    max_items: int | None = None,
) -> dict[str, _JsonValue]:
    schema: dict[str, _JsonValue] = {"type": "array", "items": items}
    if max_items is not None:
        schema["maxItems"] = max_items
    if not allowed_tickers:
        schema["maxItems"] = 0
    return schema
```

Change `_openai_result_schema` signature and use `_ticker_schema`:

```python
def _openai_result_schema(
    *,
    eligible_tickers: list[str],
    watch_tickers: list[str],
) -> dict[str, _JsonValue]:
```

For `recommendations`, wrap the existing array object with `_role_array_schema(..., allowed_tickers=eligible_tickers, max_items=RECOMMENDATION_LIMIT)` and set:

```python
"ticker": _ticker_schema(eligible_tickers),
```

For `vetoed_candidates`, wrap with `_role_array_schema(..., allowed_tickers=eligible_tickers)` and set:

```python
"ticker": _ticker_schema(eligible_tickers),
```

For `watch_candidates`, wrap with `_role_array_schema(..., allowed_tickers=watch_tickers)` and set:

```python
"ticker": _ticker_schema(watch_tickers),
```

- [ ] **Step 4: Run provider schema tests**

Run:

```bash
UV_CACHE_DIR=.uv-cache uv run python -m pytest \
  tests/test_ai_brief_providers.py::test_openai_schema_constrains_tickers_by_candidate_role \
  tests/test_ai_brief_providers.py::test_openai_schema_disallows_empty_role_arrays -q
```

Expected: PASS.

- [ ] **Step 5: Run existing provider tests**

Run:

```bash
UV_CACHE_DIR=.uv-cache uv run python -m pytest tests/test_ai_brief_providers.py -q
```

Expected: PASS.

- [ ] **Step 6: Commit task 1**

Run:

```bash
git add sab/ai_brief_providers.py tests/test_ai_brief_providers.py
git commit -m "fix(ai-brief): 모델 티커 스키마를 후보로 제한"
```

Expected: commit succeeds.

---

### Task 2: Invalid Veto Sanitizer And Quality Result

**Files:**
- Modify: `sab/ai_brief_providers.py`
- Modify: `tests/test_ai_brief_providers.py`
- Modify: `tests/test_ai_brief.py`
- Modify: `tests/test_ai_brief_eval.py`

**Interfaces:**
- Consumes: `_model_source_issue(ticker: str, code: str, message: str) -> dict[str, object]`
- Produces: `_sanitize_provider_vetoed_candidates(...) -> tuple[list[dict[str, object]], list[dict[str, object]]]`
- Produces source issue codes: `model_ineligible_veto_dropped`, `model_watch_veto_dropped`

- [ ] **Step 1: Write failing provider sanitizer tests**

Replace `test_openai_rejects_watch_candidate_returned_as_veto` in `tests/test_ai_brief_providers.py` with:

```python
def test_openai_drops_watch_candidate_returned_as_veto() -> None:
    provider = OpenAiBriefProvider(
        model_name="gpt-test",
        api_key="test-key",
        timeout_seconds=1.0,
        session=_CapturingSession(
            {
                "recommendations": [],
                "vetoed_candidates": [
                    {
                        "ticker": "MSFT.NAS",
                        "action": "SKIP",
                        "reason": "bad role",
                    }
                ],
                "watch_candidates": [
                    {
                        "ticker": "MSFT.NAS",
                        "action": "WATCH",
                        "reason": "trigger pending",
                        "retrigger_conditions": ["price back above trigger"],
                        "source_refs": ["MSFT.NAS:1"],
                    }
                ],
                "source_issues": [],
            }
        ),
    )

    result = provider.build_recommendations(
        recommendable_candidates=[_candidate("AAPL.NAS", role="recommendable")],
        watch_candidates=[_candidate("MSFT.NAS", role="watch_only")],
    )

    assert result.vetoed_candidates == []
    assert result.source_issues[-1]["ticker"] == "MSFT.NAS"
    assert result.source_issues[-1]["code"] == "model_watch_veto_dropped"
    assert result.source_issues[-1]["severity"] == "WARN"
```

Add this sibling test:

```python
def test_openai_drops_unknown_veto_candidate_as_warn_source_issue() -> None:
    provider = OpenAiBriefProvider(
        model_name="gpt-test",
        api_key="test-key",
        timeout_seconds=1.0,
        session=_CapturingSession(
            {
                "recommendations": [],
                "vetoed_candidates": [
                    {
                        "ticker": "MSFT.NAS",
                        "action": "SKIP",
                        "reason": "not in the request candidate set",
                    }
                ],
                "watch_candidates": [],
                "source_issues": [],
            }
        ),
    )

    result = provider.build_recommendations(
        recommendable_candidates=[_candidate("AAPL.NAS", role="recommendable")],
        watch_candidates=[],
    )

    assert result.vetoed_candidates == []
    assert result.source_issues == [
        {
            "ticker": "MSFT.NAS",
            "code": "model_ineligible_veto_dropped",
            "severity": "WARN",
            "message": (
                "model returned vetoed candidate outside eligible_tickers "
                "and the row was dropped"
            ),
        }
    ]
```

Add hard-error coverage near existing veto tests:

```python
def test_openai_rejects_invalid_veto_action_for_known_ticker() -> None:
    provider = OpenAiBriefProvider(
        model_name="gpt-test",
        api_key="test-key",
        timeout_seconds=1.0,
        session=_CapturingSession(
            {
                "recommendations": [],
                "vetoed_candidates": [
                    {
                        "ticker": "AAPL.NAS",
                        "action": "WATCH",
                        "reason": "bad action",
                    }
                ],
                "watch_candidates": [],
                "source_issues": [],
            }
        ),
    )

    with pytest.raises(AiBriefProviderContractError, match="PASS or SKIP"):
        provider.build_recommendations(
            recommendable_candidates=[_candidate("AAPL.NAS", role="recommendable")],
            watch_candidates=[],
        )
```

- [ ] **Step 2: Run provider sanitizer tests to verify they fail**

Run:

```bash
UV_CACHE_DIR=.uv-cache uv run python -m pytest \
  tests/test_ai_brief_providers.py::test_openai_drops_watch_candidate_returned_as_veto \
  tests/test_ai_brief_providers.py::test_openai_drops_unknown_veto_candidate_as_warn_source_issue \
  tests/test_ai_brief_providers.py::test_openai_rejects_invalid_veto_action_for_known_ticker -q
```

Expected: first two tests FAIL because current code raises `AiBriefProviderContractError`; the hard-error test may already PASS.

- [ ] **Step 3: Implement veto sanitizer**

In `sab/ai_brief_providers.py`, add:

```python
def _sanitize_provider_vetoed_candidates(
    vetoed_candidates: list[dict[str, object]],
    *,
    eligible_tickers: set[str],
    watch_tickers: set[str],
) -> tuple[list[dict[str, object]], list[dict[str, object]]]:
    valid_rows: list[dict[str, object]] = []
    issues: list[dict[str, object]] = []
    for idx, candidate in enumerate(vetoed_candidates):
        ticker = str(candidate.get("ticker") or "").strip()
        if not ticker:
            raise AiBriefProviderContractError(
                f"OpenAI output vetoed_candidates[{idx}].ticker is required"
            )
        action = str(candidate.get("action") or "").strip().upper()
        if action not in {"PASS", "SKIP"}:
            raise AiBriefProviderContractError(
                "OpenAI output vetoed_candidates[].action must be PASS or SKIP"
            )
        reason = str(candidate.get("reason") or "").strip()
        if not reason:
            raise AiBriefProviderContractError(
                f"OpenAI output vetoed_candidates[{idx}].reason is required"
            )
        if ticker in watch_tickers:
            issues.append(
                _model_source_issue(
                    ticker=ticker,
                    code="model_watch_veto_dropped",
                    message=(
                        "model returned watch ticker in vetoed_candidates "
                        "and the row was dropped"
                    ),
                )
            )
            continue
        if ticker not in eligible_tickers:
            issues.append(
                _model_source_issue(
                    ticker=ticker,
                    code="model_ineligible_veto_dropped",
                    message=(
                        "model returned vetoed candidate outside eligible_tickers "
                        "and the row was dropped"
                    ),
                )
            )
            continue
        valid_rows.append({**candidate, "ticker": ticker, "action": action, "reason": reason})
    return valid_rows, issues
```

In `_normalize_openai_provider_result`, replace:

```python
vetoed_candidates = _as_provider_mapping_rows(
    parsed.get("vetoed_candidates"), field_name="vetoed_candidates"
)
```

with:

```python
raw_vetoed_candidates = _as_provider_mapping_rows(
    parsed.get("vetoed_candidates"), field_name="vetoed_candidates"
)
vetoed_candidates, veto_source_issues = _sanitize_provider_vetoed_candidates(
    raw_vetoed_candidates,
    eligible_tickers=set(candidate_by_ticker),
    watch_tickers=set(watch_candidate_by_ticker),
)
source_issues.extend(veto_source_issues)
```

Keep `_validate_provider_vetoed_candidates` in `_validate_provider_result_contract`. It still protects the final normalized result and catches future sanitizer regressions.

- [ ] **Step 4: Run provider sanitizer tests**

Run:

```bash
UV_CACHE_DIR=.uv-cache uv run python -m pytest \
  tests/test_ai_brief_providers.py::test_openai_drops_watch_candidate_returned_as_veto \
  tests/test_ai_brief_providers.py::test_openai_drops_unknown_veto_candidate_as_warn_source_issue \
  tests/test_ai_brief_providers.py::test_openai_rejects_invalid_veto_action_for_known_ticker -q
```

Expected: PASS.

- [ ] **Step 5: Update workflow artifact test**

In `tests/test_ai_brief.py`, rename `test_run_ai_brief_openai_rejects_unknown_vetoed_candidate` to:

```python
def test_run_ai_brief_openai_drops_unknown_vetoed_candidate(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
```

Keep the existing setup and assertions for `exit_code` and `vetoed_candidates`, then replace the system issue assertion with:

```python
assert payload["system_issues"] == []
assert payload["source_issues"] == [
    {
        "ticker": "MSFT.NAS",
        "code": "model_ineligible_veto_dropped",
        "severity": "WARN",
        "message": (
            "model returned vetoed candidate outside eligible_tickers "
            "and the row was dropped"
        ),
    }
]
assert payload["summary"]["source_issue_count"] == 1
assert payload["summary"]["system_issue_count"] == 0
```

- [ ] **Step 6: Add evaluator test for empty valid judgment after sanitizer**

In `tests/test_ai_brief_eval.py`, add:

```python
def test_ai_brief_eval_fails_when_invalid_veto_drop_leaves_no_model_judgment(
    tmp_path: Path,
) -> None:
    entry_path = _write_payload(
        tmp_path,
        "entry.invalid-veto-drop.json",
        {
            "schema": "sab.report.v1",
            "type": "entry",
            "market": "US",
            "entries": [
                {
                    "ticker": "AAPL.NAS",
                    "action": "ENTER",
                    "entry_state": "READY",
                    "entry_price": 101.0,
                    "entry_price_status": "available",
                    "gap_pct": 0.01,
                    "gap_guard_pct": 0.03,
                    "strategy_mode": "ema_cross",
                    "pattern": None,
                    "reasons": ["entry conditions satisfied"],
                }
            ],
            "summary": {"entry_count": 1},
            "system_issues": [],
        },
    )
    payload = _ai_brief_payload(
        entry_count=1,
        eligible_tickers=["AAPL.NAS"],
        recommendations=[],
        excluded_candidates=[],
    )
    payload["source_issues"] = [
        {
            "ticker": "MSFT.NAS",
            "code": "model_ineligible_veto_dropped",
            "severity": "WARN",
            "message": (
                "model returned vetoed candidate outside eligible_tickers "
                "and the row was dropped"
            ),
        }
    ]
    payload["summary"]["source_issue_count"] = 1
    report_path = _write_payload(tmp_path, "invalid-veto-drop.ai-brief.json", payload)

    result = evaluate_ai_brief_recommendation_report(
        entry_report_path=entry_path,
        ai_brief_report_path=report_path,
        now=EVAL_NOW,
    )

    assert result.status == "FAIL"
    assert "ai_brief_source_issue_reported" in _issue_codes(result)
    assert "recommendation_report_empty" in _issue_codes(result)
```

- [ ] **Step 7: Run workflow and evaluator tests**

Run:

```bash
UV_CACHE_DIR=.uv-cache uv run python -m pytest \
  tests/test_ai_brief.py::test_run_ai_brief_openai_drops_unknown_vetoed_candidate \
  tests/test_ai_brief_eval.py::test_ai_brief_eval_fails_when_invalid_veto_drop_leaves_no_model_judgment -q
```

Expected: PASS.

- [ ] **Step 8: Run AI Brief provider/workflow/eval subsets**

Run:

```bash
UV_CACHE_DIR=.uv-cache uv run python -m pytest \
  tests/test_ai_brief_providers.py \
  tests/test_ai_brief.py::test_run_ai_brief_openai_drops_unknown_vetoed_candidate \
  tests/test_ai_brief_eval.py -q
```

Expected: PASS.

- [ ] **Step 9: Commit task 2**

Run:

```bash
git add sab/ai_brief_providers.py tests/test_ai_brief_providers.py tests/test_ai_brief.py tests/test_ai_brief_eval.py
git commit -m "fix(ai-brief): 잘못된 veto 후보를 경고로 격리"
```

Expected: commit succeeds.

---

### Task 3: Launchd Wrapper Structured Failure Classification

**Files:**
- Modify: `scripts/launchd/sab-ai-brief-wrapper.sh`
- Modify: `tests/test_launchd_scheduler_wrapper.py`

**Interfaces:**
- Produces shell function: `is_structured_scheduler_failure_status`
- Produces shell function: `extract_scheduler_status`
- Preserves `send_host_failure_alert "docker_daemon_unavailable"`
- Suppresses `send_host_failure_alert "scheduler_container_failed"` for recognized structured failure statuses.

- [ ] **Step 1: Write failing wrapper execution tests**

Add imports to `tests/test_launchd_scheduler_wrapper.py`:

```python
import os
import shlex
```

Add helper functions near `REPO_ROOT`:

```python
def _write_executable(path: Path, text: str) -> None:
    path.write_text(text, encoding="utf-8")
    path.chmod(0o755)


def _run_wrapper_with_stubs(
    tmp_path: Path,
    *,
    docker_script: str,
) -> tuple[subprocess.CompletedProcess[str], Path]:
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    alerts_path = tmp_path / "alerts.log"
    env_file = tmp_path / ".env.scheduler.local"
    env_file.write_text(
        "TELEGRAM_BOT_TOKEN=test-token\nTELEGRAM_CHAT_ID=test-chat\n",
        encoding="utf-8",
    )
    _write_executable(
        bin_dir / "uv",
        "#!/usr/bin/env bash\n"
        "if [[ \"$*\" == *\"--guard-only\"* ]]; then exit 0; fi\n"
        "exit 1\n",
    )
    _write_executable(bin_dir / "docker", docker_script)
    _write_executable(
        bin_dir / "curl",
        "#!/usr/bin/env bash\n"
        f"printf '%s\\n' \"$*\" >> {shlex.quote(alerts_path.as_posix())}\n"
        "exit 0\n",
    )
    env = {
        **os.environ,
        "PATH": f"{bin_dir}{os.pathsep}{os.environ['PATH']}",
    }
    result = subprocess.run(
        [
            str(REPO_ROOT / "scripts/launchd/sab-ai-brief-wrapper.sh"),
            "--repo-root",
            str(tmp_path),
            "--env-file",
            str(env_file),
            "--market",
            "US",
            "--schedule-role",
            "local-primary",
            "--runner-role",
            "local-primary",
            "--scheduled-tick",
            "0810",
        ],
        cwd=REPO_ROOT,
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )
    return result, alerts_path
```

Add tests:

```python
def test_launchd_wrapper_suppresses_host_failure_for_structured_pipeline_failed(
    tmp_path: Path,
) -> None:
    result, alerts_path = _run_wrapper_with_stubs(
        tmp_path,
        docker_script=(
            "#!/usr/bin/env bash\n"
            "if [[ \"$1\" == \"info\" ]]; then exit 0; fi\n"
            "printf '%s\\n' '{\"status\": \"pipeline_failed\", \"storage_key\": null}'\n"
            "exit 1\n"
        ),
    )

    assert result.returncode == 1
    assert '{"status": "pipeline_failed", "storage_key": null}' in result.stdout
    assert not alerts_path.exists()


def test_launchd_wrapper_sends_host_failure_without_structured_status(
    tmp_path: Path,
) -> None:
    result, alerts_path = _run_wrapper_with_stubs(
        tmp_path,
        docker_script=(
            "#!/usr/bin/env bash\n"
            "if [[ \"$1\" == \"info\" ]]; then exit 0; fi\n"
            "printf '%s\\n' 'container crashed before app status'\n"
            "exit 1\n"
        ),
    )

    assert result.returncode == 1
    assert "container crashed before app status" in result.stdout
    alert_text = alerts_path.read_text(encoding="utf-8")
    assert "reason=scheduler_container_failed" in alert_text
```

- [ ] **Step 2: Run wrapper tests to verify they fail**

Run:

```bash
UV_CACHE_DIR=.uv-cache uv run python -m pytest \
  tests/test_launchd_scheduler_wrapper.py::test_launchd_wrapper_suppresses_host_failure_for_structured_pipeline_failed \
  tests/test_launchd_scheduler_wrapper.py::test_launchd_wrapper_sends_host_failure_without_structured_status -q
```

Expected: first test FAIL because current wrapper sends `scheduler_container_failed` for every non-zero Docker run.

- [ ] **Step 3: Implement wrapper classification helpers**

In `scripts/launchd/sab-ai-brief-wrapper.sh`, add after `send_host_failure_alert`:

```bash
is_structured_scheduler_failure_status() {
  local status="$1"
  case "${status}" in
    attempt_marker_failed|guard_failed|guard_failed_before_upload|guard_failed_before_notification|pipeline_failed|upload_failed|artifact_marker_failed|artifact_marker_invalid|entry_failure_artifact_claim_held|late_alert_send_failed|late_alert_sent_marker_failed|lock_lost_before_upload|skip_artifact_upload_failed|source_config_invalid|unsupported_runner_role)
      return 0
      ;;
    *)
      return 1
      ;;
  esac
}

extract_scheduler_status() {
  local stdout_file="$1"
  local line last_line status
  [[ -r "${stdout_file}" ]] || return 1
  last_line=""
  while IFS= read -r line || [[ -n "${line}" ]]; do
    [[ -n "${line}" ]] && last_line="${line}"
  done < "${stdout_file}"
  [[ "${last_line}" == \{*\"status\"* ]] || return 1
  status="$(printf '%s' "${last_line}" | sed -nE 's/.*"status"[[:space:]]*:[[:space:]]*"([^"]+)".*/\1/p')"
  [[ -n "${status}" ]] || return 1
  printf '%s' "${status}"
}
```

Replace the final Docker command block:

```bash
if ! SAB_SCHEDULER_ENV_FILE="${SAB_SCHEDULER_ENV_FILE}" "${cmd[@]}"; then
  send_host_failure_alert "scheduler_container_failed"
  exit 1
fi
```

with:

```bash
container_status=0
container_stdout="$(mktemp "${TMPDIR:-/tmp}/sab-ai-brief-wrapper.XXXXXX")"
trap 'rm -f "${container_stdout:-}"' EXIT
SAB_SCHEDULER_ENV_FILE="${SAB_SCHEDULER_ENV_FILE}" "${cmd[@]}" > >(tee "${container_stdout}") || container_status=$?
if [[ "${container_status}" -ne 0 ]]; then
  scheduler_status="$(extract_scheduler_status "${container_stdout}" || true)"
  if [[ -n "${scheduler_status}" ]] && is_structured_scheduler_failure_status "${scheduler_status}"; then
    exit "${container_status}"
  fi
  send_host_failure_alert "scheduler_container_failed"
  exit "${container_status}"
fi
```

This captures stdout while still streaming it through `tee`. Scheduler JSON status is stdout; structured logs already go to stderr and continue flowing to launchd stderr.

- [ ] **Step 4: Run wrapper tests**

Run:

```bash
UV_CACHE_DIR=.uv-cache uv run python -m pytest tests/test_launchd_scheduler_wrapper.py -q
```

Expected: PASS.

- [ ] **Step 5: Run shell syntax check**

Run:

```bash
bash -n scripts/launchd/sab-ai-brief-wrapper.sh
```

Expected: exit 0.

- [ ] **Step 6: Commit task 3**

Run:

```bash
git add scripts/launchd/sab-ai-brief-wrapper.sh tests/test_launchd_scheduler_wrapper.py
git commit -m "fix(scheduler): 구조화 실패의 host 알림 중복 억제"
```

Expected: commit succeeds.

---

### Task 4: Documentation And Final Verification

**Files:**
- Modify: `docs/operations.md`
- Modify: `docs/ARCHITECTURE.md`

**Interfaces:**
- Consumes provider issue codes `model_ineligible_veto_dropped`, `model_watch_veto_dropped`
- Consumes wrapper behavior from Task 3
- Produces operator guidance for quality gate and host-failure interpretation

- [ ] **Step 1: Update operations runbook**

In `docs/operations.md`, extend the existing `scheduled ai-brief quality gate failed` paragraph near the current source-ref diagnostic note with:

```markdown
`model_ineligible_veto_dropped` and `model_watch_veto_dropped` mean the model tried to place a ticker outside the eligible veto universe into `vetoed_candidates[]`; the provider dropped that row and kept it as a WARN source issue. These warnings do not by themselves fail scheduled publish, but if the model leaves no valid recommendation and no valid veto for preselected candidates, the recommendation quality gate still fails with `recommendation_report_empty`.
```

Add a host wrapper note near the notification or scheduler operations section:

```markdown
The launchd host wrapper sends `scheduler_container_failed` only when the Docker scheduler command exits without a recognized structured scheduler status. If the scheduler prints a JSON status such as `pipeline_failed`, treat the app-level late-alert and local scheduler logs as the source of truth rather than diagnosing Docker first.
```

- [ ] **Step 2: Update architecture flow**

In `docs/ARCHITECTURE.md`, update the scheduled AI Brief flow paragraph to mention:

```markdown
OpenAI provider normalization drops invalid veto rows outside the eligible ticker set into WARN source issues, while the recommendation quality gate still fails artifacts that have preselected candidates but no valid recommendation or veto. The launchd wrapper no longer emits `scheduler_container_failed` for recognized structured scheduler failure statuses such as `pipeline_failed`; that alert is reserved for host/container execution failures without an app status.
```

- [ ] **Step 3: Run documentation grep check**

Run:

```bash
rg -n "model_ineligible_veto_dropped|model_watch_veto_dropped|scheduler_container_failed|pipeline_failed" docs/operations.md docs/ARCHITECTURE.md
```

Expected: both docs contain relevant matches for the new behavior.

- [ ] **Step 4: Run targeted test suite**

Run:

```bash
UV_CACHE_DIR=.uv-cache uv run python -m pytest \
  tests/test_ai_brief_providers.py \
  tests/test_ai_brief.py::test_run_ai_brief_openai_drops_unknown_vetoed_candidate \
  tests/test_ai_brief_eval.py \
  tests/test_scheduled_ai_brief_runner.py::test_default_pipeline_raises_when_ai_brief_quality_gate_fails \
  tests/test_scheduled_ai_brief_runner.py::test_default_pipeline_returns_result_when_ai_brief_quality_warns \
  tests/test_launchd_scheduler_wrapper.py -q
```

Expected: PASS.

- [ ] **Step 5: Run repository quality gate**

Run:

```bash
just quality
```

Expected: PASS. If `just quality` fails because a pinned tool is missing, run `mise exec -- just quality`. If the failure is unrelated environment setup, record the exact command, failure, and the targeted tests that passed.

- [ ] **Step 6: Check diff and commit docs**

Run:

```bash
git diff --check
git status --short
git add docs/operations.md docs/ARCHITECTURE.md
git commit -m "docs(ai-brief): 모델 veto 진단과 host 알림 기준 문서화"
```

Expected: diff check passes and commit succeeds.

- [ ] **Step 7: Final review before handoff**

Run:

```bash
git log --oneline -4
git status --short
```

Expected: the last commits correspond to Tasks 1-4, and worktree is clean except for user-owned unrelated changes if any existed before implementation.
