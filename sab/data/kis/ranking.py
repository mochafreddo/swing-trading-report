from __future__ import annotations

import time
from typing import Any

import requests  # type: ignore[import-untyped]

from .common import KISApiError, KISClientError, _KISClientState


def _format_positive_int_filter(
    value: float | None, *, empty_when_missing: bool = False
) -> str:
    if value is None or value <= 0:
        return "" if empty_when_missing else "0"
    return str(int(value))


def _json_or_none(response: requests.Response) -> Any | None:
    try:
        return response.json()
    except ValueError:
        return None


def _payload_dict(value: Any | None) -> dict[str, Any] | None:
    if isinstance(value, dict):
        return value
    return None


def _error_fields(payload: dict[str, Any] | None) -> tuple[str, str]:
    if payload is None:
        return "", "Unknown error"
    msg_cd = str(payload.get("msg_cd") or "")
    msg1 = str(payload.get("msg1") or msg_cd or "Unknown error")
    return msg_cd, msg1


def _rank_items(payload: dict[str, Any], *keys: str) -> list[dict[str, Any]]:
    raw_items: Any = []
    for key in keys:
        value = payload.get(key)
        if value:
            raw_items = value
            break
    if isinstance(raw_items, dict):
        raw_items = [raw_items]
    if not isinstance(raw_items, list):
        return []
    return [item for item in raw_items if isinstance(item, dict)]


def _pagination_key(payload: dict[str, Any]) -> Any:
    output1 = payload.get("output1") or {}
    if isinstance(output1, list) and output1:
        output1 = output1[0]
    if not isinstance(output1, dict):
        output1 = {}
    return (
        payload.get("keyb")
        or payload.get("KEYB")
        or output1.get("keyb")
        or output1.get("KEYB")
        or ""
    )


class _KISRankingMixin(_KISClientState):
    """Domestic/overseas ranking responsibilities."""

    def _rank_headers(self, tr_id: str) -> dict[str, Any]:
        return {
            "Content-Type": "application/json",
            "authorization": self._access_token,
            "appkey": self.creds.app_key,
            "appsecret": self.creds.app_secret,
            "tr_id": tr_id,
            "custtype": "P",
        }

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

        params = {
            "FID_COND_MRKT_DIV_CODE": market,
            "FID_COND_SCR_DIV_CODE": "20171",
            "FID_INPUT_ISCD": "0000",
            "FID_DIV_CLS_CODE": division_code,
            "FID_BLNG_CLS_CODE": belonging_code,
            "FID_TRGT_CLS_CODE": "000000000",
            "FID_TRGT_EXLS_CLS_CODE": "0000000000",
            "FID_INPUT_PRICE_1": _format_positive_int_filter(min_price),
            "FID_INPUT_PRICE_2": _format_positive_int_filter(max_price),
            "FID_VOL_CNT": _format_positive_int_filter(min_volume),
            "FID_INPUT_DATE_1": "0",
        }

        headers = self._rank_headers(self.creds.volume_rank_tr_id)

        results: list[dict[str, Any]] = []
        tr_cont = ""

        while len(results) < limit:
            hdrs = headers.copy()
            if tr_cont:
                hdrs["tr_cont"] = tr_cont

            # Request with body-level rate limit handling
            data: dict[str, Any] | None = None
            resp: requests.Response | None = None
            for attempt in range(self._max_attempts):
                resp = self._request(
                    "GET", self.creds.volume_rank_url, headers=hdrs, params=params
                )

                # Try to parse JSON body even on non-200 to inspect msg_cd
                parsed = _json_or_none(resp)
                data = _payload_dict(parsed)

                if resp.status_code != 200:
                    msg_cd, msg1 = _error_fields(data)
                    if msg_cd == "EGW00123" and attempt < self._max_attempts - 1:
                        # Token expired on server side: clear, refresh, and retry
                        self._access_token = None
                        self._token_expiry = None
                        self.ensure_token()
                        headers["authorization"] = self._access_token or ""
                        hdrs["authorization"] = self._access_token or ""
                        time.sleep(max(1.0, self._min_interval))
                        continue
                    if attempt < self._max_attempts - 1:
                        time.sleep(1.0)
                        continue
                    if msg_cd:
                        raise KISApiError(
                            f"Volume rank HTTP {resp.status_code}: {msg1} ({resp.text})",
                            msg_cd=msg_cd,
                            msg1=str(msg1),
                            http_status=resp.status_code,
                            context="volume_rank",
                        )
                    raise KISClientError(
                        f"Volume rank HTTP {resp.status_code}: {msg1} ({resp.text})"
                    )

                if data is None:
                    if attempt < self._max_attempts - 1:
                        time.sleep(1.0)
                        continue
                    if parsed is None:
                        raise KISClientError("Volume rank response is not JSON")
                    raise KISClientError(
                        "Volume rank response payload is not an object"
                    )

                if str(data.get("rt_cd")) != "0":
                    msg_cd, msg1 = _error_fields(data)
                    if msg_cd == "EGW00201" and attempt < self._max_attempts - 1:
                        time.sleep(max(1.0, self._min_interval))
                        continue
                    if msg_cd == "EGW00123" and attempt < self._max_attempts - 1:
                        # Token expired according to body: refresh and retry
                        self._access_token = None
                        self._token_expiry = None
                        self.ensure_token()
                        headers["authorization"] = self._access_token or ""
                        hdrs["authorization"] = self._access_token or ""
                        time.sleep(max(1.0, self._min_interval))
                        continue
                    raise KISApiError(
                        f"KIS volume rank error: {msg1}",
                        msg_cd=msg_cd,
                        msg1=msg1,
                        rt_cd=str(data.get("rt_cd") or ""),
                        context="volume_rank",
                    )
                break

            if data is None or resp is None:
                break

            parsed_items: list[dict[str, Any]] = []
            for it in _rank_items(data, "output"):
                parsed_item = self._parse_rank_item(it)
                if parsed_item is not None:
                    parsed_items.append(parsed_item)
            results.extend(parsed_items)

            tr_cont = (resp.headers.get("tr_cont") or "").strip()
            if tr_cont != "M":
                break
            tr_cont = "N"

        return results[:limit]

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

        headers_base = self._rank_headers(tr_id)

        results: list[dict[str, Any]] = []
        tr_cont = ""

        while len(results) < limit:
            data: dict[str, Any] | None = None
            resp: requests.Response | None = None

            for attempt in range(self._max_attempts):
                headers = headers_base.copy()
                if tr_cont:
                    headers["tr_cont"] = tr_cont

                resp = self._request("GET", url, headers=headers, params=request_params)
                parsed = _json_or_none(resp)

                if resp.status_code != 200:
                    error_body = _payload_dict(parsed)
                    msg_cd, msg1 = _error_fields(error_body)
                    if msg_cd == "EGW00123" and attempt < self._max_attempts - 1:
                        self._access_token = None
                        self._token_expiry = None
                        self.ensure_token()
                        headers_base["authorization"] = self._access_token or ""
                        time.sleep(max(1.0, self._min_interval))
                        continue
                    if msg_cd == "EGW00201" and attempt < self._max_attempts - 1:
                        time.sleep(max(1.0, self._min_interval))
                        continue
                    if attempt < self._max_attempts - 1:
                        time.sleep(1.0)
                        continue
                    if msg_cd:
                        raise KISApiError(
                            f"Overseas rank HTTP {resp.status_code}: {resp.text}",
                            msg_cd=msg_cd,
                            msg1=msg1,
                            http_status=resp.status_code,
                            context="overseas_rank",
                        )
                    raise KISClientError(
                        f"Overseas rank HTTP {resp.status_code}: {resp.text}"
                    )

                data = _payload_dict(parsed)
                if data is None:
                    if attempt < self._max_attempts - 1:
                        time.sleep(1.0)
                        continue
                    if parsed is None:
                        raise KISClientError("Overseas rank response is not JSON")
                    raise KISClientError(
                        "Overseas rank response payload is not an object"
                    )

                if str(data.get("rt_cd")) != "0":
                    msg_cd, msg1 = _error_fields(data)
                    if msg_cd == "EGW00201" and attempt < self._max_attempts - 1:
                        time.sleep(max(1.0, self._min_interval))
                        continue
                    if msg_cd == "EGW00123" and attempt < self._max_attempts - 1:
                        self._access_token = None
                        self._token_expiry = None
                        self.ensure_token()
                        headers_base["authorization"] = self._access_token or ""
                        time.sleep(max(1.0, self._min_interval))
                        continue
                    raise KISApiError(
                        f"KIS overseas rank error: {msg1}",
                        msg_cd=msg_cd,
                        msg1=msg1,
                        rt_cd=str(data.get("rt_cd") or ""),
                        context="overseas_rank",
                    )
                break

            if data is None or resp is None:
                break

            added = 0
            for item in _rank_items(data, "output2", "output"):
                results.append(item)
                added += 1
                if len(results) >= limit:
                    break

            if len(results) >= limit:
                break

            resp_tr_cont = (resp.headers.get("tr_cont") or "").strip().upper()
            request_params["KEYB"] = _pagination_key(data)

            # Stop if we cannot make progress.
            if added == 0:
                break

            # KIS pagination: response tr_cont == "M" means more data; request
            # should send tr_cont="N" to continue (see domestic rank usage).
            if resp_tr_cont != "M":
                break
            tr_cont = "N"

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
        price_min: float | None = None,
        price_max: float | None = None,
    ) -> list[dict[str, Any]]:
        params: dict[str, Any] = {
            "EXCD": exchange,
            "NDAY": nday,
            "VOL_RANG": volume_filter,
            "PRC1": _format_positive_int_filter(price_min, empty_when_missing=True),
            "PRC2": _format_positive_int_filter(price_max, empty_when_missing=True),
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
        nday: str = "0",
        volume_filter: str = "0",
    ) -> list[dict[str, Any]]:
        params = {
            "EXCD": exchange,
            "NDAY": nday,
            "VOL_RANG": volume_filter,
        }
        return self._fetch_overseas_rank_items(
            url=self.creds.overseas_market_cap_rank_url(),
            tr_id="HHDFS76350100",
            params=params,
            limit=limit,
        )

    @staticmethod
    def _parse_rank_item(item: dict[str, Any] | None) -> dict[str, Any] | None:
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
