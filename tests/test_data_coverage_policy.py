from __future__ import annotations

import logging
from types import SimpleNamespace
from typing import Any, cast

import pytest
import sab.data_coverage_policy as data_coverage_policy
from sab import scan, sell
from sab.data_coverage_policy import (
    MIN_DATA_COVERAGE,
    is_data_coverage_fatal,
    summarize_missing_market_data,
)


def test_is_data_coverage_fatal_threshold_boundary() -> None:
    assert is_data_coverage_fatal(MIN_DATA_COVERAGE - 0.01)
    assert not is_data_coverage_fatal(MIN_DATA_COVERAGE)
    assert not is_data_coverage_fatal(MIN_DATA_COVERAGE + 0.01)


def test_summarize_missing_market_data_returns_none_when_complete() -> None:
    summary = summarize_missing_market_data(
        requested=["AAPL.NAS", "MSFT.NAS"],
        available={"AAPL.NAS": [], "MSFT.NAS": []},
        subject="tickers",
    )

    assert summary is None


def test_summarize_missing_market_data_formats_preview_and_fatal_status() -> None:
    requested = [f"TICKER{i}" for i in range(12)]

    summary = summarize_missing_market_data(
        requested=requested,
        available={"TICKER0": []},
        subject="tickers",
    )

    assert summary is not None
    assert summary.missing == tuple(requested[1:])
    assert summary.coverage == pytest.approx(1 / 12)
    assert summary.fatal
    assert summary.message == (
        "Missing market data for 11/12 tickers "
        "(coverage=0.08, required>=0.70): "
        "TICKER1, TICKER2, TICKER3, TICKER4, TICKER5, "
        "TICKER6, TICKER7, TICKER8, TICKER9, TICKER10, +1 more"
    )


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

    monkeypatch.setattr(data_coverage_policy, "is_data_coverage_fatal", fake_policy)
    scan._mark_missing_scan_market_data(cast(Any, runtime))

    assert captured_coverage == [0.5]
    assert not runtime.fatal_failure
    assert runtime.failures == [
        "Missing market data for 1/2 tickers (coverage=0.50, required>=0.70): MSFT.NAS"
    ]
    assert runtime.system_issues == runtime.failures


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

    monkeypatch.setattr(data_coverage_policy, "is_data_coverage_fatal", fake_policy)
    sell._mark_missing_sell_market_data(cast(Any, runtime))

    assert captured_coverage == [0.5]
    assert not runtime.fatal_failure
    assert runtime.failures == [
        "Missing market data for 1/2 holdings (coverage=0.50, required>=0.70): 000660"
    ]


def test_scan_missing_data_marks_fatal_when_shared_policy_is_fatal(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    runtime = SimpleNamespace(
        tickers=["AAPL.NAS", "MSFT.NAS"],
        market_data={},
        failures=[],
        system_issues=[],
        fatal_failure=False,
        logger=logging.getLogger("test.scan.coverage.fatal"),
    )

    monkeypatch.setattr(
        data_coverage_policy,
        "is_data_coverage_fatal",
        lambda *_, **__: True,
    )

    scan._mark_missing_scan_market_data(cast(Any, runtime))

    assert runtime.fatal_failure
    assert runtime.failures == [
        "Missing market data for 2/2 tickers "
        "(coverage=0.00, required>=0.70): AAPL.NAS, MSFT.NAS"
    ]
    assert runtime.system_issues == runtime.failures


def test_sell_missing_data_marks_fatal_when_shared_policy_is_fatal(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    runtime = SimpleNamespace(
        unique_tickers=["005930", "000660"],
        market_data={},
        failures=[],
        fatal_failure=False,
        logger=logging.getLogger("test.sell.coverage.fatal"),
    )

    monkeypatch.setattr(
        data_coverage_policy,
        "is_data_coverage_fatal",
        lambda *_, **__: True,
    )

    sell._mark_missing_sell_market_data(cast(Any, runtime))

    assert runtime.fatal_failure
    assert runtime.failures == [
        "Missing market data for 2/2 holdings "
        "(coverage=0.00, required>=0.70): 005930, 000660"
    ]
