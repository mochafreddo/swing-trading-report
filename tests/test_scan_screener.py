from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import sab.scan_screener as ss


class _Logger:
    def info(self, *_args: object, **_kwargs: object) -> None:
        return None

    def warning(self, *_args: object, **_kwargs: object) -> None:
        return None

    def error(self, *_args: object, **_kwargs: object) -> None:
        return None


def _runtime(
    *,
    tickers: list[str] | None = None,
    us_screener_mode: str = "defaults",
    us_screener_limit: int = 2,
    screener_seeded: bool = False,
) -> Any:
    cfg = SimpleNamespace(
        universe_markets=["US"],
        us_screener_mode=us_screener_mode,
        us_screener_defaults=["AAPL.US", "MSFT.US", "NVDA.US"],
        us_screener_limit=us_screener_limit,
        us_screener_metric="volume",
        data_dir="data",
    )
    return SimpleNamespace(
        cfg=cfg,
        kis_client=object(),
        tickers=list(tickers or []),
        screener_seeded=screener_seeded,
        screener_meta_map={},
        logger=_Logger(),
        failures=[],
        fatal_failure=False,
    )


def _session_info(**_kwargs: object) -> dict[str, object]:
    return {
        "preferred_nday": 1,
        "state": "closed",
        "is_holiday": False,
        "ny_now": None,
    }


def test_run_us_screener_defaults_uses_us_screener_limit() -> None:
    runtime = _runtime(us_screener_mode="defaults", us_screener_limit=2)
    captured_limit: dict[str, int] = {}

    class _USRequest:
        def __init__(self, limit: int) -> None:
            self.limit = limit
            captured_limit["value"] = limit

    class _DefaultsScreener:
        def __init__(self, defaults: list[str]) -> None:
            self.defaults = defaults

        def screen(self, request: _USRequest) -> Any:
            return SimpleNamespace(
                tickers=self.defaults[: request.limit],
                metadata={},
            )

    added = ss._run_us_screener(
        runtime,
        screener_limit=7,
        screener_only=False,
        KUSCls=object,
        KUSReqCls=object,
        USScreenerCls=_DefaultsScreener,
        USScreenRequestCls=_USRequest,
        us_session_info_fn=_session_info,
        coerce_nday_fn=int,
        format_ny_now_for_log_fn=lambda _session: "-",
    )

    assert captured_limit["value"] == 2
    assert added == 2
    assert runtime.tickers == ["AAPL.US", "MSFT.US"]


def test_run_screeners_screener_only_ignores_watchlist_baseline(
    monkeypatch: Any,
) -> None:
    runtime = _runtime(tickers=["TSLA.US"], us_screener_mode="defaults")
    captured_baseline: dict[str, list[str]] = {}

    def _fake_run_kr(*_args: Any, **_kwargs: Any) -> int:
        return 0

    def _fake_run_us(
        runtime_obj: Any,
        **_kwargs: Any,
    ) -> int:
        captured_baseline["tickers"] = list(runtime_obj.tickers)
        runtime_obj.tickers = ["AAPL.US"]
        return 1

    monkeypatch.setattr(ss, "_run_kr_screener", _fake_run_kr)
    monkeypatch.setattr(ss, "_run_us_screener", _fake_run_us)

    ss._run_screeners(
        runtime,
        screener_enabled=True,
        screener_only=True,
        screener_limit=5,
        ScreenRequestCls=object,
        KISScreenerCls=object,
        KUSCls=object,
        KUSReqCls=object,
        USScreenerCls=object,
        USScreenRequestCls=object,
        us_session_info_fn=_session_info,
        coerce_nday_fn=int,
        format_ny_now_for_log_fn=lambda _session: "-",
    )

    assert captured_baseline["tickers"] == []
    assert runtime.tickers == ["AAPL.US"]


def test_run_us_screener_direct_call_clears_watchlist_in_screener_only() -> None:
    runtime = _runtime(
        tickers=["TSLA.US"],
        us_screener_mode="defaults",
        us_screener_limit=1,
    )

    class _USRequest:
        def __init__(self, limit: int) -> None:
            self.limit = limit

    class _DefaultsScreener:
        def __init__(self, defaults: list[str]) -> None:
            self.defaults = defaults

        def screen(self, request: _USRequest) -> Any:
            return SimpleNamespace(tickers=self.defaults[: request.limit], metadata={})

    ss._run_us_screener(
        runtime,
        screener_limit=1,
        screener_only=True,
        KUSCls=object,
        KUSReqCls=object,
        USScreenerCls=_DefaultsScreener,
        USScreenRequestCls=_USRequest,
        us_session_info_fn=_session_info,
        coerce_nday_fn=int,
        format_ny_now_for_log_fn=lambda _session: "-",
    )

    assert runtime.tickers == ["AAPL.US"]
    assert runtime.screener_seeded is True


def test_run_us_screener_direct_call_preserves_screener_seeded_baseline() -> None:
    runtime = _runtime(
        tickers=["005930"],
        us_screener_mode="defaults",
        us_screener_limit=1,
        screener_seeded=True,
    )

    class _USRequest:
        def __init__(self, limit: int) -> None:
            self.limit = limit

    class _DefaultsScreener:
        def __init__(self, defaults: list[str]) -> None:
            self.defaults = defaults

        def screen(self, request: _USRequest) -> Any:
            return SimpleNamespace(tickers=self.defaults[: request.limit], metadata={})

    ss._run_us_screener(
        runtime,
        screener_limit=1,
        screener_only=True,
        KUSCls=object,
        KUSReqCls=object,
        USScreenerCls=_DefaultsScreener,
        USScreenRequestCls=_USRequest,
        us_session_info_fn=_session_info,
        coerce_nday_fn=int,
        format_ny_now_for_log_fn=lambda _session: "-",
    )

    assert runtime.tickers == ["005930", "AAPL.US"]
    assert runtime.screener_seeded is True
