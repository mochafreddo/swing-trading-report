from __future__ import annotations

from sab.sell_ai_brief_candidates import classify_sell_ai_brief_rows


def _row(
    ticker: str,
    *,
    action: str,
    reasons: list[str] | None = None,
) -> dict[str, object]:
    return {
        "ticker": ticker,
        "name": ticker,
        "action": action,
        "reasons": reasons or ["sell rule matched"],
        "last_price": 101.0,
        "pnl_pct": 0.12,
    }


def test_classifier_sends_only_actionable_sell_rows_to_ai() -> None:
    result = classify_sell_ai_brief_rows(
        [
            _row("AAPL.NAS", action="SELL"),
            _row("MSFT.NAS", action="SELL_PARTIAL"),
            _row("TSLA.NAS", action="REVIEW"),
            _row("NVDA.NAS", action="HOLD"),
        ]
    )

    assert [(row.ticker, row.sell_action) for row in result.actionable] == [
        ("AAPL.NAS", "SELL"),
        ("MSFT.NAS", "SELL_PARTIAL"),
        ("TSLA.NAS", "REVIEW"),
    ]
    assert [row.role for row in result.actionable] == [
        "actionable",
        "actionable",
        "actionable",
    ]
    assert [(row.ticker, row.sell_action) for row in result.excluded_hold] == [
        ("NVDA.NAS", "HOLD")
    ]
    assert result.unsupported == []
    assert result.system_issues == []


def test_classifier_preserves_report_order_and_explains_reasons() -> None:
    result = classify_sell_ai_brief_rows(
        [
            _row("REVIEW.NAS", action="REVIEW", reasons=["data unavailable"]),
            _row("SELL.NAS", action="SELL", reasons=["stop loss breached"]),
        ]
    )

    assert [row.ticker for row in result.actionable] == ["REVIEW.NAS", "SELL.NAS"]
    assert result.actionable[0].reason == "sell report action was REVIEW"
    assert result.actionable[0].deterministic_reasons == ["data unavailable"]
    assert result.actionable[1].reason == "sell report action was SELL"
    assert result.actionable[1].deterministic_reasons == ["stop loss breached"]


def test_classifier_fails_closed_for_unknown_action() -> None:
    result = classify_sell_ai_brief_rows([_row("BAD.NAS", action="TRIM")])

    assert result.actionable == []
    assert result.excluded_hold == []
    assert [
        (row.ticker, row.sell_action, row.reason) for row in result.unsupported
    ] == [("BAD.NAS", "TRIM", "unsupported sell action TRIM")]
    assert result.system_issues == [
        {
            "ticker": "BAD.NAS",
            "code": "unsupported_sell_action",
            "severity": "WARN",
            "message": "unsupported sell action TRIM",
        }
    ]


def test_classifier_excludes_missing_ticker_without_modeling() -> None:
    result = classify_sell_ai_brief_rows([_row("", action="SELL")])

    assert result.actionable == []
    assert result.excluded_hold == []
    assert [
        (row.ticker, row.sell_action, row.reason) for row in result.unsupported
    ] == [("", "SELL", "sell row ticker is required")]
    assert result.system_issues == [
        {
            "ticker": None,
            "code": "sell_row_ticker_required",
            "severity": "WARN",
            "message": "sell row ticker is required",
        }
    ]
