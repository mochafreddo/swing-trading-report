from __future__ import annotations

import json

import pytest
from sab.ai_brief_providers import (
    AiBriefProviderContractError,
    FakeAiBriefProvider,
    OpenAiBriefProvider,
)


def _candidate(ticker: str, *, role: str) -> dict[str, object]:
    return {
        "ticker": ticker,
        "name": None,
        "action": "ENTER" if role == "recommendable" else "SKIP",
        "ai_role": role,
        "ai_role_reason": "test role reason",
        "entry_reasons": ["entry reason"],
        "buy_reason_labels": [],
        "entry_price": 100.0,
        "gap_pct": 0.01,
        "gap_guard_pct": 0.03,
        "strategy_mode": "ema_cross",
        "pattern": None,
        "entry_state": "READY",
        "sources": [
            {
                "title": f"{ticker} source",
                "url": f"https://news.example/{ticker}",
                "published_at": "2026-06-15T12:00:00+00:00",
            }
        ],
    }


def test_fake_provider_returns_watch_candidates_separately() -> None:
    provider = FakeAiBriefProvider(model_name="fake-ai-brief-v1")

    result = provider.build_recommendations(
        recommendable_candidates=[_candidate("AAPL.NAS", role="recommendable")],
        watch_candidates=[_candidate("MSFT.NAS", role="watch_only")],
    )

    assert [row["ticker"] for row in result.recommendations] == ["AAPL.NAS"]
    assert [row["ticker"] for row in result.watch_candidates] == ["MSFT.NAS"]
    assert result.watch_candidates[0]["action"] == "WATCH"


def test_openai_payload_separates_recommendable_and_watch_candidates() -> None:
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
                        "sources": [
                            {
                                "title": "MSFT source",
                                "url": "https://news.example/MSFT.NAS",
                                "published_at": "2026-06-15T12:00:00+00:00",
                            }
                        ],
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

    request = provider._session.requests[0]["json"]  # type: ignore[attr-defined]
    user_payload = json.loads(request["input"][1]["content"])
    assert [row["ticker"] for row in user_payload["recommendable_candidates"]] == [
        "AAPL.NAS"
    ]
    assert [row["ticker"] for row in user_payload["watch_candidates"]] == ["MSFT.NAS"]
    assert result.watch_candidates[0]["ticker"] == "MSFT.NAS"


def test_openai_rejects_watch_candidate_returned_as_recommendation() -> None:
    provider = OpenAiBriefProvider(
        model_name="gpt-test",
        api_key="test-key",
        timeout_seconds=1.0,
        session=_CapturingSession(
            {
                "recommendations": [
                    {
                        "ticker": "MSFT.NAS",
                        "rank": 1,
                        "confidence": "LOW",
                        "rationale": ["bad role"],
                        "checklist": ["manual check"],
                        "sources": [],
                    }
                ],
                "vetoed_candidates": [],
                "watch_candidates": [],
                "source_issues": [
                    {
                        "ticker": "MSFT.NAS",
                        "code": "openai_no_source",
                        "severity": "WARN",
                        "message": "no source",
                    }
                ],
            }
        ),
    )

    with pytest.raises(AiBriefProviderContractError, match="ineligible ticker"):
        provider.build_recommendations(
            recommendable_candidates=[_candidate("AAPL.NAS", role="recommendable")],
            watch_candidates=[_candidate("MSFT.NAS", role="watch_only")],
        )


def test_openai_rejects_overlapping_candidate_roles() -> None:
    provider = OpenAiBriefProvider(
        model_name="gpt-test",
        api_key="test-key",
        timeout_seconds=1.0,
        session=_CapturingSession(
            {
                "recommendations": [
                    {
                        "ticker": "AAPL.NAS",
                        "rank": 1,
                        "confidence": "LOW",
                        "rationale": ["bad role"],
                        "checklist": ["manual check"],
                        "sources": [
                            {
                                "title": "AAPL source",
                                "url": "https://news.example/AAPL.NAS",
                                "published_at": "2026-06-15T12:00:00+00:00",
                            }
                        ],
                    }
                ],
                "vetoed_candidates": [],
                "watch_candidates": [],
                "source_issues": [],
            }
        ),
    )

    with pytest.raises(
        AiBriefProviderContractError, match="candidate ticker roles must be disjoint"
    ):
        provider.build_recommendations(
            recommendable_candidates=[_candidate("AAPL.NAS", role="recommendable")],
            watch_candidates=[_candidate("AAPL.NAS", role="watch_only")],
        )


def test_openai_rejects_watch_candidate_returned_as_veto() -> None:
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
                "watch_candidates": [],
                "source_issues": [],
            }
        ),
    )

    with pytest.raises(AiBriefProviderContractError, match="watch ticker"):
        provider.build_recommendations(
            recommendable_candidates=[_candidate("AAPL.NAS", role="recommendable")],
            watch_candidates=[_candidate("MSFT.NAS", role="watch_only")],
        )


def test_openai_rejects_watch_candidate_with_skip_action() -> None:
    provider = OpenAiBriefProvider(
        model_name="gpt-test",
        api_key="test-key",
        timeout_seconds=1.0,
        session=_CapturingSession(
            {
                "recommendations": [],
                "vetoed_candidates": [],
                "watch_candidates": [
                    {
                        "ticker": "MSFT.NAS",
                        "action": "SKIP",
                        "reason": "trigger pending",
                        "retrigger_conditions": ["price back above trigger"],
                        "sources": [
                            {
                                "title": "MSFT source",
                                "url": "https://news.example/MSFT.NAS",
                                "published_at": "2026-06-15T12:00:00+00:00",
                            }
                        ],
                    }
                ],
                "source_issues": [],
            }
        ),
    )

    with pytest.raises(
        AiBriefProviderContractError,
        match=r"watch_candidates\[\]\.action must be WATCH",
    ):
        provider.build_recommendations(
            recommendable_candidates=[_candidate("AAPL.NAS", role="recommendable")],
            watch_candidates=[_candidate("MSFT.NAS", role="watch_only")],
        )


def test_openai_rejects_watch_candidate_with_missing_action() -> None:
    provider = OpenAiBriefProvider(
        model_name="gpt-test",
        api_key="test-key",
        timeout_seconds=1.0,
        session=_CapturingSession(
            {
                "recommendations": [],
                "vetoed_candidates": [],
                "watch_candidates": [
                    {
                        "ticker": "MSFT.NAS",
                        "reason": "trigger pending",
                        "retrigger_conditions": ["price back above trigger"],
                        "sources": [
                            {
                                "title": "MSFT source",
                                "url": "https://news.example/MSFT.NAS",
                                "published_at": "2026-06-15T12:00:00+00:00",
                            }
                        ],
                    }
                ],
                "source_issues": [],
            }
        ),
    )

    with pytest.raises(
        AiBriefProviderContractError,
        match=r"watch_candidates\[\]\.action must be WATCH",
    ):
        provider.build_recommendations(
            recommendable_candidates=[_candidate("AAPL.NAS", role="recommendable")],
            watch_candidates=[_candidate("MSFT.NAS", role="watch_only")],
        )


class _Response:
    status_code = 200

    def __init__(self, payload: dict[str, object]) -> None:
        self._payload = payload
        self.text = json.dumps(payload)

    def json(self) -> dict[str, object]:
        return {
            "output_text": json.dumps(self._payload),
        }


class _CapturingSession:
    def __init__(self, payload: dict[str, object]) -> None:
        self.payload = payload
        self.requests: list[dict[str, object]] = []

    def post(self, url: str, **kwargs: object) -> _Response:
        self.requests.append({"url": url, **kwargs})
        return _Response(self.payload)
