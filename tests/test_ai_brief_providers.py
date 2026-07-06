from __future__ import annotations

import datetime as dt
import hashlib
import json

import pytest
import requests
from sab.ai_brief_providers import (
    AiBriefProviderContractError,
    AiBriefProviderError,
    AiBriefProviderTimeoutError,
    FakeAiBriefProvider,
    OpenAiBriefProvider,
    build_ai_brief_provider_trace_metadata,
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


def _json_hash(value: object) -> str:
    payload = json.dumps(value, sort_keys=True, separators=(",", ":")).encode()
    return "sha256:" + hashlib.sha256(payload).hexdigest()


def test_fake_provider_returns_watch_candidates_separately() -> None:
    provider = FakeAiBriefProvider(model_name="fake-ai-brief-v1")

    result = provider.build_recommendations(
        recommendable_candidates=[_candidate("AAPL.NAS", role="recommendable")],
        watch_candidates=[_candidate("MSFT.NAS", role="watch_only")],
    )

    assert [row["ticker"] for row in result.recommendations] == ["AAPL.NAS"]
    assert [row["ticker"] for row in result.watch_candidates] == ["MSFT.NAS"]
    assert result.watch_candidates[0]["action"] == "WATCH"


def test_fake_provider_returns_deterministic_trace_metadata() -> None:
    provider = FakeAiBriefProvider(model_name="fake-ai-brief-v1")
    recommendable_candidate = _candidate("AAPL.NAS", role="recommendable")
    watch_candidate = _candidate("MSFT.NAS", role="watch_only")

    result = provider.build_recommendations(
        recommendable_candidates=[recommendable_candidate],
        watch_candidates=[watch_candidate],
    )

    trace_metadata = result.trace_metadata
    assert trace_metadata is not None
    assert trace_metadata.prompt_version == "fake-ai-brief-v1"
    assert trace_metadata.output_schema_version == "fake-ai-brief-output-v1"
    assert trace_metadata.request_status == "sent"
    assert trace_metadata.request_hash == _json_hash(
        {
            "model": "fake-ai-brief-v1",
            "recommendable_candidates": [recommendable_candidate],
            "watch_candidates": [watch_candidate],
        }
    )
    assert trace_metadata.source_catalog_hash == _json_hash(
        {
            "recommendable_candidates": [recommendable_candidate],
            "watch_candidates": [watch_candidate],
        }
    )


def test_fake_provider_contract_error_after_result_build_carries_trace_metadata() -> (
    None
):
    provider = FakeAiBriefProvider(model_name="fake-ai-brief-v1")
    stale_candidate = _candidate(
        "AAPL.NAS",
        role="recommendable",
        published_at=_published_at(-dt.timedelta(hours=73)),
    )

    with pytest.raises(AiBriefProviderContractError) as excinfo:
        provider.build_recommendations(
            recommendable_candidates=[stale_candidate],
            watch_candidates=[],
        )

    trace_metadata = excinfo.value.trace_metadata
    assert trace_metadata is not None
    assert trace_metadata.request_status == "sent"
    assert trace_metadata.request_hash == _json_hash(
        {
            "model": "fake-ai-brief-v1",
            "recommendable_candidates": [stale_candidate],
            "watch_candidates": [],
        }
    )


def test_fake_provider_localizes_known_watch_fallback_reason() -> None:
    provider = FakeAiBriefProvider(model_name="fake-ai-brief-v1")

    result = provider.build_recommendations(
        recommendable_candidates=[],
        watch_candidates=[
            _candidate(
                "MSFT.NAS",
                role="watch_only",
                ai_role_reason="entry trigger is pending re-confirmation",
            )
        ],
    )

    assert result.watch_candidates[0]["reason"] == "진입 트리거 재확인이 필요함"


def test_fake_provider_preserves_custom_watch_reason() -> None:
    provider = FakeAiBriefProvider(model_name="fake-ai-brief-v1")

    result = provider.build_recommendations(
        recommendable_candidates=[],
        watch_candidates=[
            _candidate(
                "MSFT.NAS",
                role="watch_only",
                ai_role_reason="post-earnings source context needs review",
            )
        ],
    )

    assert (
        result.watch_candidates[0]["reason"]
        == "post-earnings source context needs review"
    )


def test_fake_provider_localizes_no_source_issue_message() -> None:
    provider = FakeAiBriefProvider(model_name="fake-ai-brief-v1")
    candidate = _candidate("AAPL.NAS", role="recommendable")
    candidate["sources"] = []

    result = provider.build_recommendations(
        recommendable_candidates=[candidate],
        watch_candidates=[],
    )

    assert result.source_issues == [
        {
            "ticker": "AAPL.NAS",
            "code": "fake_provider_no_external_sources",
            "severity": "WARN",
            "message": "fake provider는 외부 소스를 수집하지 않음",
        }
    ]


def test_openai_drops_source_less_recommendation_with_model_source_issue() -> None:
    candidate = _candidate("AAPL.NAS", role="recommendable")
    candidate["sources"] = []
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
                        "rationale": ["model says source is missing"],
                        "checklist": ["manual source check"],
                        "source_refs": [],
                    }
                ],
                "vetoed_candidates": [],
                "watch_candidates": [],
                "source_issues": [
                    {
                        "ticker": "AAPL.NAS",
                        "code": "openai_no_sources",
                        "severity": "WARN",
                        "message": "모델이 소스 없음 문제를 보고함",
                    }
                ],
            }
        ),
    )

    result = provider.build_recommendations(
        recommendable_candidates=[candidate],
        watch_candidates=[],
    )

    assert result.recommendations == []
    assert [issue["code"] for issue in result.source_issues] == [
        "openai_no_sources",
        "model_unbacked_recommendation_dropped",
    ]


def test_openai_rewrites_source_issue_for_ineligible_ticker() -> None:
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
                        "rationale": ["risk remains aligned"],
                        "checklist": ["manual check"],
                        "source_refs": ["AAPL.NAS:1"],
                    }
                ],
                "vetoed_candidates": [],
                "watch_candidates": [],
                "source_issues": [
                    {
                        "ticker": "TSLA.NAS",
                        "code": "model_claimed_external_problem",
                        "severity": "WARN",
                        "message": "TSLA source is missing",
                    }
                ],
            }
        ),
    )

    result = provider.build_recommendations(
        recommendable_candidates=[_candidate("AAPL.NAS", role="recommendable")],
        watch_candidates=[],
    )

    assert all(issue.get("ticker") != "TSLA.NAS" for issue in result.source_issues)
    assert result.source_issues == [
        {
            "code": "model_ineligible_source_issue_dropped",
            "severity": "WARN",
            "message": "모델이 입력 후보 밖의 source issue를 반환해 해당 이슈를 제외함",
            "dropped_tickers": ["TSLA.NAS"],
        }
    ]


def test_openai_rejects_duplicate_recommendable_tickers_before_request() -> None:
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

    with pytest.raises(AiBriefProviderContractError, match="unique"):
        provider.build_recommendations(
            recommendable_candidates=[
                _candidate("AAPL.NAS", role="recommendable"),
                _candidate("AAPL.NAS", role="recommendable"),
            ],
            watch_candidates=[],
        )

    assert session.requests == []


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
    assert "AI Brief 포함 사유: 포트폴리오 정책으로 자동 진입 차단" in rationale_text
    assert "AI Brief 포함 사유: 위험 정렬 문제로 수동 검토 필요" in rationale_text
    assert "portfolio policy blocked automatic entry" not in rationale_text
    assert "risk alignment requires manual review" not in rationale_text
    assert "진입 갭 스냅샷: 1.00%" in rationale_text
    assert "수동 검토용 로컬 소스 맥락 있음" in rationale_text
    assert "AI brief inclusion" not in rationale_text
    assert "entry gap snapshot" not in rationale_text
    assert "local source context is available" not in rationale_text
    assert "entry report marked this candidate ENTER" not in rationale_text
    assert result.recommendations[0]["candidate_role"] == "blocked_but_valid"
    assert result.recommendations[0]["entry_action"] == "SKIP"
    assert result.recommendations[0]["candidate_role_reason"] == (
        "portfolio policy blocked automatic entry"
    )
    assert result.recommendations[1]["candidate_role"] == "blocked_but_valid"
    assert result.recommendations[1]["entry_action"] == "REVIEW"
    assert result.recommendations[1]["candidate_role_reason"] == (
        "risk alignment requires manual review"
    )


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


def test_openai_result_includes_trace_metadata_for_sent_request() -> None:
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

    result = provider.build_recommendations(
        recommendable_candidates=[_candidate("AAPL.NAS", role="recommendable")],
        watch_candidates=[],
    )

    request = session.requests[0]["json"]
    assert isinstance(request, dict)
    user_payload = json.loads(str(request["input"][1]["content"]))
    trace_metadata = result.trace_metadata
    assert trace_metadata is not None
    assert trace_metadata.prompt_version == "openai-ai-brief-v1"
    assert trace_metadata.output_schema_version == "openai-ai-brief-output-v1"
    assert trace_metadata.request_status == "sent"
    assert trace_metadata.request_hash == _json_hash(request)
    assert trace_metadata.source_catalog_hash == _json_hash(
        {
            "recommendable_candidates": user_payload["recommendable_candidates"],
            "watch_candidates": user_payload["watch_candidates"],
        }
    )


def test_openai_planned_trace_hashes_would_send_request_shape() -> None:
    recommendable_candidate = _candidate("AAPL.NAS", role="recommendable")
    watch_candidate = _candidate("MSFT.NAS", role="watch_only")

    planned = build_ai_brief_provider_trace_metadata(
        model_provider="openai",
        model_name="gpt-test",
        recommendable_candidates=[recommendable_candidate],
        watch_candidates=[watch_candidate],
        request_status="planned_not_sent",
    )
    sent = build_ai_brief_provider_trace_metadata(
        model_provider="openai",
        model_name="gpt-test",
        recommendable_candidates=[recommendable_candidate],
        watch_candidates=[watch_candidate],
        request_status="sent",
    )

    assert planned.request_status == "planned_not_sent"
    assert planned.request_hash == sent.request_hash
    assert planned.source_catalog_hash == sent.source_catalog_hash


def test_openai_empty_input_returns_planned_not_sent_trace_metadata() -> None:
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

    result = provider.build_recommendations(
        recommendable_candidates=[],
        watch_candidates=[],
    )

    assert session.requests == []
    trace_metadata = result.trace_metadata
    assert trace_metadata is not None
    assert trace_metadata.request_status == "planned_not_sent"
    assert trace_metadata.prompt_version == "openai-ai-brief-v1"
    assert trace_metadata.output_schema_version == "openai-ai-brief-output-v1"
    assert trace_metadata.source_catalog_hash == _json_hash(
        {"recommendable_candidates": [], "watch_candidates": []}
    )


def test_openai_preflight_contract_error_carries_planned_trace_metadata() -> None:
    session = _CapturingSession(
        {
            "recommendations": [],
            "vetoed_candidates": [],
            "watch_candidates": [],
            "source_issues": [],
        }
    )
    recommendable_candidate = _candidate("AAPL.NAS", role="recommendable")
    watch_candidate = _candidate("AAPL.NAS", role="watch_only")
    provider = OpenAiBriefProvider(
        model_name="gpt-test",
        api_key="test-key",
        timeout_seconds=1.0,
        session=session,
    )

    with pytest.raises(AiBriefProviderContractError) as excinfo:
        provider.build_recommendations(
            recommendable_candidates=[recommendable_candidate],
            watch_candidates=[watch_candidate],
        )

    assert session.requests == []
    trace_metadata = excinfo.value.trace_metadata
    assert trace_metadata is not None
    assert trace_metadata.request_status == "planned_not_sent"
    assert (
        trace_metadata.source_catalog_hash
        == build_ai_brief_provider_trace_metadata(
            model_provider="openai",
            model_name="gpt-test",
            recommendable_candidates=[recommendable_candidate],
            watch_candidates=[watch_candidate],
            request_status="sent",
        ).source_catalog_hash
    )


def test_openai_normalized_rows_preserve_validated_source_refs() -> None:
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

    assert result.recommendations[0]["source_refs"] == ["AAPL.NAS:1"]
    assert result.watch_candidates[0]["source_refs"] == ["MSFT.NAS:1"]


def test_openai_payload_rejects_same_ticker_candidate_sources_before_request() -> None:
    first_candidate = _candidate("AAPL.NAS", role="recommendable")
    second_candidate = _candidate("AAPL.NAS", role="recommendable", action="REVIEW")
    first_candidate["sources"] = [
        {
            "title": "first candidate source",
            "url": "https://news.example/aapl-first",
            "published_at": _fresh_published_at(),
        }
    ]
    second_candidate["sources"] = [
        {
            "title": "second candidate source",
            "url": "https://news.example/aapl-second",
            "published_at": _fresh_published_at(),
        }
    ]
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

    with pytest.raises(AiBriefProviderContractError, match="unique"):
        provider.build_recommendations(
            recommendable_candidates=[first_candidate, second_candidate],
            watch_candidates=[],
        )

    assert session.requests == []


def test_openai_timeout_error_carries_trace_metadata() -> None:
    session = _TimeoutSession()
    provider = OpenAiBriefProvider(
        model_name="gpt-test",
        api_key="test-key",
        timeout_seconds=1.0,
        session=session,
    )

    with pytest.raises(AiBriefProviderTimeoutError) as excinfo:
        provider.build_recommendations(
            recommendable_candidates=[_candidate("AAPL.NAS", role="recommendable")],
            watch_candidates=[],
        )

    request = session.requests[0]["json"]
    assert isinstance(request, dict)
    trace_metadata = excinfo.value.trace_metadata
    assert trace_metadata is not None
    assert trace_metadata.request_status == "sent"
    assert trace_metadata.request_hash == _json_hash(request)


def test_openai_request_error_carries_trace_metadata() -> None:
    session = _RequestExceptionSession()
    provider = OpenAiBriefProvider(
        model_name="gpt-test",
        api_key="test-key",
        timeout_seconds=1.0,
        session=session,
    )

    with pytest.raises(AiBriefProviderError) as excinfo:
        provider.build_recommendations(
            recommendable_candidates=[_candidate("AAPL.NAS", role="recommendable")],
            watch_candidates=[],
        )

    request = session.requests[0]["json"]
    assert isinstance(request, dict)
    trace_metadata = excinfo.value.trace_metadata
    assert trace_metadata is not None
    assert trace_metadata.request_status == "sent"
    assert trace_metadata.request_hash == _json_hash(request)


def test_openai_http_error_carries_trace_metadata() -> None:
    session = _HttpErrorSession()
    provider = OpenAiBriefProvider(
        model_name="gpt-test",
        api_key="test-key",
        timeout_seconds=1.0,
        session=session,
    )

    with pytest.raises(AiBriefProviderError) as excinfo:
        provider.build_recommendations(
            recommendable_candidates=[_candidate("AAPL.NAS", role="recommendable")],
            watch_candidates=[],
        )

    request = session.requests[0]["json"]
    assert isinstance(request, dict)
    trace_metadata = excinfo.value.trace_metadata
    assert trace_metadata is not None
    assert trace_metadata.request_status == "sent"
    assert trace_metadata.request_hash == _json_hash(request)


def test_openai_http_error_message_omits_raw_response_body() -> None:
    session = _HttpErrorSession(
        status_code=429,
        text=(
            '{"error":{"message":"bad key sk-secret-123",'
            '"code":"rate_limit_exceeded","type":"requests"}}'
        ),
        payload={
            "error": {
                "message": "bad key sk-secret-123",
                "code": "rate_limit_exceeded",
                "type": "requests",
            }
        },
    )
    provider = OpenAiBriefProvider(
        model_name="gpt-test",
        api_key="test-key",
        timeout_seconds=1.0,
        session=session,
    )

    with pytest.raises(AiBriefProviderError) as excinfo:
        provider.build_recommendations(
            recommendable_candidates=[_candidate("AAPL.NAS", role="recommendable")],
            watch_candidates=[],
        )

    message = str(excinfo.value)
    assert "HTTP 429" in message
    assert "rate_limit_exceeded" in message
    assert "requests" in message
    assert "sk-secret-123" not in message
    assert "bad key" not in message


def test_openai_contract_error_carries_trace_metadata() -> None:
    session = _InvalidStructuredOutputSession()
    provider = OpenAiBriefProvider(
        model_name="gpt-test",
        api_key="test-key",
        timeout_seconds=1.0,
        session=session,
    )

    with pytest.raises(AiBriefProviderContractError) as excinfo:
        provider.build_recommendations(
            recommendable_candidates=[_candidate("AAPL.NAS", role="recommendable")],
            watch_candidates=[],
        )

    request = session.requests[0]["json"]
    assert isinstance(request, dict)
    trace_metadata = excinfo.value.trace_metadata
    assert trace_metadata is not None
    assert trace_metadata.request_status == "sent"
    assert trace_metadata.request_hash == _json_hash(request)


def test_openai_prompt_requires_korean_display_fields() -> None:
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
    request_input = request["input"]
    assert isinstance(request_input, list)
    system_message = request_input[0]
    assert isinstance(system_message, dict)
    system_content = str(system_message["content"])
    assert "Write user-facing display fields in Korean" in system_content
    assert "recommendations[].rationale" in system_content
    assert "recommendations[].checklist" in system_content
    assert "vetoed_candidates[].reason" in system_content
    assert "watch_candidates[].reason" in system_content
    assert "watch_candidates[].retrigger_conditions" in system_content
    assert "source_issues[].message" in system_content
    assert "Keep ticker symbols" in system_content
    assert "confidence/action enum values" in system_content
    assert "issue codes and severities" in system_content
    assert "source_refs" in system_content
    assert "article titles, URLs, and published dates unchanged" in system_content


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
    assert "투자 준비 상태에 추가 확인 필요: CONTEXT_REQUIRED" in rationale
    assert (
        "NAV/위험 예산, 청산 유동성, 포트폴리오 노출, 소스 맥락을 행동 전 확인"
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


def test_openai_drops_watch_veto_before_action_and_reason_validation() -> None:
    provider = OpenAiBriefProvider(
        model_name="gpt-test",
        api_key="test-key",
        timeout_seconds=1.0,
        session=_CapturingSession(
            {
                "recommendations": [],
                "vetoed_candidates": [{"ticker": "MSFT.NAS", "action": "WATCH"}],
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
            "message": "모델이 eligible_tickers 밖의 제외 후보를 반환해 해당 행을 제외함",
        }
    ]


def test_openai_drops_unknown_veto_before_action_and_reason_validation() -> None:
    provider = OpenAiBriefProvider(
        model_name="gpt-test",
        api_key="test-key",
        timeout_seconds=1.0,
        session=_CapturingSession(
            {
                "recommendations": [],
                "vetoed_candidates": [{"ticker": "MSFT.NAS", "action": "WATCH"}],
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
            "message": "모델이 eligible_tickers 밖의 제외 후보를 반환해 해당 행을 제외함",
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


def test_openai_rejects_missing_veto_reason_for_known_ticker() -> None:
    provider = OpenAiBriefProvider(
        model_name="gpt-test",
        api_key="test-key",
        timeout_seconds=1.0,
        session=_CapturingSession(
            {
                "recommendations": [],
                "vetoed_candidates": [{"ticker": "AAPL.NAS", "action": "SKIP"}],
                "watch_candidates": [],
                "source_issues": [],
            }
        ),
    )

    with pytest.raises(AiBriefProviderContractError, match="reason is required"):
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


def test_openai_rejects_source_issue_with_automated_order_language() -> None:
    provider = OpenAiBriefProvider(
        model_name="gpt-test",
        api_key="test-key",
        timeout_seconds=1.0,
        session=_CapturingSession(
            {
                "recommendations": [],
                "vetoed_candidates": [],
                "watch_candidates": [],
                "source_issues": [
                    {
                        "ticker": "AAPL.NAS",
                        "code": "model_warning",
                        "severity": "WARN",
                        "message": "buy now because source coverage is weak",
                    }
                ],
            }
        ),
    )

    with pytest.raises(AiBriefProviderContractError, match="automated-order"):
        provider.build_recommendations(
            recommendable_candidates=[_candidate("AAPL.NAS", role="recommendable")],
            watch_candidates=[],
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
        "가격이 원래 진입 트리거를 다시 충족해야 함",
        "소스와 시장 맥락을 수동 확인해야 함",
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
            "message": "watch row의 source_refs가 유효하지 않아 대체 행을 사용함",
            "source_refs": ["MSFT.NAS:404"],
            "invalid_source_refs": ["MSFT.NAS:404"],
        }
    ]


def test_openai_localizes_known_watch_fallback_reason_after_invalid_source_ref() -> (
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
        recommendable_candidates=[],
        watch_candidates=[
            _candidate(
                "MSFT.NAS",
                role="watch_only",
                ai_role_reason="entry trigger is pending re-confirmation",
            )
        ],
    )

    assert result.watch_candidates[0]["reason"] == "진입 트리거 재확인이 필요함"
    assert result.source_issues == [
        {
            "ticker": "MSFT.NAS",
            "code": "model_watch_source_ref_invalid",
            "severity": "WARN",
            "message": "watch row의 source_refs가 유효하지 않아 대체 행을 사용함",
            "source_refs": ["MSFT.NAS:404"],
            "invalid_source_refs": ["MSFT.NAS:404"],
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
            "message": "모델이 candidate.sources에 없는 source_refs를 반환함",
            "source_refs": ["AAPL.NAS:404"],
            "invalid_source_refs": ["AAPL.NAS:404"],
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


class _OversizedResponse:
    status_code = 200
    text = "x" * (1024 * 1024 + 1)

    def __init__(self, payload: dict[str, object]) -> None:
        self._payload = payload

    def json(self) -> dict[str, object]:
        return {"output_text": json.dumps(self._payload)}


class _OversizedResponseSession:
    def __init__(self, payload: dict[str, object]) -> None:
        self.payload = payload
        self.requests: list[dict[str, object]] = []

    def post(self, url: str, **kwargs: object) -> _OversizedResponse:
        self.requests.append({"url": url, **kwargs})
        return _OversizedResponse(self.payload)


class _DefaultSession:
    def __init__(self) -> None:
        self.trust_env = True


def test_openai_default_session_disables_trust_env(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    session = _DefaultSession()
    monkeypatch.setattr("sab.ai_brief_providers.requests.Session", lambda: session)

    OpenAiBriefProvider(
        model_name="gpt-test",
        api_key="test-key",
        timeout_seconds=1.0,
    )

    assert session.trust_env is False


def test_openai_rejects_oversized_response_body() -> None:
    provider = OpenAiBriefProvider(
        model_name="gpt-test",
        api_key="test-key",
        timeout_seconds=1.0,
        session=_OversizedResponseSession(
            {
                "recommendations": [],
                "vetoed_candidates": [],
                "watch_candidates": [],
                "source_issues": [],
            }
        ),
    )

    with pytest.raises(
        AiBriefProviderContractError, match="response body is too large"
    ):
        provider.build_recommendations(
            recommendable_candidates=[_candidate("AAPL.NAS", role="recommendable")],
            watch_candidates=[],
        )


class _TimeoutSession:
    def __init__(self) -> None:
        self.requests: list[dict[str, object]] = []

    def post(self, url: str, **kwargs: object) -> _Response:
        self.requests.append({"url": url, **kwargs})
        raise requests.Timeout("timed out")


class _RequestExceptionSession:
    def __init__(self) -> None:
        self.requests: list[dict[str, object]] = []

    def post(self, url: str, **kwargs: object) -> _Response:
        self.requests.append({"url": url, **kwargs})
        raise requests.ConnectionError("connection reset")


class _HttpErrorResponse:
    def __init__(
        self,
        *,
        status_code: int = 429,
        text: str = "rate limited",
        payload: dict[str, object] | None = None,
    ) -> None:
        self.status_code = status_code
        self.text = text
        self._payload = {} if payload is None else payload

    def json(self) -> dict[str, object]:
        return self._payload


class _HttpErrorSession:
    def __init__(
        self,
        *,
        status_code: int = 429,
        text: str = "rate limited",
        payload: dict[str, object] | None = None,
    ) -> None:
        self.requests: list[dict[str, object]] = []
        self._response = _HttpErrorResponse(
            status_code=status_code,
            text=text,
            payload=payload,
        )

    def post(self, url: str, **kwargs: object) -> _HttpErrorResponse:
        self.requests.append({"url": url, **kwargs})
        return self._response


class _InvalidStructuredOutputResponse:
    status_code = 200
    text = "not json"

    def json(self) -> dict[str, object]:
        return {"output_text": "not json"}


class _InvalidStructuredOutputSession:
    def __init__(self) -> None:
        self.requests: list[dict[str, object]] = []

    def post(self, url: str, **kwargs: object) -> _InvalidStructuredOutputResponse:
        self.requests.append({"url": url, **kwargs})
        return _InvalidStructuredOutputResponse()
