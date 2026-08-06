"""Strict public-only contracts for bounded Decision Board research."""

from __future__ import annotations

import math
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import StrEnum

from sab.decision_board.instruments import (
    InstrumentRefV0,
    InstrumentRegistryError,
    normalize_public_text_v0,
)

from .urls import canonicalize_public_article_url_v0

MAX_RESEARCH_INSTRUMENTS = 5
MAX_SOURCES_PER_INSTRUMENT = 3
MAX_ARTICLE_ATTEMPTS = 8

_INSTRUMENT_FIELDS = {
    "market",
    "canonical_ticker",
    "exchange",
    "company_name",
    "identity_source",
    "identity_version",
}
_SEARCH_RESPONSE_FIELDS = {"schema", "instrument", "sources"}
_SOURCE_FIELDS = {
    "canonical_ticker",
    "title",
    "url",
    "publisher",
    "published_at",
    "purpose",
}


class ResearchQuestionV0(StrEnum):
    RECENT_MATERIAL_DEVELOPMENTS = "RECENT_MATERIAL_DEVELOPMENTS"
    MATERIAL_COUNTER_EVIDENCE = "MATERIAL_COUNTER_EVIDENCE"
    ACTION_CHANGING_EVIDENCE = "ACTION_CHANGING_EVIDENCE"


class SourcePurposeV0(StrEnum):
    PRIMARY = "PRIMARY"
    OPPOSING = "OPPOSING"
    ACTION_CHANGING = "ACTION_CHANGING"


_PURPOSE_PRIORITY = {
    SourcePurposeV0.PRIMARY: 0,
    SourcePurposeV0.OPPOSING: 1,
    SourcePurposeV0.ACTION_CHANGING: 2,
}


@dataclass(frozen=True, slots=True)
class ResearchSourcePolicyV0:
    freshness_hours: int = 168
    max_redirects: int = 3
    max_response_bytes: int = 1_000_000
    max_article_text_chars: int = 100_000
    operation_timeout_seconds: float = 10.0

    def __post_init__(self) -> None:
        if (
            isinstance(self.freshness_hours, bool)
            or not 1 <= self.freshness_hours <= 720
        ):
            raise ValueError("freshness_hours must be in the safe range 1..720")
        if isinstance(self.max_redirects, bool) or not 0 <= self.max_redirects <= 5:
            raise ValueError("max_redirects must be in the safe range 0..5")
        if (
            isinstance(self.max_response_bytes, bool)
            or not 1 <= self.max_response_bytes <= 2_000_000
        ):
            raise ValueError("max_response_bytes is outside the safe range")
        if (
            isinstance(self.max_article_text_chars, bool)
            or not 1 <= self.max_article_text_chars <= 200_000
        ):
            raise ValueError("max_article_text_chars is outside the safe range")
        timeout = self.operation_timeout_seconds
        if (
            isinstance(timeout, bool)
            or not isinstance(timeout, (int, float))
            or not math.isfinite(timeout)
            or not 0 < timeout <= 15.0
        ):
            raise ValueError("operation_timeout_seconds is outside the safe range")


@dataclass(frozen=True, slots=True)
class ResearchInputV0:
    instruments: tuple[InstrumentRefV0, ...]
    questions: tuple[ResearchQuestionV0, ...]
    source_policy: ResearchSourcePolicyV0 = field(
        default_factory=ResearchSourcePolicyV0
    )

    def __post_init__(self) -> None:
        if type(self.instruments) is not tuple or not self.instruments:
            raise TypeError("research instruments must be a non-empty tuple")
        if len(self.instruments) > MAX_RESEARCH_INSTRUMENTS:
            raise ValueError("research accepts at most 5 instruments")
        trusted: list[InstrumentRefV0] = []
        keys: set[tuple[str, ...]] = set()
        for instrument in self.instruments:
            copied = _copy_exact_instrument(instrument)
            if copied is None:
                raise TypeError("research requires exact InstrumentRefV0 values")
            key = tuple(copied.to_public_dict().values())
            if key in keys:
                raise ValueError("research instruments must be unique")
            keys.add(key)
            trusted.append(copied)
        if type(self.questions) is not tuple or not self.questions:
            raise TypeError("research questions must be a non-empty tuple")
        if not all(type(question) is ResearchQuestionV0 for question in self.questions):
            raise TypeError("research questions must use the allowlisted V0 type")
        if len(set(self.questions)) != len(self.questions):
            raise ValueError("research questions must be unique")
        if type(self.source_policy) is not ResearchSourcePolicyV0:
            raise TypeError("research source policy must be exact V0 policy")
        object.__setattr__(self, "instruments", tuple(trusted))


@dataclass(frozen=True, slots=True)
class SearchRequestV0:
    instrument: InstrumentRefV0
    questions: tuple[ResearchQuestionV0, ...]
    freshness_hours: int

    def __post_init__(self) -> None:
        copied = _copy_exact_instrument(self.instrument)
        if copied is None:
            raise TypeError("search request requires exact InstrumentRefV0")
        if (
            type(self.questions) is not tuple
            or not self.questions
            or not all(
                type(question) is ResearchQuestionV0 for question in self.questions
            )
        ):
            raise TypeError("search request requires allowlisted V0 questions")
        if (
            isinstance(self.freshness_hours, bool)
            or not isinstance(self.freshness_hours, int)
            or not 1 <= self.freshness_hours <= 720
        ):
            raise ValueError("search request freshness_hours is outside the safe range")
        object.__setattr__(self, "instrument", copied)

    def to_public_dict(self) -> dict[str, object]:
        return {
            "schema": "sab.research.search_request.v0",
            "instrument": {
                "market": self.instrument.market,
                "canonical_ticker": self.instrument.canonical_ticker,
                "exchange": self.instrument.exchange,
                "company_name": self.instrument.company_name,
                "identity_source": self.instrument.identity_source,
                "identity_version": self.instrument.identity_version,
            },
            "questions": [question.value for question in self.questions],
            "freshness_hours": self.freshness_hours,
        }


@dataclass(frozen=True, slots=True)
class SourceCandidateV0:
    canonical_ticker: str
    title: str
    canonical_url: str
    publisher: str
    published_at: datetime | None
    purpose: SourcePurposeV0


def build_search_request_v0(
    research_input: ResearchInputV0,
    instrument: InstrumentRefV0,
) -> SearchRequestV0:
    if type(research_input) is not ResearchInputV0:
        raise TypeError("search request requires exact ResearchInputV0")
    copied = _copy_exact_instrument(instrument)
    if copied is None or copied not in research_input.instruments:
        raise TypeError(
            "search request instrument must be trusted by the research input"
        )
    return SearchRequestV0(
        instrument=copied,
        questions=research_input.questions,
        freshness_hours=research_input.source_policy.freshness_hours,
    )


def parse_search_response_v0(
    payload: object,
    *,
    expected_instrument: InstrumentRefV0,
) -> tuple[SourceCandidateV0, ...]:
    expected = _copy_exact_instrument(expected_instrument)
    if expected is None:
        raise TypeError("expected instrument must be exact InstrumentRefV0")
    if not isinstance(payload, Mapping) or set(payload) != _SEARCH_RESPONSE_FIELDS:
        raise ValueError("search response must have the exact V0 field set")
    if payload["schema"] != "sab.research.search.v0":
        raise ValueError("search response schema is unsupported")
    _validate_response_instrument(payload["instrument"], expected)
    rows = payload["sources"]
    if isinstance(rows, (str, bytes)) or not isinstance(rows, Sequence):
        raise ValueError("search response sources must be an array")
    if len(rows) > MAX_SOURCES_PER_INSTRUMENT:
        raise ValueError("search response exceeds the per-instrument source limit")
    sources = tuple(_parse_source_row(row, expected) for row in rows)
    return tuple(sorted(sources, key=_source_sort_key))


def _validate_response_instrument(value: object, expected: InstrumentRefV0) -> None:
    if not isinstance(value, Mapping) or set(value) != _INSTRUMENT_FIELDS:
        raise ValueError("search response instrument has an invalid field set")
    if dict(value) != expected.to_public_dict():
        raise ValueError("search response instrument does not match its request")


def _parse_source_row(value: object, expected: InstrumentRefV0) -> SourceCandidateV0:
    if not isinstance(value, Mapping) or set(value) != _SOURCE_FIELDS:
        raise ValueError("search source has an invalid field set")
    if value["canonical_ticker"] != expected.canonical_ticker:
        raise ValueError("search source is bound to a different instrument")
    title = _required_public_text(value["title"], field_name="source title")
    publisher = _required_public_text(value["publisher"], field_name="publisher")
    try:
        purpose = SourcePurposeV0(value["purpose"])
    except (TypeError, ValueError) as exc:
        raise ValueError("source purpose is unsupported") from exc
    published_at = _optional_timestamp(value["published_at"])
    return SourceCandidateV0(
        canonical_ticker=expected.canonical_ticker,
        title=title,
        canonical_url=canonicalize_public_article_url_v0(value["url"]),
        publisher=publisher,
        published_at=published_at,
        purpose=purpose,
    )


def _required_public_text(value: object, *, field_name: str) -> str:
    normalized = normalize_public_text_v0(value)
    if normalized is None:
        raise ValueError(f"{field_name} must be nonblank public text")
    return normalized


def _optional_timestamp(value: object) -> datetime | None:
    if value is None:
        return None
    if not isinstance(value, str):
        raise ValueError("published_at must be an RFC 3339 string or null")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError("published_at must be a valid RFC 3339 timestamp") from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError("published_at must include an offset")
    return parsed.astimezone(UTC)


def _source_sort_key(source: SourceCandidateV0) -> tuple[object, ...]:
    published_sort = (
        -source.published_at.timestamp()
        if source.published_at is not None
        else math.inf
    )
    return (
        _PURPOSE_PRIORITY[source.purpose],
        published_sort,
        source.canonical_url.encode("utf-8"),
        source.title.encode("utf-8"),
    )


def _copy_exact_instrument(value: object) -> InstrumentRefV0 | None:
    if type(value) is not InstrumentRefV0:
        return None
    try:
        return InstrumentRefV0(
            market=value.market,
            canonical_ticker=value.canonical_ticker,
            exchange=value.exchange,
            company_name=value.company_name,
            identity_source=value.identity_source,
            identity_version=value.identity_version,
        )
    except AttributeError, InstrumentRegistryError, TypeError:
        return None


__all__ = [
    "MAX_ARTICLE_ATTEMPTS",
    "MAX_RESEARCH_INSTRUMENTS",
    "MAX_SOURCES_PER_INSTRUMENT",
    "ResearchInputV0",
    "ResearchQuestionV0",
    "ResearchSourcePolicyV0",
    "SearchRequestV0",
    "SourceCandidateV0",
    "SourcePurposeV0",
    "build_search_request_v0",
    "parse_search_response_v0",
]
