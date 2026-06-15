from __future__ import annotations

import datetime as dt
import json

import pytest
from sab.ai_brief_providers import (
    AiBriefProviderContractError,
    FakeAiBriefProvider,
    OpenAiBriefProvider,
)


def _fresh_published_at() -> str:
    return dt.datetime.now(dt.UTC).replace(microsecond=0).isoformat()


def _published_at(offset: dt.timedelta) -> str:
    return (dt.datetime.now(dt.UTC) + offset).replace(microsecond=0).isoformat()


def _source(ticker: str, *, published_at: str | None = None) -> dict[str, object]:
    return {
        "title": f"{ticker} source",
        "url": f"https://news.example/{ticker}",
        "published_at": published_at or _fresh_published_at(),
    }


def _candidate(
    ticker: str,
    *,
    role: str,
    ai_role_reason: str = "test role reason",
    published_at: str | None = None,
) -> dict[str, object]:
    return {
        "ticker": ticker,
        "name": None,
        "action": "ENTER" if role == "recommendable" else "SKIP",
        "ai_role": role,
        "ai_role_reason": ai_role_reason,
        "entry_reasons": ["entry reason"],
        "buy_reason_labels": [],
        "entry_price": 100.0,
        "gap_pct": 0.01,
        "gap_guard_pct": 0.03,
        "strategy_mode": "ema_cross",
        "pattern": None,
        "entry_state": "READY",
        "sources": [_source(ticker, published_at=published_at)],
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
                    "sources": [
                        {
                            "title": "MSFT source",
                            "url": "https://news.example/MSFT.NAS",
                            "published_at": _fresh_published_at(),
                        }
                    ],
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

    result = provider.build_recommendations(
        recommendable_candidates=[_candidate("AAPL.NAS", role="recommendable")],
        watch_candidates=[_candidate("MSFT.NAS", role="watch_only")],
    )

    request = session.requests[0]["json"]
    assert isinstance(request, dict)
    request_input = request["input"]
    assert isinstance(request_input, list)
    user_message = request_input[1]
    assert isinstance(user_message, dict)
    user_content = user_message["content"]
    assert isinstance(user_content, str)
    user_payload = json.loads(user_content)
    assert [row["ticker"] for row in user_payload["recommendable_candidates"]] == [
        "AAPL.NAS"
    ]
    assert [row["ticker"] for row in user_payload["watch_candidates"]] == ["MSFT.NAS"]
    assert result.watch_candidates[0]["ticker"] == "MSFT.NAS"


def test_fake_provider_rejects_watch_candidate_with_automated_order_language() -> None:
    provider = FakeAiBriefProvider(model_name="fake-ai-brief-v1")

    with pytest.raises(AiBriefProviderContractError, match="automated-order"):
        provider.build_recommendations(
            recommendable_candidates=[_candidate("AAPL.NAS", role="recommendable")],
            watch_candidates=[
                _candidate(
                    "MSFT.NAS",
                    role="watch_only",
                    ai_role_reason="buy now when price crosses trigger",
                )
            ],
        )


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
                                "published_at": _fresh_published_at(),
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
                                "published_at": _fresh_published_at(),
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
                                "published_at": _fresh_published_at(),
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


def test_openai_rejects_watch_candidate_with_automated_order_language() -> None:
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
                        "action": "WATCH",
                        "reason": "buy now when price crosses trigger",
                        "retrigger_conditions": ["price back above trigger"],
                        "sources": [_source("MSFT.NAS")],
                    }
                ],
                "source_issues": [],
            }
        ),
    )

    with pytest.raises(AiBriefProviderContractError, match="automated-order"):
        provider.build_recommendations(
            recommendable_candidates=[_candidate("AAPL.NAS", role="recommendable")],
            watch_candidates=[_candidate("MSFT.NAS", role="watch_only")],
        )


def test_openai_rejects_watch_candidate_stale_source() -> None:
    stale_published_at = _published_at(-dt.timedelta(hours=73))
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
                        "action": "WATCH",
                        "reason": "trigger pending",
                        "retrigger_conditions": ["price back above trigger"],
                        "sources": [
                            _source("MSFT.NAS", published_at=stale_published_at)
                        ],
                    }
                ],
                "source_issues": [],
            }
        ),
    )

    with pytest.raises(AiBriefProviderContractError, match="within 72h"):
        provider.build_recommendations(
            recommendable_candidates=[_candidate("AAPL.NAS", role="recommendable")],
            watch_candidates=[
                _candidate(
                    "MSFT.NAS", role="watch_only", published_at=stale_published_at
                )
            ],
        )


def test_openai_rejects_watch_candidate_when_canonical_source_is_stale() -> None:
    stale_published_at = _published_at(-dt.timedelta(hours=73))
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
                        "action": "WATCH",
                        "reason": "trigger pending",
                        "retrigger_conditions": ["price back above trigger"],
                        "sources": [_source("MSFT.NAS")],
                    }
                ],
                "source_issues": [],
            }
        ),
    )

    with pytest.raises(AiBriefProviderContractError, match="within 72h"):
        provider.build_recommendations(
            recommendable_candidates=[_candidate("AAPL.NAS", role="recommendable")],
            watch_candidates=[
                _candidate(
                    "MSFT.NAS", role="watch_only", published_at=stale_published_at
                )
            ],
        )


def test_openai_rejects_watch_candidate_future_source() -> None:
    future_published_at = _published_at(dt.timedelta(minutes=30))
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
                        "action": "WATCH",
                        "reason": "trigger pending",
                        "retrigger_conditions": ["price back above trigger"],
                        "sources": [
                            _source("MSFT.NAS", published_at=future_published_at)
                        ],
                    }
                ],
                "source_issues": [],
            }
        ),
    )

    with pytest.raises(AiBriefProviderContractError, match="15m"):
        provider.build_recommendations(
            recommendable_candidates=[_candidate("AAPL.NAS", role="recommendable")],
            watch_candidates=[
                _candidate(
                    "MSFT.NAS", role="watch_only", published_at=future_published_at
                )
            ],
        )


def test_openai_rejects_watch_candidate_unprovided_source_url() -> None:
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
                        "action": "WATCH",
                        "reason": "trigger pending",
                        "retrigger_conditions": ["price back above trigger"],
                        "sources": [
                            {
                                "title": "Unprovided source",
                                "url": "https://news.example/unprovided",
                                "published_at": _fresh_published_at(),
                            }
                        ],
                    }
                ],
                "source_issues": [],
            }
        ),
    )

    with pytest.raises(AiBriefProviderContractError, match="source url must be supplied"):
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
