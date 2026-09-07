"""Explicit, default-off Supabase user transport. Never reads environment credentials."""

from __future__ import annotations

import json
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any
from urllib.parse import urlsplit
from uuid import UUID

import requests

from .outcome_history import _reject_duplicate_keys


class ReviewTransportError(ValueError):
    """Only fixed error codes cross the transport boundary."""


@dataclass(frozen=True)
class ReviewSession:
    owner_id: str
    version_ids: tuple[str, ...]
    access_token: str = field(repr=False)

    def __post_init__(self) -> None:
        try:
            if (
                str(UUID(self.owner_id)) != self.owner_id
                or not 1 <= len(self.version_ids) <= 100
                or len(set(self.version_ids)) != len(self.version_ids)
                or any(str(UUID(v)) != v for v in self.version_ids)
                or not self.access_token
                or len(self.access_token) > 16384
                or any(c.isspace() for c in self.access_token)
            ):
                raise ValueError
        except Exception:
            raise ReviewTransportError("REVIEW_SESSION_INVALID") from None


class AuthenticatedReviewTransport:
    """Verify the bearer with Auth on every read; SQL independently checks ownership.

    The injected request function is for isolated fake HTTP tests. The real session
    ignores netrc/proxies, rejects redirects and bounds response bytes and timeouts.
    No administrator cookie or service-role client is accepted by this interface.
    """

    def __init__(
        self,
        origin: str,
        publishable_key: str,
        session: ReviewSession,
        *,
        enabled: bool = False,
        request: Callable[..., Any] | None = None,
    ) -> None:
        parsed = urlsplit(origin)
        if (
            parsed.scheme != "https"
            or not parsed.hostname
            or parsed.username is not None
            or parsed.password is not None
            or parsed.path not in ("", "/")
            or parsed.query
            or parsed.fragment
            or not publishable_key.startswith("sb_publishable_")
            or any(c.isspace() for c in publishable_key)
        ):
            raise ReviewTransportError("REVIEW_TRANSPORT_CONFIG_INVALID")
        self._origin = origin.rstrip("/")
        self._key = publishable_key
        self._session = session
        self._enabled = enabled
        self._http = requests.Session()
        self._http.trust_env = False
        self._request = request or self._http.request

    def _json(self, method: str, path: str, body: Any = None) -> Any:
        try:
            with self._request(
                method,
                self._origin + path,
                headers={
                    "apikey": self._key,
                    "Authorization": "Bearer " + self._session.access_token,
                    "Cache-Control": "no-store",
                    "Accept": "application/json",
                },
                json=body,
                timeout=(3, 10),
                allow_redirects=False,
                stream=True,
            ) as response:
                if response.status_code in (401, 403):
                    raise ReviewTransportError("REVIEW_UNAUTHORIZED")
                if response.status_code != 200:
                    raise ReviewTransportError("REVIEW_HTTP_UNAVAILABLE")
                if (
                    response.headers.get("content-type", "").split(";")[0]
                    != "application/json"
                ):
                    raise ReviewTransportError("REVIEW_RESPONSE_INVALID")
                data = bytearray()
                for chunk in response.iter_content(65536):
                    data.extend(chunk)
                    if len(data) > 3 * 1024 * 1024:
                        raise ReviewTransportError("REVIEW_RESPONSE_INVALID")
                return json.loads(data, object_pairs_hook=_reject_duplicate_keys)
        except ReviewTransportError:
            raise
        except Exception:
            raise ReviewTransportError("REVIEW_HTTP_UNAVAILABLE") from None

    def __call__(self, name: str, params: dict[str, Any]) -> object:
        if self._enabled is not True:
            raise ReviewTransportError("PORTFOLIO_REVIEW_DISABLED")
        if name not in {
            "read_portfolio_review_r1",
            "read_portfolio_review_store_r2",
        } or params != {"p_version_ids": list(self._session.version_ids)}:
            raise ReviewTransportError("REVIEW_OWNER_VERSION_MAPPING_REQUIRED")
        user = self._json("GET", "/auth/v1/user")
        if (
            type(user) is not dict
            or user.get("id") != self._session.owner_id
            or user.get("role") != "authenticated"
            or user.get("is_anonymous") is not False
        ):
            raise ReviewTransportError("REVIEW_UNAUTHORIZED")
        return self._json("POST", "/rest/v1/rpc/" + name, params)
