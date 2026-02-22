from __future__ import annotations

import time
from typing import Any

import requests  # type: ignore[import-untyped]

from .common import KISClientError, _KISClientState, logger


class _KISCalendarMixin(_KISClientState):
    """Overseas holiday/calendar responsibilities."""

    def overseas_holidays(
        self,
        *,
        country_code: str = "US",
        start_date: str,
        end_date: str,
    ) -> list[dict[str, Any]]:
        """Fetch overseas holiday/settlement schedule.

        Note: KIS provides countries-holiday API (해외결제일자조회) which takes a
        single reference date (TRAD_DT) and returns schedule rows. We call it
        with start_date and return its output; end_date is unused.
        """
        self.ensure_token()

        headers = {
            "Content-Type": "application/json",
            "authorization": self._access_token,
            "appkey": self.creds.app_key,
            "appsecret": self.creds.app_secret,
            "tr_id": "CTOS5011R",
            "custtype": "P",
        }

        params = {
            "TRAD_DT": start_date,
            "CTX_AREA_NK": "",
            "CTX_AREA_FK": "",
        }

        payload: dict[str, Any] | None = None
        for attempt in range(self._max_attempts):
            try:
                resp = self._request(
                    "GET",
                    self.creds.overseas_holiday_url,
                    headers=headers,
                    params=params,
                )
            except requests.RequestException as exc:  # pragma: no cover
                if attempt < self._max_attempts - 1:
                    time.sleep(1.0)
                    continue
                raise KISClientError(f"Overseas holiday request failed: {exc}") from exc

            try:
                parsed = resp.json()
            except ValueError as exc:
                if attempt < self._max_attempts - 1:
                    time.sleep(1.0)
                    continue
                raise KISClientError("Overseas holiday response is not JSON") from exc

            if not isinstance(parsed, dict):
                if attempt < self._max_attempts - 1:
                    time.sleep(1.0)
                    continue
                raise KISClientError(
                    "Overseas holiday response payload is not an object"
                )

            payload = parsed

            if resp.status_code != 200:
                msg_cd = payload.get("msg_cd") or ""
                msg1 = payload.get("msg1") or msg_cd or "Unknown error"
                if msg_cd == "EGW00123" and attempt < self._max_attempts - 1:
                    # Token expired: refresh and retry
                    self._access_token = None
                    self._token_expiry = None
                    self.ensure_token()
                    headers["authorization"] = self._access_token or ""
                    time.sleep(max(1.0, self._min_interval))
                    continue
                if attempt < self._max_attempts - 1:
                    time.sleep(1.0)
                    continue
                raise KISClientError(
                    f"Overseas holiday HTTP {resp.status_code}: {resp.text}"
                )

            if str(payload.get("rt_cd")) != "0":
                msg_cd = payload.get("msg_cd") or ""
                msg1 = payload.get("msg1") or msg_cd or "Unknown error"
                if msg_cd == "EGW00123" and attempt < self._max_attempts - 1:
                    self._access_token = None
                    self._token_expiry = None
                    self.ensure_token()
                    headers["authorization"] = self._access_token or ""
                    time.sleep(max(1.0, self._min_interval))
                    continue
                msg = msg1
                raise KISClientError(f"KIS overseas holiday error: {msg}")
            break

        if payload is None:
            return []

        items = payload.get("output") or []
        if not isinstance(items, list):
            items = [items]
        logger.debug(
            "overseas_holidays rt_cd=%s msg_cd=%s msg1=%s items=%d",
            payload.get("rt_cd"),
            payload.get("msg_cd"),
            payload.get("msg1"),
            len(items),
        )
        return items
