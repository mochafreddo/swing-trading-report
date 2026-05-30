from __future__ import annotations

import datetime as dt
import re
import time
from typing import Any

import requests  # type: ignore[import-untyped]

from .common import KISApiError, KISClientError, _KISClientState

_CLASS_DOT_SYMBOL_PATTERN = re.compile(r"^([A-Z][A-Z0-9]*)\.([ABC])$")
_CLASS_SLASH_SYMBOL_PATTERN = re.compile(r"^([A-Z][A-Z0-9]*)/([ABC])$")
_OVERSEAS_INVALID_SYMBOL_MSG_CDS = frozenset({"SYMB0001"})


def _to_float_or_nan(value: Any) -> float:
    if value is None or value == "":
        return float("nan")
    try:
        return float(str(value).replace(",", ""))
    except ValueError:
        return float("nan")


class _KISQuoteMixin(_KISClientState):
    """Domestic/overseas quote and candle responsibilities."""

    @staticmethod
    def _normalize_overseas_symbol(symbol: str) -> str:
        return str(symbol or "").strip().upper()

    @staticmethod
    def _class_symbol_parts(symbol: str) -> tuple[str, str] | None:
        dot_match = _CLASS_DOT_SYMBOL_PATTERN.fullmatch(symbol)
        if dot_match is not None:
            return dot_match.group(1), dot_match.group(2)
        slash_match = _CLASS_SLASH_SYMBOL_PATTERN.fullmatch(symbol)
        if slash_match is not None:
            return slash_match.group(1), slash_match.group(2)
        return None

    def _overseas_symbol_candidates(self, symbol: str) -> list[str]:
        normalized = self._normalize_overseas_symbol(symbol)
        parts = self._class_symbol_parts(normalized)
        if parts is None:
            return [normalized]
        base, class_code = parts
        dot_symbol = f"{base}.{class_code}"
        slash_symbol = f"{base}/{class_code}"
        preferred = self._overseas_symbol_preference.get(dot_symbol)
        if preferred in {dot_symbol, slash_symbol}:
            first = preferred
        else:
            first = (
                normalized if normalized in {dot_symbol, slash_symbol} else dot_symbol
            )
        second = slash_symbol if first == dot_symbol else dot_symbol
        return [first, second]

    @staticmethod
    def _can_fallback_overseas_symbol(error: KISClientError) -> bool:
        return (
            isinstance(error, KISApiError)
            and error.msg_cd in _OVERSEAS_INVALID_SYMBOL_MSG_CDS
        )

    def _remember_overseas_symbol_preference(
        self, *, requested_symbol: str, resolved_symbol: str
    ) -> None:
        normalized_requested = self._normalize_overseas_symbol(requested_symbol)
        parts = self._class_symbol_parts(normalized_requested)
        if parts is None:
            return
        base, class_code = parts
        dot_symbol = f"{base}.{class_code}"
        slash_symbol = f"{base}/{class_code}"
        normalized_resolved = self._normalize_overseas_symbol(resolved_symbol)
        if normalized_resolved in {dot_symbol, slash_symbol}:
            self._overseas_symbol_preference[dot_symbol] = normalized_resolved

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

    def domestic_price_detail(self, *, ticker: str) -> dict[str, Any]:
        ticker = (ticker or "").strip().upper()
        if not ticker:
            raise KISClientError("Ticker is required for domestic price detail")

        self.ensure_token()

        params = {
            "FID_COND_MRKT_DIV_CODE": "J",
            "FID_INPUT_ISCD": ticker,
        }
        headers = {
            "Content-Type": "application/json",
            "authorization": self._access_token,
            "appkey": self.creds.app_key,
            "appsecret": self.creds.app_secret,
            "tr_id": "FHKST01010100",
            "custtype": "P",
        }

        for attempt in range(self._max_attempts):
            resp = self._request(
                "GET",
                self.creds.domestic_price_detail_url,
                headers=headers,
                params=params,
            )

            data: dict[str, Any] | None = None
            try:
                data = resp.json()
            except ValueError:
                data = None

            if resp.status_code != 200:
                msg_cd = str(data.get("msg_cd") or "") if isinstance(data, dict) else ""
                if msg_cd == "EGW00123" and attempt < self._max_attempts - 1:
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
                    f"Domestic price detail HTTP {resp.status_code}: {resp.text}"
                )

            if data is None:
                if attempt < self._max_attempts - 1:
                    time.sleep(1.0)
                    continue
                raise KISClientError("Domestic price detail response is not JSON")

            if str(data.get("rt_cd")) != "0":
                msg_cd = str(data.get("msg_cd") or "")
                msg1 = str(data.get("msg1") or "Unknown error")
                if msg_cd == "EGW00123" and attempt < self._max_attempts - 1:
                    self._access_token = None
                    self._token_expiry = None
                    self.ensure_token()
                    headers["authorization"] = self._access_token or ""
                    time.sleep(max(1.0, self._min_interval))
                    continue
                if attempt < self._max_attempts - 1:
                    time.sleep(1.0)
                    continue
                raise KISClientError(f"KIS domestic price detail error: {msg1}")

            output = data.get("output")
            if isinstance(output, dict):
                return output
            if isinstance(output, list):
                return output[0] if output else {}
            return {}

        raise KISClientError("Domestic price detail request failed after retries")

    def overseas_price_detail(self, *, symbol: str, exchange: str) -> dict[str, Any]:
        normalized_symbol = self._normalize_overseas_symbol(symbol)
        exchange = (exchange or "").strip().upper()
        if not normalized_symbol or not exchange:
            raise KISClientError("Symbol and exchange are required for price detail")

        attempted_symbols: list[str] = []
        last_error: KISClientError | None = None
        for candidate_symbol in self._overseas_symbol_candidates(normalized_symbol):
            attempted_symbols.append(candidate_symbol)
            try:
                result = self._overseas_price_detail_once(
                    symbol=candidate_symbol,
                    exchange=exchange,
                )
            except KISClientError as exc:
                last_error = exc
                if len(attempted_symbols) < 2 and self._can_fallback_overseas_symbol(
                    exc
                ):
                    continue
                raise
            self._remember_overseas_symbol_preference(
                requested_symbol=normalized_symbol,
                resolved_symbol=candidate_symbol,
            )
            return result

        assert last_error is not None
        if len(attempted_symbols) > 1:
            raise KISClientError(
                f"{last_error} (overseas symbol candidates tried: {attempted_symbols})"
            ) from last_error
        raise last_error

    def _overseas_price_detail_once(
        self,
        *,
        symbol: str,
        exchange: str,
    ) -> dict[str, Any]:
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
                if msg_cd:
                    raise KISApiError(
                        f"Overseas price detail HTTP {resp.status_code}: {resp.text}",
                        msg_cd=msg_cd,
                        msg1=str(msg1),
                        http_status=resp.status_code,
                        context="overseas_price_detail",
                    )
                raise KISClientError(
                    f"Overseas price detail HTTP {resp.status_code}: {resp.text}"
                )

            if data is None:
                if attempt < self._max_attempts - 1:
                    time.sleep(1.0)
                    continue
                raise KISClientError("Overseas price detail response is not JSON")

            if str(data.get("rt_cd")) != "0":
                msg_cd = str(data.get("msg_cd") or "")
                msg1 = str(data.get("msg1") or "Unknown error")
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
                raise KISApiError(
                    f"KIS overseas price detail error: {msg1}",
                    msg_cd=msg_cd,
                    msg1=msg1,
                    rt_cd=str(data.get("rt_cd") or ""),
                    context="overseas_price_detail",
                )

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
                msg_cd = str(parsed.get("msg_cd") or "")
                msg1 = str(parsed.get("msg1") or "Unknown error")
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
        requested_symbol = symbol.strip().upper()
        exchange = exchange.strip().upper()
        if not requested_symbol or not exchange:
            raise KISClientError("Overseas symbol and exchange are required")

        self.ensure_token()

        target = max(count, 1)
        chunk_days = 240
        now = dt.datetime.now()
        earliest_allowed = now - dt.timedelta(days=365 * 10)
        for candidate_symbol in self._overseas_symbol_candidates(requested_symbol):
            collected: dict[str, dict[str, Any]] = {}
            chunk_end = now
            empty_streak = 0

            while len(collected) < target and chunk_end > earliest_allowed:
                start_dt = chunk_end - dt.timedelta(days=chunk_days)
                if start_dt < earliest_allowed:
                    start_dt = earliest_allowed
                start_str = start_dt.strftime("%Y%m%d")
                end_str = chunk_end.strftime("%Y%m%d")

                items = self._fetch_overseas_candle_chunk(
                    symbol=candidate_symbol,
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
                oldest_dt = min(
                    dt.datetime.strptime(date_text, "%Y%m%d")
                    for date_text in parsed_dates
                )
                chunk_end = oldest_dt - dt.timedelta(days=1)

            rows = sorted(collected.values(), key=lambda x: x["date"])
            if len(rows) > target:
                rows = rows[-target:]
            if rows:
                self._remember_overseas_symbol_preference(
                    requested_symbol=requested_symbol,
                    resolved_symbol=candidate_symbol,
                )
                return rows

        return []

    def _fetch_overseas_candle_chunk(
        self,
        *,
        symbol: str,
        exchange: str,
        start_date: str,
        end_date: str,
        adjusted: bool,
    ) -> list[dict[str, Any]]:
        normalized_symbol = self._normalize_overseas_symbol(symbol)
        attempted_symbols: list[str] = []
        last_error: KISClientError | None = None
        for candidate_symbol in self._overseas_symbol_candidates(normalized_symbol):
            attempted_symbols.append(candidate_symbol)
            try:
                rows = self._fetch_overseas_candle_chunk_once(
                    symbol=candidate_symbol,
                    exchange=exchange,
                    start_date=start_date,
                    end_date=end_date,
                    adjusted=adjusted,
                )
            except KISClientError as exc:
                last_error = exc
                if len(attempted_symbols) < 2 and self._can_fallback_overseas_symbol(
                    exc
                ):
                    continue
                raise
            if rows:
                self._remember_overseas_symbol_preference(
                    requested_symbol=normalized_symbol,
                    resolved_symbol=candidate_symbol,
                )
            return rows

        assert last_error is not None
        if len(attempted_symbols) > 1:
            raise KISClientError(
                f"{last_error} (overseas symbol candidates tried: {attempted_symbols})"
            ) from last_error
        raise last_error

    def _fetch_overseas_candle_chunk_once(
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
                msg_cd = str(parsed.get("msg_cd") or "")
                msg1 = str(parsed.get("msg1") or "Unknown error")
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
                if msg_cd:
                    raise KISApiError(
                        f"Overseas daily HTTP {resp.status_code}: {resp.text}",
                        msg_cd=msg_cd,
                        msg1=msg1,
                        http_status=resp.status_code,
                        context="overseas_daily",
                    )
                raise KISClientError(
                    f"Overseas daily HTTP {resp.status_code}: {resp.text}"
                )

            if str(parsed.get("rt_cd")) != "0":
                msg_cd = str(parsed.get("msg_cd") or "")
                msg1 = str(parsed.get("msg1") or "Unknown error")
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
                raise KISApiError(
                    f"KIS overseas error: {msg1}",
                    msg_cd=msg_cd,
                    msg1=msg1,
                    rt_cd=str(parsed.get("rt_cd") or ""),
                    context="overseas_daily",
                )
            break

        if data is None:
            return []

        # overseas output variable names differ; prefer 'output2' like domestic. Fallback to 'output'
        return data.get("output2") or data.get("output") or []

    @staticmethod
    def _parse_overseas_candle(item: dict[str, Any] | None) -> dict[str, Any] | None:
        if not item:
            return None

        # Overseas fields typically: xymd, open, high, low, close/last, volume/tvol
        return {
            "date": str(item.get("xymd") or item.get("stck_bsop_date") or "").replace(
                "-", ""
            ),
            "open": _to_float_or_nan(item.get("open") or item.get("stck_oprc")),
            "high": _to_float_or_nan(item.get("high") or item.get("stck_hgpr")),
            "low": _to_float_or_nan(item.get("low") or item.get("stck_lwpr")),
            "close": _to_float_or_nan(
                item.get("close")
                or item.get("last")
                or item.get("clos")
                or item.get("stck_clpr")
            ),
            "volume": _to_float_or_nan(
                item.get("volume") or item.get("tvol") or item.get("acml_vol")
            ),
            "prev_close_diff": _to_float_or_nan(item.get("prdy_vrss") or 0),
        }

    @staticmethod
    def _parse_candle(item: dict[str, Any] | None) -> dict[str, Any] | None:
        if not item:
            return None

        return {
            "date": item.get("stck_bsop_date"),
            "open": _to_float_or_nan(item.get("stck_oprc")),
            "high": _to_float_or_nan(item.get("stck_hgpr")),
            "low": _to_float_or_nan(item.get("stck_lwpr")),
            "close": _to_float_or_nan(item.get("stck_clpr")),
            "volume": _to_float_or_nan(item.get("acml_vol")),
            "prev_close_diff": _to_float_or_nan(item.get("prdy_vrss")),
        }
