## What you implemented

- Added executable wrapper tests that run `scripts/launchd/sab-ai-brief-wrapper.sh` with stubbed `uv`, `docker`, and `curl` binaries.
- Added `is_structured_scheduler_failure_status` to recognize the structured scheduler failure statuses from the brief.
- Added `extract_scheduler_status` to read the final non-empty stdout line and extract the JSON `status` field.
- Changed the wrapper's final scheduler execution path so it still streams scheduler stdout live while capturing stdout for post-exit classification.
- Preserved `send_host_failure_alert "docker_daemon_unavailable"`.
- Suppressed `send_host_failure_alert "scheduler_container_failed"` when the scheduler exits non-zero after printing a recognized structured failure status.

## Test commands and results

- `UV_CACHE_DIR=.uv-cache uv run python -m pytest tests/test_launchd_scheduler_wrapper.py -q`
  - Result: `10 passed in 1.93s`
- `bash -n scripts/launchd/sab-ai-brief-wrapper.sh`
  - Result: exit 0

## TDD Evidence

### RED command/output summary

- Command:
  - `UV_CACHE_DIR=.uv-cache uv run python -m pytest tests/test_launchd_scheduler_wrapper.py::test_launchd_wrapper_suppresses_host_failure_for_structured_pipeline_failed tests/test_launchd_scheduler_wrapper.py::test_launchd_wrapper_sends_host_failure_without_structured_status -q`
- First harness run failed for the wrong reason because the wrapper's hardcoded `PATH` bypassed the test stubs.
- After fixing the harness to execute a temporary wrapper copy with stub `PATH` precedence, the RED run produced the intended failure:
  - `1 failed, 1 passed`
  - Failing assertion: `alerts.log` existed for `{"status": "pipeline_failed", "storage_key": null}`, proving the wrapper still sent the duplicate `scheduler_container_failed` host alert.

### GREEN command/output summary

- Command:
  - `UV_CACHE_DIR=.uv-cache uv run python -m pytest tests/test_launchd_scheduler_wrapper.py -q`
- Result:
  - `10 passed in 1.93s`
- Syntax verification:
  - `bash -n scripts/launchd/sab-ai-brief-wrapper.sh`
  - exit 0

## Files changed

- `/Users/mochafreddo/GitHub/swing-trading-report/scripts/launchd/sab-ai-brief-wrapper.sh`
- `/Users/mochafreddo/GitHub/swing-trading-report/tests/test_launchd_scheduler_wrapper.py`

## Self-review findings

- The wrapper now preserves live stdout streaming and inspects only the final non-empty stdout line for structured scheduler JSON status, matching the brief's intent.
- `docker_daemon_unavailable` behavior remains unchanged and still sends a host alert before any container run.
- Unstructured container failures still send `scheduler_container_failed`.
- Test coverage exercises both the suppression path and the fallback host-alert path through real wrapper execution.

## Any issues or concerns

- I deviated from the brief's process-substitution example because this sandbox rejects `> >(tee ...)` with `/dev/fd/...: Operation not permitted`.
- The replacement uses a FIFO plus background `tee`, which is behaviorally equivalent for this task: stdout still streams live to the parent process, stderr still flows directly, and the wrapper retains a stdout capture file for final structured status inspection.
