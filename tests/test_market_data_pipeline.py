from __future__ import annotations

import datetime as dt
import logging
from collections.abc import Callable
from types import SimpleNamespace
from typing import Any, cast

import pytest
from sab.data.kis_client import KISClientError
from sab.market_data_common import build_market_data_dependencies
from sab.market_data_pipeline import (
    KisCollectionRequest,
    PykrxCollectionRequest,
    collect_market_data_from_kis,
    collect_market_data_from_pykrx,
)
from sab.market_data_service import (
    ScanMarketData,
    SellMarketData,
)
from sab.market_data_service import (
    scan_legacy_cache_keys as _scan_legacy_cache_keys,
)


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
        raw_market_data={},
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


def _cache_key(
    base_symbol: str,
    *,
    exchange: str | None = None,
    adjusted: bool = True,
) -> str:
    prefix = "adj" if adjusted else "raw"
    if exchange:
        return f"candles_overseas_{prefix}_{exchange}_{base_symbol}"
    return f"candles_{prefix}_{base_symbol}"


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
    adjusted: bool = True,
) -> None:
    request = KisCollectionRequest(
        tickers=tickers,
        target_bars=target_bars,
        adjusted=adjusted,
        load_json_fn=load_json_fn,
        save_json_fn=save_json_fn,
        ensure_pykrx_client_fn=ensure_pykrx_client_fn,
        split_symbol_and_suffix_fn=split_symbol_and_suffix_fn,
        exchange_from_suffix_fn=exchange_from_suffix_fn,
        get_pykrx_error_fn=get_pykrx_error_fn,
        legacy_cache_keys_fn=legacy_cache_keys_fn,
        on_candles_applied_fn=on_candles_applied_fn,
    )
    collect_market_data_from_kis(
        runtime,
        request=request,
        now_fn=now_fn or (lambda: dt.datetime(2025, 1, 10, 22, 0, tzinfo=dt.UTC)),
    )


def _collect_market_data_from_pykrx(
    runtime: Any,
    *,
    tickers: list[str],
    target_bars: int,
    load_json_fn: Callable[[str, str], Any],
    save_json_fn: Callable[[str, str, Any], Any],
    split_symbol_and_suffix_fn: Callable[[str], tuple[str, str | None]],
    exchange_from_suffix_fn: Callable[[str | None], str | None],
    on_candles_applied_fn: Callable[[Any, str, list[dict[str, Any]]], None]
    | None = None,
    now_fn: Callable[[], dt.datetime] | None = None,
    adjusted: bool = True,
) -> None:
    request = PykrxCollectionRequest(
        tickers=tickers,
        target_bars=target_bars,
        load_json_fn=load_json_fn,
        save_json_fn=save_json_fn,
        split_symbol_and_suffix_fn=split_symbol_and_suffix_fn,
        exchange_from_suffix_fn=exchange_from_suffix_fn,
        PykrxClientErrorCls=RuntimeError,
        adjusted=adjusted,
        on_candles_applied_fn=on_candles_applied_fn,
    )
    collect_market_data_from_pykrx(
        runtime,
        request=request,
        now_fn=now_fn or (lambda: dt.datetime(2025, 1, 10, 22, 0, tzinfo=dt.UTC)),
    )


def test_collect_market_data_from_kis_reads_legacy_cache_and_migrates() -> None:
    class _FailingKisClient:
        def __init__(self) -> None:
            self.calls = 0

        def daily_candles(self, symbol: str, *, count: int) -> list[dict[str, Any]]:
            self.calls += 1
            raise KISClientError("KIS down")

    legacy_candles = _build_candles()
    load_keys: list[str] = []
    saved_keys: list[str] = []
    kis_client = _FailingKisClient()
    runtime = _build_runtime(kis_client=kis_client)

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
    assert load_keys[:2] == [_cache_key("AAPL"), "candles_AAPL.UNKNOWN"]
    assert _cache_key("AAPL") in saved_keys
    assert kis_client.calls == 0
    assert runtime.failures == []


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


def test_collect_market_data_from_kis_continues_when_cache_persist_fails() -> None:
    class _KisClient:
        def daily_candles(self, symbol: str, *, count: int) -> list[dict[str, Any]]:
            assert symbol == "005930"
            return _build_candles(count)

    runtime = _build_runtime(kis_client=_KisClient())

    _collect_market_data_from_kis(
        runtime,
        tickers=["005930"],
        target_bars=220,
        load_json_fn=lambda *_: None,
        save_json_fn=lambda *_: (_ for _ in ()).throw(OSError("disk full")),
        ensure_pykrx_client_fn=lambda _: None,
        split_symbol_and_suffix_fn=_split_symbol_and_suffix,
        exchange_from_suffix_fn=_exchange_from_suffix,
        get_pykrx_error_fn=lambda _: None,
    )

    assert "005930" in runtime.market_data
    assert runtime.ticker_data_source["005930"] == "kis"
    assert any(
        "Failed to persist cache" in message
        and "005930" in message
        and _cache_key("005930") in message
        and "disk full" in message
        for message in runtime.failures
    )


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
            {"date": "20250101"} if key == _cache_key("005930") else None
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
        def __init__(self) -> None:
            self.calls = 0

        def overseas_daily_candles(
            self, *, symbol: str, exchange: str, count: int
        ) -> list[dict[str, Any]]:
            self.calls += 1
            raise KISClientError("KIS down")

        def daily_candles(self, symbol: str, *, count: int) -> list[dict[str, Any]]:
            return []

    legacy_candles = _build_candles()
    load_keys: list[str] = []
    kis_client = _FailingKisClient()
    runtime = _build_runtime(kis_client=kis_client)

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
    assert load_keys[:2] == [_cache_key("AAPL", exchange="NAS"), "candles_AAPL.NAS-DAQ"]
    assert kis_client.calls == 0
    assert runtime.failures == []


def test_collect_market_data_from_kis_uses_kr_cache_within_stale_limit() -> None:
    class _FailingKisClient:
        def __init__(self) -> None:
            self.calls = 0

        def daily_candles(self, symbol: str, *, count: int) -> list[dict[str, Any]]:
            self.calls += 1
            raise KISClientError("KIS down")

    cached_candles = _candles_with_last_date("20250107")
    kis_client = _FailingKisClient()
    runtime = _build_runtime(kis_client=kis_client, stale_sessions_kr=1)

    _collect_market_data_from_kis(
        runtime,
        tickers=["005930"],
        target_bars=220,
        load_json_fn=lambda _dir, key: (
            cached_candles if key == _cache_key("005930") else None
        ),
        save_json_fn=lambda *_: None,
        ensure_pykrx_client_fn=lambda _: None,
        split_symbol_and_suffix_fn=_split_symbol_and_suffix,
        exchange_from_suffix_fn=_exchange_from_suffix,
        get_pykrx_error_fn=lambda _: None,
        now_fn=lambda: dt.datetime(2025, 1, 8, 7, 0, tzinfo=dt.UTC),
    )

    assert runtime.market_data["005930"] == cached_candles
    assert kis_client.calls == 1
    assert runtime.failures == []


def test_collect_market_data_from_kis_refreshes_api_when_cache_is_stale() -> None:
    class _KisClient:
        def __init__(self) -> None:
            self.calls = 0

        def daily_candles(self, symbol: str, *, count: int) -> list[dict[str, Any]]:
            self.calls += 1
            assert symbol == "005930"
            assert count == 220
            return _candles_with_last_date("20250108")

    cached_candles = _candles_with_last_date("20250107")
    fresh_candles = _candles_with_last_date("20250108")
    kis_client = _KisClient()
    runtime = _build_runtime(kis_client=kis_client, stale_sessions_kr=1)

    _collect_market_data_from_kis(
        runtime,
        tickers=["005930"],
        target_bars=220,
        load_json_fn=lambda _dir, key: (
            cached_candles if key == _cache_key("005930") else None
        ),
        save_json_fn=lambda *_: None,
        ensure_pykrx_client_fn=lambda _: None,
        split_symbol_and_suffix_fn=_split_symbol_and_suffix,
        exchange_from_suffix_fn=_exchange_from_suffix,
        get_pykrx_error_fn=lambda _: None,
        now_fn=lambda: dt.datetime(2025, 1, 8, 7, 0, tzinfo=dt.UTC),
    )

    assert kis_client.calls == 1
    assert runtime.market_data["005930"] == fresh_candles
    assert runtime.failures == []


def test_collect_market_data_from_kis_rejects_stale_provider_response() -> None:
    class _KisClient:
        def daily_candles(self, symbol: str, *, count: int) -> list[dict[str, Any]]:
            assert symbol == "005930"
            assert count == 220
            return _candles_with_last_date("20250107")

    saved_keys: list[str] = []
    runtime = _build_runtime(kis_client=_KisClient(), stale_sessions_kr=0)

    _collect_market_data_from_kis(
        runtime,
        tickers=["005930"],
        target_bars=220,
        load_json_fn=lambda *_: None,
        save_json_fn=lambda _dir, key, payload: saved_keys.append(key),
        ensure_pykrx_client_fn=lambda _: None,
        split_symbol_and_suffix_fn=_split_symbol_and_suffix,
        exchange_from_suffix_fn=_exchange_from_suffix,
        get_pykrx_error_fn=lambda _: None,
        now_fn=lambda: dt.datetime(2025, 1, 8, 7, 0, tzinfo=dt.UTC),
    )

    assert "005930" not in runtime.market_data
    assert saved_keys == []
    assert any(
        "Provider returned stale candles" in msg
        and "stale by 1 KR sessions (max 0)" in msg
        for msg in runtime.failures
    )


def test_collect_market_data_from_kis_uses_cache_when_provider_refresh_is_stale() -> (
    None
):
    class _KisClient:
        def daily_candles(self, symbol: str, *, count: int) -> list[dict[str, Any]]:
            assert symbol == "005930"
            assert count == 220
            return [
                {
                    "date": "20250107",
                    "open": 200.0,
                    "high": 201.0,
                    "low": 199.0,
                    "close": 200.0,
                    "volume": 2_000_000.0,
                }
            ]

    cached_candles = _candles_with_last_date("20250107")
    saved_keys: list[str] = []
    runtime = _build_runtime(kis_client=_KisClient(), stale_sessions_kr=1)

    _collect_market_data_from_kis(
        runtime,
        tickers=["005930"],
        target_bars=220,
        load_json_fn=lambda _dir, key: (
            cached_candles if key == _cache_key("005930") else None
        ),
        save_json_fn=lambda _dir, key, payload: saved_keys.append(key),
        ensure_pykrx_client_fn=lambda _: None,
        split_symbol_and_suffix_fn=_split_symbol_and_suffix,
        exchange_from_suffix_fn=_exchange_from_suffix,
        get_pykrx_error_fn=lambda _: None,
        now_fn=lambda: dt.datetime(2025, 1, 8, 7, 0, tzinfo=dt.UTC),
    )

    assert runtime.market_data["005930"] == cached_candles
    assert saved_keys == []


def test_collect_market_data_from_kis_applies_stale_cache_not_rejected_provider() -> (
    None
):
    class _KisClient:
        def daily_candles(self, symbol: str, *, count: int) -> list[dict[str, Any]]:
            assert symbol == "005930"
            assert count == 220
            return [
                {
                    "date": "20250107",
                    "open": 200.0,
                    "high": 201.0,
                    "low": 199.0,
                    "close": 200.0,
                    "volume": 2_000_000.0,
                }
            ]

    cached_candles = _candles_with_last_date("20250107")
    applied: list[tuple[str, list[dict[str, Any]]]] = []
    runtime = _build_runtime(kis_client=_KisClient(), stale_sessions_kr=1)

    _collect_market_data_from_kis(
        runtime,
        tickers=["005930"],
        target_bars=220,
        load_json_fn=lambda _dir, key: (
            cached_candles if key == _cache_key("005930") else None
        ),
        save_json_fn=lambda *_: None,
        ensure_pykrx_client_fn=lambda _: None,
        split_symbol_and_suffix_fn=_split_symbol_and_suffix,
        exchange_from_suffix_fn=_exchange_from_suffix,
        get_pykrx_error_fn=lambda _: None,
        on_candles_applied_fn=lambda _runtime, ticker, candles: applied.append(
            (ticker, candles)
        ),
        now_fn=lambda: dt.datetime(2025, 1, 8, 7, 0, tzinfo=dt.UTC),
    )

    assert runtime.market_data["005930"] == cached_candles
    assert applied == [("005930", cached_candles)]
    assert runtime.failures == []


def test_collect_market_data_from_kis_uses_stale_cache_when_provider_has_no_data() -> (
    None
):
    class _KisClient:
        def __init__(self) -> None:
            self.calls = 0

        def daily_candles(self, symbol: str, *, count: int) -> list[dict[str, Any]]:
            assert symbol == "005930"
            assert count == 220
            self.calls += 1
            return []

    cached_candles = _candles_with_last_date("20250107")
    kis_client = _KisClient()
    runtime = _build_runtime(kis_client=kis_client, stale_sessions_kr=1)

    _collect_market_data_from_kis(
        runtime,
        tickers=["005930"],
        target_bars=220,
        load_json_fn=lambda _dir, key: (
            cached_candles if key == _cache_key("005930") else None
        ),
        save_json_fn=lambda *_: None,
        ensure_pykrx_client_fn=lambda _: pytest.fail(
            "PyKRX fallback should only run for KIS exceptions"
        ),
        split_symbol_and_suffix_fn=_split_symbol_and_suffix,
        exchange_from_suffix_fn=_exchange_from_suffix,
        get_pykrx_error_fn=lambda _: None,
        now_fn=lambda: dt.datetime(2025, 1, 8, 7, 0, tzinfo=dt.UTC),
    )

    assert kis_client.calls == 1
    assert runtime.market_data["005930"] == cached_candles
    assert runtime.ticker_data_source["005930"] == "kis"
    assert runtime.failures == []


@pytest.mark.parametrize(
    ("provider_candles", "expected_failure"),
    [
        ([], "No candle data returned"),
        (_candles_with_last_date("20250107"), "Provider returned stale candles"),
        (
            [
                {
                    "date": "20250107",
                    "open": 100.0,
                    "high": 101.0,
                    "low": 99.0,
                    "close": float("nan"),
                    "volume": 1_000_000.0,
                }
            ],
            "No complete and finite candle data returned",
        ),
    ],
)
def test_collect_market_data_from_kis_does_not_try_pykrx_for_non_exception_rejections(
    provider_candles: list[dict[str, Any]],
    expected_failure: str,
) -> None:
    class _KisClient:
        def daily_candles(self, symbol: str, *, count: int) -> list[dict[str, Any]]:
            assert symbol == "005930"
            assert count == 220
            return provider_candles

    runtime = _build_runtime(kis_client=_KisClient(), stale_sessions_kr=0)

    _collect_market_data_from_kis(
        runtime,
        tickers=["005930"],
        target_bars=220,
        load_json_fn=lambda *_: None,
        save_json_fn=lambda *_: None,
        ensure_pykrx_client_fn=lambda _: pytest.fail(
            "PyKRX fallback should only run for KIS exceptions"
        ),
        split_symbol_and_suffix_fn=_split_symbol_and_suffix,
        exchange_from_suffix_fn=_exchange_from_suffix,
        get_pykrx_error_fn=lambda _: None,
        now_fn=lambda: dt.datetime(2025, 1, 8, 7, 0, tzinfo=dt.UTC),
    )

    assert "005930" not in runtime.market_data
    assert any(expected_failure in message for message in runtime.failures)


def test_collect_market_data_from_kis_uses_cache_when_pykrx_fallback_is_stale() -> None:
    class _FailingKisClient:
        def daily_candles(self, symbol: str, *, count: int) -> list[dict[str, Any]]:
            raise KISClientError(f"KIS down for {symbol}")

    class _PykrxClient:
        def daily_candles(self, ticker: str, *, count: int) -> list[dict[str, Any]]:
            assert ticker == "005930"
            assert count == 220
            return _candles_with_last_date("20250107")

    cached_candles = _candles_with_last_date("20250107")
    runtime = _build_runtime(kis_client=_FailingKisClient(), stale_sessions_kr=1)

    _collect_market_data_from_kis(
        runtime,
        tickers=["005930"],
        target_bars=220,
        load_json_fn=lambda _dir, key: (
            cached_candles if key == _cache_key("005930") else None
        ),
        save_json_fn=lambda *_: None,
        ensure_pykrx_client_fn=lambda _: _PykrxClient(),
        split_symbol_and_suffix_fn=_split_symbol_and_suffix,
        exchange_from_suffix_fn=_exchange_from_suffix,
        get_pykrx_error_fn=lambda _: None,
        now_fn=lambda: dt.datetime(2025, 1, 8, 7, 0, tzinfo=dt.UTC),
    )

    assert runtime.market_data["005930"] == cached_candles
    assert runtime.ticker_data_source["005930"] == "kis"
    assert runtime.pykrx_warning_added is False
    assert runtime.failures == []


def test_collect_market_data_from_kis_rejects_stale_pykrx_fallback_without_cache() -> (
    None
):
    class _FailingKisClient:
        def daily_candles(self, symbol: str, *, count: int) -> list[dict[str, Any]]:
            raise KISClientError(f"KIS down for {symbol}")

    class _PykrxClient:
        def daily_candles(self, ticker: str, *, count: int) -> list[dict[str, Any]]:
            assert ticker == "005930"
            assert count == 220
            return _candles_with_last_date("20250107")

    runtime = _build_runtime(kis_client=_FailingKisClient(), stale_sessions_kr=0)

    _collect_market_data_from_kis(
        runtime,
        tickers=["005930"],
        target_bars=220,
        load_json_fn=lambda *_: None,
        save_json_fn=lambda *_: None,
        ensure_pykrx_client_fn=lambda _: _PykrxClient(),
        split_symbol_and_suffix_fn=_split_symbol_and_suffix,
        exchange_from_suffix_fn=_exchange_from_suffix,
        get_pykrx_error_fn=lambda _: None,
        now_fn=lambda: dt.datetime(2025, 1, 8, 7, 0, tzinfo=dt.UTC),
    )

    assert "005930" not in runtime.market_data
    assert runtime.pykrx_warning_added is False
    assert any(
        "PyKRX fallback unavailable: PyKRX returned stale candles" in msg
        for msg in runtime.failures
    )


def test_collect_market_data_from_kis_uses_cache_without_refresh_when_fresh() -> None:
    class _KisClient:
        def __init__(self) -> None:
            self.calls = 0

        def daily_candles(self, symbol: str, *, count: int) -> list[dict[str, Any]]:
            self.calls += 1
            assert symbol == "005930"
            assert count == 220
            return _candles_with_last_date("20250108")

    cached_candles = _candles_with_last_date("20250107")
    kis_client = _KisClient()
    runtime = _build_runtime(kis_client=kis_client, stale_sessions_kr=1)

    _collect_market_data_from_kis(
        runtime,
        tickers=["005930"],
        target_bars=220,
        load_json_fn=lambda _dir, key: (
            cached_candles if key == _cache_key("005930") else None
        ),
        save_json_fn=lambda *_: None,
        ensure_pykrx_client_fn=lambda _: None,
        split_symbol_and_suffix_fn=_split_symbol_and_suffix,
        exchange_from_suffix_fn=_exchange_from_suffix,
        get_pykrx_error_fn=lambda _: None,
        now_fn=lambda: dt.datetime(2025, 1, 8, 5, 0, tzinfo=dt.UTC),
    )

    assert kis_client.calls == 0
    assert runtime.market_data["005930"] == cached_candles
    assert runtime.failures == []


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
            _candles_with_last_date("20250106") if key == _cache_key("005930") else None
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
        def __init__(self) -> None:
            self.calls = 0

        def overseas_daily_candles(
            self, *, symbol: str, exchange: str, count: int
        ) -> list[dict[str, Any]]:
            self.calls += 1
            raise KISClientError("KIS down")

        def daily_candles(self, symbol: str, *, count: int) -> list[dict[str, Any]]:
            return []

    kis_client = _FailingKisClient()
    runtime = _build_runtime(kis_client=kis_client, stale_sessions_us=1)

    _collect_market_data_from_kis(
        runtime,
        tickers=["AAPL.US"],
        target_bars=220,
        load_json_fn=lambda _dir, key: (
            _candles_with_last_date("20250103")
            if key == _cache_key("AAPL", exchange="NAS")
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
    assert kis_client.calls == 1
    assert runtime.failures == []


def test_collect_market_data_from_kis_honors_us_early_close_for_staleness(
    tmp_path,
) -> None:
    class _FailingKisClient:
        def __init__(self) -> None:
            self.calls = 0

        def overseas_daily_candles(
            self, *, symbol: str, exchange: str, count: int
        ) -> list[dict[str, Any]]:
            self.calls += 1
            raise KISClientError("KIS down")

        def daily_candles(self, symbol: str, *, count: int) -> list[dict[str, Any]]:
            return []

    data_dir = tmp_path.as_posix()
    (tmp_path / "holidays_us.json").write_text(
        '{"20251224": {"note": "Early close 13:00 ET", "is_open": true}}',
        encoding="utf-8",
    )

    kis_client = _FailingKisClient()
    runtime = _build_runtime(kis_client=kis_client, stale_sessions_us=0)
    runtime.cfg.data_dir = data_dir

    _collect_market_data_from_kis(
        runtime,
        tickers=["AAPL.US"],
        target_bars=220,
        load_json_fn=lambda _dir, key: (
            _candles_with_last_date("20251224")
            if key == _cache_key("AAPL", exchange="NAS")
            else None
        ),
        save_json_fn=lambda *_: None,
        ensure_pykrx_client_fn=lambda _: None,
        split_symbol_and_suffix_fn=_split_symbol_and_suffix,
        exchange_from_suffix_fn=_exchange_from_suffix,
        get_pykrx_error_fn=lambda _: None,
        now_fn=lambda: dt.datetime(2025, 12, 24, 19, 30, tzinfo=dt.UTC),
    )

    assert "AAPL.US" in runtime.market_data
    assert kis_client.calls == 0
    assert runtime.failures == []


def test_collect_market_data_from_kis_calls_api_when_cache_stale() -> None:
    class _KisClient:
        def __init__(self) -> None:
            self.calls = 0

        def daily_candles(self, symbol: str, *, count: int) -> list[dict[str, Any]]:
            self.calls += 1
            return _build_candles(count)

    kis_client = _KisClient()
    runtime = _build_runtime(kis_client=kis_client, stale_sessions_kr=1)

    _collect_market_data_from_kis(
        runtime,
        tickers=["005930"],
        target_bars=220,
        load_json_fn=lambda _dir, key: (
            _candles_with_last_date("20250106") if key == _cache_key("005930") else None
        ),
        save_json_fn=lambda *_: None,
        ensure_pykrx_client_fn=lambda _: None,
        split_symbol_and_suffix_fn=_split_symbol_and_suffix,
        exchange_from_suffix_fn=_exchange_from_suffix,
        get_pykrx_error_fn=lambda _: None,
        now_fn=lambda: dt.datetime(2025, 1, 8, 7, 0, tzinfo=dt.UTC),
    )

    assert kis_client.calls == 1
    assert "005930" in runtime.market_data


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
            if key == _cache_key("AAPL", exchange="NAS")
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


def test_collect_market_data_from_kis_uses_raw_cache_key_when_adjusted_false() -> None:
    class _KisClient:
        def __init__(self) -> None:
            self.calls = 0

        def daily_candles(self, symbol: str, *, count: int) -> list[dict[str, Any]]:
            self.calls += 1
            del symbol
            del count
            return _candles_with_last_date("20250108")

    queried_keys: list[str] = []
    runtime = _build_runtime(kis_client=_KisClient(), stale_sessions_kr=1)
    cached_candles = _candles_with_last_date("20250107")

    def load_json_fn(_: str, key: str) -> Any:
        queried_keys.append(key)
        if key == _cache_key("005930", adjusted=False):
            return cached_candles
        return None

    _collect_market_data_from_kis(
        runtime,
        tickers=["005930"],
        target_bars=220,
        adjusted=False,
        load_json_fn=load_json_fn,
        save_json_fn=lambda *_: None,
        ensure_pykrx_client_fn=lambda _: None,
        split_symbol_and_suffix_fn=_split_symbol_and_suffix,
        exchange_from_suffix_fn=_exchange_from_suffix,
        get_pykrx_error_fn=lambda _: None,
        now_fn=lambda: dt.datetime(2025, 1, 8, 5, 0, tzinfo=dt.UTC),
    )

    assert queried_keys[0] == _cache_key("005930", adjusted=False)
    assert _cache_key("005930", adjusted=True) not in queried_keys
    assert runtime.market_data["005930"] == cached_candles


def test_collect_market_data_from_kis_drops_intraday_incomplete_candle_on_save() -> (
    None
):
    class _KisClient:
        def daily_candles(self, symbol: str, *, count: int) -> list[dict[str, Any]]:
            del symbol
            del count
            return [
                {
                    "date": "20250107",
                    "open": 100.0,
                    "high": 101.0,
                    "low": 99.0,
                    "close": 100.0,
                    "volume": 1_000_000.0,
                },
                {
                    "date": "20250108",
                    "open": 101.0,
                    "high": 102.0,
                    "low": 100.0,
                    "close": 101.0,
                    "volume": 1_100_000.0,
                },
            ]

    saved_payloads: dict[str, list[dict[str, Any]]] = {}
    runtime = _build_runtime(kis_client=_KisClient(), stale_sessions_kr=1)

    _collect_market_data_from_kis(
        runtime,
        tickers=["005930"],
        target_bars=220,
        load_json_fn=lambda *_: None,
        save_json_fn=lambda _dir, key, payload: saved_payloads.setdefault(key, payload),
        ensure_pykrx_client_fn=lambda _: None,
        split_symbol_and_suffix_fn=_split_symbol_and_suffix,
        exchange_from_suffix_fn=_exchange_from_suffix,
        get_pykrx_error_fn=lambda _: None,
        now_fn=lambda: dt.datetime(2025, 1, 8, 5, 0, tzinfo=dt.UTC),
    )

    assert runtime.market_data["005930"] == [_candles_with_last_date("20250107")[0]]
    assert saved_payloads[_cache_key("005930")] == [
        _candles_with_last_date("20250107")[0]
    ]


def test_collect_market_data_from_kis_sanitizes_cached_candles_before_reuse() -> None:
    class _KisClient:
        def daily_candles(self, symbol: str, *, count: int) -> list[dict[str, Any]]:
            raise AssertionError(f"unexpected provider fetch for {symbol} ({count})")

    saved_payloads: dict[str, list[dict[str, Any]]] = {}
    runtime = _build_runtime(kis_client=_KisClient(), stale_sessions_kr=1)
    cached_candles = [
        {
            "date": "20250106",
            "open": 100.0,
            "high": 101.0,
            "low": 99.0,
            "close": 100.0,
            "volume": 1_000_000.0,
        },
        {
            "date": "20250106",
            "open": 101.0,
            "high": 102.0,
            "low": 100.0,
            "close": float("nan"),
            "volume": 1_100_000.0,
        },
    ]

    _collect_market_data_from_kis(
        runtime,
        tickers=["005930"],
        target_bars=220,
        load_json_fn=lambda _dir, key: (
            cached_candles if key == _cache_key("005930") else None
        ),
        save_json_fn=lambda _dir, key, payload: saved_payloads.setdefault(key, payload),
        ensure_pykrx_client_fn=lambda _: None,
        split_symbol_and_suffix_fn=_split_symbol_and_suffix,
        exchange_from_suffix_fn=_exchange_from_suffix,
        get_pykrx_error_fn=lambda _: None,
        now_fn=lambda: dt.datetime(2025, 1, 7, 5, 0, tzinfo=dt.UTC),
    )

    assert runtime.market_data["005930"] == [_candles_with_last_date("20250106")[0]]
    assert saved_payloads[_cache_key("005930")] == [
        _candles_with_last_date("20250106")[0]
    ]


def test_collect_market_data_from_kis_does_not_persist_fully_invalid_provider_candles() -> (
    None
):
    class _KisClient:
        def daily_candles(self, symbol: str, *, count: int) -> list[dict[str, Any]]:
            del symbol
            del count
            return [
                {
                    "date": "20250106",
                    "open": 100.0,
                    "high": 101.0,
                    "low": 99.0,
                    "close": float("nan"),
                    "volume": 1_000_000.0,
                },
                {
                    "date": "invalid-date",
                    "open": 100.0,
                    "high": 101.0,
                    "low": 99.0,
                    "close": 100.0,
                    "volume": float("inf"),
                },
            ]

    saved_payloads: dict[str, list[dict[str, Any]]] = {}
    runtime = _build_runtime(kis_client=_KisClient(), stale_sessions_kr=1)

    _collect_market_data_from_kis(
        runtime,
        tickers=["005930"],
        target_bars=220,
        load_json_fn=lambda *_: None,
        save_json_fn=lambda _dir, key, payload: saved_payloads.setdefault(key, payload),
        ensure_pykrx_client_fn=lambda _: None,
        split_symbol_and_suffix_fn=_split_symbol_and_suffix,
        exchange_from_suffix_fn=_exchange_from_suffix,
        get_pykrx_error_fn=lambda _: None,
        now_fn=lambda: dt.datetime(2025, 1, 7, 5, 0, tzinfo=dt.UTC),
    )

    assert "005930" not in runtime.market_data
    assert saved_payloads == {}
    assert any(
        "No complete and finite candle data returned" in message
        for message in runtime.failures
    )


def test_collect_market_data_from_kis_passes_adjusted_flag_to_provider() -> None:
    class _KisClient:
        def __init__(self) -> None:
            self.adjusted_flags: list[bool] = []

        def daily_candles(
            self, symbol: str, *, count: int, adjusted: bool = True
        ) -> list[dict[str, Any]]:
            self.adjusted_flags.append(adjusted)
            return _build_candles(count)

    kis_client = _KisClient()
    runtime = _build_runtime(kis_client=kis_client)

    _collect_market_data_from_kis(
        runtime,
        tickers=["005930"],
        target_bars=220,
        load_json_fn=lambda *_: None,
        save_json_fn=lambda *_: None,
        ensure_pykrx_client_fn=lambda _: None,
        split_symbol_and_suffix_fn=_split_symbol_and_suffix,
        exchange_from_suffix_fn=_exchange_from_suffix,
        get_pykrx_error_fn=lambda _: None,
        adjusted=False,
    )

    assert kis_client.adjusted_flags == [False]


def test_collect_market_data_from_pykrx_passes_adjusted_flag_to_provider() -> None:
    class _PykrxClient:
        def __init__(self) -> None:
            self.adjusted_flags: list[bool] = []

        def daily_candles(
            self, ticker: str, *, count: int, adjusted: bool = True
        ) -> list[dict[str, Any]]:
            self.adjusted_flags.append(adjusted)
            return _build_candles(count)

    pykrx_client = _PykrxClient()
    runtime = _build_runtime(kis_client=None, data_provider="pykrx")
    runtime.pykrx_client = pykrx_client

    request: PykrxCollectionRequest[Any] = PykrxCollectionRequest(
        tickers=["005930"],
        target_bars=220,
        load_json_fn=lambda *_: None,
        save_json_fn=lambda *_: None,
        split_symbol_and_suffix_fn=_split_symbol_and_suffix,
        exchange_from_suffix_fn=_exchange_from_suffix,
        adjusted=False,
        PykrxClientErrorCls=RuntimeError,
    )
    collect_market_data_from_pykrx(runtime, request=request)

    assert pykrx_client.adjusted_flags == [False]


def test_collect_market_data_from_pykrx_rejects_invalid_candles() -> None:
    class _PykrxClient:
        def daily_candles(
            self, ticker: str, *, count: int, adjusted: bool = True
        ) -> list[dict[str, Any]]:
            del ticker
            del count
            del adjusted
            return [
                {
                    "date": "20250106",
                    "open": 100.0,
                    "high": 101.0,
                    "low": 99.0,
                    "close": float("nan"),
                    "volume": 1_000_000.0,
                }
            ]

    runtime = _build_runtime(kis_client=None, data_provider="pykrx")
    runtime.pykrx_client = _PykrxClient()

    request: PykrxCollectionRequest[Any] = PykrxCollectionRequest(
        tickers=["005930"],
        target_bars=220,
        load_json_fn=lambda *_: None,
        save_json_fn=lambda *_: None,
        split_symbol_and_suffix_fn=_split_symbol_and_suffix,
        exchange_from_suffix_fn=_exchange_from_suffix,
        adjusted=True,
        PykrxClientErrorCls=RuntimeError,
    )
    collect_market_data_from_pykrx(runtime, request=request)

    assert "005930" not in runtime.market_data
    assert any(
        "PyKRX returned no complete and finite candle data" in message
        for message in runtime.failures
    )


def test_collect_market_data_from_pykrx_uses_fresh_cache_before_provider() -> None:
    class _PykrxClient:
        def __init__(self) -> None:
            self.calls = 0

        def daily_candles(
            self, ticker: str, *, count: int, adjusted: bool = True
        ) -> list[dict[str, Any]]:
            del ticker
            del count
            del adjusted
            self.calls += 1
            raise AssertionError("provider fetch should be skipped for fresh cache")

    cached_candles = _candles_with_last_date("20250107")
    queried_keys: list[str] = []
    runtime = _build_runtime(
        kis_client=None, data_provider="pykrx", stale_sessions_kr=0
    )
    runtime.pykrx_client = _PykrxClient()

    def load_json_fn(_: str, key: str) -> Any:
        queried_keys.append(key)
        if key == _cache_key("005930", adjusted=False):
            return cached_candles
        return None

    _collect_market_data_from_pykrx(
        runtime,
        tickers=["005930"],
        target_bars=220,
        adjusted=False,
        load_json_fn=load_json_fn,
        save_json_fn=lambda *_: None,
        split_symbol_and_suffix_fn=_split_symbol_and_suffix,
        exchange_from_suffix_fn=_exchange_from_suffix,
        now_fn=lambda: dt.datetime(2025, 1, 8, 5, 0, tzinfo=dt.UTC),
    )

    assert queried_keys[0] == _cache_key("005930", adjusted=False)
    assert runtime.pykrx_client.calls == 0
    assert runtime.market_data["005930"] == cached_candles


def test_collect_market_data_from_pykrx_refreshes_stale_cache_with_fresh_provider() -> (
    None
):
    class _PykrxClient:
        def __init__(self) -> None:
            self.calls = 0

        def daily_candles(
            self, ticker: str, *, count: int, adjusted: bool = True
        ) -> list[dict[str, Any]]:
            assert ticker == "005930"
            assert count == 220
            assert adjusted is True
            self.calls += 1
            return _candles_with_last_date("20250108")

    cached_candles = _candles_with_last_date("20250107")
    saved_payloads: dict[str, list[dict[str, Any]]] = {}
    runtime = _build_runtime(
        kis_client=None, data_provider="pykrx", stale_sessions_kr=1
    )
    runtime.pykrx_client = _PykrxClient()

    _collect_market_data_from_pykrx(
        runtime,
        tickers=["005930"],
        target_bars=220,
        load_json_fn=lambda _dir, key: (
            cached_candles if key == _cache_key("005930") else None
        ),
        save_json_fn=lambda _dir, key, payload: saved_payloads.setdefault(key, payload),
        split_symbol_and_suffix_fn=_split_symbol_and_suffix,
        exchange_from_suffix_fn=_exchange_from_suffix,
        now_fn=lambda: dt.datetime(2025, 1, 8, 7, 0, tzinfo=dt.UTC),
    )

    assert runtime.pykrx_client.calls == 1
    assert runtime.market_data["005930"] == _candles_with_last_date("20250108")
    assert saved_payloads[_cache_key("005930")] == _candles_with_last_date("20250108")


def test_collect_market_data_from_pykrx_uses_stale_cache_when_provider_has_no_data() -> (
    None
):
    class _PykrxClient:
        def __init__(self) -> None:
            self.calls = 0

        def daily_candles(
            self, ticker: str, *, count: int, adjusted: bool = True
        ) -> list[dict[str, Any]]:
            assert ticker == "005930"
            assert count == 220
            assert adjusted is True
            self.calls += 1
            return []

    cached_candles = _candles_with_last_date("20250107")
    runtime = _build_runtime(
        kis_client=None, data_provider="pykrx", stale_sessions_kr=1
    )
    runtime.pykrx_client = _PykrxClient()

    _collect_market_data_from_pykrx(
        runtime,
        tickers=["005930"],
        target_bars=220,
        load_json_fn=lambda _dir, key: (
            cached_candles if key == _cache_key("005930") else None
        ),
        save_json_fn=lambda *_: None,
        split_symbol_and_suffix_fn=_split_symbol_and_suffix,
        exchange_from_suffix_fn=_exchange_from_suffix,
        now_fn=lambda: dt.datetime(2025, 1, 8, 7, 0, tzinfo=dt.UTC),
    )

    assert runtime.pykrx_client.calls == 1
    assert runtime.market_data["005930"] == cached_candles
    assert runtime.ticker_data_source["005930"] == "pykrx"
    assert runtime.failures == [
        "Warning: PyKRX provider data is end-of-day and may lag intraday feeds."
    ]


def test_collect_market_data_from_pykrx_continues_when_cache_persist_fails() -> None:
    class _PykrxClient:
        def daily_candles(
            self, ticker: str, *, count: int, adjusted: bool = True
        ) -> list[dict[str, Any]]:
            assert ticker == "005930"
            assert count == 220
            assert adjusted is True
            return _candles_with_last_date("20250108")

    runtime = _build_runtime(kis_client=None, data_provider="pykrx")
    runtime.pykrx_client = _PykrxClient()

    _collect_market_data_from_pykrx(
        runtime,
        tickers=["005930"],
        target_bars=220,
        load_json_fn=lambda *_: None,
        save_json_fn=lambda *_: (_ for _ in ()).throw(OSError("disk full")),
        split_symbol_and_suffix_fn=_split_symbol_and_suffix,
        exchange_from_suffix_fn=_exchange_from_suffix,
        now_fn=lambda: dt.datetime(2025, 1, 8, 7, 0, tzinfo=dt.UTC),
    )

    assert runtime.market_data["005930"] == _candles_with_last_date("20250108")
    assert runtime.ticker_data_source["005930"] == "pykrx"
    assert any(
        "Failed to persist cache" in message
        and "005930" in message
        and _cache_key("005930") in message
        and "disk full" in message
        for message in runtime.failures
    )


def test_collect_market_data_from_pykrx_rejects_stale_provider_response() -> None:
    class _PykrxClient:
        def daily_candles(
            self, ticker: str, *, count: int, adjusted: bool = True
        ) -> list[dict[str, Any]]:
            assert ticker == "005930"
            assert count == 220
            assert adjusted is True
            return _candles_with_last_date("20250107")

    saved_keys: list[str] = []
    runtime = _build_runtime(
        kis_client=None, data_provider="pykrx", stale_sessions_kr=0
    )
    runtime.pykrx_client = _PykrxClient()

    _collect_market_data_from_pykrx(
        runtime,
        tickers=["005930"],
        target_bars=220,
        load_json_fn=lambda *_: None,
        save_json_fn=lambda _dir, key, payload: saved_keys.append(key),
        split_symbol_and_suffix_fn=_split_symbol_and_suffix,
        exchange_from_suffix_fn=_exchange_from_suffix,
        now_fn=lambda: dt.datetime(2025, 1, 8, 7, 0, tzinfo=dt.UTC),
    )

    assert "005930" not in runtime.market_data
    assert saved_keys == []
    assert any(
        "PyKRX returned stale candles" in message
        and "stale by 1 KR sessions (max 0)" in message
        for message in runtime.failures
    )


def test_collect_market_data_from_pykrx_rejects_us_ticker_immediately() -> None:
    class _PykrxClient:
        def __init__(self) -> None:
            self.calls = 0

        def daily_candles(
            self, ticker: str, *, count: int, adjusted: bool = True
        ) -> list[dict[str, Any]]:
            del ticker
            del count
            del adjusted
            self.calls += 1
            raise AssertionError("US ticker should fail before provider fetch")

    runtime = _build_runtime(kis_client=None, data_provider="pykrx")
    runtime.pykrx_client = _PykrxClient()

    _collect_market_data_from_pykrx(
        runtime,
        tickers=["AAPL.NASD"],
        target_bars=220,
        load_json_fn=lambda *_: None,
        save_json_fn=lambda *_: None,
        split_symbol_and_suffix_fn=_split_symbol_and_suffix,
        exchange_from_suffix_fn=_exchange_from_suffix,
    )

    assert "AAPL.NASD" not in runtime.market_data
    assert runtime.pykrx_client.calls == 0
    assert any(
        "PyKRX provider supports KR tickers only" in message
        for message in runtime.failures
    )


def test_collect_market_data_from_kis_does_not_suppress_non_kwarg_type_error() -> None:
    class _KisClient:
        def daily_candles(
            self, symbol: str, *, count: int, **kwargs: Any
        ) -> list[dict[str, Any]]:
            del symbol
            if "adjusted" in kwargs:
                raise TypeError("internal converter failed")
            return _build_candles(count)

    runtime = _build_runtime(kis_client=_KisClient())

    with pytest.raises(TypeError, match="internal converter failed"):
        _collect_market_data_from_kis(
            runtime,
            tickers=["005930"],
            target_bars=220,
            load_json_fn=lambda *_: None,
            save_json_fn=lambda *_: None,
            ensure_pykrx_client_fn=lambda _: None,
            split_symbol_and_suffix_fn=_split_symbol_and_suffix,
            exchange_from_suffix_fn=_exchange_from_suffix,
            get_pykrx_error_fn=lambda _: None,
            adjusted=False,
        )


def test_collect_market_data_from_pykrx_does_not_suppress_non_kwarg_type_error() -> (
    None
):
    class _PykrxClient:
        def daily_candles(
            self, ticker: str, *, count: int, **kwargs: Any
        ) -> list[dict[str, Any]]:
            del ticker
            if "adjusted" in kwargs:
                raise TypeError("vectorization failed")
            return _build_candles(count)

    runtime = _build_runtime(kis_client=None, data_provider="pykrx")
    runtime.pykrx_client = _PykrxClient()

    request: PykrxCollectionRequest[Any] = PykrxCollectionRequest(
        tickers=["005930"],
        target_bars=220,
        load_json_fn=lambda *_: None,
        save_json_fn=lambda *_: None,
        split_symbol_and_suffix_fn=_split_symbol_and_suffix,
        exchange_from_suffix_fn=_exchange_from_suffix,
        adjusted=False,
        PykrxClientErrorCls=RuntimeError,
    )

    with pytest.raises(TypeError, match="vectorization failed"):
        collect_market_data_from_pykrx(runtime, request=request)


def test_scan_market_data_wires_pykrx_cache_hooks(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: dict[str, Any] = {}
    deps = build_market_data_dependencies(
        load_json_fn=lambda *_: None,
        save_json_fn=lambda *_: None,
    )
    service = ScanMarketData(deps=deps)
    runtime = SimpleNamespace(
        cfg=SimpleNamespace(data_provider="pykrx", min_history_bars=50),
        tickers=["005930"],
        pykrx_client=object(),
        failures=[],
        fatal_failure=False,
        latest_dates={},
        logger=logging.getLogger(__name__),
    )

    def _fake_collect(runtime_arg: Any, *, request: Any) -> None:
        captured["runtime"] = runtime_arg
        captured["request"] = request

    monkeypatch.setattr(
        "sab.market_data_service.market_data_pipeline.collect_market_data_from_pykrx",
        _fake_collect,
    )

    service.collect_market_data(cast(Any, runtime))

    request = captured["request"]
    assert captured["runtime"] is runtime
    assert request.load_json_fn is deps.load_json_fn
    assert request.save_json_fn is deps.save_json_fn
    assert request.adjusted is True
    assert request.legacy_cache_keys_fn is _scan_legacy_cache_keys
    assert request.split_symbol_and_suffix_fn("AAPL.NASD") == ("AAPL", "NASD")
    assert request.exchange_from_suffix_fn("NASD") == "NAS"


def test_scan_market_data_requests_tail_trim_buffer() -> None:
    captured: dict[str, Any] = {}
    deps = build_market_data_dependencies(
        load_json_fn=lambda *_: None,
        save_json_fn=lambda *_: None,
    )
    service = ScanMarketData(deps=deps)
    runtime = SimpleNamespace(
        cfg=SimpleNamespace(data_provider="kis", min_history_bars=200),
        tickers=["005930"],
        failures=[],
        fatal_failure=False,
    )

    def _fake_collect(runtime_arg: Any, tickers: list[str], target_bars: int) -> None:
        captured["runtime"] = runtime_arg
        captured["tickers"] = tickers
        captured["target_bars"] = target_bars

    service._provider_collectors["kis"] = _fake_collect

    service.collect_market_data(cast(Any, runtime))

    assert captured["runtime"] is runtime
    assert captured["tickers"] == ["005930"]
    assert captured["target_bars"] == 201


def test_scan_market_data_collects_candidate_raw_data_without_overwriting_adjusted(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: dict[str, Any] = {}
    deps = build_market_data_dependencies(
        load_json_fn=lambda *_: None,
        save_json_fn=lambda *_: None,
    )
    service = ScanMarketData(deps=deps)
    adjusted_payload = {
        "005930": cast(
            Any,
            [
                {
                    "date": "20250110",
                    "open": 100.0,
                    "high": 101.0,
                    "low": 99.0,
                    "close": 100.0,
                    "volume": 1_000_000.0,
                }
            ],
        )
    }
    runtime = SimpleNamespace(
        cfg=SimpleNamespace(data_provider="kis"),
        raw_market_data={},
        market_data=adjusted_payload,
        ticker_data_source={"005930": "kis"},
        kis_client=object(),
        pykrx_client=None,
        failures=[],
        fatal_failure=False,
        pykrx_warning_added=False,
        pykrx_import_error=None,
        cache_hint=None,
        logger=logging.getLogger(__name__),
    )

    def _fake_collect(runtime_arg: Any, *, request: Any) -> None:
        captured["runtime_market_data"] = runtime_arg.market_data
        captured["runtime_ticker_data_source"] = runtime_arg.ticker_data_source
        captured["request"] = request
        runtime_arg.market_data["005930"] = [
            {
                "date": "20250110",
                "open": 100.0,
                "high": 100.0,
                "low": 100.0,
                "close": 100.0,
                "volume": 1_000_000.0,
            }
        ]
        runtime_arg.ticker_data_source["005930"] = "pykrx"

    monkeypatch.setattr(
        "sab.market_data_service.market_data_pipeline.collect_market_data_from_kis",
        _fake_collect,
    )

    service.collect_entry_reference_raw_market_data(
        cast(Any, runtime),
        tickers=["005930", "005930"],
    )

    request = captured["request"]
    assert request.adjusted is False
    assert request.tickers == ["005930"]
    assert captured["runtime_market_data"] is runtime.raw_market_data
    assert captured["runtime_ticker_data_source"] == {"005930": "pykrx"}
    assert runtime.market_data is adjusted_payload
    assert runtime.market_data["005930"][0]["open"] == 100.0
    assert runtime.raw_market_data["005930"][0]["close"] == 100.0
    assert runtime.ticker_data_source == {"005930": "kis"}


def test_scan_market_data_skips_prefetched_raw_candidate_tickers(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: dict[str, Any] = {}
    deps = build_market_data_dependencies(
        load_json_fn=lambda *_: None,
        save_json_fn=lambda *_: None,
    )
    service = ScanMarketData(deps=deps)
    runtime = SimpleNamespace(
        cfg=SimpleNamespace(data_provider="pykrx"),
        raw_market_data={"005930": [_candles_with_last_date("20250110")[0]]},
        market_data={},
        ticker_data_source={},
        kis_client=None,
        pykrx_client=object(),
        failures=[],
        fatal_failure=False,
        pykrx_warning_added=False,
        pykrx_import_error=None,
        cache_hint=None,
        logger=logging.getLogger(__name__),
    )

    def _fake_collect(runtime_arg: Any, *, request: Any) -> None:
        captured["runtime_market_data"] = runtime_arg.market_data
        captured["request"] = request

    monkeypatch.setattr(
        "sab.market_data_service.market_data_pipeline.collect_market_data_from_pykrx",
        _fake_collect,
    )

    service.collect_entry_reference_raw_market_data(
        cast(Any, runtime),
        tickers=["005930", "000660", "000660"],
    )

    request = captured["request"]
    assert request.adjusted is False
    assert request.tickers == ["000660"]
    assert captured["runtime_market_data"] is runtime.raw_market_data


def test_sell_market_data_wires_pykrx_cache_hooks(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: dict[str, Any] = {}
    deps = build_market_data_dependencies(
        load_json_fn=lambda *_: None,
        save_json_fn=lambda *_: None,
    )
    service = SellMarketData(deps=deps)
    runtime = SimpleNamespace(
        cfg=SimpleNamespace(data_provider="pykrx"),
        unique_tickers=["005930"],
        pykrx_client=object(),
        failures=[],
        fatal_failure=False,
        logger=logging.getLogger(__name__),
    )

    def _fake_collect(runtime_arg: Any, *, request: Any) -> None:
        captured["runtime"] = runtime_arg
        captured["request"] = request

    monkeypatch.setattr(
        "sab.market_data_service.market_data_pipeline.collect_market_data_from_pykrx",
        _fake_collect,
    )

    service.collect_market_data(cast(Any, runtime), target_bars=220)

    request = captured["request"]
    assert captured["runtime"] is runtime
    assert request.load_json_fn is deps.load_json_fn
    assert request.save_json_fn is deps.save_json_fn
    assert request.adjusted is False
    assert request.legacy_cache_keys_fn is None
    assert request.split_symbol_and_suffix_fn("AAPL.NASD") == ("AAPL", "NASD")
    assert request.exchange_from_suffix_fn("NASD") == "NAS"
