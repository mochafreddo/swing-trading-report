from __future__ import annotations

import datetime as dt
import logging
from collections.abc import Callable
from types import SimpleNamespace
from typing import Any

from sab.data.kis_client import KISClientError
from sab.market_data_pipeline import KisCollectionRequest, collect_market_data_from_kis
from sab.market_data_service import scan_legacy_cache_keys as _scan_legacy_cache_keys


def _build_runtime(
    *,
    kis_client: Any,
    data_provider: str = "kis",
    stale_sessions_kr: int = 9999,
    stale_sessions_us: int = 9999,
) -> SimpleNamespace:
    return SimpleNamespace(
        cfg=SimpleNamespace(
            data_dir="/tmp",
            data_provider=data_provider,
            market_cache_stale_sessions_kr=stale_sessions_kr,
            market_cache_stale_sessions_us=stale_sessions_us,
        ),
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


def _candles_with_last_date(date_key: str) -> list[dict[str, float | str]]:
    return [
        {
            "date": date_key,
            "open": 100.0,
            "high": 101.0,
            "low": 99.0,
            "close": 100.0,
            "volume": 1_000_000.0,
        }
    ]


def _split_symbol_and_suffix(ticker: str) -> tuple[str, str | None]:
    if "." not in ticker:
        return ticker, None
    base, suffix = ticker.rsplit(".", 1)
    return base.strip().upper(), suffix.strip().upper()


def _exchange_from_suffix(suffix: str | None) -> str | None:
    if suffix in {"US", "NASDAQ", "NASD", "NAS"}:
        return "NAS"
    return None


def _collect_market_data_from_kis(
    runtime: Any,
    *,
    tickers: list[str],
    target_bars: int,
    load_json_fn: Callable[[str, str], Any],
    save_json_fn: Callable[[str, str, Any], Any],
    ensure_pykrx_client_fn: Callable[[Any], Any | None],
    split_symbol_and_suffix_fn: Callable[[str], tuple[str, str | None]],
    exchange_from_suffix_fn: Callable[[str | None], str | None],
    get_pykrx_error_fn: Callable[[Any], str | None],
    legacy_cache_keys_fn: Callable[[str, str, str | None], list[str]] | None = None,
    on_candles_applied_fn: Callable[[Any, str, list[dict[str, Any]]], None]
    | None = None,
    now_fn: Callable[[], dt.datetime] | None = None,
) -> None:
    request = KisCollectionRequest(
        tickers=tickers,
        target_bars=target_bars,
        load_json_fn=load_json_fn,
        save_json_fn=save_json_fn,
        ensure_pykrx_client_fn=ensure_pykrx_client_fn,
        split_symbol_and_suffix_fn=split_symbol_and_suffix_fn,
        exchange_from_suffix_fn=exchange_from_suffix_fn,
        get_pykrx_error_fn=get_pykrx_error_fn,
        legacy_cache_keys_fn=legacy_cache_keys_fn,
        on_candles_applied_fn=on_candles_applied_fn,
    )
    collect_market_data_from_kis(runtime, request=request, now_fn=now_fn)


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

    _collect_market_data_from_kis(
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

    _collect_market_data_from_kis(
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

    _collect_market_data_from_kis(
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


def test_collect_market_data_from_kis_ignores_non_list_cache_payload() -> None:
    class _FailingKisClient:
        def daily_candles(self, symbol: str, *, count: int) -> list[dict[str, Any]]:
            raise KISClientError("KIS down")

    runtime = _build_runtime(kis_client=_FailingKisClient())

    _collect_market_data_from_kis(
        runtime,
        tickers=["005930"],
        target_bars=220,
        load_json_fn=lambda _dir, key: (
            {"date": "20250101"} if key == "candles_005930" else None
        ),
        save_json_fn=lambda *_: None,
        ensure_pykrx_client_fn=lambda _: None,
        split_symbol_and_suffix_fn=_split_symbol_and_suffix,
        exchange_from_suffix_fn=_exchange_from_suffix,
        get_pykrx_error_fn=lambda _: None,
    )

    assert "005930" not in runtime.market_data
    assert any("KIS down" in msg for msg in runtime.failures)


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

    _collect_market_data_from_kis(
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

    _collect_market_data_from_kis(
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


def test_collect_market_data_from_kis_uses_kr_cache_within_stale_limit() -> None:
    class _FailingKisClient:
        def daily_candles(self, symbol: str, *, count: int) -> list[dict[str, Any]]:
            raise KISClientError("KIS down")

    cached_candles = _candles_with_last_date("20250107")
    runtime = _build_runtime(kis_client=_FailingKisClient(), stale_sessions_kr=1)

    _collect_market_data_from_kis(
        runtime,
        tickers=["005930"],
        target_bars=220,
        load_json_fn=lambda _dir, key: (
            cached_candles if key == "candles_005930" else None
        ),
        save_json_fn=lambda *_: None,
        ensure_pykrx_client_fn=lambda _: None,
        split_symbol_and_suffix_fn=_split_symbol_and_suffix,
        exchange_from_suffix_fn=_exchange_from_suffix,
        get_pykrx_error_fn=lambda _: None,
        now_fn=lambda: dt.datetime(2025, 1, 8, 7, 0, tzinfo=dt.UTC),
    )

    assert runtime.market_data["005930"] == cached_candles
    assert any("API error, using cached data" in msg for msg in runtime.failures)
    assert any("stale=1/1 KR sessions" in msg for msg in runtime.failures)


def test_collect_market_data_from_kis_rejects_kr_cache_over_stale_limit() -> None:
    class _FailingKisClient:
        def daily_candles(self, symbol: str, *, count: int) -> list[dict[str, Any]]:
            raise KISClientError("KIS down")

    runtime = _build_runtime(kis_client=_FailingKisClient(), stale_sessions_kr=1)

    _collect_market_data_from_kis(
        runtime,
        tickers=["005930"],
        target_bars=220,
        load_json_fn=lambda _dir, key: (
            _candles_with_last_date("20250106") if key == "candles_005930" else None
        ),
        save_json_fn=lambda *_: None,
        ensure_pykrx_client_fn=lambda _: None,
        split_symbol_and_suffix_fn=_split_symbol_and_suffix,
        exchange_from_suffix_fn=_exchange_from_suffix,
        get_pykrx_error_fn=lambda _: None,
        now_fn=lambda: dt.datetime(2025, 1, 8, 7, 0, tzinfo=dt.UTC),
    )

    assert "005930" not in runtime.market_data
    assert any(
        "cache unavailable: stale by 2 KR sessions (max 1)" in msg
        for msg in runtime.failures
    )
    assert not any("API error, using cached data" in msg for msg in runtime.failures)


def test_collect_market_data_from_kis_uses_us_session_based_staleness() -> None:
    class _FailingKisClient:
        def overseas_daily_candles(
            self, *, symbol: str, exchange: str, count: int
        ) -> list[dict[str, Any]]:
            raise KISClientError("KIS down")

        def daily_candles(self, symbol: str, *, count: int) -> list[dict[str, Any]]:
            return []

    runtime = _build_runtime(kis_client=_FailingKisClient(), stale_sessions_us=1)

    _collect_market_data_from_kis(
        runtime,
        tickers=["AAPL.US"],
        target_bars=220,
        load_json_fn=lambda _dir, key: (
            _candles_with_last_date("20250103")
            if key == "candles_overseas_NAS_AAPL"
            else None
        ),
        save_json_fn=lambda *_: None,
        ensure_pykrx_client_fn=lambda _: None,
        split_symbol_and_suffix_fn=_split_symbol_and_suffix,
        exchange_from_suffix_fn=_exchange_from_suffix,
        get_pykrx_error_fn=lambda _: None,
        now_fn=lambda: dt.datetime(2025, 1, 6, 22, 0, tzinfo=dt.UTC),
    )

    assert "AAPL.US" in runtime.market_data
    assert any("stale=1/1 US sessions" in msg for msg in runtime.failures)


def test_collect_market_data_from_kis_rejects_us_cache_over_stale_limit() -> None:
    class _FailingKisClient:
        def overseas_daily_candles(
            self, *, symbol: str, exchange: str, count: int
        ) -> list[dict[str, Any]]:
            raise KISClientError("KIS down")

        def daily_candles(self, symbol: str, *, count: int) -> list[dict[str, Any]]:
            return []

    runtime = _build_runtime(kis_client=_FailingKisClient(), stale_sessions_us=1)

    _collect_market_data_from_kis(
        runtime,
        tickers=["AAPL.US"],
        target_bars=220,
        load_json_fn=lambda _dir, key: (
            _candles_with_last_date("20250103")
            if key == "candles_overseas_NAS_AAPL"
            else None
        ),
        save_json_fn=lambda *_: None,
        ensure_pykrx_client_fn=lambda _: None,
        split_symbol_and_suffix_fn=_split_symbol_and_suffix,
        exchange_from_suffix_fn=_exchange_from_suffix,
        get_pykrx_error_fn=lambda _: None,
        now_fn=lambda: dt.datetime(2025, 1, 7, 22, 0, tzinfo=dt.UTC),
    )

    assert "AAPL.US" not in runtime.market_data
    assert any(
        "cache unavailable: stale by 2 US sessions (max 1)" in msg
        for msg in runtime.failures
    )
    assert not any("API error, using cached data" in msg for msg in runtime.failures)
