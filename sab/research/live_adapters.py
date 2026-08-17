"""Concrete live-source adapters built on the existing hardened news loaders."""

from __future__ import annotations

import asyncio
import http.client
import os
import socket
import ssl
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any
from urllib.parse import urlsplit

from sab.ai_brief_sources import (
    SOURCE_PROVIDER_BENZINGA_NEWS,
    SOURCE_PROVIDER_FINNHUB,
    SOURCE_PROVIDER_POLYGON_NEWS,
    AiBriefSourceProviderError,
    AiBriefSourceProviderResult,
    AiBriefSourceProviderTimeoutError,
    load_ai_brief_sources,
)
from sab.utils.bounded_process import (
    AsyncBoundedProcessRunnerV0,
    run_sync_in_bounded_process_async_v0,
)

from .contracts import SearchRequestV0
from .deadline import Deadline, DeadlineExpiredError
from .orchestrator import (
    SearchProviderOperationalError,
    SearchProviderTimeoutError,
)
from .source_safety import ArticleFetchResponseV0
from .urls import canonicalize_public_article_url_v0

_PROVIDERS = (
    SOURCE_PROVIDER_FINNHUB,
    SOURCE_PROVIDER_POLYGON_NEWS,
    SOURCE_PROVIDER_BENZINGA_NEWS,
)
_PROVIDER_CREDENTIAL_ENV = {
    SOURCE_PROVIDER_FINNHUB: "FINNHUB_API_KEY",
    SOURCE_PROVIDER_POLYGON_NEWS: "POLYGON_API_KEY",
    SOURCE_PROVIDER_BENZINGA_NEWS: "BENZINGA_API_TOKEN",
}
type SourceLoaderV0 = Callable[..., AiBriefSourceProviderResult]
type ResolveSyncV0 = Callable[[str, int], tuple[str, ...]]
type FetchSyncV0 = Callable[[str, tuple[str, ...], float, int], ArticleFetchResponseV0]


class ProviderObservationCounterV0:
    """Invocation-local public counters for the fixed provider chain."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._counts = {
            provider: {"attempts": 0, "failures": 0, "timeouts": 0}
            for provider in _PROVIDERS
        }

    def record(self, provider: str, outcome: str) -> None:
        if provider not in self._counts or outcome not in {
            "SUCCEEDED",
            "FAILED",
            "TIMED_OUT",
        }:
            raise ValueError("provider observation is invalid")
        with self._lock:
            row = self._counts[provider]
            row["attempts"] += 1
            if outcome != "SUCCEEDED":
                row["failures"] += 1
            if outcome == "TIMED_OUT":
                row["timeouts"] += 1

    def snapshot(self) -> dict[str, int]:
        with self._lock:
            return {
                f"provider_{provider.replace('-', '_')}_{metric}": value
                for provider in _PROVIDERS
                for metric, value in self._counts[provider].items()
            }


@dataclass(frozen=True, slots=True)
class AsyncPublicDnsResolverV0:
    """Resolve a hostname off-loop while leaving public-IP policy to the verifier."""

    resolve_sync: ResolveSyncV0 = field(
        default_factory=lambda: _resolve_sync,
        repr=False,
        compare=False,
    )
    bounded_runner: AsyncBoundedProcessRunnerV0 = field(
        default=run_sync_in_bounded_process_async_v0,
        repr=False,
        compare=False,
    )

    async def resolve(
        self,
        hostname: str,
        port: int,
        *,
        timeout: float,
    ) -> tuple[str, ...]:
        if (
            type(hostname) is not str
            or not hostname
            or type(port) is not int
            or not 1 <= port <= 65535
            or isinstance(timeout, bool)
            or not isinstance(timeout, (int, float))
            or timeout <= 0
        ):
            raise ValueError("DNS request is invalid")
        try:
            result = await self.bounded_runner(
                self.resolve_sync,
                (hostname, port),
                timeout=float(timeout),
            )
        except TimeoutError:
            raise
        except Exception as exc:
            raise TimeoutError("public DNS resolution failed") from exc
        if type(result) is not tuple:
            raise ValueError("DNS result is invalid")
        return result


@dataclass(frozen=True, slots=True)
class PinnedArticleFetcherV0:
    """Fetch one article by a previously verified address with hostname TLS checks."""

    fetch_sync: FetchSyncV0 = field(
        default_factory=lambda: _fetch_pinned_sync,
        repr=False,
        compare=False,
    )
    bounded_runner: AsyncBoundedProcessRunnerV0 = field(
        default=run_sync_in_bounded_process_async_v0,
        repr=False,
        compare=False,
    )

    async def fetch(
        self,
        url: str,
        addresses: tuple[str, ...],
        *,
        timeout: float,
        max_bytes: int,
    ) -> ArticleFetchResponseV0:
        if (
            type(url) is not str
            or type(addresses) is not tuple
            or not addresses
            or not all(type(address) is str for address in addresses)
            or isinstance(timeout, bool)
            or not isinstance(timeout, (int, float))
            or timeout <= 0
            or type(max_bytes) is not int
            or max_bytes <= 0
        ):
            raise ValueError("article fetch request is invalid")
        try:
            response = await self.bounded_runner(
                self.fetch_sync,
                (url, addresses, float(timeout), max_bytes),
                timeout=float(timeout),
            )
        except TimeoutError:
            raise
        except Exception as exc:
            raise TimeoutError("article fetch failed") from exc
        if type(response) is not ArticleFetchResponseV0:
            raise ValueError("article fetch response is invalid")
        return response


@dataclass(frozen=True, slots=True)
class AiBriefNewsSearchProviderV0:
    """Combine three existing live news providers behind one public batch seam."""

    source_loader: SourceLoaderV0 = field(
        default=load_ai_brief_sources,
        repr=False,
        compare=False,
    )
    now: Callable[[], datetime] = field(
        default=lambda: datetime.now(UTC),
        repr=False,
        compare=False,
    )
    observations: ProviderObservationCounterV0 = field(
        default_factory=ProviderObservationCounterV0,
        repr=False,
        compare=False,
    )
    bounded_runner: AsyncBoundedProcessRunnerV0 = field(
        default=run_sync_in_bounded_process_async_v0,
        repr=False,
        compare=False,
    )

    async def search(
        self,
        request: SearchRequestV0,
        *,
        deadline: Deadline,
    ) -> object:
        if type(request) is not SearchRequestV0 or type(deadline) is not Deadline:
            raise SearchProviderOperationalError("live news request is invalid")
        instrument = request.instrument
        if instrument.market != "US":
            return _search_payload(request, ())
        current_time = self.now()
        if current_time.tzinfo is None or current_time.utcoffset() is None:
            raise SearchProviderOperationalError("live news clock is invalid")
        current_time = current_time.astimezone(UTC)
        sources: list[dict[str, object]] = []
        failed = 0
        timed_out = 0
        for index, provider in enumerate(_PROVIDERS):
            providers_left = len(_PROVIDERS) - index
            attempted = False
            try:
                timeout = deadline.child_timeout() / providers_left
                attempted = True
                result = await self.bounded_runner(
                    _load_provider_sources_sync,
                    (
                        self.source_loader,
                        provider,
                        os.getenv(_PROVIDER_CREDENTIAL_ENV[provider]),
                    ),
                    timeout=timeout,
                    kwargs={
                        "source_provider": provider,
                        "source_report_path": None,
                        "source_api_url": None,
                        "source_timeout_seconds": timeout,
                        "eligible_tickers": {instrument.canonical_ticker},
                        "now": current_time,
                    },
                )
                deadline.remaining()
                candidate = _first_safe_source(
                    result,
                    ticker=instrument.canonical_ticker,
                    now=current_time,
                    freshness_hours=request.freshness_hours,
                )
            except asyncio.CancelledError:
                if attempted:
                    self.observations.record(provider, "TIMED_OUT")
                raise
            except AiBriefSourceProviderTimeoutError, TimeoutError:
                self.observations.record(provider, "TIMED_OUT")
                timed_out += 1
                continue
            except AiBriefSourceProviderError:
                self.observations.record(provider, "FAILED")
                failed += 1
                continue
            except DeadlineExpiredError as exc:
                if attempted:
                    self.observations.record(provider, "TIMED_OUT")
                raise SearchProviderTimeoutError("live news search timed out") from exc
            except Exception as exc:
                self.observations.record(provider, "FAILED")
                raise SearchProviderOperationalError(
                    "live news provider failed"
                ) from exc
            self.observations.record(provider, "SUCCEEDED")
            if candidate is not None and not any(
                row["url"] == candidate["url"] for row in sources
            ):
                sources.append(candidate)
        if not sources and timed_out == len(_PROVIDERS):
            raise SearchProviderTimeoutError("live news search timed out")
        if not sources and failed == len(_PROVIDERS):
            raise SearchProviderOperationalError("live news providers failed")
        return _search_payload(request, tuple(sources))


def _first_safe_source(
    result: object,
    *,
    ticker: str,
    now: datetime,
    freshness_hours: int,
) -> dict[str, object] | None:
    if type(result) is not AiBriefSourceProviderResult:
        raise SearchProviderOperationalError("live news result is malformed")
    rows = result.sources_by_ticker.get(ticker, [])
    if type(rows) is not list:
        raise SearchProviderOperationalError("live news result is malformed")
    earliest = now - timedelta(hours=freshness_hours)
    for row in rows:
        if type(row) is not dict:
            continue
        title = row.get("title")
        raw_url = row.get("url")
        published_at = _utc_timestamp(row.get("published_at"))
        if (
            type(title) is not str
            or not title.strip()
            or type(raw_url) is not str
            or published_at is None
            or published_at < earliest
            or published_at > now
        ):
            continue
        try:
            url = canonicalize_public_article_url_v0(raw_url)
        except TypeError, ValueError:
            continue
        publisher = urlsplit(url).hostname
        if publisher is None:
            continue
        return {
            "canonical_ticker": ticker,
            "title": title.strip(),
            "url": url,
            "publisher": publisher,
            "published_at": published_at.isoformat().replace("+00:00", "Z"),
            "purpose": "PRIMARY",
        }
    return None


def _utc_timestamp(value: object) -> datetime | None:
    if type(value) is not str:
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        return None
    return parsed.astimezone(UTC)


def _search_payload(
    request: SearchRequestV0,
    sources: tuple[dict[str, object], ...],
) -> dict[str, Any]:
    return {
        "schema": "sab.research.search.v0",
        "instrument": request.instrument.to_public_dict(),
        "sources": list(sources),
    }


def _resolve_sync(hostname: str, port: int) -> tuple[str, ...]:
    addresses = {
        str(record[4][0])
        for record in socket.getaddrinfo(
            hostname,
            port,
            family=socket.AF_UNSPEC,
            type=socket.SOCK_STREAM,
        )
    }
    return tuple(sorted(addresses))


def _load_provider_sources_sync(
    source_loader: SourceLoaderV0,
    provider: str,
    credential: str | None,
    **kwargs: object,
) -> object:
    env_name = _PROVIDER_CREDENTIAL_ENV.get(provider)
    if env_name is None:
        raise ValueError("live news provider is invalid")
    previous = os.environ.get(env_name)
    try:
        if credential is None:
            os.environ.pop(env_name, None)
        else:
            os.environ[env_name] = credential
        return source_loader(**kwargs)
    finally:
        if previous is None:
            os.environ.pop(env_name, None)
        else:
            os.environ[env_name] = previous


class _PinnedHttpConnection(http.client.HTTPConnection):
    def __init__(
        self,
        hostname: str,
        port: int,
        *,
        address: str,
        timeout: float,
    ) -> None:
        super().__init__(hostname, port=port, timeout=timeout)
        self._address = address

    def connect(self) -> None:
        self.sock = socket.create_connection(
            (self._address, self.port),
            self.timeout,
        )


class _PinnedHttpsConnection(http.client.HTTPSConnection):
    def __init__(
        self,
        hostname: str,
        port: int,
        *,
        address: str,
        timeout: float,
    ) -> None:
        self._ssl_context = ssl.create_default_context()
        super().__init__(
            hostname,
            port=port,
            timeout=timeout,
            context=self._ssl_context,
        )
        self._address = address

    def connect(self) -> None:
        raw_socket = socket.create_connection(
            (self._address, self.port),
            self.timeout,
        )
        try:
            self.sock = self._ssl_context.wrap_socket(
                raw_socket,
                server_hostname=self.host,
            )
        except BaseException:
            raw_socket.close()
            raise


def _fetch_pinned_sync(
    url: str,
    addresses: tuple[str, ...],
    timeout: float,
    max_bytes: int,
) -> ArticleFetchResponseV0:
    canonical_url = canonicalize_public_article_url_v0(url)
    parsed = urlsplit(canonical_url)
    hostname = parsed.hostname
    if hostname is None:
        raise ValueError("article hostname is unavailable")
    port = 443 if parsed.scheme == "https" else 80
    path = parsed.path or "/"
    if parsed.query:
        path = f"{path}?{parsed.query}"
    expires_at = time.monotonic() + timeout
    last_error: Exception | None = None
    for address in addresses:
        remaining = expires_at - time.monotonic()
        if remaining <= 0:
            break
        connection: http.client.HTTPConnection
        if parsed.scheme == "https":
            connection = _PinnedHttpsConnection(
                hostname,
                port,
                address=address,
                timeout=remaining,
            )
        else:
            connection = _PinnedHttpConnection(
                hostname,
                port,
                address=address,
                timeout=remaining,
            )
        try:
            connection.request(
                "GET",
                path,
                headers={
                    "Accept": "text/html,application/xhtml+xml,text/plain",
                    "Accept-Encoding": "identity",
                    "Host": hostname,
                    "User-Agent": "sab-decision-board-shadow/0",
                },
            )
            response = connection.getresponse()
            result = ArticleFetchResponseV0(
                status_code=response.status,
                content_type=response.getheader("content-type", ""),
                content_encoding=response.getheader("content-encoding"),
                body=response.read(max_bytes + 1),
                location=response.getheader("location"),
            )
            if time.monotonic() >= expires_at:
                raise TimeoutError("article fetch timed out")
            return result
        except (OSError, http.client.HTTPException) as exc:
            last_error = exc
        finally:
            connection.close()
    raise TimeoutError("article fetch failed") from last_error


__all__ = [
    "AiBriefNewsSearchProviderV0",
    "AsyncPublicDnsResolverV0",
    "PinnedArticleFetcherV0",
    "ProviderObservationCounterV0",
]
