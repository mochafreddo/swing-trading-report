from __future__ import annotations

import datetime as dt
from dataclasses import dataclass, field
from typing import Any

import pytest
from sab.scheduler.generic_state import build_scheduled_state_key
from sab.scheduler.sell_ai_brief_delivery import (
    ScheduledSellAiBriefDeliveryRequest,
    ScheduledSellAiBriefDeliveryRunner,
)
from sab.scheduler.state import RuntimeStateEntry, RuntimeStateLockClaim


def _key(kind: str) -> str:
    return build_scheduled_state_key(
        pipeline="sell",
        kind=kind,
        scope="MIXED",
        session_date="2026-07-06",
    )


def _request(*, dry_run: bool = False) -> ScheduledSellAiBriefDeliveryRequest:
    return ScheduledSellAiBriefDeliveryRequest(
        sell_ai_brief_report_path="reports/2026-07-06.sell-ai-brief.json",
        session_date="2026-07-06",
        dry_run=dry_run,
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


@dataclass
class _FakeStateStore:
    entries: dict[str, RuntimeStateEntry] = field(default_factory=dict)
    upserted: list[tuple[str, dict[str, object]]] = field(default_factory=list)
    claims: list[tuple[str, str]] = field(default_factory=list)
    releases: list[tuple[str, str]] = field(default_factory=list)
    upsert_failures: dict[str, Exception] = field(default_factory=dict)

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
        if key in self.upsert_failures:
            raise self.upsert_failures[key]
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
        del ttl_seconds, now, payload
        self.claims.append((key, owner_token))
        return RuntimeStateLockClaim(acquired=True, expires_at="soon")

    def release_lock(self, key: str, *, owner_token: str) -> bool:
        self.releases.append((key, owner_token))
        return True


@dataclass
class _FakeStorage:
    downloads: dict[str, dict[str, Any]] = field(default_factory=dict)
    uploads: list[tuple[str, str]] = field(default_factory=list)

    def download_json(self, storage_key: str) -> dict[str, Any]:
        return self.downloads[storage_key]


@dataclass
class _FakeNotifier:
    sent: list[tuple[str, dict[str, Any]]] = field(default_factory=list)
    error_after_send: Exception | None = None

    def send_schedule(
        self,
        *,
        report: dict[str, Any],
        storage_key: str,
        text: str,
    ) -> None:
        assert text
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

    with pytest.raises(ValueError):
        runner.run(_request())

    assert notifier.sent == []
    assert state.releases == state.claims


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

    with pytest.raises(RuntimeError, match="state write unavailable"):
        runner.run(_request())

    assert notifier.sent == [("2026/07/2026-07-06.sell-ai-brief.json", report)]
    assert state.releases == []
