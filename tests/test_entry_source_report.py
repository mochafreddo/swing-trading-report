from __future__ import annotations

import json
from pathlib import Path

import sab.entry as entry


def _candidate(ticker: str) -> dict[str, object]:
    return {
        "ticker": ticker,
        "eval_date": "20260225",
        "entry_reference_eval_date": "20260225",
        "entry_reference_close_raw_value": 100.0,
        "gap_guard_pct_value": 0.05,
    }


def test_entry_source_report_context_filters_market_override_without_losing_source_order(
    tmp_path: Path,
) -> None:
    assert hasattr(entry, "_load_entry_source_report")
    helper = entry._load_entry_source_report
    buy_report_path = tmp_path / "2026-02-25.buy.json"
    buy_report_path.write_text(
        json.dumps(
            {
                "eval_context": {"market": "MIXED"},
                "candidates": [
                    _candidate("005930"),
                    _candidate("AAPL.NASD"),
                ],
            }
        ),
        encoding="utf-8",
    )

    context = helper(
        report_dir=tmp_path.as_posix(),
        buy_report_path=buy_report_path.as_posix(),
        market_override="US",
    )

    assert context.resolved_report_path == buy_report_path.as_posix()
    assert [row["ticker"] for row in context.candidates] == [
        "005930",
        "AAPL.NASD",
    ]
    assert context.resolved_markets == ["US"]
    assert {
        market: [row["ticker"] for row in rows]
        for market, rows in context.candidates_by_market.items()
    } == {"US": ["AAPL.NASD"]}
