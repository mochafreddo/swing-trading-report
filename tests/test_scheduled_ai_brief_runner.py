from __future__ import annotations

import datetime as dt
import threading
from dataclasses import dataclass, field

import pytest
import sab.scheduler.runner as scheduler_runner
from sab.scheduler.runner import (
    DefaultScheduledNotifier,
    DefaultScheduledPipeline,
    GuardSnapshot,
    ScheduledAiBriefRequest,
    ScheduledAiBriefRunner,
    ScheduledPipelineResult,
    build_attempt_id,
)
from sab.scheduler.state import (
    RuntimeStateEntry,
    RuntimeStateLockClaim,
    build_scheduler_state_key,
)


@dataclass
class _FakeStateStore:
    entries: dict[str, RuntimeStateEntry] = field(default_factory=dict)
    upserts: list[tuple[str, dict[str, object]]] = field(default_factory=list)
    claims: list[str] = field(default_factory=list)
    releases: list[str] = field(default_factory=list)
    renewals: list[str] = field(default_factory=list)
    ownership_results: list[bool] = field(default_factory=lambda: [True, True, True])
    preflight_calls: int = 0
    fail_attempt_upsert: bool = False
    fail_artifact_upsert: bool = False
    claim_results: list[bool] = field(default_factory=list)
    renewed_event: threading.Event | None = None

    def preflight(self) -> None:
        self.preflight_calls += 1

    def get_entry(self, key: str) -> RuntimeStateEntry | None:
        return self.entries.get(key)

    def list_entries(self, *, prefix: str, limit: int = 20) -> list[RuntimeStateEntry]:
        del limit
        return [entry for key, entry in self.entries.items() if key.startswith(prefix)]

    def upsert_marker(
        self,
        *,
        key: str,
        payload: dict[str, object],
        ttl_seconds: int,
        now: dt.datetime | None = None,
    ) -> None:
        if ":attempt:" in key and self.fail_attempt_upsert:
            raise RuntimeError("attempt write failed")
        if ":artifact:" in key and self.fail_artifact_upsert:
            raise RuntimeError("artifact write failed")
        self.upserts.append((key, payload))
        self.entries[key] = RuntimeStateEntry(
            state_key=key,
            state_payload=payload,
            expires_at="2026-05-30T00:00:00Z",
        )

    def claim_lock(
        self,
        *,
        key: str,
        owner_token: str,
        ttl_seconds: int,
        now: dt.datetime | None = None,
        payload: dict[str, object] | None = None,
    ) -> RuntimeStateLockClaim:
        self.claims.append(key)
        acquired = self.claim_results.pop(0) if self.claim_results else True
        return RuntimeStateLockClaim(acquired=acquired, expires_at="soon")

    def release_lock(self, key: str, *, owner_token: str) -> bool:
        self.releases.append(key)
        return True

    def renew_lock(self, key: str, *, owner_token: str, ttl_seconds: int) -> bool:
        self.renewals.append(key)
        if self.renewed_event is not None:
            self.renewed_event.set()
        return True

    def check_ownership(self, key: str, *, owner_token: str) -> bool:
        if not self.ownership_results:
            return True
        return self.ownership_results.pop(0)


@dataclass
class _FakePipeline:
    calls: list[tuple[str, dict[str, object]]] = field(default_factory=list)
    fail: bool = False

    def _record_call(
        self,
        *,
        market: str,
        session_date: str,
        report_date: str,
        source_provider: str | None,
        model_provider: str,
        dry_run: bool,
    ) -> None:
        self.calls.append(
            (
                "run",
                {
                    "market": market,
                    "session_date": session_date,
                    "report_date": report_date,
                    "source_provider": source_provider,
                    "model_provider": model_provider,
                    "dry_run": dry_run,
                },
            )
        )

    def run(
        self,
        *,
        market: str,
        session_date: str,
        report_date: str,
        source_provider: str | None,
        model_provider: str,
        dry_run: bool,
    ) -> ScheduledPipelineResult:
        self._record_call(
            market=market,
            session_date=session_date,
            report_date=report_date,
            source_provider=source_provider,
            model_provider=model_provider,
            dry_run=dry_run,
        )
        if self.fail:
            raise RuntimeError("pipeline failed")
        return ScheduledPipelineResult(
            ai_brief_report_path="reports/2026-05-28.ai-brief.json"
        )


@dataclass
class _BlockingPipeline(_FakePipeline):
    started_event: threading.Event = field(default_factory=threading.Event)
    finish_event: threading.Event = field(default_factory=threading.Event)

    def run(
        self,
        *,
        market: str,
        session_date: str,
        report_date: str,
        source_provider: str | None,
        model_provider: str,
        dry_run: bool,
    ) -> ScheduledPipelineResult:
        self._record_call(
            market=market,
            session_date=session_date,
            report_date=report_date,
            source_provider=source_provider,
            model_provider=model_provider,
            dry_run=dry_run,
        )
        self.started_event.set()
        if not self.finish_event.wait(timeout=1):
            raise AssertionError("pipeline was not released by the test")
        return ScheduledPipelineResult(
            ai_brief_report_path="reports/2026-05-28.ai-brief.json"
        )


@dataclass
class _FakeStorage:
    uploads: list[str] = field(default_factory=list)
    downloads: list[str] = field(default_factory=list)
    repair_candidates: list[str] = field(default_factory=list)
    payload_by_key: dict[str, dict[str, object]] = field(default_factory=dict)
    payload: dict[str, object] = field(
        default_factory=lambda: {
            "schema": "sab.ai_brief.v1",
            "type": "ai_brief",
            "market": "US",
            "report_date": "2026-05-28",
            "generated_at": "2026-05-28T08:15:00-04:00",
            "model_provider": "fake",
            "model_name": "fake-ai-brief-v1",
            "source_entry_report": "2026-05-28.entry.json",
            "summary": {},
            "recommendations": [],
            "excluded_candidates": [],
            "vetoed_candidates": [],
            "cap_excluded_candidates": [],
            "source_issues": [],
            "system_issues": [],
            "eligible_tickers": [],
            "brief_state": "NO_SIGNAL",
            "brief_reason": "no_enter_candidates",
        }
    )
    fail_upload: bool = False

    def upload_ai_brief(self, report_path: str, *, report_date: str) -> str:
        self.uploads.append(report_path)
        if self.fail_upload:
            raise RuntimeError("upload failed")
        storage_key = "2026/05/2026-05-28.ai-brief.json"
        self.payload_by_key[storage_key] = {
            **self.payload,
            "generated_at": "2026-05-28T08:15:00-04:00",
        }
        return storage_key

    def download_json(self, storage_key: str) -> dict[str, object]:
        self.downloads.append(storage_key)
        return dict(self.payload_by_key.get(storage_key, self.payload))

    def list_ai_brief_report_index(self, *, report_date: str) -> list[str]:
        del report_date
        return list(self.repair_candidates)


@dataclass
class _FakeNotifier:
    sent: list[str] = field(default_factory=list)
    telegram_ready: bool = True

    def require_telegram(self) -> None:
        if not self.telegram_ready:
            raise RuntimeError("telegram missing")

    def send_schedule(self, *, report: dict[str, object], storage_key: str) -> None:
        self.sent.append(storage_key)

    def send_late_alert(self, *, reason: str, context: dict[str, object]) -> None:
        self.sent.append(reason)


def _guard(
    *,
    session_state: str = "PRE_OPEN",
    trading_session: bool = True,
    session_date: str = "2026-05-28",
) -> GuardSnapshot:
    return GuardSnapshot(
        trading_session=trading_session,
        session_state=session_state,
        session_date=session_date,
        local_time="2026-05-28T08:10:00-04:00",
    )


def _runner(
    *,
    state: _FakeStateStore | None = None,
    pipeline: _FakePipeline | None = None,
    storage: _FakeStorage | None = None,
    notifier: _FakeNotifier | None = None,
    now: dt.datetime | None = None,
    guard: GuardSnapshot | None = None,
    guard_sequence: list[GuardSnapshot] | None = None,
    lock_renew_interval_seconds: float | None = None,
) -> tuple[
    ScheduledAiBriefRunner,
    _FakeStateStore,
    _FakePipeline,
    _FakeStorage,
    _FakeNotifier,
]:
    state = state or _FakeStateStore()
    pipeline = pipeline or _FakePipeline()
    storage = storage or _FakeStorage()
    notifier = notifier or _FakeNotifier()

    def resolve_guard(_market: str, _now: dt.datetime) -> GuardSnapshot:
        if guard_sequence is not None:
            if guard_sequence:
                return guard_sequence.pop(0)
            return _guard()
        return guard or _guard()

    runner = ScheduledAiBriefRunner(
        state_store=state,
        pipeline=pipeline,
        storage=storage,
        notifier=notifier,
        now_fn=lambda: now or dt.datetime(2026, 5, 28, 12, 10, tzinfo=dt.UTC),
        guard_resolver=resolve_guard,
        lock_renew_interval_seconds=lock_renew_interval_seconds,
    )
    return runner, state, pipeline, storage, notifier


def test_off_window_candidate_exits_before_runtime_state_preflight() -> None:
    runner, state, pipeline, storage, notifier = _runner(
        now=dt.datetime(2026, 5, 28, 13, 10, tzinfo=dt.UTC)
    )

    result = runner.run(
        ScheduledAiBriefRequest(
            market="US",
            schedule_role="local-primary",
            runner_role="local-primary",
            scheduled_tick="0810",
            attempt_id="attempt-1",
        )
    )

    assert result.status == "off_window_noop"
    assert state.preflight_calls == 0
    assert pipeline.calls == []
    assert storage.uploads == []
    assert notifier.sent == []


def test_pipeline_role_records_role_scoped_attempt_after_preflight() -> None:
    success_key = build_scheduler_state_key(
        kind="success", market="US", session_date="2026-05-28"
    )
    state = _FakeStateStore(
        entries={
            success_key: RuntimeStateEntry(
                state_key=success_key,
                state_payload={"done": True},
                expires_at="2026-05-30T00:00:00Z",
            )
        }
    )
    runner, state, _pipeline, _storage, _notifier = _runner(state=state)

    result = runner.run(
        ScheduledAiBriefRequest(
            market="US",
            schedule_role="local-primary",
            runner_role="local-primary",
            scheduled_tick="0810",
            attempt_id="attempt-2",
        )
    )

    attempt_key = build_scheduler_state_key(
        kind="attempt",
        market="US",
        session_date="2026-05-28",
        runner_role="local-primary",
        attempt_id="attempt-2",
    )
    assert result.status == "success_marker_skip"
    assert state.preflight_calls == 1
    assert state.upserts[0][0] == attempt_key
    assert state.upserts[0][1]["scheduledTick"] == "0810"
    assert state.upserts[0][1]["startedAt"] == "2026-05-28T12:10:00+00:00"


@pytest.mark.parametrize("runner_role", ["monitor-only", "cutoff-alert"])
def test_non_pipeline_roles_do_not_write_attempt_marker(runner_role: str) -> None:
    now = (
        dt.datetime(2026, 5, 28, 13, 30, tzinfo=dt.UTC)
        if runner_role == "cutoff-alert"
        else dt.datetime(2026, 5, 28, 12, 35, tzinfo=dt.UTC)
    )
    runner, state, _pipeline, _storage, _notifier = _runner(now=now)

    result = runner.run(
        ScheduledAiBriefRequest(
            market="US",
            schedule_role="early-monitor"
            if runner_role == "monitor-only"
            else runner_role,
            runner_role=runner_role,
            scheduled_tick="0830",
            attempt_id="attempt-3",
        )
    )

    assert result.status in {"monitor_local_primary_missing", "late_alert_sent"}
    assert all(":attempt:" not in key for key, _payload in state.upserts)


def test_cutoff_alert_skips_when_success_marker_exists() -> None:
    success_key = build_scheduler_state_key(
        kind="success", market="US", session_date="2026-05-28"
    )
    state = _FakeStateStore(
        entries={
            success_key: RuntimeStateEntry(
                state_key=success_key,
                state_payload={"done": True},
                expires_at="2026-05-30T00:00:00Z",
            )
        }
    )
    runner, state, _pipeline, _storage, notifier = _runner(
        state=state,
        now=dt.datetime(2026, 5, 28, 13, 30, tzinfo=dt.UTC),
    )

    result = runner.run(
        ScheduledAiBriefRequest(
            market="US",
            schedule_role="cutoff-alert",
            runner_role="cutoff-alert",
            scheduled_tick="0926",
            attempt_id="attempt-cutoff",
        )
    )

    assert result.status == "success_marker_skip"
    assert notifier.sent == []
    assert not any(":late-alert:" in key for key in state.claims)


def test_monitor_only_classifies_missing_local_primary_attempt() -> None:
    runner, state, pipeline, storage, notifier = _runner(
        now=dt.datetime(2026, 5, 28, 12, 35, tzinfo=dt.UTC)
    )

    result = runner.run(
        ScheduledAiBriefRequest(
            market="US",
            schedule_role="early-monitor",
            runner_role="monitor-only",
            scheduled_tick="0830",
            attempt_id="attempt-monitor",
        )
    )

    assert result.status == "monitor_local_primary_missing"
    assert pipeline.calls == []
    assert storage.uploads == []
    assert "local_primary_missing" in notifier.sent
    assert any(":late-alert:claim:" in key for key in state.claims)
    assert any(":late-alert:sent:" in key for key, _payload in state.upserts)


def test_monitor_only_observes_local_primary_attempt_without_alerting() -> None:
    attempt_key = build_scheduler_state_key(
        kind="attempt",
        market="US",
        session_date="2026-05-28",
        runner_role="local-primary",
        attempt_id="0810-started",
    )
    state = _FakeStateStore(
        entries={
            attempt_key: RuntimeStateEntry(
                state_key=attempt_key,
                state_payload={"runnerRole": "local-primary"},
                expires_at="2026-06-04T00:00:00Z",
            )
        }
    )
    runner, _state, pipeline, storage, notifier = _runner(
        state=state,
        now=dt.datetime(2026, 5, 28, 12, 35, tzinfo=dt.UTC),
    )

    result = runner.run(
        ScheduledAiBriefRequest(
            market="US",
            schedule_role="early-monitor",
            runner_role="monitor-only",
            scheduled_tick="0830",
            attempt_id="attempt-monitor",
        )
    )

    assert result.status == "monitor_local_primary_started"
    assert pipeline.calls == []
    assert storage.uploads == []
    assert notifier.sent == []


def test_attempt_marker_failure_stops_before_pipeline_generation() -> None:
    runner, _state, pipeline, _storage, _notifier = _runner(
        state=_FakeStateStore(fail_attempt_upsert=True)
    )

    result = runner.run(
        ScheduledAiBriefRequest(
            market="US",
            schedule_role="local-primary",
            runner_role="local-primary",
            scheduled_tick="0810",
            attempt_id="attempt-4",
        )
    )

    assert result.status == "attempt_marker_failed"
    assert pipeline.calls == []


def test_artifact_only_reconciliation_uses_notification_claim_without_main_lock() -> (
    None
):
    artifact_key = build_scheduler_state_key(
        kind="artifact", market="US", session_date="2026-05-28"
    )
    state = _FakeStateStore(
        entries={
            artifact_key: RuntimeStateEntry(
                state_key=artifact_key,
                state_payload={
                    "storageKey": "2026/05/2026-05-28.ai-brief.json",
                    "market": "US",
                    "sessionDate": "2026-05-28",
                    "reportDate": "2026-05-28",
                },
                expires_at="2026-05-30T00:00:00Z",
            )
        }
    )
    runner, state, pipeline, storage, notifier = _runner(
        state=state,
        now=dt.datetime(2026, 5, 28, 12, 45, tzinfo=dt.UTC),
    )

    result = runner.run(
        ScheduledAiBriefRequest(
            market="US",
            schedule_role="local-retry",
            runner_role="local-retry",
            scheduled_tick="0845",
            attempt_id="attempt-5",
        )
    )

    assert result.status == "notification_reconciled"
    assert pipeline.calls == []
    assert storage.downloads == ["2026/05/2026-05-28.ai-brief.json"]
    assert not any(":lock:" in key for key in state.claims)
    assert any(":notification:claim:" in key for key in state.claims)
    assert notifier.sent == ["2026/05/2026-05-28.ai-brief.json"]


def test_artifact_only_reconciliation_rejects_payload_outside_scheduled_window() -> (
    None
):
    artifact_key = build_scheduler_state_key(
        kind="artifact", market="US", session_date="2026-05-28"
    )
    state = _FakeStateStore(
        entries={
            artifact_key: RuntimeStateEntry(
                state_key=artifact_key,
                state_payload={
                    "storageKey": "2026/05/2026-05-28.ai-brief.json",
                    "market": "US",
                    "sessionDate": "2026-05-28",
                    "reportDate": "2026-05-28",
                },
                expires_at="2026-05-30T00:00:00Z",
            )
        }
    )
    storage = _FakeStorage()
    storage.payload = {
        **storage.payload,
        "generated_at": "2026-05-28T10:15:00-04:00",
    }
    runner, state, pipeline, storage, notifier = _runner(
        state=state,
        storage=storage,
        now=dt.datetime(2026, 5, 28, 12, 45, tzinfo=dt.UTC),
    )

    result = runner.run(
        ScheduledAiBriefRequest(
            market="US",
            schedule_role="local-retry",
            runner_role="local-retry",
            scheduled_tick="0845",
            attempt_id="attempt-artifact-invalid-window",
        )
    )

    assert result.status == "artifact_marker_invalid"
    assert pipeline.calls == []
    assert storage.downloads == ["2026/05/2026-05-28.ai-brief.json"]
    assert notifier.sent == []
    assert any(":notification:claim:" in key for key in state.releases)
    assert not any(":notification:sent:" in key for key, _payload in state.upserts)
    assert not any(":success:" in key for key, _payload in state.upserts)


def test_report_index_repair_happens_before_new_pipeline() -> None:
    state = _FakeStateStore()
    storage = _FakeStorage()
    storage.repair_candidates = ["2026/05/2026-05-28.ai-brief.json"]
    runner, state, pipeline, storage, _notifier = _runner(
        state=state,
        storage=storage,
        now=dt.datetime(2026, 5, 28, 12, 45, tzinfo=dt.UTC),
    )

    result = runner.run(
        ScheduledAiBriefRequest(
            market="US",
            schedule_role="local-retry",
            runner_role="local-retry",
            scheduled_tick="0845",
            attempt_id="attempt-repair",
        )
    )

    assert result.status == "notification_reconciled"
    assert pipeline.calls == []
    artifact_upserts = [
        payload for key, payload in state.upserts if ":artifact:" in key
    ]
    assert artifact_upserts
    assert artifact_upserts[0]["repairedFromReportIndex"] is True
    assert artifact_upserts[0]["storageKey"] == "2026/05/2026-05-28.ai-brief.json"


def test_report_index_repair_rejects_generated_at_outside_scheduled_window() -> None:
    state = _FakeStateStore()
    storage = _FakeStorage()
    storage.repair_candidates = ["2026/05/2026-05-28.ai-brief.json"]
    storage.payload = {
        **storage.payload,
        "generated_at": "2026-05-28T10:15:00-04:00",
    }
    runner, state, pipeline, storage, _notifier = _runner(
        state=state,
        storage=storage,
        now=dt.datetime(2026, 5, 28, 12, 45, tzinfo=dt.UTC),
    )

    result = runner.run(
        ScheduledAiBriefRequest(
            market="US",
            schedule_role="local-retry",
            runner_role="local-retry",
            scheduled_tick="0845",
            attempt_id="attempt-repair-outside-window",
        )
    )

    assert result.status == "completed"
    assert len(pipeline.calls) == 1
    repaired_artifacts = [
        payload
        for key, payload in state.upserts
        if ":artifact:" in key and payload.get("repairedFromReportIndex") is True
    ]
    assert repaired_artifacts == []


def test_runner_aborts_without_upload_when_lock_is_lost_before_upload() -> None:
    runner, _state, pipeline, storage, notifier = _runner(
        state=_FakeStateStore(ownership_results=[False])
    )

    result = runner.run(
        ScheduledAiBriefRequest(
            market="US",
            schedule_role="local-primary",
            runner_role="local-primary",
            scheduled_tick="0810",
            attempt_id="attempt-6",
        )
    )

    assert result.status == "lock_lost_before_upload"
    assert len(pipeline.calls) == 1
    assert storage.uploads == []
    assert notifier.sent == []


def test_runner_rechecks_pre_open_guard_before_upload() -> None:
    runner, state, pipeline, storage, notifier = _runner(
        guard_sequence=[
            _guard(session_state="PRE_OPEN"),
            _guard(session_state="INTRADAY"),
        ]
    )

    result = runner.run(
        ScheduledAiBriefRequest(
            market="US",
            schedule_role="local-primary",
            runner_role="local-primary",
            scheduled_tick="0810",
            attempt_id="attempt-guard-upload",
        )
    )

    assert result.status == "guard_failed_before_upload"
    assert len(pipeline.calls) == 1
    assert storage.uploads == []
    assert any(":lock:" in key for key in state.releases)
    assert "pre_upload_guard_failed" in notifier.sent


def test_runner_rechecks_guard_after_notification_claim_before_sending() -> None:
    runner, state, _pipeline, storage, notifier = _runner(
        guard_sequence=[
            _guard(session_state="PRE_OPEN"),
            _guard(session_state="PRE_OPEN"),
            _guard(session_state="INTRADAY"),
        ]
    )

    result = runner.run(
        ScheduledAiBriefRequest(
            market="US",
            schedule_role="local-primary",
            runner_role="local-primary",
            scheduled_tick="0810",
            attempt_id="attempt-guard-notify",
        )
    )

    assert result.status == "guard_failed_before_notification"
    assert storage.uploads == ["reports/2026-05-28.ai-brief.json"]
    assert "pre_notification_guard_failed" in notifier.sent
    assert "2026/05/2026-05-28.ai-brief.json" not in notifier.sent
    assert any(":notification:claim:" in key for key in state.releases)
    assert not any(":notification:sent:" in key for key, _payload in state.upserts)
    assert not any(":success:" in key for key, _payload in state.upserts)


def test_runner_renews_main_lock_after_pipeline_before_upload() -> None:
    runner, state, _pipeline, storage, _notifier = _runner()

    result = runner.run(
        ScheduledAiBriefRequest(
            market="US",
            schedule_role="local-primary",
            runner_role="local-primary",
            scheduled_tick="0810",
            attempt_id="attempt-renew",
        )
    )

    assert result.status == "completed"
    assert storage.uploads == ["reports/2026-05-28.ai-brief.json"]
    assert any(":lock:" in key for key in state.renewals)


def test_runner_renews_main_lock_while_pipeline_is_running() -> None:
    renewed = threading.Event()
    state = _FakeStateStore(renewed_event=renewed)
    pipeline = _BlockingPipeline()
    runner, _state, _pipeline, storage, _notifier = _runner(
        state=state,
        pipeline=pipeline,
        lock_renew_interval_seconds=0.01,
    )
    results: list[str] = []

    thread = threading.Thread(
        target=lambda: results.append(
            runner.run(
                ScheduledAiBriefRequest(
                    market="US",
                    schedule_role="local-primary",
                    runner_role="local-primary",
                    scheduled_tick="0810",
                    attempt_id="attempt-renew-during-pipeline",
                )
            ).status
        )
    )

    thread.start()
    assert pipeline.started_event.wait(timeout=1)
    assert renewed.wait(timeout=1)
    assert storage.uploads == []

    pipeline.finish_event.set()
    thread.join(timeout=1)

    assert results == ["completed"]
    assert storage.uploads == ["reports/2026-05-28.ai-brief.json"]


def test_runner_passes_session_date_as_ai_brief_report_date() -> None:
    runner, _state, pipeline, _storage, _notifier = _runner()

    result = runner.run(
        ScheduledAiBriefRequest(
            market="US",
            schedule_role="local-primary",
            runner_role="local-primary",
            scheduled_tick="0810",
            attempt_id="attempt-7",
        )
    )

    assert result.status == "completed"
    assert pipeline.calls[0][0] == "run"
    assert pipeline.calls[0][1]["report_date"] == "2026-05-28"


def test_runner_releases_main_lock_when_pipeline_fails() -> None:
    runner, state, _pipeline, _storage, notifier = _runner(
        pipeline=_FakePipeline(fail=True)
    )

    result = runner.run(
        ScheduledAiBriefRequest(
            market="US",
            schedule_role="local-primary",
            runner_role="local-primary",
            scheduled_tick="0810",
            attempt_id="attempt-8",
        )
    )

    assert result.status == "pipeline_failed"
    assert any(":lock:" in key for key in state.releases)
    assert notifier.sent == ["pipeline_failed"]


def test_runner_releases_main_lock_when_upload_fails() -> None:
    runner, state, _pipeline, _storage, notifier = _runner(
        storage=_FakeStorage(fail_upload=True)
    )

    result = runner.run(
        ScheduledAiBriefRequest(
            market="US",
            schedule_role="local-primary",
            runner_role="local-primary",
            scheduled_tick="0810",
            attempt_id="attempt-9",
        )
    )

    assert result.status == "upload_failed"
    assert any(":lock:" in key for key in state.releases)
    assert notifier.sent == ["upload_failed"]


def test_runner_releases_main_lock_when_artifact_marker_write_fails() -> None:
    runner, state, _pipeline, storage, notifier = _runner(
        state=_FakeStateStore(fail_artifact_upsert=True)
    )

    result = runner.run(
        ScheduledAiBriefRequest(
            market="US",
            schedule_role="local-primary",
            runner_role="local-primary",
            scheduled_tick="0810",
            attempt_id="attempt-artifact-marker-fail",
        )
    )

    assert result.status == "artifact_marker_failed"
    assert storage.uploads == ["reports/2026-05-28.ai-brief.json"]
    assert any(":lock:" in key for key in state.releases)
    assert "artifact_marker_failed" in notifier.sent


def test_invalid_artifact_marker_is_failed_scheduler_status() -> None:
    assert "artifact_marker_invalid" in scheduler_runner._FAILED_STATUSES


def test_default_pipeline_rechecks_pre_open_guard_before_entry(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    entry_calls: list[str] = []

    monkeypatch.setattr(
        "sab.scheduler.runner.load_config",
        lambda **_kwargs: type("Config", (), {"report_dir": "reports"})(),
    )
    monkeypatch.setattr("sab.scheduler.runner.run_scan", lambda **_kwargs: 0)
    monkeypatch.setattr(
        "sab.scheduler.runner._latest_report",
        lambda _report_dir, suffix: f"reports/2026-05-28.{suffix}.json",
    )
    monkeypatch.setattr(
        "sab.scheduler.runner.SupabaseHoldingsExportConfig.from_env",
        lambda: object(),
    )
    monkeypatch.setattr(
        "sab.scheduler.runner.export_active_holdings_snapshot",
        lambda **_kwargs: 1,
    )
    monkeypatch.setattr(
        "sab.scheduler.runner._default_guard_snapshot",
        lambda _market, _now: _guard(session_state="INTRADAY"),
    )

    def fake_run_entry(**_kwargs: object) -> int:
        entry_calls.append("entry")
        return 0

    monkeypatch.setattr("sab.scheduler.runner.run_entry", fake_run_entry)

    with pytest.raises(RuntimeError, match="pre-open guard failed before entry"):
        DefaultScheduledPipeline().run(
            market="US",
            session_date="2026-05-28",
            report_date="2026-05-28",
            source_provider=None,
            model_provider="fake",
            dry_run=False,
        )

    assert entry_calls == []


@pytest.mark.parametrize(
    ("schedule_role", "runner_role", "now"),
    [
        (
            "early-monitor",
            "monitor-only",
            dt.datetime(2026, 5, 28, 12, 35, tzinfo=dt.UTC),
        ),
        (
            "cutoff-alert",
            "cutoff-alert",
            dt.datetime(2026, 5, 28, 13, 30, tzinfo=dt.UTC),
        ),
    ],
)
def test_monitor_and_cutoff_do_not_alert_when_trading_session_guard_fails(
    schedule_role: str,
    runner_role: str,
    now: dt.datetime,
) -> None:
    runner, state, pipeline, storage, notifier = _runner(
        now=now,
        guard=_guard(trading_session=False),
    )

    result = runner.run(
        ScheduledAiBriefRequest(
            market="US",
            schedule_role=schedule_role,
            runner_role=runner_role,
            scheduled_tick="0830" if runner_role == "monitor-only" else "0926",
            attempt_id="attempt-non-trading",
        )
    )

    assert result.status == "guard_noop"
    assert pipeline.calls == []
    assert storage.uploads == []
    assert notifier.sent == []
    assert not any(":late-alert:" in key for key in state.claims)


def test_monitor_only_classifies_local_primary_lock_without_alerting() -> None:
    lock_key = build_scheduler_state_key(
        kind="lock", market="US", session_date="2026-05-28"
    )
    state = _FakeStateStore(
        entries={
            lock_key: RuntimeStateEntry(
                state_key=lock_key,
                state_payload={"runnerRole": "local-primary"},
                expires_at="2026-05-28T13:05:00Z",
            )
        }
    )
    runner, _state, pipeline, storage, notifier = _runner(
        state=state,
        now=dt.datetime(2026, 5, 28, 12, 35, tzinfo=dt.UTC),
    )

    result = runner.run(
        ScheduledAiBriefRequest(
            market="US",
            schedule_role="early-monitor",
            runner_role="monitor-only",
            scheduled_tick="0830",
            attempt_id="attempt-monitor-lock",
        )
    )

    assert result.status == "monitor_local_primary_lock_active"
    assert pipeline.calls == []
    assert storage.uploads == []
    assert notifier.sent == []


def test_default_notifier_treats_slack_failure_as_best_effort(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[str] = []

    class _Response:
        status_code = 200

    def fake_post(url: str, **kwargs: object) -> _Response:
        del kwargs
        calls.append(url)
        if "hooks.slack.com" in url:
            raise RuntimeError("slack down")
        return _Response()

    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "token")
    monkeypatch.setenv("TELEGRAM_CHAT_ID", "chat")
    monkeypatch.setenv("SLACK_WEBHOOK_URL", "https://hooks.slack.com/services/test")
    monkeypatch.setattr("sab.scheduler.runner.requests.post", fake_post)

    DefaultScheduledNotifier().send_schedule(
        report=_FakeStorage().payload,
        storage_key="2026/05/2026-05-28.ai-brief.json",
    )

    assert any("api.telegram.org" in url for url in calls)
    assert any("hooks.slack.com" in url for url in calls)


def test_build_attempt_id_includes_tick_and_utc_started_at() -> None:
    assert (
        build_attempt_id(
            scheduled_tick="0810",
            started_at=dt.datetime(2026, 5, 28, 12, 10, tzinfo=dt.UTC),
            suffix="pid123",
        )
        == "0810-20260528T121000Z-pid123"
    )
