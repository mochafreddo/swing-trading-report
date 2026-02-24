from __future__ import annotations

import datetime as dt
import json
import time
from typing import Any

import requests  # type: ignore[import-untyped]

from .common import KISClientError, _KISClientState, logger

_COUNTRY_CODE_ALIASES: dict[str, set[str]] = {
    "US": {"USA", "840"},
    "KR": {"KOR", "410"},
    "JP": {"JPN", "392"},
    "DE": {"DEU", "276"},
}


def _parse_yyyymmdd(value: str, *, field: str) -> dt.date:
    text = str(value or "").strip()
    if len(text) != 8 or not text.isdigit():
        raise KISClientError(f"Invalid {field}: {value!r} (expected YYYYMMDD)")
    try:
        return dt.datetime.strptime(text, "%Y%m%d").date()
    except ValueError as exc:
        raise KISClientError(f"Invalid {field}: {value!r} (expected YYYYMMDD)") from exc


def _item_signature(item: dict[str, Any]) -> str:
    try:
        return json.dumps(item, sort_keys=True, ensure_ascii=False, default=str)
    except TypeError:  # pragma: no cover
        return repr(sorted((str(key), str(value)) for key, value in item.items()))


def _resolve_country_aliases(country: str) -> tuple[set[str], bool]:
    normalized = str(country or "").strip().upper()
    for canonical, aliases in _COUNTRY_CODE_ALIASES.items():
        all_codes = {canonical, *aliases}
        if normalized in all_codes:
            return all_codes, True
    return {normalized}, False


def _matches_country(item: dict[str, Any], *, country: str) -> bool:
    natn_alpha = str(item.get("natn_eng_abrv_cd") or "").strip().upper()
    natn_numeric = str(item.get("tr_natn_cd") or "").strip().upper()

    if not natn_alpha and not natn_numeric:
        # Keep rows that do not expose explicit country metadata.
        return True

    allowed, _ = _resolve_country_aliases(country)
    if natn_alpha and natn_alpha not in allowed:
        return False
    return not (natn_numeric and natn_numeric not in allowed)


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
        single reference date (TRAD_DT) and returns schedule rows.
        We iterate date by date from start_date to end_date (inclusive).
        """
        country = (country_code or "US").strip().upper() or "US"
        start = _parse_yyyymmdd(start_date, field="start_date")
        end = _parse_yyyymmdd(end_date, field="end_date")
        if start > end:
            raise KISClientError(
                f"Invalid date range: start_date ({start_date}) > end_date ({end_date})"
            )

        self.ensure_token()

        headers = {
            "Content-Type": "application/json",
            "authorization": self._access_token,
            "appkey": self.creds.app_key,
            "appsecret": self.creds.app_secret,
            "tr_id": "CTOS5011R",
            "custtype": "P",
        }

        items: list[dict[str, Any]] = []
        seen_signatures: set[str] = set()
        request_count = 0
        cursor = start
        while cursor <= end:
            params = {
                "TRAD_DT": cursor.strftime("%Y%m%d"),
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
                    request_count += 1
                except requests.RequestException as exc:  # pragma: no cover
                    if attempt < self._max_attempts - 1:
                        time.sleep(1.0)
                        continue
                    raise KISClientError(
                        f"Overseas holiday request failed: {exc}"
                    ) from exc

                try:
                    parsed = resp.json()
                except ValueError as exc:
                    if attempt < self._max_attempts - 1:
                        time.sleep(1.0)
                        continue
                    raise KISClientError(
                        "Overseas holiday response is not JSON"
                    ) from exc

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
                    raise KISClientError(f"KIS overseas holiday error: {msg1}")
                break

            if payload is not None:
                current_items = payload.get("output") or []
                if not isinstance(current_items, list):
                    current_items = [current_items]
                for item in current_items:
                    if not isinstance(item, dict):
                        continue
                    if not _matches_country(item, country=country):
                        continue
                    signature = _item_signature(item)
                    if signature in seen_signatures:
                        continue
                    seen_signatures.add(signature)
                    items.append(item)
            cursor += dt.timedelta(days=1)

        logger.debug(
            "overseas_holidays country=%s start=%s end=%s requests=%d items=%d",
            country,
            start_date,
            end_date,
            request_count,
            len(items),
        )
        return items
