from __future__ import annotations

import asyncio
import copy
import json
from datetime import UTC, datetime
from pathlib import Path

import pytest
from sab.decision_board.claims import (
    ClaimRequestV0,
    ClaimValidationFailedV0,
    ClaimValidationSucceededV0,
    ClaimValidationTimedOutV0,
    ClaimVerifierRequestV0,
    ClaimVerifierTimeoutError,
    EntailmentV0,
    validate_claim_v0,
)
from sab.decision_board.instruments import InstrumentRefV0
from sab.research.contracts import (
    ResearchSourcePolicyV0,
    SourcePurposeV0,
    create_source_candidate_v0,
)
from sab.research.deadline import Deadline
from sab.research.source_safety import create_article_artifact_v0

FIXTURE = (
    Path(__file__).parent
    / "fixtures"
    / "decision_board"
    / "claim-verifier-responses-recorded.json"
)
ARTICLE_TEXT = "Aurora beat guidance. Aurora beat guidance. Café demand is stable."
_RESPONSE_FIELDS = {"id", "object", "status", "model", "output"}
_MESSAGE_FIELDS = {"type", "role", "content"}
_CONTENT_FIELDS = {"type", "text"}


def _recording() -> dict[str, object]:
    value = json.loads(FIXTURE.read_text(encoding="utf-8"))
    assert type(value) is dict
    return value


def _instrument() -> InstrumentRefV0:
    return InstrumentRefV0(
        market="US",
        canonical_ticker="AUR.NAS",
        exchange="NASDAQ",
        company_name="Aurora Synthetic Systems",
        identity_source="synthetic-directory",
        identity_version="fixture-2026-08-13",
    )


def _inputs():
    instrument = _instrument()
    policy = ResearchSourcePolicyV0()
    source = create_source_candidate_v0(
        instrument=instrument,
        title="Synthetic quarterly update",
        canonical_url="https://evidence.example/aurora/update",
        publisher="Synthetic Wire",
        published_at=datetime(2026, 8, 13, 1, 2, 3, tzinfo=UTC),
        purpose=SourcePurposeV0.ACTION_CHANGING,
    )
    article = create_article_artifact_v0(
        source=source,
        final_url="https://evidence.example/aurora/final-update",
        normalized_text=ARTICLE_TEXT,
        policy=policy,
    )
    request = ClaimRequestV0(
        claim_id="claim-aurora-guidance",
        instrument=instrument,
        claim_text="Aurora raised its synthetic guidance.",
        action_changing=True,
    )
    return request, source, article, policy


class _RecordedResponsesVerifier:
    """Strict offline adapter for the recorded Responses-style wire shape."""

    def __init__(self, recording: object, case: str) -> None:
        if type(recording) is not dict or set(recording) != {
            "schema",
            "model",
            "cases",
        }:
            raise ValueError("recording contract is invalid")
        if recording["schema"] != "openai.responses.recorded.v0":
            raise ValueError("recording schema is invalid")
        model = recording["model"]
        cases = recording["cases"]
        if type(model) is not str or type(cases) is not dict or case not in cases:
            raise ValueError("recording identity is invalid")
        self._model = model
        self._case = copy.deepcopy(cases[case])
        self.requests: list[dict[str, object]] = []

    async def verify(
        self,
        request: ClaimVerifierRequestV0,
        *,
        deadline: Deadline,
        timeout: float,
    ) -> object:
        public = request.to_public_dict()
        wire_request: dict[str, object] = {
            "model": self._model,
            "input": [
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "input_text",
                            "text": json.dumps(
                                public,
                                ensure_ascii=False,
                                sort_keys=True,
                                separators=(",", ":"),
                            ),
                        }
                    ],
                }
            ],
            "deadline": {
                "timeout_seconds": timeout,
                "expires_at_monotonic": deadline.expires_at,
            },
        }
        self.requests.append(wire_request)
        case = self._case
        if type(case) is not dict or set(case) not in ({"response"}, {"failure"}):
            raise RuntimeError("recorded case is invalid")
        if "failure" in case:
            failure = case["failure"]
            if type(failure) is not dict or set(failure) != {"kind"}:
                raise RuntimeError("recorded failure is invalid")
            if failure["kind"] == "timeout":
                raise ClaimVerifierTimeoutError("recorded timeout")
            raise RuntimeError("recorded unexpected failure")
        response = case["response"]
        if type(response) is not dict or set(response) != _RESPONSE_FIELDS:
            raise RuntimeError("recorded response is invalid")
        if (
            response["object"] != "response"
            or response["status"] != "completed"
            or response["model"] != self._model
            or type(response["id"]) is not str
        ):
            raise RuntimeError("recorded response identity is invalid")
        output = response["output"]
        if type(output) is not list or len(output) != 1:
            raise RuntimeError("recorded response output is invalid")
        message = output[0]
        if (
            type(message) is not dict
            or set(message) != _MESSAGE_FIELDS
            or message["type"] != "message"
            or message["role"] != "assistant"
        ):
            raise RuntimeError("recorded response message is invalid")
        content = message["content"]
        if type(content) is not list or len(content) != 1:
            raise RuntimeError("recorded response content is invalid")
        text = content[0]
        if (
            type(text) is not dict
            or set(text) != _CONTENT_FIELDS
            or text["type"] != "output_text"
            or type(text["text"]) is not str
        ):
            raise RuntimeError("recorded response text is invalid")
        try:
            return json.loads(text["text"])
        except json.JSONDecodeError:
            return {}


def _run(case: str, *, recording: object | None = None):
    request, source, article, policy = _inputs()
    verifier = _RecordedResponsesVerifier(recording or _recording(), case)
    result = asyncio.run(
        validate_claim_v0(
            request,
            article,
            expected_source=source,
            policy=policy,
            verifier=verifier,
            deadline=Deadline.start(monotonic=lambda: 100.0),
        )
    )
    return result, verifier.requests


@pytest.mark.parametrize("case", ["SUPPORTED", "CONTRADICTED", "UNCLEAR"])
def test_recorded_responses_entailments_bind_exact_public_evidence(case: str) -> None:
    first, requests = _run(case)
    second, second_requests = _run(case)

    assert type(first) is ClaimValidationSucceededV0
    assert type(second) is ClaimValidationSucceededV0
    assert first.validation.to_public_dict() == second.validation.to_public_dict()
    assert first.validation.entailment is EntailmentV0(case)
    assert (
        first.validation.article_content_hash == second.validation.article_content_hash
    )
    assert (
        first.validation.supporting_span
        == ARTICLE_TEXT[
            first.validation.supporting_location.start : first.validation.supporting_location.end
        ]
    )
    assert first.validation.source_url == "https://evidence.example/aurora/final-update"
    assert first.validation.publisher == "Synthetic Wire"
    assert first.validation.verifier_version == "synthetic-verifier-2026-08-13"
    assert requests == second_requests


def test_recorded_responses_request_is_public_bounded_and_deadline_aware() -> None:
    _result, requests = _run("SUPPORTED")
    assert len(requests) == 1
    wire = requests[0]
    assert set(wire) == {"model", "input", "deadline"}
    deadline = wire["deadline"]
    assert type(deadline) is dict
    assert set(deadline) == {"timeout_seconds", "expires_at_monotonic"}
    input_rows = wire["input"]
    assert type(input_rows) is list
    text = input_rows[0]["content"][0]["text"]  # type: ignore[index]
    public = json.loads(text)
    assert set(public) == {
        "claim_id",
        "claim_text",
        "instrument",
        "article_content_hash",
        "article_text",
    }
    assert set(public["instrument"]) == {
        "market",
        "canonical_ticker",
        "exchange",
        "company_name",
        "identity_source",
        "identity_version",
    }
    serialized = json.dumps(wire, ensure_ascii=False).casefold()
    for private_name in (
        "account",
        "portfolio",
        "quantity",
        "entry_price",
        "pnl",
        "notes",
        "tags",
        "secret",
    ):
        assert private_name not in serialized


@pytest.mark.parametrize(
    ("case", "result_type", "code"),
    [
        ("MALFORMED", ClaimValidationFailedV0, "VERIFIER_RESULT_MALFORMED"),
        ("TIMEOUT", ClaimValidationTimedOutV0, "CLAIM_TIMEOUT"),
        ("UNEXPECTED", ClaimValidationFailedV0, "VERIFIER_FAILED"),
    ],
)
def test_recorded_responses_failure_taxonomy(
    case: str, result_type: type, code: str
) -> None:
    result, _requests = _run(case)
    assert type(result) is result_type
    assert getattr(result, "code", None) == code


def test_recorded_responses_mutation_and_raw_shape_fail_closed() -> None:
    mutated = _recording()
    cases = mutated["cases"]
    assert type(cases) is dict
    supported = cases["SUPPORTED"]
    assert type(supported) is dict
    response = supported["response"]
    assert type(response) is dict
    response["private_raw"] = "not-authoritative"

    result, _requests = _run("SUPPORTED", recording=mutated)

    assert type(result) is ClaimValidationFailedV0
    assert result.code == "VERIFIER_FAILED"

    location_mutation = _recording()
    cases = location_mutation["cases"]
    assert type(cases) is dict
    supported = cases["SUPPORTED"]
    assert type(supported) is dict
    response = supported["response"]
    assert type(response) is dict
    output = response["output"]
    assert type(output) is list
    content = output[0]["content"]  # type: ignore[index]
    payload = json.loads(content[0]["text"])  # type: ignore[index]
    payload["supporting_location"]["start"] = 1
    payload["source_url"] = "https://forged.example/private"
    content[0]["text"] = json.dumps(payload)  # type: ignore[index]

    malformed, _requests = _run("SUPPORTED", recording=location_mutation)

    assert type(malformed) is ClaimValidationFailedV0
    assert malformed.code == "VERIFIER_RESULT_MALFORMED"
