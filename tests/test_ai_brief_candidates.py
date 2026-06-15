from __future__ import annotations

from sab.ai_brief_candidates import classify_ai_brief_entry_rows


def _row(
    ticker: str,
    *,
    action: str,
    reasons: list[str] | None = None,
    entry_state: str | None = "READY",
    entry_price_status: str | None = "available",
) -> dict[str, object]:
    return {
        "ticker": ticker,
        "action": action,
        "reasons": reasons or [],
        "entry_state": entry_state,
        "entry_price_status": entry_price_status,
    }


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
                "CIFR.NAS",
                action="REVIEW",
                reasons=["risk_alignment=tight_stop_vs_volatility"],
            ),
            _row(
                "IREN.NAS",
                action="REVIEW",
                reasons=["risk_alignment=tight_stop_vs_volatility"],
            ),
            _row(
                "COHR.NYS",
                action="REVIEW",
                reasons=["risk_alignment=tight_stop_vs_volatility"],
            ),
            _row(
                "ANET.NYS",
                action="REVIEW",
                reasons=["risk_alignment=tight_stop_vs_volatility"],
            ),
        ]
    )

    assert [row.ticker for row in result.recommendable] == [
        "ELV.NYS",
        "CAT.NYS",
        "TSM.NYS",
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
