from __future__ import annotations

import logging
from types import SimpleNamespace
from typing import Any, cast

import pytest
from sab import scan, sell
from sab.data_coverage_policy import MIN_DATA_COVERAGE, is_data_coverage_fatal


def test_is_data_coverage_fatal_threshold_boundary() -> None:
    assert is_data_coverage_fatal(MIN_DATA_COVERAGE - 0.01)
    assert not is_data_coverage_fatal(MIN_DATA_COVERAGE)
    assert not is_data_coverage_fatal(MIN_DATA_COVERAGE + 0.01)


def test_scan_missing_data_uses_shared_coverage_policy(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    runtime = SimpleNamespace(
        tickers=["AAPL.NAS", "MSFT.NAS"],
        market_data={"AAPL.NAS": []},
        failures=[],
        system_issues=[],
        fatal_failure=False,
        logger=logging.getLogger("test.scan.coverage"),
    )
    captured_coverage: list[float] = []

    def fake_policy(
        data_coverage: float,
        *,
        min_data_coverage: float = MIN_DATA_COVERAGE,
    ) -> bool:
        del min_data_coverage
        captured_coverage.append(data_coverage)
        return False

    monkeypatch.setattr(scan, "is_data_coverage_fatal", fake_policy)
    scan._mark_missing_scan_market_data(cast(Any, runtime))

    assert captured_coverage == [0.5]
    assert not runtime.fatal_failure


def test_sell_missing_data_uses_shared_coverage_policy(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    runtime = SimpleNamespace(
        unique_tickers=["005930", "000660"],
        market_data={"005930": []},
        failures=[],
        fatal_failure=False,
        logger=logging.getLogger("test.sell.coverage"),
    )
    captured_coverage: list[float] = []

    def fake_policy(
        data_coverage: float,
        *,
        min_data_coverage: float = MIN_DATA_COVERAGE,
    ) -> bool:
        del min_data_coverage
        captured_coverage.append(data_coverage)
        return False

    monkeypatch.setattr(sell, "is_data_coverage_fatal", fake_policy)
    sell._mark_missing_sell_market_data(cast(Any, runtime))

    assert captured_coverage == [0.5]
    assert not runtime.fatal_failure
