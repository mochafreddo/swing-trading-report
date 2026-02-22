from __future__ import annotations

import datetime as dt
from typing import Any

import requests  # type: ignore[import-untyped]

from ..cache import load_json, save_json
from .common import (
    _KST,
    KISAuthError,
    _KISClientState,
    logger,
)


class _KISAuthMixin(_KISClientState):
    """Authentication/token lifecycle responsibilities."""

    def _try_load_cached_token(self) -> None:
        if not self._cache_dir:
            self.cache_status = "disabled"
            return

        cached = load_json(self._cache_dir, self._token_cache_key)
        if not cached:
            self.cache_status = "miss"
            return

        token = cached.get("token")
        token_type = cached.get("token_type", "Bearer")
        expires_at = cached.get("expires_at")

        if not token or not expires_at:
            self.cache_status = "miss"
            return

        expiry_dt = self._parse_expiry_at(expires_at)
        if expiry_dt is None:
            self.cache_status = "miss"
            return

        refresh_dt = expiry_dt - dt.timedelta(minutes=5)
        if refresh_dt <= dt.datetime.now(dt.UTC):
            self.cache_status = "expired"
            return

        self._access_token = f"{token_type} {token}".strip()
        self._token_expiry = refresh_dt
        self.cache_status = "hit"

    @staticmethod
    def _normalize_expiry_dt(expiry_dt: dt.datetime) -> dt.datetime:
        """Normalize token expiry timestamp to UTC.

        KIS may return naive timestamps. Treat them as KST for consistency.
        """
        if expiry_dt.tzinfo is None:
            expiry_dt = expiry_dt.replace(tzinfo=_KST)
        return expiry_dt.astimezone(dt.UTC)

    @classmethod
    def _parse_expiry_at(cls, expires_at: Any) -> dt.datetime | None:
        if not isinstance(expires_at, str):
            return None
        value = expires_at.strip()
        if not value:
            return None

        parsed: dt.datetime | None = None
        try:
            parsed = dt.datetime.strptime(value, "%Y-%m-%d %H:%M:%S")
        except ValueError:
            candidates = [value]
            if value.endswith("Z"):
                candidates.append(f"{value[:-1]}+00:00")
            for candidate in candidates:
                try:
                    parsed = dt.datetime.fromisoformat(candidate)
                except ValueError:
                    continue
                break

        if parsed is None:
            return None
        return cls._normalize_expiry_dt(parsed)

    def ensure_token(self) -> None:
        if (
            self._access_token
            and self._token_expiry
            and dt.datetime.now(dt.UTC) < self._token_expiry
        ):
            return

        payload = {
            "grant_type": "client_credentials",
            "appkey": self.creds.app_key,
            "appsecret": self.creds.app_secret,
        }
        headers = {
            "Content-Type": "application/json",
            "Accept": "application/json",
            "charset": "UTF-8",
        }

        try:
            resp = self._request(
                "POST", self.creds.token_url, headers=headers, json=payload
            )
        except requests.RequestException as exc:  # pragma: no cover
            raise KISAuthError(f"Token request failed: {exc}") from exc

        if resp.status_code != 200:
            raise KISAuthError(f"Token request HTTP {resp.status_code}: {resp.text}")

        try:
            data = resp.json()
        except ValueError as exc:
            raise KISAuthError("Token response is not JSON") from exc

        token = data.get("access_token") or data.get("ACCESS_TOKEN")
        token_type = data.get("token_type") or data.get("TOKEN_TYPE") or "Bearer"
        expires_in = data.get("expires_in") or data.get("EXPIRES_IN")
        expires_at_str = (
            data.get("access_token_token_expired")
            or data.get("access_token_expired")
            or data.get("expires_at")
        )

        if not token:
            raise KISAuthError(f"Token missing in response: {data}")

        try:
            expires_seconds = int(expires_in) if expires_in is not None else 3600
        except (TypeError, ValueError):
            expires_seconds = 3600

        expiry_dt: dt.datetime | None = None
        if expires_at_str:
            expiry_dt = self._parse_expiry_at(expires_at_str)

        if expiry_dt is None:
            expiry_dt = dt.datetime.now(dt.UTC) + dt.timedelta(seconds=expires_seconds)

        # refresh a little earlier than actual expiry
        refresh_dt = expiry_dt - dt.timedelta(minutes=5)
        if refresh_dt <= dt.datetime.now(dt.UTC):
            refresh_dt = dt.datetime.now(dt.UTC) + dt.timedelta(
                seconds=int(expires_seconds * 0.9)
            )

        self._access_token = f"{token_type} {token}".strip()
        self._token_expiry = refresh_dt

        if self._cache_dir:
            save_json(
                self._cache_dir,
                self._token_cache_key,
                {
                    "token": token,
                    "token_type": token_type,
                    "expires_at": expiry_dt.isoformat(),
                },
            )
            self.cache_status = "refresh"
        else:
            self.cache_status = "n/a"

        logger.info(
            "KIS token refreshed (env=%s, cache_status=%s, cache_dir=%s)",
            self.creds.env,
            self.cache_status,
            self._cache_dir or "disabled",
        )
