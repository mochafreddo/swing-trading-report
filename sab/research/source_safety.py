"""Safe, injectable article retrieval with no claim interpretation."""

from __future__ import annotations

import hashlib
import ipaddress
import re
from collections.abc import Sequence
from dataclasses import dataclass, field
from html.parser import HTMLParser
from typing import Protocol
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


@dataclass(frozen=True, slots=True)
class ArticleArtifactV0:
    source: SourceCandidateV0
    final_url: str
    normalized_text: str
    content_hash: str


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

    def preflight(self) -> None:
        if type(self.policy) is not ResearchSourcePolicyV0:
            raise ArticlePreflightError(
                "VERIFIER_CONFIG_UNSAFE", "article verifier policy is invalid"
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
    ) -> ArticleArtifactV0:
        self.preflight()
        if type(source) is not SourceCandidateV0:
            raise ArticleSafetyError(
                "SOURCE_INVALID", "article source must be an exact V0 candidate"
            )
        try:
            current_url = canonicalize_public_article_url_v0(source.canonical_url)
        except ValueError as exc:
            raise ArticleSafetyError("SOURCE_URL_UNSAFE", str(exc)) from None
        original_origin = _origin(current_url)

        for redirect_count in range(self.policy.max_redirects + 1):
            parsed = urlsplit(current_url)
            hostname = parsed.hostname or ""
            port = 443 if parsed.scheme == "https" else 80
            timeout = deadline.child_timeout(self.policy.operation_timeout_seconds)
            try:
                raw_addresses = await self.resolver.resolve(
                    hostname,
                    port,
                    timeout=timeout,
                )
            except TimeoutError as exc:
                raise ArticleSafetyError(
                    "DNS_TIMEOUT", "article DNS resolution timed out"
                ) from exc
            addresses = _validate_public_addresses(raw_addresses)

            timeout = deadline.child_timeout(self.policy.operation_timeout_seconds)
            try:
                response = await self.fetcher.fetch(
                    current_url,
                    addresses,
                    timeout=timeout,
                    max_bytes=self.policy.max_response_bytes,
                )
            except TimeoutError as exc:
                raise ArticleSafetyError(
                    "FETCH_TIMEOUT", "article fetch timed out"
                ) from exc
            if type(response) is not ArticleFetchResponseV0:
                raise ArticleSafetyError(
                    "FETCH_RESPONSE_INVALID",
                    "article fetch returned an invalid response",
                )

            if 300 <= response.status_code < 400:
                if redirect_count >= self.policy.max_redirects:
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
            normalized_text = _decode_article_response(response, policy=self.policy)
            digest = hashlib.sha256(normalized_text.encode("utf-8")).hexdigest()
            return ArticleArtifactV0(
                source=source,
                final_url=current_url,
                normalized_text=normalized_text,
                content_hash=f"sha256:{digest}",
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
    return addresses


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
    "ArticleFetchResponseV0",
    "ArticleFetcherV0",
    "ArticlePreflightError",
    "ArticleSafetyError",
    "PublicDnsResolverV0",
    "SafeArticleVerifierV0",
]
