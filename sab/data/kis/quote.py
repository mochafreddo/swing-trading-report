from __future__ import annotations

import datetime as dt
import time
from typing import Any

import requests  # type: ignore[import-untyped]

from .common import KISClientError, _KISClientState


class _KISQuoteMixin(_KISClientState):
    """Domestic/overseas quote and candle responsibilities."""

    def daily_candles(
        self, ticker: str, *, count: int = 120, adjusted: bool = True
    ) -> list[dict[str, Any]]:
        ticker = ticker.strip()
        if not ticker:
            raise KISClientError("Ticker is required")

        self.ensure_token()

        target = max(count, 1)
        chunk_days = 240  # window size per call (~100 trading days)
        collected: dict[str, dict[str, Any]] = {}

        now = dt.datetime.now()
        chunk_end = now
        earliest_allowed = now - dt.timedelta(days=365 * 10)  # safety limit (~10y)
        empty_streak = 0

        while len(collected) < target and chunk_end > earliest_allowed:
            start_dt = chunk_end - dt.timedelta(days=chunk_days)
            if start_dt < earliest_allowed:
                start_dt = earliest_allowed

            start_str = start_dt.strftime("%Y%m%d")
            end_str = chunk_end.strftime("%Y%m%d")

            items = self._fetch_candle_chunk(
                ticker=ticker,
                start_date=start_str,
                end_date=end_str,
                adjusted=adjusted,
            )

            parsed_dates: list[str] = []
            for item in items:
                parsed_item = self._parse_candle(item)
                if parsed_item and parsed_item.get("date"):
                    date_key = str(parsed_item["date"])
                    collected[date_key] = parsed_item
                    parsed_dates.append(date_key)

            if not parsed_dates:
                empty_streak += 1
                if empty_streak >= self._max_attempts:
                    break
                chunk_end = start_dt - dt.timedelta(days=1)
                continue

            empty_streak = 0
            oldest_dt = min(dt.datetime.strptime(d, "%Y%m%d") for d in parsed_dates)
            chunk_end = oldest_dt - dt.timedelta(days=1)

        rows = sorted(collected.values(), key=lambda x: x["date"])
        if len(rows) > target:
            rows = rows[-target:]

        return rows

    def overseas_price_detail(self, *, symbol: str, exchange: str) -> dict[str, Any]:
        symbol = (symbol or "").strip().upper()
        exchange = (exchange or "").strip().upper()
        if not symbol or not exchange:
            raise KISClientError("Symbol and exchange are required for price detail")

        self.ensure_token()

        params = {
            "AUTH": "",
            "EXCD": exchange,
            "SYMB": symbol,
        }
        headers = {
            "Content-Type": "application/json",
            "authorization": self._access_token,
            "appkey": self.creds.app_key,
            "appsecret": self.creds.app_secret,
            "tr_id": "HHDFS76200200",
            "custtype": "P",
        }

        for attempt in range(self._max_attempts):
            resp = self._request(
                "GET",
                self.creds.overseas_price_detail_url,
                headers=headers,
                params=params,
            )

            # Try to parse JSON body even on non-200 to inspect msg_cd
            data: dict[str, Any] | None = None
            try:
                data = resp.json()
            except ValueError:
                data = None

            if resp.status_code != 200:
                msg_cd = str(data.get("msg_cd") or "") if isinstance(data, dict) else ""
                msg1 = (
                    (data.get("msg1") or data.get("msg_cd") or "Unknown error")
                    if isinstance(data, dict)
                    else "Unknown error"
                )
                if msg_cd == "EGW00123" and attempt < self._max_attempts - 1:
                    # Token expired on server side: clear, refresh, and retry
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
                    f"Overseas price detail HTTP {resp.status_code}: {resp.text}"
                )

            if data is None:
                if attempt < self._max_attempts - 1:
                    time.sleep(1.0)
                    continue
                raise KISClientError("Overseas price detail response is not JSON")

            if str(data.get("rt_cd")) != "0":
                msg_cd = data.get("msg_cd") or ""
                msg1 = data.get("msg1") or "Unknown error"
                if msg_cd == "EGW00201" and attempt < self._max_attempts - 1:
                    time.sleep(max(1.0, self._min_interval))
                    continue
                if msg_cd == "EGW00123" and attempt < self._max_attempts - 1:
                    self._access_token = None
                    self._token_expiry = None
                    self.ensure_token()
                    headers["authorization"] = self._access_token or ""
                    time.sleep(max(1.0, self._min_interval))
                    continue
                raise KISClientError(f"KIS overseas price detail error: {msg1}")

            output = data.get("output")
            if isinstance(output, list):
                return output[0] if output else {}
            if isinstance(output, dict):
                return output
            return {}

        # If loop exits without return, raise generic error
        raise KISClientError("Overseas price detail request failed after retries")

    def _fetch_candle_chunk(
        self,
        *,
        ticker: str,
        start_date: str,
        end_date: str,
        adjusted: bool,
    ) -> list[dict[str, Any]]:
        params = {
            "FID_COND_MRKT_DIV_CODE": "J",
            "FID_INPUT_ISCD": ticker,
            "FID_INPUT_DATE_1": start_date,
            "FID_INPUT_DATE_2": end_date,
            "FID_PERIOD_DIV_CODE": "D",
            "FID_ORG_ADJ_PRC": "0" if adjusted else "1",
        }

        headers = {
            "Content-Type": "application/json",
            "authorization": self._access_token,
            "appkey": self.creds.app_key,
            "appsecret": self.creds.app_secret,
            "tr_id": self.creds.tr_id,
            "custtype": "P",
        }

        data: dict[str, Any] | None = None
        for attempt in range(self._max_attempts):
            try:
                resp = self._request(
                    "GET", self.creds.candle_url, headers=headers, params=params
                )
            except requests.RequestException as exc:  # pragma: no cover
                if attempt < self._max_attempts - 1:
                    time.sleep(1.0)
                    continue
                raise KISClientError(f"Daily candle request failed: {exc}") from exc

            try:
                parsed = resp.json()
            except ValueError as exc:
                if attempt < self._max_attempts - 1:
                    time.sleep(1.0)
                    continue
                raise KISClientError("Daily candle response is not JSON") from exc

            if not isinstance(parsed, dict):
                raise KISClientError("Daily candle response payload is not an object")

            data = parsed

            if resp.status_code != 200:
                msg_cd = parsed.get("msg_cd") or ""
                msg1 = parsed.get("msg1") or "Unknown error"
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
                    f"Daily candle HTTP {resp.status_code}: {resp.text}"
                )

            if str(parsed.get("rt_cd")) != "0":
                msg_cd = parsed.get("msg_cd") or ""
                msg1 = parsed.get("msg1") or "Unknown error"
                if msg_cd == "EGW00201" and attempt < self._max_attempts - 1:
                    time.sleep(max(1.0, self._min_interval))
                    continue
                if msg_cd == "EGW00123" and attempt < self._max_attempts - 1:
                    self._access_token = None
                    self._token_expiry = None
                    self.ensure_token()
                    headers["authorization"] = self._access_token or ""
                    time.sleep(max(1.0, self._min_interval))
                    continue
                raise KISClientError(f"KIS error: {msg1}")
            break

        if data is None:
            return []

        return data.get("output2") or []

    def overseas_daily_candles(
        self,
        *,
        symbol: str,
        exchange: str = "NASD",
        count: int = 120,
        adjusted: bool = True,
    ) -> list[dict[str, Any]]:
        symbol = symbol.strip().upper()
        exchange = exchange.strip().upper()
        if not symbol or not exchange:
            raise KISClientError("Overseas symbol and exchange are required")

        self.ensure_token()

        target = max(count, 1)
        chunk_days = 240
        collected: dict[str, dict[str, Any]] = {}

        now = dt.datetime.now()
        chunk_end = now
        earliest_allowed = now - dt.timedelta(days=365 * 10)
        empty_streak = 0

        while len(collected) < target and chunk_end > earliest_allowed:
            start_dt = chunk_end - dt.timedelta(days=chunk_days)
            if start_dt < earliest_allowed:
                start_dt = earliest_allowed
            start_str = start_dt.strftime("%Y%m%d")
            end_str = chunk_end.strftime("%Y%m%d")

            items = self._fetch_overseas_candle_chunk(
                symbol=symbol,
                exchange=exchange,
                start_date=start_str,
                end_date=end_str,
                adjusted=adjusted,
            )

            parsed_dates: list[str] = []
            for it in items:
                parsed_item = self._parse_overseas_candle(it)
                if parsed_item and parsed_item.get("date"):
                    date_key = str(parsed_item["date"])
                    collected[date_key] = parsed_item
                    parsed_dates.append(date_key)

            if not parsed_dates:
                empty_streak += 1
                if empty_streak >= self._max_attempts:
                    break
                chunk_end = start_dt - dt.timedelta(days=1)
                continue

            empty_streak = 0
            oldest_dt = min(dt.datetime.strptime(d, "%Y%m%d") for d in parsed_dates)
            chunk_end = oldest_dt - dt.timedelta(days=1)

        rows = sorted(collected.values(), key=lambda x: x["date"])
        if len(rows) > target:
            rows = rows[-target:]
        return rows

    def _fetch_overseas_candle_chunk(
        self,
        *,
        symbol: str,
        exchange: str,
        start_date: str,
        end_date: str,
        adjusted: bool,
    ) -> list[dict[str, Any]]:
        params = {
            # KIS overseas params: EXCD(exchange), SYMB(symbol), GUBN(0:period), BYMD(end ymd), MODP(1:adjusted)
            "EXCD": exchange,
            "SYMB": symbol,
            "GUBN": "0",
            "BYMD": end_date,
            "MODP": "1" if adjusted else "0",
        }

        headers = {
            "Content-Type": "application/json",
            "authorization": self._access_token,
            "appkey": self.creds.app_key,
            "appsecret": self.creds.app_secret,
            "tr_id": self.creds.overseas_tr_id,
            "custtype": "P",
        }

        data: dict[str, Any] | None = None
        for attempt in range(self._max_attempts):
            try:
                resp = self._request(
                    "GET",
                    self.creds.overseas_candle_url,
                    headers=headers,
                    params=params,
                )
            except requests.RequestException as exc:  # pragma: no cover
                if attempt < self._max_attempts - 1:
                    time.sleep(1.0)
                    continue
                raise KISClientError(f"Overseas daily request failed: {exc}") from exc

            try:
                parsed = resp.json()
            except ValueError as exc:
                if attempt < self._max_attempts - 1:
                    time.sleep(1.0)
                    continue
                raise KISClientError("Overseas daily response is not JSON") from exc

            if not isinstance(parsed, dict):
                raise KISClientError("Overseas daily response payload is not an object")

            data = parsed

            if resp.status_code != 200:
                msg_cd = parsed.get("msg_cd") or ""
                msg1 = parsed.get("msg1") or "Unknown error"
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
                    f"Overseas daily HTTP {resp.status_code}: {resp.text}"
                )

            if str(parsed.get("rt_cd")) != "0":
                msg_cd = parsed.get("msg_cd") or ""
                msg1 = parsed.get("msg1") or "Unknown error"
                if msg_cd == "EGW00201" and attempt < self._max_attempts - 1:
                    time.sleep(max(1.0, self._min_interval))
                    continue
                if msg_cd == "EGW00123" and attempt < self._max_attempts - 1:
                    self._access_token = None
                    self._token_expiry = None
                    self.ensure_token()
                    headers["authorization"] = self._access_token or ""
                    time.sleep(max(1.0, self._min_interval))
                    continue
                raise KISClientError(f"KIS overseas error: {msg1}")
            break

        if data is None:
            return []

        # overseas output variable names differ; prefer 'output2' like domestic. Fallback to 'output'
        return data.get("output2") or data.get("output") or []

    @staticmethod
    def _parse_overseas_candle(item: dict[str, Any] | None) -> dict[str, Any] | None:
        if not item:
            return None

        def _to_float(val: Any) -> float:
            if val is None or val == "":
                return float("nan")
            try:
                return float(str(val).replace(",", ""))
            except ValueError:
                return float("nan")

        # Overseas fields typically: xymd, open, high, low, close/last, volume/tvol
        return {
            "date": str(item.get("xymd") or item.get("stck_bsop_date") or "").replace(
                "-", ""
            ),
            "open": _to_float(item.get("open") or item.get("stck_oprc")),
            "high": _to_float(item.get("high") or item.get("stck_hgpr")),
            "low": _to_float(item.get("low") or item.get("stck_lwpr")),
            "close": _to_float(
                item.get("close")
                or item.get("last")
                or item.get("clos")
                or item.get("stck_clpr")
            ),
            "volume": _to_float(
                item.get("volume") or item.get("tvol") or item.get("acml_vol")
            ),
            "prev_close_diff": _to_float(item.get("prdy_vrss") or 0),
        }

    @staticmethod
    def _parse_candle(item: dict[str, Any] | None) -> dict[str, Any] | None:
        if not item:
            return None

        def _to_float(val: Any) -> float:
            if val is None or val == "":
                return float("nan")
            try:
                return float(str(val).replace(",", ""))
            except ValueError:
                return float("nan")

        return {
            "date": item.get("stck_bsop_date"),
            "open": _to_float(item.get("stck_oprc")),
            "high": _to_float(item.get("stck_hgpr")),
            "low": _to_float(item.get("stck_lwpr")),
            "close": _to_float(item.get("stck_clpr")),
            "volume": _to_float(item.get("acml_vol")),
            "prev_close_diff": _to_float(item.get("prdy_vrss")),
        }
