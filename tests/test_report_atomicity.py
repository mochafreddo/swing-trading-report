from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import sab.report.markdown as buy_markdown
import sab.report.sell_report as sell_markdown
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


def test_write_sell_report_formats_fractional_quantity_in_summary(
    tmp_path: Path,
) -> None:
    rows = [
        SellReportRow(
            ticker="CMG.NYS",
            name="Chipotle",
            quantity=0.268187,
            entry_price=37.25,
            entry_date="2026-01-02",
            last_price=38.45,
            pnl_pct=0.032,
            action="REVIEW",
            reasons=["test"],
            stop_price=None,
            target_price=40.98,
            currency="USD",
        ),
        SellReportRow(
            ticker="005930",
            name="Samsung",
            quantity=12.0,
            entry_price=71200.0,
            entry_date="2025-01-01",
            last_price=75000.0,
            pnl_pct=0.053,
            action="HOLD",
            reasons=["test"],
            stop_price=None,
            target_price=79000.0,
            currency="KRW",
        ),
    ]
    out_path = write_sell_report(
        report_dir=tmp_path.as_posix(),
        provider="test",
        evaluated=rows,
    )
    content = Path(out_path).read_text(encoding="utf-8")
    assert "| CMG.NYS | 0.268187 |" in content
    assert "| 005930 | 12 |" in content


def test_write_sell_report_quantity_digits_is_configurable(tmp_path: Path) -> None:
    row = SellReportRow(
        ticker="CMG.NYS",
        name="Chipotle",
        quantity=0.268187,
        entry_price=37.25,
        entry_date="2026-01-02",
        last_price=38.45,
        pnl_pct=0.032,
        action="REVIEW",
        reasons=["test"],
        stop_price=None,
        target_price=40.98,
        currency="USD",
    )
    out_path = write_sell_report(
        report_dir=tmp_path.as_posix(),
        provider="test",
        evaluated=[row],
        quantity_digits=4,
    )
    content = Path(out_path).read_text(encoding="utf-8")
    assert "| CMG.NYS | 0.2682 |" in content


def test_write_report_uses_runtime_timezone_label(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(
        buy_markdown,
        "resolve_report_timestamp",
        lambda: ("2026-02-06", "2026-02-06 09:30", "EST"),
    )
    out_path = write_report(
        report_dir=tmp_path.as_posix(),
        provider="test",
        universe_count=1,
        candidates=[{"ticker": "AAPL", "name": "Apple", "price": "190"}],
        report_type="buy",
    )
    content = Path(out_path).read_text(encoding="utf-8")
    assert "- Run at: 2026-02-06 09:30 EST" in content
    assert "KST" not in content


def test_write_sell_report_uses_runtime_timezone_label(
    tmp_path: Path, monkeypatch
) -> None:
    monkeypatch.setattr(
        sell_markdown,
        "resolve_report_timestamp",
        lambda: ("2026-02-06", "2026-02-06 09:30", "EST"),
    )
    row = SellReportRow(
        ticker="AAPL.NAS",
        name="Apple",
        quantity=1.0,
        entry_price=150.0,
        entry_date="2026-01-02",
        last_price=190.0,
        pnl_pct=0.2,
        action="HOLD",
        reasons=["test"],
        stop_price=170.0,
        target_price=210.0,
        currency="USD",
    )
    out_path = write_sell_report(
        report_dir=tmp_path.as_posix(),
        provider="test",
        evaluated=[row],
    )
    content = Path(out_path).read_text(encoding="utf-8")
    assert "- Run at: 2026-02-06 09:30 EST" in content
    assert "KST" not in content
