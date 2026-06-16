from __future__ import annotations

from sab.ai_brief_candidates import classify_ai_brief_entry_rows

_RISK_ALIGNMENT_REVIEW_REASON = (
    "hybrid risk_alignment requires manual review "
    "(tight_stop_vs_volatility: gap_guard_exceeds_stop_max)"
)


def _row(
    ticker: str,
    *,
    action: str,
    reasons: list[str] | None = None,
    entry_state: str | None = "READY",
    entry_price_status: str | None = "available",
    entry_price: float | None = 101.0,
) -> dict[str, object]:
    row: dict[str, object] = {
        "ticker": ticker,
        "action": action,
        "reasons": reasons or [],
        "entry_state": entry_state,
    }
    if entry_price_status is not None:
        row["entry_price_status"] = entry_price_status
    if entry_price is not None:
        row["entry_price"] = entry_price
    return row


def test_classifier_maps_2026_06_15_ready_rows_to_ai_roles() -> None:
    result = classify_ai_brief_entry_rows(
        [
            _row("ELV.NYS", action="ENTER"),
            _row(
                "MO.NYS",
                action="SKIP",
                reasons=["hybrid trigger guard failed (70.43 < ema10 71.59)"],
            ),
            _row(
                "CAT.NYS",
                action="SKIP",
                reasons=["portfolio market cap reached (US)"],
            ),
            _row(
                "TSM.NYS",
                action="SKIP",
                reasons=["portfolio market cap reached (US)"],
            ),
            _row(
                "TOTAL.NAS",
                action="SKIP",
                reasons=["portfolio max active holdings reached"],
            ),
            _row(
                "CIFR.NAS",
                action="REVIEW",
                reasons=[_RISK_ALIGNMENT_REVIEW_REASON],
            ),
            _row(
                "IREN.NAS",
                action="REVIEW",
                reasons=[_RISK_ALIGNMENT_REVIEW_REASON],
            ),
            _row(
                "COHR.NYS",
                action="REVIEW",
                reasons=[_RISK_ALIGNMENT_REVIEW_REASON],
            ),
            _row(
                "ANET.NYS",
                action="REVIEW",
                reasons=[_RISK_ALIGNMENT_REVIEW_REASON],
            ),
        ]
    )

    assert [row.ticker for row in result.recommendable] == [
        "ELV.NYS",
        "CAT.NYS",
        "TSM.NYS",
        "TOTAL.NAS",
        "CIFR.NAS",
        "IREN.NAS",
        "COHR.NYS",
        "ANET.NYS",
    ]
    assert [row.ticker for row in result.watch_only] == ["MO.NYS"]
    assert result.excluded == []


def test_classifier_excludes_rows_that_fail_base_ready_gates() -> None:
    result = classify_ai_brief_entry_rows(
        [
            _row(
                "MISSING.NAS",
                action="ENTER",
                entry_state="READY",
                entry_price_status="missing",
            ),
            _row(
                "WATCH.NAS",
                action="ENTER",
                entry_state="WATCH",
                entry_price_status="available",
            ),
            _row("UNKNOWN.NAS", action="HOLD"),
        ]
    )

    assert result.recommendable == []
    assert result.watch_only == []
    assert [(row.ticker, row.action) for row in result.excluded] == [
        ("MISSING.NAS", "ENTER"),
        ("WATCH.NAS", "ENTER"),
        ("UNKNOWN.NAS", "HOLD"),
    ]
    assert "entry_price_status=missing" in result.excluded[0].reason
    assert "entry_state=WATCH" in result.excluded[1].reason
    assert "unsupported action HOLD" in result.excluded[2].reason


def test_classifier_accepts_legacy_ready_enter_with_entry_price() -> None:
    result = classify_ai_brief_entry_rows(
        [
            _row(
                "LEGACY.NAS",
                action="ENTER",
                entry_price_status=None,
                entry_price=123.45,
            )
        ]
    )

    assert [row.ticker for row in result.recommendable] == ["LEGACY.NAS"]
    assert result.watch_only == []
    assert result.excluded == []


def test_classifier_excludes_legacy_ready_enter_without_entry_price() -> None:
    result = classify_ai_brief_entry_rows(
        [
            _row(
                "LEGACY.NAS",
                action="ENTER",
                entry_price_status=None,
                entry_price=None,
            )
        ]
    )

    assert result.recommendable == []
    assert result.watch_only == []
    assert [(row.ticker, row.action) for row in result.excluded] == [
        ("LEGACY.NAS", "ENTER")
    ]
    assert "entry_price_status=-" in result.excluded[0].reason


def test_classifier_explains_supported_actions_that_do_not_match_rules() -> None:
    result = classify_ai_brief_entry_rows(
        [
            _row("SKIP.NAS", action="SKIP", reasons=["below score threshold"]),
            _row(
                "REVIEW.NAS",
                action="REVIEW",
                reasons=["hybrid risk_alignment requires manual review (unknown)"],
            ),
        ]
    )

    assert result.recommendable == []
    assert result.watch_only == []
    assert [(row.ticker, row.action) for row in result.excluded] == [
        ("SKIP.NAS", "SKIP"),
        ("REVIEW.NAS", "REVIEW"),
    ]
    assert (
        result.excluded[0].reason
        == "action SKIP did not match an AI brief inclusion rule"
    )
    assert (
        result.excluded[1].reason
        == "action REVIEW did not match an AI brief inclusion rule"
    )
    assert "unsupported action" not in result.excluded[0].reason
    assert "unsupported action" not in result.excluded[1].reason


def test_classifier_excludes_missing_ticker() -> None:
    result = classify_ai_brief_entry_rows([_row("", action="ENTER")])

    assert result.recommendable == []
    assert result.watch_only == []
    assert [(row.ticker, row.action, row.reason) for row in result.excluded] == [
        ("", "ENTER", "entry row ticker is required")
    ]
