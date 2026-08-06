from __future__ import annotations

import asyncio
import json

import pytest
from sab.decision_board.instruments import InstrumentRefV0
from sab.research.contracts import (
    ResearchInputV0,
    ResearchQuestionV0,
    ResearchSourcePolicyV0,
    SourceCandidateV0,
)
from sab.research.deadline import Deadline
from sab.research.orchestrator import (
    EvidenceResearcherV0,
    ResearchCompletedV0,
    ResearchInputFailedV0,
    ResearchItemMalformedV0,
    ResearchItemNoUsableSourceV0,
    ResearchItemSucceededV0,
    ResearchItemTimedOutV0,
    ResearchSharedBlockedV0,
    SearchProviderV0,
)
from sab.research.source_safety import (
    ArticleArtifactV0,
    ArticleFetchResponseV0,
    ArticlePreflightError,
    SafeArticleVerifierV0,
)


def _instrument(index: int) -> InstrumentRefV0:
    ticker = f"SYN{index}.NAS"
    return InstrumentRefV0(
        market="US",
        canonical_ticker=ticker,
        exchange="NASDAQ",
        company_name=f"Synthetic Company {index}",
        identity_source="synthetic-directory",
        identity_version="fixture-2026-08-07",
    )


def _research_input(count: int) -> ResearchInputV0:
    return ResearchInputV0(
        instruments=tuple(_instrument(index) for index in range(count)),
        questions=(ResearchQuestionV0.RECENT_MATERIAL_DEVELOPMENTS,),
    )


def _row(
    instrument: InstrumentRefV0,
    *,
    suffix: str,
    purpose: str = "PRIMARY",
    url: str | None = None,
) -> dict[str, object]:
    return {
        "canonical_ticker": instrument.canonical_ticker,
        "title": f"Synthetic {suffix}",
        "url": url
        or f"https://evidence.example/{instrument.canonical_ticker}/{suffix}",
        "publisher": "Synthetic Wire",
        "published_at": "2026-08-07T01:00:00Z",
        "purpose": purpose,
    }


def _payload(
    instrument: InstrumentRefV0,
    rows: list[dict[str, object]] | None = None,
) -> dict[str, object]:
    return {
        "schema": "sab.research.search.v0",
        "instrument": instrument.to_public_dict(),
        "sources": rows if rows is not None else [_row(instrument, suffix="primary")],
    }


class _ConcurrentProvider:
    def __init__(self, payloads: dict[str, object]) -> None:
        self.payloads = payloads
        self.calls: list[tuple[dict[str, object], Deadline]] = []
        self.active = 0
        self.peak_active = 0

    async def search(self, request: object, *, deadline: Deadline) -> object:
        public = request.to_public_dict()  # type: ignore[attr-defined]
        self.calls.append((public, deadline))
        self.active += 1
        self.peak_active = max(self.peak_active, self.active)
        await asyncio.sleep(0)
        self.active -= 1
        ticker = public["instrument"]["canonical_ticker"]  # type: ignore[index]
        return self.payloads[ticker]


class _RecordingVerifier:
    def __init__(self, *, blocked: bool = False) -> None:
        self.blocked = blocked
        self.calls: list[tuple[SourceCandidateV0, Deadline]] = []

    def preflight(self) -> None:
        if self.blocked:
            raise ArticlePreflightError("VERIFIER_UNAVAILABLE", "synthetic")

    async def verify(
        self, source: SourceCandidateV0, *, deadline: Deadline
    ) -> ArticleArtifactV0:
        self.calls.append((source, deadline))
        return ArticleArtifactV0(
            source=source,
            final_url=source.canonical_url,
            normalized_text=f"Synthetic body for {source.canonical_ticker}",
            content_hash=f"sha256:{'0' * 64}",
        )


def test_max_five_instruments_one_call_each_and_provider_concurrency_two() -> None:
    research_input = _research_input(5)
    provider = _ConcurrentProvider(
        {
            instrument.canonical_ticker: _payload(instrument)
            for instrument in research_input.instruments
        }
    )
    verifier = _RecordingVerifier()

    result = asyncio.run(
        EvidenceResearcherV0(provider, verifier).research(research_input)
    )

    assert type(result) is ResearchCompletedV0
    assert provider.peak_active == 2
    assert [call[0]["instrument"]["canonical_ticker"] for call in provider.calls] == [  # type: ignore[index]
        instrument.canonical_ticker for instrument in research_input.instruments
    ]
    assert all(
        sum(
            call[0]["instrument"]["canonical_ticker"]  # type: ignore[index]
            == instrument.canonical_ticker
            for call in provider.calls
        )
        == 1
        for instrument in research_input.instruments
    )
    assert len({id(deadline) for _, deadline in provider.calls}) == 1
    assert len({id(deadline) for _, deadline in verifier.calls}) == 1
    assert id(provider.calls[0][1]) == id(verifier.calls[0][1])

    with pytest.raises(ValueError, match="at most 5 instruments"):
        _research_input(6)


def test_round_robin_global_eight_attempts_and_global_url_dedupe() -> None:
    research_input = _research_input(5)
    shared_url = "https://evidence.example/shared"
    payloads: dict[str, object] = {}
    for index, instrument in enumerate(research_input.instruments):
        first_url = shared_url if index in {0, 1} else None
        payloads[instrument.canonical_ticker] = _payload(
            instrument,
            [
                _row(instrument, suffix="primary", url=first_url),
                _row(instrument, suffix="opposing", purpose="OPPOSING"),
                _row(
                    instrument,
                    suffix="action",
                    purpose="ACTION_CHANGING",
                ),
            ],
        )
    provider = _ConcurrentProvider(payloads)
    verifier = _RecordingVerifier()

    result = asyncio.run(
        EvidenceResearcherV0(provider, verifier).research(research_input)
    )

    assert type(result) is ResearchCompletedV0
    assert len(verifier.calls) == 8
    assert [call[0].canonical_ticker for call in verifier.calls[:4]] == [
        "SYN0.NAS",
        "SYN2.NAS",
        "SYN3.NAS",
        "SYN4.NAS",
    ]
    assert sum(call[0].canonical_url == shared_url for call in verifier.calls) == 1
    succeeded = [item for item in result.items if type(item) is ResearchItemSucceededV0]
    assert {item.instrument.canonical_ticker for item in succeeded} == {
        instrument.canonical_ticker for instrument in research_input.instruments
    }
    shared_attributions = [
        item.instrument.canonical_ticker
        for item in succeeded
        if any(article.source.canonical_url == shared_url for article in item.articles)
    ]
    assert shared_attributions == ["SYN0.NAS", "SYN1.NAS"]


def test_shared_preflight_blocks_before_any_provider_work() -> None:
    research_input = _research_input(2)
    provider = _ConcurrentProvider({})

    result = asyncio.run(
        EvidenceResearcherV0(provider, _RecordingVerifier(blocked=True)).research(
            research_input
        )
    )

    assert type(result) is ResearchSharedBlockedV0
    assert result.status == "BLOCKED"
    assert result.issue.code == "VERIFIER_UNAVAILABLE"
    assert provider.calls == []


def test_timeout_malformed_and_empty_provider_items_are_isolated_from_peer() -> None:
    research_input = _research_input(4)

    class IsolatingProvider(_ConcurrentProvider):
        async def search(self, request: object, *, deadline: Deadline) -> object:
            public = request.to_public_dict()  # type: ignore[attr-defined]
            ticker = public["instrument"]["canonical_ticker"]  # type: ignore[index]
            self.calls.append((public, deadline))
            if ticker == "SYN0.NAS":
                raise TimeoutError
            if ticker == "SYN1.NAS":
                return {"schema": "malformed"}
            if ticker == "SYN2.NAS":
                return _payload(_instrument(2), [])
            return _payload(_instrument(3))

    provider = IsolatingProvider({})

    result = asyncio.run(
        EvidenceResearcherV0(provider, _RecordingVerifier()).research(research_input)
    )

    assert type(result) is ResearchCompletedV0
    assert [type(item) for item in result.items] == [
        ResearchItemTimedOutV0,
        ResearchItemMalformedV0,
        ResearchItemNoUsableSourceV0,
        ResearchItemSucceededV0,
    ]


def test_deadline_cancels_and_drains_inflight_provider_work() -> None:
    research_input = _research_input(3)

    class HangingProvider:
        def __init__(self) -> None:
            self.active = 0
            self.cancelled = 0

        async def search(self, request: object, *, deadline: Deadline) -> object:
            del request, deadline
            self.active += 1
            try:
                await asyncio.Event().wait()
            finally:
                self.active -= 1
                self.cancelled += 1
            raise AssertionError("hanging provider unexpectedly resumed")

    provider = HangingProvider()
    result = asyncio.run(
        EvidenceResearcherV0(
            provider,
            _RecordingVerifier(),
            budget_seconds=0.01,
        ).research(research_input)
    )

    assert type(result) is ResearchCompletedV0
    assert all(type(item) is ResearchItemTimedOutV0 for item in result.items)
    assert provider.active == 0
    assert provider.cancelled == 2


def test_negative_clock_movement_is_typed_input_failure() -> None:
    class ReverseClock:
        def __init__(self) -> None:
            self.values = iter((10.0, 9.0))

        def __call__(self) -> float:
            return next(self.values)

    research_input = _research_input(1)
    provider = _ConcurrentProvider({"SYN0.NAS": _payload(_instrument(0))})

    result = asyncio.run(
        EvidenceResearcherV0(
            provider,
            _RecordingVerifier(),
            monotonic=ReverseClock(),
        ).research(research_input)
    )

    assert type(result) is ResearchInputFailedV0
    assert result.status == "FAILED"
    assert result.issue.code == "DEADLINE_INVARIANT"


def test_result_variants_cannot_carry_arbitrary_or_contradictory_status() -> None:
    instrument = _instrument(0)
    with pytest.raises(TypeError):
        ResearchItemSucceededV0(  # type: ignore[call-arg]
            instrument=instrument,
            articles=(),
            status="NO_NEWS",
        )
    with pytest.raises(ValueError, match="at least one article"):
        ResearchItemSucceededV0(instrument=instrument, articles=())

    assert not hasattr(SearchProviderV0, "create_order")
    assert not hasattr(SearchProviderV0, "modify_order")
    assert not hasattr(SearchProviderV0, "cancel_order")


def test_private_provider_payload_never_appears_in_result_or_error() -> None:
    private_sentinel = "PRIVATE-ACCOUNT-9917"
    research_input = _research_input(1)
    provider = _ConcurrentProvider(
        {
            "SYN0.NAS": {
                **_payload(_instrument(0)),
                "account_id": private_sentinel,
            }
        }
    )

    result = asyncio.run(
        EvidenceResearcherV0(provider, _RecordingVerifier()).research(research_input)
    )

    assert type(result) is ResearchCompletedV0
    assert type(result.items[0]) is ResearchItemMalformedV0
    assert private_sentinel not in repr(result)
    assert private_sentinel not in json.dumps(provider.calls[0][0])


def test_one_45_second_deadline_spans_search_backoff_dns_redirect_and_fetch() -> None:
    class FakeClock:
        def __init__(self) -> None:
            self.now = 100.0

        def __call__(self) -> float:
            return self.now

    class RetryingProvider:
        def __init__(self, clock: FakeClock) -> None:
            self.clock = clock
            self.deadlines: list[Deadline] = []
            self.timeouts: list[float] = []

        async def search(self, request: object, *, deadline: Deadline) -> object:
            self.deadlines.append(deadline)
            self.timeouts.append(deadline.child_timeout())
            self.clock.now += 25.0

            async def fake_sleep(seconds: float) -> None:
                self.timeouts.append(seconds)
                self.clock.now += seconds

            await deadline.sleep(5.0, sleeper=fake_sleep)
            instrument = request.instrument  # type: ignore[attr-defined]
            return _payload(
                instrument,
                [
                    _row(
                        instrument, suffix="start", url="https://evidence.example/start"
                    )
                ],
            )

    class Resolver:
        def __init__(self, clock: FakeClock) -> None:
            self.clock = clock
            self.timeouts: list[float] = []

        async def resolve(
            self, hostname: str, port: int, *, timeout: float
        ) -> tuple[str, ...]:
            assert (hostname, port) == ("evidence.example", 443)
            self.timeouts.append(timeout)
            self.clock.now += 1.0
            return ("93.184.216.34",)

    class Fetcher:
        def __init__(self, clock: FakeClock) -> None:
            self.clock = clock
            self.timeouts: list[float] = []

        async def fetch(
            self,
            url: str,
            addresses: tuple[str, ...],
            *,
            timeout: float,
            max_bytes: int,
        ) -> ArticleFetchResponseV0:
            del addresses, max_bytes
            self.timeouts.append(timeout)
            self.clock.now += 2.0
            if url.endswith("/start"):
                return ArticleFetchResponseV0(
                    status_code=302,
                    content_type="text/plain",
                    content_encoding=None,
                    body=b"",
                    location="/final",
                )
            return ArticleFetchResponseV0(
                status_code=200,
                content_type="text/plain; charset=utf-8",
                content_encoding=None,
                body=b"Synthetic final article.",
                location=None,
            )

    clock = FakeClock()
    provider = RetryingProvider(clock)
    resolver = Resolver(clock)
    fetcher = Fetcher(clock)
    policy = ResearchSourcePolicyV0(operation_timeout_seconds=15.0)
    research_input = ResearchInputV0(
        instruments=(_instrument(0),),
        questions=(ResearchQuestionV0.RECENT_MATERIAL_DEVELOPMENTS,),
        source_policy=policy,
    )
    verifier = SafeArticleVerifierV0(
        resolver=resolver,
        fetcher=fetcher,
        policy=policy,
    )

    result = asyncio.run(
        EvidenceResearcherV0(
            provider,
            verifier,
            monotonic=clock,
        ).research(research_input)
    )

    assert type(result) is ResearchCompletedV0
    assert type(result.items[0]) is ResearchItemSucceededV0
    assert provider.timeouts == [45.0, 5.0]
    assert resolver.timeouts == [15.0, 12.0]
    assert fetcher.timeouts == [14.0, 11.0]
    assert clock.now == 136.0
    assert provider.deadlines[0].expires_at == 145.0
