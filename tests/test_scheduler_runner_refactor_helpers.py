from __future__ import annotations

import datetime as dt
from dataclasses import dataclass, field

from sab.scheduler.runner import (
    GuardSnapshot,
    ScheduledAiBriefRequest,
    ScheduledAiBriefRunner,
    ScheduledPipelineResult,
)
from sab.scheduler.state import RuntimeStateEntry, RuntimeStateLockClaim


@dataclass
class _StateStore:
    upserts: list[tuple[str, dict[str, object]]] = field(default_factory=list)
    claims: list[str] = field(default_factory=list)
    releases: list[str] = field(default_factory=list)
    preflight_calls: int = 0

    def preflight(self) -> None:
        self.preflight_calls += 1

    def get_entry(self, key: str) -> RuntimeStateEntry | None:
        return None

    def list_entries(self, *, prefix: str, limit: int = 20) -> list[RuntimeStateEntry]:
        return []

    def upsert_marker(
        self,
        *,
        key: str,
        payload: dict[str, object],
        ttl_seconds: int,
        now: dt.datetime | None = None,
    ) -> None:
        self.upserts.append((key, payload))

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
        return RuntimeStateLockClaim(acquired=True, expires_at="soon")

    def release_lock(self, key: str, *, owner_token: str) -> bool:
        self.releases.append(key)
        return True

    def renew_lock(self, key: str, *, owner_token: str, ttl_seconds: int) -> bool:
        return True

    def check_ownership(self, key: str, *, owner_token: str) -> bool:
        return True


@dataclass
class _Pipeline:
    calls: int = 0

    def run(self, **_kwargs: object) -> ScheduledPipelineResult:
        self.calls += 1
        return ScheduledPipelineResult(
            ai_brief_report_path="reports/2026-05-28.ai-brief.json"
        )


@dataclass
class _Storage:
    uploads: list[str] = field(default_factory=list)
    downloads: list[str] = field(default_factory=list)

    def list_ai_brief_report_index(self, *, report_date: str) -> list[str]:
        return []

    def upload_ai_brief(self, report_path: str, *, report_date: str) -> str:
        self.uploads.append(report_path)
        return "2026/05/2026-05-28.ai-brief.json"

    def upload_entry_report(self, report_path: str, *, report_date: str) -> str:
        raise AssertionError("unsupported runner role must not upload entry artifact")

    def upload_ai_brief_skip(self, report_path: str, *, report_date: str) -> str:
        raise AssertionError("unsupported runner role must not upload skip artifact")

    def download_json(self, storage_key: str) -> dict[str, object]:
        self.downloads.append(storage_key)
        return {
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


@dataclass
class _Notifier:
    schedules: list[tuple[dict[str, object], str]] = field(default_factory=list)
    late_alerts: list[tuple[str, dict[str, object]]] = field(default_factory=list)

    def require_telegram(self) -> None:
        return None

    def send_schedule(self, *, report: dict[str, object], storage_key: str) -> None:
        self.schedules.append((report, storage_key))

    def send_late_alert(self, *, reason: str, context: dict[str, object]) -> None:
        self.late_alerts.append((reason, context))


def test_scheduled_runner_rejects_unsupported_runner_role_before_side_effects() -> None:
    state = _StateStore()
    pipeline = _Pipeline()
    runner = ScheduledAiBriefRunner(
        state_store=state,
        pipeline=pipeline,
        storage=_Storage(),
        notifier=_Notifier(),
        now_fn=lambda: dt.datetime(2026, 5, 28, 12, 10, tzinfo=dt.UTC),
        guard_resolver=lambda _market, _now: GuardSnapshot(
            trading_session=True,
            session_state="PRE_OPEN",
            session_date="2026-05-28",
            local_time="2026-05-28T08:10:00-04:00",
        ),
    )

    result = runner.run(
        ScheduledAiBriefRequest(
            market="US",
            schedule_role="local-primary",
            runner_role="manual",
            scheduled_tick="0810",
            attempt_id="manual-attempt",
        )
    )

    assert result.status == "unsupported_runner_role"
    assert result.session_date == "2026-05-28"
    assert state.preflight_calls == 0
    assert state.upserts == []
    assert state.claims == []
    assert state.releases == []
    assert pipeline.calls == 0
