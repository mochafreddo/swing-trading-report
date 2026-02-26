from __future__ import annotations

import json
from pathlib import Path

from sab.report.entry_report import EntryReportRow, write_entry_report


def test_write_entry_report_writes_schema_and_entries(tmp_path: Path) -> None:
    rows = [
        EntryReportRow(
            ticker="AAPL.NASD",
            action="ENTER",
            reasons=["Gap within guard"],
            signal_close=100.0,
            entry_price=101.0,
            gap_pct=0.01,
            gap_guard_pct=0.02,
            gap_guard_up_price=102.0,
            gap_guard_down_price=98.0,
            strategy_mode="ema_cross",
        )
    ]
    artifact = {
        "provider": "kis",
        "mode": "PRE_OPEN",
        "market": "US",
        "source_buy_report": "2026-02-25.buy.json",
        "signal_eval_date": "2026-02-25",
        "entry_session_date": "2026-02-26",
        "summary": {"entry_count": 1, "action_counts": {"ENTER": 1}},
        "tickers": ["AAPL.NASD"],
        "system_issues": [],
    }
    out_path = write_entry_report(
        report_dir=tmp_path.as_posix(),
        artifact=artifact,
        entries=rows,
    )

    payload = json.loads(Path(out_path).read_text(encoding="utf-8"))
    assert payload["schema"] == "sab.report.v1"
    assert payload["type"] == "entry"
    assert payload["provider"] == "kis"
    assert payload["mode"] == "PRE_OPEN"
    assert payload["market"] == "US"
    assert payload["source_buy_report"] == "2026-02-25.buy.json"
    assert payload["entries"][0]["ticker"] == "AAPL.NASD"
    assert payload["entries"][0]["action"] == "ENTER"
    assert "generated_at" in payload
