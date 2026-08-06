from __future__ import annotations

import asyncio
from dataclasses import replace
from datetime import UTC, datetime

import pytest
from sab.research.contracts import (
    ResearchSourcePolicyV0,
    SourceCandidateV0,
    SourcePurposeV0,
)
from sab.research.deadline import Deadline
from sab.research.source_safety import (
    ArticleFetchResponseV0,
    ArticleSafetyError,
    SafeArticleVerifierV0,
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
    return SourceCandidateV0(
        canonical_ticker="AUR.NAS",
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

    artifact = asyncio.run(verifier.verify(_source(), deadline=deadline))

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
            verifier.verify(_source(), deadline=Deadline.start(45.0, monotonic=clock))
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
            verifier.verify(_source(), deadline=Deadline.start(45.0, monotonic=clock))
        )
    assert exc_info.value.code == "ARTICLE_TEXT_TOO_LARGE"
