from __future__ import annotations

import socket
import threading
import time
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from typing import Any
from urllib.parse import urlparse

from . import ai_brief_url_safety as url_safety

SOURCE_ROW_DNS_TIMEOUT_SECONDS = 1.0
SOURCE_DNS_RESOLVER_WORKERS = 4
SOURCE_DNS_PIN_LOCK = threading.RLock()
_SOURCE_DNS_RESOLVER_SLOTS = threading.BoundedSemaphore(SOURCE_DNS_RESOLVER_WORKERS)


class AiBriefSourceUrlTimeoutError(TimeoutError):
    pass


@dataclass(frozen=True)
class ValidatedSourceApiUrl:
    url: str
    hostnames: tuple[str, ...]
    addrinfos: tuple[Any, ...]


def validate_ai_brief_source_url(value: object, *, field_name: str = "url") -> str:
    return url_safety.validate_url(value, field_name=field_name)


def validate_ai_brief_source_api_url(value: object) -> str:
    return validate_source_api_request_url(value, deadline=None).url


def validate_source_row_url(
    value: object,
    *,
    field_name: str = "url",
    deadline: float | None = None,
    resolve_hostname: bool = False,
    dns_lock: object | None = None,
    resolver_slots: object | None = None,
) -> str:
    text = validate_ai_brief_source_url(value, field_name=field_name)
    parsed = urlparse(text)
    hostname = parsed.hostname or ""
    port = url_safety.validated_url_port(parsed, field_name=field_name)
    hostnames = source_api_hostname_aliases(hostname)
    if is_blocked_source_row_hostname(hostname):
        raise ValueError(f"{field_name} must not target local or private hosts")
    if resolve_hostname:
        hostnames = source_api_fetch_hostname_aliases(
            hostname,
            field_name=field_name,
        )
        resolve_public_source_addrinfos(
            hostnames,
            port,
            field_name=field_name,
            deadline=deadline,
            dns_lock=dns_lock,
            resolver_slots=resolver_slots,
        )
    return text


def validate_source_api_request_url(
    value: object,
    *,
    deadline: float | None,
    dns_lock: object | None = None,
    resolver_slots: object | None = None,
) -> ValidatedSourceApiUrl:
    text = validate_ai_brief_source_url(value, field_name="source API URL")
    parsed = urlparse(text)
    if parsed.scheme.lower() != "https":
        raise ValueError("source API URL must use https")
    hostname = parsed.hostname or ""
    port = url_safety.validated_url_port(parsed, field_name="source API URL")
    hostnames = source_api_fetch_hostname_aliases(
        hostname,
        field_name="source API URL",
    )
    addrinfos = resolve_source_api_addrinfos(
        hostnames,
        port,
        deadline=deadline,
        dns_lock=dns_lock,
        resolver_slots=resolver_slots,
    )
    return ValidatedSourceApiUrl(
        url=text,
        hostnames=hostnames,
        addrinfos=addrinfos,
    )


def is_blocked_source_row_hostname(hostname: str) -> bool:
    return any(
        url_safety.is_blocked_hostname(alias)
        for alias in source_api_hostname_aliases(hostname)
    )


def source_api_hostname_aliases(hostname: str) -> tuple[str, ...]:
    return url_safety.hostname_aliases(hostname)


def source_api_fetch_hostname_aliases(
    hostname: str,
    *,
    field_name: str,
) -> tuple[str, ...]:
    return url_safety.fetch_hostname_aliases(hostname, field_name=field_name)


def resolve_source_api_addrinfos(
    hostnames: tuple[str, ...],
    port: int,
    *,
    deadline: float | None,
    dns_lock: object | None = None,
    resolver_slots: object | None = None,
) -> tuple[Any, ...]:
    return resolve_public_source_addrinfos(
        hostnames,
        port,
        field_name="source API URL",
        deadline=deadline,
        dns_lock=dns_lock,
        resolver_slots=resolver_slots,
    )


def resolve_public_source_addrinfos(
    hostnames: tuple[str, ...],
    port: int,
    *,
    field_name: str,
    deadline: float | None,
    dns_lock: object | None = None,
    resolver_slots: object | None = None,
) -> tuple[Any, ...]:
    if any(url_safety.is_local_hostname(hostname) for hostname in hostnames):
        raise ValueError(f"{field_name} must not target local or private hosts")
    if any(url_safety.is_blocked_ip_text(hostname) for hostname in hostnames):
        raise ValueError(f"{field_name} must not target local or private hosts")
    resolution_hostname = hostnames[-1] if hostnames else ""
    try:
        with source_dns_pin_lock(deadline, lock=dns_lock):
            addrinfos = getaddrinfo_with_timeout(
                resolution_hostname,
                port,
                timeout=source_dns_timeout(deadline),
                resolver_slots=resolver_slots,
            )
    except AiBriefSourceUrlTimeoutError:
        raise
    except TimeoutError as exc:
        raise AiBriefSourceUrlTimeoutError(
            f"{field_name} DNS resolution timed out"
        ) from exc
    except OSError as exc:
        raise ValueError(f"{field_name} hostname could not be resolved") from exc
    if not addrinfos:
        raise ValueError(f"{field_name} hostname could not be resolved")
    if any(url_safety.is_blocked_addrinfo(addrinfo) for addrinfo in addrinfos):
        raise ValueError(f"{field_name} must not target local or private hosts")
    return tuple(addrinfos)


def getaddrinfo_with_timeout(
    hostname: str,
    port: int,
    *,
    timeout: float,
    resolver_slots: object | None = None,
) -> list[Any]:
    return url_safety.getaddrinfo_with_timeout(
        hostname,
        port,
        timeout=timeout,
        slots=resolver_slots
        if resolver_slots is not None
        else _SOURCE_DNS_RESOLVER_SLOTS,
        resolver=socket.getaddrinfo,
        thread_factory=threading.Thread,
        monotonic=time.monotonic,
        thread_name="ai-brief-source-dns",
    )


def source_dns_timeout(deadline: float | None) -> float:
    timeout = SOURCE_ROW_DNS_TIMEOUT_SECONDS
    if deadline is None:
        return timeout
    remaining = deadline - time.monotonic()
    if remaining <= 0:
        raise TimeoutError("DNS resolution timed out")
    return min(timeout, remaining)


@contextmanager
def pin_source_api_dns(
    hostnames: tuple[str, ...],
    addrinfos: tuple[Any, ...],
    *,
    deadline: float | None = None,
    lock: object | None = None,
    remaining_timeout: Callable[[float], float] | None = None,
    timeout_error: Callable[[], BaseException] | None = None,
    socket_module: Any = socket,
) -> Iterator[None]:
    with url_safety.pin_dns(
        hostnames,
        addrinfos,
        lock=lock if lock is not None else SOURCE_DNS_PIN_LOCK,
        deadline=deadline,
        remaining_timeout=remaining_timeout or _remaining_url_timeout,
        timeout_error=timeout_error
        or (lambda: AiBriefSourceUrlTimeoutError("source API DNS pin lock timed out")),
        socket_module=socket_module,
    ):
        yield


@contextmanager
def source_dns_pin_lock(
    deadline: float | None,
    *,
    lock: object | None = None,
    remaining_timeout: Callable[[float], float] | None = None,
    timeout_error: Callable[[], BaseException] | None = None,
) -> Iterator[None]:
    with url_safety.dns_pin_lock(
        lock if lock is not None else SOURCE_DNS_PIN_LOCK,
        deadline=deadline,
        remaining_timeout=remaining_timeout or _remaining_url_timeout,
        timeout_error=timeout_error
        or (lambda: AiBriefSourceUrlTimeoutError("source API DNS pin lock timed out")),
    ):
        yield


def _remaining_url_timeout(deadline: float) -> float:
    remaining = deadline - time.monotonic()
    if remaining <= 0:
        raise AiBriefSourceUrlTimeoutError("source API request timed out")
    return remaining


__all__ = [
    "SOURCE_DNS_PIN_LOCK",
    "SOURCE_DNS_RESOLVER_WORKERS",
    "SOURCE_ROW_DNS_TIMEOUT_SECONDS",
    "AiBriefSourceUrlTimeoutError",
    "ValidatedSourceApiUrl",
    "getaddrinfo_with_timeout",
    "is_blocked_source_row_hostname",
    "pin_source_api_dns",
    "resolve_public_source_addrinfos",
    "resolve_source_api_addrinfos",
    "source_api_fetch_hostname_aliases",
    "source_api_hostname_aliases",
    "source_dns_pin_lock",
    "source_dns_timeout",
    "validate_ai_brief_source_api_url",
    "validate_ai_brief_source_url",
    "validate_source_api_request_url",
    "validate_source_row_url",
]
