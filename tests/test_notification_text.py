from __future__ import annotations

from sab.report.notification_text import (
    build_scan_slack_summary_text,
    build_scan_telegram_report_text,
    build_sell_slack_summary_text,
    build_sell_telegram_report_text,
)


def test_build_scan_telegram_report_text_includes_buy_candidates() -> None:
    report = {
        "generated_at": "2026-02-11 21:03 KST",
        "summary": {"candidate_count": 3, "issue_count": 1},
        "candidates": [
            {
                "ticker": "GS.NYS",
                "name": "골드만삭스",
                "price": "$948.99",
                "score": "7.0",
                "entry_state": "READY",
                "entry_state_reason": "Pullback bounce confirmed",
            },
            {
                "ticker": "SYK.NYS",
                "name": "스트라이커",
                "price": "$361.06",
                "score": "7.0",
                "entry_state": "READY",
                "entry_state_reason": "RSI crossed above 50",
            },
            {
                "ticker": "MDT.NYS",
                "name": "메드트로닉",
                "price": "$101.42",
                "score": "6.5",
                "entry_state": "READY",
                "entry_state_reason": "Reversal candle near EMA short",
            },
        ],
    }

    text = build_scan_telegram_report_text(
        report=report,
        run_url="https://github.com/example/repo/actions/runs/123",
        provider="kis",
        universe="both",
        max_items=5,
    )

    assert "매수 후보 3건 (표시 3건)" in text
    assert (
        "1. GS.NYS 골드만삭스 | $948.99 | score 7.0 | READY/Pullback bounce confirmed"
        in text
    )
    assert (
        "2. SYK.NYS 스트라이커 | $361.06 | score 7.0 | READY/RSI crossed above 50"
        in text
    )
    assert (
        "3. MDT.NYS 메드트로닉 | $101.42 | score 6.5 | READY/Reversal candle near EMA short"
        in text
    )


def test_build_scan_telegram_report_text_handles_zero_candidates() -> None:
    report = {
        "generated_at": "2026-02-11 21:03 KST",
        "summary": {"candidate_count": 0, "issue_count": 0},
        "candidates": [],
    }

    text = build_scan_telegram_report_text(
        report=report,
        run_url="https://github.com/example/repo/actions/runs/123",
        provider="kis",
        universe="KR",
    )

    assert "매수 후보 0건 (표시 0건)" in text
    assert "매수 후보 없음" in text


def test_build_sell_telegram_report_text_excludes_hold_rows() -> None:
    report = {
        "generated_at": "2026-02-11 21:00 KST",
        "summary": {
            "evaluated_count": 4,
            "issue_count": 0,
            "action_counts": {"SELL": 1, "REVIEW": 2, "HOLD": 1},
        },
        "evaluated": [
            {
                "ticker": "CMG.NYS",
                "action": "SELL",
                "pnl_pct": 0.123,
                "reasons": ["Hard stop triggered"],
            },
            {
                "ticker": "COP.NYS",
                "action": "REVIEW",
                "pnl_pct": 0.088,
                "reasons": ["Reached profit target zone"],
            },
            {
                "ticker": "CI.NYS",
                "action": "HOLD",
                "pnl_pct": 0.014,
                "reasons": ["No hybrid sell criteria triggered"],
            },
            {
                "ticker": "MSI.NYS",
                "action": "REVIEW",
                "pnl_pct": -0.034,
                "reasons": ["Close below EMA short"],
            },
        ],
    }

    text = build_sell_telegram_report_text(
        report=report,
        run_url="https://github.com/example/repo/actions/runs/456",
        provider="kis",
        include_actions=("SELL", "REVIEW"),
        max_items=5,
    )

    assert "매도/점검 후보 3건 (SELL 1, REVIEW 2, HOLD 1 제외)" in text
    assert "CMG.NYS | SELL | PnL +12.3% | Hard stop triggered" in text
    assert "COP.NYS | REVIEW | PnL +8.8% | Reached profit target zone" in text
    assert "MSI.NYS | REVIEW | PnL -3.4% | Close below EMA short" in text
    assert "CI.NYS" not in text


def test_build_sell_telegram_report_text_handles_hold_only() -> None:
    report = {
        "generated_at": "2026-02-11 21:00 KST",
        "summary": {
            "evaluated_count": 2,
            "issue_count": 0,
            "action_counts": {"HOLD": 2},
        },
        "evaluated": [
            {
                "ticker": "CI.NYS",
                "action": "HOLD",
                "pnl_pct": 0.012,
                "reasons": ["No hybrid sell criteria triggered"],
            },
            {
                "ticker": "JPM.NYS",
                "action": "HOLD",
                "pnl_pct": -0.005,
                "reasons": ["No hybrid sell criteria triggered"],
            },
        ],
    }

    text = build_sell_telegram_report_text(
        report=report,
        run_url="https://github.com/example/repo/actions/runs/789",
        provider="kis",
        include_actions=("SELL", "REVIEW"),
    )

    assert "매도/점검 후보 0건 (SELL 0, REVIEW 0, HOLD 2 제외)" in text
    assert "매도/점검 후보 없음" in text


def test_build_scan_telegram_report_text_limits_items_and_adds_rest_count() -> None:
    candidates = []
    for idx in range(7):
        candidates.append(
            {
                "ticker": f"T{idx:03d}",
                "name": f"Name{idx}",
                "price": f"${100 + idx}",
                "score": "6.0",
                "entry_state": "READY",
                "entry_state_reason": f"Reason {idx}",
            }
        )

    report = {
        "generated_at": "2026-02-11 21:03 KST",
        "summary": {"candidate_count": 7, "issue_count": 0},
        "candidates": candidates,
    }

    text = build_scan_telegram_report_text(
        report=report,
        run_url="https://github.com/example/repo/actions/runs/987",
        provider="kis",
        universe="US",
        max_items=5,
    )

    assert "매수 후보 7건 (표시 5건)" in text
    assert "외 2건" in text
    assert "T004 Name4" in text
    assert "T005 Name5" not in text


def test_build_sell_telegram_report_text_limits_items_and_adds_rest_count() -> None:
    evaluated = []
    for idx in range(7):
        evaluated.append(
            {
                "ticker": f"S{idx:03d}",
                "action": "SELL" if idx % 2 == 0 else "REVIEW",
                "pnl_pct": 0.01 * (idx + 1),
                "reasons": [f"Reason {idx}"],
            }
        )

    report = {
        "generated_at": "2026-02-11 21:00 KST",
        "summary": {
            "evaluated_count": 7,
            "issue_count": 0,
            "action_counts": {"SELL": 4, "REVIEW": 3, "HOLD": 0},
        },
        "evaluated": evaluated,
    }

    text = build_sell_telegram_report_text(
        report=report,
        run_url="https://github.com/example/repo/actions/runs/654",
        provider="kis",
        include_actions=("SELL", "REVIEW"),
        max_items=5,
    )

    assert "매도/점검 후보 7건 (SELL 4, REVIEW 3, HOLD 0 제외)" in text
    assert "외 2건" in text
    assert "S004 | SELL | PnL +5.0% | Reason 4" in text
    assert "S005 | REVIEW | PnL +6.0% | Reason 5" not in text


def test_build_scan_slack_summary_text_keeps_key_value_format() -> None:
    report = {
        "generated_at": "2026-02-11 21:03 KST",
        "summary": {"candidate_count": 3, "issue_count": 1},
        "candidates": [{}, {}, {}],
    }

    text = build_scan_slack_summary_text(
        report=report,
        repo="mocha/swing-trading-report",
        run_url="https://github.com/mocha/swing-trading-report/actions/runs/123",
        provider="kis",
        universe="both",
        storage_key="2026/02/2026-02-11.buy.json",
    )

    assert text.splitlines() == [
        "[SAB][scan][schedule]",
        "repo=mocha/swing-trading-report",
        "provider=kis",
        "universe=both",
        "generated_at=2026-02-11 21:03 KST",
        "candidate_count=3",
        "issue_count=1",
        "storage_key=2026/02/2026-02-11.buy.json",
        "run_url=https://github.com/mocha/swing-trading-report/actions/runs/123",
    ]


def test_build_sell_slack_summary_text_keeps_key_value_format() -> None:
    report = {
        "generated_at": "2026-02-11 21:00 KST",
        "summary": {
            "evaluated_count": 4,
            "issue_count": 1,
            "action_counts": {"REVIEW": 2, "SELL": 1, "HOLD": 1},
        },
        "evaluated": [{}, {}, {}, {}],
    }

    text = build_sell_slack_summary_text(
        report=report,
        repo="mocha/swing-trading-report",
        run_url="https://github.com/mocha/swing-trading-report/actions/runs/456",
        provider="kis",
        storage_key="2026/02/2026-02-11.sell.json",
    )

    assert text.splitlines() == [
        "[SAB][sell][schedule]",
        "repo=mocha/swing-trading-report",
        "provider=kis",
        "generated_at=2026-02-11 21:00 KST",
        "evaluated_count=4",
        "issue_count=1",
        "action_counts=HOLD:1, REVIEW:2, SELL:1",
        "storage_key=2026/02/2026-02-11.sell.json",
        "run_url=https://github.com/mocha/swing-trading-report/actions/runs/456",
    ]
