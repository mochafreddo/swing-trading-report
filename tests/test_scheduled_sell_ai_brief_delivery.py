from __future__ import annotations

import datetime as dt
import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import pytest
import sab.scheduler.runner as scheduler_runner
from sab.report.supabase_storage import SupabaseStorageConfig
from sab.scheduler.generic_state import build_scheduled_state_key
from sab.scheduler.sell_ai_brief_delivery import (
    ScheduledSellAiBriefDeliveryRequest,
    ScheduledSellAiBriefDeliveryRunner,
)
from sab.scheduler.state import RuntimeStateEntry, RuntimeStateLockClaim


def _key(kind: str, *, scope: str = "MIXED") -> str:
    return build_scheduled_state_key(
        pipeline="sell",
        kind=kind,
        scope=scope,
        session_date="2026-07-06",
    )


def _attempt_key(attempt_id: str) -> str:
    return build_scheduled_state_key(
        pipeline="sell",
        kind="attempt",
        scope="MIXED",
        session_date="2026-07-06",
        runner_role="local-primary",
        attempt_id=attempt_id,
    )


def _request(
    *,
    dry_run: bool = False,
    report_path: str = "reports/2026-07-06.sell-ai-brief.json",
    attempt_id: str | None = None,
    scope: str = "MIXED",
) -> ScheduledSellAiBriefDeliveryRequest:
    return ScheduledSellAiBriefDeliveryRequest(
        sell_ai_brief_report_path=report_path,
        scope=scope,
        session_date="2026-07-06",
        dry_run=dry_run,
        attempt_id=attempt_id,
    )


def _runner(
    *,
    state: _FakeStateStore,
    storage: _FakeStorage | None = None,
    notifier: _FakeNotifier | None = None,
) -> ScheduledSellAiBriefDeliveryRunner:
    return ScheduledSellAiBriefDeliveryRunner(
        state_store=state,
        storage=storage or _FakeStorage(),
        notifier=notifier or _FakeNotifier(),
        now_fn=lambda: dt.datetime(2026, 7, 6, 12, 0, tzinfo=dt.UTC),
    )


def _source() -> dict[str, object]:
    return {
        "title": "Apple sell-side risk update",
        "url": "https://news.example/aapl-risk",
        "published_at": "2026-07-06T07:00:00+00:00",
    }


def _sell_ai_brief_report() -> dict[str, Any]:
    return {
        "schema": "sab.sell_ai_brief.v1",
        "type": "sell-ai-brief",
        "generated_at": "2026-07-06T08:40:00+00:00",
        "report_date": "2026-07-06",
        "source_sell_report": "2026-07-06.sell.json",
        "market": "MIXED",
        "model_provider": "fake",
        "model_name": "fake-sell-ai-brief-v1",
        "brief_state": "FINAL_JUDGMENT",
        "brief_reason": "model_judgment_ready",
        "summary": {
            "evaluated_count": 3,
            "actionable_count": 1,
            "preselected_count": 1,
            "judgment_count": 1,
            "excluded_hold_count": 1,
            "unsupported_action_count": 1,
            "vetoed_count": 0,
            "cap_excluded_count": 0,
            "source_issue_count": 0,
            "system_issue_count": 0,
        },
        "tickers": ["AAPL.NAS"],
        "actionable_tickers": ["AAPL.NAS"],
        "actionable_candidates": [
            {
                "ticker": "AAPL.NAS",
                "name": "Apple",
                "sell_action": "SELL",
                "deterministic_reasons": ["stop loss breached"],
                "ai_role_reason": "sell report action was SELL",
            }
        ],
        "excluded_hold_candidates": [
            {
                "ticker": "MSFT.NAS",
                "sell_action": "HOLD",
                "reason": "sell report action was HOLD",
            }
        ],
        "unsupported_action_candidates": [
            {
                "ticker": "BAD.NAS",
                "sell_action": "TRIM",
                "reason": "unsupported sell action TRIM",
            }
        ],
        "cap_excluded_candidates": [],
        "judgments": [
            {
                "ticker": "AAPL.NAS",
                "name": "Apple",
                "sell_action": "SELL",
                "ai_stance": "AGREE",
                "confidence": "LOW",
                "deterministic_reasons": ["stop loss breached"],
                "rationale": ["기계적 매도 조건과 최근 리스크가 같은 방향입니다."],
                "checklist": ["체결 전 수량, 세금, 유동성을 수동 확인"],
                "sources": [_source()],
                "as_of": "2026-07-06T08:40:00+00:00",
            }
        ],
        "vetoed_candidates": [],
        "source_issues": [],
        "system_issues": [],
    }


def _sell_ai_brief_report_with(**overrides: object) -> dict[str, Any]:
    report = _sell_ai_brief_report()
    report.update(overrides)
    return report


def _write_report(tmp_path: Path, report: dict[str, Any] | None = None) -> str:
    report_path = tmp_path / "2026-07-06.sell-ai-brief.json"
    report_path.write_text(
        json.dumps(report or _sell_ai_brief_report()),
        encoding="utf-8",
    )
    return str(report_path)


@dataclass
class _FakeStateStore:
    entries: dict[str, RuntimeStateEntry] = field(default_factory=dict)
    upserted: list[tuple[str, dict[str, object]]] = field(default_factory=list)
    upsert_ttls: list[tuple[str, int]] = field(default_factory=list)
    claims: list[tuple[str, str]] = field(default_factory=list)
    claim_ttls: list[tuple[str, int]] = field(default_factory=list)
    releases: list[tuple[str, str]] = field(default_factory=list)
    held_locks: set[str] = field(default_factory=set)
    upsert_failures: dict[str, Exception] = field(default_factory=dict)
    fail_upsert_kinds: set[str] = field(default_factory=set)
    acquire_main_lock: bool = True
    claim_hook: Any | None = None

    def __post_init__(self) -> None:
        for kind in self.fail_upsert_kinds:
            self.upsert_failures[_key(kind)] = RuntimeError(f"{kind} write failed")

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
        del now
        if key in self.upsert_failures:
            raise self.upsert_failures[key]
        self.upserted.append((key, payload))
        self.upsert_ttls.append((key, ttl_seconds))
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
        del now
        self.claims.append((key, owner_token))
        self.claim_ttls.append((key, ttl_seconds))
        if key == _key("lock") and not self.acquire_main_lock:
            return RuntimeStateLockClaim(acquired=False, expires_at="soon")
        self.held_locks.add(key)
        self.entries[key] = RuntimeStateEntry(
            state_key=key,
            state_payload={**(payload or {}), "ownerToken": owner_token},
            expires_at="soon",
        )
        if self.claim_hook is not None:
            self.claim_hook(key=key, owner_token=owner_token)
        return RuntimeStateLockClaim(acquired=True, expires_at="soon")

    def release_lock(self, key: str, *, owner_token: str) -> bool:
        self.releases.append((key, owner_token))
        if (
            self.entries.get(key)
            and self.entries[key].state_payload.get("ownerToken") == owner_token
        ):
            del self.entries[key]
        self.held_locks.discard(key)
        return True


@dataclass
class _FakeStorage:
    downloads: dict[str, dict[str, Any]] = field(default_factory=dict)
    uploads: list[str] = field(default_factory=list)
    upload_key: str = "2026/07/2026-07-06.sell-ai-brief.json"
    upload_error: Exception | None = None

    def upload_sell_ai_brief(self, report_path: str, *, report_date: str) -> str:
        del report_date
        self.uploads.append(report_path)
        if self.upload_error is not None:
            raise self.upload_error
        return self.upload_key

    def download_json(self, storage_key: str) -> dict[str, Any]:
        return self.downloads[storage_key]


@dataclass
class _FakeNotifier:
    sent: list[tuple[str, dict[str, Any]]] = field(default_factory=list)
    error_after_send: Exception | None = None
    send_hook: Any | None = None
    preflight_error: Exception | None = None

    def require_telegram(self) -> None:
        if self.preflight_error is not None:
            raise self.preflight_error

    def send_schedule(
        self,
        *,
        report: dict[str, Any],
        storage_key: str,
        text: str,
    ) -> None:
        assert text
        if self.send_hook is not None:
            self.send_hook()
        self.sent.append((storage_key, report))
        if self.error_after_send is not None:
            raise self.error_after_send


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
    assert state.releases == state.claims


def test_scheduled_sell_ai_brief_delivery_rechecks_sent_markers_after_claim() -> None:
    report = _sell_ai_brief_report()
    storage_key = "2026/07/2026-07-06.sell-ai-brief.json"
    state = _FakeStateStore()
    state.entries[_key("artifact")] = RuntimeStateEntry(
        state_key=_key("artifact"),
        state_payload={"storageKey": storage_key},
        expires_at="",
    )

    def complete_after_claim(*, key: str, owner_token: str) -> None:
        del owner_token
        if key != _key("notification:claim"):
            return
        state.entries[_key("notification:sent")] = RuntimeStateEntry(
            state_key=_key("notification:sent"),
            state_payload={"storageKey": storage_key},
            expires_at="",
        )
        state.entries[_key("success")] = RuntimeStateEntry(
            state_key=_key("success"),
            state_payload={"storageKey": storage_key},
            expires_at="",
        )

    state.claim_hook = complete_after_claim
    storage = _FakeStorage(downloads={storage_key: report})
    notifier = _FakeNotifier()
    runner = _runner(state=state, storage=storage, notifier=notifier)

    result = runner.run(_request())

    assert result.status == "success_marker_skip"
    assert result.storage_key == storage_key
    assert notifier.sent == []
    assert state.releases == state.claims


def test_scheduled_sell_ai_brief_delivery_repairs_success_when_sent_marker_exists() -> (
    None
):
    storage_key = "2026/07/2026-07-06.sell-ai-brief.json"
    state = _FakeStateStore()
    state.entries[_key("artifact")] = RuntimeStateEntry(
        state_key=_key("artifact"),
        state_payload={"storageKey": storage_key},
        expires_at="",
    )
    state.entries[_key("notification:sent")] = RuntimeStateEntry(
        state_key=_key("notification:sent"),
        state_payload={"storageKey": storage_key},
        expires_at="",
    )
    storage = _FakeStorage(downloads={storage_key: _sell_ai_brief_report()})
    notifier = _FakeNotifier()
    runner = _runner(state=state, storage=storage, notifier=notifier)

    result = runner.run(_request())

    assert result.status == "completion_repaired"
    assert result.storage_key == "2026/07/2026-07-06.sell-ai-brief.json"
    assert notifier.sent == []
    assert _key("success") in state.entries
    assert state.entries[_key("success")].state_payload["storageKey"] == (
        "2026/07/2026-07-06.sell-ai-brief.json"
    )


def test_scheduled_sell_ai_brief_delivery_repair_rejects_mismatched_storage_keys() -> (
    None
):
    state = _FakeStateStore()
    state.entries[_key("artifact")] = RuntimeStateEntry(
        state_key=_key("artifact"),
        state_payload={"storageKey": "2026/07/2026-07-06.sell-ai-brief.json"},
        expires_at="",
    )
    state.entries[_key("notification:sent")] = RuntimeStateEntry(
        state_key=_key("notification:sent"),
        state_payload={"storageKey": "2026/07/other.sell-ai-brief.json"},
        expires_at="",
    )
    notifier = _FakeNotifier()
    runner = _runner(state=state, notifier=notifier)

    result = runner.run(_request())

    assert result.status == "notification_sent_marker_invalid"
    assert notifier.sent == []
    assert _key("success") not in state.entries


def test_scheduled_sell_ai_brief_delivery_repair_rejects_report_date_mismatch() -> None:
    storage_key = "2026/07/2026-07-06.sell-ai-brief.json"
    state = _FakeStateStore()
    state.entries[_key("artifact")] = RuntimeStateEntry(
        state_key=_key("artifact"),
        state_payload={"storageKey": storage_key},
        expires_at="",
    )
    state.entries[_key("notification:sent")] = RuntimeStateEntry(
        state_key=_key("notification:sent"),
        state_payload={"storageKey": storage_key},
        expires_at="",
    )
    storage = _FakeStorage(
        downloads={storage_key: _sell_ai_brief_report_with(report_date="2026-07-05")}
    )
    notifier = _FakeNotifier()
    runner = _runner(state=state, storage=storage, notifier=notifier)

    result = runner.run(_request())

    assert result.status == "notification_sent_marker_invalid"
    assert notifier.sent == []
    assert _key("success") not in state.entries


def test_scheduled_sell_ai_brief_delivery_reconcile_rejects_report_date_mismatch() -> (
    None
):
    storage_key = "2026/07/2026-07-06.sell-ai-brief.json"
    state = _FakeStateStore()
    state.entries[_key("artifact")] = RuntimeStateEntry(
        state_key=_key("artifact"),
        state_payload={"storageKey": storage_key},
        expires_at="",
    )
    storage = _FakeStorage(
        downloads={storage_key: _sell_ai_brief_report_with(report_date="2026-07-05")}
    )
    notifier = _FakeNotifier()
    runner = _runner(state=state, storage=storage, notifier=notifier)

    result = runner.run(_request())

    assert result.status == "artifact_marker_invalid"
    assert notifier.sent == []
    assert _key("notification:sent") not in state.entries
    assert _key("success") not in state.entries


def test_scheduled_sell_ai_brief_delivery_mixed_scope_accepts_single_market_report() -> (
    None
):
    storage_key = "2026/07/2026-07-06.sell-ai-brief.json"
    state = _FakeStateStore()
    state.entries[_key("artifact")] = RuntimeStateEntry(
        state_key=_key("artifact"),
        state_payload={"storageKey": storage_key},
        expires_at="",
    )
    storage = _FakeStorage(
        downloads={storage_key: _sell_ai_brief_report_with(market="KR")}
    )
    notifier = _FakeNotifier()
    runner = _runner(state=state, storage=storage, notifier=notifier)

    result = runner.run(_request())

    assert result.status == "notification_reconciled"
    assert notifier.sent == [(storage_key, _sell_ai_brief_report_with(market="KR"))]
    assert _key("notification:sent") in state.entries
    assert _key("success") in state.entries


def test_scheduled_sell_ai_brief_delivery_single_scope_rejects_other_market_report() -> (
    None
):
    storage_key = "2026/07/2026-07-06.sell-ai-brief.json"
    state = _FakeStateStore()
    state.entries[_key("artifact", scope="US")] = RuntimeStateEntry(
        state_key=_key("artifact", scope="US"),
        state_payload={"storageKey": storage_key},
        expires_at="",
    )
    storage = _FakeStorage(
        downloads={storage_key: _sell_ai_brief_report_with(market="KR")}
    )
    notifier = _FakeNotifier()
    runner = _runner(state=state, storage=storage, notifier=notifier)

    result = runner.run(_request(scope="US"))

    assert result.status == "artifact_marker_invalid"
    assert notifier.sent == []
    assert _key("notification:sent", scope="US") not in state.entries
    assert _key("success", scope="US") not in state.entries


def test_scheduled_sell_ai_brief_delivery_reconcile_rejects_unbound_storage_key() -> (
    None
):
    storage_key = "2026/07/2026-07-05.sell-ai-brief.json"
    state = _FakeStateStore()
    state.entries[_key("artifact")] = RuntimeStateEntry(
        state_key=_key("artifact"),
        state_payload={"storageKey": storage_key},
        expires_at="",
    )
    storage = _FakeStorage(downloads={storage_key: _sell_ai_brief_report()})
    notifier = _FakeNotifier()
    runner = _runner(state=state, storage=storage, notifier=notifier)

    result = runner.run(_request())

    assert result.status == "artifact_marker_invalid"
    assert notifier.sent == []
    assert storage.downloads[storage_key]


def test_scheduled_sell_ai_brief_delivery_releases_claim_on_pre_send_validation_failure() -> (
    None
):
    state = _FakeStateStore()
    state.entries[_key("artifact")] = RuntimeStateEntry(
        state_key=_key("artifact"),
        state_payload={"storageKey": "2026/07/2026-07-06.sell-ai-brief.json"},
        expires_at="",
    )
    storage = _FakeStorage(downloads={"2026/07/2026-07-06.sell-ai-brief.json": {}})
    notifier = _FakeNotifier()
    runner = _runner(state=state, storage=storage, notifier=notifier)

    result = runner.run(_request())

    assert result.status == "artifact_marker_invalid"
    assert notifier.sent == []
    assert _key("notification:claim") not in [key for key, _owner in state.claims]


def test_scheduled_sell_ai_brief_delivery_preflights_notifier_before_claim() -> None:
    report = _sell_ai_brief_report()
    storage_key = "2026/07/2026-07-06.sell-ai-brief.json"
    state = _FakeStateStore()
    state.entries[_key("artifact")] = RuntimeStateEntry(
        state_key=_key("artifact"),
        state_payload={"storageKey": storage_key},
        expires_at="",
    )
    storage = _FakeStorage(downloads={storage_key: report})
    notifier = _FakeNotifier(preflight_error=RuntimeError("telegram env missing"))
    runner = _runner(state=state, storage=storage, notifier=notifier)

    with pytest.raises(RuntimeError, match="telegram env missing"):
        runner.run(_request())

    assert notifier.sent == []
    assert _key("notification:claim") not in [key for key, _owner in state.claims]


def test_scheduled_sell_ai_brief_delivery_keeps_claim_when_send_raises_after_send() -> (
    None
):
    report = _sell_ai_brief_report()
    state = _FakeStateStore()
    state.entries[_key("artifact")] = RuntimeStateEntry(
        state_key=_key("artifact"),
        state_payload={"storageKey": "2026/07/2026-07-06.sell-ai-brief.json"},
        expires_at="",
    )
    storage = _FakeStorage(downloads={"2026/07/2026-07-06.sell-ai-brief.json": report})
    notifier = _FakeNotifier(error_after_send=RuntimeError("telegram partial send"))
    runner = _runner(state=state, storage=storage, notifier=notifier)

    with pytest.raises(RuntimeError, match="telegram partial send"):
        runner.run(_request())

    assert notifier.sent == [("2026/07/2026-07-06.sell-ai-brief.json", report)]
    assert state.releases == []
    assert state.upsert_ttls[-1] == (_key("notification:claim"), 48 * 60 * 60)
    assert (
        state.entries[_key("notification:claim")].state_payload["ownerToken"]
        == (state.claims[-1][1])
    )


def test_scheduled_sell_ai_brief_delivery_keeps_claim_when_sent_marker_upsert_raises() -> (
    None
):
    report = _sell_ai_brief_report()
    state = _FakeStateStore(
        upsert_failures={
            _key("notification:sent"): RuntimeError("state write unavailable")
        }
    )
    state.entries[_key("artifact")] = RuntimeStateEntry(
        state_key=_key("artifact"),
        state_payload={"storageKey": "2026/07/2026-07-06.sell-ai-brief.json"},
        expires_at="",
    )
    storage = _FakeStorage(downloads={"2026/07/2026-07-06.sell-ai-brief.json": report})
    notifier = _FakeNotifier()
    runner = _runner(state=state, storage=storage, notifier=notifier)

    result = runner.run(_request())

    assert result.status == "notification_sent_marker_failed"
    assert notifier.sent == [("2026/07/2026-07-06.sell-ai-brief.json", report)]
    assert state.releases == []
    assert state.upsert_ttls[-1] == (_key("notification:claim"), 48 * 60 * 60)
    assert (
        state.entries[_key("notification:claim")].state_payload["ownerToken"]
        == (state.claims[-1][1])
    )


def test_scheduled_sell_ai_brief_delivery_reconcile_handles_claim_extension_failure() -> (
    None
):
    report = _sell_ai_brief_report()
    storage_key = "2026/07/2026-07-06.sell-ai-brief.json"
    state = _FakeStateStore(
        upsert_failures={
            _key("notification:claim"): RuntimeError("claim extension unavailable")
        }
    )
    state.entries[_key("artifact")] = RuntimeStateEntry(
        state_key=_key("artifact"),
        state_payload={"storageKey": storage_key},
        expires_at="",
    )
    storage = _FakeStorage(downloads={storage_key: report})
    notifier = _FakeNotifier()
    runner = _runner(state=state, storage=storage, notifier=notifier)

    result = runner.run(_request())

    assert result.status == "notification_sent_marker_failed"
    assert result.storage_key == storage_key
    assert notifier.sent == []
    assert state.releases == state.claims


def test_scheduled_sell_ai_brief_delivery_uploads_then_marks_artifact_then_notifies(
    tmp_path: Path,
) -> None:
    state = _FakeStateStore()
    storage = _FakeStorage(upload_key="2026/07/2026-07-06.sell-ai-brief.json")
    notifier = _FakeNotifier()
    report_path = _write_report(tmp_path)
    runner = _runner(state=state, storage=storage, notifier=notifier)

    result = runner.run(_request(report_path=report_path))

    assert result.status == "completed"
    assert storage.uploads == [report_path]
    assert _key("artifact") in state.entries
    assert _key("notification:sent") in state.entries
    assert _key("success") in state.entries
    assert notifier.sent


def test_scheduled_sell_ai_brief_delivery_lock_contention_skips_without_upload(
    tmp_path: Path,
) -> None:
    state = _FakeStateStore(acquire_main_lock=False)
    storage = _FakeStorage()
    report_path = _write_report(tmp_path)
    runner = _runner(state=state, storage=storage)

    result = runner.run(_request(report_path=report_path))

    assert result.status == "lock_held_skip"
    assert storage.uploads == []


def test_scheduled_sell_ai_brief_delivery_upload_failure_blocks_markers_and_notification(
    tmp_path: Path,
) -> None:
    state = _FakeStateStore()
    storage = _FakeStorage(upload_error=RuntimeError("index down"))
    notifier = _FakeNotifier()
    report_path = _write_report(tmp_path)
    runner = _runner(state=state, storage=storage, notifier=notifier)

    result = runner.run(_request(report_path=report_path))

    assert result.status == "upload_failed"
    assert _key("artifact") not in state.entries
    assert _key("success") not in state.entries
    assert notifier.sent == []


def test_scheduled_sell_ai_brief_delivery_blank_upload_key_blocks_markers_and_notification(
    tmp_path: Path,
) -> None:
    state = _FakeStateStore()
    storage = _FakeStorage(upload_key="   ")
    notifier = _FakeNotifier()
    report_path = _write_report(tmp_path)
    runner = _runner(state=state, storage=storage, notifier=notifier)

    result = runner.run(_request(report_path=report_path))

    assert result.status == "upload_failed"
    assert storage.uploads == [report_path]
    assert _key("artifact") not in state.entries
    assert _key("success") not in state.entries
    assert notifier.sent == []


def test_scheduled_sell_ai_brief_delivery_invalid_report_blocks_upload(
    tmp_path: Path,
) -> None:
    state = _FakeStateStore()
    storage = _FakeStorage()
    report_path = _write_report(
        tmp_path,
        {"type": "sell-ai-brief", "schema": "broken", "report_date": "2026-07-06"},
    )
    runner = _runner(state=state, storage=storage)

    result = runner.run(_request(report_path=report_path))

    assert result.status == "artifact_invalid"
    assert storage.uploads == []


def test_scheduled_sell_ai_brief_delivery_keeps_claim_when_sent_marker_fails(
    tmp_path: Path,
) -> None:
    state = _FakeStateStore(fail_upsert_kinds={"notification:sent"})
    notifier = _FakeNotifier()
    report_path = _write_report(tmp_path)
    runner = _runner(state=state, notifier=notifier)

    result = runner.run(_request(report_path=report_path))

    assert result.status == "notification_sent_marker_failed"
    assert notifier.sent
    assert _key("notification:claim") in state.held_locks


def test_scheduled_sell_ai_brief_delivery_reconcile_records_attempt_before_send_and_success() -> (
    None
):
    report = _sell_ai_brief_report()
    attempt_id = "reconcile-1"
    state = _FakeStateStore()
    state.entries[_key("artifact")] = RuntimeStateEntry(
        state_key=_key("artifact"),
        state_payload={"storageKey": "2026/07/2026-07-06.sell-ai-brief.json"},
        expires_at="",
    )
    storage = _FakeStorage(downloads={"2026/07/2026-07-06.sell-ai-brief.json": report})

    def assert_attempt_exists_before_send() -> None:
        assert _attempt_key(attempt_id) in state.entries
        assert _key("notification:sent") not in state.entries
        assert _key("success") not in state.entries

    notifier = _FakeNotifier(send_hook=assert_attempt_exists_before_send)
    runner = _runner(state=state, storage=storage, notifier=notifier)

    result = runner.run(_request(attempt_id=attempt_id))

    upserted_keys = [key for key, _payload in state.upserted]
    assert result.status == "notification_reconciled"
    assert upserted_keys.index(_attempt_key(attempt_id)) < upserted_keys.index(
        _key("notification:sent")
    )
    assert upserted_keys.index(_attempt_key(attempt_id)) < upserted_keys.index(
        _key("success")
    )


def test_default_scheduled_storage_upload_sell_ai_brief_uses_report_artifact(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[dict[str, object]] = []

    def fake_upload_report_artifact(**kwargs: object) -> str:
        calls.append(kwargs)
        return "2026/07/2026-07-06.sell-ai-brief.json"

    monkeypatch.setattr(
        scheduler_runner,
        "upload_report_artifact",
        fake_upload_report_artifact,
    )
    config = SupabaseStorageConfig(
        url="https://example.supabase.co",
        service_role_key="service-key",
        bucket="reports",
    )
    storage = scheduler_runner.DefaultScheduledStorage(config)

    result = storage.upload_sell_ai_brief(
        "reports/2026-07-06.sell-ai-brief.json",
        report_date="2026-07-06",
    )

    assert result == "2026/07/2026-07-06.sell-ai-brief.json"
    assert calls == [
        {
            "local_path": "reports/2026-07-06.sell-ai-brief.json",
            "run_type": "sell-ai-brief",
            "report_date": dt.date(2026, 7, 6),
            "config": config,
        }
    ]
