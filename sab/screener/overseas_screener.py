from __future__ import annotations

import datetime as dt
from dataclasses import dataclass
from typing import Any

from ..utils.market_time import us_market_status


@dataclass
class ScreenRequest:
    limit: int


@dataclass
class ScreenResult:
    tickers: list[str]
    metadata: dict[str, Any]


class USSimpleScreener:
    """Simple US screener that returns defaults from config.

    This avoids extra API calls; evaluation/filters run later.
    """

    def __init__(self, defaults: list[str]) -> None:
        self._defaults = [t.strip().upper() for t in defaults if t.strip()]

    def screen(self, request: ScreenRequest) -> ScreenResult:
        tickers = self._defaults[: max(0, request.limit)]
        return ScreenResult(
            tickers=tickers,
            metadata={
                "source": "us_defaults",
                "generated_at": dt.datetime.now().isoformat(),
                "market_status": us_market_status(),
            },
        )


__all__ = ["USSimpleScreener", "ScreenRequest", "ScreenResult"]
