from __future__ import annotations

import datetime as dt
import logging
from dataclasses import dataclass
from typing import Any

import requests  # type: ignore[import-untyped]

# Preserve legacy logger namespace for stable log filtering in tests/ops.
logger = logging.getLogger("sab.data.kis_client")
_KST = dt.timezone(dt.timedelta(hours=9), name="KST")


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
        return (
            f"{self.base_url.rstrip('/')}/uapi/domestic-stock/v1/quotations/volume-rank"
        )

    @property
    def domestic_price_detail_url(self) -> str:
        return (
            f"{self.base_url.rstrip('/')}/uapi/domestic-stock/v1/quotations/"
            "inquire-price"
        )

    @property
    def volume_rank_tr_id(self) -> str:
        return "FHPST01710000"

    # Overseas
    @property
    def overseas_candle_url(self) -> str:
        # KIS Overseas period (daily) price endpoint
        # v1_해외주식-010: /overseas-price/v1/quotations/dailyprice
        return (
            f"{self.base_url.rstrip('/')}/uapi/overseas-price/v1/quotations/dailyprice"
        )

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


class _KISClientState:
    """Shared mutable state shape used by KIS mixins."""

    creds: KISCredentials
    session: requests.Session
    _access_token: str | None
    _token_expiry: dt.datetime | None
    _cache_dir: str | None
    _token_cache_key: str
    cache_status: str | None
    _max_attempts: int
    _min_interval: float
    _last_request_at: dt.datetime | None

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
        raise NotImplementedError

    def ensure_token(self) -> None:
        raise NotImplementedError
