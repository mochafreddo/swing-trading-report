"""Safe, injectable article retrieval with no claim interpretation."""

from __future__ import annotations

import hashlib
import ipaddress
import re
from collections.abc import Sequence
from dataclasses import dataclass, field
from html.parser import HTMLParser
from typing import Protocol
from unicodedata import category
from urllib.parse import urljoin, urlsplit

from sab import ai_brief_url_safety

from .contracts import ResearchSourcePolicyV0, SourceCandidateV0
from .deadline import Deadline
from .urls import canonicalize_public_article_url_v0


class ArticleSafetyError(RuntimeError):
    """A public source could not be retrieved safely."""

    def __init__(self, code: str, message: str) -> None:
        self.code = code
        super().__init__(f"{code}: {message}")


class ArticlePreflightError(ArticleSafetyError):
    """The shared verifier cannot safely start."""


@dataclass(frozen=True, slots=True)
class ArticleFetchResponseV0:
    status_code: int
    content_type: str
    content_encoding: str | None
    body: bytes
    location: str | None

    def __post_init__(self) -> None:
        if isinstance(self.status_code, bool) or not isinstance(self.status_code, int):
            raise TypeError("article response status_code must be an integer")
        if not isinstance(self.content_type, str):
            raise TypeError("article response content_type must be text")
        if self.content_encoding is not None and not isinstance(
            self.content_encoding, str
        ):
            raise TypeError("article response content_encoding must be text or null")
        if type(self.body) is not bytes:
            raise TypeError("article response body must be immutable bytes")
        if self.location is not None and not isinstance(self.location, str):
            raise TypeError("article response location must be text or null")


class ArticleArtifactValidationError(RuntimeError):
    """An injected verifier returned an untrusted artifact value."""


@dataclass(frozen=True, slots=True, init=False)
class ArticleArtifactV0:
    source: SourceCandidateV0
    final_url: str
    normalized_text: str
    content_hash: str


def create_article_artifact_v0(
    *,
    source: SourceCandidateV0,
    final_url: str,
    normalized_text: str,
    policy: ResearchSourcePolicyV0,
) -> ArticleArtifactV0:
    """Create one strictly validated immutable article artifact."""

    return _validated_article_artifact_v0(
        source=source,
        expected_source=source,
        final_url=final_url,
        normalized_text=normalized_text,
        content_hash=None,
        policy=policy,
    )


def validate_and_copy_article_artifact_v0(
    value: object,
    *,
    expected_source: SourceCandidateV0,
    policy: ResearchSourcePolicyV0,
) -> ArticleArtifactV0:
    """Revalidate an adapter artifact against its requested source and copy it."""

    if type(value) is not ArticleArtifactV0:
        raise ArticleArtifactValidationError("artifact must be exact ArticleArtifactV0")
    try:
        return _validated_article_artifact_v0(
            source=value.source,
            expected_source=expected_source,
            final_url=value.final_url,
            normalized_text=value.normalized_text,
            content_hash=value.content_hash,
            policy=policy,
        )
    except AttributeError as exc:
        raise ArticleArtifactValidationError("artifact fields are unavailable") from exc


def _validated_article_artifact_v0(
    *,
    source: object,
    expected_source: object,
    final_url: object,
    normalized_text: object,
    content_hash: object | None,
    policy: object,
) -> ArticleArtifactV0:
    if (
        type(source) is not SourceCandidateV0
        or type(expected_source) is not SourceCandidateV0
    ):
        raise ArticleArtifactValidationError("artifact source must be exact V0 source")
    if source != expected_source:
        raise ArticleArtifactValidationError(
            "artifact source does not match its request"
        )
    if type(policy) is not ResearchSourcePolicyV0:
        raise ArticleArtifactValidationError("artifact policy must be exact V0 policy")
    if not isinstance(final_url, str):
        raise ArticleArtifactValidationError("artifact final URL must be text")
    try:
        canonical_final_url = canonicalize_public_article_url_v0(final_url)
        canonical_source_url = canonicalize_public_article_url_v0(source.canonical_url)
    except ValueError as exc:
        raise ArticleArtifactValidationError("artifact URL is unsafe") from exc
    if canonical_final_url != final_url or _origin(canonical_final_url) != _origin(
        canonical_source_url
    ):
        raise ArticleArtifactValidationError(
            "artifact final URL must be canonical and same-origin"
        )
    if type(normalized_text) is not str:
        raise ArticleArtifactValidationError("artifact text must be exact text")
    if any(category(character) in {"Cc", "Cf", "Cs"} for character in normalized_text):
        raise ArticleArtifactValidationError("artifact text contains unsafe characters")
    if re.sub(r"\s+", " ", normalized_text).strip() != normalized_text:
        raise ArticleArtifactValidationError("artifact text is not normalized")
    if not normalized_text or len(normalized_text) > policy.max_article_text_chars:
        raise ArticleArtifactValidationError("artifact text exceeds its safe bound")
    expected_hash = (
        f"sha256:{hashlib.sha256(normalized_text.encode('utf-8')).hexdigest()}"
    )
    if content_hash is not None and (
        type(content_hash) is not str or content_hash != expected_hash
    ):
        raise ArticleArtifactValidationError("artifact content hash is invalid")
    artifact = object.__new__(ArticleArtifactV0)
    object.__setattr__(artifact, "source", source)
    object.__setattr__(artifact, "final_url", canonical_final_url)
    object.__setattr__(artifact, "normalized_text", normalized_text)
    object.__setattr__(artifact, "content_hash", expected_hash)
    return artifact


class PublicDnsResolverV0(Protocol):
    async def resolve(
        self,
        hostname: str,
        port: int,
        *,
        timeout: float,
    ) -> Sequence[str]: ...


class ArticleFetcherV0(Protocol):
    async def fetch(
        self,
        url: str,
        addresses: tuple[str, ...],
        *,
        timeout: float,
        max_bytes: int,
    ) -> ArticleFetchResponseV0: ...


@dataclass(frozen=True, slots=True)
class SafeArticleVerifierV0:
    resolver: PublicDnsResolverV0
    fetcher: ArticleFetcherV0
    policy: ResearchSourcePolicyV0 = field(default_factory=ResearchSourcePolicyV0)

    def preflight(self, policy: ResearchSourcePolicyV0) -> None:
        if (
            type(self.policy) is not ResearchSourcePolicyV0
            or type(policy) is not ResearchSourcePolicyV0
        ):
            raise ArticlePreflightError(
                "VERIFIER_CONFIG_UNSAFE", "article verifier policy is invalid"
            )
        if (
            policy.max_redirects > self.policy.max_redirects
            or policy.max_response_bytes > self.policy.max_response_bytes
            or policy.max_article_text_chars > self.policy.max_article_text_chars
            or policy.operation_timeout_seconds > self.policy.operation_timeout_seconds
        ):
            raise ArticlePreflightError(
                "VERIFIER_CONFIG_UNSAFE",
                "invocation policy exceeds verifier hard safety limits",
            )
        if not callable(getattr(self.resolver, "resolve", None)) or not callable(
            getattr(self.fetcher, "fetch", None)
        ):
            raise ArticlePreflightError(
                "VERIFIER_UNAVAILABLE", "article verifier dependencies are unavailable"
            )

    async def verify(
        self,
        source: SourceCandidateV0,
        *,
        deadline: Deadline,
        policy: ResearchSourcePolicyV0,
    ) -> ArticleArtifactV0:
        self.preflight(policy)
        if type(source) is not SourceCandidateV0:
            raise ArticleSafetyError(
                "SOURCE_INVALID", "article source must be an exact V0 candidate"
            )
        try:
            current_url = canonicalize_public_article_url_v0(source.canonical_url)
        except ValueError as exc:
            raise ArticleSafetyError("SOURCE_URL_UNSAFE", str(exc)) from None
        original_origin = _origin(current_url)

        for redirect_count in range(policy.max_redirects + 1):
            parsed = urlsplit(current_url)
            hostname = parsed.hostname or ""
            port = 443 if parsed.scheme == "https" else 80
            timeout = deadline.child_timeout(policy.operation_timeout_seconds)
            try:
                raw_addresses = await self.resolver.resolve(
                    hostname,
                    port,
                    timeout=timeout,
                )
            except TimeoutError as exc:
                deadline.remaining()
                raise ArticleSafetyError(
                    "DNS_TIMEOUT", "article DNS resolution timed out"
                ) from exc
            addresses = _validate_public_addresses(raw_addresses)

            timeout = deadline.child_timeout(policy.operation_timeout_seconds)
            try:
                response = await self.fetcher.fetch(
                    current_url,
                    addresses,
                    timeout=timeout,
                    max_bytes=policy.max_response_bytes,
                )
            except TimeoutError as exc:
                deadline.remaining()
                raise ArticleSafetyError(
                    "FETCH_TIMEOUT", "article fetch timed out"
                ) from exc
            if type(response) is not ArticleFetchResponseV0:
                raise ArticleSafetyError(
                    "FETCH_RESPONSE_INVALID",
                    "article fetch returned an invalid response",
                )

            if 300 <= response.status_code < 400:
                if redirect_count >= policy.max_redirects:
                    raise ArticleSafetyError(
                        "REDIRECT_LIMIT", "article redirect limit was exceeded"
                    )
                current_url = _safe_redirect_url(
                    current_url,
                    response.location,
                    expected_origin=original_origin,
                )
                continue
            if response.status_code != 200:
                raise ArticleSafetyError(
                    "HTTP_STATUS_UNUSABLE", "article response was not successful"
                )
            normalized_text = _decode_article_response(response, policy=policy)
            return create_article_artifact_v0(
                source=source,
                final_url=current_url,
                normalized_text=normalized_text,
                policy=policy,
            )
        raise ArticleSafetyError(
            "REDIRECT_LIMIT", "article redirect limit was exceeded"
        )


def _validate_public_addresses(raw_addresses: object) -> tuple[str, ...]:
    if isinstance(raw_addresses, (str, bytes)) or not isinstance(
        raw_addresses, Sequence
    ):
        raise ArticleSafetyError("DNS_INVALID", "DNS answer must be an address array")
    addresses = tuple(raw_addresses)
    if not addresses or not all(isinstance(address, str) for address in addresses):
        raise ArticleSafetyError("DNS_INVALID", "DNS answer was empty or malformed")
    if any("%" in address for address in addresses):
        raise ArticleSafetyError("DNS_INVALID", "scoped DNS addresses are unsupported")
    try:
        parsed_addresses = tuple(ipaddress.ip_address(address) for address in addresses)
    except ValueError as exc:
        raise ArticleSafetyError(
            "DNS_INVALID", "DNS answer was not an IP address"
        ) from exc
    if any(ai_brief_url_safety.is_blocked_ip(address) for address in parsed_addresses):
        raise ArticleSafetyError(
            "DNS_NOT_PUBLIC", "DNS answer included a non-public address"
        )
    return tuple(str(address) for address in parsed_addresses)


def _safe_redirect_url(
    current_url: str,
    location: str | None,
    *,
    expected_origin: tuple[str, str, int],
) -> str:
    if not location:
        raise ArticleSafetyError("REDIRECT_INVALID", "redirect location was missing")
    try:
        target = canonicalize_public_article_url_v0(urljoin(current_url, location))
    except ValueError as exc:
        raise ArticleSafetyError("REDIRECT_UNSAFE", str(exc)) from None
    if _origin(target) != expected_origin:
        raise ArticleSafetyError(
            "REDIRECT_UNSAFE", "article redirect changed the requested public origin"
        )
    return target


def _origin(url: str) -> tuple[str, str, int]:
    parsed = urlsplit(url)
    return (
        parsed.scheme,
        parsed.hostname or "",
        443 if parsed.scheme == "https" else 80,
    )


def _decode_article_response(
    response: ArticleFetchResponseV0,
    *,
    policy: ResearchSourcePolicyV0,
) -> str:
    if len(response.body) > policy.max_response_bytes:
        raise ArticleSafetyError(
            "RESPONSE_TOO_LARGE", "article response exceeded the byte limit"
        )
    encoding = (response.content_encoding or "identity").strip().lower()
    if encoding not in {"", "identity"}:
        raise ArticleSafetyError(
            "CONTENT_ENCODING_UNSAFE", "compressed article responses are unsupported"
        )
    content_type_parts = [part.strip() for part in response.content_type.split(";")]
    media_type = content_type_parts[0].lower()
    if media_type not in {"text/html", "application/xhtml+xml", "text/plain"}:
        raise ArticleSafetyError(
            "CONTENT_TYPE_UNSAFE", "article response content type is unsupported"
        )
    charsets = [
        part.split("=", 1)[1].strip().strip('"').lower()
        for part in content_type_parts[1:]
        if part.lower().startswith("charset=")
    ]
    if len(charsets) > 1 or any(charset != "utf-8" for charset in charsets):
        raise ArticleSafetyError(
            "CONTENT_TYPE_UNSAFE", "article response charset must be UTF-8"
        )
    try:
        decoded = response.body.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise ArticleSafetyError(
            "ARTICLE_ENCODING_INVALID", "article response was not valid UTF-8"
        ) from exc
    if media_type in {"text/html", "application/xhtml+xml"}:
        parser = _ArticleTextParser()
        parser.feed(decoded)
        parser.close()
        decoded = " ".join(parser.parts)
    normalized = re.sub(r"\s+", " ", decoded).strip()
    if not normalized:
        raise ArticleSafetyError("ARTICLE_EMPTY", "article contained no usable text")
    if len(normalized) > policy.max_article_text_chars:
        raise ArticleSafetyError(
            "ARTICLE_TEXT_TOO_LARGE", "article text exceeded the character limit"
        )
    return normalized


class _ArticleTextParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []
        self._ignored_depth = 0

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        del attrs
        if tag.lower() in {"script", "style", "noscript"}:
            self._ignored_depth += 1

    def handle_endtag(self, tag: str) -> None:
        if tag.lower() in {"script", "style", "noscript"} and self._ignored_depth:
            self._ignored_depth -= 1

    def handle_data(self, data: str) -> None:
        if not self._ignored_depth:
            self.parts.append(data)


__all__ = [
    "ArticleArtifactV0",
    "ArticleArtifactValidationError",
    "ArticleFetchResponseV0",
    "ArticleFetcherV0",
    "ArticlePreflightError",
    "ArticleSafetyError",
    "PublicDnsResolverV0",
    "SafeArticleVerifierV0",
    "create_article_artifact_v0",
    "validate_and_copy_article_artifact_v0",
]
