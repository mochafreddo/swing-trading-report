from __future__ import annotations

import datetime as dt
from zoneinfo import ZoneInfo

from sab.signals.eval_index import choose_eval_index


def _build_candle(date: dt.date, close: float = 100.0) -> dict[str, float | str]:
    return {
        "date": date.strftime("%Y%m%d"),
        "open": close,
        "high": close + 1.0,
        "low": close - 1.0,
        "close": close,
        "volume": 1_000_000.0,
    }


def test_choose_eval_index_prefers_exchange_when_currency_conflicts() -> None:
    candles = [
        _build_candle(dt.date(2025, 1, 10), close=100.0),
        _build_candle(dt.date(2025, 1, 13), close=101.0),
    ]
    now = dt.datetime(2025, 1, 13, 15, 0, tzinfo=ZoneInfo("America/New_York"))

    idx, dropped = choose_eval_index(
        candles,
        meta={"currency": "KRW", "exchange": "NAS"},
        now=now,
    )

    assert idx == 0
    assert dropped is True
