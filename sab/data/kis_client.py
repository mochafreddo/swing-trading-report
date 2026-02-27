from __future__ import annotations

import datetime as dt
import time
from typing import Any

import requests  # type: ignore[import-untyped]

from .kis import (
    KISApiError,
    KISAuthError,
    KISClientError,
    KISCredentials,
    _KISAuthMixin,
    _KISCalendarMixin,
    _KISClientState,
    _KISQuoteMixin,
    _KISRankingMixin,
)


class _KISTransportMixin(_KISClientState):
    """Common HTTP transport + retry + client-side throttle."""

    def _request(
        self,
        method: str,
        url: str,
        *,
        headers: dict[str, Any] | None = None,
        params: dict[str, Any] | None = None,
        json: dict[str, Any] | None = None,
        timeout: float = 10.0,
    ) -> requests.Response:
        backoff = 1.0
        last_exc: requests.RequestException | None = None
        resp: requests.Response | None = None

        for attempt in range(self._max_attempts):
            # simple client-side throttle
            if self._min_interval and self._last_request_at is not None:
                delta = (
                    dt.datetime.now(dt.UTC) - self._last_request_at
                ).total_seconds()
                if delta < self._min_interval:
                    time.sleep(self._min_interval - delta)
            try:
                resp = self.session.request(
                    method,
                    url,
                    headers=headers,
                    params=params,
                    json=json,
                    timeout=timeout,
                )
                self._last_request_at = dt.datetime.now(dt.UTC)
            except requests.RequestException as exc:
                last_exc = exc
            else:
                if (
                    resp.status_code in {429, 418, 503}
                    and attempt < self._max_attempts - 1
                ):
                    time.sleep(backoff)
                    backoff = min(backoff * 2, 8.0)
                    continue
                return resp

            if attempt < self._max_attempts - 1:
                time.sleep(backoff)
                backoff = min(backoff * 2, 8.0)

        if last_exc is not None:
            raise last_exc
        assert resp is not None  # final response present if not exception
        return resp


class KISClient(
    _KISAuthMixin,
    _KISQuoteMixin,
    _KISCalendarMixin,
    _KISRankingMixin,
    _KISTransportMixin,
):
    """Facade that composes KIS responsibilities via internal mixins."""

    def __init__(
        self,
        creds: KISCredentials,
        *,
        session: requests.Session | None = None,
        cache_dir: str | None = None,
        max_attempts: int = 3,
        min_interval: float | None = None,
    ):
        self.creds = creds
        self.session = session or requests.Session()
        self._access_token: str | None = None
        self._token_expiry: dt.datetime | None = None
        self._cache_dir = cache_dir
        self._token_cache_key = f"kis_token_{creds.env}"
        self.cache_status: str | None = None
        self._max_attempts = max(1, max_attempts)
        # throttle between requests (seconds)
        self._min_interval = (
            float(min_interval)
            if min_interval is not None
            else (0.5 if creds.env == "demo" else 0.1)
        )
        self._last_request_at: dt.datetime | None = None
        self._overseas_symbol_preference: dict[str, str] = {}

        self._try_load_cached_token()


__all__ = [
    "KISApiError",
    "KISAuthError",
    "KISClient",
    "KISClientError",
    "KISCredentials",
]
