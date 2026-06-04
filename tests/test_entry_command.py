from __future__ import annotations

import json
import logging
import re
from collections.abc import Callable
from pathlib import Path
from types import SimpleNamespace
from typing import cast

import pytest
import sab.entry as entry
from sab.config import Config
from sab.config_loader import ConfigLoadError
from sab.entry import (
    _collect_candidate_eval_date_issues,
    _resolve_entry_artifact_date_context,
    _resolve_entry_fatal_missing_price_ratio,
    _resolve_signal_eval_date,
    _select_latest_buy_report,
    evaluate_entry_candidates,
    run_entry,
)
from sab.holdings_loader import Holding, HoldingsData, HoldingSettings


def _portfolio_config(
    *,
    max_active_holdings: int | None = None,
    max_new_entries_kr: int | None = None,
    max_new_entries_us: int | None = None,
) -> SimpleNamespace:
    return SimpleNamespace(
        max_active_holdings=max_active_holdings,
        max_new_entries_kr=max_new_entries_kr,
        max_new_entries_us=max_new_entries_us,
    )


def _holdings_data(rows: list[Holding]) -> HoldingsData:
    return HoldingsData(
        path=None,
        settings=HoldingSettings(),
        holdings=rows,
    )


def _entry_candidate(
    ticker: str,
    *,
    raw_close: float = 100.0,
    gap_guard_value: float | None = 0.03,
    strategy_mode: str = "ema_cross",
    eval_date: str = "20260225",
    **extra: object,
) -> dict[str, object]:
    candidate = {
        "ticker": ticker,
        "signal_price_basis": "adjusted",
        "signal_close_adjusted_value": 100.0,
        "entry_reference_close_raw_value": raw_close,
        "entry_reference_eval_date": eval_date,
        "eval_date": eval_date,
        "gap_guard_pct_value": gap_guard_value,
        "strategy_mode": strategy_mode,
    }
    candidate.update(extra)
    return candidate


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


def test_entry_fatal_missing_price_ratio_rejects_invalid_env_in_ci(
    monkeypatch,
) -> None:
    monkeypatch.setenv("GITHUB_ACTIONS", "true")
    monkeypatch.setenv("ENTRY_FATAL_MISSING_PRICE_RATIO", "not-a-ratio")

    with pytest.raises(ConfigLoadError, match="ENTRY_FATAL_MISSING_PRICE_RATIO"):
        _resolve_entry_fatal_missing_price_ratio()


def test_evaluate_entry_candidates_applies_gap_guard_and_strategy() -> None:
    candidates = [
        _entry_candidate("AAPL.NASD", raw_close=100.0, gap_guard_value=0.03),
        _entry_candidate("MSFT.NASD", raw_close=100.0, gap_guard_value=0.02),
        _entry_candidate(
            "NVDA.NASD",
            raw_close=100.0,
            gap_guard_value=0.02,
            strategy_mode="sma_ema_hybrid",
            entry_state="WATCH",
        ),
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


def test_evaluate_entry_candidates_skips_hybrid_ready_on_trigger_fail() -> None:
    candidates = [
        _entry_candidate(
            "005930",
            raw_close=100.0,
            gap_guard_value=0.03,
            strategy_mode="sma_ema_hybrid",
            entry_state="READY",
            pattern="swing_high_breakout",
            entry_trigger_price_value=102.0,
            entry_trigger_operator="gte",
            entry_trigger_label="swing high",
        )
    ]

    rows, issues = evaluate_entry_candidates(
        candidates=candidates,
        price_lookup_fn=lambda _ticker: 101.0,
        gap_breach_action="SKIP",
    )

    assert len(rows) == 1
    assert rows[0].action == "SKIP"
    assert any("hybrid trigger guard failed" in reason for reason in rows[0].reasons)
    assert issues == []


def test_evaluate_entry_candidates_normalizes_adjusted_hybrid_trigger_to_raw_reference() -> (
    None
):
    candidates = [
        _entry_candidate(
            "005930",
            raw_close=200.0,
            gap_guard_value=0.03,
            strategy_mode="sma_ema_hybrid",
            entry_state="READY",
            pattern="swing_high_breakout",
            entry_trigger_price_value=102.0,
            entry_trigger_price_basis="adjusted",
            entry_trigger_operator="gte",
            entry_trigger_label="swing high",
        )
    ]

    rows, issues = evaluate_entry_candidates(
        candidates=candidates,
        price_lookup_fn=lambda _ticker: 203.0,
        gap_breach_action="SKIP",
    )

    assert len(rows) == 1
    assert rows[0].action == "SKIP"
    assert any(
        "hybrid trigger guard failed (203.00 < swing high 204.00)" in reason
        for reason in rows[0].reasons
    )
    assert issues == []


def test_evaluate_entry_candidates_reviews_malformed_hybrid_trigger_guard() -> None:
    candidates = [
        _entry_candidate(
            "005930",
            raw_close=100.0,
            gap_guard_value=0.03,
            strategy_mode="sma_ema_hybrid",
            entry_state="READY",
            pattern="swing_high_breakout",
            entry_trigger_price_value="bad",
            entry_trigger_operator="gte",
            entry_trigger_label="swing high",
        )
    ]

    rows, issues = evaluate_entry_candidates(
        candidates=candidates,
        price_lookup_fn=lambda _ticker: 101.0,
        gap_breach_action="SKIP",
    )

    assert len(rows) == 1
    assert rows[0].action == "REVIEW"
    assert any("hybrid trigger guard invalid" in reason for reason in rows[0].reasons)
    assert issues == ["005930: hybrid trigger guard invalid"]


def test_evaluate_entry_candidates_marks_review_on_missing_data() -> None:
    candidates = [
        _entry_candidate(
            "AAPL.NASD",
            raw_close=100.0,
            gap_guard_value=0.02,
            gap_guard_pct_value=None,
            gap_guard_pct="±2.0%",
        ),
        {
            "ticker": "MSFT.NASD",
            "signal_price_basis": "adjusted",
            "signal_close_adjusted_value": 100.0,
            "entry_reference_close_raw_value": 100.0,
            "entry_reference_eval_date": "20260225",
            "eval_date": "20260225",
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


def test_evaluate_entry_candidates_skips_gap_guard_when_disabled() -> None:
    candidates = [
        _entry_candidate("AAPL.NASD", raw_close=100.0, gap_guard_value=None),
        _entry_candidate(
            "MSFT.NASD",
            raw_close=100.0,
            gap_guard_value=None,
            strategy_mode="sma_ema_hybrid",
            entry_state="READY",
        ),
        _entry_candidate(
            "NVDA.NASD",
            raw_close=100.0,
            gap_guard_value=None,
            strategy_mode="sma_ema_hybrid",
            entry_state="WATCH",
        ),
    ]
    prices = {
        "AAPL.NASD": 101.0,
        "MSFT.NASD": 101.0,
        "NVDA.NASD": 101.0,
    }

    rows, issues = evaluate_entry_candidates(
        candidates=candidates,
        price_lookup_fn=lambda ticker: prices.get(ticker),
        gap_breach_action="SKIP",
        allow_missing_gap_guard=True,
    )

    by_ticker = {row.ticker: row for row in rows}
    assert by_ticker["AAPL.NASD"].action == "ENTER"
    assert by_ticker["MSFT.NASD"].action == "ENTER"
    assert by_ticker["NVDA.NASD"].action == "REVIEW"
    assert "gap guard unavailable" not in by_ticker["AAPL.NASD"].reasons
    assert issues == []


def test_evaluate_entry_candidates_handles_legacy_guard_strings() -> None:
    candidates = [
        _entry_candidate(
            "AAPL.NASD",
            raw_close=100.0,
            gap_guard_value=0.025,
            gap_guard_pct_value=None,
            gap_guard_pct="±2.5%",
            gap_guard_up_price="102.50",
            gap_guard_down_price="97.50",
        )
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


def test_evaluate_entry_candidates_marks_legacy_basis_as_review() -> None:
    rows, issues = evaluate_entry_candidates(
        candidates=[
            {
                "ticker": "AAPL.NASD",
                "close_value": 100.0,
                "gap_guard_pct_value": 0.03,
                "strategy_mode": "ema_cross",
            }
        ],
        price_lookup_fn=lambda _ticker: 101.0,
        gap_breach_action="SKIP",
    )

    assert len(rows) == 1
    assert rows[0].action == "REVIEW"
    assert "signal price basis unavailable" in rows[0].reasons
    assert issues == ["AAPL.NASD: signal price basis unavailable"]


def test_evaluate_entry_candidates_marks_basis_date_mismatch_as_review() -> None:
    rows, issues = evaluate_entry_candidates(
        candidates=[
            _entry_candidate(
                "AAPL.NASD",
                raw_close=100.0,
                eval_date="20260225",
                entry_reference_eval_date="20260224",
            )
        ],
        price_lookup_fn=lambda _ticker: 101.0,
        gap_breach_action="SKIP",
    )

    assert len(rows) == 1
    assert rows[0].action == "REVIEW"
    assert "entry reference eval_date mismatch" in rows[0].reasons[0]
    assert any("entry reference eval_date mismatch" in issue for issue in issues)


def test_evaluate_entry_candidate_markets_preserves_source_order_and_issue_contract(
    monkeypatch,
) -> None:
    assert hasattr(entry, "_evaluate_entry_candidate_markets")
    helper = entry._evaluate_entry_candidate_markets
    source_candidates = [
        _entry_candidate("AAPL.NASD"),
        _entry_candidate("005930"),
        _entry_candidate("MSFT.NASD"),
    ]
    candidates_by_market = {
        "KR": [source_candidates[1]],
        "US": [source_candidates[0], source_candidates[2]],
    }

    def fake_price_lookup(
        *, cfg: object, provider: str, mode: str, market: str
    ) -> tuple[Callable[[str], float | None], list[str]]:
        del cfg, provider, mode
        prices_by_market: dict[str, dict[str, float | None]] = {
            "KR": {"005930": 101.0},
            "US": {"AAPL.NASD": 101.0, "MSFT.NASD": None},
        }
        market_prices = prices_by_market[market]
        return lambda ticker: market_prices.get(ticker), ["provider issue"]

    monkeypatch.setattr("sab.entry._make_price_lookup", fake_price_lookup)

    rows, issues = helper(
        cfg=cast(Config, SimpleNamespace()),
        provider="kis",
        mode="PRE_OPEN",
        resolved_markets=["KR", "US"],
        candidates_by_market=candidates_by_market,
        source_candidates=source_candidates,
        market_override=None,
        default_strategy_mode="ema_cross",
        allow_missing_gap_guard=False,
    )

    assert [row.ticker for row in rows] == ["AAPL.NASD", "005930", "MSFT.NASD"]
    assert [row.action for row in rows] == ["ENTER", "ENTER", "REVIEW"]
    assert issues == [
        "provider issue",
        "MSFT.NASD: price snapshot unavailable",
    ]


def test_select_latest_buy_report_raises_when_missing(tmp_path: Path) -> None:
    with pytest.raises(FileNotFoundError, match="No buy report files"):
        _select_latest_buy_report(tmp_path.as_posix())


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


def test_resolve_entry_artifact_date_context_preserves_single_market_contract(
    monkeypatch,
) -> None:
    monkeypatch.setattr("sab.entry._entry_session_date", lambda market: "2026-02-26")
    source_report = {
        "run_ts_utc": "2026-02-26T01:30:00Z",
        "report_date": "2026-02-26",
        "eval_context": {"market": "US"},
    }
    candidates_by_market = {
        "US": [
            _entry_candidate("AAPL.NASD", eval_date="20260224"),
            _entry_candidate("MSFT.NASD", eval_date="20260225"),
        ]
    }

    context = _resolve_entry_artifact_date_context(
        source_report=source_report,
        candidates_by_market=candidates_by_market,
        resolved_markets=["US"],
    )

    assert context.artifact_market == "US"
    assert context.artifact_markets is None
    assert context.signal_eval_date == "2026-02-25"
    assert context.entry_session_date == "2026-02-26"
    assert context.signal_eval_date_by_market is None
    assert context.entry_session_date_by_market is None


def test_resolve_entry_artifact_date_context_preserves_mixed_market_contract(
    monkeypatch,
) -> None:
    session_dates = {"KR": "2026-02-27", "US": "2026-02-26"}
    monkeypatch.setattr(
        "sab.entry._entry_session_date", lambda market: session_dates[market]
    )
    source_report = {
        "run_ts_utc": "2026-02-26T01:30:00Z",
        "eval_context": {"market": "MIXED", "markets": ["KR", "US"]},
    }
    candidates_by_market = {
        "KR": [_entry_candidate("005930", eval_date="20260226")],
        "US": [_entry_candidate("AAPL.NASD", eval_date="20260225")],
    }

    context = _resolve_entry_artifact_date_context(
        source_report=source_report,
        candidates_by_market=candidates_by_market,
        resolved_markets=["KR", "US"],
    )

    assert context.artifact_market == "MIXED"
    assert context.artifact_markets == ["KR", "US"]
    assert context.signal_eval_date is None
    assert context.entry_session_date is None
    assert context.signal_eval_date_by_market == {
        "KR": "2026-02-26",
        "US": "2026-02-25",
    }
    assert context.entry_session_date_by_market == {
        "KR": "2026-02-27",
        "US": "2026-02-26",
    }


def test_collect_candidate_eval_date_issues_preserves_single_market_preview() -> None:
    source_report: dict[str, object] = {}
    candidates_by_market = {
        "US": [
            _entry_candidate("AAPL.NASD", eval_date="20260220"),
            _entry_candidate("MSFT.NASD", eval_date="20260221"),
            _entry_candidate("NVDA.NASD", eval_date="20260222"),
            _entry_candidate("TSLA.NASD", eval_date="20260223"),
            _entry_candidate("META.NASD", eval_date="20260224"),
            _entry_candidate("GOOG.NASD", eval_date="20260225"),
        ]
    }

    issues = _collect_candidate_eval_date_issues(
        source_report=source_report,
        candidates_by_market=candidates_by_market,
        resolved_markets=["US"],
    )

    assert issues == [
        "Mixed candidate eval_date values: "
        "2026-02-20, 2026-02-21, 2026-02-22, 2026-02-23, 2026-02-24, +1 more"
    ]


def test_collect_candidate_eval_date_issues_scopes_mixed_market_message() -> None:
    source_report: dict[str, object] = {}
    candidates_by_market = {
        "KR": [
            _entry_candidate("005930", eval_date="20260225"),
            _entry_candidate("000660", eval_date="20260226"),
        ],
        "US": [_entry_candidate("AAPL.NASD", eval_date="20260225")],
    }

    issues = _collect_candidate_eval_date_issues(
        source_report=source_report,
        candidates_by_market=candidates_by_market,
        resolved_markets=["KR", "US"],
    )

    assert issues == ["Mixed candidate eval_date values for KR: 2026-02-25, 2026-02-26"]


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
                "candidates": [_entry_candidate("AAPL.NASD")],
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
        holdings=_holdings_data([]),
        portfolio=_portfolio_config(),
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
            return {"last": "101.0", "xymd": "20260226"}

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
    assert payload["signal_eval_date"] == "2026-02-25"
    assert payload["source_buy_report"] == "source.buy.json"
    assert re.fullmatch(r"\d{4}-\d{2}-\d{2}", payload["entry_session_date"])
    assert payload["entries"][0]["ticker"] == "AAPL.NASD"
    assert payload["entries"][0]["action"] == "ENTER"
    assert payload["entries"][0]["entry_price"] == 101.0


def test_run_entry_e2e_returns_exit_1_when_all_prices_are_missing(
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
                "candidates": [_entry_candidate("AAPL.NASD")],
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
        holdings=_holdings_data([]),
        portfolio=_portfolio_config(),
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

    assert exit_code == 1
    out_files = sorted(report_dir.glob("*.entry.json"))
    assert len(out_files) == 1
    payload = json.loads(out_files[0].read_text(encoding="utf-8"))
    assert payload["entries"][0]["action"] == "REVIEW"
    assert payload["entries"][0]["entry_price"] is None
    assert any(
        "provider not configured" in issue.lower() for issue in payload["system_issues"]
    )


def test_run_entry_e2e_reviews_pre_open_kis_price_without_datetime_marker(
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
                "candidates": [_entry_candidate("AAPL.NASD")],
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
        holdings=_holdings_data([]),
        portfolio=_portfolio_config(),
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
            return {"last": "101.0", "entry_snapshot_state": "PRE_OPEN"}

    monkeypatch.setattr("sab.entry.KISClient", _FakeKISClient)

    exit_code = run_entry(
        buy_report_path=buy_report_path.as_posix(),
        provider="kis",
        mode="PRE_OPEN",
        market="US",
    )

    assert exit_code == 1
    payload = json.loads(
        next(report_dir.glob("*.entry.json")).read_text(encoding="utf-8")
    )
    assert payload["entries"][0]["action"] == "REVIEW"
    assert payload["entries"][0]["entry_price"] is None
    assert any(
        "price snapshot unavailable" in reason
        for reason in payload["entries"][0]["reasons"]
    )
    assert payload["summary"]["missing_entry_price_count"] == 1


def test_run_entry_e2e_writes_empty_report_when_buy_candidates_are_empty(
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
                "candidates": [],
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
        holdings=_holdings_data([]),
        portfolio=_portfolio_config(),
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
    assert payload["market"] == "US"
    assert payload["entries"] == []
    assert payload["tickers"] == []
    assert payload["summary"] == {
        "entry_count": 0,
        "action_counts": {},
        "system_issue_count": 0,
        "missing_entry_price_count": 0,
        "missing_entry_price_ratio": 0.0,
        "portfolio_blocked_count": 0,
        "portfolio_blocked_by_market": {},
    }
    assert payload["source_buy_report"] == "source.buy.json"


def test_run_entry_e2e_threshold_zero_does_not_fail_when_prices_available(
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
                "candidates": [_entry_candidate("AAPL.NASD")],
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
        holdings=_holdings_data([]),
        portfolio=_portfolio_config(),
    )
    monkeypatch.setattr(
        "sab.entry.load_config", lambda provider_override=None: fake_cfg
    )
    monkeypatch.setenv("ENTRY_FATAL_MISSING_PRICE_RATIO", "0.0")

    class _FakeKISClient:
        def __init__(self, *_args: object, **_kwargs: object) -> None:
            pass

        def overseas_price_detail(
            self, *, symbol: str, exchange: str
        ) -> dict[str, str]:
            assert symbol == "AAPL"
            assert exchange == "NAS"
            return {"last": "101.0", "xymd": "20260226"}

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
    assert payload["entries"][0]["entry_price"] == 101.0


def test_run_entry_e2e_skips_gap_guard_when_filter_disabled(
    monkeypatch, tmp_path: Path
) -> None:
    report_dir = tmp_path / "reports"
    report_dir.mkdir(parents=True, exist_ok=True)
    buy_report_path = tmp_path / "source.buy.json"
    candidate = _entry_candidate("AAPL.NASD", gap_guard_value=None)
    candidate.pop("gap_guard_pct_value", None)
    buy_report_path.write_text(
        json.dumps(
            {
                "run_ts_utc": "2026-02-26T01:30:00Z",
                "report_date": "2026-02-26",
                "eval_context": {"market": "US"},
                "candidates": [candidate],
            }
        ),
        encoding="utf-8",
    )

    fake_cfg = SimpleNamespace(
        report_dir=report_dir.as_posix(),
        strategy_mode="ema_cross",
        gap_atr_multiplier=0.0,
        min_history_bars=50,
        data_dir=tmp_path.as_posix(),
        kis_app_key="k",
        kis_app_secret="s",
        kis_base_url="https://example.test",
        kis_min_interval_ms=None,
        holdings=_holdings_data([]),
        portfolio=_portfolio_config(),
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
            return {"last": "101.0", "xymd": "20260226"}

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
    assert payload["entries"][0]["gap_guard_pct"] is None
    assert "gap guard unavailable" not in payload["entries"][0]["reasons"]
    assert not any(
        "gap guard unavailable" in issue for issue in payload["system_issues"]
    )


def test_run_entry_e2e_uses_source_report_gap_guard_disabled_config(
    monkeypatch, tmp_path: Path
) -> None:
    report_dir = tmp_path / "reports"
    report_dir.mkdir(parents=True, exist_ok=True)
    buy_report_path = tmp_path / "source.buy.json"
    candidate = _entry_candidate("AAPL.NASD", gap_guard_value=None)
    candidate.pop("gap_guard_pct_value", None)
    buy_report_path.write_text(
        json.dumps(
            {
                "run_ts_utc": "2026-02-26T01:30:00Z",
                "report_date": "2026-02-26",
                "eval_context": {"market": "US"},
                "config_snapshot": {"gap_atr_multiplier": 0.0},
                "candidates": [candidate],
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
        holdings=_holdings_data([]),
        portfolio=_portfolio_config(),
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
            return {"last": "101.0", "xymd": "20260226"}

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
    assert payload["config_snapshot"]["gap_atr_multiplier"] == 1.0
    assert payload["config_snapshot"]["effective_gap_atr_multiplier"] == 0.0
    assert payload["config_snapshot"]["source_report_gap_atr_multiplier"] == 0.0
    assert "gap guard unavailable" not in payload["entries"][0]["reasons"]


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
                    _entry_candidate("AAPL.NASD", eval_date="20260224"),
                    _entry_candidate("MSFT.NASD", eval_date="20260224"),
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
            assert exchange == "NAS"
            return {
                "last": "101.0" if symbol == "AAPL" else "101.2",
                "xymd": "20260226",
            }

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
                    _entry_candidate("AAPL.NASD", eval_date="20260224"),
                    _entry_candidate("MSFT.NASD", eval_date="20260225"),
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
            assert exchange == "NAS"
            return {
                "last": "101.0" if symbol == "AAPL" else "101.2",
                "xymd": "20260226",
            }

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
                    _entry_candidate(
                        "005930",
                        eval_date="20260225",
                        strategy_mode="sma_ema_hybrid",
                        entry_state="WATCH",
                    )
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
            return {"stck_prpr": "101.0", "stck_cntg_hour": "090001"}

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


def test_run_entry_e2e_handles_mixed_market_buy_report(
    monkeypatch, tmp_path: Path
) -> None:
    report_dir = tmp_path / "reports"
    report_dir.mkdir(parents=True, exist_ok=True)
    buy_report_path = tmp_path / "source.buy.json"
    buy_report_path.write_text(
        json.dumps(
            {
                "run_ts_utc": "2026-02-26T01:30:00Z",
                "eval_context": {"market": "MIXED", "markets": ["KR", "US"]},
                "candidates": [
                    _entry_candidate("005930", eval_date="20260226"),
                    _entry_candidate("AAPL.NASD", eval_date="20260225"),
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
            return {"stck_prpr": "101.2", "stck_cntg_hour": "090001"}

        def overseas_price_detail(
            self, *, symbol: str, exchange: str
        ) -> dict[str, str]:
            assert symbol == "AAPL"
            assert exchange == "NAS"
            return {"last": "101.0", "xymd": "20260226"}

    monkeypatch.setattr("sab.entry.KISClient", _FakeKISClient)

    exit_code = run_entry(
        buy_report_path=buy_report_path.as_posix(),
        provider="kis",
        mode="PRE_OPEN",
        market=None,
    )

    assert exit_code == 0
    out_files = sorted(report_dir.glob("*.entry.json"))
    assert len(out_files) == 1
    payload = json.loads(out_files[0].read_text(encoding="utf-8"))
    assert payload["market"] == "MIXED"
    assert payload["markets"] == ["KR", "US"]
    assert payload["signal_eval_date"] is None
    assert payload["entry_session_date"] is None
    assert payload["signal_eval_date_by_market"] == {
        "KR": "2026-02-26",
        "US": "2026-02-25",
    }
    assert re.fullmatch(
        r"\d{4}-\d{2}-\d{2}", payload["entry_session_date_by_market"]["KR"]
    )
    assert re.fullmatch(
        r"\d{4}-\d{2}-\d{2}", payload["entry_session_date_by_market"]["US"]
    )
    assert payload["eval_context"]["market"] == "MIXED"
    assert payload["eval_context"]["markets"] == ["KR", "US"]
    assert {row["ticker"] for row in payload["entries"]} == {"005930", "AAPL.NASD"}
    assert not any(
        issue.startswith("Mixed candidate eval_date values:")
        for issue in payload["system_issues"]
    )


def test_run_entry_e2e_market_override_filters_mixed_buy_report(
    monkeypatch, tmp_path: Path
) -> None:
    report_dir = tmp_path / "reports"
    report_dir.mkdir(parents=True, exist_ok=True)
    buy_report_path = tmp_path / "source.buy.json"
    buy_report_path.write_text(
        json.dumps(
            {
                "run_ts_utc": "2026-02-26T01:30:00Z",
                "eval_context": {"market": "MIXED", "markets": ["KR", "US"]},
                "candidates": [
                    _entry_candidate("005930", eval_date="20260226"),
                    _entry_candidate("AAPL.NASD", eval_date="20260225"),
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
            return {"last": "101.0", "xymd": "20260226"}

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
    assert payload["market"] == "US"
    assert payload["entries"] == [
        {
            "ticker": "AAPL.NASD",
            "action": "ENTER",
            "reasons": ["entry conditions satisfied"],
            "signal_close": 100.0,
            "entry_price": 101.0,
            "gap_pct": 0.01,
            "gap_guard_pct": 0.03,
            "gap_guard_up_price": 103.0,
            "gap_guard_down_price": 97.0,
            "strategy_mode": "ema_cross",
            "pattern": None,
            "entry_state": None,
        }
    ]


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
                "candidates": [_entry_candidate("AAPL.US", gap_guard_value=0.05)],
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
                "candidates": [_entry_candidate("AAPL.NASD", gap_guard_value=0.05)],
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
            return {"last": "101.5", "xymd": "20260226"}

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
                "candidates": [_entry_candidate("005930", gap_guard_value=0.05)],
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
            return {"stck_prpr": "101.2", "stck_cntg_hour": "090001"}

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
                "candidates": [_entry_candidate("005930", gap_guard_value=0.05)],
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

    assert exit_code == 1
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
                "candidates": [_entry_candidate("005930", gap_guard_value=0.05)],
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


def test_run_entry_e2e_applies_max_active_holdings_portfolio_guard(
    monkeypatch, tmp_path: Path
) -> None:
    report_dir = tmp_path / "reports"
    report_dir.mkdir(parents=True, exist_ok=True)
    buy_report_path = tmp_path / "source.buy.json"
    buy_report_path.write_text(
        json.dumps(
            {
                "run_ts_utc": "2026-02-26T01:30:00Z",
                "eval_context": {"market": "US"},
                "candidates": [_entry_candidate("AAPL.NASD", gap_guard_value=0.05)],
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
        holdings=_holdings_data(
            [Holding(ticker="MSFT.NASD", quantity=1, entry_price=100.0)]
        ),
        portfolio=_portfolio_config(max_active_holdings=1),
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
            return {"last": "101.0", "xymd": "20260226"}

    monkeypatch.setattr("sab.entry.KISClient", _FakeKISClient)

    exit_code = run_entry(
        buy_report_path=buy_report_path.as_posix(),
        provider="kis",
        mode="PRE_OPEN",
        market="US",
    )

    assert exit_code == 0
    payload = json.loads(
        next(report_dir.glob("*.entry.json")).read_text(encoding="utf-8")
    )
    assert payload["entries"][0]["action"] == "SKIP"
    assert "portfolio max active holdings reached" in payload["entries"][0]["reasons"]
    assert payload["summary"]["portfolio_blocked_count"] == 1
    assert payload["summary"]["portfolio_blocked_by_market"] == {"US": 1}


def test_run_entry_e2e_loads_holdings_from_holdings_path_for_portfolio_guard(
    monkeypatch, tmp_path: Path
) -> None:
    report_dir = tmp_path / "reports"
    report_dir.mkdir(parents=True, exist_ok=True)
    holdings_path = tmp_path / "holdings.yaml"
    holdings_path.write_text(
        """
holdings:
  - ticker: MSFT.NASD
    quantity: 1
    entry_price: 100
    entry_currency: USD
""".strip()
        + "\n",
        encoding="utf-8",
    )
    buy_report_path = tmp_path / "source.buy.json"
    buy_report_path.write_text(
        json.dumps(
            {
                "run_ts_utc": "2026-02-26T01:30:00Z",
                "eval_context": {"market": "US"},
                "candidates": [_entry_candidate("AAPL.NASD", gap_guard_value=0.05)],
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
        holdings_path=holdings_path.as_posix(),
        holdings=_holdings_data([]),
        portfolio=_portfolio_config(max_active_holdings=1),
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
            return {"last": "101.0", "xymd": "20260226"}

    monkeypatch.setattr("sab.entry.KISClient", _FakeKISClient)

    exit_code = run_entry(
        buy_report_path=buy_report_path.as_posix(),
        provider="kis",
        mode="PRE_OPEN",
        market="US",
    )

    assert exit_code == 0
    payload = json.loads(
        next(report_dir.glob("*.entry.json")).read_text(encoding="utf-8")
    )
    assert payload["entries"][0]["action"] == "SKIP"
    assert "portfolio max active holdings reached" in payload["entries"][0]["reasons"]
    assert payload["summary"]["portfolio_blocked_count"] == 1


def test_run_entry_e2e_applies_market_portfolio_guard_without_touching_review_rows(
    monkeypatch, tmp_path: Path
) -> None:
    report_dir = tmp_path / "reports"
    report_dir.mkdir(parents=True, exist_ok=True)
    buy_report_path = tmp_path / "source.buy.json"
    buy_report_path.write_text(
        json.dumps(
            {
                "run_ts_utc": "2026-02-26T01:30:00Z",
                "eval_context": {"market": "MIXED", "markets": ["KR", "US"]},
                "candidates": [
                    _entry_candidate("AAPL.NASD", gap_guard_value=0.05),
                    _entry_candidate(
                        "NVDA.NASD",
                        gap_guard_value=0.05,
                        strategy_mode="sma_ema_hybrid",
                        entry_state="WATCH",
                    ),
                    _entry_candidate("005930", gap_guard_value=0.05),
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
        holdings=_holdings_data([]),
        portfolio=_portfolio_config(max_new_entries_us=1, max_new_entries_kr=1),
    )
    monkeypatch.setattr(
        "sab.entry.load_config", lambda provider_override=None: fake_cfg
    )

    class _FakeKISClient:
        def __init__(self, *_args: object, **_kwargs: object) -> None:
            pass

        def domestic_price_detail(self, *, ticker: str) -> dict[str, str]:
            assert ticker == "005930"
            return {"stck_prpr": "101.0", "stck_cntg_hour": "090001"}

        def overseas_price_detail(
            self, *, symbol: str, exchange: str
        ) -> dict[str, str]:
            assert exchange == "NAS"
            return {"last": "101.0", "xymd": "20260226"}

    monkeypatch.setattr("sab.entry.KISClient", _FakeKISClient)

    exit_code = run_entry(
        buy_report_path=buy_report_path.as_posix(),
        provider="kis",
        mode="PRE_OPEN",
        market=None,
    )

    assert exit_code == 0
    payload = json.loads(
        next(report_dir.glob("*.entry.json")).read_text(encoding="utf-8")
    )
    by_ticker = {row["ticker"]: row for row in payload["entries"]}
    assert by_ticker["AAPL.NASD"]["action"] == "ENTER"
    assert by_ticker["NVDA.NASD"]["action"] == "REVIEW"
    assert by_ticker["005930"]["action"] == "ENTER"
    assert payload["summary"]["portfolio_blocked_count"] == 0
    assert payload["summary"]["portfolio_blocked_by_market"] == {}


def test_run_entry_e2e_preserves_buy_report_order_for_mixed_portfolio_guard(
    monkeypatch, tmp_path: Path
) -> None:
    report_dir = tmp_path / "reports"
    report_dir.mkdir(parents=True, exist_ok=True)
    buy_report_path = tmp_path / "source.buy.json"
    buy_report_path.write_text(
        json.dumps(
            {
                "run_ts_utc": "2026-02-26T01:30:00Z",
                "eval_context": {"market": "MIXED", "markets": ["KR", "US"]},
                "candidates": [
                    _entry_candidate("AAPL.NASD", gap_guard_value=0.05),
                    _entry_candidate("005930", gap_guard_value=0.05),
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
        holdings=_holdings_data([]),
        portfolio=_portfolio_config(max_active_holdings=1),
    )
    monkeypatch.setattr(
        "sab.entry.load_config", lambda provider_override=None: fake_cfg
    )

    class _FakeKISClient:
        def __init__(self, *_args: object, **_kwargs: object) -> None:
            pass

        def domestic_price_detail(self, *, ticker: str) -> dict[str, str]:
            assert ticker == "005930"
            return {"stck_prpr": "101.0", "stck_cntg_hour": "090001"}

        def overseas_price_detail(
            self, *, symbol: str, exchange: str
        ) -> dict[str, str]:
            assert symbol == "AAPL"
            assert exchange == "NAS"
            return {"last": "101.0", "xymd": "20260226"}

    monkeypatch.setattr("sab.entry.KISClient", _FakeKISClient)

    exit_code = run_entry(
        buy_report_path=buy_report_path.as_posix(),
        provider="kis",
        mode="PRE_OPEN",
        market=None,
    )

    assert exit_code == 0
    payload = json.loads(
        next(report_dir.glob("*.entry.json")).read_text(encoding="utf-8")
    )
    assert [row["ticker"] for row in payload["entries"]] == ["AAPL.NASD", "005930"]
    assert payload["entries"][0]["action"] == "ENTER"
    assert payload["entries"][1]["action"] == "SKIP"
    assert "portfolio max active holdings reached" in payload["entries"][1]["reasons"]
    assert payload["summary"]["portfolio_blocked_by_market"] == {"KR": 1}


def test_run_entry_e2e_blocks_second_us_entry_when_market_cap_reached(
    monkeypatch, tmp_path: Path
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
                    _entry_candidate("AAPL.NASD", gap_guard_value=0.05),
                    _entry_candidate("MSFT.NASD", gap_guard_value=0.05),
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
        holdings=_holdings_data([]),
        portfolio=_portfolio_config(max_new_entries_us=1),
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
            assert exchange == "NAS"
            return {"last": "101.0", "xymd": "20260226"}

    monkeypatch.setattr("sab.entry.KISClient", _FakeKISClient)

    exit_code = run_entry(
        buy_report_path=buy_report_path.as_posix(),
        provider="kis",
        mode="PRE_OPEN",
        market="US",
    )

    assert exit_code == 0
    payload = json.loads(
        next(report_dir.glob("*.entry.json")).read_text(encoding="utf-8")
    )
    assert payload["entries"][0]["action"] == "ENTER"
    assert payload["entries"][1]["action"] == "SKIP"
    assert "portfolio market cap reached (US)" in payload["entries"][1]["reasons"]
    assert payload["summary"]["portfolio_blocked_count"] == 1
    assert payload["summary"]["portfolio_blocked_by_market"] == {"US": 1}


def test_run_entry_e2e_market_new_entry_cap_excludes_existing_holdings(
    monkeypatch, tmp_path: Path
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
                    _entry_candidate("AAPL.NASD", gap_guard_value=0.05),
                    _entry_candidate("NVDA.NASD", gap_guard_value=0.05),
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
        holdings=_holdings_data([Holding(ticker="MSFT.NASD", quantity=1)]),
        portfolio=_portfolio_config(max_new_entries_us=1),
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
            assert exchange == "NAS"
            return {"last": "101.0", "xymd": "20260226"}

    monkeypatch.setattr("sab.entry.KISClient", _FakeKISClient)

    exit_code = run_entry(
        buy_report_path=buy_report_path.as_posix(),
        provider="kis",
        mode="PRE_OPEN",
        market="US",
    )

    assert exit_code == 0
    payload = json.loads(
        next(report_dir.glob("*.entry.json")).read_text(encoding="utf-8")
    )
    by_ticker = {row["ticker"]: row for row in payload["entries"]}
    assert by_ticker["AAPL.NASD"]["action"] == "ENTER"
    assert by_ticker["NVDA.NASD"]["action"] == "SKIP"
    assert "portfolio market cap reached (US)" in by_ticker["NVDA.NASD"]["reasons"]
    assert payload["summary"]["portfolio_blocked_by_market"] == {"US": 1}
