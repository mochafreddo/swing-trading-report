from __future__ import annotations

import logging
from dataclasses import replace
from typing import Any

from sab.config import Config
from sab.scan import _evaluate_scan_runtime
from sab.scan_types import _ScanRuntime


def test_evaluate_scan_runtime_batch_warms_raw_entry_reference_prices(
    monkeypatch: Any,
) -> None:
    runtime = _ScanRuntime(
        cfg=replace(Config(), data_dir="data", report_dir="reports"),
        logger=logging.getLogger(__name__),
        tickers=["005930", "000660"],
    )
    call_order: list[str] = []

    class _FakeMarketDataService:
        def __init__(self) -> None:
            self.tickers: list[str] = []

        def collect_entry_reference_raw_market_data(
            self,
            runtime_arg: _ScanRuntime,
            *,
            tickers: list[str],
            target_bars: int = 10,
        ) -> None:
            del runtime_arg
            call_order.append("raw")
            self.tickers = list(tickers)
            assert target_bars == 10

    def _fake_evaluate_candidates(runtime_arg: _ScanRuntime, **kwargs: Any) -> None:
        assert runtime_arg is runtime
        assert kwargs["enrich_entry_reference_prices"] is False
        call_order.append("evaluate")
        runtime_arg.candidates = [
            {"ticker": "005930"},
            {"ticker": "000660"},
            {"ticker": "005930"},
        ]

    service = _FakeMarketDataService()
    monkeypatch.setattr(
        "sab.scan.scan_evaluation._evaluate_candidates",
        _fake_evaluate_candidates,
    )
    monkeypatch.setattr(
        "sab.scan.scan_evaluation._enrich_entry_reference_prices",
        lambda runtime_arg: call_order.append("enrich"),
    )
    monkeypatch.setattr(
        "sab.scan.scan_evaluation._decorate_candidates",
        lambda runtime_arg, **kwargs: call_order.append("decorate"),
    )

    _evaluate_scan_runtime(runtime, market_data_service=service)  # type: ignore[arg-type]

    assert call_order == ["evaluate", "raw", "enrich", "decorate"]
    assert service.tickers == ["005930", "000660", "005930"]
