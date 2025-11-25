from __future__ import annotations

import datetime as dt
import time
from dataclasses import dataclass
from typing import Any, Optional

import requests

from .cache import load_json, save_json


class KISClientError(RuntimeError):
    """Base error for KIS client."""


class KISAuthError(KISClientError):
    """Authentication/authz failure."""


@dataclass(frozen=True)
class KISCredentials:
    app_key: str
    app_secret: str
    base_url: str
    env: str  # "real" or "demo"

    @property
    def token_url(self) -> str:
        return f"{self.base_url.rstrip('/')}/oauth2/tokenP"

    @property
    def candle_url(self) -> str:
        return (
            f"{self.base_url.rstrip('/')}/uapi/domestic-stock/v1/quotations/"
            "inquire-daily-itemchartprice"
        )

    @property
    def tr_id(self) -> str:
        # 동일 TR_ID (실전/모의)
        return "FHKST03010100"

    @property
    def volume_rank_url(self) -> str:
        return f"{self.base_url.rstrip('/')}/uapi/domestic-stock/v1/quotations/volume-rank"

    @property
    def volume_rank_tr_id(self) -> str:
        return "FHPST01710000"

    # Overseas
    @property
    def overseas_candle_url(self) -> str:
        # KIS Overseas period (daily) price endpoint
        # v1_해외주식-010: /overseas-price/v1/quotations/dailyprice
        return f"{self.base_url.rstrip('/')}/uapi/overseas-price/v1/quotations/dailyprice"

    @property
    def overseas_tr_id(self) -> str:
        # TR ID for overseas dailyprice (v1_해외주식-010)
        return "HHDFS76240000"

    @property
    def overseas_holiday_url(self) -> str:
        # v1 해외주식-017 해외결제일자조회 (countries-holiday)
        return f"{self.base_url.rstrip('/')}/uapi/overseas-stock/v1/quotations/countries-holiday"

    @property
    def overseas_price_detail_url(self) -> str:
        return f"{self.base_url.rstrip('/')}/uapi/overseas-price/v1/quotations/price-detail"

    def overseas_volume_rank_url(self) -> str:
        return f"{self.base_url.rstrip('/')}/uapi/overseas-stock/v1/ranking/trade-vol"

    def overseas_trade_value_rank_url(self) -> str:
        return f"{self.base_url.rstrip('/')}/uapi/overseas-stock/v1/ranking/trade-pbmn"

    def overseas_market_cap_rank_url(self) -> str:
        return f"{self.base_url.rstrip('/')}/uapi/overseas-stock/v1/ranking/market-cap"


class KISClient:
    """Lightweight HTTP client for KIS Developers REST endpoints."""

    def __init__(
        self,
        creds: KISCredentials,
        *,
        session: Optional[requests.Session] = None,
        cache_dir: Optional[str] = None,
        max_attempts: int = 3,
        min_interval: Optional[float] = None,
    ):
        self.creds = creds
        self.session = session or requests.Session()
        self._access_token: Optional[str] = None
        self._token_expiry: Optional[dt.datetime] = None
        self._cache_dir = cache_dir
        self._token_cache_key = f"kis_token_{creds.env}"
        self.cache_status: Optional[str] = None
        self._max_attempts = max(1, max_attempts)
        # throttle between requests (seconds)
        self._min_interval = (
            float(min_interval)
            if min_interval is not None
            else (0.5 if creds.env == "demo" else 0.1)
        )
        self._last_request_at: Optional[dt.datetime] = None

        self._try_load_cached_token()

    # ------------------------------------------------------------------
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

        try:
            expiry_dt = dt.datetime.fromisoformat(expires_at)
        except ValueError:
            self.cache_status = "miss"
            return

        refresh_dt = expiry_dt - dt.timedelta(minutes=5)
        if refresh_dt <= dt.datetime.utcnow():
            self.cache_status = "expired"
            return

        self._access_token = f"{token_type} {token}".strip()
        self._token_expiry = refresh_dt
        self.cache_status = "hit"

    # ------------------------------------------------------------------
    # Auth
    # ------------------------------------------------------------------
    def _request(
        self,
        method: str,
        url: str,
        *,
        headers: Optional[dict[str, Any]] = None,
        params: Optional[dict[str, Any]] = None,
        json: Optional[dict[str, Any]] = None,
        timeout: float = 10.0,
    ) -> requests.Response:
        backoff = 1.0
        last_exc: Optional[requests.RequestException] = None
        resp: Optional[requests.Response] = None

        for attempt in range(self._max_attempts):
            # simple client-side throttle
            if self._min_interval and self._last_request_at is not None:
                delta = (dt.datetime.utcnow() - self._last_request_at).total_seconds()
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
                self._last_request_at = dt.datetime.utcnow()
            except requests.RequestException as exc:
                last_exc = exc
            else:
                if resp.status_code in {429, 418, 503} and attempt < self._max_attempts - 1:
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

    def ensure_token(self) -> None:
        if self._access_token and self._token_expiry:
            if dt.datetime.utcnow() < self._token_expiry:
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
            resp = self._request("POST", self.creds.token_url, headers=headers, json=payload)
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

        expiry_dt: Optional[dt.datetime] = None
        if expires_at_str:
            try:
                expiry_dt = dt.datetime.strptime(expires_at_str, "%Y-%m-%d %H:%M:%S")
            except ValueError:
                try:
                    expiry_dt = dt.datetime.fromisoformat(expires_at_str)
                except ValueError:
                    expiry_dt = None

        if expiry_dt is None:
            expiry_dt = dt.datetime.utcnow() + dt.timedelta(seconds=expires_seconds)

        # refresh a little earlier than actual expiry
        refresh_dt = expiry_dt - dt.timedelta(minutes=5)
        if refresh_dt <= dt.datetime.utcnow():
            refresh_dt = dt.datetime.utcnow() + dt.timedelta(seconds=int(expires_seconds * 0.9))

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

    # ------------------------------------------------------------------
    # Data fetch
    # ------------------------------------------------------------------
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
                parsed = self._parse_candle(item)
                if parsed and parsed.get("date"):
                    collected[parsed["date"]] = parsed
                    parsed_dates.append(parsed["date"])

            if not parsed_dates:
                empty_streak += 1
                if empty_streak >= self._max_attempts:
                    break
                chunk_end = start_dt - dt.timedelta(days=1)
                continue

            empty_streak = 0
            oldest_dt = min(dt.datetime.strptime(d, "%Y%m%d") for d in parsed_dates)
            chunk_end = oldest_dt - dt.timedelta(days=1)

        parsed = sorted(collected.values(), key=lambda x: x["date"])
        if len(parsed) > target:
            parsed = parsed[-target:]

        return parsed

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
                msg1 = (data.get("msg1") or data.get("msg_cd") or "Unknown error") if isinstance(
                    data, dict
                ) else "Unknown error"
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
                resp = self._request("GET", self.creds.candle_url, headers=headers, params=params)
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
                raise KISClientError(f"Daily candle HTTP {resp.status_code}: {resp.text}")

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

    # ------------------------------------------------------------------
    # Holidays
    # ------------------------------------------------------------------
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

        data: dict[str, Any] | None = None
        for attempt in range(self._max_attempts):
            try:
                resp = self._request(
                    "GET", self.creds.overseas_holiday_url, headers=headers, params=params
                )
            except requests.RequestException as exc:  # pragma: no cover
                if attempt < self._max_attempts - 1:
                    time.sleep(1.0)
                    continue
                raise KISClientError(f"Overseas holiday request failed: {exc}") from exc

            try:
                data = resp.json()
            except ValueError as exc:
                if attempt < self._max_attempts - 1:
                    time.sleep(1.0)
                    continue
                raise KISClientError("Overseas holiday response is not JSON") from exc

            if resp.status_code != 200:
                msg_cd = data.get("msg_cd") or ""
                msg1 = data.get("msg1") or msg_cd or "Unknown error"
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
                raise KISClientError(f"Overseas holiday HTTP {resp.status_code}: {resp.text}")

            if str(data.get("rt_cd")) != "0":
                msg_cd = data.get("msg_cd") or ""
                msg1 = data.get("msg1") or msg_cd or "Unknown error"
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

        items = data.get("output") or []
        if not isinstance(items, list):
            items = [items]
        return items

    # ------------------------------------------------------------------
    # Overseas daily candles (US etc.) with accumulation
    # ------------------------------------------------------------------
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
                parsed = self._parse_overseas_candle(it)
                if parsed and parsed.get("date"):
                    collected[parsed["date"]] = parsed
                    parsed_dates.append(parsed["date"])

            if not parsed_dates:
                empty_streak += 1
                if empty_streak >= self._max_attempts:
                    break
                chunk_end = start_dt - dt.timedelta(days=1)
                continue

            empty_streak = 0
            oldest_dt = min(dt.datetime.strptime(d, "%Y%m%d") for d in parsed_dates)
            chunk_end = oldest_dt - dt.timedelta(days=1)

        parsed = sorted(collected.values(), key=lambda x: x["date"])
        if len(parsed) > target:
            parsed = parsed[-target:]
        return parsed

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
                    "GET", self.creds.overseas_candle_url, headers=headers, params=params
                )
            except requests.RequestException as exc:  # pragma: no cover
                if attempt < self._max_attempts - 1:
                    time.sleep(1.0)
                    continue
                raise KISClientError(f"Overseas daily request failed: {exc}")

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
                raise KISClientError(f"Overseas daily HTTP {resp.status_code}: {resp.text}")

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
    def _parse_overseas_candle(item: dict[str, Any] | None) -> Optional[dict[str, Any]]:
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
            "date": str(item.get("xymd") or item.get("stck_bsop_date") or "").replace("-", ""),
            "open": _to_float(item.get("open") or item.get("stck_oprc")),
            "high": _to_float(item.get("high") or item.get("stck_hgpr")),
            "low": _to_float(item.get("low") or item.get("stck_lwpr")),
            "close": _to_float(
                item.get("close") or item.get("last") or item.get("clos") or item.get("stck_clpr")
            ),
            "volume": _to_float(item.get("volume") or item.get("tvol") or item.get("acml_vol")),
            "prev_close_diff": _to_float(item.get("prdy_vrss") or 0),
        }

    @staticmethod
    def _parse_candle(item: dict[str, Any] | None) -> Optional[dict[str, Any]]:
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

    # ------------------------------------------------------------------
    # Screener helpers
    # ------------------------------------------------------------------
    def volume_rank(
        self,
        *,
        limit: int = 100,
        market: str = "J",
        division_code: str = "0",
        belonging_code: str = "3",
        min_price: float | None = None,
        max_price: float | None = None,
        min_volume: float | None = None,
    ) -> list[dict[str, Any]]:
        if limit <= 0:
            return []

        self.ensure_token()

        def _fmt(val: float | None) -> str:
            if val is None or val <= 0:
                return "0"
            return str(int(val))

        params = {
            "FID_COND_MRKT_DIV_CODE": market,
            "FID_COND_SCR_DIV_CODE": "20171",
            "FID_INPUT_ISCD": "0000",
            "FID_DIV_CLS_CODE": division_code,
            "FID_BLNG_CLS_CODE": belonging_code,
            "FID_TRGT_CLS_CODE": "000000000",
            "FID_TRGT_EXLS_CLS_CODE": "0000000000",
            "FID_INPUT_PRICE_1": _fmt(min_price),
            "FID_INPUT_PRICE_2": _fmt(max_price),
            "FID_VOL_CNT": _fmt(min_volume),
            "FID_INPUT_DATE_1": "0",
        }

        headers = {
            "Content-Type": "application/json",
            "authorization": self._access_token,
            "appkey": self.creds.app_key,
            "appsecret": self.creds.app_secret,
            "tr_id": self.creds.volume_rank_tr_id,
            "custtype": "P",
        }

        results: list[dict[str, Any]] = []
        tr_cont = ""

        while len(results) < limit:
            hdrs = headers.copy()
            if tr_cont:
                hdrs["tr_cont"] = tr_cont

            # Request with body-level rate limit handling
            for attempt in range(self._max_attempts):
                resp = self._request("GET", self.creds.volume_rank_url, headers=hdrs, params=params)

                # Try to parse JSON body even on non-200 to inspect msg_cd
                data: dict[str, Any] | None = None
                try:
                    data = resp.json()
                except ValueError:
                    data = None

                if resp.status_code != 200:
                    msg_cd = str(data.get("msg_cd") or "") if isinstance(data, dict) else ""
                    msg1 = (data.get("msg1") or data.get("msg_cd") or "Unknown error") if isinstance(
                        data, dict
                    ) else "Unknown error"
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
                        f"Volume rank HTTP {resp.status_code}: {msg1} ({resp.text})"
                    )

                if data is None:
                    if attempt < self._max_attempts - 1:
                        time.sleep(1.0)
                        continue
                    raise KISClientError("Volume rank response is not JSON")

                if str(data.get("rt_cd")) != "0":
                    msg_cd = data.get("msg_cd") or ""
                    msg1 = data.get("msg1") or "Unknown error"
                    if msg_cd == "EGW00201" and attempt < self._max_attempts - 1:
                        time.sleep(max(1.0, self._min_interval))
                        continue
                    if msg_cd == "EGW00123" and attempt < self._max_attempts - 1:
                        # Token expired according to body: refresh and retry
                        self._access_token = None
                        self._token_expiry = None
                        self.ensure_token()
                        headers["authorization"] = self._access_token or ""
                        time.sleep(max(1.0, self._min_interval))
                        continue
                    raise KISClientError(f"KIS volume rank error: {msg1}")
                break

            items = data.get("output") or []
            parsed = [self._parse_rank_item(it) for it in items]
            parsed = [p for p in parsed if p]
            results.extend(parsed)

            tr_cont = (resp.headers.get("tr_cont") or "").strip()
            if tr_cont != "M":
                break
            tr_cont = "N"

        return results[:limit]

    # ------------------------------------------------------------------
    # Overseas ranking helpers
    # ------------------------------------------------------------------
    def _fetch_overseas_rank_items(
        self,
        *,
        url: str,
        tr_id: str,
        params: dict[str, Any],
        limit: int,
    ) -> list[dict[str, Any]]:
        if limit <= 0:
            return []

        self.ensure_token()
        request_params = {k: ("" if v is None else v) for k, v in params.items()}
        request_params.setdefault("AUTH", "")
        request_params.setdefault("KEYB", "")

        headers_base = {
            "Content-Type": "application/json",
            "authorization": self._access_token,
            "appkey": self.creds.app_key,
            "appsecret": self.creds.app_secret,
            "tr_id": tr_id,
            "custtype": "P",
        }

        results: list[dict[str, Any]] = []
        tr_cont = ""

        while len(results) < limit:
            headers = headers_base.copy()
            if tr_cont:
                headers["tr_cont"] = tr_cont

            resp = self._request("GET", url, headers=headers, params=request_params)

            if resp.status_code != 200:
                raise KISClientError(f"Overseas rank HTTP {resp.status_code}: {resp.text}")

            try:
                data = resp.json()
            except ValueError as exc:
                raise KISClientError("Overseas rank response is not JSON") from exc

            if str(data.get("rt_cd")) != "0":
                msg = data.get("msg1") or data.get("msg_cd") or "Unknown error"
                raise KISClientError(f"KIS overseas rank error: {msg}")

            items = data.get("output2") or data.get("output") or []
            if isinstance(items, dict):
                items = [items]

            for item in items:
                if not isinstance(item, dict):
                    continue
                results.append(item)
                if len(results) >= limit:
                    break

            if len(results) >= limit:
                break

            tr_cont = (resp.headers.get("tr_cont") or "").strip()
            keyb = (
                data.get("keyb")
                or data.get("KEYB")
                or (data.get("output1") or {}).get("keyb")
                or ""
            )
            request_params["KEYB"] = keyb

            if tr_cont not in {"M", "F"}:
                break

        return results[:limit]

    def overseas_trade_volume_rank(
        self,
        *,
        exchange: str,
        limit: int,
        nday: str = "0",
        volume_filter: str = "0",
    ) -> list[dict[str, Any]]:
        params = {
            "EXCD": exchange,
            "NDAY": nday,
            "VOL_RANG": volume_filter,
        }
        return self._fetch_overseas_rank_items(
            url=self.creds.overseas_volume_rank_url(),
            tr_id="HHDFS76310010",
            params=params,
            limit=limit,
        )

    def overseas_trade_value_rank(
        self,
        *,
        exchange: str,
        limit: int,
        nday: str = "0",
        volume_filter: str = "0",
        price_min: Optional[float] = None,
        price_max: Optional[float] = None,
    ) -> list[dict[str, Any]]:
        def _price(val: Optional[float]) -> str:
            if val is None or val <= 0:
                return ""
            return str(int(val))

        params: dict[str, Any] = {
            "EXCD": exchange,
            "NDAY": nday,
            "VOL_RANG": volume_filter,
            "PRC1": _price(price_min),
            "PRC2": _price(price_max),
        }
        return self._fetch_overseas_rank_items(
            url=self.creds.overseas_trade_value_rank_url(),
            tr_id="HHDFS76320010",
            params=params,
            limit=limit,
        )

    def overseas_market_cap_rank(
        self,
        *,
        exchange: str,
        limit: int,
        volume_filter: str = "0",
    ) -> list[dict[str, Any]]:
        params = {
            "EXCD": exchange,
            "VOL_RANG": volume_filter,
        }
        return self._fetch_overseas_rank_items(
            url=self.creds.overseas_market_cap_rank_url(),
            tr_id="HHDFS76350100",
            params=params,
            limit=limit,
        )

    @staticmethod
    def _parse_rank_item(item: dict[str, Any] | None) -> Optional[dict[str, Any]]:
        if not item:
            return None

        def _g(keys: list[str]) -> Any:
            for k in keys:
                if k in item:
                    return item[k]
            return None

        def _to_float(val: Any) -> float:
            if val is None or val == "":
                return 0.0
            try:
                return float(str(val).replace(",", ""))
            except ValueError:
                return 0.0

        ticker = _g(["shrn_iscd", "mksc_shrn_iscd", "stck_shrn_iscd"]) or ""
        name = _g(["hts_kor_isnm", "stck_hnm", "kor_sec_name"]) or ticker
        price = _to_float(_g(["stck_prpr", "stck_prtp"]))
        volume = _to_float(_g(["stck_cnt", "acml_vol", "acc_trdvol"]))
        amount = _to_float(_g(["acml_tr_pbmn", "acc_trdprc", "acc_trdval"]))

        if not ticker:
            return None

        if amount == 0.0:
            amount = price * volume

        return {
            "ticker": ticker,
            "name": name,
            "price": price,
            "volume": volume,
            "amount": amount,
        }
