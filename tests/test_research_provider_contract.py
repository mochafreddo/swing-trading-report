from __future__ import annotations

import json
from dataclasses import replace
from pathlib import Path

import pytest
from sab.decision_board.instruments import InstrumentRefV0
from sab.research.contracts import (
    ResearchInputV0,
    ResearchQuestionV0,
    ResearchSourcePolicyV0,
    SearchRequestV0,
    SourcePurposeV0,
    build_search_request_v0,
    parse_search_response_v0,
)

_FIXTURE = Path("tests/fixtures/research/search.aurora.json")
_PRIVATE_SENTINEL = "PRIVATE-ACCOUNT-9917"


def _instrument() -> InstrumentRefV0:
    return InstrumentRefV0(
        market="US",
        canonical_ticker="AUR.NAS",
        exchange="NASDAQ",
        company_name="Aurora Synthetic Systems",
        identity_source="synthetic-directory",
        identity_version="fixture-2026-08-07",
    )


def test_recorded_provider_fixture_is_strict_and_deterministically_ordered() -> None:
    payload = json.loads(_FIXTURE.read_text(encoding="utf-8"))

    sources = parse_search_response_v0(payload, expected_instrument=_instrument())

    assert [(source.purpose, source.canonical_url) for source in sources] == [
        (SourcePurposeV0.PRIMARY, "https://evidence.example/aurora-primary"),
        (SourcePurposeV0.OPPOSING, "https://evidence.example/aurora-counter"),
    ]


def test_same_instrument_duplicate_canonical_url_is_malformed() -> None:
    payload = json.loads(_FIXTURE.read_text(encoding="utf-8"))
    payload["sources"][1]["url"] = payload["sources"][0]["url"]  # type: ignore[index]

    with pytest.raises(ValueError, match="duplicate canonical URL"):
        parse_search_response_v0(payload, expected_instrument=_instrument())


@pytest.mark.parametrize(
    "published_at",
    [
        "2026-08-07 01:00:00Z",
        "2026-08-07t01:00:00z",
        "2026-08-07T01:00:00+00:00:30",
        "2026-02-30T01:00:00Z",
    ],
)
def test_published_at_requires_strict_real_rfc3339(published_at: str) -> None:
    payload = json.loads(_FIXTURE.read_text(encoding="utf-8"))
    payload["sources"][0]["published_at"] = published_at  # type: ignore[index]

    with pytest.raises(ValueError, match="RFC 3339"):
        parse_search_response_v0(payload, expected_instrument=_instrument())


@pytest.mark.parametrize(
    "mutate",
    [
        lambda payload: {**payload, "account_id": _PRIVATE_SENTINEL},
        lambda payload: {**payload, "schema": "sab.research.search.v9"},
        lambda payload: {
            **payload,
            "instrument": {**payload["instrument"], "canonical_ticker": "OTHER.NAS"},
        },
        lambda payload: {
            **payload,
            "sources": [*payload["sources"], *payload["sources"]],
        },
        lambda payload: {
            **payload,
            "sources": [{**payload["sources"][0], "quantity": _PRIVATE_SENTINEL}],
        },
        lambda payload: {
            **payload,
            "sources": [{**payload["sources"][0], "purpose": "SUPPORTING"}],
        },
    ],
)
def test_provider_payload_rejects_unknown_binding_excess_and_status_smuggling(
    mutate: object,
) -> None:
    payload = json.loads(_FIXTURE.read_text(encoding="utf-8"))

    with pytest.raises(ValueError):
        parse_search_response_v0(mutate(payload), expected_instrument=_instrument())  # type: ignore[operator]


def test_research_input_and_provider_request_are_exact_public_only_values() -> None:
    instrument = _instrument()
    research_input = ResearchInputV0(
        instruments=(instrument,),
        questions=(
            ResearchQuestionV0.RECENT_MATERIAL_DEVELOPMENTS,
            ResearchQuestionV0.MATERIAL_COUNTER_EVIDENCE,
        ),
        source_policy=ResearchSourcePolicyV0(freshness_hours=72),
    )

    request = build_search_request_v0(research_input, instrument)
    serialized = json.dumps(request.to_public_dict(), sort_keys=True)

    assert set(request.to_public_dict()) == {
        "schema",
        "instrument",
        "questions",
        "freshness_hours",
    }
    instrument_payload = request.to_public_dict()["instrument"]
    assert isinstance(instrument_payload, dict)
    assert set(instrument_payload) == {
        "market",
        "canonical_ticker",
        "exchange",
        "company_name",
        "identity_source",
        "identity_version",
    }
    assert _PRIVATE_SENTINEL not in serialized
    assert "quantity" not in serialized
    assert "entry_price" not in serialized
    assert "account_id" not in serialized


def test_fake_subclass_and_private_unknown_input_cannot_cross_research_boundary() -> (
    None
):
    class FakeInstrumentRef(InstrumentRefV0):
        account_id = _PRIVATE_SENTINEL

    fake = FakeInstrumentRef(**_instrument().to_public_dict())

    with pytest.raises(TypeError, match="exact InstrumentRefV0"):
        ResearchInputV0(
            instruments=(fake,),
            questions=(ResearchQuestionV0.RECENT_MATERIAL_DEVELOPMENTS,),
        )
    with pytest.raises(TypeError, match="exact InstrumentRefV0"):
        SearchRequestV0(
            instrument=fake,
            questions=(ResearchQuestionV0.RECENT_MATERIAL_DEVELOPMENTS,),
            freshness_hours=72,
        )
    with pytest.raises(TypeError):
        ResearchInputV0(  # type: ignore[call-arg]
            instruments=(_instrument(),),
            questions=(ResearchQuestionV0.RECENT_MATERIAL_DEVELOPMENTS,),
            account_id=_PRIVATE_SENTINEL,
        )
    with pytest.raises(TypeError):
        replace(
            ResearchInputV0(
                instruments=(_instrument(),),
                questions=(ResearchQuestionV0.RECENT_MATERIAL_DEVELOPMENTS,),
            ),
            questions=("arbitrary private question",),  # type: ignore[arg-type]
        )
