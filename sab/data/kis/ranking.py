from __future__ import annotations

import time
from typing import Any

import requests  # type: ignore[import-untyped]

from .common import KISClientError, _KISClientState


class _KISRankingMixin(_KISClientState):
    """Domestic/overseas ranking responsibilities."""

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
            data: dict[str, Any] | None = None
            resp: requests.Response | None = None
            for attempt in range(self._max_attempts):
                resp = self._request(
                    "GET", self.creds.volume_rank_url, headers=hdrs, params=params
                )

                # Try to parse JSON body even on non-200 to inspect msg_cd
                try:
                    data = resp.json()
                except ValueError:
                    data = None

                if resp.status_code != 200:
                    msg_cd = (
                        str(data.get("msg_cd") or "") if isinstance(data, dict) else ""
                    )
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

            if data is None or resp is None:
                break

            items = data.get("output") or []
            if isinstance(items, dict):
                items = [items]
            if not isinstance(items, list):
                items = []

            parsed_items: list[dict[str, Any]] = []
            for it in items:
                if not isinstance(it, dict):
                    continue
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
                raise KISClientError(
                    f"Overseas rank HTTP {resp.status_code}: {resp.text}"
                )

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

            added = 0
            for item in items:
                if not isinstance(item, dict):
                    continue
                results.append(item)
                added += 1
                if len(results) >= limit:
                    break

            if len(results) >= limit:
                break

            resp_tr_cont = (resp.headers.get("tr_cont") or "").strip().upper()
            output1 = data.get("output1") or {}
            if isinstance(output1, list) and output1:
                output1 = output1[0]
            if not isinstance(output1, dict):
                output1 = {}
            keyb = (
                data.get("keyb")
                or data.get("KEYB")
                or output1.get("keyb")
                or output1.get("KEYB")
                or ""
            )
            request_params["KEYB"] = keyb

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
        def _price(val: float | None) -> str:
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
