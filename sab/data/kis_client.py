from __future__ import annotations

import datetime as dt
from dataclasses import dataclass
from typing import Any, Optional

import requests

import time

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


class KISClient:
    """Lightweight HTTP client for KIS Developers REST endpoints."""

    def __init__(
        self,
        creds: KISCredentials,
        *,
        session: Optional[requests.Session] = None,
        cache_dir: Optional[str] = None,
        max_attempts: int = 3,
    ):
        self.creds = creds
        self.session = session or requests.Session()
        self._access_token: Optional[str] = None
        self._token_expiry: Optional[dt.datetime] = None
        self._cache_dir = cache_dir
        self._token_cache_key = f"kis_token_{creds.env}"
        self.cache_status: Optional[str] = None
        self._max_attempts = max(1, max_attempts)

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

        if expiry_dt <= dt.datetime.utcnow():
            self.cache_status = "expired"
            return

        self._access_token = f"{token_type} {token}".strip()
        self._token_expiry = expiry_dt
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
            try:
                resp = self.session.request(
                    method,
                    url,
                    headers=headers,
                    params=params,
                    json=json,
                    timeout=timeout,
                )
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
    def daily_candles(self, ticker: str, *, count: int = 120, adjusted: bool = True) -> list[dict[str, Any]]:
        ticker = ticker.strip()
        if not ticker:
            raise KISClientError("Ticker is required")

        self.ensure_token()

        today = dt.datetime.now().strftime("%Y%m%d")
        start_date = (dt.datetime.now() - dt.timedelta(days=max(count * 2, 240))).strftime("%Y%m%d")

        params = {
            "FID_COND_MRKT_DIV_CODE": "J",  # 기본: KRX
            "FID_INPUT_ISCD": ticker,
            "FID_INPUT_DATE_1": start_date,
            "FID_INPUT_DATE_2": today,
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

        try:
            resp = self._request("GET", self.creds.candle_url, headers=headers, params=params)
        except requests.RequestException as exc:  # pragma: no cover
            raise KISClientError(f"Daily candle request failed: {exc}") from exc

        if resp.status_code != 200:
            raise KISClientError(f"Daily candle HTTP {resp.status_code}: {resp.text}")

        try:
            data = resp.json()
        except ValueError as exc:
            raise KISClientError("Daily candle response is not JSON") from exc

        if str(data.get("rt_cd")) != "0":
            msg = data.get("msg1") or data.get("msg_cd") or "Unknown error"
            raise KISClientError(f"KIS error: {msg}")

        items = data.get("output2") or []
        parsed = [self._parse_candle(it) for it in items]

        # API returns most recent first; reverse to oldest→newest
        parsed = [c for c in parsed if c]
        parsed.sort(key=lambda x: x["date"])

        if len(parsed) > count:
            parsed = parsed[-count:]

        return parsed

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

            resp = self._request("GET", self.creds.volume_rank_url, headers=hdrs, params=params)

            if resp.status_code != 200:
                raise KISClientError(f"Volume rank HTTP {resp.status_code}: {resp.text}")

            try:
                data = resp.json()
            except ValueError as exc:
                raise KISClientError("Volume rank response is not JSON") from exc

            if str(data.get("rt_cd")) != "0":
                msg = data.get("msg1") or data.get("msg_cd") or "Unknown error"
                raise KISClientError(f"KIS volume rank error: {msg}")

            items = data.get("output") or []
            parsed = [self._parse_rank_item(it) for it in items]
            parsed = [p for p in parsed if p]
            results.extend(parsed)

            tr_cont = (resp.headers.get("tr_cont") or "").strip()
            if tr_cont != "M":
                break
            tr_cont = "N"

        return results[:limit]

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
