from __future__ import annotations

import json
import logging
import re
from pathlib import Path
from types import SimpleNamespace

from sab.entry import (
    _resolve_signal_eval_date,
    _select_latest_buy_report,
    evaluate_entry_candidates,
    run_entry,
)


def test_select_latest_buy_report_prefers_latest_date_and_duplicate(
    tmp_path: Path,
) -> None:
    names = [
        "2026-02-24.buy.json",
        "2026-02-24-2.buy.json",
        "2026-02-25.buy.json",
        "2026-02-25-1.buy.json",
    ]
    for name in names:
        (tmp_path / name).write_text("{}", encoding="utf-8")

    selected = _select_latest_buy_report(tmp_path.as_posix())

    assert selected.endswith("2026-02-25-1.buy.json")


def test_evaluate_entry_candidates_applies_gap_guard_and_strategy() -> None:
    candidates = [
        {
            "ticker": "AAPL.NASD",
            "close_value": 100.0,
            "gap_guard_pct_value": 0.03,
            "strategy_mode": "ema_cross",
        },
        {
            "ticker": "MSFT.NASD",
            "close_value": 100.0,
            "gap_guard_pct_value": 0.02,
            "strategy_mode": "ema_cross",
        },
        {
            "ticker": "NVDA.NASD",
            "close_value": 100.0,
            "gap_guard_pct_value": 0.02,
            "strategy_mode": "sma_ema_hybrid",
            "entry_state": "WATCH",
        },
    ]
    prices = {
        "AAPL.NASD": 101.0,  # +1% -> ENTER
        "MSFT.NASD": 104.0,  # +4% -> SKIP (guard breach)
        "NVDA.NASD": 101.0,  # WATCH -> REVIEW
    }

    rows, issues = evaluate_entry_candidates(
        candidates=candidates,
        price_lookup_fn=lambda ticker: prices.get(ticker),
        gap_breach_action="SKIP",
    )

    by_ticker = {row.ticker: row for row in rows}
    assert by_ticker["AAPL.NASD"].action == "ENTER"
    assert by_ticker["MSFT.NASD"].action == "SKIP"
    assert by_ticker["NVDA.NASD"].action == "REVIEW"
    assert issues == []


def test_evaluate_entry_candidates_marks_review_on_missing_data() -> None:
    candidates = [
        {
            "ticker": "AAPL.NASD",
            "price_value": 100.0,
            "gap_guard_pct": "±2.0%",
            "strategy_mode": "ema_cross",
        },
        {
            "ticker": "MSFT.NASD",
            "price_value": 100.0,
            "strategy_mode": "ema_cross",
        },
    ]

    rows, issues = evaluate_entry_candidates(
        candidates=candidates,
        price_lookup_fn=lambda _ticker: None,
        gap_breach_action="SKIP",
    )

    assert [row.action for row in rows] == ["REVIEW", "REVIEW"]
    assert any("price snapshot unavailable" in reason for reason in rows[0].reasons)
    assert any("gap guard unavailable" in reason for reason in rows[1].reasons)
    assert len(issues) == 3


def test_evaluate_entry_candidates_handles_legacy_guard_strings() -> None:
    candidates = [
        {
            "ticker": "AAPL.NASD",
            "price_value": 100.0,
            "gap_guard_pct": "±2.5%",
            "gap_guard_up_price": "102.50",
            "gap_guard_down_price": "97.50",
            "strategy_mode": "ema_cross",
        }
    ]
    rows, issues = evaluate_entry_candidates(
        candidates=candidates,
        price_lookup_fn=lambda _ticker: 101.0,
        gap_breach_action="SKIP",
    )

    assert len(rows) == 1
    assert rows[0].action == "ENTER"
    assert rows[0].gap_guard_pct == 0.025
    assert rows[0].gap_guard_up_price == 102.5
    assert rows[0].gap_guard_down_price == 97.5
    assert issues == []


def test_select_latest_buy_report_raises_when_missing(tmp_path: Path) -> None:
    try:
        _select_latest_buy_report(tmp_path.as_posix())
    except FileNotFoundError as exc:
        assert "No buy report files" in str(exc)
    else:
        raise AssertionError("expected FileNotFoundError")


def test_select_latest_buy_report_ignores_non_matching_files(tmp_path: Path) -> None:
    (tmp_path / "README.md").write_text("noop", encoding="utf-8")
    (tmp_path / "2026-02-25.sell.json").write_text("{}", encoding="utf-8")
    (tmp_path / "2026-02-25.buy.json").write_text("{}", encoding="utf-8")

    selected = _select_latest_buy_report(tmp_path.as_posix())
    assert selected.endswith("2026-02-25.buy.json")

    # sanity check file is valid JSON path for consumers
    payload = json.loads(Path(selected).read_text(encoding="utf-8"))
    assert payload == {}


def test_resolve_signal_eval_date_uses_market_session_date_from_run_ts_utc() -> None:
    source_report = {
        "run_ts_utc": "2026-02-26T01:30:00Z",
        "report_date": "2026-02-26",
    }

    resolved = _resolve_signal_eval_date(report=source_report, market="US")

    assert resolved == "2026-02-25"


def test_resolve_signal_eval_date_falls_back_to_report_date() -> None:
    source_report = {
        "run_ts_utc": "bad-timestamp",
        "report_date": "2026-02-25",
    }

    resolved = _resolve_signal_eval_date(report=source_report, market="KR")

    assert resolved == "2026-02-25"


def test_resolve_signal_eval_date_prefers_candidate_eval_date_majority() -> None:
    source_report = {
        "run_ts_utc": "2026-02-26T01:30:00Z",
        "report_date": "2026-02-26",
        "candidates": [
            {"ticker": "AAPL.NASD", "eval_date": "20260225"},
            {"ticker": "MSFT.NASD", "eval_date": "20260225"},
            {"ticker": "NVDA.NASD", "eval_date": "20260224"},
        ],
    }

    resolved = _resolve_signal_eval_date(report=source_report, market="US")

    assert resolved == "2026-02-25"


def test_resolve_signal_eval_date_breaks_tie_with_latest_date() -> None:
    source_report = {
        "run_ts_utc": "2026-02-26T01:30:00Z",
        "report_date": "2026-02-26",
        "candidates": [
            {"ticker": "AAPL.NASD", "eval_date": "20260224"},
            {"ticker": "MSFT.NASD", "eval_date": "20260225"},
        ],
    }

    resolved = _resolve_signal_eval_date(report=source_report, market="US")

    assert resolved == "2026-02-25"


def test_run_entry_e2e_normalizes_signal_eval_date_to_market_session(
    monkeypatch, tmp_path: Path
) -> None:
    report_dir = tmp_path / "reports"
    report_dir.mkdir(parents=True, exist_ok=True)
    buy_report_path = tmp_path / "source.buy.json"
    buy_report_path.write_text(
        json.dumps(
            {
                "run_ts_utc": "2026-02-26T01:30:00Z",
                "report_date": "2026-02-26",
                "eval_context": {"market": "US"},
                "candidates": [
                    {
                        "ticker": "AAPL.NASD",
                        "close_value": 100.0,
                        "gap_guard_pct_value": 0.03,
                        "strategy_mode": "ema_cross",
                    }
                ],
            }
        ),
        encoding="utf-8",
    )

    fake_cfg = SimpleNamespace(
        report_dir=report_dir.as_posix(),
        strategy_mode="ema_cross",
        gap_atr_multiplier=1.0,
        min_history_bars=50,
        data_dir=tmp_path.as_posix(),
        kis_app_key=None,
        kis_app_secret=None,
        kis_base_url=None,
        kis_min_interval_ms=None,
    )
    monkeypatch.setattr(
        "sab.entry.load_config", lambda provider_override=None: fake_cfg
    )

    exit_code = run_entry(
        buy_report_path=buy_report_path.as_posix(),
        provider="kis",
        mode="PRE_OPEN",
        market="US",
    )

    assert exit_code == 0
    out_files = sorted(report_dir.glob("*.entry.json"))
    assert len(out_files) == 1
    payload = json.loads(out_files[0].read_text(encoding="utf-8"))
    assert payload["signal_eval_date"] == "2026-02-25"
    assert payload["source_buy_report"] == "source.buy.json"
    assert re.fullmatch(r"\d{4}-\d{2}-\d{2}", payload["entry_session_date"])
    assert payload["entries"][0]["ticker"] == "AAPL.NASD"
    assert payload["entries"][0]["action"] == "REVIEW"
    assert payload["entries"][0]["entry_price"] is None


def test_run_entry_e2e_prefers_candidate_eval_date_over_run_ts(
    monkeypatch, tmp_path: Path
) -> None:
    report_dir = tmp_path / "reports"
    report_dir.mkdir(parents=True, exist_ok=True)
    buy_report_path = tmp_path / "source.buy.json"
    buy_report_path.write_text(
        json.dumps(
            {
                "run_ts_utc": "2026-02-26T01:30:00Z",
                "report_date": "2026-02-26",
                "eval_context": {"market": "US"},
                "candidates": [
                    {
                        "ticker": "AAPL.NASD",
                        "close_value": 100.0,
                        "gap_guard_pct_value": 0.03,
                        "strategy_mode": "ema_cross",
                        "eval_date": "20260224",
                    },
                    {
                        "ticker": "MSFT.NASD",
                        "close_value": 100.0,
                        "gap_guard_pct_value": 0.03,
                        "strategy_mode": "ema_cross",
                        "eval_date": "20260224",
                    },
                ],
            }
        ),
        encoding="utf-8",
    )

    fake_cfg = SimpleNamespace(
        report_dir=report_dir.as_posix(),
        strategy_mode="ema_cross",
        gap_atr_multiplier=1.0,
        min_history_bars=50,
        data_dir=tmp_path.as_posix(),
        kis_app_key=None,
        kis_app_secret=None,
        kis_base_url=None,
        kis_min_interval_ms=None,
    )
    monkeypatch.setattr(
        "sab.entry.load_config", lambda provider_override=None: fake_cfg
    )

    exit_code = run_entry(
        buy_report_path=buy_report_path.as_posix(),
        provider="kis",
        mode="PRE_OPEN",
        market="US",
    )

    assert exit_code == 0
    out_files = sorted(report_dir.glob("*.entry.json"))
    assert len(out_files) == 1
    payload = json.loads(out_files[0].read_text(encoding="utf-8"))
    assert payload["signal_eval_date"] == "2026-02-24"


def test_run_entry_e2e_reports_mixed_candidate_eval_dates_as_system_issue(
    monkeypatch, tmp_path: Path
) -> None:
    report_dir = tmp_path / "reports"
    report_dir.mkdir(parents=True, exist_ok=True)
    buy_report_path = tmp_path / "source.buy.json"
    buy_report_path.write_text(
        json.dumps(
            {
                "run_ts_utc": "2026-02-26T01:30:00Z",
                "report_date": "2026-02-26",
                "eval_context": {"market": "US"},
                "candidates": [
                    {
                        "ticker": "AAPL.NASD",
                        "close_value": 100.0,
                        "gap_guard_pct_value": 0.03,
                        "strategy_mode": "ema_cross",
                        "eval_date": "20260224",
                    },
                    {
                        "ticker": "MSFT.NASD",
                        "close_value": 100.0,
                        "gap_guard_pct_value": 0.03,
                        "strategy_mode": "ema_cross",
                        "eval_date": "20260225",
                    },
                ],
            }
        ),
        encoding="utf-8",
    )

    fake_cfg = SimpleNamespace(
        report_dir=report_dir.as_posix(),
        strategy_mode="ema_cross",
        gap_atr_multiplier=1.0,
        min_history_bars=50,
        data_dir=tmp_path.as_posix(),
        kis_app_key=None,
        kis_app_secret=None,
        kis_base_url=None,
        kis_min_interval_ms=None,
    )
    monkeypatch.setattr(
        "sab.entry.load_config", lambda provider_override=None: fake_cfg
    )

    exit_code = run_entry(
        buy_report_path=buy_report_path.as_posix(),
        provider="kis",
        mode="PRE_OPEN",
        market="US",
    )

    assert exit_code == 0
    out_files = sorted(report_dir.glob("*.entry.json"))
    assert len(out_files) == 1
    payload = json.loads(out_files[0].read_text(encoding="utf-8"))
    assert payload["signal_eval_date"] == "2026-02-25"
    assert any(
        issue.startswith("Mixed candidate eval_date values:")
        for issue in payload["system_issues"]
    )


def test_run_entry_e2e_uses_report_level_strategy_mode_for_legacy_candidates(
    monkeypatch, tmp_path: Path
) -> None:
    report_dir = tmp_path / "reports"
    report_dir.mkdir(parents=True, exist_ok=True)
    buy_report_path = tmp_path / "source.buy.json"
    buy_report_path.write_text(
        json.dumps(
            {
                "run_ts_utc": "2026-02-26T01:30:00Z",
                "eval_context": {"market": "KR"},
                "strategy_mode": "sma_ema_hybrid",
                "candidates": [
                    {
                        "ticker": "005930",
                        "close_value": 100.0,
                        "gap_guard_pct_value": 0.05,
                        "entry_state": "WATCH",
                    }
                ],
            }
        ),
        encoding="utf-8",
    )

    fake_cfg = SimpleNamespace(
        report_dir=report_dir.as_posix(),
        strategy_mode="ema_cross",
        gap_atr_multiplier=1.0,
        min_history_bars=50,
        data_dir=tmp_path.as_posix(),
        kis_app_key="k",
        kis_app_secret="s",
        kis_base_url="https://example.test",
        kis_min_interval_ms=None,
    )
    monkeypatch.setattr(
        "sab.entry.load_config", lambda provider_override=None: fake_cfg
    )

    class _FakeKISClient:
        def __init__(self, *_args: object, **_kwargs: object) -> None:
            pass

        def domestic_price_detail(self, *, ticker: str) -> dict[str, str]:
            assert ticker == "005930"
            return {"stck_prpr": "101.0"}

    monkeypatch.setattr("sab.entry.KISClient", _FakeKISClient)

    exit_code = run_entry(
        buy_report_path=buy_report_path.as_posix(),
        provider="kis",
        mode="PRE_OPEN",
        market="KR",
    )

    assert exit_code == 0
    out_files = sorted(report_dir.glob("*.entry.json"))
    assert len(out_files) == 1
    payload = json.loads(out_files[0].read_text(encoding="utf-8"))
    assert payload["entries"][0]["strategy_mode"] == "sma_ema_hybrid"
    assert payload["entries"][0]["entry_state"] == "WATCH"
    assert payload["entries"][0]["action"] == "REVIEW"
    assert any(
        "manual review" in reason.lower() for reason in payload["entries"][0]["reasons"]
    )


def test_run_entry_e2e_rejects_ambiguous_us_suffix_immediately(
    monkeypatch, tmp_path: Path, caplog
) -> None:
    report_dir = tmp_path / "reports"
    report_dir.mkdir(parents=True, exist_ok=True)
    buy_report_path = tmp_path / "source.buy.json"
    buy_report_path.write_text(
        json.dumps(
            {
                "run_ts_utc": "2026-02-26T01:30:00Z",
                "eval_context": {"market": "US"},
                "candidates": [
                    {
                        "ticker": "AAPL.US",
                        "close_value": 100.0,
                        "gap_guard_pct_value": 0.05,
                        "strategy_mode": "ema_cross",
                    }
                ],
            }
        ),
        encoding="utf-8",
    )

    fake_cfg = SimpleNamespace(
        report_dir=report_dir.as_posix(),
        strategy_mode="ema_cross",
        gap_atr_multiplier=1.0,
        min_history_bars=50,
        data_dir=tmp_path.as_posix(),
        kis_app_key=None,
        kis_app_secret=None,
        kis_base_url=None,
        kis_min_interval_ms=None,
    )
    monkeypatch.setattr(
        "sab.entry.load_config", lambda provider_override=None: fake_cfg
    )
    caplog.set_level(logging.ERROR)

    exit_code = run_entry(
        buy_report_path=buy_report_path.as_posix(),
        provider="kis",
        mode="PRE_OPEN",
        market="US",
    )

    assert exit_code == 1
    assert list(report_dir.glob("*.entry.json")) == []
    assert any(
        "explicit US exchange suffix required" in record.getMessage()
        for record in caplog.records
    )


def test_run_entry_e2e_uses_kis_us_snapshot_price(monkeypatch, tmp_path: Path) -> None:
    report_dir = tmp_path / "reports"
    report_dir.mkdir(parents=True, exist_ok=True)
    buy_report_path = tmp_path / "source.buy.json"
    buy_report_path.write_text(
        json.dumps(
            {
                "run_ts_utc": "2026-02-26T01:30:00Z",
                "eval_context": {"market": "US"},
                "candidates": [
                    {
                        "ticker": "AAPL.NASD",
                        "close_value": 100.0,
                        "gap_guard_pct_value": 0.05,
                        "strategy_mode": "ema_cross",
                    }
                ],
            }
        ),
        encoding="utf-8",
    )

    fake_cfg = SimpleNamespace(
        report_dir=report_dir.as_posix(),
        strategy_mode="ema_cross",
        gap_atr_multiplier=1.0,
        min_history_bars=50,
        data_dir=tmp_path.as_posix(),
        kis_app_key="k",
        kis_app_secret="s",
        kis_base_url="https://example.test",
        kis_min_interval_ms=None,
    )
    monkeypatch.setattr(
        "sab.entry.load_config", lambda provider_override=None: fake_cfg
    )

    class _FakeKISClient:
        def __init__(self, *_args: object, **_kwargs: object) -> None:
            pass

        def overseas_price_detail(
            self, *, symbol: str, exchange: str
        ) -> dict[str, str]:
            assert symbol == "AAPL"
            assert exchange == "NAS"
            return {"last": "101.5"}

    monkeypatch.setattr("sab.entry.KISClient", _FakeKISClient)

    exit_code = run_entry(
        buy_report_path=buy_report_path.as_posix(),
        provider="kis",
        mode="PRE_OPEN",
        market="US",
    )

    assert exit_code == 0
    out_files = sorted(report_dir.glob("*.entry.json"))
    assert len(out_files) == 1
    payload = json.loads(out_files[0].read_text(encoding="utf-8"))
    assert payload["entries"][0]["action"] == "ENTER"
    assert payload["entries"][0]["entry_price"] == 101.5


def test_run_entry_e2e_uses_kis_kr_snapshot_price_intraday(
    monkeypatch, tmp_path: Path
) -> None:
    report_dir = tmp_path / "reports"
    report_dir.mkdir(parents=True, exist_ok=True)
    buy_report_path = tmp_path / "source.buy.json"
    buy_report_path.write_text(
        json.dumps(
            {
                "run_ts_utc": "2026-02-26T01:30:00Z",
                "eval_context": {"market": "KR"},
                "candidates": [
                    {
                        "ticker": "005930",
                        "close_value": 100.0,
                        "gap_guard_pct_value": 0.05,
                        "strategy_mode": "ema_cross",
                    }
                ],
            }
        ),
        encoding="utf-8",
    )

    fake_cfg = SimpleNamespace(
        report_dir=report_dir.as_posix(),
        strategy_mode="ema_cross",
        gap_atr_multiplier=1.0,
        min_history_bars=50,
        data_dir=tmp_path.as_posix(),
        kis_app_key="k",
        kis_app_secret="s",
        kis_base_url="https://example.test",
        kis_min_interval_ms=None,
    )
    monkeypatch.setattr(
        "sab.entry.load_config", lambda provider_override=None: fake_cfg
    )

    class _FakeKISClient:
        def __init__(self, *_args: object, **_kwargs: object) -> None:
            pass

        def domestic_price_detail(self, *, ticker: str) -> dict[str, str]:
            assert ticker == "005930"
            return {"stck_prpr": "101.2"}

    monkeypatch.setattr("sab.entry.KISClient", _FakeKISClient)

    exit_code = run_entry(
        buy_report_path=buy_report_path.as_posix(),
        provider="kis",
        mode="INTRADAY",
        market="KR",
    )

    assert exit_code == 0
    out_files = sorted(report_dir.glob("*.entry.json"))
    assert len(out_files) == 1
    payload = json.loads(out_files[0].read_text(encoding="utf-8"))
    assert payload["entries"][0]["action"] == "ENTER"
    assert payload["entries"][0]["entry_price"] == 101.2


def test_run_entry_e2e_kr_pre_open_requires_positive_live_price(
    monkeypatch, tmp_path: Path
) -> None:
    report_dir = tmp_path / "reports"
    report_dir.mkdir(parents=True, exist_ok=True)
    buy_report_path = tmp_path / "source.buy.json"
    buy_report_path.write_text(
        json.dumps(
            {
                "run_ts_utc": "2026-02-26T01:30:00Z",
                "eval_context": {"market": "KR"},
                "candidates": [
                    {
                        "ticker": "005930",
                        "close_value": 100.0,
                        "gap_guard_pct_value": 0.05,
                        "strategy_mode": "ema_cross",
                    }
                ],
            }
        ),
        encoding="utf-8",
    )

    fake_cfg = SimpleNamespace(
        report_dir=report_dir.as_posix(),
        strategy_mode="ema_cross",
        gap_atr_multiplier=1.0,
        min_history_bars=50,
        data_dir=tmp_path.as_posix(),
        kis_app_key="k",
        kis_app_secret="s",
        kis_base_url="https://example.test",
        kis_min_interval_ms=None,
    )
    monkeypatch.setattr(
        "sab.entry.load_config", lambda provider_override=None: fake_cfg
    )

    class _FakeKISClient:
        def __init__(self, *_args: object, **_kwargs: object) -> None:
            pass

        def domestic_price_detail(self, *, ticker: str) -> dict[str, str]:
            assert ticker == "005930"
            return {
                "stck_prpr": "0",
                "stck_prdy_clpr": "101.0",
            }

    monkeypatch.setattr("sab.entry.KISClient", _FakeKISClient)

    exit_code = run_entry(
        buy_report_path=buy_report_path.as_posix(),
        provider="kis",
        mode="PRE_OPEN",
        market="KR",
    )

    assert exit_code == 0
    out_files = sorted(report_dir.glob("*.entry.json"))
    assert len(out_files) == 1
    payload = json.loads(out_files[0].read_text(encoding="utf-8"))
    assert payload["entries"][0]["action"] == "REVIEW"
    assert payload["entries"][0]["entry_price"] is None


def test_run_entry_e2e_uses_pykrx_after_close_price(
    monkeypatch, tmp_path: Path
) -> None:
    report_dir = tmp_path / "reports"
    report_dir.mkdir(parents=True, exist_ok=True)
    buy_report_path = tmp_path / "source.buy.json"
    buy_report_path.write_text(
        json.dumps(
            {
                "run_ts_utc": "2026-02-26T01:30:00Z",
                "eval_context": {"market": "KR"},
                "candidates": [
                    {
                        "ticker": "005930",
                        "close_value": 100.0,
                        "gap_guard_pct_value": 0.05,
                        "strategy_mode": "ema_cross",
                    }
                ],
            }
        ),
        encoding="utf-8",
    )

    fake_cfg = SimpleNamespace(
        report_dir=report_dir.as_posix(),
        strategy_mode="ema_cross",
        gap_atr_multiplier=1.0,
        min_history_bars=50,
        data_dir=tmp_path.as_posix(),
        kis_app_key=None,
        kis_app_secret=None,
        kis_base_url=None,
        kis_min_interval_ms=None,
    )
    monkeypatch.setattr(
        "sab.entry.load_config", lambda provider_override=None: fake_cfg
    )

    class _FakePykrxClient:
        def __init__(self, *_args: object, **_kwargs: object) -> None:
            pass

        def daily_candles(
            self, ticker: str, *, count: int, adjusted: bool
        ) -> list[dict[str, float]]:
            assert ticker == "005930"
            assert count == 1
            assert adjusted is False
            return [{"close": 101.0}]

    monkeypatch.setattr("sab.entry.PykrxClient", _FakePykrxClient)

    exit_code = run_entry(
        buy_report_path=buy_report_path.as_posix(),
        provider="pykrx",
        mode="AFTER_CLOSE",
        market="KR",
    )

    assert exit_code == 0
    out_files = sorted(report_dir.glob("*.entry.json"))
    assert len(out_files) == 1
    payload = json.loads(out_files[0].read_text(encoding="utf-8"))
    assert payload["entries"][0]["action"] == "ENTER"
    assert payload["entries"][0]["entry_price"] == 101.0
