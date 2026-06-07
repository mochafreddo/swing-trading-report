from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

from sab.entry import run_entry
from sab.holdings_loader import Holding, HoldingsData, HoldingSettings


def _entry_candidate(ticker: str) -> dict[str, object]:
    return {
        "ticker": ticker,
        "signal_price_basis": "adjusted",
        "signal_close_adjusted_value": 100.0,
        "entry_reference_close_raw_value": 100.0,
        "entry_reference_eval_date": "20260225",
        "eval_date": "20260225",
        "gap_guard_pct_value": 0.05,
        "strategy_mode": "ema_cross",
    }


def test_run_entry_existing_holding_candidate_does_not_consume_new_entry_caps(
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
                    _entry_candidate("AAPL.NASD"),
                    _entry_candidate("NVDA.NASD"),
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
        entry_fatal_missing_price_ratio=1.0,
        holdings=HoldingsData(
            path=None,
            settings=HoldingSettings(),
            holdings=[
                Holding(ticker="AAPL.NASD", quantity=1, entry_price=100.0),
            ],
        ),
        portfolio=SimpleNamespace(
            max_active_holdings=2,
            max_new_entries_kr=None,
            max_new_entries_us=1,
        ),
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
            assert symbol in {"AAPL", "NVDA"}
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
    assert by_ticker["NVDA.NASD"]["action"] == "ENTER"
    assert payload["summary"]["portfolio_blocked_count"] == 0
    assert payload["summary"]["portfolio_blocked_by_market"] == {}
