from __future__ import annotations

import asyncio
from dataclasses import replace
from datetime import UTC, datetime

import pytest
import sab.research.source_safety as research_source_safety
from sab.decision_board.instruments import InstrumentRefV0
from sab.research.contracts import (
    ResearchSourcePolicyV0,
    SourceCandidateV0,
    SourcePurposeV0,
    create_source_candidate_v0,
    validate_and_copy_source_candidate_v0,
)
from sab.research.deadline import (
    Deadline,
    DeadlineExpiredError,
    DeadlineInvariantError,
)
from sab.research.source_safety import (
    ArticleArtifactValidationError,
    ArticleFetchResponseV0,
    ArticleSafetyError,
    SafeArticleVerifierV0,
    create_article_artifact_v0,
    validate_and_copy_article_artifact_v0,
)
from sab.research.urls import canonicalize_public_article_url_v0


class _FakeClock:
    def __init__(self) -> None:
        self.now = 10.0

    def __call__(self) -> float:
        return self.now


class _FakeResolver:
    def __init__(
        self,
        clock: _FakeClock,
        answers: dict[str, tuple[str, ...]],
    ) -> None:
        self.clock = clock
        self.answers = answers
        self.calls: list[tuple[str, int, float]] = []

    async def resolve(
        self, hostname: str, port: int, *, timeout: float
    ) -> tuple[str, ...]:
        self.calls.append((hostname, port, timeout))
        self.clock.now += 1.0
        return self.answers[hostname]


class _FakeFetcher:
    def __init__(
        self,
        clock: _FakeClock,
        responses: dict[str, ArticleFetchResponseV0],
    ) -> None:
        self.clock = clock
        self.responses = responses
        self.calls: list[tuple[str, tuple[str, ...], float, int]] = []

    async def fetch(
        self,
        url: str,
        addresses: tuple[str, ...],
        *,
        timeout: float,
        max_bytes: int,
    ) -> ArticleFetchResponseV0:
        self.calls.append((url, addresses, timeout, max_bytes))
        self.clock.now += 2.0
        return self.responses[url]


def _source(url: str = "https://evidence.example/start") -> SourceCandidateV0:
    return create_source_candidate_v0(
        instrument=InstrumentRefV0(
            market="US",
            canonical_ticker="AUR.NAS",
            exchange="NASDAQ",
            company_name="Aurora Synthetic Systems",
            identity_source="synthetic-directory",
            identity_version="fixture-2026-08-07",
        ),
        title="Synthetic evidence",
        canonical_url=url,
        publisher="Synthetic Wire",
        published_at=datetime(2026, 8, 7, 1, 0, tzinfo=UTC),
        purpose=SourcePurposeV0.PRIMARY,
    )


def _response(**overrides: object) -> ArticleFetchResponseV0:
    values: dict[str, object] = {
        "status_code": 200,
        "content_type": "text/html; charset=utf-8",
        "content_encoding": None,
        "body": b"<article>Aurora synthetic article body.</article>",
        "location": None,
    }
    values.update(overrides)
    return ArticleFetchResponseV0(**values)  # type: ignore[arg-type]


@pytest.mark.parametrize(
    "url",
    [
        "file:///tmp/article",
        "https://user:password@evidence.example/article",
        "https://localhost/article",
        "https://intranet/article",
        "https://service.local/article",
        "http://127.0.0.1/article",
        "https://169.254.1.7/article",
        "https://224.0.0.1/article",
        "https://192.0.2.1/article",
        "https://evidence.example/article#private-fragment",
    ],
)
def test_non_public_or_fragmented_article_urls_are_rejected(url: str) -> None:
    with pytest.raises(ValueError):
        canonicalize_public_article_url_v0(url)


def test_mixed_public_and_private_dns_answers_fail_closed_before_fetch() -> None:
    clock = _FakeClock()
    resolver = _FakeResolver(
        clock,
        {"evidence.example": ("93.184.216.34", "10.0.0.7")},
    )
    fetcher = _FakeFetcher(clock, {})
    verifier = SafeArticleVerifierV0(resolver=resolver, fetcher=fetcher)

    with pytest.raises(ArticleSafetyError) as exc_info:
        asyncio.run(
            verifier.verify(
                _source(),
                deadline=Deadline.start(45.0, monotonic=clock),
                policy=verifier.policy,
            )
        )

    assert exc_info.value.code == "DNS_NOT_PUBLIC"
    assert fetcher.calls == []


def test_redirects_revalidate_target_and_never_leave_original_origin() -> None:
    clock = _FakeClock()
    resolver = _FakeResolver(
        clock,
        {"evidence.example": ("93.184.216.34",)},
    )
    fetcher = _FakeFetcher(
        clock,
        {
            "https://evidence.example/start": _response(
                status_code=302,
                body=b"",
                content_type="text/plain",
                location="http://127.0.0.1/private",
            )
        },
    )
    verifier = SafeArticleVerifierV0(resolver=resolver, fetcher=fetcher)

    with pytest.raises(ArticleSafetyError) as exc_info:
        asyncio.run(
            verifier.verify(
                _source(),
                deadline=Deadline.start(45.0, monotonic=clock),
                policy=verifier.policy,
            )
        )

    assert exc_info.value.code == "REDIRECT_UNSAFE"
    assert len(resolver.calls) == 1
    assert len(fetcher.calls) == 1


def test_safe_redirect_uses_shrinking_timeouts_and_returns_normalized_hash() -> None:
    clock = _FakeClock()
    resolver = _FakeResolver(
        clock,
        {"evidence.example": ("93.184.216.34",)},
    )
    fetcher = _FakeFetcher(
        clock,
        {
            "https://evidence.example/start": _response(
                status_code=302,
                body=b"",
                content_type="text/plain",
                location="/article",
            ),
            "https://evidence.example/article": _response(),
        },
    )
    verifier = SafeArticleVerifierV0(resolver=resolver, fetcher=fetcher)
    deadline = Deadline.start(12.0, monotonic=clock)

    artifact = asyncio.run(
        verifier.verify(_source(), deadline=deadline, policy=verifier.policy)
    )

    assert artifact.final_url == "https://evidence.example/article"
    assert artifact.normalized_text == "Aurora synthetic article body."
    assert artifact.content_hash == (
        "sha256:36e6a7057af414e8acc6299aaadb30d9959cc2335b6f95de560bdc1c85b87dea"
    )
    assert [call[2] for call in resolver.calls] == [10.0, 9.0]
    assert [call[2] for call in fetcher.calls] == [10.0, 8.0]
    assert deadline.remaining() == 6.0


@pytest.mark.parametrize(
    ("response", "max_response_bytes", "expected_code"),
    [
        (_response(content_type="application/json"), 100, "CONTENT_TYPE_UNSAFE"),
        (_response(content_encoding="gzip"), 100, "CONTENT_ENCODING_UNSAFE"),
        (
            _response(content_type="text/plain; charset=iso-8859-1; note=utf-8"),
            100,
            "CONTENT_TYPE_UNSAFE",
        ),
        (_response(body=b""), 100, "ARTICLE_EMPTY"),
        (_response(body=b"x" * 21), 20, "RESPONSE_TOO_LARGE"),
    ],
)
def test_article_response_bounds_fail_closed(
    response: ArticleFetchResponseV0,
    max_response_bytes: int,
    expected_code: str,
) -> None:
    clock = _FakeClock()
    resolver = _FakeResolver(clock, {"evidence.example": ("93.184.216.34",)})
    fetcher = _FakeFetcher(
        clock,
        {"https://evidence.example/start": response},
    )
    policy = replace(ResearchSourcePolicyV0(), max_response_bytes=max_response_bytes)
    verifier = SafeArticleVerifierV0(
        resolver=resolver,
        fetcher=fetcher,
        policy=policy,
    )

    with pytest.raises(ArticleSafetyError) as exc_info:
        asyncio.run(
            verifier.verify(
                _source(),
                deadline=Deadline.start(45.0, monotonic=clock),
                policy=verifier.policy,
            )
        )

    assert exc_info.value.code == expected_code


def test_non_ip_dns_answer_and_oversized_normalized_text_are_rejected() -> None:
    clock = _FakeClock()
    bad_resolver = _FakeResolver(clock, {"evidence.example": ("not-an-ip",)})
    verifier = SafeArticleVerifierV0(
        resolver=bad_resolver,
        fetcher=_FakeFetcher(clock, {}),
    )
    with pytest.raises(ArticleSafetyError) as exc_info:
        asyncio.run(
            verifier.verify(
                _source(),
                deadline=Deadline.start(45.0, monotonic=clock),
                policy=verifier.policy,
            )
        )
    assert exc_info.value.code == "DNS_INVALID"

    clock = _FakeClock()
    verifier = SafeArticleVerifierV0(
        resolver=_FakeResolver(clock, {"evidence.example": ("93.184.216.34",)}),
        fetcher=_FakeFetcher(
            clock,
            {"https://evidence.example/start": _response(body=b"123456")},
        ),
        policy=replace(ResearchSourcePolicyV0(), max_article_text_chars=5),
    )
    with pytest.raises(ArticleSafetyError) as exc_info:
        asyncio.run(
            verifier.verify(
                _source(),
                deadline=Deadline.start(45.0, monotonic=clock),
                policy=verifier.policy,
            )
        )
    assert exc_info.value.code == "ARTICLE_TEXT_TOO_LARGE"


def test_verifier_hard_policy_is_an_internal_copy_not_a_caller_alias() -> None:
    clock = _FakeClock()
    caller_policy = ResearchSourcePolicyV0(
        max_redirects=0,
        max_article_text_chars=16,
    )
    verifier = SafeArticleVerifierV0(
        resolver=_FakeResolver(clock, {"evidence.example": ("93.184.216.34",)}),
        fetcher=_FakeFetcher(clock, {}),
        policy=caller_policy,
    )

    assert verifier.policy == caller_policy
    assert verifier.policy is not caller_policy

    object.__setattr__(caller_policy, "max_redirects", 5)
    object.__setattr__(verifier.policy, "max_redirects", 5)

    with pytest.raises(ArticleSafetyError) as exc_info:
        verifier.preflight(ResearchSourcePolicyV0(max_redirects=1))

    assert exc_info.value.code == "VERIFIER_CONFIG_UNSAFE"


def test_artifact_validation_detects_in_place_source_mutation() -> None:
    private_sentinel = "PRIVATE-ARTIFACT-SOURCE-SENTINEL"
    policy = ResearchSourcePolicyV0()
    artifact = create_article_artifact_v0(
        source=_source(),
        final_url="https://evidence.example/start",
        normalized_text="Synthetic trusted text",
        policy=policy,
    )
    expected_source = validate_and_copy_source_candidate_v0(
        artifact.source,
        expected_instrument=artifact.source.instrument,
    )
    object.__setattr__(artifact.source, "title", private_sentinel)
    object.__setattr__(
        artifact,
        "_integrity_seal",
        research_source_safety._article_integrity_seal(
            source=artifact.source,
            final_url=artifact.final_url,
            normalized_text=artifact.normalized_text,
            content_hash=artifact.content_hash,
        ),
    )

    with pytest.raises(ArticleArtifactValidationError) as exc_info:
        validate_and_copy_article_artifact_v0(
            artifact,
            expected_source=expected_source,
            policy=policy,
        )

    assert private_sentinel not in str(exc_info.value)


def test_artifact_validation_rejects_missing_integrity_seal() -> None:
    policy = ResearchSourcePolicyV0()
    artifact = create_article_artifact_v0(
        source=_source(),
        final_url="https://evidence.example/start",
        normalized_text="Synthetic trusted text",
        policy=policy,
    )
    object.__setattr__(artifact, "_integrity_seal", None)

    with pytest.raises(ArticleArtifactValidationError):
        validate_and_copy_article_artifact_v0(
            artifact,
            expected_source=artifact.source,
            policy=policy,
        )


def test_artifact_validation_rejects_legacy_creation_sentinel_injection() -> None:
    policy = ResearchSourcePolicyV0()
    artifact = create_article_artifact_v0(
        source=_source(),
        final_url="https://evidence.example/start",
        normalized_text="Synthetic trusted text",
        policy=policy,
    )
    expected_source = validate_and_copy_source_candidate_v0(
        artifact.source,
        expected_instrument=artifact.source.instrument,
    )
    legacy_sentinel = getattr(
        research_source_safety,
        "_CREATE_ARTIFACT_SEAL",
        object(),
    )
    object.__setattr__(artifact, "_integrity_seal", legacy_sentinel)

    with pytest.raises(ArticleArtifactValidationError, match="integrity seal"):
        validate_and_copy_article_artifact_v0(
            artifact,
            expected_source=expected_source,
            policy=policy,
        )
    assert not hasattr(research_source_safety, "_CREATE_ARTIFACT_SEAL")


@pytest.mark.parametrize("failure_site", ["dns", "fetch"])
def test_operation_timeout_preserves_exhausted_global_deadline(
    failure_site: str,
) -> None:
    clock = _FakeClock()

    class Resolver:
        async def resolve(
            self, hostname: str, port: int, *, timeout: float
        ) -> tuple[str, ...]:
            del hostname, port
            if failure_site == "dns":
                clock.now += timeout
                raise TimeoutError
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
            del url, addresses, max_bytes
            clock.now += timeout
            raise TimeoutError

    verifier = SafeArticleVerifierV0(resolver=Resolver(), fetcher=Fetcher())
    with pytest.raises(DeadlineExpiredError):
        asyncio.run(
            verifier.verify(
                _source(),
                deadline=Deadline.start(0.01, monotonic=clock),
                policy=verifier.policy,
            )
        )


def test_clock_rollback_during_timeout_handling_is_an_invariant_failure() -> None:
    clock = _FakeClock()

    class Resolver:
        async def resolve(
            self, hostname: str, port: int, *, timeout: float
        ) -> tuple[str, ...]:
            del hostname, port, timeout
            clock.now -= 1.0
            raise TimeoutError

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
            raise AssertionError("fetch must not start")

    verifier = SafeArticleVerifierV0(resolver=Resolver(), fetcher=Fetcher())
    with pytest.raises(DeadlineInvariantError):
        asyncio.run(
            verifier.verify(
                _source(),
                deadline=Deadline.start(45.0, monotonic=clock),
                policy=verifier.policy,
            )
        )


def test_dns_addresses_are_canonicalized_before_pinned_fetch() -> None:
    clock = _FakeClock()
    captured: list[tuple[str, ...]] = []

    class Resolver:
        async def resolve(
            self, hostname: str, port: int, *, timeout: float
        ) -> tuple[str, ...]:
            del hostname, port, timeout
            return (
                "2606:2800:0220:0001:0248:1893:25C8:1946",
                "93.184.216.34",
            )

    class Fetcher:
        async def fetch(
            self,
            url: str,
            addresses: tuple[str, ...],
            *,
            timeout: float,
            max_bytes: int,
        ) -> ArticleFetchResponseV0:
            del url, timeout, max_bytes
            captured.append(addresses)
            return _response(content_type="text/plain", body=b"Synthetic article")

    verifier = SafeArticleVerifierV0(resolver=Resolver(), fetcher=Fetcher())
    asyncio.run(
        verifier.verify(
            _source(),
            deadline=Deadline.start(45.0, monotonic=clock),
            policy=verifier.policy,
        )
    )

    assert captured == [("2606:2800:220:1:248:1893:25c8:1946", "93.184.216.34")]


def test_scoped_ipv6_dns_answer_is_rejected_before_fetch() -> None:
    clock = _FakeClock()
    fetcher = _FakeFetcher(clock, {})
    verifier = SafeArticleVerifierV0(
        resolver=_FakeResolver(
            clock,
            {"evidence.example": ("2606:4700:4700::1111%en0",)},
        ),
        fetcher=fetcher,
    )

    with pytest.raises(ArticleSafetyError) as exc_info:
        asyncio.run(
            verifier.verify(
                _source(),
                deadline=Deadline.start(45.0, monotonic=clock),
                policy=verifier.policy,
            )
        )

    assert exc_info.value.code == "DNS_INVALID"
    assert fetcher.calls == []


def test_ambiguous_noncanonical_ipv4_dns_answer_is_rejected() -> None:
    clock = _FakeClock()
    fetcher = _FakeFetcher(clock, {})
    verifier = SafeArticleVerifierV0(
        resolver=_FakeResolver(
            clock,
            {"evidence.example": ("093.184.216.034",)},
        ),
        fetcher=fetcher,
    )

    with pytest.raises(ArticleSafetyError) as exc_info:
        asyncio.run(
            verifier.verify(
                _source(),
                deadline=Deadline.start(45.0, monotonic=clock),
                policy=verifier.policy,
            )
        )

    assert exc_info.value.code == "DNS_INVALID"
    assert fetcher.calls == []
