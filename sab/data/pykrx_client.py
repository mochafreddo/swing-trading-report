from __future__ import annotations

import datetime as dt
import importlib
from types import ModuleType
from typing import Any, Optional


class PykrxClientError(RuntimeError):
    """Base error for PyKRX client."""


class PykrxNotInstalledError(PykrxClientError):
    """Raised when pykrx package is not available."""


class PykrxClient:
    """Thin wrapper around pykrx.stock daily OHLC fetch."""

    def __init__(self, *, cache_dir: Optional[str] = None) -> None:
        self.cache_dir = cache_dir
        self._stock_module: ModuleType = _import_pykrx_stock()

    # ------------------------------------------------------------------
    def daily_candles(
        self,
        ticker: str,
        *,
        count: int = 120,
        adjusted: bool = True,
    ) -> list[dict[str, Any]]:
        ticker = ticker.strip()
        if not ticker:
            raise PykrxClientError("Ticker is required")

        stock = self._stock_module

        target = max(1, count)
        lookback_days = max(365, int(target * 3))
        end = dt.datetime.now()

        df = None
        attempts = 0
        while attempts < 4:
            start = end - dt.timedelta(days=lookback_days)
            start_str = start.strftime("%Y%m%d")
            end_str = end.strftime("%Y%m%d")
            data = stock.get_market_ohlcv_by_date(
                start_str,
                end_str,
                ticker,
                adjusted=adjusted,
            )
            if data is not None and not data.empty:
                df = data
                break
            lookback_days *= 2
            attempts += 1

        if df is None or df.empty:
            return []

        df = df.sort_index()
        records: list[dict[str, Any]] = []

        def _col(*names: str) -> Any:
            for name in names:
                if name in df.columns:
                    return df[name]
            raise PykrxClientError(f"Missing required column(s): {names}")

        opens = _col("시가", "Open", "open")
        highs = _col("고가", "High", "high")
        lows = _col("저가", "Low", "low")
        closes = _col("종가", "Close", "close")
        volumes = _col("거래량", "Volume", "volume")

        prev_close: float | None = None
        for idx, date_idx in enumerate(df.index):
            row_open = _to_float(opens.iloc[idx])
            row_high = _to_float(highs.iloc[idx])
            row_low = _to_float(lows.iloc[idx])
            row_close = _to_float(closes.iloc[idx])
            row_volume = _to_float(volumes.iloc[idx])

            date_str = _format_date(date_idx)

            diff = float("nan")
            if (
                prev_close is not None
                and prev_close != 0
                and not _is_nan(prev_close)
                and not _is_nan(row_close)
            ):
                diff = row_close - prev_close

            records.append(
                {
                    "date": date_str,
                    "open": row_open,
                    "high": row_high,
                    "low": row_low,
                    "close": row_close,
                    "volume": row_volume,
                    "prev_close_diff": diff,
                }
            )
            prev_close = row_close

        if len(records) > target:
            records = records[-target:]

        return records


def _import_pykrx_stock() -> ModuleType:
    try:
        return importlib.import_module("pykrx.stock")
    except ImportError as exc:  # pragma: no cover - runtime dependency
        raise PykrxNotInstalledError(
            "pykrx is required for PyKRX data provider. Install with 'uv sync --extra pykrx'."
        ) from exc


def _to_float(value: Any) -> float:
    if value is None:
        return float("nan")
    try:
        return float(value)
    except (TypeError, ValueError):
        try:
            return float(str(value).replace(",", ""))
        except (TypeError, ValueError):
            return float("nan")


def _is_nan(value: Any) -> bool:
    try:
        return float(value) != float(value)
    except Exception:
        return False


def _format_date(value: Any) -> str:
    if isinstance(value, dt.datetime):
        return value.strftime("%Y%m%d")
    text = str(value)
    if len(text) >= 10 and text[4] == "-" and text[7] == "-":
        return text[:10].replace("-", "")
    if len(text) == 8 and text.isdigit():
        return text
    return text.replace("-", "")[:8]
