from __future__ import annotations

import ipaddress
import queue
import socket
import time
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from typing import Any, cast
from urllib.parse import urlparse

import idna

ALLOWED_URL_SCHEMES = frozenset({"http", "https"})
NAT64_WELL_KNOWN_PREFIX = ipaddress.IPv6Network("64:ff9b::/96")
IPV4_COMPATIBLE_IPV6_PREFIX = ipaddress.IPv6Network("::/96")


def validate_url(
    value: object,
    *,
    field_name: str = "url",
    allowed_schemes: frozenset[str] = ALLOWED_URL_SCHEMES,
) -> str:
    text = str(value or "").strip()
    if not text:
        raise ValueError(f"{field_name} is required")
    if any(char.isspace() or ord(char) < 32 or ord(char) == 127 for char in text):
        raise ValueError(f"{field_name} must not contain whitespace or control chars")
    if "\\" in text:
        raise ValueError(f"{field_name} must not contain backslashes")
    try:
        parsed = urlparse(text)
        hostname = parsed.hostname
        username = parsed.username
        password = parsed.password
    except ValueError as exc:
        raise ValueError(f"{field_name} is invalid") from exc
    if parsed.scheme.lower() not in allowed_schemes:
        raise ValueError(
            f"{field_name} must use {' or '.join(sorted(allowed_schemes))}"
        )
    if not parsed.netloc or not hostname:
        raise ValueError(f"{field_name} must include a hostname")
    if "@" in parsed.netloc or username is not None or password is not None:
        raise ValueError(f"{field_name} must not include userinfo")
    if "%" in parsed.netloc or "%" in hostname:
        raise ValueError(f"{field_name} hostname must not contain percent escapes")
    return text


def validated_url_port(parsed: Any, *, field_name: str) -> int:
    try:
        port_value = parsed.port
    except ValueError as exc:
        raise ValueError(f"{field_name} port is invalid") from exc
    if port_value is None:
        return 443 if parsed.scheme.lower() == "https" else 80
    port = int(port_value)
    if port <= 0:
        raise ValueError(f"{field_name} port is invalid")
    return port


def hostname_aliases(hostname: str) -> tuple[str, ...]:
    normalized = normalize_hostname(hostname)
    aliases = [normalized]
    for idna_hostname in (
        encode_idna_hostname(normalized, uts46=False),
        encode_idna_hostname(normalized, uts46=True),
    ):
        if idna_hostname is None:
            continue
        idna_hostname = normalize_hostname(idna_hostname)
        if idna_hostname and idna_hostname not in aliases:
            aliases.append(idna_hostname)
    return tuple(aliases)


def fetch_hostname_aliases(hostname: str, *, field_name: str) -> tuple[str, ...]:
    aliases = list(hostname_aliases(hostname))
    if any(is_blocked_hostname(alias) for alias in aliases):
        return tuple(aliases)
    request_hostname = encode_idna_hostname(normalize_hostname(hostname), uts46=False)
    if request_hostname is None:
        raise ValueError(f"{field_name} hostname is invalid")
    request_hostname = normalize_hostname(request_hostname)
    if request_hostname in aliases:
        aliases.remove(request_hostname)
    aliases.append(request_hostname)
    return tuple(aliases)


def encode_idna_hostname(hostname: str, *, uts46: bool) -> str | None:
    if hostname.isascii():
        return hostname.lower()
    try:
        return idna.encode(
            hostname.lower(),
            strict=True,
            std3_rules=True,
            uts46=uts46,
        ).decode("ascii")
    except idna.IDNAError:
        return None


def normalize_hostname(hostname: object) -> str:
    if isinstance(hostname, bytes):
        hostname = hostname.decode("ascii", errors="ignore")
    return str(hostname or "").strip().strip("[]").lower().rstrip(".")


def is_blocked_hostname(normalized_hostname: str) -> bool:
    return is_local_hostname(normalized_hostname) or is_blocked_ip_text(
        normalized_hostname
    )


def is_local_hostname(normalized_hostname: str) -> bool:
    return normalized_hostname in {"localhost", "ip6-localhost"} or (
        normalized_hostname.endswith(".localhost")
    )


def is_blocked_addrinfo(addrinfo: object) -> bool:
    try:
        sockaddr = cast(Any, addrinfo)[4]
        ip_text = str(sockaddr[0])
    except IndexError:
        return True
    except TypeError:
        return True
    except KeyError:
        return True
    return is_blocked_ip_text(ip_text)


def is_blocked_ip_text(value: str) -> bool:
    try:
        return is_blocked_ip(ipaddress.ip_address(value))
    except ValueError:
        pass
    try:
        return is_blocked_ip(ipaddress.IPv4Address(socket.inet_aton(value)))
    except OSError:
        return False


def is_blocked_ip(address: ipaddress.IPv4Address | ipaddress.IPv6Address) -> bool:
    if address.is_multicast or not address.is_global:
        return True
    if isinstance(address, ipaddress.IPv6Address):
        return any(
            is_blocked_ip(embedded_address)
            for embedded_address in embedded_ipv4_addresses(address)
        )
    return False


def embedded_ipv4_addresses(
    address: ipaddress.IPv6Address,
) -> tuple[ipaddress.IPv4Address, ...]:
    embedded_addresses: list[ipaddress.IPv4Address] = []
    if address.ipv4_mapped is not None:
        embedded_addresses.append(address.ipv4_mapped)
    if address.sixtofour is not None:
        embedded_addresses.append(address.sixtofour)
    if address.teredo is not None:
        embedded_addresses.extend(address.teredo)
    if address in NAT64_WELL_KNOWN_PREFIX:
        embedded_addresses.append(ipaddress.IPv4Address(int(address) & 0xFFFFFFFF))
    if address in IPV4_COMPATIBLE_IPV6_PREFIX and int(address) > 0xFFFF:
        embedded_addresses.append(ipaddress.IPv4Address(int(address) & 0xFFFFFFFF))
    return tuple(embedded_addresses)


def getaddrinfo_with_timeout(
    hostname: str,
    port: int,
    *,
    timeout: float,
    slots: Any,
    resolver: Callable[..., Any],
    thread_factory: Callable[..., Any],
    monotonic: Callable[[], float] = time.monotonic,
    thread_name: str = "ai-brief-dns",
) -> list[Any]:
    if timeout <= 0:
        raise TimeoutError("DNS resolution timed out")
    started_at = monotonic()
    if not slots.acquire(timeout=timeout):
        raise TimeoutError("DNS resolver capacity exhausted")
    result_queue: queue.Queue[tuple[float, bool, Any]] = queue.Queue(maxsize=1)
    remaining_timeout = timeout - (monotonic() - started_at)
    if remaining_timeout <= 0:
        slots.release()
        raise TimeoutError("DNS resolution timed out")

    def resolve() -> None:
        try:
            try:
                result: tuple[bool, Any] = (
                    True,
                    resolver(
                        hostname,
                        port,
                        type=socket.SOCK_STREAM,
                    ),
                )
            except BaseException as exc:
                result = (False, exc)
            completed_at = monotonic()
        finally:
            slots.release()
        success, value = result
        result_queue.put((completed_at, success, value))

    try:
        thread = thread_factory(
            target=resolve,
            name=thread_name,
            daemon=True,
        )
        thread.start()
    except BaseException:
        slots.release()
        raise
    remaining_timeout = timeout - (monotonic() - started_at)
    if remaining_timeout <= 0:
        raise TimeoutError("DNS resolution timed out")
    try:
        completed_at, success, value = result_queue.get(timeout=remaining_timeout)
    except queue.Empty as exc:
        raise TimeoutError("DNS resolution timed out") from exc
    if completed_at - started_at > timeout:
        raise TimeoutError("DNS resolution timed out")
    if not success:
        raise value
    return cast(list[Any], value)


@contextmanager
def pin_dns(
    hostnames: tuple[str, ...],
    addrinfos: tuple[Any, ...],
    *,
    lock: Any,
    deadline: float | None,
    remaining_timeout: Callable[[float], float],
    timeout_error: Callable[[], BaseException],
    socket_module: Any = socket,
) -> Iterator[None]:
    hostname_set = set(hostnames)
    expected_port = addrinfo_port(addrinfos)

    with dns_pin_lock(
        lock,
        deadline=deadline,
        remaining_timeout=remaining_timeout,
        timeout_error=timeout_error,
    ):
        original_getaddrinfo = socket_module.getaddrinfo

        def pinned_getaddrinfo(
            host: bytes | str | None,
            port: bytes | str | int | None,
            family: int = 0,
            type: int = 0,
            proto: int = 0,
            flags: int = 0,
        ) -> list[Any]:
            host_matches = normalize_hostname(host) in hostname_set
            port_matches = dns_port_matches(port, expected_port)
            if host_matches and port_matches:
                matching_addrinfos = filter_addrinfos(
                    addrinfos,
                    family=family,
                    socket_type=type,
                    proto=proto,
                    flags=flags,
                )
                if matching_addrinfos:
                    return matching_addrinfos
                raise socket_module.gaierror(
                    "pinned DNS result does not match requested parameters"
                )
            return cast(
                list[Any],
                original_getaddrinfo(host, port, family, type, proto, flags),
            )

        socket_module.getaddrinfo = pinned_getaddrinfo
        try:
            yield
        finally:
            socket_module.getaddrinfo = original_getaddrinfo


@contextmanager
def dns_pin_lock(
    lock: Any,
    *,
    deadline: float | None,
    remaining_timeout: Callable[[float], float],
    timeout_error: Callable[[], BaseException],
) -> Iterator[None]:
    if deadline is None or not hasattr(lock, "acquire") or not hasattr(lock, "release"):
        with lock:
            yield
        return
    timeout = remaining_timeout(deadline)
    if not lock.acquire(timeout=timeout):
        raise timeout_error()
    try:
        yield
    finally:
        lock.release()


def addrinfo_port(addrinfos: tuple[Any, ...]) -> int | None:
    try:
        return int(addrinfos[0][4][1])
    except IndexError:
        return None
    except TypeError:
        return None
    except KeyError:
        return None
    except ValueError:
        return None


def dns_port_matches(port: bytes | str | int | None, expected_port: int | None) -> bool:
    if expected_port is None:
        return False
    if isinstance(port, bytes):
        port = port.decode("ascii", errors="ignore")
    try:
        return int(str(port)) == expected_port
    except ValueError:
        return False


def filter_addrinfos(
    addrinfos: tuple[Any, ...],
    *,
    family: int,
    socket_type: int,
    proto: int,
    flags: int,
) -> list[Any]:
    if flags != 0:
        return []
    return [
        addrinfo
        for addrinfo in addrinfos
        if addrinfo_matches_request(
            addrinfo,
            family=family,
            socket_type=socket_type,
            proto=proto,
        )
    ]


def addrinfo_matches_request(
    addrinfo: object,
    *,
    family: int,
    socket_type: int,
    proto: int,
) -> bool:
    addrinfo_any = cast(Any, addrinfo)
    try:
        addrinfo_family = int(addrinfo_any[0])
        addrinfo_type = int(addrinfo_any[1])
        addrinfo_proto = int(addrinfo_any[2])
    except IndexError:
        return False
    except TypeError:
        return False
    except KeyError:
        return False
    except ValueError:
        return False
    return (
        (family == 0 or addrinfo_family == 0 or int(family) == addrinfo_family)
        and (
            socket_type == 0 or addrinfo_type == 0 or int(socket_type) == addrinfo_type
        )
        and (proto == 0 or addrinfo_proto == 0 or int(proto) == addrinfo_proto)
    )


__all__ = [
    "ALLOWED_URL_SCHEMES",
    "IPV4_COMPATIBLE_IPV6_PREFIX",
    "NAT64_WELL_KNOWN_PREFIX",
    "addrinfo_matches_request",
    "addrinfo_port",
    "dns_pin_lock",
    "dns_port_matches",
    "embedded_ipv4_addresses",
    "encode_idna_hostname",
    "fetch_hostname_aliases",
    "filter_addrinfos",
    "getaddrinfo_with_timeout",
    "hostname_aliases",
    "is_blocked_addrinfo",
    "is_blocked_hostname",
    "is_blocked_ip",
    "is_blocked_ip_text",
    "is_local_hostname",
    "normalize_hostname",
    "pin_dns",
    "validate_url",
    "validated_url_port",
]
