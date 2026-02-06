from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from sab.report.markdown import write_report
from sab.report.sell_report import SellReportRow, write_sell_report


def _write_buy_report(report_dir: str, idx: int) -> str:
    return write_report(
        report_dir=report_dir,
        provider="test",
        universe_count=1,
        candidates=[{"ticker": f"T{idx:03d}", "name": "Name", "price": "100"}],
        report_type="buy",
    )


def _write_sell_report(report_dir: str, idx: int) -> str:
    row = SellReportRow(
        ticker=f"T{idx:03d}",
        name="Name",
        quantity=1.0,
        entry_price=100.0,
        entry_date="2025-01-01",
        last_price=101.0,
        pnl_pct=0.01,
        action="HOLD",
        reasons=["test"],
        stop_price=95.0,
        target_price=110.0,
    )
    return write_sell_report(
        report_dir=report_dir,
        provider="test",
        evaluated=[row],
    )


def test_write_report_uses_unique_paths_under_concurrency(tmp_path: Path) -> None:
    report_dir = tmp_path.as_posix()
    jobs = 12

    with ThreadPoolExecutor(max_workers=6) as executor:
        futures = [
            executor.submit(_write_buy_report, report_dir, i) for i in range(jobs)
        ]
        paths = [future.result() for future in futures]

    assert len(paths) == jobs
    assert len(set(paths)) == jobs
    for out_path in paths:
        report_path = Path(out_path)
        assert report_path.parent == tmp_path
        assert report_path.exists()
        assert report_path.read_text(encoding="utf-8").startswith("# Swing Screening")


def test_write_sell_report_uses_unique_paths_under_concurrency(tmp_path: Path) -> None:
    report_dir = tmp_path.as_posix()
    jobs = 12

    with ThreadPoolExecutor(max_workers=6) as executor:
        futures = [
            executor.submit(_write_sell_report, report_dir, i) for i in range(jobs)
        ]
        paths = [future.result() for future in futures]

    assert len(paths) == jobs
    assert len(set(paths)) == jobs
    for out_path in paths:
        report_path = Path(out_path)
        assert report_path.parent == tmp_path
        assert report_path.exists()
        assert report_path.read_text(encoding="utf-8").startswith(
            "# Holdings Sell Review"
        )
