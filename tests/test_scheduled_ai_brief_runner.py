from __future__ import annotations

import datetime as dt
import json
import logging
import os
import threading
import unicodedata
from dataclasses import dataclass, field
from pathlib import Path
from types import SimpleNamespace

import pytest
import sab.scheduler.runner as scheduler_runner
from sab.config import load_config
from sab.config_loader import ConfigLoadError
from sab.env_loader import getenv, load_dotenv_if_available
from sab.scheduler import status_file as scheduler_status_file
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

_SCHEDULED_SOURCE_ENV_KEYS = (
    "AI_BRIEF_SOURCE_PROVIDER_CHAIN_KR",
    "AI_BRIEF_SOURCE_PROVIDER_CHAIN_US",
    "AI_BRIEF_SOURCE_PROVIDER_CHAIN",
    "AI_BRIEF_SOURCE_PROVIDER_KR",
    "AI_BRIEF_SOURCE_PROVIDER_US",
    "AI_BRIEF_SOURCE_PROVIDER",
    "AI_BRIEF_SOURCE_API_URL_KR",
    "AI_BRIEF_SOURCE_API_URL_US",
    "AI_BRIEF_SOURCE_API_URL",
)


@pytest.fixture(autouse=True)
def _clear_scheduled_source_env(monkeypatch: pytest.MonkeyPatch) -> None:
    for key in _SCHEDULED_SOURCE_ENV_KEYS:
        monkeypatch.delenv(key, raising=False)


@pytest.fixture(autouse=True)
def _scheduled_ai_brief_quality_pass(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        scheduler_runner,
        "evaluate_ai_brief_recommendation_report",
        lambda **_kwargs: SimpleNamespace(status="PASS", issues=[]),
    )


def _log_records_for_event(
    caplog: pytest.LogCaptureFixture,
    event: str,
) -> list[logging.LogRecord]:
    return [
        record for record in caplog.records if getattr(record, "event", None) == event
    ]


@dataclass
class _FakeStateStore:
    entries: dict[str, RuntimeStateEntry] = field(default_factory=dict)
    upserts: list[tuple[str, dict[str, object]]] = field(default_factory=list)
    events: list[tuple[str, str]] = field(default_factory=list)
    claims: list[str] = field(default_factory=list)
    claim_payloads: list[tuple[str, dict[str, object] | None]] = field(
        default_factory=list
    )
    releases: list[str] = field(default_factory=list)
    renewals: list[str] = field(default_factory=list)
    ownership_results: list[bool] = field(default_factory=lambda: [True, True, True])
    preflight_calls: int = 0
    fail_attempt_upsert: bool = False
    fail_artifact_upsert: bool = False
    fail_entry_failure_artifact_upsert: bool = False
    fail_skip_artifact_upsert: bool = False
    fail_notification_sent_upsert: bool = False
    fail_late_alert_sent_upsert: bool = False
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
        self.events.append(("upsert", key))
        if ":attempt:" in key and self.fail_attempt_upsert:
            raise RuntimeError("attempt write failed")
        if ":artifact:" in key and self.fail_artifact_upsert:
            raise RuntimeError("artifact write failed")
        if (
            ":entry-failure-artifact:" in key
            and self.fail_entry_failure_artifact_upsert
        ):
            raise RuntimeError("entry failure artifact write failed")
        if ":skip-artifact:" in key and self.fail_skip_artifact_upsert:
            raise RuntimeError("skip artifact write failed")
        if ":notification:sent:" in key and self.fail_notification_sent_upsert:
            raise RuntimeError("notification sent write failed")
        if ":late-alert:sent:" in key and self.fail_late_alert_sent_upsert:
            raise RuntimeError("late alert sent write failed")
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
        self.claim_payloads.append((key, payload))
        acquired = self.claim_results.pop(0) if self.claim_results else True
        return RuntimeStateLockClaim(acquired=acquired, expires_at="soon")

    def release_lock(self, key: str, *, owner_token: str) -> bool:
        self.events.append(("release", key))
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
    failure_message: str = "pipeline failed"

    def _record_call(
        self,
        *,
        market: str,
        session_date: str,
        report_date: str,
        source_provider: str | None,
        model_provider: str,
        dry_run: bool,
        model_deadline_remaining_seconds: float | None = None,
        model_deadline_at: dt.datetime | None = None,
        source_api_url: str | None = None,
        source_provider_chain: tuple[str, ...] | None = None,
    ) -> None:
        self.calls.append(
            (
                "run",
                {
                    "market": market,
                    "session_date": session_date,
                    "report_date": report_date,
                    "source_provider": source_provider,
                    "source_api_url": source_api_url,
                    "source_provider_chain": source_provider_chain,
                    "model_provider": model_provider,
                    "dry_run": dry_run,
                    "model_deadline_remaining_seconds": (
                        model_deadline_remaining_seconds
                    ),
                    "model_deadline_at": model_deadline_at,
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
        model_deadline_remaining_seconds: float | None = None,
        model_deadline_at: dt.datetime | None = None,
        source_api_url: str | None = None,
        source_provider_chain: tuple[str, ...] | None = None,
    ) -> ScheduledPipelineResult:
        self._record_call(
            market=market,
            session_date=session_date,
            report_date=report_date,
            source_provider=source_provider,
            source_api_url=source_api_url,
            source_provider_chain=source_provider_chain,
            model_provider=model_provider,
            dry_run=dry_run,
            model_deadline_remaining_seconds=model_deadline_remaining_seconds,
            model_deadline_at=model_deadline_at,
        )
        if self.fail:
            raise RuntimeError(self.failure_message)
        return ScheduledPipelineResult(
            ai_brief_report_path="reports/2026-05-28.ai-brief.json"
        )


@dataclass
class _TypedEntryFailurePipeline(_FakePipeline):
    entry_report_path: str = "reports/current.entry.json"

    def run(
        self,
        *,
        market: str,
        session_date: str,
        report_date: str,
        source_provider: str | None,
        model_provider: str,
        dry_run: bool,
        model_deadline_remaining_seconds: float | None = None,
        model_deadline_at: dt.datetime | None = None,
        source_api_url: str | None = None,
        source_provider_chain: tuple[str, ...] | None = None,
    ) -> ScheduledPipelineResult:
        self._record_call(
            market=market,
            session_date=session_date,
            report_date=report_date,
            source_provider=source_provider,
            source_api_url=source_api_url,
            source_provider_chain=source_provider_chain,
            model_provider=model_provider,
            dry_run=dry_run,
            model_deadline_remaining_seconds=model_deadline_remaining_seconds,
            model_deadline_at=model_deadline_at,
        )
        raise scheduler_runner._ScheduledEntryStepError(self.entry_report_path)


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
        model_deadline_remaining_seconds: float | None = None,
        model_deadline_at: dt.datetime | None = None,
        source_api_url: str | None = None,
        source_provider_chain: tuple[str, ...] | None = None,
    ) -> ScheduledPipelineResult:
        self._record_call(
            market=market,
            session_date=session_date,
            report_date=report_date,
            source_provider=source_provider,
            source_api_url=source_api_url,
            source_provider_chain=source_provider_chain,
            model_provider=model_provider,
            dry_run=dry_run,
            model_deadline_remaining_seconds=model_deadline_remaining_seconds,
            model_deadline_at=model_deadline_at,
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
    entry_uploads: list[str] = field(default_factory=list)
    skip_uploads: list[str] = field(default_factory=list)
    downloads: list[str] = field(default_factory=list)
    repair_candidates: list[str] = field(default_factory=list)
    payload_by_key: dict[str, dict[str, object]] = field(default_factory=dict)
    uploaded_generated_at: str = "2026-05-28T08:15:00-04:00"
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
    fail_skip_upload: bool = False
    fail_download: bool = False

    def upload_ai_brief(self, report_path: str, *, report_date: str) -> str:
        self.uploads.append(report_path)
        if self.fail_upload:
            raise RuntimeError("upload failed")
        storage_key = "2026/05/2026-05-28.ai-brief.json"
        self.payload_by_key[storage_key] = {
            **self.payload,
            "generated_at": self.uploaded_generated_at,
        }
        return storage_key

    def upload_entry_report(self, report_path: str, *, report_date: str) -> str:
        self.entry_uploads.append(report_path)
        return f"2026/05/{report_date}.entry.json"

    def upload_ai_brief_skip(self, report_path: str, *, report_date: str) -> str:
        self.skip_uploads.append(report_path)
        if self.fail_skip_upload:
            raise RuntimeError("skip upload failed")
        return f"2026/05/{report_date}.ai-brief-skip.json"

    def download_json(self, storage_key: str) -> dict[str, object]:
        self.downloads.append(storage_key)
        if self.fail_download:
            raise RuntimeError("download failed")
        return dict(self.payload_by_key.get(storage_key, self.payload))

    def list_ai_brief_report_index(self, *, report_date: str) -> list[str]:
        del report_date
        return list(self.repair_candidates)


@dataclass
class _FakeNotifier:
    sent: list[str] = field(default_factory=list)
    late_alerts: list[tuple[str, dict[str, object]]] = field(default_factory=list)
    telegram_ready: bool = True
    fail_late_alert: bool = False

    def require_telegram(self) -> None:
        if not self.telegram_ready:
            raise RuntimeError("telegram missing")

    def send_schedule(self, *, report: dict[str, object], storage_key: str) -> None:
        self.sent.append(storage_key)

    def send_late_alert(self, *, reason: str, context: dict[str, object]) -> None:
        if self.fail_late_alert:
            raise RuntimeError("late alert delivery failed")
        self.sent.append(reason)
        self.late_alerts.append((reason, dict(context)))


@dataclass
class _BlockingScheduleNotifier(_FakeNotifier):
    send_started_event: threading.Event = field(default_factory=threading.Event)
    release_event: threading.Event = field(default_factory=threading.Event)

    def send_schedule(self, *, report: dict[str, object], storage_key: str) -> None:
        self.send_started_event.set()
        if not self.release_event.wait(timeout=1):
            raise AssertionError("notification send was not released by the test")
        super().send_schedule(report=report, storage_key=storage_key)


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


def test_run_context_helper_normalizes_request_and_builds_attempt_id(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class _FixedUuid:
        hex = "abcdef1234567890"

    monkeypatch.setattr(scheduler_runner.os, "getpid", lambda: 12345)
    monkeypatch.setattr(scheduler_runner.uuid, "uuid4", lambda: _FixedUuid())
    runner, state, pipeline, storage, notifier = _runner()

    assert hasattr(runner, "_resolve_run_context")

    context = runner._resolve_run_context(
        ScheduledAiBriefRequest(
            market=" us ",
            schedule_role=" LOCAL-PRIMARY ",
            runner_role=" LOCAL-PRIMARY ",
            scheduled_tick="0810",
        )
    )

    assert isinstance(context, scheduler_runner._ScheduledRunContext)
    assert context.now == dt.datetime(2026, 5, 28, 12, 10, tzinfo=dt.UTC)
    assert context.market == "US"
    assert context.schedule_role == "local-primary"
    assert context.runner_role == "local-primary"
    assert context.scheduled_tick == "0810"
    assert context.guard == _guard()
    assert context.session_date == "2026-05-28"
    assert context.attempt_id == "0810-20260528T121000Z-pid12345-abcdef12"
    assert state.preflight_calls == 0
    assert pipeline.calls == []
    assert storage.uploads == []
    assert notifier.sent == []


def test_invalid_scheduled_tick_exits_before_runtime_state_preflight() -> None:
    runner, state, pipeline, storage, notifier = _runner()

    result = runner.run(
        ScheduledAiBriefRequest(
            market="US",
            schedule_role="local-primary",
            runner_role="local-primary",
            scheduled_tick="2460",
            attempt_id=None,
        )
    )

    assert result.status == "invalid_scheduled_tick"
    assert result.session_date is None
    assert state.preflight_calls == 0
    assert state.upserts == []
    assert pipeline.calls == []
    assert storage.uploads == []
    assert notifier.sent == []


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


def test_github_fallback_runs_inside_bounded_queue_grace() -> None:
    storage = _FakeStorage(uploaded_generated_at="2026-05-28T09:27:00-04:00")
    runner, state, pipeline, storage, notifier = _runner(
        storage=storage,
        now=dt.datetime(2026, 5, 28, 13, 27, tzinfo=dt.UTC),
    )

    result = runner.run(
        ScheduledAiBriefRequest(
            market="US",
            schedule_role="github-fallback",
            runner_role="github-fallback",
            scheduled_tick="0855",
            attempt_id="attempt-github-queued",
        )
    )

    assert result.status == "completed"
    assert len(pipeline.calls) == 1
    assert storage.uploads == ["reports/2026-05-28.ai-brief.json"]
    assert notifier.sent == ["2026/05/2026-05-28.ai-brief.json"]
    assert any(
        ":attempt:US:2026-05-28:github-fallback:" in key for key, _ in state.upserts
    )


def test_runner_passes_role_deadline_remaining_seconds_to_pipeline() -> None:
    runner, state, pipeline, storage, notifier = _runner()

    result = runner.run(
        ScheduledAiBriefRequest(
            market="US",
            schedule_role="local-primary",
            runner_role="local-primary",
            scheduled_tick="0810",
            attempt_id="attempt-deadline-budget",
        )
    )

    assert result.status == "completed"
    assert pipeline.calls[0][1]["model_deadline_at"] == dt.datetime(
        2026, 5, 28, 12, 30, tzinfo=dt.UTC
    )
    assert state.preflight_calls == 1
    assert storage.uploads == ["reports/2026-05-28.ai-brief.json"]
    assert notifier.sent == ["2026/05/2026-05-28.ai-brief.json"]


def test_github_fallback_queue_grace_remains_bounded() -> None:
    runner, state, pipeline, storage, notifier = _runner(
        now=dt.datetime(2026, 5, 28, 13, 29, tzinfo=dt.UTC),
    )

    result = runner.run(
        ScheduledAiBriefRequest(
            market="US",
            schedule_role="github-fallback",
            runner_role="github-fallback",
            scheduled_tick="0855",
            attempt_id="attempt-github-too-late",
        )
    )

    assert result.status == "off_window_noop"
    assert state.preflight_calls == 0
    assert pipeline.calls == []
    assert storage.uploads == []
    assert notifier.sent == []


def test_scheduled_artifact_window_ends_at_fallback_grace_boundary() -> None:
    assert scheduler_runner._is_generated_during_scheduled_window(
        market="US",
        session_date="2026-05-28",
        generated_at="2026-05-28T09:28:59-04:00",
    )
    assert not scheduler_runner._is_generated_during_scheduled_window(
        market="US",
        session_date="2026-05-28",
        generated_at="2026-05-28T09:29:00-04:00",
    )


def test_cutoff_alert_waits_until_fallback_grace_expires() -> None:
    runner, state, pipeline, storage, notifier = _runner(
        now=dt.datetime(2026, 5, 28, 13, 26, tzinfo=dt.UTC),
    )

    # Keep the stale 0926 candidate as a regression guard: old cutoff ticks must
    # no-op while the GitHub fallback role is still inside its bounded grace.
    result = runner.run(
        ScheduledAiBriefRequest(
            market="US",
            schedule_role="cutoff-alert",
            runner_role="cutoff-alert",
            scheduled_tick="0926",
            attempt_id="attempt-cutoff-too-early",
        )
    )

    assert result.status == "off_window_noop"
    assert state.preflight_calls == 0
    assert pipeline.calls == []
    assert storage.uploads == []
    assert notifier.sent == []


def test_cutoff_alert_runs_after_fallback_grace_expires() -> None:
    runner, state, pipeline, storage, notifier = _runner(
        now=dt.datetime(2026, 5, 28, 13, 29, tzinfo=dt.UTC),
    )

    result = runner.run(
        ScheduledAiBriefRequest(
            market="US",
            schedule_role="cutoff-alert",
            runner_role="cutoff-alert",
            scheduled_tick="0929",
            attempt_id="attempt-cutoff-after-grace",
        )
    )

    assert result.status == "late_alert_sent"
    assert state.preflight_calls == 1
    assert pipeline.calls == []
    assert storage.uploads == []
    assert notifier.sent == ["cutoff_missing_ai_brief"]
    assert notifier.late_alerts == [
        (
            "cutoff_missing_ai_brief",
            {
                "market": "US",
                "sessionDate": "2026-05-28",
                "scheduleRole": "cutoff-alert",
                "runnerRole": "cutoff-alert",
                "attemptId": "attempt-cutoff-after-grace",
            },
        )
    ]
    sent_payloads = [
        payload
        for key, payload in state.upserts
        if ":late-alert:sent:US:2026-05-28:cutoff_missing_ai_brief" in key
    ]
    assert sent_payloads == [
        {
            "market": "US",
            "sessionDate": "2026-05-28",
            "reason": "cutoff_missing_ai_brief",
            "scheduleRole": "cutoff-alert",
            "runnerRole": "cutoff-alert",
            "attemptId": "attempt-cutoff-after-grace",
        }
    ]


def test_late_alert_sent_marker_failure_reports_failure_after_delivery() -> None:
    runner, state, pipeline, storage, notifier = _runner(
        state=_FakeStateStore(fail_late_alert_sent_upsert=True),
        now=dt.datetime(2026, 5, 28, 13, 29, tzinfo=dt.UTC),
    )

    result = runner.run(
        ScheduledAiBriefRequest(
            market="US",
            schedule_role="cutoff-alert",
            runner_role="cutoff-alert",
            scheduled_tick="0929",
            attempt_id="attempt-cutoff-marker-fail",
        )
    )

    assert result.status == "late_alert_sent_marker_failed"
    assert pipeline.calls == []
    assert storage.uploads == []
    assert notifier.sent == ["cutoff_missing_ai_brief"]
    assert any(":late-alert:claim:" in key for key in state.releases)
    assert "late_alert_sent_marker_failed" in scheduler_runner._FAILED_STATUSES


def test_late_alert_delivery_failure_does_not_write_sent_marker() -> None:
    runner, state, pipeline, storage, notifier = _runner(
        notifier=_FakeNotifier(fail_late_alert=True),
        now=dt.datetime(2026, 5, 28, 13, 29, tzinfo=dt.UTC),
    )

    result = runner.run(
        ScheduledAiBriefRequest(
            market="US",
            schedule_role="cutoff-alert",
            runner_role="cutoff-alert",
            scheduled_tick="0929",
            attempt_id="attempt-cutoff-send-fail",
        )
    )

    assert result.status == "late_alert_send_failed"
    assert pipeline.calls == []
    assert storage.uploads == []
    assert notifier.sent == []
    assert not any(":late-alert:sent:" in key for key, _payload in state.upserts)
    assert any(":late-alert:claim:" in key for key in state.releases)
    assert "late_alert_send_failed" in scheduler_runner._FAILED_STATUSES


def test_late_alert_telegram_preflight_failure_does_not_write_sent_marker() -> None:
    runner, state, pipeline, storage, notifier = _runner(
        notifier=_FakeNotifier(telegram_ready=False),
        now=dt.datetime(2026, 5, 28, 13, 29, tzinfo=dt.UTC),
    )

    result = runner.run(
        ScheduledAiBriefRequest(
            market="US",
            schedule_role="cutoff-alert",
            runner_role="cutoff-alert",
            scheduled_tick="0929",
            attempt_id="attempt-cutoff-telegram-missing",
        )
    )

    assert result.status == "late_alert_send_failed"
    assert pipeline.calls == []
    assert storage.uploads == []
    assert notifier.sent == []
    assert not any(":late-alert:sent:" in key for key, _payload in state.upserts)
    assert any(":late-alert:claim:" in key for key in state.releases)


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
            scheduled_tick="0830" if runner_role == "monitor-only" else "0929",
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
            scheduled_tick="0929",
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


def test_pipeline_attempt_marker_helper_records_role_scoped_payload() -> None:
    runner, state, _pipeline, _storage, _notifier = _runner()

    result = runner._record_pipeline_attempt_marker(
        market="US",
        session_date="2026-05-28",
        schedule_role="local-primary",
        runner_role="local-primary",
        scheduled_tick="0810",
        attempt_id="attempt-helper",
        run_url="https://github.com/owner/repo/actions/runs/1",
        now=dt.datetime(2026, 5, 28, 12, 10, tzinfo=dt.UTC),
    )

    attempt_key = build_scheduler_state_key(
        kind="attempt",
        market="US",
        session_date="2026-05-28",
        runner_role="local-primary",
        attempt_id="attempt-helper",
    )
    assert result is None
    assert state.upserts[0][0] == attempt_key
    assert state.upserts[0][1]["runner"] == "local"
    assert state.upserts[0][1]["runUrl"] == (
        "https://github.com/owner/repo/actions/runs/1"
    )


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


def test_main_lock_renewer_stays_active_during_locked_notification_send() -> None:
    state = _FakeStateStore()
    notifier = _BlockingScheduleNotifier()
    runner, state, _pipeline, _storage, _returned_notifier = _runner(
        state=state,
        notifier=notifier,
        lock_renew_interval_seconds=0.01,
    )
    renewed_during_send = threading.Event()
    results: list[scheduler_runner.ScheduledAiBriefResult] = []

    thread = threading.Thread(
        target=lambda: results.append(
            runner.run(
                ScheduledAiBriefRequest(
                    market="US",
                    schedule_role="local-primary",
                    runner_role="local-primary",
                    scheduled_tick="0810",
                    attempt_id="attempt-renew-during-notification",
                )
            )
        ),
        daemon=True,
    )
    thread.start()

    assert notifier.send_started_event.wait(timeout=1)
    state.renewed_event = renewed_during_send
    try:
        assert renewed_during_send.wait(timeout=1)
    finally:
        notifier.release_event.set()
        thread.join(timeout=1)

    assert not thread.is_alive()
    assert results[0].status == "completed"
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


def test_artifact_only_reconciliation_releases_notification_claim_when_download_fails() -> (
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
    runner, state, _pipeline, storage, notifier = _runner(
        state=state,
        storage=_FakeStorage(fail_download=True),
        now=dt.datetime(2026, 5, 28, 12, 45, tzinfo=dt.UTC),
    )

    with pytest.raises(RuntimeError, match="download failed"):
        runner.run(
            ScheduledAiBriefRequest(
                market="US",
                schedule_role="local-retry",
                runner_role="local-retry",
                scheduled_tick="0845",
                attempt_id="attempt-download-fail",
            )
        )

    assert storage.downloads == ["2026/05/2026-05-28.ai-brief.json"]
    assert notifier.sent == []
    assert any(":notification:claim:" in key for key in state.releases)


def test_artifact_only_reconciliation_releases_notification_claim_when_sent_marker_fails() -> (
    None
):
    artifact_key = build_scheduler_state_key(
        kind="artifact", market="US", session_date="2026-05-28"
    )
    state = _FakeStateStore(
        fail_notification_sent_upsert=True,
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
        },
    )
    runner, state, _pipeline, _storage, notifier = _runner(
        state=state,
        now=dt.datetime(2026, 5, 28, 12, 45, tzinfo=dt.UTC),
    )

    with pytest.raises(RuntimeError, match="notification sent write failed"):
        runner.run(
            ScheduledAiBriefRequest(
                market="US",
                schedule_role="local-retry",
                runner_role="local-retry",
                scheduled_tick="0845",
                attempt_id="attempt-sent-marker-fail",
            )
        )

    assert notifier.sent == ["2026/05/2026-05-28.ai-brief.json"]
    assert any(":notification:claim:" in key for key in state.releases)


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


def test_existing_artifact_reconciliation_repairs_index_candidate() -> None:
    state = _FakeStateStore()
    storage = _FakeStorage()
    storage.repair_candidates = ["2026/05/2026-05-28.ai-brief.json"]
    runner, state, _pipeline, storage, notifier = _runner(
        state=state,
        storage=storage,
        now=dt.datetime(2026, 5, 28, 12, 45, tzinfo=dt.UTC),
    )

    result = runner._reconcile_existing_or_repaired_artifact(
        market="US",
        session_date="2026-05-28",
        schedule_role="local-retry",
        runner_role="local-retry",
        attempt_id="attempt-repair-helper",
        run_url="",
        now=dt.datetime(2026, 5, 28, 12, 45, tzinfo=dt.UTC),
    )

    assert result is not None
    assert result.status == "notification_reconciled"
    assert storage.downloads == [
        "2026/05/2026-05-28.ai-brief.json",
        "2026/05/2026-05-28.ai-brief.json",
    ]
    assert notifier.sent == ["2026/05/2026-05-28.ai-brief.json"]
    assert not any(":lock:" in key for key in state.claims)
    assert any(
        payload.get("repairedFromReportIndex") is True
        for key, payload in state.upserts
        if ":artifact:" in key
    )


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
    assert "lock_lost_before_upload" in scheduler_runner._FAILED_STATUSES
    assert len(pipeline.calls) == 1
    assert storage.uploads == []
    assert notifier.sent == []


def test_runner_does_not_publish_failure_alert_when_lock_is_lost() -> None:
    state = _FakeStateStore(ownership_results=[False])
    runner, state, _pipeline, _storage, notifier = _runner(
        state=state,
        pipeline=_FakePipeline(fail=True),
    )

    result = runner.run(
        ScheduledAiBriefRequest(
            market="US",
            schedule_role="local-primary",
            runner_role="local-primary",
            scheduled_tick="0810",
            attempt_id="attempt-failure-lock-lost",
        )
    )

    assert result.status == "lock_lost_before_upload"
    assert any(":lock:" in key for key in state.renewals)
    assert any(":lock:" in key for key in state.releases)
    assert notifier.sent == []
    assert notifier.late_alerts == []
    assert not any(":late-alert:sent:" in key for key, _payload in state.upserts)


def test_runner_does_not_publish_unsafe_entry_failure_alert_when_lock_is_lost() -> None:
    state = _FakeStateStore(ownership_results=[False])
    runner, state, _pipeline, storage, notifier = _runner(
        state=state,
        pipeline=_TypedEntryFailurePipeline(entry_report_path="unsafe"),
    )

    result = runner.run(
        ScheduledAiBriefRequest(
            market="US",
            schedule_role="local-primary",
            runner_role="local-primary",
            scheduled_tick="0810",
            attempt_id="attempt-unsafe-entry-lock-lost",
        )
    )

    assert result.status == "lock_lost_before_upload"
    assert storage.entry_uploads == []
    assert any(":lock:" in key for key in state.renewals)
    assert any(":lock:" in key for key in state.releases)
    assert notifier.sent == []
    assert notifier.late_alerts == []
    assert not any(":late-alert:sent:" in key for key, _payload in state.upserts)


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
    assert result.storage_key == "2026/05/2026-05-28.ai-brief-skip.json"
    assert len(pipeline.calls) == 1
    assert storage.uploads == []
    assert len(storage.skip_uploads) == 1
    assert any(":skip-artifact:US:" in key for key, _payload in state.upserts)
    assert any(":skip-artifact:claim:US:" in key for key in state.claims)
    assert any(":lock:" in key for key in state.releases)
    assert "pre_upload_guard_failed" in notifier.sent


def test_locked_upload_precheck_helper_persists_skip_artifact_before_upload() -> None:
    runner, state, _pipeline, storage, notifier = _runner(
        guard=_guard(session_state="INTRADAY")
    )
    lock_key = build_scheduler_state_key(
        kind="lock", market="US", session_date="2026-05-28"
    )

    result = runner._handle_locked_pipeline_upload_precheck(
        market="US",
        session_date="2026-05-28",
        run_url="https://github.com/owner/repo/actions/runs/4",
        lock_key=lock_key,
        owner_token="attempt-upload-precheck-helper-owner",
        schedule_role="local-primary",
        runner_role="local-primary",
        attempt_id="attempt-upload-precheck-helper",
    )

    assert result is not None
    assert result.status == "guard_failed_before_upload"
    assert result.storage_key == "2026/05/2026-05-28.ai-brief-skip.json"
    assert storage.uploads == []
    assert len(storage.skip_uploads) == 1
    assert any(":lock:" in key for key in state.renewals)
    assert lock_key in state.releases
    assert "pre_upload_guard_failed" in notifier.sent
    assert notifier.late_alerts[0][1]["scheduleRole"] == "local-primary"
    assert notifier.late_alerts[0][1]["runnerRole"] == "local-primary"
    assert notifier.late_alerts[0][1]["attemptId"] == "attempt-upload-precheck-helper"


def test_locked_upload_precheck_does_not_record_skip_or_alert_after_lock_loss() -> None:
    state = _FakeStateStore(ownership_results=[True, False])
    runner, state, _pipeline, storage, notifier = _runner(
        state=state,
        guard=_guard(session_state="INTRADAY"),
    )
    lock_key = build_scheduler_state_key(
        kind="lock", market="US", session_date="2026-05-28"
    )

    result = runner._handle_locked_pipeline_upload_precheck(
        market="US",
        session_date="2026-05-28",
        run_url="https://github.com/owner/repo/actions/runs/5",
        lock_key=lock_key,
        owner_token="attempt-upload-precheck-lock-lost-owner",
        schedule_role="local-primary",
        runner_role="local-primary",
        attempt_id="attempt-upload-precheck-lock-lost",
    )

    assert result is not None
    assert result.status == "lock_lost_before_upload"
    assert result.storage_key is None
    assert storage.uploads == []
    assert storage.skip_uploads == []
    assert lock_key in state.releases
    assert not any(":skip-artifact:US:2026-05-28" in key for key, _ in state.upserts)
    assert "pre_upload_guard_failed" not in notifier.sent
    assert notifier.late_alerts == []


def test_locked_upload_precheck_does_not_record_skip_marker_after_post_upload_lock_loss() -> (
    None
):
    state = _FakeStateStore(ownership_results=[True, True, False])
    runner, state, _pipeline, storage, notifier = _runner(
        state=state,
        guard=_guard(session_state="INTRADAY"),
    )
    lock_key = build_scheduler_state_key(
        kind="lock", market="US", session_date="2026-05-28"
    )

    result = runner._handle_locked_pipeline_upload_precheck(
        market="US",
        session_date="2026-05-28",
        run_url="https://github.com/owner/repo/actions/runs/7",
        lock_key=lock_key,
        owner_token="attempt-upload-precheck-post-upload-lock-lost-owner",
        schedule_role="local-primary",
        runner_role="local-primary",
        attempt_id="attempt-upload-precheck-post-upload-lock-lost",
    )

    assert result is not None
    assert result.status == "lock_lost_before_upload"
    assert result.storage_key == "2026/05/2026-05-28.ai-brief-skip.json"
    assert storage.uploads == []
    assert len(storage.skip_uploads) == 1
    assert not any(":skip-artifact:US:2026-05-28" in key for key, _ in state.upserts)
    assert lock_key in state.releases
    assert "pre_upload_guard_failed" not in notifier.sent
    assert notifier.late_alerts == []


def test_locked_upload_precheck_does_not_write_skip_marker_after_post_upload_lock_loss() -> (
    None
):
    state = _FakeStateStore(ownership_results=[True, True, False])
    runner, state, _pipeline, storage, notifier = _runner(
        state=state,
        guard=_guard(session_state="INTRADAY"),
    )
    lock_key = build_scheduler_state_key(
        kind="lock", market="US", session_date="2026-05-28"
    )

    result = runner._handle_locked_pipeline_upload_precheck(
        market="US",
        session_date="2026-05-28",
        run_url="https://github.com/owner/repo/actions/runs/7",
        lock_key=lock_key,
        owner_token="attempt-upload-precheck-marker-fail-owner",
        schedule_role="local-primary",
        runner_role="local-primary",
        attempt_id="attempt-upload-precheck-marker-fail",
    )

    assert result is not None
    assert result.status == "lock_lost_before_upload"
    assert result.storage_key == "2026/05/2026-05-28.ai-brief-skip.json"
    assert len(storage.skip_uploads) == 1
    assert not any(":skip-artifact:US:2026-05-28" in key for key, _ in state.upserts)
    assert lock_key in state.releases
    assert notifier.sent == []
    assert notifier.late_alerts == []


def test_locked_upload_precheck_does_not_alert_after_lock_loss_reusing_skip() -> None:
    skip_key = build_scheduler_state_key(
        kind="skip-artifact", market="US", session_date="2026-05-28"
    )
    lock_key = build_scheduler_state_key(
        kind="lock", market="US", session_date="2026-05-28"
    )
    state = _FakeStateStore(
        entries={
            skip_key: RuntimeStateEntry(
                state_key=skip_key,
                state_payload={"storageKey": "2026/05/2026-05-28.ai-brief-skip.json"},
                expires_at="2026-05-30T00:00:00Z",
            )
        },
        ownership_results=[True, False],
    )
    runner, state, _pipeline, storage, notifier = _runner(
        state=state,
        guard=_guard(session_state="INTRADAY"),
    )

    result = runner._handle_locked_pipeline_upload_precheck(
        market="US",
        session_date="2026-05-28",
        run_url="https://github.com/owner/repo/actions/runs/6",
        lock_key=lock_key,
        owner_token="attempt-upload-precheck-reuse-lock-lost-owner",
        schedule_role="local-primary",
        runner_role="local-primary",
        attempt_id="attempt-upload-precheck-reuse-lock-lost",
    )

    assert result is not None
    assert result.status == "lock_lost_before_upload"
    assert result.storage_key == "2026/05/2026-05-28.ai-brief-skip.json"
    assert storage.uploads == []
    assert storage.skip_uploads == []
    assert lock_key in state.releases
    assert "pre_upload_guard_failed" not in notifier.sent
    assert notifier.late_alerts == []


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


def test_notification_repair_defers_success_marker_after_main_lock_loss() -> None:
    sent_key = build_scheduler_state_key(
        kind="notification:sent", market="US", session_date="2026-05-28"
    )
    artifact_entry = RuntimeStateEntry(
        state_key=build_scheduler_state_key(
            kind="artifact", market="US", session_date="2026-05-28"
        ),
        state_payload={"storageKey": "2026/05/2026-05-28.ai-brief.json"},
        expires_at="2026-05-30T00:00:00Z",
    )
    state = _FakeStateStore(
        entries={
            sent_key: RuntimeStateEntry(
                state_key=sent_key,
                state_payload={
                    "storageKey": "2026/05/2026-05-28.ai-brief.json",
                },
                expires_at="2026-05-30T00:00:00Z",
            )
        },
        ownership_results=[True, False],
    )
    runner, state, _pipeline, _storage, _notifier = _runner(state=state)

    result = runner._reconcile_notification(
        market="US",
        session_date="2026-05-28",
        schedule_role="local-primary",
        runner_role="local-primary",
        attempt_id="attempt-notification-repair-lock-lost",
        artifact_entry=artifact_entry,
        require_main_lock=True,
        main_lock_key=build_scheduler_state_key(
            kind="lock", market="US", session_date="2026-05-28"
        ),
        main_owner_token="attempt-notification-repair-lock-lost-owner",
    )

    assert result.status == "artifact_uploaded_notification_deferred"
    assert not any(":success:US:2026-05-28" in key for key, _payload in state.upserts)


def test_notification_repair_defers_send_after_main_lock_loss() -> None:
    artifact_entry = RuntimeStateEntry(
        state_key=build_scheduler_state_key(
            kind="artifact", market="US", session_date="2026-05-28"
        ),
        state_payload={"storageKey": "2026/05/2026-05-28.ai-brief.json"},
        expires_at="2026-05-30T00:00:00Z",
    )
    state = _FakeStateStore(ownership_results=[True, True, False])
    runner, state, _pipeline, storage, notifier = _runner(state=state)

    result = runner._reconcile_notification(
        market="US",
        session_date="2026-05-28",
        schedule_role="local-primary",
        runner_role="local-primary",
        attempt_id="attempt-notification-send-lock-lost",
        artifact_entry=artifact_entry,
        require_main_lock=True,
        main_lock_key=build_scheduler_state_key(
            kind="lock", market="US", session_date="2026-05-28"
        ),
        main_owner_token="attempt-notification-send-lock-lost-owner",
    )

    assert result.status == "artifact_uploaded_notification_deferred"
    assert result.storage_key == "2026/05/2026-05-28.ai-brief.json"
    assert storage.downloads == ["2026/05/2026-05-28.ai-brief.json"]
    assert notifier.sent == []
    assert not any(":notification:sent:" in key for key, _payload in state.upserts)
    assert not any(":success:US:2026-05-28" in key for key, _payload in state.upserts)


def test_notification_guard_failure_helper_preserves_alert_context() -> None:
    runner, _state, _pipeline, _storage, notifier = _runner()
    guard = _guard(session_state="INTRADAY")

    assert hasattr(runner, "_handle_notification_guard_failure")

    result = runner._handle_notification_guard_failure(
        market="US",
        session_date="2026-05-28",
        schedule_role="local-primary",
        runner_role="local-primary",
        attempt_id="attempt-notification-guard-helper",
        guard=guard,
        storage_key="2026/05/2026-05-28.ai-brief.json",
    )

    assert result.status == "guard_failed_before_notification"
    assert result.session_date == "2026-05-28"
    assert result.storage_key == "2026/05/2026-05-28.ai-brief.json"
    assert notifier.sent == ["pre_notification_guard_failed"]
    assert notifier.late_alerts == [
        (
            "pre_notification_guard_failed",
            {
                "market": "US",
                "sessionDate": "2026-05-28",
                "sessionState": "INTRADAY",
                "tradingSession": True,
                "localTime": "2026-05-28T08:10:00-04:00",
                "scheduleRole": "local-primary",
                "runnerRole": "local-primary",
                "attemptId": "attempt-notification-guard-helper",
                "storageKey": "2026/05/2026-05-28.ai-brief.json",
            },
        )
    ]


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


def test_runner_does_not_record_artifact_marker_when_lock_is_lost_after_upload() -> (
    None
):
    state = _FakeStateStore(ownership_results=[True, False])
    runner, state, _pipeline, storage, notifier = _runner(state=state)

    result = runner.run(
        ScheduledAiBriefRequest(
            market="US",
            schedule_role="local-primary",
            runner_role="local-primary",
            scheduled_tick="0810",
            attempt_id="attempt-artifact-lock-lost-after-upload",
        )
    )

    assert result.status == "lock_lost_before_upload"
    assert storage.uploads == ["reports/2026-05-28.ai-brief.json"]
    assert any(":lock:" in key for key in state.releases)
    assert not any(":artifact:US:2026-05-28" in key for key, _payload in state.upserts)
    assert notifier.sent == []
    assert notifier.late_alerts == []


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


def test_runner_uses_market_specific_source_provider_env(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("AI_BRIEF_SOURCE_PROVIDER_US", "finnhub")
    monkeypatch.setenv("AI_BRIEF_SOURCE_PROVIDER", "naver-news")
    runner, _state, pipeline, _storage, _notifier = _runner()

    result = runner.run(
        ScheduledAiBriefRequest(
            market="US",
            schedule_role="local-primary",
            runner_role="local-primary",
            scheduled_tick="0810",
            attempt_id="attempt-source-provider-env",
        )
    )

    assert result.status == "completed"
    assert pipeline.calls[0][1]["source_provider"] == "finnhub"
    assert pipeline.calls[0][1]["source_api_url"] is None


def test_runner_uses_global_source_provider_env_when_market_env_is_absent(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("AI_BRIEF_SOURCE_PROVIDER", "polygon-news")
    runner, _state, pipeline, _storage, _notifier = _runner()

    result = runner.run(
        ScheduledAiBriefRequest(
            market="US",
            schedule_role="local-primary",
            runner_role="local-primary",
            scheduled_tick="0810",
            attempt_id="attempt-source-provider-global",
        )
    )

    assert result.status == "completed"
    assert pipeline.calls[0][1]["source_provider"] == "polygon-news"
    assert pipeline.calls[0][1]["source_api_url"] is None


def test_runner_source_provider_request_overrides_env(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("AI_BRIEF_SOURCE_PROVIDER_US", "finnhub")
    runner, _state, pipeline, _storage, _notifier = _runner()

    result = runner.run(
        ScheduledAiBriefRequest(
            market="US",
            schedule_role="local-primary",
            runner_role="local-primary",
            scheduled_tick="0810",
            attempt_id="attempt-source-provider-override",
            source_provider="benzinga-news",
        )
    )

    assert result.status == "completed"
    assert pipeline.calls[0][1]["source_provider"] == "benzinga-news"
    assert pipeline.calls[0][1]["source_api_url"] is None


def test_runner_source_provider_chain_env_wins_over_single_provider_env(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv(
        "AI_BRIEF_SOURCE_PROVIDER_CHAIN_US",
        "finnhub,benzinga-news,polygon-news",
    )
    monkeypatch.setenv("AI_BRIEF_SOURCE_PROVIDER_CHAIN", "naver-news")
    monkeypatch.setenv("AI_BRIEF_SOURCE_PROVIDER_US", "marketaux-news")
    runner, _state, pipeline, _storage, _notifier = _runner()

    result = runner.run(
        ScheduledAiBriefRequest(
            market="US",
            schedule_role="local-primary",
            runner_role="local-primary",
            scheduled_tick="0810",
            attempt_id="attempt-source-provider-chain-env",
        )
    )

    assert result.status == "completed"
    assert pipeline.calls[0][1]["source_provider"] is None
    assert pipeline.calls[0][1]["source_provider_chain"] == (
        "finnhub",
        "benzinga-news",
        "polygon-news",
    )
    assert pipeline.calls[0][1]["source_api_url"] is None


def test_runner_source_provider_request_overrides_chain_env(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("AI_BRIEF_SOURCE_PROVIDER_CHAIN_US", "finnhub,benzinga-news")
    runner, _state, pipeline, _storage, _notifier = _runner()

    result = runner.run(
        ScheduledAiBriefRequest(
            market="US",
            schedule_role="local-primary",
            runner_role="local-primary",
            scheduled_tick="0810",
            attempt_id="attempt-source-provider-chain-override",
            source_provider="polygon-news",
        )
    )

    assert result.status == "completed"
    assert pipeline.calls[0][1]["source_provider"] == "polygon-news"
    assert pipeline.calls[0][1]["source_provider_chain"] is None
    assert pipeline.calls[0][1]["source_api_url"] is None


def test_runner_source_provider_chain_http_json_uses_source_api_url_env(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("AI_BRIEF_SOURCE_PROVIDER_CHAIN_US", "http-json,finnhub")
    monkeypatch.setenv("AI_BRIEF_SOURCE_API_URL_US", "https://source.example/us")
    runner, _state, pipeline, _storage, _notifier = _runner()

    result = runner.run(
        ScheduledAiBriefRequest(
            market="US",
            schedule_role="local-primary",
            runner_role="local-primary",
            scheduled_tick="0810",
            attempt_id="attempt-source-provider-chain-http-json",
        )
    )

    assert result.status == "completed"
    assert pipeline.calls[0][1]["source_provider"] is None
    assert pipeline.calls[0][1]["source_provider_chain"] == ("http-json", "finnhub")
    assert pipeline.calls[0][1]["source_api_url"] == "https://source.example/us"


def test_runner_fails_fast_when_chain_http_json_source_api_url_is_missing(
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    monkeypatch.setenv("AI_BRIEF_SOURCE_PROVIDER_CHAIN_US", "http-json,finnhub")
    runner, _state, pipeline, storage, notifier = _runner()
    caplog.set_level("ERROR", logger="sab.scheduler.runner")

    result = runner.run(
        ScheduledAiBriefRequest(
            market="US",
            schedule_role="local-primary",
            runner_role="local-primary",
            scheduled_tick="0810",
            attempt_id="attempt-source-provider-chain-missing-url",
        )
    )

    assert result.status == "source_config_invalid"
    assert pipeline.calls == []
    assert storage.uploads == []
    assert notifier.sent == []
    records = _log_records_for_event(
        caplog,
        "scheduled_ai_brief_source_config_invalid",
    )
    assert len(records) == 1
    record = records[0]
    assert record.__dict__["error_code"] == "missing_source_api_url"
    assert record.__dict__["source_provider_chain"] == "http-json,finnhub"
    assert record.__dict__["source_provider_chain_origin"] == "env_market"


@pytest.mark.parametrize(
    "chain",
    [
        "finnhub,finnhub",
        "none,finnhub",
        "bogus-news",
    ],
)
def test_runner_fails_fast_for_invalid_source_provider_chain_env(
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
    chain: str,
) -> None:
    monkeypatch.setenv("AI_BRIEF_SOURCE_PROVIDER_CHAIN_US", chain)
    runner, _state, pipeline, storage, notifier = _runner()
    caplog.set_level("ERROR", logger="sab.scheduler.runner")

    result = runner.run(
        ScheduledAiBriefRequest(
            market="US",
            schedule_role="local-primary",
            runner_role="local-primary",
            scheduled_tick="0810",
            attempt_id="attempt-source-provider-chain-invalid",
        )
    )

    assert result.status == "source_config_invalid"
    assert pipeline.calls == []
    assert storage.uploads == []
    assert notifier.sent == []
    records = _log_records_for_event(
        caplog,
        "scheduled_ai_brief_source_config_invalid",
    )
    assert len(records) == 1
    assert records[0].__dict__["error_code"] == "invalid_source_provider_chain"


def test_runner_source_api_url_env_implies_http_json_provider(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("AI_BRIEF_SOURCE_API_URL_US", "https://source.example/us")
    monkeypatch.setenv("AI_BRIEF_SOURCE_API_URL", "https://source.example/global")
    runner, _state, pipeline, _storage, _notifier = _runner()

    result = runner.run(
        ScheduledAiBriefRequest(
            market="US",
            schedule_role="local-primary",
            runner_role="local-primary",
            scheduled_tick="0810",
            attempt_id="attempt-source-api-url",
        )
    )

    assert result.status == "completed"
    assert pipeline.calls[0][1]["source_provider"] == "http-json"
    assert pipeline.calls[0][1]["source_api_url"] == "https://source.example/us"


def test_runner_http_json_provider_env_uses_source_api_url_env(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("AI_BRIEF_SOURCE_PROVIDER_US", "http-json")
    monkeypatch.setenv("AI_BRIEF_SOURCE_API_URL_US", "https://source.example/us")
    runner, _state, pipeline, _storage, _notifier = _runner()

    result = runner.run(
        ScheduledAiBriefRequest(
            market="US",
            schedule_role="local-primary",
            runner_role="local-primary",
            scheduled_tick="0810",
            attempt_id="attempt-http-json-source-api-url",
        )
    )

    assert result.status == "completed"
    assert pipeline.calls[0][1]["source_provider"] == "http-json"
    assert pipeline.calls[0][1]["source_api_url"] == "https://source.example/us"


def test_runner_logs_resolved_source_context_without_source_api_url(
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    monkeypatch.setenv("AI_BRIEF_SOURCE_PROVIDER_US", "HTTP-JSON")
    monkeypatch.setenv(
        "AI_BRIEF_SOURCE_API_URL_US",
        "https://source.example/us?token=secret-token",
    )
    runner, _state, pipeline, _storage, _notifier = _runner()
    caplog.set_level("INFO", logger="sab.scheduler.runner")

    result = runner.run(
        ScheduledAiBriefRequest(
            market="US",
            schedule_role="local-primary",
            runner_role="local-primary",
            scheduled_tick="0810",
            attempt_id="attempt-source-context-log",
        )
    )

    assert result.status == "completed"
    assert pipeline.calls[0][1]["source_provider"] == "http-json"
    records = _log_records_for_event(
        caplog,
        "scheduled_ai_brief_source_context_resolved",
    )
    assert len(records) == 1
    record = records[0]
    assert record.__dict__["market"] == "US"
    assert record.__dict__["session_date"] == "2026-05-28"
    assert record.__dict__["schedule_role"] == "local-primary"
    assert record.__dict__["runner_role"] == "local-primary"
    assert record.__dict__["attempt_id"] == "attempt-source-context-log"
    assert record.__dict__["source_provider"] == "http-json"
    assert record.__dict__["source_provider_origin"] == "env_market"
    assert record.__dict__["source_api_url_configured"] is True
    assert record.__dict__["source_api_url_origin"] == "env_market"
    assert "secret-token" not in caplog.text
    assert "https://source.example/us" not in caplog.text


def test_runner_fails_fast_for_unsupported_source_provider_env(
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    monkeypatch.setenv("AI_BRIEF_SOURCE_PROVIDER_US", "https://token@example.test")
    runner, _state, pipeline, storage, notifier = _runner()
    caplog.set_level("ERROR", logger="sab.scheduler.runner")

    result = runner.run(
        ScheduledAiBriefRequest(
            market="US",
            schedule_role="local-primary",
            runner_role="local-primary",
            scheduled_tick="0810",
            attempt_id="attempt-invalid-source-provider",
        )
    )

    assert result.status == "source_config_invalid"
    assert pipeline.calls == []
    assert storage.uploads == []
    assert notifier.sent == []
    assert "source_config_invalid" in scheduler_runner._FAILED_STATUSES
    records = _log_records_for_event(
        caplog,
        "scheduled_ai_brief_source_config_invalid",
    )
    assert len(records) == 1
    record = records[0]
    assert record.__dict__["error_code"] == "unsupported_source_provider"
    assert record.__dict__["source_provider"] == "unsupported"
    assert record.__dict__["source_provider_origin"] == "env_market"
    assert "https://token@example.test" not in caplog.text
    assert "token" not in caplog.text


def test_runner_fails_fast_when_http_json_source_api_url_is_missing(
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    monkeypatch.setenv("AI_BRIEF_SOURCE_PROVIDER_US", "http-json")
    runner, _state, pipeline, storage, notifier = _runner()
    caplog.set_level("ERROR", logger="sab.scheduler.runner")

    result = runner.run(
        ScheduledAiBriefRequest(
            market="US",
            schedule_role="local-primary",
            runner_role="local-primary",
            scheduled_tick="0810",
            attempt_id="attempt-http-json-missing-url",
        )
    )

    assert result.status == "source_config_invalid"
    assert pipeline.calls == []
    assert storage.uploads == []
    assert notifier.sent == []
    records = _log_records_for_event(
        caplog,
        "scheduled_ai_brief_source_config_invalid",
    )
    assert len(records) == 1
    record = records[0]
    assert record.__dict__["error_code"] == "missing_source_api_url"
    assert record.__dict__["source_provider"] == "http-json"
    assert record.__dict__["source_provider_origin"] == "env_market"
    assert record.__dict__["source_api_url_configured"] is False


def test_runner_fails_fast_when_source_api_url_env_is_multiline(
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    monkeypatch.setenv("AI_BRIEF_SOURCE_API_URL_US", "https://source.example/us\nnext")
    runner, _state, pipeline, storage, notifier = _runner()
    caplog.set_level("ERROR", logger="sab.scheduler.runner")

    result = runner.run(
        ScheduledAiBriefRequest(
            market="US",
            schedule_role="local-primary",
            runner_role="local-primary",
            scheduled_tick="0810",
            attempt_id="attempt-source-url-multiline",
        )
    )

    assert result.status == "source_config_invalid"
    assert pipeline.calls == []
    assert storage.uploads == []
    assert notifier.sent == []
    records = _log_records_for_event(
        caplog,
        "scheduled_ai_brief_source_config_invalid",
    )
    assert len(records) == 1
    record = records[0]
    assert record.__dict__["error_code"] == "invalid_source_api_url"
    assert record.__dict__["source_provider"] == "http-json"
    assert record.__dict__["source_provider_origin"] == "api_url_market"
    assert record.__dict__["source_api_url_origin"] == "env_market"
    assert "https://source.example/us" not in caplog.text


@pytest.mark.parametrize(
    "source_api_url",
    [
        "http://source.example/us",
        "https://token@source.example/us",
        "https://localhost/us",
        "https://127.0.0.1/us",
        "https://source.example:0/us",
    ],
)
def test_runner_fails_fast_when_source_api_url_env_is_unsafe(
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
    source_api_url: str,
) -> None:
    monkeypatch.setenv("AI_BRIEF_SOURCE_API_URL_US", source_api_url)
    runner, _state, pipeline, storage, notifier = _runner()
    caplog.set_level("ERROR", logger="sab.scheduler.runner")

    result = runner.run(
        ScheduledAiBriefRequest(
            market="US",
            schedule_role="local-primary",
            runner_role="local-primary",
            scheduled_tick="0810",
            attempt_id="attempt-source-url-unsafe",
        )
    )

    assert result.status == "source_config_invalid"
    assert pipeline.calls == []
    assert storage.uploads == []
    assert notifier.sent == []
    records = _log_records_for_event(
        caplog,
        "scheduled_ai_brief_source_config_invalid",
    )
    assert len(records) == 1
    record = records[0]
    assert record.__dict__["error_code"] == "invalid_source_api_url"
    assert record.__dict__["source_provider"] == "http-json"
    assert record.__dict__["source_api_url_configured"] is True
    assert source_api_url not in caplog.text


def test_artifact_marker_helper_records_upload_payload() -> None:
    runner, state, _pipeline, _storage, _notifier = _runner()
    artifact_key = build_scheduler_state_key(
        kind="artifact", market="US", session_date="2026-05-28"
    )

    runner._record_ai_brief_artifact_marker(
        artifact_key=artifact_key,
        storage_key="2026/05/2026-05-28.ai-brief.json",
        market="US",
        session_date="2026-05-28",
        runner_role="github-fallback",
        attempt_id="attempt-artifact-helper",
        run_url="https://github.com/owner/repo/actions/runs/3",
        now=dt.datetime(2026, 5, 28, 12, 10, tzinfo=dt.UTC),
    )

    assert state.upserts == [
        (
            artifact_key,
            {
                "storageKey": "2026/05/2026-05-28.ai-brief.json",
                "market": "US",
                "sessionDate": "2026-05-28",
                "reportDate": "2026-05-28",
                "runner": "github",
                "attemptId": "attempt-artifact-helper",
                "runUrl": "https://github.com/owner/repo/actions/runs/3",
            },
        )
    ]


def test_uploaded_artifact_marker_helper_preserves_failure_context() -> None:
    runner, state, _pipeline, _storage, notifier = _runner(
        state=_FakeStateStore(fail_artifact_upsert=True)
    )
    lock_key = build_scheduler_state_key(
        kind="lock", market="US", session_date="2026-05-28"
    )
    artifact_key = build_scheduler_state_key(
        kind="artifact", market="US", session_date="2026-05-28"
    )

    result = runner._record_uploaded_ai_brief_artifact(
        artifact_key=artifact_key,
        storage_key="2026/05/2026-05-28.ai-brief.json",
        market="US",
        session_date="2026-05-28",
        schedule_role="local-primary",
        runner_role="local-primary",
        attempt_id="attempt-artifact-helper-fail",
        run_url="https://github.com/owner/repo/actions/runs/5",
        lock_key=lock_key,
        owner_token="attempt-artifact-helper-fail-owner",
        now=dt.datetime(2026, 5, 28, 12, 10, tzinfo=dt.UTC),
    )

    assert result is not None
    assert result.status == "artifact_marker_failed"
    assert result.storage_key == "2026/05/2026-05-28.ai-brief.json"
    assert lock_key in state.releases
    assert notifier.sent == ["artifact_marker_failed"]
    assert notifier.late_alerts == [
        (
            "artifact_marker_failed",
            {
                "market": "US",
                "sessionDate": "2026-05-28",
                "attemptId": "attempt-artifact-helper-fail",
                "scheduleRole": "local-primary",
                "runnerRole": "local-primary",
                "storageKey": "2026/05/2026-05-28.ai-brief.json",
            },
        )
    ]


def test_locked_pipeline_helper_completes_and_releases_main_lock() -> None:
    runner, state, pipeline, storage, notifier = _runner()
    lock_key = build_scheduler_state_key(
        kind="lock", market="US", session_date="2026-05-28"
    )
    artifact_key = build_scheduler_state_key(
        kind="artifact", market="US", session_date="2026-05-28"
    )

    result = runner._run_locked_pipeline(
        market="US",
        session_date="2026-05-28",
        schedule_role="local-primary",
        runner_role="local-primary",
        attempt_id="attempt-helper-lock",
        run_url="https://github.com/owner/repo/actions/runs/3",
        source_provider="finnhub",
        model_provider="openai",
        lock_key=lock_key,
        owner_token="attempt-helper-lock-owner",
        artifact_key=artifact_key,
        now=dt.datetime(2026, 5, 28, 12, 10, tzinfo=dt.UTC),
        model_deadline_at=None,
    )

    assert result.status == "completed"
    assert pipeline.calls[0][1]["source_provider"] == "finnhub"
    assert pipeline.calls[0][1]["model_provider"] == "openai"
    assert storage.uploads == ["reports/2026-05-28.ai-brief.json"]
    assert notifier.sent == ["2026/05/2026-05-28.ai-brief.json"]
    assert any(key == artifact_key for key, _payload in state.upserts)
    assert lock_key in state.releases


def test_main_lock_claim_helper_claims_session_lock_with_attempt_context() -> None:
    runner, state, _pipeline, _storage, _notifier = _runner()
    lock_key = build_scheduler_state_key(
        kind="lock", market="US", session_date="2026-05-28"
    )

    lease = runner._claim_main_lock(
        market="US",
        session_date="2026-05-28",
        runner_role="local-primary",
        attempt_id="attempt-lock-helper",
        now=dt.datetime(2026, 5, 28, 12, 10, tzinfo=dt.UTC),
    )

    assert isinstance(lease, scheduler_runner._MainLockLease)
    assert lease.lock_key == lock_key
    assert lease.owner_token.startswith("attempt-lock-helper-")
    assert state.claims == [lock_key]
    assert state.claim_payloads == [
        (
            lock_key,
            {
                "attemptId": "attempt-lock-helper",
                "market": "US",
                "sessionDate": "2026-05-28",
                "runnerRole": "local-primary",
            },
        )
    ]


def test_main_lock_claim_helper_reports_lock_held_skip() -> None:
    runner, state, _pipeline, _storage, _notifier = _runner(
        state=_FakeStateStore(claim_results=[False])
    )
    lock_key = build_scheduler_state_key(
        kind="lock", market="US", session_date="2026-05-28"
    )

    result = runner._claim_main_lock(
        market="US",
        session_date="2026-05-28",
        runner_role="local-primary",
        attempt_id="attempt-lock-held",
        now=dt.datetime(2026, 5, 28, 12, 10, tzinfo=dt.UTC),
    )

    assert isinstance(result, scheduler_runner.ScheduledAiBriefResult)
    assert result.status == "lock_held_skip"
    assert result.session_date == "2026-05-28"
    assert result.storage_key is None
    assert state.claims == [lock_key]


def test_notification_claim_helper_claims_schedule_claim_with_attempt_context() -> None:
    runner, state, _pipeline, _storage, _notifier = _runner()
    claim_key = build_scheduler_state_key(
        kind="notification:claim", market="US", session_date="2026-05-28"
    )

    lease = runner._claim_schedule_notification(
        market="US",
        session_date="2026-05-28",
        schedule_role="local-primary",
        runner_role="local-primary",
        attempt_id="attempt-notification-helper",
    )

    assert isinstance(lease, scheduler_runner._NotificationClaimLease)
    assert lease.claim_key == claim_key
    assert lease.owner_token.startswith("attempt-notification-helper-notification-")
    assert state.claims == [claim_key]
    assert state.claim_payloads == [
        (
            claim_key,
            {
                "attemptId": "attempt-notification-helper",
                "market": "US",
                "sessionDate": "2026-05-28",
                "runnerRole": "local-primary",
                "scheduleRole": "local-primary",
                "channel": "telegram",
                "notificationType": "schedule",
            },
        )
    ]


def test_notification_claim_helper_reports_claim_held() -> None:
    runner, state, _pipeline, _storage, _notifier = _runner(
        state=_FakeStateStore(claim_results=[False])
    )
    claim_key = build_scheduler_state_key(
        kind="notification:claim", market="US", session_date="2026-05-28"
    )

    result = runner._claim_schedule_notification(
        market="US",
        session_date="2026-05-28",
        schedule_role="local-primary",
        runner_role="local-primary",
        attempt_id="attempt-notification-held",
    )

    assert isinstance(result, scheduler_runner.ScheduledAiBriefResult)
    assert result.status == "notification_claim_held"
    assert result.session_date == "2026-05-28"
    assert result.storage_key is None
    assert state.claims == [claim_key]


def test_runner_releases_main_lock_when_pipeline_fails(
    caplog: pytest.LogCaptureFixture,
) -> None:
    runner, state, _pipeline, _storage, notifier = _runner(
        pipeline=_FakePipeline(fail=True)
    )

    caplog.set_level("ERROR", logger="sab.scheduler.runner")

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
    assert "scheduled AI brief pipeline failed" in caplog.text
    assert "schedule_role=local-primary" in caplog.text
    assert "runner_role=local-primary" in caplog.text
    assert "attempt_id=attempt-8" in caplog.text
    assert "pipeline failed" in caplog.text
    assert notifier.late_alerts == [
        (
            "pipeline_failed",
            {
                "market": "US",
                "sessionDate": "2026-05-28",
                "attemptId": "attempt-8",
                "scheduleRole": "local-primary",
                "runnerRole": "local-primary",
            },
        )
    ]
    late_alert_sent_index = next(
        index
        for index, (_event, key) in enumerate(state.events)
        if ":late-alert:sent:US:2026-05-28:pipeline_failed" in key
    )
    main_lock_key = build_scheduler_state_key(
        kind="lock", market="US", session_date="2026-05-28"
    )
    main_lock_release_index = next(
        index
        for index, event in enumerate(state.events)
        if event == ("release", main_lock_key)
    )
    assert late_alert_sent_index < main_lock_release_index


def test_pipeline_failure_late_alert_includes_scheduled_entry_report_hint() -> None:
    class _TypedEntryFailurePipeline(_FakePipeline):
        def run(
            self,
            *,
            market: str,
            session_date: str,
            report_date: str,
            source_provider: str | None,
            model_provider: str,
            dry_run: bool,
            model_deadline_remaining_seconds: float | None = None,
            model_deadline_at: dt.datetime | None = None,
            source_api_url: str | None = None,
            source_provider_chain: tuple[str, ...] | None = None,
        ) -> ScheduledPipelineResult:
            self._record_call(
                market=market,
                session_date=session_date,
                report_date=report_date,
                source_provider=source_provider,
                source_api_url=source_api_url,
                source_provider_chain=source_provider_chain,
                model_provider=model_provider,
                dry_run=dry_run,
            )
            raise scheduler_runner._ScheduledEntryStepError(
                "reports/current.entry.json"
            )

    runner, state, _pipeline, storage, notifier = _runner(
        pipeline=_TypedEntryFailurePipeline()
    )

    result = runner.run(
        ScheduledAiBriefRequest(
            market="US",
            schedule_role="local-primary",
            runner_role="local-primary",
            scheduled_tick="0810",
            attempt_id="attempt-entry-failed",
        )
    )

    assert result.status == "pipeline_failed"
    assert any(":lock:" in key for key in state.releases)
    assert storage.entry_uploads == ["reports/current.entry.json"]
    assert notifier.sent == ["scheduled_entry_failed"]
    expected_context = {
        "market": "US",
        "sessionDate": "2026-05-28",
        "attemptId": "attempt-entry-failed",
        "scheduleRole": "local-primary",
        "runnerRole": "local-primary",
        "failureDetail": "scheduled entry failed",
        "entryReportPath": "reports/current.entry.json",
        "entryReportStorageKey": "2026/05/2026-05-28.entry.json",
    }
    assert notifier.late_alerts == [("scheduled_entry_failed", expected_context)]
    sent_payloads = [
        payload
        for key, payload in state.upserts
        if ":late-alert:sent:US:2026-05-28:scheduled_entry_failed" in key
    ]
    assert sent_payloads == [{**expected_context, "reason": "scheduled_entry_failed"}]


def test_scheduled_entry_failure_preserves_storage_key_when_marker_fails() -> None:
    state = _FakeStateStore(fail_entry_failure_artifact_upsert=True)
    runner, state, _pipeline, storage, notifier = _runner(
        state=state,
        pipeline=_TypedEntryFailurePipeline(),
    )

    result = runner.run(
        ScheduledAiBriefRequest(
            market="US",
            schedule_role="local-primary",
            runner_role="local-primary",
            scheduled_tick="0810",
            attempt_id="attempt-entry-marker-failed",
        )
    )

    assert result.status == "pipeline_failed"
    assert storage.entry_uploads == ["reports/current.entry.json"]
    expected_context = {
        "market": "US",
        "sessionDate": "2026-05-28",
        "attemptId": "attempt-entry-marker-failed",
        "scheduleRole": "local-primary",
        "runnerRole": "local-primary",
        "failureDetail": "scheduled entry failed",
        "entryReportPath": "reports/current.entry.json",
        "entryReportStorageKey": "2026/05/2026-05-28.entry.json",
    }
    assert notifier.late_alerts == [("scheduled_entry_failed", expected_context)]
    sent_payloads = [
        payload
        for key, payload in state.upserts
        if ":late-alert:sent:US:2026-05-28:scheduled_entry_failed" in key
    ]
    assert sent_payloads == [{**expected_context, "reason": "scheduled_entry_failed"}]


def test_scheduled_entry_failure_skips_upload_and_alert_when_main_lock_is_lost() -> (
    None
):
    state = _FakeStateStore(ownership_results=[False])
    runner, state, _pipeline, storage, notifier = _runner(
        state=state,
        pipeline=_TypedEntryFailurePipeline(),
    )

    result = runner.run(
        ScheduledAiBriefRequest(
            market="US",
            schedule_role="local-primary",
            runner_role="local-primary",
            scheduled_tick="0810",
            attempt_id="attempt-entry-lock-lost",
        )
    )

    assert result.status == "lock_lost_before_upload"
    assert "lock_lost_before_upload" in scheduler_runner._FAILED_STATUSES
    assert any(":lock:" in key for key in state.renewals)
    assert storage.entry_uploads == []
    assert notifier.sent == []
    assert notifier.late_alerts == []


def test_scheduled_entry_failure_skips_upload_and_alert_when_lock_is_lost_after_claim() -> (
    None
):
    state = _FakeStateStore(ownership_results=[True, False])
    runner, state, _pipeline, storage, notifier = _runner(
        state=state,
        pipeline=_TypedEntryFailurePipeline(),
    )

    result = runner.run(
        ScheduledAiBriefRequest(
            market="US",
            schedule_role="local-primary",
            runner_role="local-primary",
            scheduled_tick="0810",
            attempt_id="attempt-entry-lock-lost-after-upload",
        )
    )

    assert result.status == "lock_lost_before_upload"
    assert storage.entry_uploads == []
    assert not any(
        ":entry-failure-artifact:US:2026-05-28" in key
        for key, _payload in state.upserts
    )
    assert not any(
        ":late-alert:sent:US:2026-05-28:scheduled_entry_failed" in key
        for key, _payload in state.upserts
    )
    assert notifier.sent == []
    assert notifier.late_alerts == []


def test_scheduled_entry_failure_does_not_record_marker_after_post_upload_lock_loss() -> (
    None
):
    state = _FakeStateStore(ownership_results=[True, True, False])
    runner, state, _pipeline, storage, notifier = _runner(
        state=state,
        pipeline=_TypedEntryFailurePipeline(),
    )

    result = runner.run(
        ScheduledAiBriefRequest(
            market="US",
            schedule_role="local-primary",
            runner_role="local-primary",
            scheduled_tick="0810",
            attempt_id="attempt-entry-lock-lost-after-upload",
        )
    )

    assert result.status == "lock_lost_before_upload"
    assert result.storage_key == "2026/05/2026-05-28.entry.json"
    assert storage.entry_uploads == ["reports/current.entry.json"]
    assert not any(
        ":entry-failure-artifact:US:2026-05-28" in key
        for key, _payload in state.upserts
    )
    assert not any(
        ":late-alert:sent:US:2026-05-28:scheduled_entry_failed" in key
        for key, _payload in state.upserts
    )
    assert notifier.sent == []
    assert notifier.late_alerts == []


def test_scheduled_entry_failure_does_not_write_marker_after_post_upload_lock_loss() -> (
    None
):
    state = _FakeStateStore(ownership_results=[True, True, False])
    runner, state, _pipeline, storage, notifier = _runner(
        state=state,
        pipeline=_TypedEntryFailurePipeline(),
    )

    result = runner.run(
        ScheduledAiBriefRequest(
            market="US",
            schedule_role="local-primary",
            runner_role="local-primary",
            scheduled_tick="0810",
            attempt_id="attempt-entry-marker-fail-after-lock-lost",
        )
    )

    assert result.status == "lock_lost_before_upload"
    assert result.storage_key == "2026/05/2026-05-28.entry.json"
    assert storage.entry_uploads == ["reports/current.entry.json"]
    assert not any(
        ":entry-failure-artifact:US:2026-05-28" in key
        for key, _payload in state.upserts
    )
    assert not any(
        ":late-alert:sent:US:2026-05-28:scheduled_entry_failed" in key
        for key, _payload in state.upserts
    )
    assert notifier.sent == []
    assert notifier.late_alerts == []


def test_scheduled_entry_failure_claim_loser_does_not_suppress_artifact_alert() -> None:
    state = _FakeStateStore(claim_results=[True, False, True, True, True, True])
    notifier = _FakeNotifier()
    loser_storage = _FakeStorage()
    loser_runner, _state, _pipeline, _storage, _notifier = _runner(
        state=state,
        storage=loser_storage,
        notifier=notifier,
        pipeline=_TypedEntryFailurePipeline(),
    )

    loser_result = loser_runner.run(
        ScheduledAiBriefRequest(
            market="US",
            schedule_role="local-primary",
            runner_role="local-primary",
            scheduled_tick="0810",
            attempt_id="attempt-entry-claim-loser",
        )
    )

    assert loser_result.status == "entry_failure_artifact_claim_held"
    assert "entry_failure_artifact_claim_held" in scheduler_runner._FAILED_STATUSES
    assert loser_storage.entry_uploads == []
    assert notifier.sent == []
    assert not any(
        ":late-alert:sent:US:2026-05-28:pipeline_failed" in key
        for key, _payload in state.upserts
    )
    assert not any(
        ":late-alert:sent:US:2026-05-28:scheduled_entry_failed" in key
        for key, _payload in state.upserts
    )

    winner_storage = _FakeStorage()
    winner_runner, _state, _pipeline, _storage, _notifier = _runner(
        state=state,
        storage=winner_storage,
        notifier=notifier,
        pipeline=_TypedEntryFailurePipeline(),
    )

    winner_result = winner_runner.run(
        ScheduledAiBriefRequest(
            market="US",
            schedule_role="local-primary",
            runner_role="local-primary",
            scheduled_tick="0810",
            attempt_id="attempt-entry-claim-winner",
        )
    )

    assert winner_result.status == "pipeline_failed"
    assert winner_storage.entry_uploads == ["reports/current.entry.json"]
    assert notifier.sent == ["scheduled_entry_failed"]
    expected_entry_context = {
        "market": "US",
        "sessionDate": "2026-05-28",
        "attemptId": "attempt-entry-claim-winner",
        "scheduleRole": "local-primary",
        "runnerRole": "local-primary",
        "failureDetail": "scheduled entry failed",
        "entryReportPath": "reports/current.entry.json",
        "entryReportStorageKey": "2026/05/2026-05-28.entry.json",
    }
    assert notifier.late_alerts[-1] == (
        "scheduled_entry_failed",
        expected_entry_context,
    )


def test_scheduled_entry_failure_uploads_artifact_when_prior_alert_lacks_storage_key() -> (
    None
):
    sent_key = (
        build_scheduler_state_key(
            kind="late-alert:sent",
            market="US",
            session_date="2026-05-28",
        )
        + ":scheduled_entry_failed"
    )
    state = _FakeStateStore(
        entries={
            sent_key: RuntimeStateEntry(
                state_key=sent_key,
                state_payload={
                    "market": "US",
                    "sessionDate": "2026-05-28",
                    "reason": "scheduled_entry_failed",
                },
                expires_at="2026-05-30T00:00:00Z",
            )
        }
    )
    runner, state, _pipeline, storage, notifier = _runner(
        state=state,
        pipeline=_TypedEntryFailurePipeline(),
    )

    result = runner.run(
        ScheduledAiBriefRequest(
            market="US",
            schedule_role="local-primary",
            runner_role="local-primary",
            scheduled_tick="0810",
            attempt_id="attempt-entry-alert-already-sent",
        )
    )

    assert result.status == "pipeline_failed"
    assert any(":lock:" in key for key in state.releases)
    assert storage.entry_uploads == ["reports/current.entry.json"]
    assert notifier.sent == []
    assert notifier.late_alerts == []
    artifact_payloads = [
        payload
        for key, payload in state.upserts
        if ":entry-failure-artifact:US:2026-05-28" in key
    ]
    assert artifact_payloads == [
        {
            "storageKey": "2026/05/2026-05-28.entry.json",
            "market": "US",
            "sessionDate": "2026-05-28",
            "reportDate": "2026-05-28",
            "entryReportPath": "reports/current.entry.json",
            "reason": "scheduled_entry_failed",
            "scheduleRole": "local-primary",
            "runnerRole": "local-primary",
            "attemptId": "attempt-entry-alert-already-sent",
        }
    ]


def test_pipeline_failure_string_does_not_spoof_scheduled_entry_alert() -> None:
    runner, _state, _pipeline, _storage, notifier = _runner(
        pipeline=_FakePipeline(
            fail=True,
            failure_message=(
                "scheduled entry failed (entry_report_path=reports/current.entry.json)"
            ),
        )
    )

    result = runner.run(
        ScheduledAiBriefRequest(
            market="US",
            schedule_role="local-primary",
            runner_role="local-primary",
            scheduled_tick="0810",
            attempt_id="attempt-spoofed-entry-failed",
        )
    )

    assert result.status == "pipeline_failed"
    assert notifier.sent == ["pipeline_failed"]
    reason, context = notifier.late_alerts[0]
    assert reason == "pipeline_failed"
    assert "failureDetail" not in context
    assert "entryReportPath" not in context


def test_scheduled_entry_failure_alert_is_not_suppressed_by_generic_pipeline_failure() -> (
    None
):
    state = _FakeStateStore()
    notifier = _FakeNotifier()
    generic_runner, _state, _pipeline, _storage, _notifier = _runner(
        state=state,
        notifier=notifier,
        pipeline=_FakePipeline(fail=True),
    )

    generic_result = generic_runner.run(
        ScheduledAiBriefRequest(
            market="US",
            schedule_role="local-primary",
            runner_role="local-primary",
            scheduled_tick="0810",
            attempt_id="attempt-generic-pipeline-failed",
        )
    )

    entry_runner, _state, _pipeline, _storage, _notifier = _runner(
        state=state,
        notifier=notifier,
        pipeline=_TypedEntryFailurePipeline(),
    )
    entry_result = entry_runner.run(
        ScheduledAiBriefRequest(
            market="US",
            schedule_role="local-primary",
            runner_role="local-primary",
            scheduled_tick="0810",
            attempt_id="attempt-scheduled-entry-failed",
        )
    )

    assert generic_result.status == "pipeline_failed"
    assert entry_result.status == "pipeline_failed"
    assert notifier.sent == ["pipeline_failed", "scheduled_entry_failed"]
    entry_context = {
        "market": "US",
        "sessionDate": "2026-05-28",
        "attemptId": "attempt-scheduled-entry-failed",
        "scheduleRole": "local-primary",
        "runnerRole": "local-primary",
        "failureDetail": "scheduled entry failed",
        "entryReportPath": "reports/current.entry.json",
        "entryReportStorageKey": "2026/05/2026-05-28.entry.json",
    }
    assert notifier.late_alerts[-1] == ("scheduled_entry_failed", entry_context)
    sent_payloads = [
        payload
        for key, payload in state.upserts
        if ":late-alert:sent:US:2026-05-28:scheduled_entry_failed" in key
    ]
    assert sent_payloads == [{**entry_context, "reason": "scheduled_entry_failed"}]


def test_wrapped_scheduled_entry_failure_alert_is_not_suppressed_by_generic_pipeline_failure() -> (
    None
):
    class _WrappedScheduledEntryFailurePipeline(_FakePipeline):
        def run(
            self,
            *,
            market: str,
            session_date: str,
            report_date: str,
            source_provider: str | None,
            model_provider: str,
            dry_run: bool,
            model_deadline_remaining_seconds: float | None = None,
            model_deadline_at: dt.datetime | None = None,
            source_api_url: str | None = None,
            source_provider_chain: tuple[str, ...] | None = None,
        ) -> ScheduledPipelineResult:
            self._record_call(
                market=market,
                session_date=session_date,
                report_date=report_date,
                source_provider=source_provider,
                source_api_url=source_api_url,
                source_provider_chain=source_provider_chain,
                model_provider=model_provider,
                dry_run=dry_run,
            )
            try:
                raise scheduler_runner._ScheduledEntryStepError(
                    "reports/current.entry.json"
                )
            except RuntimeError as err:
                raise RuntimeError("pipeline wrapper") from err

    state = _FakeStateStore()
    notifier = _FakeNotifier()
    generic_runner, _state, _pipeline, _storage, _notifier = _runner(
        state=state,
        notifier=notifier,
        pipeline=_FakePipeline(fail=True),
    )

    generic_result = generic_runner.run(
        ScheduledAiBriefRequest(
            market="US",
            schedule_role="local-primary",
            runner_role="local-primary",
            scheduled_tick="0810",
            attempt_id="attempt-generic-before-wrapped-entry",
        )
    )

    entry_runner, _state, _pipeline, _storage, _notifier = _runner(
        state=state,
        notifier=notifier,
        pipeline=_WrappedScheduledEntryFailurePipeline(),
    )
    entry_result = entry_runner.run(
        ScheduledAiBriefRequest(
            market="US",
            schedule_role="local-primary",
            runner_role="local-primary",
            scheduled_tick="0810",
            attempt_id="attempt-wrapped-scheduled-entry",
        )
    )

    assert generic_result.status == "pipeline_failed"
    assert entry_result.status == "pipeline_failed"
    assert notifier.sent == ["pipeline_failed", "scheduled_entry_failed"]
    entry_context = {
        "market": "US",
        "sessionDate": "2026-05-28",
        "attemptId": "attempt-wrapped-scheduled-entry",
        "scheduleRole": "local-primary",
        "runnerRole": "local-primary",
        "failureDetail": "scheduled entry failed",
        "entryReportPath": "reports/current.entry.json",
        "entryReportStorageKey": "2026/05/2026-05-28.entry.json",
    }
    assert notifier.late_alerts[-1] == ("scheduled_entry_failed", entry_context)


def test_pipeline_failure_late_alert_does_not_classify_case_variant_string_detail() -> (
    None
):
    failure_message = (
        "Scheduled entry failed (entry_report_path=reports/current.entry.json)"
    )
    runner, state, _pipeline, _storage, notifier = _runner(
        pipeline=_FakePipeline(fail=True, failure_message=failure_message)
    )

    result = runner.run(
        ScheduledAiBriefRequest(
            market="US",
            schedule_role="local-primary",
            runner_role="local-primary",
            scheduled_tick="0810",
            attempt_id="attempt-entry-case-variant",
        )
    )

    assert result.status == "pipeline_failed"
    assert any(":lock:" in key for key in state.releases)
    expected_context = {
        "market": "US",
        "sessionDate": "2026-05-28",
        "attemptId": "attempt-entry-case-variant",
        "scheduleRole": "local-primary",
        "runnerRole": "local-primary",
    }
    assert notifier.late_alerts == [("pipeline_failed", expected_context)]
    sent_payloads = [
        payload
        for key, payload in state.upserts
        if ":late-alert:sent:US:2026-05-28:pipeline_failed" in key
    ]
    assert sent_payloads == [{**expected_context, "reason": "pipeline_failed"}]


@pytest.mark.parametrize(
    "entry_report_path",
    [
        "/tmp/private/current.entry.json",
        "reports/../current.entry.json",
        "reports\\current.entry.json",
        "reports//current.entry.json",
        "reports/./current.entry.json",
        "reports/foo\x00/current.entry.json",
        "reports/foo\x1f/current.entry.json",
        "reports/foo\x85/current.entry.json",
        "reports/foo\x9b/current.entry.json",
        "\nreports/current.entry.json\n",
        "\rreports/current.entry.json\r",
        "reports/foo\nentryReportPath=/tmp/private/current.entry.json",
        "reports/foo\rentryReportPath=/tmp/private/current.entry.json",
        "reports/foo\u2028entryReportPath=/tmp/private/current.entry.json",
        "reports/foo\u2029entryReportPath=/tmp/private/current.entry.json",
        "reports/..\uff0fprivate.entry.json",
        "reports/\uff0e\uff0e/private.entry.json",
        "reports/foo\uff0fbar.entry.json",
        "reports/..\u2215private.entry.json",
        "reports/foo\u2044bar.entry.json",
        "reports/foo\u29f8bar.entry.json",
        "reports/foo\u2216bar.entry.json",
        "reports/foo\u2571bar.entry.json",
    ],
)
def test_pipeline_failure_late_alert_omits_unsafe_scheduled_entry_detail(
    caplog: pytest.LogCaptureFixture, entry_report_path: str
) -> None:
    runner, state, _pipeline, _storage, notifier = _runner(
        pipeline=_FakePipeline(
            fail=True,
            failure_message=(
                f"scheduled entry failed (entry_report_path={entry_report_path})"
            ),
        )
    )
    caplog.set_level("ERROR", logger="sab.scheduler.runner")

    result = runner.run(
        ScheduledAiBriefRequest(
            market="US",
            schedule_role="local-primary",
            runner_role="local-primary",
            scheduled_tick="0810",
            attempt_id="attempt-entry-unsafe-detail",
        )
    )

    assert result.status == "pipeline_failed"
    assert any(":lock:" in key for key in state.releases)
    expected_context = {
        "market": "US",
        "sessionDate": "2026-05-28",
        "attemptId": "attempt-entry-unsafe-detail",
        "scheduleRole": "local-primary",
        "runnerRole": "local-primary",
    }
    assert notifier.late_alerts == [("pipeline_failed", expected_context)]
    sent_payloads = [
        payload
        for key, payload in state.upserts
        if ":late-alert:sent:US:2026-05-28:pipeline_failed" in key
    ]
    assert sent_payloads == [{**expected_context, "reason": "pipeline_failed"}]
    assert "entry_report_path=unsafe" in caplog.text

    emitted_text = "\n".join(
        [caplog.text, str(notifier.late_alerts), str(sent_payloads)]
    )
    dangerous_fragments = {
        entry_report_path,
        unicodedata.normalize("NFKC", entry_report_path),
        "/tmp/private",
    }
    for fragment in dangerous_fragments:
        assert fragment not in emitted_text


@pytest.mark.parametrize(
    "failure_message",
    [
        "scheduled entry failed (entry_report_path=/tmp/private/current.entry.json)",
        "\nscheduled entry failed (entry_report_path=/tmp/private/current.entry.json)\n",
        "\rscheduled entry failed (entry_report_path=/tmp/private/current.entry.json)\r",
        "scheduled entry failed (entry_report_path=/tmp/private/current.entry.json)\u2028",
        "\x00scheduled entry failed (entry_report_path=/tmp/private/current.entry.json)\x00",
        "\x1bscheduled entry failed (entry_report_path=/tmp/private/current.entry.json)\x1b",
        "wrapper: scheduled entry failed (entry_report_path=/tmp/private/current.entry.json)",
        "entry wrapper: scheduled entry failed (entry_report_path=/tmp/private/current.entry.json)",
    ],
)
def test_runner_pipeline_failure_log_omits_raw_wrapped_entry_report_path(
    caplog: pytest.LogCaptureFixture, failure_message: str
) -> None:
    runner, state, _pipeline, _storage, notifier = _runner(
        pipeline=_FakePipeline(fail=True, failure_message=failure_message)
    )
    caplog.set_level("ERROR", logger="sab.scheduler.runner")

    result = runner.run(
        ScheduledAiBriefRequest(
            market="US",
            schedule_role="local-primary",
            runner_role="local-primary",
            scheduled_tick="0810",
            attempt_id="attempt-entry-raw-log",
        )
    )

    assert result.status == "pipeline_failed"
    assert any(":lock:" in key for key in state.releases)
    assert notifier.sent == ["pipeline_failed"]
    assert "entry_report_path=unsafe" in caplog.text
    assert "/tmp/private" not in caplog.text
    assert "/tmp/private" not in str(notifier.late_alerts)


def test_runner_pipeline_failure_log_keeps_sanitized_traceback_for_entry_failure(
    caplog: pytest.LogCaptureFixture,
) -> None:
    failure_message = (
        "scheduled entry failed (entry_report_path=/tmp/private/current.entry.json)"
    )
    runner, state, _pipeline, _storage, notifier = _runner(
        pipeline=_FakePipeline(fail=True, failure_message=failure_message)
    )
    caplog.set_level("ERROR", logger="sab.scheduler.runner")

    result = runner.run(
        ScheduledAiBriefRequest(
            market="US",
            schedule_role="local-primary",
            runner_role="local-primary",
            scheduled_tick="0810",
            attempt_id="attempt-entry-sanitized-traceback",
        )
    )

    assert result.status == "pipeline_failed"
    assert any(":lock:" in key for key in state.releases)
    assert notifier.sent == ["pipeline_failed"]
    failure_records = [
        record
        for record in caplog.records
        if "scheduled AI brief pipeline failed" in record.getMessage()
    ]
    assert len(failure_records) == 1
    assert failure_records[0].exc_info is not None
    assert "error_type=RuntimeError" in caplog.text
    assert "entry_report_path=unsafe" in caplog.text
    assert "/tmp/private" not in caplog.text


def test_runner_pipeline_failure_log_redacts_mixed_case_entry_report_token(
    caplog: pytest.LogCaptureFixture,
) -> None:
    failure_message = (
        "scheduled entry failed "
        "(entry_report_path=reports/current.entry.json) "
        "raw=/tmp/private/CURRENT.ENTRY.JSON"
    )
    runner, state, _pipeline, _storage, notifier = _runner(
        pipeline=_FakePipeline(fail=True, failure_message=failure_message)
    )
    caplog.set_level("ERROR", logger="sab.scheduler.runner")

    result = runner.run(
        ScheduledAiBriefRequest(
            market="US",
            schedule_role="local-primary",
            runner_role="local-primary",
            scheduled_tick="0810",
            attempt_id="attempt-entry-mixed-case-token",
        )
    )

    assert result.status == "pipeline_failed"
    assert any(":lock:" in key for key in state.releases)
    assert notifier.sent == ["pipeline_failed"]
    assert "entry_report_path=unsafe" in caplog.text
    assert "/tmp/private" not in caplog.text
    assert "CURRENT.ENTRY.JSON" not in caplog.text


def test_runner_pipeline_failure_log_redacts_entry_report_path_token_suffix(
    caplog: pytest.LogCaptureFixture,
) -> None:
    failure_message = (
        "scheduled entry failed "
        "(entry_report_path=reports/current.entry.json) "
        "raw=/tmp/private/current.entry.json?token=abc#fragment"
    )
    runner, state, _pipeline, _storage, notifier = _runner(
        pipeline=_FakePipeline(fail=True, failure_message=failure_message)
    )
    caplog.set_level("ERROR", logger="sab.scheduler.runner")

    result = runner.run(
        ScheduledAiBriefRequest(
            market="US",
            schedule_role="local-primary",
            runner_role="local-primary",
            scheduled_tick="0810",
            attempt_id="attempt-entry-token-suffix",
        )
    )

    assert result.status == "pipeline_failed"
    assert any(":lock:" in key for key in state.releases)
    assert notifier.sent == ["pipeline_failed"]
    assert "raw=unsafe" in caplog.text
    assert "/tmp/private" not in caplog.text
    assert "token=abc" not in caplog.text
    assert "#fragment" not in caplog.text


def test_runner_pipeline_failure_log_redacts_entry_report_path_token_with_parenthesis(
    caplog: pytest.LogCaptureFixture,
) -> None:
    failure_message = (
        "scheduled entry failed "
        "(entry_report_path=reports/current.entry.json) "
        "raw=/tmp/private/foo)bar.entry.json"
    )
    runner, state, _pipeline, _storage, notifier = _runner(
        pipeline=_FakePipeline(fail=True, failure_message=failure_message)
    )
    caplog.set_level("ERROR", logger="sab.scheduler.runner")

    result = runner.run(
        ScheduledAiBriefRequest(
            market="US",
            schedule_role="local-primary",
            runner_role="local-primary",
            scheduled_tick="0810",
            attempt_id="attempt-entry-token-paren",
        )
    )

    assert result.status == "pipeline_failed"
    assert any(":lock:" in key for key in state.releases)
    assert notifier.sent == ["pipeline_failed"]
    assert "raw=unsafe" in caplog.text
    assert "/tmp/private" not in caplog.text
    assert "foo)bar.entry.json" not in caplog.text


def test_runner_pipeline_failure_log_redacts_labeled_entry_report_path_with_parenthesis(
    caplog: pytest.LogCaptureFixture,
) -> None:
    failure_message = (
        "scheduled entry failed (entry_report_path=/tmp/private/foo)bar.entry.json)"
    )
    runner, state, _pipeline, _storage, notifier = _runner(
        pipeline=_FakePipeline(fail=True, failure_message=failure_message)
    )
    caplog.set_level("ERROR", logger="sab.scheduler.runner")

    result = runner.run(
        ScheduledAiBriefRequest(
            market="US",
            schedule_role="local-primary",
            runner_role="local-primary",
            scheduled_tick="0810",
            attempt_id="attempt-entry-label-paren",
        )
    )

    assert result.status == "pipeline_failed"
    assert any(":lock:" in key for key in state.releases)
    assert notifier.sent == ["pipeline_failed"]
    assert "entry_report_path=unsafe" in caplog.text
    assert "/tmp/private" not in caplog.text
    assert "foo)bar.entry.json" not in caplog.text


def test_runner_pipeline_failure_log_keeps_original_exception_type_for_sanitized_traceback(
    caplog: pytest.LogCaptureFixture,
) -> None:
    class _ValueErrorEntryFailurePipeline(_FakePipeline):
        def run(
            self,
            *,
            market: str,
            session_date: str,
            report_date: str,
            source_provider: str | None,
            model_provider: str,
            dry_run: bool,
            model_deadline_remaining_seconds: float | None = None,
            model_deadline_at: dt.datetime | None = None,
            source_api_url: str | None = None,
            source_provider_chain: tuple[str, ...] | None = None,
        ) -> ScheduledPipelineResult:
            self._record_call(
                market=market,
                session_date=session_date,
                report_date=report_date,
                source_provider=source_provider,
                source_api_url=source_api_url,
                source_provider_chain=source_provider_chain,
                model_provider=model_provider,
                dry_run=dry_run,
            )
            raise ValueError(
                "scheduled entry failed "
                "(entry_report_path=/tmp/private/current.entry.json)"
            )

    runner, state, _pipeline, _storage, notifier = _runner(
        pipeline=_ValueErrorEntryFailurePipeline()
    )
    caplog.set_level("ERROR", logger="sab.scheduler.runner")

    result = runner.run(
        ScheduledAiBriefRequest(
            market="US",
            schedule_role="local-primary",
            runner_role="local-primary",
            scheduled_tick="0810",
            attempt_id="attempt-entry-value-error-traceback",
        )
    )

    assert result.status == "pipeline_failed"
    assert any(":lock:" in key for key in state.releases)
    assert notifier.sent == ["pipeline_failed"]
    failure_records = [
        record
        for record in caplog.records
        if "scheduled AI brief pipeline failed" in record.getMessage()
    ]
    assert len(failure_records) == 1
    assert failure_records[0].exc_info is not None
    exc_type, exc_value, _traceback = failure_records[0].exc_info
    assert exc_type is ValueError
    assert isinstance(exc_value, ValueError)
    assert "entry_report_path=unsafe" in str(exc_value)
    assert "error_type=ValueError" in caplog.text
    assert "/tmp/private" not in caplog.text


def test_runner_pipeline_failure_log_keeps_sanitized_exception_chain(
    caplog: pytest.LogCaptureFixture,
) -> None:
    class _ChainedValueErrorEntryFailurePipeline(_FakePipeline):
        def run(
            self,
            *,
            market: str,
            session_date: str,
            report_date: str,
            source_provider: str | None,
            model_provider: str,
            dry_run: bool,
            model_deadline_remaining_seconds: float | None = None,
            model_deadline_at: dt.datetime | None = None,
            source_api_url: str | None = None,
            source_provider_chain: tuple[str, ...] | None = None,
        ) -> ScheduledPipelineResult:
            self._record_call(
                market=market,
                session_date=session_date,
                report_date=report_date,
                source_provider=source_provider,
                source_api_url=source_api_url,
                source_provider_chain=source_provider_chain,
                model_provider=model_provider,
                dry_run=dry_run,
            )
            try:
                raise ValueError(
                    "scheduled entry failed "
                    "(entry_report_path=/tmp/private/current.entry.json)"
                )
            except ValueError as err:
                raise RuntimeError("pipeline wrapper") from err

    runner, state, _pipeline, _storage, notifier = _runner(
        pipeline=_ChainedValueErrorEntryFailurePipeline()
    )
    caplog.set_level("ERROR", logger="sab.scheduler.runner")

    result = runner.run(
        ScheduledAiBriefRequest(
            market="US",
            schedule_role="local-primary",
            runner_role="local-primary",
            scheduled_tick="0810",
            attempt_id="attempt-entry-sanitized-chain",
        )
    )

    assert result.status == "pipeline_failed"
    assert any(":lock:" in key for key in state.releases)
    assert notifier.sent == ["pipeline_failed"]
    failure_records = [
        record
        for record in caplog.records
        if "scheduled AI brief pipeline failed" in record.getMessage()
    ]
    assert len(failure_records) == 1
    assert failure_records[0].exc_info is not None
    _exc_type, exc_value, _traceback = failure_records[0].exc_info
    assert isinstance(exc_value, RuntimeError)
    assert isinstance(exc_value.__cause__, ValueError)
    assert "entry_report_path=unsafe" in str(exc_value.__cause__)
    assert str(exc_value) == "<redacted scheduled entry exception>"
    assert "pipeline wrapper" not in str(exc_value)
    assert "/tmp/private" not in caplog.text


def test_runner_pipeline_failure_log_redacts_wrapper_and_note_entry_report_paths(
    caplog: pytest.LogCaptureFixture,
) -> None:
    class _RawWrapperEntryFailurePipeline(_FakePipeline):
        def run(
            self,
            *,
            market: str,
            session_date: str,
            report_date: str,
            source_provider: str | None,
            model_provider: str,
            dry_run: bool,
            model_deadline_remaining_seconds: float | None = None,
            model_deadline_at: dt.datetime | None = None,
            source_api_url: str | None = None,
            source_provider_chain: tuple[str, ...] | None = None,
        ) -> ScheduledPipelineResult:
            self._record_call(
                market=market,
                session_date=session_date,
                report_date=report_date,
                source_provider=source_provider,
                source_api_url=source_api_url,
                source_provider_chain=source_provider_chain,
                model_provider=model_provider,
                dry_run=dry_run,
            )
            try:
                raise RuntimeError(
                    "scheduled entry failed "
                    "(entry_report_path=reports/current.entry.json)"
                )
            except RuntimeError as err:
                wrapper = RuntimeError(
                    "pipeline wrapper raw=/tmp/private/current.entry.json"
                )
                wrapper.add_note("note raw=/tmp/private/from-note.entry.json")
                raise wrapper from err

    runner, state, _pipeline, _storage, notifier = _runner(
        pipeline=_RawWrapperEntryFailurePipeline()
    )
    caplog.set_level("ERROR", logger="sab.scheduler.runner")

    result = runner.run(
        ScheduledAiBriefRequest(
            market="US",
            schedule_role="local-primary",
            runner_role="local-primary",
            scheduled_tick="0810",
            attempt_id="attempt-entry-raw-wrapper-note",
        )
    )

    assert result.status == "pipeline_failed"
    assert any(":lock:" in key for key in state.releases)
    assert notifier.sent == ["pipeline_failed"]
    assert "entry_report_path=reports/current.entry.json" in caplog.text
    assert "<redacted scheduled entry exception>" in caplog.text
    assert "raw=unsafe" not in caplog.text
    assert "/tmp/private" not in caplog.text
    assert "/tmp/private" not in str(notifier.late_alerts)


def test_runner_pipeline_failure_log_classifies_exception_group_entry_failure(
    caplog: pytest.LogCaptureFixture,
) -> None:
    class _GroupedEntryFailurePipeline(_FakePipeline):
        def run(
            self,
            *,
            market: str,
            session_date: str,
            report_date: str,
            source_provider: str | None,
            model_provider: str,
            dry_run: bool,
            model_deadline_remaining_seconds: float | None = None,
            model_deadline_at: dt.datetime | None = None,
            source_api_url: str | None = None,
            source_provider_chain: tuple[str, ...] | None = None,
        ) -> ScheduledPipelineResult:
            self._record_call(
                market=market,
                session_date=session_date,
                report_date=report_date,
                source_provider=source_provider,
                source_api_url=source_api_url,
                source_provider_chain=source_provider_chain,
                model_provider=model_provider,
                dry_run=dry_run,
            )
            raise ExceptionGroup(
                "pipeline group",
                [
                    RuntimeError(
                        "scheduled entry failed "
                        "(entry_report_path=/tmp/private/current.entry.json)"
                    )
                ],
            )

    runner, state, _pipeline, _storage, notifier = _runner(
        pipeline=_GroupedEntryFailurePipeline()
    )
    caplog.set_level("ERROR", logger="sab.scheduler.runner")

    result = runner.run(
        ScheduledAiBriefRequest(
            market="US",
            schedule_role="local-primary",
            runner_role="local-primary",
            scheduled_tick="0810",
            attempt_id="attempt-entry-exception-group",
        )
    )

    assert result.status == "pipeline_failed"
    assert any(":lock:" in key for key in state.releases)
    assert notifier.sent == ["pipeline_failed"]
    assert notifier.late_alerts[0][0] == "pipeline_failed"
    assert "failureDetail" not in notifier.late_alerts[0][1]
    assert "entryReportPath" not in notifier.late_alerts[0][1]
    assert "entry_report_path=unsafe" in caplog.text
    assert "/tmp/private" not in caplog.text
    assert "/tmp/private" not in str(notifier.late_alerts)


def test_runner_pipeline_failure_log_preserves_unrelated_entry_report_path_error(
    caplog: pytest.LogCaptureFixture,
) -> None:
    failure_message = (
        "ai-brief parse failed entry_report_path=reports/current.entry.json"
    )
    runner, state, _pipeline, _storage, notifier = _runner(
        pipeline=_FakePipeline(fail=True, failure_message=failure_message)
    )
    caplog.set_level("ERROR", logger="sab.scheduler.runner")

    result = runner.run(
        ScheduledAiBriefRequest(
            market="US",
            schedule_role="local-primary",
            runner_role="local-primary",
            scheduled_tick="0810",
            attempt_id="attempt-unrelated-entry-report-token",
        )
    )

    assert result.status == "pipeline_failed"
    assert any(":lock:" in key for key in state.releases)
    assert notifier.sent == ["pipeline_failed"]
    assert failure_message in caplog.text
    assert "scheduled entry failed (entry_report_path=" not in caplog.text
    context = notifier.late_alerts[0][1]
    assert "failureDetail" not in context
    assert "entryReportPath" not in context


@pytest.mark.parametrize(
    ("failure_message", "expected_context", "raw_fragment", "expected_reason"),
    [
        (
            "scheduled entry failed raw=／tmp／private/current.entry.json",
            "scheduled entry failed",
            "／tmp／private",
            "pipeline_failed",
        ),
        (
            "scheduled entry failed raw=⁄tmp⁄private/current.entry.json",
            "scheduled entry failed",
            "⁄tmp⁄private",
            "pipeline_failed",
        ),
        (
            "scheduled entry failed\u200b "
            "(entry_report_path=/tmp/private/current.entry.json)",
            "scheduled entry failed",
            "/tmp/private",
            "pipeline_failed",
        ),
        (
            "scheduled-entry failed "
            "(entry_report_path=/tmp/private/current.entry.json)",
            "scheduled-entry failed",
            "/tmp/private",
            "pipeline_failed",
        ),
        (
            "entry wrapper: scheduled entry failed "
            "(entry_report_path=reports/current.entry.json); "
            "raw=/tmp/private/current.entry.json",
            "entry wrapper",
            "/tmp/private",
            "pipeline_failed",
        ),
        (
            "scheduled entry failed "
            "(entry_report_path=reports/current.entry.json) "
            r"raw=C:\Users\me\current.entry.json",
            "scheduled entry failed",
            r"C:\Users",
            "pipeline_failed",
        ),
        (
            "scheduled entry failed "
            "(entry_report_path=reports/current.entry.json) "
            "raw=/tmp/private/current entry.entry.json",
            "scheduled entry failed",
            "/tmp/private",
            "pipeline_failed",
        ),
        (
            "scheduled entry failed "
            "(ｅｎｔｒｙ_report_path="
            r"C:\Users\me\current.entry.json)",
            "scheduled entry failed",
            r"C:\Users",
            "pipeline_failed",
        ),
        (
            "ai-brief parse failed while reading text: scheduled entry failed "
            "(entry_report_path=/tmp/private/current.entry.json)",
            "ai-brief parse failed",
            "/tmp/private",
            "pipeline_failed",
        ),
    ],
)
def test_runner_pipeline_failure_log_redacts_obfuscated_scheduled_entry_path(
    caplog: pytest.LogCaptureFixture,
    failure_message: str,
    expected_context: str,
    raw_fragment: str,
    expected_reason: str,
) -> None:
    runner, state, _pipeline, _storage, notifier = _runner(
        pipeline=_FakePipeline(fail=True, failure_message=failure_message)
    )
    caplog.set_level("ERROR", logger="sab.scheduler.runner")

    result = runner.run(
        ScheduledAiBriefRequest(
            market="US",
            schedule_role="local-primary",
            runner_role="local-primary",
            scheduled_tick="0810",
            attempt_id="attempt-entry-obfuscated-log",
        )
    )

    assert result.status == "pipeline_failed"
    assert any(":lock:" in key for key in state.releases)
    assert notifier.sent == [expected_reason]
    assert expected_context in caplog.text
    assert "entry_report_path=unsafe" in caplog.text
    assert raw_fragment not in caplog.text
    assert raw_fragment not in str(notifier.late_alerts)


def test_runner_pipeline_failure_log_redacts_noted_windows_entry_report_path(
    caplog: pytest.LogCaptureFixture,
) -> None:
    class _NotedWindowsEntryFailurePipeline(_FakePipeline):
        def run(
            self,
            *,
            market: str,
            session_date: str,
            report_date: str,
            source_provider: str | None,
            model_provider: str,
            dry_run: bool,
            model_deadline_remaining_seconds: float | None = None,
            model_deadline_at: dt.datetime | None = None,
            source_api_url: str | None = None,
            source_provider_chain: tuple[str, ...] | None = None,
        ) -> ScheduledPipelineResult:
            self._record_call(
                market=market,
                session_date=session_date,
                report_date=report_date,
                source_provider=source_provider,
                source_api_url=source_api_url,
                source_provider_chain=source_provider_chain,
                model_provider=model_provider,
                dry_run=dry_run,
            )
            err = RuntimeError("pipeline wrapper")
            err.add_note(
                "scheduled entry failed "
                "(entry_report_path=reports/current.entry.json) "
                r"raw=C:\Users\me\current.entry.json"
            )
            raise err

    runner, state, _pipeline, _storage, notifier = _runner(
        pipeline=_NotedWindowsEntryFailurePipeline()
    )
    caplog.set_level("ERROR", logger="sab.scheduler.runner")

    result = runner.run(
        ScheduledAiBriefRequest(
            market="US",
            schedule_role="local-primary",
            runner_role="local-primary",
            scheduled_tick="0810",
            attempt_id="attempt-noted-windows-entry-report-log",
        )
    )

    assert result.status == "pipeline_failed"
    assert any(":lock:" in key for key in state.releases)
    assert notifier.sent == ["pipeline_failed"]
    assert "entry_report_path=unsafe" in caplog.text
    assert r"C:\Users" not in caplog.text
    assert r"C:\Users" not in str(notifier.late_alerts)


def test_runner_pipeline_failure_log_redacts_split_scheduled_entry_note_path(
    caplog: pytest.LogCaptureFixture,
) -> None:
    class _SplitNotedEntryFailurePipeline(_FakePipeline):
        def run(
            self,
            *,
            market: str,
            session_date: str,
            report_date: str,
            source_provider: str | None,
            model_provider: str,
            dry_run: bool,
            model_deadline_remaining_seconds: float | None = None,
            model_deadline_at: dt.datetime | None = None,
            source_api_url: str | None = None,
            source_provider_chain: tuple[str, ...] | None = None,
        ) -> ScheduledPipelineResult:
            self._record_call(
                market=market,
                session_date=session_date,
                report_date=report_date,
                source_provider=source_provider,
                source_api_url=source_api_url,
                source_provider_chain=source_provider_chain,
                model_provider=model_provider,
                dry_run=dry_run,
            )
            err = RuntimeError("scheduled entry failed")
            err.add_note("entry_report_path=/tmp/private/from-note.entry.json")
            raise err

    runner, state, _pipeline, _storage, notifier = _runner(
        pipeline=_SplitNotedEntryFailurePipeline()
    )
    caplog.set_level("ERROR", logger="sab.scheduler.runner")

    result = runner.run(
        ScheduledAiBriefRequest(
            market="US",
            schedule_role="local-primary",
            runner_role="local-primary",
            scheduled_tick="0810",
            attempt_id="attempt-split-noted-entry-report-log",
        )
    )

    assert result.status == "pipeline_failed"
    assert any(":lock:" in key for key in state.releases)
    assert notifier.sent == ["pipeline_failed"]
    assert "entry_report_path=unsafe" in caplog.text
    assert "/tmp/private" not in caplog.text
    assert "/tmp/private" not in str(notifier.late_alerts)


def test_runner_pipeline_failure_log_redacts_wrapped_scheduled_entry_exception_output(
    caplog: pytest.LogCaptureFixture,
) -> None:
    class _WrappedEntryFailurePipeline(_FakePipeline):
        def run(
            self,
            *,
            market: str,
            session_date: str,
            report_date: str,
            source_provider: str | None,
            model_provider: str,
            dry_run: bool,
            model_deadline_remaining_seconds: float | None = None,
            model_deadline_at: dt.datetime | None = None,
            source_api_url: str | None = None,
            source_provider_chain: tuple[str, ...] | None = None,
        ) -> ScheduledPipelineResult:
            self._record_call(
                market=market,
                session_date=session_date,
                report_date=report_date,
                source_provider=source_provider,
                source_api_url=source_api_url,
                source_provider_chain=source_provider_chain,
                model_provider=model_provider,
                dry_run=dry_run,
            )
            try:
                raise scheduler_runner._ScheduledEntryStepError(
                    "reports/current.entry.json"
                )
            except RuntimeError as err:
                entry_output = "entry stdout=KIS_APP_SECRET=sekret"
                raise RuntimeError(entry_output) from err

    runner, state, _pipeline, _storage, notifier = _runner(
        pipeline=_WrappedEntryFailurePipeline()
    )
    caplog.set_level("ERROR", logger="sab.scheduler.runner")

    result = runner.run(
        ScheduledAiBriefRequest(
            market="US",
            schedule_role="local-primary",
            runner_role="local-primary",
            scheduled_tick="0810",
            attempt_id="attempt-wrapped-entry-secret-log",
        )
    )

    assert result.status == "pipeline_failed"
    assert any(":lock:" in key for key in state.releases)
    assert notifier.sent == ["scheduled_entry_failed"]
    assert "scheduled entry failed" in caplog.text
    assert "KIS_APP_SECRET" not in caplog.text
    assert "sekret" not in caplog.text


def test_runner_pipeline_failure_log_omits_chained_unsafe_entry_report_path(
    caplog: pytest.LogCaptureFixture,
) -> None:
    class _ChainedEntryFailurePipeline(_FakePipeline):
        def run(
            self,
            *,
            market: str,
            session_date: str,
            report_date: str,
            source_provider: str | None,
            model_provider: str,
            dry_run: bool,
            model_deadline_remaining_seconds: float | None = None,
            model_deadline_at: dt.datetime | None = None,
            source_api_url: str | None = None,
            source_provider_chain: tuple[str, ...] | None = None,
        ) -> ScheduledPipelineResult:
            self._record_call(
                market=market,
                session_date=session_date,
                report_date=report_date,
                source_provider=source_provider,
                source_api_url=source_api_url,
                source_provider_chain=source_provider_chain,
                model_provider=model_provider,
                dry_run=dry_run,
            )
            try:
                raise RuntimeError(
                    "scheduled entry failed "
                    "(entry_report_path=/tmp/private/current.entry.json)"
                )
            except RuntimeError as err:
                raise RuntimeError("pipeline wrapper") from err

    runner, state, _pipeline, _storage, notifier = _runner(
        pipeline=_ChainedEntryFailurePipeline()
    )
    caplog.set_level("ERROR", logger="sab.scheduler.runner")

    result = runner.run(
        ScheduledAiBriefRequest(
            market="US",
            schedule_role="local-primary",
            runner_role="local-primary",
            scheduled_tick="0810",
            attempt_id="attempt-chained-entry-report-log",
        )
    )

    assert result.status == "pipeline_failed"
    assert any(":lock:" in key for key in state.releases)
    assert notifier.sent == ["pipeline_failed"]
    assert "entry_report_path=unsafe" in caplog.text
    assert "/tmp/private" not in caplog.text
    assert "/tmp/private" not in str(notifier.late_alerts)


def test_runner_pipeline_failure_log_omits_noted_unsafe_entry_report_path(
    caplog: pytest.LogCaptureFixture,
) -> None:
    class _NotedEntryFailurePipeline(_FakePipeline):
        def run(
            self,
            *,
            market: str,
            session_date: str,
            report_date: str,
            source_provider: str | None,
            model_provider: str,
            dry_run: bool,
            model_deadline_remaining_seconds: float | None = None,
            model_deadline_at: dt.datetime | None = None,
            source_api_url: str | None = None,
            source_provider_chain: tuple[str, ...] | None = None,
        ) -> ScheduledPipelineResult:
            self._record_call(
                market=market,
                session_date=session_date,
                report_date=report_date,
                source_provider=source_provider,
                source_api_url=source_api_url,
                source_provider_chain=source_provider_chain,
                model_provider=model_provider,
                dry_run=dry_run,
            )
            err = RuntimeError("pipeline wrapper")
            err.add_note(
                "\x00scheduled entry failed "
                "(entry_report_path=/tmp/private/from-note.entry.json)\x00"
            )
            raise err

    runner, state, _pipeline, _storage, notifier = _runner(
        pipeline=_NotedEntryFailurePipeline()
    )
    caplog.set_level("ERROR", logger="sab.scheduler.runner")

    result = runner.run(
        ScheduledAiBriefRequest(
            market="US",
            schedule_role="local-primary",
            runner_role="local-primary",
            scheduled_tick="0810",
            attempt_id="attempt-noted-entry-report-log",
        )
    )

    assert result.status == "pipeline_failed"
    assert any(":lock:" in key for key in state.releases)
    assert notifier.sent == ["pipeline_failed"]
    assert "entry_report_path=unsafe" in caplog.text
    assert "/tmp/private" not in caplog.text
    assert "/tmp/private" not in str(notifier.late_alerts)


def test_runner_pipeline_failure_log_preserves_quoted_scheduled_entry_phrase(
    caplog: pytest.LogCaptureFixture,
) -> None:
    failure_message = (
        "ai-brief parse failed while reading text: scheduled entry failed "
        "(entry_report_path=reports/current.entry.json)"
    )
    runner, state, _pipeline, _storage, notifier = _runner(
        pipeline=_FakePipeline(fail=True, failure_message=failure_message)
    )
    caplog.set_level("ERROR", logger="sab.scheduler.runner")

    result = runner.run(
        ScheduledAiBriefRequest(
            market="US",
            schedule_role="local-primary",
            runner_role="local-primary",
            scheduled_tick="0810",
            attempt_id="attempt-quoted-entry-report-token",
        )
    )

    assert result.status == "pipeline_failed"
    assert any(":lock:" in key for key in state.releases)
    assert notifier.sent == ["pipeline_failed"]
    assert failure_message in caplog.text
    assert "error=scheduled entry failed" not in caplog.text
    context = notifier.late_alerts[0][1]
    assert "failureDetail" not in context
    assert "entryReportPath" not in context


@pytest.mark.parametrize(
    "failure_message",
    [
        "\nscheduled entry failed (entry_report_path=reports/current.entry.json)\n",
        "\rscheduled entry failed (entry_report_path=reports/current.entry.json)\r",
    ],
)
def test_pipeline_failure_late_alert_includes_boundary_wrapped_scheduled_entry_detail(
    failure_message: str,
) -> None:
    runner, state, _pipeline, _storage, notifier = _runner(
        pipeline=_FakePipeline(fail=True, failure_message=failure_message)
    )

    result = runner.run(
        ScheduledAiBriefRequest(
            market="US",
            schedule_role="local-primary",
            runner_role="local-primary",
            scheduled_tick="0810",
            attempt_id="attempt-entry-non-exact-wrapper",
        )
    )

    assert result.status == "pipeline_failed"
    assert any(":lock:" in key for key in state.releases)
    expected_context = {
        "market": "US",
        "sessionDate": "2026-05-28",
        "attemptId": "attempt-entry-non-exact-wrapper",
        "scheduleRole": "local-primary",
        "runnerRole": "local-primary",
    }
    assert notifier.late_alerts == [("pipeline_failed", expected_context)]
    sent_payloads = [
        payload
        for key, payload in state.upserts
        if ":late-alert:sent:US:2026-05-28:pipeline_failed" in key
    ]
    assert sent_payloads == [{**expected_context, "reason": "pipeline_failed"}]


def test_pipeline_failure_late_alert_includes_entry_not_produced_detail() -> None:
    runner, state, _pipeline, _storage, notifier = _runner(
        pipeline=_TypedEntryFailurePipeline(entry_report_path="not produced")
    )

    result = runner.run(
        ScheduledAiBriefRequest(
            market="US",
            schedule_role="local-primary",
            runner_role="local-primary",
            scheduled_tick="0810",
            attempt_id="attempt-entry-not-produced",
        )
    )

    assert result.status == "pipeline_failed"
    assert any(":lock:" in key for key in state.releases)
    expected_context = {
        "market": "US",
        "sessionDate": "2026-05-28",
        "attemptId": "attempt-entry-not-produced",
        "scheduleRole": "local-primary",
        "runnerRole": "local-primary",
        "failureDetail": "scheduled entry failed",
        "entryReportPath": "not produced",
    }
    assert notifier.late_alerts == [("scheduled_entry_failed", expected_context)]
    sent_payloads = [
        payload
        for key, payload in state.upserts
        if ":late-alert:sent:US:2026-05-28:scheduled_entry_failed" in key
    ]
    assert sent_payloads == [{**expected_context, "reason": "scheduled_entry_failed"}]


def test_pipeline_failure_late_alert_includes_entry_unsafe_detail() -> None:
    runner, state, _pipeline, _storage, notifier = _runner(
        pipeline=_TypedEntryFailurePipeline(entry_report_path="unsafe")
    )

    result = runner.run(
        ScheduledAiBriefRequest(
            market="US",
            schedule_role="local-primary",
            runner_role="local-primary",
            scheduled_tick="0810",
            attempt_id="attempt-entry-unsafe-sentinel",
        )
    )

    assert result.status == "pipeline_failed"
    assert any(":lock:" in key for key in state.releases)
    expected_context = {
        "market": "US",
        "sessionDate": "2026-05-28",
        "attemptId": "attempt-entry-unsafe-sentinel",
        "scheduleRole": "local-primary",
        "runnerRole": "local-primary",
        "failureDetail": "scheduled entry failed",
        "entryReportPath": "unsafe",
    }
    assert notifier.late_alerts == [("scheduled_entry_failed", expected_context)]
    sent_payloads = [
        payload
        for key, payload in state.upserts
        if ":late-alert:sent:US:2026-05-28:scheduled_entry_failed" in key
    ]
    assert sent_payloads == [{**expected_context, "reason": "scheduled_entry_failed"}]


def test_pipeline_failure_late_alert_marker_failure_preserves_pipeline_status() -> None:
    runner, state, _pipeline, _storage, notifier = _runner(
        state=_FakeStateStore(fail_late_alert_sent_upsert=True),
        pipeline=_FakePipeline(fail=True),
    )

    result = runner.run(
        ScheduledAiBriefRequest(
            market="US",
            schedule_role="local-primary",
            runner_role="local-primary",
            scheduled_tick="0810",
            attempt_id="attempt-pipeline-late-marker-fail",
        )
    )

    assert result.status == "pipeline_failed"
    assert any(":lock:" in key for key in state.releases)
    assert notifier.sent == ["pipeline_failed"]
    assert any(":late-alert:claim:" in key for key in state.releases)


def test_locked_pipeline_failure_helper_releases_lock_and_alerts() -> None:
    runner, state, _pipeline, _storage, notifier = _runner()
    lock_key = build_scheduler_state_key(
        kind="lock", market="US", session_date="2026-05-28"
    )

    result = runner._handle_locked_pipeline_failure(
        market="US",
        session_date="2026-05-28",
        attempt_id="attempt-failure-helper",
        lock_key=lock_key,
        owner_token="attempt-failure-helper-owner",
        reason="artifact_marker_failed",
        storage_key="2026/05/2026-05-28.ai-brief.json",
    )

    assert result.status == "artifact_marker_failed"
    assert result.session_date == "2026-05-28"
    assert result.storage_key == "2026/05/2026-05-28.ai-brief.json"
    assert lock_key in state.releases
    assert notifier.sent == ["artifact_marker_failed"]
    assert notifier.late_alerts == [
        (
            "artifact_marker_failed",
            {
                "market": "US",
                "sessionDate": "2026-05-28",
                "attemptId": "attempt-failure-helper",
                "storageKey": "2026/05/2026-05-28.ai-brief.json",
            },
        )
    ]
    sent_payloads = [
        payload
        for key, payload in state.upserts
        if ":late-alert:sent:US:2026-05-28:artifact_marker_failed" in key
    ]
    assert sent_payloads == [
        {
            "market": "US",
            "sessionDate": "2026-05-28",
            "reason": "artifact_marker_failed",
            "attemptId": "attempt-failure-helper",
            "storageKey": "2026/05/2026-05-28.ai-brief.json",
        }
    ]


def test_locked_pipeline_failure_defers_late_alert_after_main_lock_loss() -> None:
    state = _FakeStateStore(ownership_results=[True, False])
    runner, state, _pipeline, _storage, notifier = _runner(state=state)
    lock_key = build_scheduler_state_key(
        kind="lock", market="US", session_date="2026-05-28"
    )

    result = runner._handle_locked_pipeline_failure(
        market="US",
        session_date="2026-05-28",
        attempt_id="attempt-failure-alert-lock-lost",
        lock_key=lock_key,
        owner_token="attempt-failure-alert-lock-lost-owner",
        reason="pipeline_failed",
    )

    assert result.status == "lock_lost_before_upload"
    assert lock_key in state.releases
    assert notifier.sent == []
    assert notifier.late_alerts == []
    assert not any(":late-alert:sent:" in key for key, _payload in state.upserts)


def test_runner_releases_main_lock_when_upload_fails(
    caplog: pytest.LogCaptureFixture,
) -> None:
    runner, state, _pipeline, _storage, notifier = _runner(
        storage=_FakeStorage(fail_upload=True)
    )

    caplog.set_level("ERROR", logger="sab.scheduler.runner")

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
    assert "scheduled AI brief upload failed" in caplog.text
    assert "schedule_role=local-primary" in caplog.text
    assert "runner_role=local-primary" in caplog.text
    assert "attempt_id=attempt-9" in caplog.text
    assert "upload failed" in caplog.text


def test_runner_releases_main_lock_when_artifact_marker_write_fails(
    caplog: pytest.LogCaptureFixture,
) -> None:
    runner, state, _pipeline, storage, notifier = _runner(
        state=_FakeStateStore(fail_artifact_upsert=True)
    )

    caplog.set_level("ERROR", logger="sab.scheduler.runner")

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
    assert "scheduled AI brief artifact marker failed" in caplog.text
    assert "schedule_role=local-primary" in caplog.text
    assert "runner_role=local-primary" in caplog.text
    assert "attempt_id=attempt-artifact-marker-fail" in caplog.text
    assert "storage_key=2026/05/2026-05-28.ai-brief.json" in caplog.text
    assert "artifact write failed" in caplog.text


def test_invalid_artifact_marker_is_failed_scheduler_status() -> None:
    assert "artifact_marker_invalid" in scheduler_runner._FAILED_STATUSES


def test_default_pipeline_scan_step_helper_returns_single_buy_report(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("HOLDINGS_FILE", "holdings.yaml")
    observed_kwargs: list[dict[str, object]] = []

    def fake_run_scan(**kwargs: object) -> int:
        load_dotenv_if_available()
        assert getenv("HOLDINGS_FILE") is None
        assert os.getenv("HOLDINGS_FILE") == "holdings.yaml"
        observed_kwargs.append(dict(kwargs))
        callback = kwargs.get("report_path_callback")
        if callable(callback):
            callback("reports/current.buy.json")
        return 0

    monkeypatch.setattr("sab.scheduler.runner.run_scan", fake_run_scan)

    assert hasattr(DefaultScheduledPipeline(), "_run_scan_step")
    result = DefaultScheduledPipeline()._run_scan_step(
        market="US",
        report_date="2026-05-28",
    )

    assert result == "reports/current.buy.json"
    assert len(observed_kwargs) == 1
    scan_kwargs = observed_kwargs[0]
    callback = scan_kwargs.pop("report_path_callback")
    assert callable(callback)
    assert scan_kwargs == {
        "limit": None,
        "watchlist_path": None,
        "provider": "kis",
        "universe": "both",
        "markets": "US",
    }
    assert os.getenv("HOLDINGS_FILE") == "holdings.yaml"


def test_default_pipeline_holdings_export_step_helper_writes_snapshot(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    export_config = object()
    exported: list[dict[str, object]] = []

    monkeypatch.setattr(
        "sab.scheduler.runner.SupabaseHoldingsExportConfig.from_env",
        lambda: export_config,
    )

    def fake_export_active_holdings_snapshot(**kwargs: object) -> int:
        exported.append(dict(kwargs))
        return 1

    monkeypatch.setattr(
        "sab.scheduler.runner.export_active_holdings_snapshot",
        fake_export_active_holdings_snapshot,
    )

    assert hasattr(DefaultScheduledPipeline(), "_run_holdings_export_step")
    result = DefaultScheduledPipeline()._run_holdings_export_step(
        market="US",
        report_date="2026-05-28",
    )

    expected_path = "data/scheduler/holdings.US.2026-05-28.yaml"
    assert result == expected_path
    assert len(exported) == 1
    assert str(exported[0]["output_path"]) == expected_path
    assert exported[0]["config"] is export_config


def test_default_pipeline_entry_step_helper_returns_single_entry_report(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("HOLDINGS_FILE", "holdings.yaml")
    observed_kwargs: list[dict[str, object]] = []

    def fake_run_entry(**kwargs: object) -> int:
        load_dotenv_if_available()
        assert getenv("HOLDINGS_FILE") is None
        assert os.getenv("HOLDINGS_FILE") == "holdings.yaml"
        observed_kwargs.append(dict(kwargs))
        callback = kwargs.get("report_path_callback")
        if callable(callback):
            callback("reports/current.entry.json")
        return 0

    monkeypatch.setattr("sab.scheduler.runner.run_entry", fake_run_entry)

    assert hasattr(DefaultScheduledPipeline(), "_run_entry_step")
    result = DefaultScheduledPipeline()._run_entry_step(
        market="US",
        report_date="2026-05-28",
        buy_report_path="reports/current.buy.json",
        holdings_path="data/scheduler/holdings.US.2026-05-28.yaml",
    )

    assert result == "reports/current.entry.json"
    assert len(observed_kwargs) == 1
    entry_kwargs = observed_kwargs[0]
    callback = entry_kwargs.pop("report_path_callback")
    assert callable(callback)
    assert entry_kwargs == {
        "buy_report_path": "reports/current.buy.json",
        "provider": "kis",
        "mode": "PRE_OPEN",
        "market": "US",
        "holdings_path": "data/scheduler/holdings.US.2026-05-28.yaml",
        "upload": False,
    }
    assert os.getenv("HOLDINGS_FILE") == "holdings.yaml"


def test_default_pipeline_entry_step_failure_mentions_written_entry_report(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fake_run_entry(**kwargs: object) -> int:
        callback = kwargs.get("report_path_callback")
        if callable(callback):
            callback("reports/current.entry.json")
        return 1

    monkeypatch.setattr("sab.scheduler.runner.run_entry", fake_run_entry)

    with pytest.raises(
        RuntimeError,
        match=r"scheduled entry failed.*reports/current\.entry\.json",
    ):
        DefaultScheduledPipeline()._run_entry_step(
            market="US",
            report_date="2026-05-28",
            buy_report_path="reports/current.buy.json",
            holdings_path="data/scheduler/holdings.US.2026-05-28.yaml",
        )


def test_default_pipeline_entry_step_failure_mentions_last_written_entry_report(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fake_run_entry(**kwargs: object) -> int:
        callback = kwargs.get("report_path_callback")
        if callable(callback):
            callback("reports/stale.entry.json")
            callback("reports/current.entry.json")
        return 1

    monkeypatch.setattr("sab.scheduler.runner.run_entry", fake_run_entry)

    with pytest.raises(RuntimeError) as exc:
        DefaultScheduledPipeline()._run_entry_step(
            market="US",
            report_date="2026-05-28",
            buy_report_path="reports/current.buy.json",
            holdings_path="data/scheduler/holdings.US.2026-05-28.yaml",
        )

    assert "scheduled entry failed" in str(exc.value)
    assert "entry_report_path=reports/current.entry.json" in str(exc.value)
    assert "reports/stale.entry.json" not in str(exc.value)


def test_default_pipeline_entry_step_failure_omits_unsafe_entry_report_path(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fake_run_entry(**kwargs: object) -> int:
        callback = kwargs.get("report_path_callback")
        if callable(callback):
            callback("/tmp/private/current.entry.json")
        return 1

    monkeypatch.setattr("sab.scheduler.runner.run_entry", fake_run_entry)

    with pytest.raises(RuntimeError) as exc:
        DefaultScheduledPipeline()._run_entry_step(
            market="US",
            report_date="2026-05-28",
            buy_report_path="reports/current.buy.json",
            holdings_path="data/scheduler/holdings.US.2026-05-28.yaml",
        )

    assert "scheduled entry failed" in str(exc.value)
    assert "entry_report_path=unsafe" in str(exc.value)
    assert "/tmp/private" not in str(exc.value)


def test_runner_pipeline_failure_log_omits_unsafe_entry_report_path(
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    def fake_run_scan(**kwargs: object) -> int:
        callback = kwargs.get("report_path_callback")
        if callable(callback):
            callback("reports/current.buy.json")
        return 0

    def fake_run_entry(**kwargs: object) -> int:
        callback = kwargs.get("report_path_callback")
        if callable(callback):
            callback("/tmp/private/current.entry.json")
        return 1

    monkeypatch.setattr("sab.scheduler.runner.run_scan", fake_run_scan)
    monkeypatch.setattr("sab.scheduler.runner.run_entry", fake_run_entry)
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
        lambda _market, _now: _guard(session_state="PRE_OPEN"),
    )
    state = _FakeStateStore()
    notifier = _FakeNotifier()
    runner = ScheduledAiBriefRunner(
        state_store=state,
        pipeline=DefaultScheduledPipeline(),
        storage=_FakeStorage(),
        notifier=notifier,
        now_fn=lambda: dt.datetime(2026, 5, 28, 12, 10, tzinfo=dt.UTC),
        guard_resolver=lambda _market, _now: _guard(),
    )
    caplog.set_level("ERROR", logger="sab.scheduler.runner")

    result = runner.run(
        ScheduledAiBriefRequest(
            market="US",
            schedule_role="local-primary",
            runner_role="local-primary",
            scheduled_tick="0810",
            attempt_id="attempt-entry-unsafe-log",
        )
    )

    assert result.status == "pipeline_failed"
    assert any(":lock:" in key for key in state.releases)
    assert notifier.sent == ["scheduled_entry_failed"]
    expected_context = {
        "market": "US",
        "sessionDate": "2026-05-28",
        "attemptId": "attempt-entry-unsafe-log",
        "scheduleRole": "local-primary",
        "runnerRole": "local-primary",
        "failureDetail": "scheduled entry failed",
        "entryReportPath": "unsafe",
    }
    assert notifier.late_alerts == [("scheduled_entry_failed", expected_context)]
    sent_payloads = [
        payload
        for key, payload in state.upserts
        if ":late-alert:sent:US:2026-05-28:scheduled_entry_failed" in key
    ]
    assert sent_payloads == [{**expected_context, "reason": "scheduled_entry_failed"}]
    assert "entry_report_path=unsafe" in caplog.text
    assert "/tmp/private" not in caplog.text
    assert "/tmp/private" not in str(notifier.late_alerts)
    assert "/tmp/private" not in str(sent_payloads)


def test_default_pipeline_entry_step_failure_mentions_not_produced_without_report(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fake_run_entry(**_kwargs: object) -> int:
        return 1

    monkeypatch.setattr("sab.scheduler.runner.run_entry", fake_run_entry)

    with pytest.raises(
        RuntimeError,
        match=r"scheduled entry failed \(entry_report_path=not produced\)",
    ):
        DefaultScheduledPipeline()._run_entry_step(
            market="US",
            report_date="2026-05-28",
            buy_report_path="reports/current.buy.json",
            holdings_path="data/scheduler/holdings.US.2026-05-28.yaml",
        )


def test_default_pipeline_rechecks_pre_open_guard_before_entry(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    entry_calls: list[str] = []

    def fake_run_scan(**kwargs: object) -> int:
        callback = kwargs.get("report_path_callback")
        if callable(callback):
            callback("reports/2026-05-28.buy.json")
        return 0

    monkeypatch.setattr("sab.scheduler.runner.run_scan", fake_run_scan)
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


def test_default_pipeline_uses_report_paths_returned_by_each_step(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("HOLDINGS_FILE", raising=False)
    entry_buy_paths: list[str] = []
    entry_holdings_paths: list[str] = []
    exported_paths: list[str] = []
    ai_brief_inputs: list[dict[str, object]] = []

    def fake_run_scan(**kwargs: object) -> int:
        callback = kwargs.get("report_path_callback")
        if callable(callback):
            callback("reports/current.buy.json")
        return 0

    def fake_export_active_holdings_snapshot(**kwargs: object) -> int:
        exported_paths.append(str(kwargs["output_path"]))
        return 1

    def fake_run_entry(**kwargs: object) -> int:
        assert os.getenv("HOLDINGS_FILE") is None
        entry_buy_paths.append(str(kwargs["buy_report_path"]))
        entry_holdings_paths.append(str(kwargs["holdings_path"]))
        callback = kwargs.get("report_path_callback")
        if callable(callback):
            callback("reports/current.entry.json")
        return 0

    def fake_run_ai_brief(**kwargs: object) -> int:
        ai_brief_inputs.append(dict(kwargs))
        callback = kwargs.get("report_path_callback")
        if callable(callback):
            callback("reports/current.ai-brief.json")
        return 0

    monkeypatch.setattr("sab.scheduler.runner.run_scan", fake_run_scan)
    monkeypatch.setattr("sab.scheduler.runner.run_entry", fake_run_entry)
    monkeypatch.setattr("sab.scheduler.runner.run_ai_brief", fake_run_ai_brief)
    monkeypatch.setattr(
        "sab.scheduler.runner._latest_report",
        lambda _report_dir, suffix: f"reports/stale.{suffix}.json",
        raising=False,
    )
    monkeypatch.setattr(
        "sab.scheduler.runner.SupabaseHoldingsExportConfig.from_env",
        lambda: object(),
    )
    monkeypatch.setattr(
        "sab.scheduler.runner.export_active_holdings_snapshot",
        fake_export_active_holdings_snapshot,
    )
    monkeypatch.setattr(
        "sab.scheduler.runner._default_guard_snapshot",
        lambda _market, _now: _guard(session_state="PRE_OPEN"),
    )

    result = DefaultScheduledPipeline().run(
        market="US",
        session_date="2026-05-28",
        report_date="2026-05-28",
        source_provider=None,
        source_provider_chain=("finnhub", "benzinga-news"),
        model_provider="fake",
        dry_run=False,
        model_deadline_remaining_seconds=1200.0,
        model_deadline_at=dt.datetime(2026, 5, 28, 12, 30, tzinfo=dt.UTC),
    )

    expected_holdings_path = "data/scheduler/holdings.US.2026-05-28.yaml"
    assert exported_paths == [expected_holdings_path]
    assert entry_buy_paths == ["reports/current.buy.json"]
    assert entry_holdings_paths == [expected_holdings_path]
    assert ai_brief_inputs[0]["buy_report_path"] == "reports/current.buy.json"
    assert ai_brief_inputs[0]["entry_report_path"] == "reports/current.entry.json"
    assert ai_brief_inputs[0]["source_provider"] is None
    assert ai_brief_inputs[0]["source_provider_chain"] == "finnhub,benzinga-news"
    assert ai_brief_inputs[0]["model_deadline_remaining_seconds"] == 1200.0
    assert ai_brief_inputs[0]["model_deadline_at"] == dt.datetime(
        2026, 5, 28, 12, 30, tzinfo=dt.UTC
    )
    assert result.ai_brief_report_path == "reports/current.ai-brief.json"


def test_default_pipeline_raises_when_ai_brief_quality_gate_fails(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    eval_calls: list[dict[str, object]] = []

    def fake_run_scan(**kwargs: object) -> int:
        callback = kwargs.get("report_path_callback")
        if callable(callback):
            callback("reports/current.buy.json")
        return 0

    def fake_run_entry(**kwargs: object) -> int:
        callback = kwargs.get("report_path_callback")
        if callable(callback):
            callback("reports/current.entry.json")
        return 0

    def fake_run_ai_brief(**kwargs: object) -> int:
        callback = kwargs.get("report_path_callback")
        if callable(callback):
            callback("reports/current.ai-brief.json")
        return 0

    def fake_evaluate_ai_brief_recommendation_report(
        **kwargs: object,
    ) -> SimpleNamespace:
        eval_calls.append(dict(kwargs))
        return SimpleNamespace(
            status="FAIL",
            issues=[
                SimpleNamespace(
                    code="reported_system_error",
                    message="AI brief reported a model provider error",
                )
            ],
        )

    monkeypatch.setattr("sab.scheduler.runner.run_scan", fake_run_scan)
    monkeypatch.setattr("sab.scheduler.runner.run_entry", fake_run_entry)
    monkeypatch.setattr("sab.scheduler.runner.run_ai_brief", fake_run_ai_brief)
    monkeypatch.setattr(
        "sab.scheduler.runner.evaluate_ai_brief_recommendation_report",
        fake_evaluate_ai_brief_recommendation_report,
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
        lambda _market, _now: _guard(session_state="PRE_OPEN"),
    )

    with pytest.raises(RuntimeError, match="quality gate failed"):
        DefaultScheduledPipeline().run(
            market="US",
            session_date="2026-05-28",
            report_date="2026-05-28",
            source_provider=None,
            model_provider="fake",
            dry_run=False,
        )

    assert eval_calls == [
        {
            "entry_report_path": "reports/current.entry.json",
            "ai_brief_report_path": "reports/current.ai-brief.json",
            "market": "US",
        }
    ]


def test_default_pipeline_returns_result_when_ai_brief_quality_warns(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fake_run_scan(**kwargs: object) -> int:
        callback = kwargs.get("report_path_callback")
        if callable(callback):
            callback("reports/current.buy.json")
        return 0

    def fake_run_entry(**kwargs: object) -> int:
        callback = kwargs.get("report_path_callback")
        if callable(callback):
            callback("reports/current.entry.json")
        return 0

    def fake_run_ai_brief(**kwargs: object) -> int:
        callback = kwargs.get("report_path_callback")
        if callable(callback):
            callback("reports/current.ai-brief.json")
        return 0

    def fake_evaluate_ai_brief_recommendation_report(
        **kwargs: object,
    ) -> SimpleNamespace:
        return SimpleNamespace(
            status="WARN",
            issues=[
                SimpleNamespace(
                    code="ai_brief_source_issue_reported",
                    message="watch source ref fallback was used",
                )
            ],
        )

    monkeypatch.setattr("sab.scheduler.runner.run_scan", fake_run_scan)
    monkeypatch.setattr("sab.scheduler.runner.run_entry", fake_run_entry)
    monkeypatch.setattr("sab.scheduler.runner.run_ai_brief", fake_run_ai_brief)
    monkeypatch.setattr(
        "sab.scheduler.runner.evaluate_ai_brief_recommendation_report",
        fake_evaluate_ai_brief_recommendation_report,
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
        lambda _market, _now: _guard(session_state="PRE_OPEN"),
    )

    result = DefaultScheduledPipeline().run(
        market="US",
        session_date="2026-05-28",
        report_date="2026-05-28",
        source_provider=None,
        model_provider="fake",
        dry_run=False,
    )

    assert result.ai_brief_report_path == "reports/current.ai-brief.json"


def test_default_pipeline_suppresses_ambient_github_actions_report_uploads(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("GITHUB_ACTIONS", "true")
    monkeypatch.setenv("SUPABASE_URL", "https://example.supabase.co")
    monkeypatch.setenv("SUPABASE_SECRET_KEY", "test-secret")
    upload_calls: list[str] = []

    def fake_upload_report_artifact(**kwargs: object) -> str:
        run_type = str(kwargs["run_type"])
        upload_calls.append(run_type)
        return f"2026/05/2026-05-28.{run_type}.json"

    def maybe_upload_from_step(*, artifact_path: str, run_type: str) -> None:
        from sab.report.supabase_storage import maybe_upload_report_artifact

        maybe_upload_report_artifact(
            artifact_path=artifact_path,
            run_type=run_type,
            logger=logging.getLogger(__name__),
        )

    def fake_run_scan(**kwargs: object) -> int:
        callback = kwargs.get("report_path_callback")
        if callable(callback):
            callback("reports/2026-05-28.buy.json")
        maybe_upload_from_step(
            artifact_path="reports/2026-05-28.buy.json",
            run_type="buy",
        )
        return 0

    def fake_run_entry(**kwargs: object) -> int:
        callback = kwargs.get("report_path_callback")
        if callable(callback):
            callback("reports/2026-05-28.entry.json")
        maybe_upload_from_step(
            artifact_path="reports/2026-05-28.entry.json",
            run_type="entry",
        )
        return 0

    def fake_run_ai_brief(**kwargs: object) -> int:
        callback = kwargs.get("report_path_callback")
        if callable(callback):
            callback("reports/2026-05-28.ai-brief.json")
        maybe_upload_from_step(
            artifact_path="reports/2026-05-28.ai-brief.json",
            run_type="ai-brief",
        )
        return 0

    monkeypatch.setattr(
        "sab.report.supabase_storage.upload_report_artifact",
        fake_upload_report_artifact,
    )
    monkeypatch.setattr("sab.scheduler.runner.run_scan", fake_run_scan)
    monkeypatch.setattr("sab.scheduler.runner.run_entry", fake_run_entry)
    monkeypatch.setattr("sab.scheduler.runner.run_ai_brief", fake_run_ai_brief)
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
        lambda _market, _now: _guard(session_state="PRE_OPEN"),
    )

    result = DefaultScheduledPipeline().run(
        market="US",
        session_date="2026-05-28",
        report_date="2026-05-28",
        source_provider=None,
        model_provider="fake",
        dry_run=False,
    )

    assert result.ai_brief_report_path == "reports/2026-05-28.ai-brief.json"
    assert upload_calls == []


def test_default_pipeline_ignores_ambient_holdings_file_env(
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.chdir(tmp_path)
    (tmp_path / ".env").write_text(
        "HOLDINGS_FILE=from-dotenv.yaml\nKIS_BASE_URL=https://dotenv.example.invalid\n",
        encoding="utf-8",
    )
    monkeypatch.setattr("sab.env_loader._load_with_python_dotenv", lambda **_: False)
    monkeypatch.delenv("SAB_CONFIG", raising=False)
    monkeypatch.setenv("HOLDINGS_FILE", "holdings.yaml")
    monkeypatch.setenv("KIS_BASE_URL", "https://ambient.example.invalid")
    observed_steps: list[str] = []

    def fake_run_scan(**kwargs: object) -> int:
        load_dotenv_if_available()
        assert getenv("HOLDINGS_FILE") is None
        assert getenv("KIS_BASE_URL") == "https://ambient.example.invalid"
        assert os.getenv("HOLDINGS_FILE") == "holdings.yaml"
        assert os.getenv("KIS_BASE_URL") == "https://ambient.example.invalid"
        assert load_config().kis_base_url == "https://ambient.example.invalid:9443"
        observed_steps.append("scan")
        callback = kwargs.get("report_path_callback")
        if callable(callback):
            callback("reports/current.buy.json")
        return 0

    def fake_run_entry(**kwargs: object) -> int:
        load_dotenv_if_available()
        assert getenv("HOLDINGS_FILE") is None
        assert getenv("KIS_BASE_URL") == "https://ambient.example.invalid"
        assert os.getenv("HOLDINGS_FILE") == "holdings.yaml"
        assert os.getenv("KIS_BASE_URL") == "https://ambient.example.invalid"
        observed_steps.append("entry")
        assert kwargs["holdings_path"] == "data/scheduler/holdings.US.2026-05-28.yaml"
        callback = kwargs.get("report_path_callback")
        if callable(callback):
            callback("reports/current.entry.json")
        return 0

    def fake_run_ai_brief(**kwargs: object) -> int:
        load_dotenv_if_available()
        assert getenv("HOLDINGS_FILE") is None
        assert getenv("KIS_BASE_URL") == "https://ambient.example.invalid"
        assert os.getenv("HOLDINGS_FILE") == "holdings.yaml"
        assert os.getenv("KIS_BASE_URL") == "https://ambient.example.invalid"
        observed_steps.append("ai-brief")
        callback = kwargs.get("report_path_callback")
        if callable(callback):
            callback("reports/current.ai-brief.json")
        return 0

    monkeypatch.setattr("sab.scheduler.runner.run_scan", fake_run_scan)
    monkeypatch.setattr("sab.scheduler.runner.run_entry", fake_run_entry)
    monkeypatch.setattr("sab.scheduler.runner.run_ai_brief", fake_run_ai_brief)
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
        lambda _market, _now: _guard(session_state="PRE_OPEN"),
    )

    result = DefaultScheduledPipeline().run(
        market="US",
        session_date="2026-05-28",
        report_date="2026-05-28",
        source_provider=None,
        model_provider="fake",
        dry_run=False,
    )

    assert observed_steps == ["scan", "entry", "ai-brief"]
    assert result.ai_brief_report_path == "reports/current.ai-brief.json"
    assert os.getenv("HOLDINGS_FILE") == "holdings.yaml"
    assert os.getenv("KIS_BASE_URL") == "https://ambient.example.invalid"


def test_default_pipeline_does_not_mask_kis_base_url_config_conflict(
    tmp_path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(tmp_path)
    (tmp_path / "config.yaml").write_text(
        "kis:\n  base_url: https://yaml.example.invalid\n",
        encoding="utf-8",
    )
    monkeypatch.delenv("SAB_CONFIG", raising=False)
    monkeypatch.setenv("KIS_BASE_URL", "https://ambient.example.invalid")

    def fake_run_scan(**_kwargs: object) -> int:
        load_config()
        return 0

    monkeypatch.setattr("sab.scheduler.runner.run_scan", fake_run_scan)

    with pytest.raises(ConfigLoadError, match="KIS_BASE_URL"):
        DefaultScheduledPipeline()._run_scan_step(
            market="US",
            report_date="2026-05-28",
        )


def test_default_pipeline_logs_stage_boundaries(
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    def fake_run_scan(**kwargs: object) -> int:
        callback = kwargs.get("report_path_callback")
        if callable(callback):
            callback("reports/current.buy.json")
        return 0

    def fake_run_entry(**kwargs: object) -> int:
        callback = kwargs.get("report_path_callback")
        if callable(callback):
            callback("reports/current.entry.json")
        return 0

    def fake_run_ai_brief(**kwargs: object) -> int:
        callback = kwargs.get("report_path_callback")
        if callable(callback):
            callback("reports/current.ai-brief.json")
        return 0

    monkeypatch.setattr("sab.scheduler.runner.run_scan", fake_run_scan)
    monkeypatch.setattr("sab.scheduler.runner.run_entry", fake_run_entry)
    monkeypatch.setattr("sab.scheduler.runner.run_ai_brief", fake_run_ai_brief)
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
        lambda _market, _now: _guard(session_state="PRE_OPEN"),
    )
    caplog.set_level("INFO", logger="sab.scheduler.runner")

    DefaultScheduledPipeline().run(
        market="US",
        session_date="2026-05-28",
        report_date="2026-05-28",
        source_provider="finnhub",
        model_provider="fake",
        dry_run=False,
    )

    assert "step=scan market=US report_date=2026-05-28" in caplog.text
    assert "step=holdings_export market=US report_date=2026-05-28" in caplog.text
    assert "step=entry market=US report_date=2026-05-28" in caplog.text
    assert "step=ai_brief market=US report_date=2026-05-28" in caplog.text
    assert "report_path=reports/current.ai-brief.json" in caplog.text


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
            scheduled_tick="0830" if runner_role == "monitor-only" else "0929",
            attempt_id="attempt-non-trading",
        )
    )

    assert result.status == "guard_noop"
    assert pipeline.calls == []
    assert storage.uploads == []
    assert notifier.sent == []
    assert not any(":late-alert:" in key for key in state.claims)


def test_pipeline_runner_persists_non_trading_guard_skip_artifact() -> None:
    runner, state, pipeline, storage, notifier = _runner(
        guard=_guard(trading_session=False, session_date="2026-05-25"),
    )

    result = runner.run(
        ScheduledAiBriefRequest(
            market="US",
            schedule_role="local-primary",
            runner_role="local-primary",
            scheduled_tick="0810",
            attempt_id="attempt-non-trading-artifact",
            run_url="https://github.com/owner/repo/actions/runs/1",
        )
    )

    assert result.status == "guard_noop"
    assert result.storage_key == "2026/05/2026-05-25.ai-brief-skip.json"
    assert pipeline.calls == []
    assert storage.uploads == []
    assert len(storage.skip_uploads) == 1
    assert storage.skip_uploads[0].endswith(".ai-brief-skip.json")
    assert any(":skip-artifact:US:2026-05-25" in key for key, _payload in state.upserts)
    assert any(":skip-artifact:claim:US:2026-05-25" in key for key in state.claims)
    assert notifier.sent == []


def test_non_trading_guard_helper_skips_report_index_repair() -> None:
    storage = _FakeStorage()
    storage.repair_candidates = ["2026/05/2026-05-25.ai-brief.json"]
    runner, state, pipeline, storage, notifier = _runner(storage=storage)
    guard = _guard(trading_session=False, session_date="2026-05-25")

    result = runner._handle_non_trading_guard(
        market="US",
        session_date="2026-05-25",
        schedule_role="local-primary",
        runner_role="local-primary",
        attempt_id="attempt-non-trading-helper",
        guard=guard,
        run_url="https://github.com/owner/repo/actions/runs/1",
    )

    assert result.status == "guard_noop"
    assert result.storage_key == "2026/05/2026-05-25.ai-brief-skip.json"
    assert pipeline.calls == []
    assert storage.downloads == []
    assert len(storage.skip_uploads) == 1
    assert any(":skip-artifact:US:2026-05-25" in key for key, _payload in state.upserts)
    assert notifier.sent == []


def test_pipeline_runner_reuses_existing_non_trading_guard_skip_artifact() -> None:
    skip_key = build_scheduler_state_key(
        kind="skip-artifact", market="US", session_date="2026-05-25"
    )
    runner, _state, pipeline, storage, notifier = _runner(
        state=_FakeStateStore(
            entries={
                skip_key: RuntimeStateEntry(
                    state_key=skip_key,
                    state_payload={
                        "storageKey": "2026/05/2026-05-25.ai-brief-skip.json"
                    },
                    expires_at="2026-05-27T00:00:00Z",
                )
            }
        ),
        guard=_guard(trading_session=False, session_date="2026-05-25"),
    )

    result = runner.run(
        ScheduledAiBriefRequest(
            market="US",
            schedule_role="local-primary",
            runner_role="local-primary",
            scheduled_tick="0810",
            attempt_id="attempt-non-trading-artifact-reuse",
        )
    )

    assert result.status == "guard_noop"
    assert result.storage_key == "2026/05/2026-05-25.ai-brief-skip.json"
    assert pipeline.calls == []
    assert storage.skip_uploads == []
    assert notifier.sent == []


def test_pipeline_runner_does_not_write_skip_after_success_marker() -> None:
    success_key = build_scheduler_state_key(
        kind="success", market="US", session_date="2026-05-25"
    )
    runner, _state, pipeline, storage, notifier = _runner(
        state=_FakeStateStore(
            entries={
                success_key: RuntimeStateEntry(
                    state_key=success_key,
                    state_payload={"market": "US", "sessionDate": "2026-05-25"},
                    expires_at="2026-05-27T00:00:00Z",
                )
            }
        ),
        guard=_guard(trading_session=False, session_date="2026-05-25"),
    )

    result = runner.run(
        ScheduledAiBriefRequest(
            market="US",
            schedule_role="local-primary",
            runner_role="local-primary",
            scheduled_tick="0810",
            attempt_id="attempt-non-trading-success",
        )
    )

    assert result.status == "success_marker_skip"
    assert pipeline.calls == []
    assert storage.skip_uploads == []
    assert notifier.sent == []


def test_pipeline_runner_noops_when_skip_artifact_claim_is_held() -> None:
    runner, _state, pipeline, storage, notifier = _runner(
        state=_FakeStateStore(claim_results=[False]),
        guard=_guard(trading_session=False, session_date="2026-05-25"),
    )

    result = runner.run(
        ScheduledAiBriefRequest(
            market="US",
            schedule_role="local-primary",
            runner_role="local-primary",
            scheduled_tick="0810",
            attempt_id="attempt-non-trading-claim-held",
        )
    )

    assert result.status == "skip_artifact_claim_held"
    assert pipeline.calls == []
    assert storage.skip_uploads == []
    assert notifier.sent == []


def test_pipeline_runner_reports_skip_artifact_upload_failure() -> None:
    runner, _state, pipeline, storage, notifier = _runner(
        guard=_guard(trading_session=False, session_date="2026-05-25"),
    )
    storage.fail_skip_upload = True

    result = runner.run(
        ScheduledAiBriefRequest(
            market="US",
            schedule_role="local-primary",
            runner_role="local-primary",
            scheduled_tick="0810",
            attempt_id="attempt-non-trading-artifact-fail",
        )
    )

    assert result.status == "skip_artifact_upload_failed"
    assert result.storage_key is None
    assert pipeline.calls == []
    assert len(storage.skip_uploads) == 1
    assert notifier.sent == []
    assert "skip_artifact_upload_failed" in scheduler_runner._FAILED_STATUSES
    assert any(":skip-artifact:claim:US:2026-05-25" in key for key in _state.releases)


def test_pipeline_runner_persists_pre_open_guard_failure_artifact() -> None:
    runner, _state, pipeline, storage, notifier = _runner(
        guard=_guard(session_state="INTRADAY"),
    )

    result = runner.run(
        ScheduledAiBriefRequest(
            market="US",
            schedule_role="local-primary",
            runner_role="local-primary",
            scheduled_tick="0810",
            attempt_id="attempt-pre-open-guard-artifact",
            run_url="https://github.com/owner/repo/actions/runs/2",
        )
    )

    assert result.status == "guard_failed"
    assert result.storage_key == "2026/05/2026-05-28.ai-brief-skip.json"
    assert pipeline.calls == []
    assert storage.uploads == []
    assert len(storage.skip_uploads) == 1
    assert "pre_open_guard_failed" in notifier.sent


def test_runtime_guard_skip_result_helper_alerts_when_upload_fails() -> None:
    storage = _FakeStorage(fail_skip_upload=True)
    runner, _state, pipeline, storage, notifier = _runner(storage=storage)
    guard = _guard(session_state="INTRADAY")

    result = runner._persist_runtime_guard_skip_result(
        market="US",
        session_date="2026-05-28",
        guard=guard,
        run_url="https://github.com/owner/repo/actions/runs/2",
        success_status="guard_failed",
        alert_reason="pre_open_guard_failed",
        alert_context=scheduler_runner._guard_context(
            market="US",
            session_date="2026-05-28",
            guard=guard,
        ),
        now=dt.datetime(2026, 5, 28, 12, 10, tzinfo=dt.UTC),
    )

    assert result.status == "skip_artifact_upload_failed"
    assert result.session_date == "2026-05-28"
    assert result.storage_key is None
    assert pipeline.calls == []
    assert storage.uploads == []
    assert len(storage.skip_uploads) == 1
    assert notifier.sent == ["pre_open_guard_failed"]


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
    calls: list[tuple[str, dict[str, object]]] = []

    class _Response:
        status_code = 200

    def fake_post(url: str, **kwargs: object) -> _Response:
        calls.append((url, kwargs))
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

    telegram_call = next(
        (kwargs for url, kwargs in calls if "api.telegram.org" in url),
        None,
    )
    assert telegram_call is not None
    telegram_data = telegram_call.get("data")
    assert isinstance(telegram_data, dict)
    assert telegram_data["parse_mode"] == "HTML"
    assert telegram_data["disable_web_page_preview"] == "true"
    assert any("hooks.slack.com" in url for url, _kwargs in calls)


def test_default_scheduled_notifier_late_alert_stays_plain_text(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[tuple[str, dict[str, object]]] = []

    class _Response:
        status_code = 200

    def fake_post(url: str, **kwargs: object) -> _Response:
        calls.append((url, kwargs))
        return _Response()

    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "token")
    monkeypatch.setenv("TELEGRAM_CHAT_ID", "chat")
    monkeypatch.setattr("sab.scheduler.runner.requests.post", fake_post)

    DefaultScheduledNotifier().send_late_alert(
        reason="docker_failed",
        context={"detail": "plain <text> & safe"},
    )

    telegram_call = next(
        (kwargs for url, kwargs in calls if "api.telegram.org" in url),
        None,
    )
    assert telegram_call is not None
    telegram_data = telegram_call.get("data")
    assert isinstance(telegram_data, dict)
    assert "parse_mode" not in telegram_data
    assert "plain <text> & safe" in str(telegram_data["text"])


def test_build_attempt_id_includes_tick_and_utc_started_at() -> None:
    assert (
        build_attempt_id(
            scheduled_tick="0810",
            started_at=dt.datetime(2026, 5, 28, 12, 10, tzinfo=dt.UTC),
            suffix="pid123",
        )
        == "0810-20260528T121000Z-pid123"
    )


def test_write_scheduled_status_file_writes_status_file(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    status_file = tmp_path / "nested" / "status.json"
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
    assert (
        status_file.read_text(encoding="utf-8")
        == '{"session_date": "2026-06-26", "status": "pipeline_failed", "storage_key": null}\n'
    )


def test_write_status_json_removes_temp_file_on_failure(tmp_path: Path) -> None:
    status_file = tmp_path / "nested" / "status.json"

    with pytest.raises(TypeError):
        scheduler_status_file.write_status_json(status_file, {"status": object()})

    assert not status_file.exists()
    assert list(status_file.parent.glob(f".{status_file.name}.*")) == []


def test_write_scheduled_status_file_noops_without_env(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("SAB_SCHEDULER_STATUS_FILE", raising=False)

    scheduler_runner._write_scheduled_status_file(
        scheduler_runner.ScheduledAiBriefResult(status="dry_run")
    )


def test_run_scheduled_ai_brief_preserves_result_when_status_file_write_fails(
    caplog: pytest.LogCaptureFixture,
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class _FakeRunner:
        def __init__(self, **_kwargs: object) -> None:
            pass

        def run(
            self, _request: scheduler_runner.ScheduledAiBriefRequest
        ) -> scheduler_runner.ScheduledAiBriefResult:
            return scheduler_runner.ScheduledAiBriefResult(
                status="completed",
                session_date="2026-06-26",
                storage_key="reports/x.ai-brief.json",
            )

    monkeypatch.setenv("SAB_SCHEDULER_STATUS_FILE", "/unwritable/status.json")
    monkeypatch.setattr(
        scheduler_runner.SupabaseRuntimeStateClient,
        "from_env",
        staticmethod(lambda: object()),
    )
    monkeypatch.setattr(
        scheduler_runner.DefaultScheduledStorage,
        "from_env",
        staticmethod(lambda: object()),
    )
    monkeypatch.setattr(scheduler_runner, "DefaultScheduledPipeline", object)
    monkeypatch.setattr(scheduler_runner, "DefaultScheduledNotifier", object)
    monkeypatch.setattr(scheduler_runner, "ScheduledAiBriefRunner", _FakeRunner)
    monkeypatch.setattr(
        scheduler_runner.status_file,
        "write_status_json",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(OSError("status denied")),
    )
    caplog.set_level("WARNING", logger="sab.scheduler.runner")

    exit_code = scheduler_runner.run_scheduled_ai_brief(
        request=scheduler_runner.ScheduledAiBriefRequest(
            market="US",
            schedule_role="local-primary",
            runner_role="local-primary",
            scheduled_tick="0810",
        )
    )

    assert exit_code == 0
    assert json.loads(capsys.readouterr().out) == {
        "status": "completed",
        "storage_key": "reports/x.ai-brief.json",
    }
    assert "failed to write scheduled status file: status denied" in caplog.text
