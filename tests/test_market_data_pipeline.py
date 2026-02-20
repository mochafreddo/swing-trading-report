from __future__ import annotations

import logging
from types import SimpleNamespace
from typing import Any

from sab.data.kis_client import KISClientError
from sab.market_data_pipeline import collect_market_data_from_kis
from sab.scan_market_data import _scan_legacy_cache_keys


def _build_runtime(*, kis_client: Any, data_provider: str = "kis") -> SimpleNamespace:
    return SimpleNamespace(
        cfg=SimpleNamespace(data_dir="/tmp", data_provider=data_provider),
        logger=logging.getLogger(__name__),
        failures=[],
        market_data={},
        ticker_data_source={},
        pykrx_client=None,
        pykrx_warning_added=False,
        pykrx_import_error=None,
        pykrx_init_error=None,
        kis_client=kis_client,
    )


def _build_candles(count: int = 220) -> list[dict[str, float | str]]:
    candles: list[dict[str, float | str]] = []
    for idx in range(count):
        candles.append(
            {
                "date": f"202501{idx % 30 + 1:02d}",
                "open": 100.0 + idx,
                "high": 101.0 + idx,
                "low": 99.0 + idx,
                "close": 100.0 + idx,
                "volume": 1_000_000.0,
            }
        )
    return candles


def _split_symbol_and_suffix(ticker: str) -> tuple[str, str | None]:
    if "." not in ticker:
        return ticker, None
    base, suffix = ticker.rsplit(".", 1)
    return base.strip().upper(), suffix.strip().upper()


def _exchange_from_suffix(suffix: str | None) -> str | None:
    if suffix in {"US", "NASDAQ", "NASD", "NAS"}:
        return "NAS"
    return None


def test_collect_market_data_from_kis_reads_legacy_cache_and_migrates() -> None:
    class _FailingKisClient:
        def daily_candles(self, symbol: str, *, count: int) -> list[dict[str, Any]]:
            raise KISClientError("KIS down")

    legacy_candles = _build_candles()
    load_keys: list[str] = []
    saved_keys: list[str] = []
    runtime = _build_runtime(kis_client=_FailingKisClient())

    def load_json_fn(_: str, key: str) -> Any:
        load_keys.append(key)
        if key == "candles_AAPL.UNKNOWN":
            return legacy_candles
        return None

    def save_json_fn(_: str, key: str, payload: Any) -> None:
        assert payload
        saved_keys.append(key)

    collect_market_data_from_kis(
        runtime,
        tickers=["AAPL.UNKNOWN"],
        target_bars=220,
        load_json_fn=load_json_fn,
        save_json_fn=save_json_fn,
        ensure_pykrx_client_fn=lambda _: None,
        split_symbol_and_suffix_fn=_split_symbol_and_suffix,
        exchange_from_suffix_fn=_exchange_from_suffix,
        get_pykrx_error_fn=lambda _: None,
        legacy_cache_keys_fn=lambda ticker, _base, exchange: (
            [f"candles_{ticker}"] if exchange is None else []
        ),
    )

    assert runtime.market_data["AAPL.UNKNOWN"] == legacy_candles
    assert runtime.ticker_data_source["AAPL.UNKNOWN"] == "kis"
    assert load_keys[:2] == ["candles_AAPL", "candles_AAPL.UNKNOWN"]
    assert "candles_AAPL" in saved_keys
    assert any("API error, using cached data" in msg for msg in runtime.failures)


def test_collect_market_data_from_kis_adds_fallback_warning_once() -> None:
    class _FailingKisClient:
        def daily_candles(self, symbol: str, *, count: int) -> list[dict[str, Any]]:
            raise KISClientError(f"KIS down for {symbol}")

    class _PykrxClient:
        def daily_candles(self, symbol: str, *, count: int) -> list[dict[str, Any]]:
            return _build_candles(count)

    runtime = _build_runtime(kis_client=_FailingKisClient())

    collect_market_data_from_kis(
        runtime,
        tickers=["005930", "000660"],
        target_bars=220,
        load_json_fn=lambda *_: None,
        save_json_fn=lambda *_: None,
        ensure_pykrx_client_fn=lambda _: _PykrxClient(),
        split_symbol_and_suffix_fn=_split_symbol_and_suffix,
        exchange_from_suffix_fn=_exchange_from_suffix,
        get_pykrx_error_fn=lambda _: None,
    )

    assert runtime.ticker_data_source["005930"] == "pykrx"
    assert runtime.ticker_data_source["000660"] == "pykrx"
    assert runtime.pykrx_warning_added is True
    assert (
        runtime.failures.count(
            "Warning: PyKRX fallback data is end-of-day and may differ from KIS."
        )
        == 1
    )


def test_collect_market_data_from_kis_ignores_cache_migration_write_error() -> None:
    class _FailingKisClient:
        def daily_candles(self, symbol: str, *, count: int) -> list[dict[str, Any]]:
            raise KISClientError("KIS down")

    runtime = _build_runtime(kis_client=_FailingKisClient())
    legacy_candles = _build_candles()

    collect_market_data_from_kis(
        runtime,
        tickers=["AAPL.UNKNOWN"],
        target_bars=220,
        load_json_fn=lambda _dir, key: (
            legacy_candles if key == "candles_AAPL.UNKNOWN" else None
        ),
        save_json_fn=lambda *_: (_ for _ in ()).throw(OSError("disk full")),
        ensure_pykrx_client_fn=lambda _: None,
        split_symbol_and_suffix_fn=_split_symbol_and_suffix,
        exchange_from_suffix_fn=_exchange_from_suffix,
        get_pykrx_error_fn=lambda _: None,
        legacy_cache_keys_fn=lambda ticker, _base, exchange: (
            [f"candles_{ticker}"] if exchange is None else []
        ),
    )

    assert runtime.market_data["AAPL.UNKNOWN"] == legacy_candles
    assert any("Failed to migrate cache key" in message for message in runtime.failures)


def test_collect_market_data_from_kis_uses_canonical_suffix_mapping_fallback() -> None:
    class _KisClient:
        def __init__(self) -> None:
            self.calls: list[tuple[str, str, int]] = []

        def overseas_daily_candles(
            self, *, symbol: str, exchange: str, count: int
        ) -> list[dict[str, Any]]:
            self.calls.append((symbol, exchange, count))
            return _build_candles(count)

        def daily_candles(self, symbol: str, *, count: int) -> list[dict[str, Any]]:
            return []

    kis_client = _KisClient()
    runtime = _build_runtime(kis_client=kis_client)

    collect_market_data_from_kis(
        runtime,
        tickers=["AAPL.NAS-DAQ"],
        target_bars=220,
        load_json_fn=lambda *_: None,
        save_json_fn=lambda *_: None,
        ensure_pykrx_client_fn=lambda _: None,
        split_symbol_and_suffix_fn=_split_symbol_and_suffix,
        exchange_from_suffix_fn=lambda _: None,
        get_pykrx_error_fn=lambda _: None,
    )

    assert kis_client.calls == [("AAPL", "NAS", 220)]
    assert runtime.ticker_data_source["AAPL.NAS-DAQ"] == "kis"


def test_collect_market_data_from_kis_reads_scan_legacy_overseas_cache() -> None:
    class _FailingKisClient:
        def overseas_daily_candles(
            self, *, symbol: str, exchange: str, count: int
        ) -> list[dict[str, Any]]:
            raise KISClientError("KIS down")

        def daily_candles(self, symbol: str, *, count: int) -> list[dict[str, Any]]:
            return []

    legacy_candles = _build_candles()
    load_keys: list[str] = []
    runtime = _build_runtime(kis_client=_FailingKisClient())

    def load_json_fn(_: str, key: str) -> Any:
        load_keys.append(key)
        if key == "candles_AAPL.NAS-DAQ":
            return legacy_candles
        return None

    collect_market_data_from_kis(
        runtime,
        tickers=["AAPL.NAS-DAQ"],
        target_bars=220,
        load_json_fn=load_json_fn,
        save_json_fn=lambda *_: None,
        ensure_pykrx_client_fn=lambda _: None,
        split_symbol_and_suffix_fn=_split_symbol_and_suffix,
        exchange_from_suffix_fn=lambda _: None,
        get_pykrx_error_fn=lambda _: None,
        legacy_cache_keys_fn=_scan_legacy_cache_keys,
    )

    assert runtime.market_data["AAPL.NAS-DAQ"] == legacy_candles
    assert load_keys[:2] == ["candles_overseas_NAS_AAPL", "candles_AAPL.NAS-DAQ"]
    assert any("API error, using cached data" in msg for msg in runtime.failures)
