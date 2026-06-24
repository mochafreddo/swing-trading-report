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
    action: str | None = None,
    ai_role_reason: str = "test role reason",
    published_at: str | None = None,
) -> dict[str, object]:
    return {
        "ticker": ticker,
        "name": None,
        "action": action or ("ENTER" if role == "recommendable" else "SKIP"),
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


def test_fake_provider_rationale_uses_ai_role_reason_for_promoted_candidates() -> None:
    provider = FakeAiBriefProvider(model_name="fake-ai-brief-v1")

    result = provider.build_recommendations(
        recommendable_candidates=[
            _candidate(
                "CAT.NYS",
                role="blocked_but_valid",
                action="SKIP",
                ai_role_reason="portfolio policy blocked automatic entry",
            ),
            _candidate(
                "CIFR.NAS",
                role="blocked_but_valid",
                action="REVIEW",
                ai_role_reason="risk alignment requires manual review",
            ),
        ],
        watch_candidates=[],
    )

    rationale_items: list[str] = []
    for recommendation in result.recommendations:
        rationale = recommendation["rationale"]
        assert isinstance(rationale, list)
        rationale_items.extend(str(item) for item in rationale)
    rationale_text = "\n".join(rationale_items)
    assert "portfolio policy blocked automatic entry" in rationale_text
    assert "risk alignment requires manual review" in rationale_text
    assert "entry report marked this candidate ENTER" not in rationale_text
    assert result.recommendations[0]["candidate_role"] == "blocked_but_valid"
    assert result.recommendations[0]["entry_action"] == "SKIP"
    assert result.recommendations[0]["candidate_role_reason"] == (
        "portfolio policy blocked automatic entry"
    )
    assert result.recommendations[1]["candidate_role"] == "blocked_but_valid"
    assert result.recommendations[1]["entry_action"] == "REVIEW"


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


def test_openai_payload_adds_source_ids_and_schema_uses_source_refs() -> None:
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
        recommendable_candidates=[_candidate("AAPL.NAS", role="recommendable")],
        watch_candidates=[_candidate("MSFT.NAS", role="watch_only")],
    )

    request = session.requests[0]["json"]
    assert isinstance(request, dict)
    user_payload = json.loads(str(request["input"][1]["content"]))
    recommendation_source = user_payload["recommendable_candidates"][0]["sources"][0]
    watch_source = user_payload["watch_candidates"][0]["sources"][0]
    assert recommendation_source["source_id"] == "AAPL.NAS:1"
    assert watch_source["source_id"] == "MSFT.NAS:1"

    schema = request["text"]["format"]["schema"]
    recommendation_props = schema["properties"]["recommendations"]["items"][
        "properties"
    ]
    watch_props = schema["properties"]["watch_candidates"]["items"]["properties"]
    assert "source_refs" in recommendation_props
    assert "source_refs" in watch_props
    assert "sources" not in recommendation_props
    assert "sources" not in watch_props


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
    assert (
        "enum"
        not in schema["properties"]["recommendations"]["items"]["properties"]["ticker"]
    )
    assert schema["properties"]["watch_candidates"]["items"]["properties"][
        "ticker"
    ] == {"type": "string", "enum": ["MSFT.NAS"]}


def test_openai_normalized_output_preserves_candidate_investment_readiness() -> None:
    session = _CapturingSession(
        {
            "recommendations": [
                {
                    "ticker": "AAPL.NAS",
                    "rank": 1,
                    "confidence": "LOW",
                    "rationale": ["entry setup remains valid"],
                    "checklist": ["confirm price"],
                    "source_refs": ["AAPL.NAS:1"],
                }
            ],
            "vetoed_candidates": [],
            "watch_candidates": [],
            "source_issues": [],
        }
    )
    provider = OpenAiBriefProvider(
        model_name="gpt-test",
        api_key="test-key",
        timeout_seconds=1.0,
        session=session,
    )
    candidate = _candidate("AAPL.NAS", role="recommendable")
    candidate.update(
        {
            "implementation_ready": False,
            "investment_readiness": "CONTEXT_REQUIRED",
            "investment_readiness_reasons": [
                "nav_risk_budget_unavailable",
                "liquidity_exit_capacity_unavailable",
            ],
            "liquidity_exit_capacity": {
                "status": "available",
                "position_adv_percent": 5.0,
                "exit_days_normal": 0.5,
                "exit_days_stressed": 1.6667,
            },
            "liquidity_warnings": ["small_cap_liquidity_risk"],
        }
    )

    result = provider.build_recommendations(
        recommendable_candidates=[candidate],
        watch_candidates=[],
    )

    recommendation = result.recommendations[0]
    assert recommendation["implementation_ready"] is False
    assert recommendation["investment_readiness"] == "CONTEXT_REQUIRED"
    assert recommendation["investment_readiness_reasons"] == [
        "nav_risk_budget_unavailable",
        "liquidity_exit_capacity_unavailable",
    ]
    assert recommendation["liquidity_exit_capacity"] == {
        "status": "available",
        "position_adv_percent": 5.0,
        "exit_days_normal": 0.5,
        "exit_days_stressed": 1.6667,
    }
    assert recommendation["liquidity_warnings"] == ["small_cap_liquidity_risk"]
    rationale = recommendation["rationale"]
    checklist = recommendation["checklist"]
    assert isinstance(rationale, list)
    assert isinstance(checklist, list)
    assert "investment readiness requires context: CONTEXT_REQUIRED" in rationale
    assert (
        "confirm NAV/risk budget, exit liquidity, portfolio exposure, and source context before acting"
        in checklist
    )


def test_openai_rejects_legacy_output_sources_after_source_ref_schema_switch() -> None:
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

    with pytest.raises(AiBriefProviderContractError, match="source_refs"):
        provider.build_recommendations(
            recommendable_candidates=[_candidate("AAPL.NAS", role="recommendable")],
            watch_candidates=[_candidate("MSFT.NAS", role="watch_only")],
        )


def test_openai_prompt_separates_executable_from_blocked_review_skip_candidates() -> (
    None
):
    session = _CapturingSession(
        {
            "recommendations": [],
            "vetoed_candidates": [],
            "watch_candidates": [],
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
        recommendable_candidates=[
            _candidate(
                "CAT.NYS",
                role="blocked_but_valid",
                action="SKIP",
                ai_role_reason="portfolio policy blocked automatic entry",
            ),
            _candidate(
                "CIFR.NAS",
                role="blocked_but_valid",
                action="REVIEW",
                ai_role_reason="risk alignment requires manual review",
            ),
        ],
        watch_candidates=[],
    )

    request = session.requests[0]["json"]
    assert isinstance(request, dict)
    request_input = request["input"]
    assert isinstance(request_input, list)
    system_message = request_input[0]
    assert isinstance(system_message, dict)
    system_content = str(system_message["content"])
    assert "Do not recommend REVIEW or SKIP rows" not in system_content
    assert "executable" in system_content
    assert "blocked_but_valid" in system_content
    user_message = request_input[1]
    assert isinstance(user_message, dict)
    user_payload = json.loads(str(user_message["content"]))
    assert [row["action"] for row in user_payload["recommendable_candidates"]] == [
        "SKIP",
        "REVIEW",
    ]
    assert [row["ai_role"] for row in user_payload["recommendable_candidates"]] == [
        "blocked_but_valid",
        "blocked_but_valid",
    ]
    assert [
        row["ai_role_reason"] for row in user_payload["recommendable_candidates"]
    ] == [
        "portfolio policy blocked automatic entry",
        "risk alignment requires manual review",
    ]


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
                        "source_refs": [],
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


@pytest.mark.parametrize("bad_rank", [True, 1.0])
def test_openai_rejects_non_integer_raw_recommendation_rank(
    bad_rank: object,
) -> None:
    provider = OpenAiBriefProvider(
        model_name="gpt-test",
        api_key="test-key",
        timeout_seconds=1.0,
        session=_CapturingSession(
            {
                "recommendations": [
                    {
                        "ticker": "AAPL.NAS",
                        "rank": bad_rank,
                        "confidence": "LOW",
                        "rationale": ["bad rank type"],
                        "checklist": ["manual check"],
                        "source_refs": [],
                    }
                ],
                "vetoed_candidates": [],
                "watch_candidates": [],
                "source_issues": [],
            }
        ),
    )

    with pytest.raises(AiBriefProviderContractError, match="rank must be an integer"):
        provider.build_recommendations(
            recommendable_candidates=[_candidate("AAPL.NAS", role="recommendable")],
            watch_candidates=[],
        )


def test_openai_rejects_missing_watch_candidate_output() -> None:
    provider = OpenAiBriefProvider(
        model_name="gpt-test",
        api_key="test-key",
        timeout_seconds=1.0,
        session=_CapturingSession(
            {
                "recommendations": [],
                "vetoed_candidates": [],
                "watch_candidates": [],
                "source_issues": [],
            }
        ),
    )

    with pytest.raises(AiBriefProviderContractError, match="watch_candidates"):
        provider.build_recommendations(
            recommendable_candidates=[_candidate("AAPL.NAS", role="recommendable")],
            watch_candidates=[_candidate("MSFT.NAS", role="watch_only")],
        )


def test_openai_rejects_reordered_watch_candidate_output() -> None:
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
                        "ticker": "TSLA.NAS",
                        "action": "WATCH",
                        "reason": "trigger pending",
                        "retrigger_conditions": ["price back above trigger"],
                        "source_refs": ["TSLA.NAS:1"],
                    },
                    {
                        "ticker": "MSFT.NAS",
                        "action": "WATCH",
                        "reason": "trigger pending",
                        "retrigger_conditions": ["price back above trigger"],
                        "source_refs": ["MSFT.NAS:1"],
                    },
                ],
                "source_issues": [],
            }
        ),
    )

    with pytest.raises(AiBriefProviderContractError, match="watch_candidates"):
        provider.build_recommendations(
            recommendable_candidates=[_candidate("AAPL.NAS", role="recommendable")],
            watch_candidates=[
                _candidate("MSFT.NAS", role="watch_only"),
                _candidate("TSLA.NAS", role="watch_only"),
            ],
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
                        "source_refs": ["AAPL.NAS:1"],
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
                        "source_refs": ["MSFT.NAS:1"],
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


def test_openai_rejects_watch_candidate_with_skip_action_and_invalid_source_ref() -> (
    None
):
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
                        "source_refs": ["MSFT.NAS:404"],
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
                        "source_refs": ["MSFT.NAS:1"],
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
                        "source_refs": ["MSFT.NAS:1"],
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
                        "source_refs": ["MSFT.NAS:1"],
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
                        "source_refs": ["MSFT.NAS:1"],
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
                        "source_refs": ["MSFT.NAS:1"],
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


def test_openai_replaces_watch_candidate_with_invalid_source_ref_with_fallback() -> (
    None
):
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
                        "reason": "model watch reason",
                        "retrigger_conditions": ["model condition"],
                        "source_refs": ["MSFT.NAS:404"],
                    }
                ],
                "source_issues": [],
            }
        ),
    )

    result = provider.build_recommendations(
        recommendable_candidates=[_candidate("AAPL.NAS", role="recommendable")],
        watch_candidates=[
            _candidate(
                "MSFT.NAS",
                role="watch_only",
                ai_role_reason="entry trigger requires re-confirmation",
            )
        ],
    )

    assert result.watch_candidates[0]["ticker"] == "MSFT.NAS"
    assert result.watch_candidates[0]["action"] == "WATCH"
    assert result.watch_candidates[0]["reason"] == (
        "entry trigger requires re-confirmation"
    )
    assert result.watch_candidates[0]["retrigger_conditions"] == [
        "price must satisfy the original entry trigger again",
        "manual review must confirm source and market context",
    ]
    sources = result.watch_candidates[0]["sources"]
    assert isinstance(sources, list)
    assert sources[0]["title"] == "MSFT.NAS source"
    assert sources[0]["url"] == "https://news.example/MSFT.NAS"
    assert result.source_issues == [
        {
            "ticker": "MSFT.NAS",
            "code": "model_watch_source_ref_invalid",
            "severity": "WARN",
            "message": "watch row source_refs were invalid and fallback was used",
        }
    ]


def test_openai_resolves_watch_source_refs_to_canonical_sources() -> None:
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

    sources = result.watch_candidates[0]["sources"]
    assert isinstance(sources, list)
    assert sources[0]["title"] == "MSFT.NAS source"
    assert sources[0]["url"] == "https://news.example/MSFT.NAS"


def test_openai_rejects_duplicate_watch_source_refs() -> None:
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
                        "source_refs": ["MSFT.NAS:1", "MSFT.NAS:1"],
                    }
                ],
                "source_issues": [],
            }
        ),
    )

    with pytest.raises(AiBriefProviderContractError, match="duplicate source_refs"):
        provider.build_recommendations(
            recommendable_candidates=[_candidate("AAPL.NAS", role="recommendable")],
            watch_candidates=[_candidate("MSFT.NAS", role="watch_only")],
        )


def test_openai_resolves_recommendation_source_refs_to_canonical_sources() -> None:
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
                        "rationale": ["entry setup remains valid"],
                        "checklist": ["manually confirm price and risk before order"],
                        "source_refs": ["AAPL.NAS:1"],
                    }
                ],
                "vetoed_candidates": [],
                "watch_candidates": [],
                "source_issues": [],
            }
        ),
    )

    result = provider.build_recommendations(
        recommendable_candidates=[_candidate("AAPL.NAS", role="recommendable")],
        watch_candidates=[],
    )

    sources = result.recommendations[0]["sources"]
    assert isinstance(sources, list)
    assert sources[0]["title"] == "AAPL.NAS source"
    assert sources[0]["url"] == "https://news.example/AAPL.NAS"
    assert sources[0]["published_at"]


def test_openai_drops_recommendation_with_invalid_source_ref_and_reranks() -> None:
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
                        "rationale": ["bad source ref"],
                        "checklist": ["manually confirm price and risk before order"],
                        "source_refs": ["AAPL.NAS:404"],
                    },
                    {
                        "ticker": "MSFT.NAS",
                        "rank": 2,
                        "confidence": "LOW",
                        "rationale": ["valid source ref"],
                        "checklist": ["manually confirm price and risk before order"],
                        "source_refs": ["MSFT.NAS:1"],
                    },
                ],
                "vetoed_candidates": [],
                "watch_candidates": [],
                "source_issues": [],
            }
        ),
    )

    result = provider.build_recommendations(
        recommendable_candidates=[
            _candidate("AAPL.NAS", role="recommendable"),
            _candidate("MSFT.NAS", role="recommendable"),
        ],
        watch_candidates=[],
    )

    assert [row["ticker"] for row in result.recommendations] == ["MSFT.NAS"]
    assert result.recommendations[0]["rank"] == 1
    sources = result.recommendations[0]["sources"]
    assert isinstance(sources, list)
    assert sources[0]["title"] == "MSFT.NAS source"
    assert sources[0]["url"] == "https://news.example/MSFT.NAS"
    assert result.source_issues == [
        {
            "ticker": "AAPL.NAS",
            "code": "model_source_ref_invalid",
            "severity": "WARN",
            "message": "model returned source_refs not present in candidate.sources",
        }
    ]


def test_openai_rejects_non_string_source_ref_items() -> None:
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
                        "rationale": ["source ref has wrong item type"],
                        "checklist": ["manually confirm price and risk before order"],
                        "source_refs": [1],
                    }
                ],
                "vetoed_candidates": [],
                "watch_candidates": [],
                "source_issues": [],
            }
        ),
    )

    with pytest.raises(AiBriefProviderContractError, match="must be a string"):
        provider.build_recommendations(
            recommendable_candidates=[_candidate("AAPL.NAS", role="recommendable")],
            watch_candidates=[],
        )


def test_openai_rejects_duplicate_recommendation_source_refs() -> None:
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
                        "rationale": ["duplicate source refs"],
                        "checklist": ["manually confirm price and risk before order"],
                        "source_refs": ["AAPL.NAS:1", "AAPL.NAS:1"],
                    }
                ],
                "vetoed_candidates": [],
                "watch_candidates": [],
                "source_issues": [],
            }
        ),
    )

    with pytest.raises(AiBriefProviderContractError, match="duplicate source_refs"):
        provider.build_recommendations(
            recommendable_candidates=[_candidate("AAPL.NAS", role="recommendable")],
            watch_candidates=[],
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
