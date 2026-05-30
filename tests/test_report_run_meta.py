from __future__ import annotations

import json
import re
from datetime import UTC, datetime
from pathlib import Path

from sab.report.markdown import write_report
from sab.report.run_meta import build_run_meta
from sab.report.sell_report import SellReportRow, write_sell_report


def test_build_run_meta_uses_env_sha_and_fixed_timestamp(monkeypatch) -> None:
    monkeypatch.setenv("GITHUB_SHA", "deadbeef")
    meta = build_run_meta(
        market="KR",
        session_state="AFTER_CLOSE",
        eval_index_policy="choose_eval_index:v1",
        config_snapshot={"strategy_mode": "ema_cross"},
        now=datetime(2026, 2, 25, 12, 0, tzinfo=UTC),
        run_id="11111111-1111-1111-1111-111111111111",
    )

    assert meta["run_id"] == "11111111-1111-1111-1111-111111111111"
    assert meta["run_ts_utc"] == "2026-02-25T12:00:00Z"
    assert meta["git_sha"] == "deadbeef"
    assert meta["eval_context"] == {
        "market": "KR",
        "session_state": "AFTER_CLOSE",
        "eval_index_policy": "choose_eval_index:v1",
    }
    assert meta["config_snapshot"] == {"strategy_mode": "ema_cross"}


def test_build_run_meta_keeps_git_sha_optional_when_git_is_unavailable(
    monkeypatch,
) -> None:
    monkeypatch.delenv("GITHUB_SHA", raising=False)

    def _raise_os_error(*_args, **_kwargs):
        raise OSError("git unavailable")

    monkeypatch.setattr("sab.report.run_meta.subprocess.run", _raise_os_error)

    meta = build_run_meta(
        market="KR",
        session_state="AFTER_CLOSE",
        eval_index_policy="choose_eval_index:v1",
        config_snapshot=None,
        now=datetime(2026, 2, 25, 12, 0, tzinfo=UTC),
        run_id="11111111-1111-1111-1111-111111111111",
    )

    assert meta["git_sha"] is None


def test_write_buy_report_includes_standard_run_meta(tmp_path: Path) -> None:
    out_path = write_report(
        report_dir=tmp_path.as_posix(),
        provider="test",
        universe_count=1,
        candidates=[{"ticker": "AAPL.NASD", "name": "Apple", "price": "190"}],
        report_type="buy",
    )
    payload = json.loads(Path(out_path).read_text(encoding="utf-8"))

    assert re.fullmatch(
        r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}",
        payload["run_id"],
    )
    assert re.fullmatch(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z", payload["run_ts_utc"])
    assert "git_sha" in payload
    assert "eval_context" in payload
    assert "config_snapshot" in payload


def test_build_run_meta_includes_session_state_by_market_when_provided() -> None:
    meta = build_run_meta(
        market="MIXED",
        markets=["US", "KR"],
        session_state="INTRADAY",
        session_state_by_market={"US": "INTRADAY", "KR": "AFTER_CLOSE"},
        eval_index_policy="choose_eval_index:v1",
        config_snapshot=None,
    )

    assert meta["eval_context"]["session_state_by_market"] == {
        "KR": "AFTER_CLOSE",
        "US": "INTRADAY",
    }


def test_write_sell_report_includes_standard_run_meta(tmp_path: Path) -> None:
    row = SellReportRow(
        ticker="AAPL.NASD",
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
    )
    out_path = write_sell_report(
        report_dir=tmp_path.as_posix(),
        provider="test",
        evaluated=[row],
    )
    payload = json.loads(Path(out_path).read_text(encoding="utf-8"))

    assert re.fullmatch(
        r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}",
        payload["run_id"],
    )
    assert re.fullmatch(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z", payload["run_ts_utc"])
    assert "git_sha" in payload
    assert "eval_context" in payload
    assert "config_snapshot" in payload
