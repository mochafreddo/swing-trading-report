from __future__ import annotations

import asyncio
import copy
import json
from datetime import UTC, datetime
from pathlib import Path

import pytest
from sab.decision_board.claim_responses import ResponsesClaimVerifierV0
from sab.decision_board.claims import (
    ClaimRequestV0,
    ClaimValidationFailedV0,
    ClaimValidationSucceededV0,
    ClaimValidationTimedOutV0,
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
from scripts.compare_decision_board_claim_live import main as live_compare_main

FIXTURE = (
    Path(__file__).parent
    / "fixtures"
    / "decision_board"
    / "claim-verifier-responses-recorded.json"
)
ARTICLE_TEXT = "Aurora beat guidance. Aurora beat guidance. Café demand is stable."


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


class _RecordedResponsesTransport:
    """Fixture transport; the reusable decoder/adapter is production-neutral."""

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
        self.deadlines: list[dict[str, float]] = []

    async def create_response(
        self,
        request: dict[str, object],
        *,
        deadline: Deadline,
        timeout: float,
    ) -> object:
        self.requests.append(copy.deepcopy(request))
        self.deadlines.append(
            {
                "timeout_seconds": timeout,
                "expires_at_monotonic": deadline.expires_at,
            }
        )
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
        return copy.deepcopy(case["response"])


def _run(case: str, *, recording: object | None = None):
    request, source, article, policy = _inputs()
    recording_value = recording or _recording()
    assert type(recording_value) is dict
    model = recording_value.get("model")
    assert type(model) is str
    transport = _RecordedResponsesTransport(recording_value, case)
    verifier = ResponsesClaimVerifierV0(transport=transport, model=model)
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
    return result, transport.requests, transport.deadlines


@pytest.mark.parametrize("case", ["SUPPORTED", "CONTRADICTED", "UNCLEAR"])
def test_recorded_responses_entailments_bind_exact_public_evidence(case: str) -> None:
    first, requests, deadlines = _run(case)
    second, second_requests, second_deadlines = _run(case)

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
    assert first.validation.verifier_version == "decision-board-claim-verifier-v0"
    assert requests == second_requests
    assert deadlines == second_deadlines


def test_recorded_responses_request_is_public_bounded_and_deadline_aware() -> None:
    _result, requests, deadlines = _run("SUPPORTED")
    assert len(requests) == 1
    wire = requests[0]
    assert set(wire) == {"model", "input", "text"}
    assert len(deadlines) == 1
    deadline = deadlines[0]
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
    serialized = json.dumps(
        {"model": wire["model"], "input": wire["input"]}, ensure_ascii=False
    ).casefold()
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
    result, _requests, _deadlines = _run(case)
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

    result, _requests, _deadlines = _run("SUPPORTED", recording=mutated)

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

    malformed, _requests, _deadlines = _run("SUPPORTED", recording=location_mutation)

    assert type(malformed) is ClaimValidationFailedV0
    assert malformed.code == "VERIFIER_RESULT_MALFORMED"


def test_claim_live_compare_is_explicit_and_forbidden_in_ci(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    request_path = tmp_path / "request.json"
    request_path.write_text('{"model":"gpt-5.4-mini"}', encoding="utf-8")
    monkeypatch.setenv("CI", "true")
    monkeypatch.setenv("DECISION_BOARD_CLAIM_LIVE_PROVIDER_COMMAND", "provider")
    monkeypatch.setenv("DECISION_BOARD_CLAIM_LIVE_MODEL", "gpt-5.4-mini")

    with pytest.raises(SystemExit) as caught:
        live_compare_main(["--request-json", str(request_path), "--case", "SUPPORTED"])

    assert caught.value.code == 2
