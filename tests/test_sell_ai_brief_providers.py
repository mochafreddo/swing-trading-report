from __future__ import annotations

import datetime as dt
import hashlib
import json

import pytest
import requests
from sab.sell_ai_brief_providers import (
    FakeSellAiBriefProvider,
    OpenAiSellAiBriefProvider,
    SellAiBriefProviderContractError,
    SellAiBriefProviderError,
    SellAiBriefProviderTimeoutError,
    build_sell_ai_brief_provider_trace_metadata,
)


def _fresh_published_at() -> str:
    return dt.datetime.now(dt.UTC).replace(microsecond=0).isoformat()


def _source(ticker: str, *, published_at: str | None = None) -> dict[str, object]:
    return {
        "title": f"{ticker} risk update",
        "url": f"https://news.example/{ticker}",
        "published_at": published_at or _fresh_published_at(),
    }


def _candidate(
    ticker: str,
    *,
    sell_action: str = "SELL",
    sources: list[dict[str, object]] | None = None,
) -> dict[str, object]:
    return {
        "ticker": ticker,
        "name": ticker,
        "sell_action": sell_action,
        "ai_role_reason": f"sell report action was {sell_action}",
        "deterministic_reasons": ["stop loss breached"],
        "last_price": 101.0,
        "pnl_pct": -0.08,
        "sources": [_source(ticker)] if sources is None else sources,
    }


def _json_hash(value: object) -> str:
    payload = json.dumps(value, sort_keys=True, separators=(",", ":")).encode()
    return "sha256:" + hashlib.sha256(payload).hexdigest()


def test_fake_provider_returns_judgments_and_trace_metadata() -> None:
    provider = FakeSellAiBriefProvider(model_name="fake-sell-ai-brief-v1")
    candidates = [
        _candidate("AAPL.NAS", sell_action="SELL"),
        _candidate("MSFT.NAS", sell_action="REVIEW", sources=[]),
    ]

    result = provider.build_judgments(actionable_candidates=candidates)

    assert [(row["ticker"], row["sell_action"]) for row in result.judgments] == [
        ("AAPL.NAS", "SELL"),
        ("MSFT.NAS", "REVIEW"),
    ]
    assert result.judgments[0]["ai_stance"] == "AGREE"
    assert result.judgments[1]["ai_stance"] == "CAUTION"
    assert result.source_issues == [
        {
            "ticker": "MSFT.NAS",
            "code": "fake_provider_no_external_sources",
            "severity": "WARN",
            "message": "fake provider는 외부 소스를 수집하지 않음",
        }
    ]
    assert result.trace_metadata is not None
    assert result.trace_metadata.request_status == "sent"
    assert result.trace_metadata.request_hash == _json_hash(
        {"model": "fake-sell-ai-brief-v1", "actionable_candidates": candidates}
    )


def test_fake_provider_rejects_hold_candidate() -> None:
    provider = FakeSellAiBriefProvider(model_name="fake-sell-ai-brief-v1")

    with pytest.raises(SellAiBriefProviderContractError, match="HOLD"):
        provider.build_judgments(
            actionable_candidates=[_candidate("MSFT.NAS", sell_action="HOLD")]
        )


def test_openai_payload_uses_source_refs_and_sell_action_schema() -> None:
    session = _CapturingSession(
        {
            "judgments": [
                {
                    "ticker": "AAPL.NAS",
                    "sell_action": "SELL",
                    "ai_stance": "AGREE",
                    "confidence": "LOW",
                    "rationale": ["risk remains aligned"],
                    "checklist": ["confirm size"],
                    "source_refs": ["AAPL.NAS:1"],
                }
            ],
            "vetoed_candidates": [],
            "source_issues": [],
        }
    )
    provider = OpenAiSellAiBriefProvider(
        model_name="gpt-test",
        api_key="test-key",
        timeout_seconds=1.0,
        session=session,
    )

    result = provider.build_judgments(
        actionable_candidates=[_candidate("AAPL.NAS", sell_action="SELL")]
    )

    request = session.requests[0]["json"]
    assert isinstance(request, dict)
    user_payload = json.loads(str(request["input"][1]["content"]))
    model_candidate = user_payload["actionable_candidates"][0]
    assert model_candidate["sources"][0]["source_id"] == "AAPL.NAS:1"
    assert result.judgments[0]["source_refs"] == ["AAPL.NAS:1"]
    assert result.judgments[0]["sources"] == [_source("AAPL.NAS")]

    schema = request["text"]["format"]["schema"]
    judgment_props = schema["properties"]["judgments"]["items"]["properties"]
    assert "source_refs" in judgment_props
    assert "sources" not in judgment_props
    assert judgment_props["ticker"] == {"type": "string", "enum": ["AAPL.NAS"]}
    assert judgment_props["sell_action"] == {"type": "string", "enum": ["SELL"]}


def test_openai_rejects_source_less_judgment_with_model_source_issue() -> None:
    provider = OpenAiSellAiBriefProvider(
        model_name="gpt-test",
        api_key="test-key",
        timeout_seconds=1.0,
        session=_CapturingSession(
            {
                "judgments": [
                    {
                        "ticker": "AAPL.NAS",
                        "sell_action": "SELL",
                        "ai_stance": "CAUTION",
                        "confidence": "LOW",
                        "rationale": ["model says source is missing"],
                        "checklist": ["manual source check"],
                        "source_refs": [],
                    }
                ],
                "vetoed_candidates": [],
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

    with pytest.raises(SellAiBriefProviderContractError, match="no sources"):
        provider.build_judgments(
            actionable_candidates=[
                _candidate("AAPL.NAS", sell_action="SELL", sources=[])
            ]
        )


def test_openai_contract_error_when_model_changes_sell_action() -> None:
    provider = OpenAiSellAiBriefProvider(
        model_name="gpt-test",
        api_key="test-key",
        timeout_seconds=1.0,
        session=_CapturingSession(
            {
                "judgments": [
                    {
                        "ticker": "AAPL.NAS",
                        "sell_action": "SELL_PARTIAL",
                        "ai_stance": "AGREE",
                        "confidence": "LOW",
                        "rationale": ["changed action"],
                        "checklist": ["manual check"],
                        "source_refs": ["AAPL.NAS:1"],
                    }
                ],
                "vetoed_candidates": [],
                "source_issues": [],
            }
        ),
    )

    with pytest.raises(SellAiBriefProviderContractError, match="sell_action"):
        provider.build_judgments(
            actionable_candidates=[_candidate("AAPL.NAS", sell_action="SELL")]
        )


def test_openai_contract_error_when_model_omits_actionable_candidate() -> None:
    provider = OpenAiSellAiBriefProvider(
        model_name="gpt-test",
        api_key="test-key",
        timeout_seconds=1.0,
        session=_CapturingSession(
            {"judgments": [], "vetoed_candidates": [], "source_issues": []}
        ),
    )

    with pytest.raises(SellAiBriefProviderContractError, match="cover"):
        provider.build_judgments(
            actionable_candidates=[_candidate("AAPL.NAS", sell_action="SELL")]
        )


def test_openai_contract_error_when_model_duplicates_vetoed_candidate() -> None:
    provider = OpenAiSellAiBriefProvider(
        model_name="gpt-test",
        api_key="test-key",
        timeout_seconds=1.0,
        session=_CapturingSession(
            {
                "judgments": [],
                "vetoed_candidates": [
                    {
                        "ticker": "AAPL.NAS",
                        "sell_action": "SELL",
                        "reason": "source confidence was too weak",
                    },
                    {
                        "ticker": "AAPL.NAS",
                        "sell_action": "SELL",
                        "reason": "duplicate veto",
                    },
                ],
                "source_issues": [],
            }
        ),
    )

    with pytest.raises(SellAiBriefProviderContractError, match="unique"):
        provider.build_judgments(
            actionable_candidates=[_candidate("AAPL.NAS", sell_action="SELL")]
        )


def test_openai_contract_error_when_invalid_source_refs_drop_candidate() -> None:
    provider = OpenAiSellAiBriefProvider(
        model_name="gpt-test",
        api_key="test-key",
        timeout_seconds=1.0,
        session=_CapturingSession(
            {
                "judgments": [
                    {
                        "ticker": "AAPL.NAS",
                        "sell_action": "SELL",
                        "ai_stance": "AGREE",
                        "confidence": "LOW",
                        "rationale": ["risk remains aligned"],
                        "checklist": ["manual check"],
                        "source_refs": ["AAPL.NAS:missing"],
                    }
                ],
                "vetoed_candidates": [],
                "source_issues": [],
            }
        ),
    )

    with pytest.raises(SellAiBriefProviderContractError, match="cover"):
        provider.build_judgments(
            actionable_candidates=[_candidate("AAPL.NAS", sell_action="SELL")]
        )


def test_openai_rejects_automated_order_language_in_source_issue_message() -> None:
    provider = OpenAiSellAiBriefProvider(
        model_name="gpt-test",
        api_key="test-key",
        timeout_seconds=1.0,
        session=_CapturingSession(
            {
                "judgments": [
                    {
                        "ticker": "AAPL.NAS",
                        "sell_action": "SELL",
                        "ai_stance": "AGREE",
                        "confidence": "LOW",
                        "rationale": ["risk remains aligned"],
                        "checklist": ["manual check"],
                        "source_refs": ["AAPL.NAS:1"],
                    }
                ],
                "vetoed_candidates": [],
                "source_issues": [
                    {
                        "ticker": "AAPL.NAS",
                        "code": "model_diagnostic",
                        "severity": "WARN",
                        "message": "지금 매도하세요",
                    }
                ],
            }
        ),
    )

    with pytest.raises(SellAiBriefProviderContractError, match="automated-order"):
        provider.build_judgments(
            actionable_candidates=[_candidate("AAPL.NAS", sell_action="SELL")]
        )


def test_openai_empty_input_returns_planned_not_sent_trace_metadata() -> None:
    session = _CapturingSession(
        {"judgments": [], "vetoed_candidates": [], "source_issues": []}
    )
    provider = OpenAiSellAiBriefProvider(
        model_name="gpt-test",
        api_key="test-key",
        timeout_seconds=1.0,
        session=session,
    )

    result = provider.build_judgments(actionable_candidates=[])

    assert session.requests == []
    assert result.trace_metadata is not None
    assert result.trace_metadata.request_status == "planned_not_sent"


def test_openai_timeout_error_carries_trace_metadata() -> None:
    session = _TimeoutSession()
    provider = OpenAiSellAiBriefProvider(
        model_name="gpt-test",
        api_key="test-key",
        timeout_seconds=1.0,
        session=session,
    )

    with pytest.raises(SellAiBriefProviderTimeoutError) as excinfo:
        provider.build_judgments(
            actionable_candidates=[_candidate("AAPL.NAS", sell_action="SELL")]
        )

    request = session.requests[0]["json"]
    assert isinstance(request, dict)
    assert excinfo.value.trace_metadata is not None
    assert excinfo.value.trace_metadata.request_hash == _json_hash(request)


def test_openai_http_error_message_omits_raw_response_body() -> None:
    session = _HttpErrorSession(
        status_code=500,
        text=(
            '{"error":{"message":"bad key sk-secret-123",'
            '"code":"server_error","type":"api_error"}}'
        ),
        payload={
            "error": {
                "message": "bad key sk-secret-123",
                "code": "server_error",
                "type": "api_error",
            }
        },
    )
    provider = OpenAiSellAiBriefProvider(
        model_name="gpt-test",
        api_key="test-key",
        timeout_seconds=1.0,
        session=session,
    )

    with pytest.raises(SellAiBriefProviderError) as excinfo:
        provider.build_judgments(
            actionable_candidates=[_candidate("AAPL.NAS", sell_action="SELL")]
        )

    message = str(excinfo.value)
    assert "HTTP 500" in message
    assert "server_error" in message
    assert "api_error" in message
    assert "sk-secret-123" not in message
    assert "bad key" not in message


def test_planned_trace_hashes_would_send_request_shape() -> None:
    candidate = _candidate("AAPL.NAS", sell_action="SELL")

    planned = build_sell_ai_brief_provider_trace_metadata(
        model_provider="openai",
        model_name="gpt-test",
        actionable_candidates=[candidate],
        request_status="planned_not_sent",
    )
    sent = build_sell_ai_brief_provider_trace_metadata(
        model_provider="openai",
        model_name="gpt-test",
        actionable_candidates=[candidate],
        request_status="sent",
    )

    assert planned.request_status == "planned_not_sent"
    assert planned.request_hash == sent.request_hash
    assert planned.source_catalog_hash == sent.source_catalog_hash


class _Response:
    status_code = 200
    text = "ok"

    def __init__(self, payload: object) -> None:
        self._payload = payload

    def json(self) -> object:
        return {"output_text": json.dumps(self._payload)}


class _CapturingSession:
    def __init__(self, payload: object) -> None:
        self._payload = payload
        self.requests: list[dict[str, object]] = []

    def post(self, url: str, **kwargs: object) -> _Response:
        self.requests.append({"url": url, **kwargs})
        return _Response(self._payload)


class _DefaultSession:
    def __init__(self) -> None:
        self.trust_env = True


def test_openai_default_session_disables_trust_env(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    session = _DefaultSession()
    monkeypatch.setattr("sab.sell_ai_brief_providers.requests.Session", lambda: session)

    OpenAiSellAiBriefProvider(
        model_name="gpt-test",
        api_key="test-key",
        timeout_seconds=1.0,
    )

    assert session.trust_env is False


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
        raise requests.RequestException("failed")


class _HttpErrorResponse:
    def __init__(
        self,
        *,
        status_code: int,
        text: str,
        payload: dict[str, object],
    ) -> None:
        self.status_code = status_code
        self.text = text
        self._payload = payload

    def json(self) -> dict[str, object]:
        return self._payload


class _HttpErrorSession:
    def __init__(
        self,
        *,
        status_code: int,
        text: str,
        payload: dict[str, object],
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


def test_openai_request_error_carries_trace_metadata() -> None:
    session = _RequestExceptionSession()
    provider = OpenAiSellAiBriefProvider(
        model_name="gpt-test",
        api_key="test-key",
        timeout_seconds=1.0,
        session=session,
    )

    with pytest.raises(SellAiBriefProviderError) as excinfo:
        provider.build_judgments(
            actionable_candidates=[_candidate("AAPL.NAS", sell_action="SELL")]
        )

    request = session.requests[0]["json"]
    assert isinstance(request, dict)
    assert excinfo.value.trace_metadata is not None
    assert excinfo.value.trace_metadata.request_hash == _json_hash(request)
