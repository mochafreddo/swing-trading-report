from __future__ import annotations

import asyncio
import json

import pytest
import sab.research as research_package
import sab.research.orchestrator as research_orchestrator
from sab.decision_board.instruments import InstrumentRefV0
from sab.research.contracts import (
    ResearchInputV0,
    ResearchQuestionV0,
    ResearchSourcePolicyV0,
    SourceCandidateV0,
    create_source_candidate_v0,
)
from sab.research.deadline import Deadline
from sab.research.orchestrator import (
    EvidenceResearcherV0,
    ResearchCompletedV0,
    ResearchInputFailedV0,
    ResearchIssueV0,
    ResearchItemMalformedV0,
    ResearchItemNoUsableSourceV0,
    ResearchItemProviderFailedV0,
    ResearchItemSucceededV0,
    ResearchItemTimedOutV0,
    ResearchSharedBlockedV0,
    SearchProviderOperationalError,
    SearchProviderTimeoutError,
    SearchProviderV0,
)
from sab.research.source_safety import (
    ArticleArtifactV0,
    ArticleFetchResponseV0,
    ArticlePreflightError,
    ArticleSafetyError,
    SafeArticleVerifierV0,
    create_article_artifact_v0,
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

    def preflight(self, policy: ResearchSourcePolicyV0) -> None:
        del policy
        if self.blocked:
            raise ArticlePreflightError("VERIFIER_UNAVAILABLE", "synthetic")

    async def verify(
        self,
        source: SourceCandidateV0,
        *,
        deadline: Deadline,
        policy: ResearchSourcePolicyV0,
    ) -> ArticleArtifactV0:
        self.calls.append((source, deadline))
        return create_article_artifact_v0(
            source=source,
            final_url=source.canonical_url,
            normalized_text=f"Synthetic body for {source.canonical_ticker}",
            policy=policy,
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


def test_expected_provider_item_failures_are_isolated_from_peer() -> None:
    research_input = _research_input(5)

    class IsolatingProvider(_ConcurrentProvider):
        async def search(self, request: object, *, deadline: Deadline) -> object:
            public = request.to_public_dict()  # type: ignore[attr-defined]
            ticker = public["instrument"]["canonical_ticker"]  # type: ignore[index]
            self.calls.append((public, deadline))
            if ticker == "SYN0.NAS":
                raise SearchProviderTimeoutError
            if ticker == "SYN1.NAS":
                return {"schema": "malformed"}
            if ticker == "SYN2.NAS":
                return _payload(_instrument(2), [])
            if ticker == "SYN3.NAS":
                raise SearchProviderOperationalError
            return _payload(_instrument(4))

    provider = IsolatingProvider({})

    result = asyncio.run(
        EvidenceResearcherV0(provider, _RecordingVerifier()).research(research_input)
    )

    assert type(result) is ResearchCompletedV0
    assert [type(item) for item in result.items] == [
        ResearchItemTimedOutV0,
        ResearchItemMalformedV0,
        ResearchItemNoUsableSourceV0,
        ResearchItemProviderFailedV0,
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
    with pytest.raises(TypeError, match="artifact"):
        research_orchestrator._create_research_item_succeeded_v0(
            instrument=instrument,
            articles=(),
            policy=ResearchSourcePolicyV0(),
        )

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


def test_invocation_zero_redirect_policy_is_enforced_by_shared_verifier() -> None:
    class Resolver:
        async def resolve(
            self, hostname: str, port: int, *, timeout: float
        ) -> tuple[str, ...]:
            del hostname, port, timeout
            return ("93.184.216.34",)

    class RedirectingFetcher:
        def __init__(self) -> None:
            self.calls: list[str] = []

        async def fetch(
            self,
            url: str,
            addresses: tuple[str, ...],
            *,
            timeout: float,
            max_bytes: int,
        ) -> ArticleFetchResponseV0:
            del addresses, timeout, max_bytes
            self.calls.append(url)
            if url.endswith("/primary"):
                return ArticleFetchResponseV0(
                    status_code=302,
                    content_type="text/plain",
                    content_encoding=None,
                    body=b"",
                    location="/final",
                )
            return ArticleFetchResponseV0(
                status_code=200,
                content_type="text/plain",
                content_encoding=None,
                body=b"Synthetic article",
                location=None,
            )

    research_input = ResearchInputV0(
        instruments=(_instrument(0),),
        questions=(ResearchQuestionV0.RECENT_MATERIAL_DEVELOPMENTS,),
        source_policy=ResearchSourcePolicyV0(max_redirects=0),
    )
    provider = _ConcurrentProvider({"SYN0.NAS": _payload(_instrument(0))})
    fetcher = RedirectingFetcher()

    result = asyncio.run(
        EvidenceResearcherV0(
            provider,
            SafeArticleVerifierV0(resolver=Resolver(), fetcher=fetcher),
        ).research(research_input)
    )

    assert type(result) is ResearchCompletedV0
    assert type(result.items[0]) is ResearchItemNoUsableSourceV0
    assert result.items[0].issues[0].code == "REDIRECT_LIMIT"
    assert fetcher.calls == ["https://evidence.example/SYN0.NAS/primary"]


def test_invocation_looser_than_verifier_hard_limit_blocks_before_provider() -> None:
    class Resolver:
        async def resolve(
            self, hostname: str, port: int, *, timeout: float
        ) -> tuple[str, ...]:
            del hostname, port, timeout
            return ("93.184.216.34",)

    class Fetcher:
        async def fetch(
            self,
            url: str,
            addresses: tuple[str, ...],
            *,
            timeout: float,
            max_bytes: int,
        ) -> ArticleFetchResponseV0:
            del url, addresses, timeout, max_bytes
            raise AssertionError("provider must not start")

    research_input = ResearchInputV0(
        instruments=(_instrument(0),),
        questions=(ResearchQuestionV0.RECENT_MATERIAL_DEVELOPMENTS,),
        source_policy=ResearchSourcePolicyV0(max_redirects=3),
    )
    provider = _ConcurrentProvider({})
    verifier = SafeArticleVerifierV0(
        resolver=Resolver(),
        fetcher=Fetcher(),
        policy=ResearchSourcePolicyV0(max_redirects=0),
    )

    result = asyncio.run(
        EvidenceResearcherV0(provider, verifier).research(research_input)
    )

    assert type(result) is ResearchSharedBlockedV0
    assert result.issue.code == "VERIFIER_CONFIG_UNSAFE"
    assert provider.calls == []


@pytest.mark.parametrize(
    "failure_site",
    [
        "preflight",
        "preflight_wrong_code",
        "provider",
        "verify",
        "verify_wrong_code",
        "clock",
    ],
)
def test_unexpected_operational_boundary_failures_become_typed_failed(
    failure_site: str,
) -> None:
    research_input = _research_input(1)

    class Provider(_ConcurrentProvider):
        async def search(self, request: object, *, deadline: Deadline) -> object:
            if failure_site == "provider":
                raise RuntimeError("PRIVATE-RUNTIME-SENTINEL")
            return await super().search(request, deadline=deadline)

    class Verifier(_RecordingVerifier):
        def preflight(self, policy: ResearchSourcePolicyV0) -> None:
            if failure_site == "preflight":
                raise AssertionError("PRIVATE-PREFLIGHT-SENTINEL")
            if failure_site == "preflight_wrong_code":
                raise ArticlePreflightError("DNS_TIMEOUT", "PRIVATE-PREFLIGHT-SENTINEL")
            super().preflight(policy)

        async def verify(
            self,
            source: SourceCandidateV0,
            *,
            deadline: Deadline,
            policy: ResearchSourcePolicyV0,
        ) -> ArticleArtifactV0:
            if failure_site == "verify":
                raise RuntimeError("PRIVATE-VERIFY-SENTINEL")
            if failure_site == "verify_wrong_code":
                raise ArticleSafetyError(
                    "VERIFIER_UNAVAILABLE", "PRIVATE-VERIFY-SENTINEL"
                )
            return await super().verify(source, deadline=deadline, policy=policy)

    provider = Provider({"SYN0.NAS": _payload(_instrument(0))})

    def clock() -> float:
        if failure_site == "clock":
            raise RuntimeError("PRIVATE-CLOCK-SENTINEL")
        return 10.0

    result = asyncio.run(
        EvidenceResearcherV0(provider, Verifier(), monotonic=clock).research(
            research_input
        )
    )

    assert type(result) is ResearchInputFailedV0
    assert result.status == "FAILED"
    assert result.issue.code == "RESEARCH_INVARIANT"
    assert "PRIVATE-" not in repr(result)


@pytest.mark.parametrize(
    "artifact_case",
    ["file_url", "bad_hash", "control", "oversize", "forged_source", "subclass"],
)
def test_untrusted_verifier_artifacts_never_become_success(
    artifact_case: str,
) -> None:
    private_sentinel = "PRIVATE-ARTIFACT-SENTINEL"
    research_input = ResearchInputV0(
        instruments=(_instrument(0),),
        questions=(ResearchQuestionV0.RECENT_MATERIAL_DEVELOPMENTS,),
        source_policy=ResearchSourcePolicyV0(max_article_text_chars=32),
    )
    provider = _ConcurrentProvider({"SYN0.NAS": _payload(_instrument(0))})

    class ForgedArtifact(ArticleArtifactV0):
        private_metadata = private_sentinel

    class Verifier(_RecordingVerifier):
        async def verify(
            self,
            source: SourceCandidateV0,
            *,
            deadline: Deadline,
            policy: ResearchSourcePolicyV0,
        ) -> ArticleArtifactV0:
            del deadline, policy
            artifact_source = source
            final_url = source.canonical_url
            text = "Synthetic trusted body"
            content_hash = "sha256:22354f5ec53c9893dcf407910b5bc6bf3f5ef40af998bf7facfdf2536bace6c9"
            if artifact_case == "file_url":
                final_url = "file:///tmp/private"
            elif artifact_case == "bad_hash":
                content_hash = f"sha256:{'0' * 64}"
            elif artifact_case == "control":
                text = f"Synthetic\x00{private_sentinel}"
            elif artifact_case == "oversize":
                text = private_sentinel * 4
            elif artifact_case == "forged_source":
                artifact_source = create_source_candidate_v0(
                    instrument=source.instrument,
                    title=private_sentinel,
                    canonical_url=source.canonical_url,
                    publisher=source.publisher,
                    published_at=source.published_at,
                    purpose=source.purpose,
                )
            artifact_type = (
                ForgedArtifact if artifact_case == "subclass" else ArticleArtifactV0
            )
            artifact = object.__new__(artifact_type)
            object.__setattr__(artifact, "source", artifact_source)
            object.__setattr__(artifact, "final_url", final_url)
            object.__setattr__(artifact, "normalized_text", text)
            object.__setattr__(artifact, "content_hash", content_hash)
            return artifact

    result = asyncio.run(
        EvidenceResearcherV0(provider, Verifier()).research(research_input)
    )

    assert type(result) is ResearchInputFailedV0
    assert result.issue.code == "RESEARCH_INVARIANT"
    assert private_sentinel not in repr(result)


def test_arbitrary_issue_code_and_message_cannot_be_constructed() -> None:
    with pytest.raises(TypeError):
        ResearchIssueV0(  # type: ignore[call-arg]
            code="ARBITRARY_STATUS",
            message="PRIVATE-ISSUE-SENTINEL",
        )


def test_invocation_policy_children_cannot_mutate_internal_baseline() -> None:
    preflight_policies: list[ResearchSourcePolicyV0] = []
    verify_policies: list[ResearchSourcePolicyV0] = []
    research_input = ResearchInputV0(
        instruments=(_instrument(0),),
        questions=(ResearchQuestionV0.RECENT_MATERIAL_DEVELOPMENTS,),
        source_policy=ResearchSourcePolicyV0(max_article_text_chars=16),
    )
    provider = _ConcurrentProvider({"SYN0.NAS": _payload(_instrument(0))})

    class MutatingVerifier(_RecordingVerifier):
        def preflight(self, policy: ResearchSourcePolicyV0) -> None:
            preflight_policies.append(policy)
            object.__setattr__(policy, "max_article_text_chars", 200_000)

        async def verify(
            self,
            source: SourceCandidateV0,
            *,
            deadline: Deadline,
            policy: ResearchSourcePolicyV0,
        ) -> ArticleArtifactV0:
            del deadline
            verify_policies.append(policy)
            object.__setattr__(policy, "max_article_text_chars", 200_000)
            return create_article_artifact_v0(
                source=source,
                final_url=source.canonical_url,
                normalized_text="Synthetic text longer than sixteen characters",
                policy=policy,
            )

    result = asyncio.run(
        EvidenceResearcherV0(provider, MutatingVerifier()).research(research_input)
    )

    assert type(result) is ResearchInputFailedV0
    assert result.issue.code == "RESEARCH_INVARIANT"
    assert research_input.source_policy.max_article_text_chars == 16
    assert preflight_policies[0] is not verify_policies[0]
    assert preflight_policies[0] is not research_input.source_policy
    assert verify_policies[0] is not research_input.source_policy


def test_mutated_input_policy_is_revalidated_at_invocation_start() -> None:
    research_input = _research_input(1)
    object.__setattr__(research_input.source_policy, "max_redirects", 999)
    provider = _ConcurrentProvider({})

    result = asyncio.run(
        EvidenceResearcherV0(provider, _RecordingVerifier()).research(research_input)
    )

    assert type(result) is ResearchInputFailedV0
    assert result.issue.code == "RESEARCH_INPUT_INVALID"
    assert provider.calls == []


@pytest.mark.parametrize("mutated_field", ["title", "canonical_ticker"])
def test_verifier_source_mutation_cannot_change_internal_binding(
    mutated_field: str,
) -> None:
    private_sentinel = "PRIVATE-SOURCE-SENTINEL"
    research_input = _research_input(1)
    provider = _ConcurrentProvider({"SYN0.NAS": _payload(_instrument(0))})

    class MutatingVerifier(_RecordingVerifier):
        async def verify(
            self,
            source: SourceCandidateV0,
            *,
            deadline: Deadline,
            policy: ResearchSourcePolicyV0,
        ) -> ArticleArtifactV0:
            del deadline
            object.__setattr__(source, mutated_field, private_sentinel)
            return create_article_artifact_v0(
                source=source,
                final_url=source.canonical_url,
                normalized_text="Synthetic body",
                policy=policy,
            )

    result = asyncio.run(
        EvidenceResearcherV0(provider, MutatingVerifier()).research(research_input)
    )

    assert type(result) is ResearchInputFailedV0
    assert result.issue.code == "RESEARCH_INVARIANT"
    assert private_sentinel not in repr(result)


def test_verifier_and_success_result_do_not_share_source_identity() -> None:
    research_input = _research_input(1)
    provider = _ConcurrentProvider({"SYN0.NAS": _payload(_instrument(0))})
    verifier = _RecordingVerifier()

    result = asyncio.run(
        EvidenceResearcherV0(provider, verifier).research(research_input)
    )

    assert type(result) is ResearchCompletedV0
    item = result.items[0]
    assert type(item) is ResearchItemSucceededV0
    assert item.articles[0].source is not verifier.calls[0][0]


@pytest.mark.parametrize(
    "identity_overrides",
    [
        {"canonical_ticker": "SYN0.NYS", "exchange": "NYSE"},
        {"identity_source": "other-directory"},
        {"identity_version": "fixture-other"},
    ],
)
def test_success_result_rejects_article_bound_to_another_instrument(
    identity_overrides: dict[str, str],
) -> None:
    research_input = _research_input(1)
    provider = _ConcurrentProvider({"SYN0.NAS": _payload(_instrument(0))})
    result = asyncio.run(
        EvidenceResearcherV0(provider, _RecordingVerifier()).research(research_input)
    )
    assert type(result) is ResearchCompletedV0
    item = result.items[0]
    assert type(item) is ResearchItemSucceededV0

    wrong_identity = InstrumentRefV0(
        **{**item.instrument.to_public_dict(), **identity_overrides}
    )
    with pytest.raises((TypeError, ValueError), match="artifact"):
        research_orchestrator._create_research_item_succeeded_v0(
            instrument=wrong_identity,
            articles=item.articles,
            policy=research_input.source_policy,
        )


@pytest.mark.parametrize(
    ("failure_phase", "clock_change", "expected_type", "expected_code"),
    [
        ("preflight", "expire", ResearchCompletedV0, "PROVIDER_TIMEOUT"),
        ("preflight", "rollback", ResearchInputFailedV0, "DEADLINE_INVARIANT"),
        ("provider_operational", "expire", ResearchCompletedV0, "PROVIDER_TIMEOUT"),
        ("provider_timeout", "rollback", ResearchInputFailedV0, "DEADLINE_INVARIANT"),
        ("article", "expire", ResearchCompletedV0, "ARTICLE_TIMEOUT"),
        ("article", "rollback", ResearchInputFailedV0, "DEADLINE_INVARIANT"),
    ],
)
def test_deadline_state_precedes_typed_operational_classification(
    failure_phase: str,
    clock_change: str,
    expected_type: type[object],
    expected_code: str,
) -> None:
    class Clock:
        now = 10.0

        def __call__(self) -> float:
            return self.now

        def change(self) -> None:
            self.now = 60.0 if clock_change == "expire" else 9.0

    clock = Clock()
    research_input = _research_input(1)

    class Provider(_ConcurrentProvider):
        async def search(self, request: object, *, deadline: Deadline) -> object:
            if failure_phase.startswith("provider"):
                clock.change()
                if failure_phase == "provider_timeout":
                    raise SearchProviderTimeoutError
                raise SearchProviderOperationalError
            return await super().search(request, deadline=deadline)

    class Verifier(_RecordingVerifier):
        def preflight(self, policy: ResearchSourcePolicyV0) -> None:
            del policy
            if failure_phase == "preflight":
                clock.change()
                raise ArticlePreflightError("VERIFIER_UNAVAILABLE", "synthetic")

        async def verify(
            self,
            source: SourceCandidateV0,
            *,
            deadline: Deadline,
            policy: ResearchSourcePolicyV0,
        ) -> ArticleArtifactV0:
            if failure_phase == "article":
                clock.change()
                raise ArticleSafetyError("ARTICLE_EMPTY", "synthetic")
            return await super().verify(source, deadline=deadline, policy=policy)

    result = asyncio.run(
        EvidenceResearcherV0(
            Provider({"SYN0.NAS": _payload(_instrument(0))}),
            Verifier(),
            monotonic=clock,
        ).research(research_input)
    )

    assert type(result) is expected_type
    if type(result) is ResearchCompletedV0:
        item = result.items[0]
        assert type(item) is ResearchItemTimedOutV0
        assert item.issues[0].code == expected_code
    else:
        assert type(result) is ResearchInputFailedV0
        assert result.issue.code == expected_code


def test_timed_out_result_requires_a_timeout_issue() -> None:
    research_input = _research_input(1)
    provider = _ConcurrentProvider({"SYN0.NAS": _payload(_instrument(0))})

    class EmptyVerifier(_RecordingVerifier):
        async def verify(
            self,
            source: SourceCandidateV0,
            *,
            deadline: Deadline,
            policy: ResearchSourcePolicyV0,
        ) -> ArticleArtifactV0:
            del source, deadline, policy
            raise ArticleSafetyError("ARTICLE_EMPTY", "synthetic")

    result = asyncio.run(
        EvidenceResearcherV0(provider, EmptyVerifier()).research(research_input)
    )
    assert type(result) is ResearchCompletedV0
    no_source = result.items[0]
    assert type(no_source) is ResearchItemNoUsableSourceV0

    with pytest.raises(ValueError, match="timeout issue"):
        ResearchItemTimedOutV0(
            instrument=no_source.instrument,
            issues=no_source.issues,
        )


def test_success_result_public_constructor_is_closed() -> None:
    research_input = _research_input(1)
    result = asyncio.run(
        EvidenceResearcherV0(
            _ConcurrentProvider({"SYN0.NAS": _payload(_instrument(0))}),
            _RecordingVerifier(),
        ).research(research_input)
    )
    assert type(result) is ResearchCompletedV0
    item = result.items[0]
    assert type(item) is ResearchItemSucceededV0

    with pytest.raises(TypeError):
        ResearchItemSucceededV0(  # type: ignore[call-arg]
            instrument=item.instrument,
            articles=item.articles,
        )
    with pytest.raises(TypeError):
        ResearchItemSucceededV0()
    assert not hasattr(research_package, "create_research_item_succeeded_v0")
    assert not hasattr(research_orchestrator, "create_research_item_succeeded_v0")


@pytest.mark.parametrize(
    "artifact_case",
    ["file_url", "bad_hash", "private_text", "source", "subclass"],
)
def test_success_factory_rejects_mutated_or_subclass_artifact(
    artifact_case: str,
) -> None:
    private_sentinel = "PRIVATE-SUCCESS-SENTINEL"
    policy = ResearchSourcePolicyV0()
    research_input = ResearchInputV0(
        instruments=(_instrument(0),),
        questions=(ResearchQuestionV0.RECENT_MATERIAL_DEVELOPMENTS,),
        source_policy=policy,
    )
    result = asyncio.run(
        EvidenceResearcherV0(
            _ConcurrentProvider({"SYN0.NAS": _payload(_instrument(0))}),
            _RecordingVerifier(),
        ).research(research_input)
    )
    assert type(result) is ResearchCompletedV0
    item = result.items[0]
    assert type(item) is ResearchItemSucceededV0
    artifact = item.articles[0]

    if artifact_case == "file_url":
        object.__setattr__(artifact, "final_url", "file:///tmp/private")
    elif artifact_case == "bad_hash":
        object.__setattr__(artifact, "content_hash", f"sha256:{'0' * 64}")
    elif artifact_case == "private_text":
        object.__setattr__(artifact, "normalized_text", private_sentinel)
    elif artifact_case == "source":
        object.__setattr__(artifact.source, "title", private_sentinel)
    else:

        class ArtifactWithPrivateState(ArticleArtifactV0):
            private_value = private_sentinel

        forged = object.__new__(ArtifactWithPrivateState)
        for field_name in ArticleArtifactV0.__slots__:
            object.__setattr__(forged, field_name, getattr(artifact, field_name))
        artifact = forged

    factory = getattr(
        research_orchestrator,
        "_create_research_item_succeeded_v0",
        None,
    )
    assert callable(factory)
    with pytest.raises((TypeError, ValueError), match="artifact") as exc_info:
        factory(
            instrument=item.instrument,
            articles=(artifact,),
            issues=(),
            policy=policy,
        )
    assert private_sentinel not in str(exc_info.value)


def test_success_factory_copies_exact_artifact_tuple_and_rejects_tuple_subclass() -> (
    None
):
    policy = ResearchSourcePolicyV0()
    research_input = ResearchInputV0(
        instruments=(_instrument(0),),
        questions=(ResearchQuestionV0.RECENT_MATERIAL_DEVELOPMENTS,),
        source_policy=policy,
    )
    result = asyncio.run(
        EvidenceResearcherV0(
            _ConcurrentProvider({"SYN0.NAS": _payload(_instrument(0))}),
            _RecordingVerifier(),
        ).research(research_input)
    )
    assert type(result) is ResearchCompletedV0
    item = result.items[0]
    assert type(item) is ResearchItemSucceededV0
    supplied = item.articles
    factory = getattr(
        research_orchestrator,
        "_create_research_item_succeeded_v0",
        None,
    )
    assert callable(factory)

    copied = factory(
        instrument=item.instrument,
        articles=supplied,
        issues=(),
        policy=policy,
    )

    assert type(copied) is ResearchItemSucceededV0
    assert copied.articles is not supplied
    assert copied.articles[0] is not supplied[0]

    class ArtifactTuple(tuple[ArticleArtifactV0]):
        pass

    with pytest.raises(TypeError, match="artifact"):
        factory(
            instrument=item.instrument,
            articles=ArtifactTuple(supplied),
            issues=(),
            policy=policy,
        )


def test_verify_deadline_preserves_completed_peer_and_stops_remaining_sources() -> None:
    class Clock:
        now = 0.0

        def __call__(self) -> float:
            return self.now

    clock = Clock()
    research_input = _research_input(3)
    provider = _ConcurrentProvider(
        {
            instrument.canonical_ticker: _payload(instrument)
            for instrument in research_input.instruments
        }
    )

    class DeadlineVerifier(_RecordingVerifier):
        async def verify(
            self,
            source: SourceCandidateV0,
            *,
            deadline: Deadline,
            policy: ResearchSourcePolicyV0,
        ) -> ArticleArtifactV0:
            self.calls.append((source, deadline))
            if source.canonical_ticker == "SYN0.NAS":
                clock.now = 40.0
                return create_article_artifact_v0(
                    source=source,
                    final_url=source.canonical_url,
                    normalized_text="Synthetic completed peer",
                    policy=policy,
                )
            if source.canonical_ticker == "SYN1.NAS":
                clock.now = 46.0
                raise ArticleSafetyError("ARTICLE_EMPTY", "synthetic")
            raise AssertionError("queued source must not start")

    verifier = DeadlineVerifier()
    result = asyncio.run(
        EvidenceResearcherV0(provider, verifier, monotonic=clock).research(
            research_input
        )
    )

    assert type(result) is ResearchCompletedV0
    assert [type(item) for item in result.items] == [
        ResearchItemSucceededV0,
        ResearchItemTimedOutV0,
        ResearchItemTimedOutV0,
    ]
    assert [issue.code for issue in result.items[0].issues] == []
    assert [issue.code for issue in result.items[1].issues] == ["ARTICLE_TIMEOUT"]
    assert [issue.code for issue in result.items[2].issues] == ["ARTICLE_TIMEOUT"]
    assert [call[0].canonical_ticker for call in verifier.calls] == [
        "SYN0.NAS",
        "SYN1.NAS",
    ]


def test_verify_deadline_preserves_same_instrument_partial_success() -> None:
    class Clock:
        now = 0.0

        def __call__(self) -> float:
            return self.now

    clock = Clock()
    instrument = _instrument(0)
    research_input = ResearchInputV0(
        instruments=(instrument,),
        questions=(ResearchQuestionV0.RECENT_MATERIAL_DEVELOPMENTS,),
    )
    provider = _ConcurrentProvider(
        {
            instrument.canonical_ticker: _payload(
                instrument,
                [
                    _row(instrument, suffix="primary"),
                    _row(instrument, suffix="opposing", purpose="OPPOSING"),
                    _row(instrument, suffix="queued", purpose="ACTION_CHANGING"),
                ],
            )
        }
    )

    class DeadlineVerifier(_RecordingVerifier):
        async def verify(
            self,
            source: SourceCandidateV0,
            *,
            deadline: Deadline,
            policy: ResearchSourcePolicyV0,
        ) -> ArticleArtifactV0:
            self.calls.append((source, deadline))
            if source.canonical_url.endswith("/primary"):
                clock.now = 40.0
                return create_article_artifact_v0(
                    source=source,
                    final_url=source.canonical_url,
                    normalized_text="Synthetic partial success",
                    policy=policy,
                )
            if source.canonical_url.endswith("/opposing"):
                clock.now = 46.0
                raise ArticleSafetyError("ARTICLE_EMPTY", "synthetic")
            raise AssertionError("queued source must not start")

    verifier = DeadlineVerifier()
    result = asyncio.run(
        EvidenceResearcherV0(provider, verifier, monotonic=clock).research(
            research_input
        )
    )

    assert type(result) is ResearchCompletedV0
    item = result.items[0]
    assert type(item) is ResearchItemSucceededV0
    assert len(item.articles) == 1
    assert [issue.code for issue in item.issues] == ["ARTICLE_TIMEOUT"]
    assert len(verifier.calls) == 2
