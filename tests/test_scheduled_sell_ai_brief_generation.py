from __future__ import annotations

import datetime as dt
import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, cast

from sab.scheduler.generic_state import build_scheduled_state_key
from sab.scheduler.sell_ai_brief_delivery import (
    ScheduledSellAiBriefDeliveryRequest,
    ScheduledSellAiBriefDeliveryRunner,
)
from sab.scheduler.sell_ai_brief_generation import (
    ScheduledSellAiBriefGenerationRequest,
    ScheduledSellAiBriefGenerationRunner,
)
from sab.scheduler.state import RuntimeStateEntry, RuntimeStateLockClaim

from tests.test_scheduled_sell_ai_brief_delivery import _sell_ai_brief_report


def _sell_key(kind: str, *, session_date: str = "2026-07-06") -> str:
    return build_scheduled_state_key(
        pipeline="sell",
        kind=kind,
        scope="MIXED",
        session_date=session_date,
    )


def _toss_key(*, session_date: str = "2026-07-06") -> str:
    return f"toss-sync:success:MIXED:{session_date}"


def _request(**overrides: object) -> ScheduledSellAiBriefGenerationRequest:
    values: dict[str, object] = {
        "scope": "MIXED",
        "session_date": "2026-07-06",
        "runner_role": "local-primary",
        "scheduled_tick": "0725",
        "attempt_id": "attempt-1",
    }
    values.update(overrides)
    return ScheduledSellAiBriefGenerationRequest(
        scope=cast(str, values["scope"]),
        session_date=cast(str, values["session_date"]),
        runner_role=cast(str, values["runner_role"]),
        scheduled_tick=cast(str, values["scheduled_tick"]),
        attempt_id=cast(str | None, values.get("attempt_id")),
        run_url=cast(str, values.get("run_url", "")),
        provider=cast(str | None, values.get("provider")),
        model_provider=cast(str | None, values.get("model_provider", "openai")),
        model_name=cast(str | None, values.get("model_name")),
        dry_run=cast(bool, values.get("dry_run", False)),
    )


def _runner(
    *,
    state: _FakeStateStore,
    notifier: _FakeNotifier | None = None,
    storage: _FakeStorage | None = None,
    sell_result: _FakeSellResult | None = None,
    brief_result: _FakeBriefResult | None = None,
    eval_result: _FakeEvalResult | None = None,
    delivery_result: _FakeDeliveryResult | None = None,
    calls: dict[str, list[object]] | None = None,
) -> ScheduledSellAiBriefGenerationRunner:
    call_log = calls if calls is not None else {}

    def _record(name: str, value: object) -> None:
        call_log.setdefault(name, []).append(value)

    def _run_sell(request: ScheduledSellAiBriefGenerationRequest) -> _FakeSellResult:
        _record("sell", request)
        return sell_result or _FakeSellResult(
            exit_code=0,
            report_path="reports/2026-07-06.sell.json",
        )

    def _run_brief(
        request: ScheduledSellAiBriefGenerationRequest,
        sell_report_path: str,
    ) -> _FakeBriefResult:
        _record("brief", (request, sell_report_path))
        return brief_result or _FakeBriefResult(
            exit_code=0,
            report_path="reports/2026-07-06.sell-ai-brief.json",
        )

    def _evaluate(sell_path: str, brief_path: str) -> _FakeEvalResult:
        _record("eval", (sell_path, brief_path))
        return eval_result or _FakeEvalResult(status="PASS")

    def _deliver(request: object) -> _FakeDeliveryResult:
        _record("delivery", request)
        return delivery_result or _FakeDeliveryResult(
            status="completed",
            session_date="2026-07-06",
            storage_key="2026/07/2026-07-06.sell-ai-brief.json",
        )

    return ScheduledSellAiBriefGenerationRunner(
        state_store=state,
        storage=storage or _FakeStorage(),
        notifier=notifier or _FakeNotifier(),
        sell_runner=_run_sell,
        sell_ai_brief_runner=_run_brief,
        evaluator=_evaluate,
        delivery_runner=_deliver,
        now_fn=lambda: dt.datetime(2026, 7, 6, 22, 25, tzinfo=dt.UTC),
    )


@dataclass(frozen=True)
class _FakeSellResult:
    exit_code: int
    report_path: str | None


@dataclass(frozen=True)
class _FakeBriefResult:
    exit_code: int
    report_path: str | None


@dataclass(frozen=True)
class _FakeEvalResult:
    status: str


@dataclass(frozen=True)
class _FakeDeliveryResult:
    status: str
    session_date: str
    storage_key: str | None


@dataclass
class _FakeStateStore:
    entries: dict[str, RuntimeStateEntry] = field(default_factory=dict)
    upserted: list[tuple[str, dict[str, object]]] = field(default_factory=list)
    claims: list[tuple[str, str]] = field(default_factory=list)
    releases: list[tuple[str, str]] = field(default_factory=list)
    renewals: list[tuple[str, str]] = field(default_factory=list)
    renewal_results: list[bool] = field(default_factory=list)
    acquire_lock: bool = True

    def get_entry(self, key: str) -> RuntimeStateEntry | None:
        return self.entries.get(key)

    def upsert_marker(
        self,
        *,
        key: str,
        payload: dict[str, object],
        ttl_seconds: int,
        now: dt.datetime | None = None,
    ) -> None:
        del ttl_seconds, now
        self.upserted.append((key, payload))
        self.entries[key] = RuntimeStateEntry(
            state_key=key,
            state_payload=payload,
            expires_at="2026-07-08T00:00:00Z",
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
        del ttl_seconds, now
        self.claims.append((key, owner_token))
        if not self.acquire_lock:
            return RuntimeStateLockClaim(
                acquired=False,
                expires_at="2026-07-06T23:00:00Z",
            )
        self.entries[key] = RuntimeStateEntry(
            state_key=key,
            state_payload={**(payload or {}), "ownerToken": owner_token},
            expires_at="2026-07-06T23:00:00Z",
        )
        return RuntimeStateLockClaim(acquired=True, expires_at="2026-07-06T23:00:00Z")

    def renew_lock(self, key: str, *, owner_token: str, ttl_seconds: int) -> bool:
        del ttl_seconds
        self.renewals.append((key, owner_token))
        if self.renewal_results:
            return self.renewal_results.pop(0)
        return (
            self.entries.get(key, RuntimeStateEntry(key, {}, "")).state_payload.get(
                "ownerToken"
            )
            == owner_token
        )

    def check_ownership(self, key: str, *, owner_token: str) -> bool:
        return (
            self.entries.get(key, RuntimeStateEntry(key, {}, "")).state_payload.get(
                "ownerToken"
            )
            == owner_token
        )

    def release_lock(self, key: str, *, owner_token: str) -> bool:
        self.releases.append((key, owner_token))
        return True


class _ContentionStateStore(_FakeStateStore):
    def claim_lock(
        self,
        *,
        key: str,
        owner_token: str,
        ttl_seconds: int,
        now: dt.datetime | None = None,
        payload: dict[str, object] | None = None,
    ) -> RuntimeStateLockClaim:
        existing = self.entries.get(key)
        if existing is not None and existing.state_payload.get("ownerToken"):
            self.claims.append((key, owner_token))
            return RuntimeStateLockClaim(acquired=False, expires_at=existing.expires_at)
        return super().claim_lock(
            key=key,
            owner_token=owner_token,
            ttl_seconds=ttl_seconds,
            now=now,
            payload=payload,
        )

    def release_lock(self, key: str, *, owner_token: str) -> bool:
        self.releases.append((key, owner_token))
        if (
            self.entries.get(key) is not None
            and self.entries[key].state_payload.get("ownerToken") == owner_token
        ):
            del self.entries[key]
        return True


@dataclass
class _FakeStorage:
    sell_uploads: list[str] = field(default_factory=list)
    sell_upload_dates: list[str] = field(default_factory=list)
    sell_ai_brief_uploads: list[str] = field(default_factory=list)
    sell_ai_brief_upload_key: str = "2026/07/2026-07-06.sell-ai-brief.json"
    downloads: dict[str, dict[str, Any]] = field(default_factory=dict)

    def upload_sell(self, report_path: str, *, report_date: str) -> str:
        self.sell_uploads.append(report_path)
        self.sell_upload_dates.append(report_date)
        return "2026/07/2026-07-06.sell.json"

    def upload_sell_ai_brief(self, report_path: str, *, report_date: str) -> str:
        del report_date
        self.sell_ai_brief_uploads.append(report_path)
        return self.sell_ai_brief_upload_key

    def download_json(self, storage_key: str) -> dict[str, Any]:
        return self.downloads[storage_key]


@dataclass
class _FakeNotifier:
    blocked: list[dict[str, object]] = field(default_factory=list)
    schedule_sent: list[tuple[str, dict[str, Any]]] = field(default_factory=list)
    on_blocked_send: object | None = None

    def send_blocked(self, *, scope: str, session_date: str, reason: str) -> None:
        if callable(self.on_blocked_send):
            self.on_blocked_send()
        self.blocked.append(
            {"scope": scope, "session_date": session_date, "reason": reason}
        )

    def send_schedule(
        self,
        *,
        report: dict[str, Any],
        storage_key: str,
        text: str,
    ) -> None:
        assert text
        self.schedule_sent.append((storage_key, report))


def test_generation_missing_toss_freshness_sends_blocked_alert_without_success() -> (
    None
):
    state = _FakeStateStore()
    notifier = _FakeNotifier()
    runner = _runner(state=state, notifier=notifier)

    result = runner.run(_request())

    assert result.status == "toss_freshness_missing"
    assert notifier.blocked == [
        {
            "scope": "MIXED",
            "session_date": "2026-07-06",
            "reason": "toss_freshness_missing",
        }
    ]
    assert _sell_key("blocked") in state.entries
    assert _sell_key("notification:blocked-sent") in state.entries
    assert _sell_key("success") not in state.entries
    assert [claim[0] for claim in state.claims] == [
        _sell_key("blocked-notification-lock")
    ]


def test_generation_blocked_alert_uses_claim_to_suppress_concurrent_duplicate() -> None:
    state = _ContentionStateStore()
    nested_notifier = _FakeNotifier()

    def _send_nested_run() -> None:
        nested_runner = _runner(state=state, notifier=nested_notifier)
        nested_result = nested_runner.run(_request(attempt_id="attempt-2"))
        assert nested_result.status == "toss_freshness_missing"

    notifier = _FakeNotifier(on_blocked_send=_send_nested_run)
    runner = _runner(state=state, notifier=notifier)

    result = runner.run(_request())

    assert result.status == "toss_freshness_missing"
    assert len(notifier.blocked) == 1
    assert nested_notifier.blocked == []
    assert _sell_key("notification:blocked-sent") in state.entries


def test_generation_rejects_invalid_toss_freshness_without_generation() -> None:
    state = _FakeStateStore(
        entries={
            _toss_key(): RuntimeStateEntry(
                state_key=_toss_key(),
                state_payload={"status": "error", "sessionDate": "2026-07-06"},
                expires_at="2026-07-07T12:00:00Z",
            )
        }
    )
    notifier = _FakeNotifier()
    runner = _runner(state=state, notifier=notifier)

    result = runner.run(_request())

    assert result.status == "toss_freshness_invalid"
    assert notifier.blocked[0]["reason"] == "toss_freshness_invalid"
    assert _sell_key("blocked") in state.entries
    assert [claim[0] for claim in state.claims] == [
        _sell_key("blocked-notification-lock")
    ]


def test_generation_rejects_stale_toss_freshness_without_generation() -> None:
    state = _FakeStateStore(
        entries={
            _toss_key(): RuntimeStateEntry(
                state_key=_toss_key(),
                state_payload={"status": "applied", "sessionDate": "2026-07-06"},
                expires_at="2026-07-06T00:00:00Z",
            )
        }
    )
    notifier = _FakeNotifier()
    runner = _runner(state=state, notifier=notifier)

    result = runner.run(_request())

    assert result.status == "toss_freshness_stale"
    assert notifier.blocked[0]["reason"] == "toss_freshness_stale"
    assert [claim[0] for claim in state.claims] == [
        _sell_key("blocked-notification-lock")
    ]


def test_generation_blocked_alert_is_sent_once_per_session() -> None:
    state = _FakeStateStore(
        entries={
            _sell_key("notification:blocked-sent"): RuntimeStateEntry(
                state_key=_sell_key("notification:blocked-sent"),
                state_payload={"reason": "toss_freshness_missing"},
                expires_at="2026-07-08T00:00:00Z",
            )
        }
    )
    notifier = _FakeNotifier()
    runner = _runner(state=state, notifier=notifier)

    result = runner.run(_request())

    assert result.status == "toss_freshness_missing"
    assert notifier.blocked == []
    assert _sell_key("success") not in state.entries


def test_generation_success_uploads_sell_then_delegates_brief_delivery() -> None:
    state = _FakeStateStore(
        entries={
            _toss_key(): RuntimeStateEntry(
                state_key=_toss_key(),
                state_payload={"status": "applied", "sessionDate": "2026-07-06"},
                expires_at="2026-07-07T12:00:00Z",
            )
        }
    )
    storage = _FakeStorage()
    calls: dict[str, list[object]] = {}
    runner = _runner(state=state, storage=storage, calls=calls)

    result = runner.run(_request())

    assert result.status == "completed"
    assert result.sell_storage_key == "2026/07/2026-07-06.sell.json"
    assert result.sell_ai_brief_storage_key == ("2026/07/2026-07-06.sell-ai-brief.json")
    assert storage.sell_uploads == ["reports/2026-07-06.sell.json"]
    assert calls["eval"] == [
        ("reports/2026-07-06.sell.json", "reports/2026-07-06.sell-ai-brief.json")
    ]
    assert len(calls["delivery"]) == 1
    delivery_request = cast(ScheduledSellAiBriefDeliveryRequest, calls["delivery"][0])
    assert delivery_request.sell_ai_brief_report_path == (
        "reports/2026-07-06.sell-ai-brief.json"
    )
    generation_payload = state.entries[_sell_key("generation")].state_payload
    assert generation_payload["sellStorageKey"] == "2026/07/2026-07-06.sell.json"
    assert generation_payload["sellAiBriefStorageKey"] == (
        "2026/07/2026-07-06.sell-ai-brief.json"
    )
    assert generation_payload["qualityStatus"] == "PASS"


def test_generation_uses_distinct_lock_when_delegating_to_real_delivery(
    tmp_path: Path,
) -> None:
    brief_path = tmp_path / "2026-07-06.sell-ai-brief.json"
    brief_path.write_text(json.dumps(_sell_ai_brief_report()), encoding="utf-8")
    state = _ContentionStateStore(
        entries={
            _toss_key(): RuntimeStateEntry(
                state_key=_toss_key(),
                state_payload={"status": "applied", "sessionDate": "2026-07-06"},
                expires_at="2026-07-07T12:00:00Z",
            )
        }
    )
    storage = _FakeStorage()
    notifier = _FakeNotifier()
    delivery_notifier = _FakeNotifier()

    runner = ScheduledSellAiBriefGenerationRunner(
        state_store=state,
        storage=storage,
        notifier=notifier,
        sell_runner=lambda request: _FakeSellResult(
            exit_code=0,
            report_path="reports/2026-07-06.sell.json",
        ),
        sell_ai_brief_runner=lambda request, sell_path: _FakeBriefResult(
            exit_code=0,
            report_path=str(brief_path),
        ),
        evaluator=lambda sell_path, brief_path: _FakeEvalResult(status="PASS"),
        delivery_runner=lambda request: ScheduledSellAiBriefDeliveryRunner(
            state_store=state,
            storage=storage,
            notifier=delivery_notifier,
            now_fn=lambda: dt.datetime(2026, 7, 6, 22, 25, tzinfo=dt.UTC),
        ).run(request),
        now_fn=lambda: dt.datetime(2026, 7, 6, 22, 25, tzinfo=dt.UTC),
    )

    result = runner.run(_request())

    assert result.status == "completed"
    assert storage.sell_uploads == ["reports/2026-07-06.sell.json"]
    assert storage.sell_ai_brief_uploads == [str(brief_path)]
    assert delivery_notifier.schedule_sent
    assert _sell_key("success") in state.entries


def test_generation_maps_delegated_delivery_lock_skip_to_failure_status() -> None:
    state = _FakeStateStore(
        entries={
            _toss_key(): RuntimeStateEntry(
                state_key=_toss_key(),
                state_payload={"status": "applied", "sessionDate": "2026-07-06"},
                expires_at="2026-07-07T12:00:00Z",
            )
        }
    )
    runner = _runner(
        state=state,
        delivery_result=_FakeDeliveryResult(
            status="lock_held_skip",
            session_date="2026-07-06",
            storage_key=None,
        ),
    )

    result = runner.run(_request())

    assert result.status == "delivery_lock_held"
    assert _sell_key("generation") not in state.entries


def test_generation_resolves_empty_session_date_before_running_helpers() -> None:
    state = _FakeStateStore(
        entries={
            _toss_key(session_date="2026-07-07"): RuntimeStateEntry(
                state_key=_toss_key(session_date="2026-07-07"),
                state_payload={"status": "applied", "sessionDate": "2026-07-07"},
                expires_at="2026-07-08T12:00:00Z",
            )
        }
    )
    calls: dict[str, list[object]] = {}
    runner = _runner(state=state, calls=calls)

    result = runner.run(_request(session_date=""))

    assert result.status == "completed"
    sell_request = cast(ScheduledSellAiBriefGenerationRequest, calls["sell"][0])
    brief_request, _sell_path = cast(
        tuple[ScheduledSellAiBriefGenerationRequest, str],
        calls["brief"][0],
    )
    assert sell_request.session_date == "2026-07-07"
    assert brief_request.session_date == "2026-07-07"


def test_generation_skips_when_generation_lock_is_held() -> None:
    state = _FakeStateStore(
        entries={
            _toss_key(): RuntimeStateEntry(
                state_key=_toss_key(),
                state_payload={"status": "applied", "sessionDate": "2026-07-06"},
                expires_at="2026-07-07T12:00:00Z",
            )
        },
        acquire_lock=False,
    )
    calls: dict[str, list[object]] = {}
    runner = _runner(state=state, calls=calls)

    result = runner.run(_request())

    assert result.status == "lock_held_skip"
    assert calls == {}


def test_generation_stops_before_upload_when_sell_report_generation_fails() -> None:
    state = _FakeStateStore(
        entries={
            _toss_key(): RuntimeStateEntry(
                state_key=_toss_key(),
                state_payload={"status": "unchanged", "sessionDate": "2026-07-06"},
                expires_at="2026-07-07T12:00:00Z",
            )
        }
    )
    storage = _FakeStorage()
    calls: dict[str, list[object]] = {}
    runner = _runner(
        state=state,
        storage=storage,
        sell_result=_FakeSellResult(exit_code=1, report_path=None),
        calls=calls,
    )

    result = runner.run(_request())

    assert result.status == "sell_report_failed"
    assert storage.sell_uploads == []
    assert "brief" not in calls
    assert "delivery" not in calls


def test_generation_quality_fail_blocks_upload_and_delivery() -> None:
    state = _FakeStateStore(
        entries={
            _toss_key(): RuntimeStateEntry(
                state_key=_toss_key(),
                state_payload={"status": "applied", "sessionDate": "2026-07-06"},
                expires_at="2026-07-07T12:00:00Z",
            )
        }
    )
    storage = _FakeStorage()
    calls: dict[str, list[object]] = {}
    runner = _runner(
        state=state,
        storage=storage,
        eval_result=_FakeEvalResult(status="FAIL"),
        calls=calls,
    )

    result = runner.run(_request())

    assert result.status == "quality_gate_failed"
    assert storage.sell_uploads == []
    assert "delivery" not in calls


def test_generation_warn_delivers_but_marks_review_required() -> None:
    state = _FakeStateStore(
        entries={
            _toss_key(): RuntimeStateEntry(
                state_key=_toss_key(),
                state_payload={"status": "applied", "sessionDate": "2026-07-06"},
                expires_at="2026-07-07T12:00:00Z",
            )
        }
    )
    runner = _runner(state=state, eval_result=_FakeEvalResult(status="WARN"))

    result = runner.run(_request())

    assert result.status == "completed_review_required"
    assert (
        state.entries[_sell_key("review-required")].state_payload["qualityStatus"]
        == "WARN"
    )
    assert _sell_key("success") not in state.entries


def test_generation_renews_lock_across_long_pipeline_before_upload() -> None:
    state = _FakeStateStore(
        entries={
            _toss_key(): RuntimeStateEntry(
                state_key=_toss_key(),
                state_payload={"status": "applied", "sessionDate": "2026-07-06"},
                expires_at="2026-07-07T12:00:00Z",
            )
        }
    )
    storage = _FakeStorage()
    runner = _runner(state=state, storage=storage)

    result = runner.run(_request())

    assert result.status == "completed"
    assert [renewal[0] for renewal in state.renewals] == [
        _sell_key("generation-lock"),
        _sell_key("generation-lock"),
        _sell_key("generation-lock"),
        _sell_key("generation-lock"),
    ]
    assert storage.sell_uploads == ["reports/2026-07-06.sell.json"]


def test_generation_stops_when_lock_renewal_fails_after_sell_report() -> None:
    state = _FakeStateStore(
        entries={
            _toss_key(): RuntimeStateEntry(
                state_key=_toss_key(),
                state_payload={"status": "applied", "sessionDate": "2026-07-06"},
                expires_at="2026-07-07T12:00:00Z",
            )
        },
        renewal_results=[True, False],
    )
    storage = _FakeStorage()
    calls: dict[str, list[object]] = {}
    runner = _runner(state=state, storage=storage, calls=calls)

    result = runner.run(_request())

    assert result.status == "lock_lost_before_upload"
    assert "sell" in calls
    assert "brief" not in calls
    assert storage.sell_uploads == []
