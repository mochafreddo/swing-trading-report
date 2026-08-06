"""Canonical public article URL checks independent of network access."""

from __future__ import annotations

from urllib.parse import urlsplit, urlunsplit

from sab import ai_brief_url_safety

_LOCAL_HOST_SUFFIXES = (".local", ".internal", ".lan", ".home")


def canonicalize_public_article_url_v0(value: object) -> str:
    """Return a fragment-free canonical URL or reject a non-public target."""

    text = ai_brief_url_safety.validate_url(value, field_name="article URL")
    parsed = urlsplit(text)
    if parsed.fragment:
        raise ValueError("article URL must not include a fragment")
    hostname = parsed.hostname or ""
    aliases = ai_brief_url_safety.fetch_hostname_aliases(
        hostname, field_name="article URL"
    )
    if not aliases:
        raise ValueError("article URL hostname is invalid")
    if any(_is_local_or_unqualified(alias) for alias in aliases):
        raise ValueError("article URL must target a qualified public hostname")
    port = ai_brief_url_safety.validated_url_port(parsed, field_name="article URL")
    expected_port = 443 if parsed.scheme.lower() == "https" else 80
    if port != expected_port:
        raise ValueError("article URL must use the standard scheme port")
    request_hostname = aliases[-1]
    netloc = f"[{request_hostname}]" if ":" in request_hostname else request_hostname
    return urlunsplit(
        (
            parsed.scheme.lower(),
            netloc,
            parsed.path or "/",
            parsed.query,
            "",
        )
    )


def _is_local_or_unqualified(hostname: str) -> bool:
    return (
        ai_brief_url_safety.is_blocked_hostname(hostname)
        or "." not in hostname
        or hostname.endswith(_LOCAL_HOST_SUFFIXES)
    )


__all__ = ["canonicalize_public_article_url_v0"]
