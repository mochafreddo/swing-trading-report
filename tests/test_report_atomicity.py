from __future__ import annotations

import json
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import sab.report.markdown as buy_reports
import sab.report.sell_report as sell_reports
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
        payload = json.loads(report_path.read_text(encoding="utf-8"))
        assert payload["schema"] == "sab.report.v1"
        assert payload["type"] == "buy"
        assert payload["summary"]["candidate_count"] == 1


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
        payload = json.loads(report_path.read_text(encoding="utf-8"))
        assert payload["schema"] == "sab.report.v1"
        assert payload["type"] == "sell"
        assert payload["summary"]["evaluated_count"] == 1


def test_write_sell_report_preserves_fractional_quantity_in_payload(
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
    payload = json.loads(Path(out_path).read_text(encoding="utf-8"))
    evaluated = {row["ticker"]: row for row in payload["evaluated"]}
    assert evaluated["CMG.NYS"]["quantity"] == 0.268187
    assert evaluated["005930"]["quantity"] == 12.0


def test_write_sell_report_emits_rules_and_fx_metadata(tmp_path: Path) -> None:
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
        atr_trail_multiplier=1.5,
        time_stop_days=7,
        fx_rate=1380.0,
        fx_note="manual",
        sell_mode="sma_ema_hybrid",
        sell_mode_note="hybrid tuned",
    )
    payload = json.loads(Path(out_path).read_text(encoding="utf-8"))
    assert payload["rules"]["atr_trail_multiplier"] == 1.5
    assert payload["rules"]["time_stop_days"] == 7
    assert payload["rules"]["sell_mode"] == "sma_ema_hybrid"
    assert payload["fx"]["usd_krw_rate"] == 1380.0
    assert payload["fx"]["note"] == "manual"


def test_write_report_uses_runtime_timezone_label(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(
        buy_reports,
        "resolve_report_timestamp",
        lambda artifact_date=None: ("2026-02-06", "2026-02-06 09:30", "EST"),
    )
    out_path = write_report(
        report_dir=tmp_path.as_posix(),
        provider="test",
        universe_count=1,
        candidates=[{"ticker": "AAPL", "name": "Apple", "price": "190"}],
        report_type="buy",
    )
    payload = json.loads(Path(out_path).read_text(encoding="utf-8"))
    assert payload["generated_at"] == "2026-02-06 09:30 EST"
    assert payload["report_date"] == "2026-02-06"


def test_write_report_uses_artifact_date_for_filename_and_payload(
    tmp_path: Path, monkeypatch
) -> None:
    monkeypatch.setattr(
        buy_reports,
        "resolve_report_timestamp",
        lambda artifact_date=None: (
            "2026-02-25" if artifact_date == "20260225" else "2026-02-26",
            "2026-02-26 09:30",
            "KST",
        ),
    )
    out_path = write_report(
        report_dir=tmp_path.as_posix(),
        provider="test",
        universe_count=1,
        candidates=[{"ticker": "AAPL", "name": "Apple", "price": "190"}],
        report_type="buy",
        artifact_date="20260225",
    )
    payload = json.loads(Path(out_path).read_text(encoding="utf-8"))
    assert Path(out_path).name == "2026-02-25.buy.json"
    assert payload["report_date"] == "2026-02-25"


def test_write_sell_report_uses_runtime_timezone_label(
    tmp_path: Path, monkeypatch
) -> None:
    monkeypatch.setattr(
        sell_reports,
        "resolve_report_timestamp",
        lambda artifact_date=None: ("2026-02-06", "2026-02-06 09:30", "EST"),
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
    payload = json.loads(Path(out_path).read_text(encoding="utf-8"))
    assert payload["generated_at"] == "2026-02-06 09:30 EST"


def test_write_sell_report_uses_artifact_date_for_filename_and_payload(
    tmp_path: Path, monkeypatch
) -> None:
    monkeypatch.setattr(
        sell_reports,
        "resolve_report_timestamp",
        lambda artifact_date=None: (
            "2026-02-25" if artifact_date == "20260225" else "2026-02-26",
            "2026-02-26 09:30",
            "KST",
        ),
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
        artifact_date="20260225",
    )
    payload = json.loads(Path(out_path).read_text(encoding="utf-8"))
    assert Path(out_path).name == "2026-02-25.sell.json"
    assert payload["report_date"] == "2026-02-25"


def test_write_report_emits_issue_split_fields(tmp_path: Path) -> None:
    out_path = write_report(
        report_dir=tmp_path.as_posix(),
        provider="test",
        universe_count=2,
        candidates=[{"ticker": "AAPL.US", "name": "Apple", "price": "190"}],
        failures=["sys-1", "screen-1"],
        system_issues=["sys-1"],
        screen_outs=["screen-1"],
        report_type="buy",
    )
    payload = json.loads(Path(out_path).read_text(encoding="utf-8"))
    assert payload["issues"] == ["sys-1", "screen-1"]
    assert payload["system_issues"] == ["sys-1"]
    assert payload["screen_outs"] == ["screen-1"]
    assert payload["summary"]["issue_count"] == 2
    assert payload["summary"]["system_issue_count"] == 1
    assert payload["summary"]["screen_out_count"] == 1


def test_write_report_merges_summary_fields(tmp_path: Path) -> None:
    out_path = write_report(
        report_dir=tmp_path.as_posix(),
        provider="test",
        universe_count=3,
        candidates=[{"ticker": "AAPL.US", "name": "Apple", "price": "190"}],
        report_type="buy",
        summary_fields={
            "data_requested_count": 3,
            "data_covered_count": 2,
            "data_missing_count": 1,
            "data_coverage_ratio": 2 / 3,
            "provider_fallback_count": 1,
            "provider_fallback_ratio": 0.5,
            "rs_benchmark_requested_count": 2,
            "rs_benchmark_unavailable_count": 1,
            "rs_benchmark_unavailable_ratio": 0.5,
        },
    )

    payload = json.loads(Path(out_path).read_text(encoding="utf-8"))
    assert payload["summary"]["candidate_count"] == 1
    assert payload["summary"]["data_requested_count"] == 3
    assert payload["summary"]["data_covered_count"] == 2
    assert payload["summary"]["data_missing_count"] == 1
    assert payload["summary"]["provider_fallback_count"] == 1
    assert payload["summary"]["rs_benchmark_requested_count"] == 2
    assert payload["summary"]["rs_benchmark_unavailable_count"] == 1


def test_write_sell_report_merges_summary_fields(tmp_path: Path) -> None:
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
        summary_fields={
            "data_requested_count": 2,
            "data_covered_count": 1,
            "data_missing_count": 1,
            "data_coverage_ratio": 0.5,
            "provider_fallback_count": 1,
            "provider_fallback_ratio": 1.0,
        },
    )

    payload = json.loads(Path(out_path).read_text(encoding="utf-8"))
    assert payload["summary"]["evaluated_count"] == 1
    assert payload["summary"]["data_requested_count"] == 2
    assert payload["summary"]["data_covered_count"] == 1
    assert payload["summary"]["data_missing_count"] == 1
    assert payload["summary"]["provider_fallback_count"] == 1
    assert payload["summary"]["provider_fallback_ratio"] == 1.0
