from __future__ import annotations

import sab.entry as entry


def test_entry_candidate_helper_preserves_review_issue_order() -> None:
    helper = getattr(entry, "_evaluate_entry_candidate", None)

    assert helper is not None
    lookup_result = entry.EntryPriceLookupResult.missing(
        "kis_live_snapshot_missing",
        source="kis_live_snapshot",
    )

    row, issues = helper(
        candidate={
            "ticker": "AAPL.NASD",
            "signal_price_basis": "adjusted",
            "signal_close_adjusted_value": 100.0,
            "entry_reference_close_raw_value": 100.0,
            "entry_reference_eval_date": "20260225",
            "eval_date": "20260225",
            "strategy_mode": "sma_ema_hybrid",
            "entry_state": "READY",
            "entry_trigger_price_value": "not-a-price",
            "entry_trigger_operator": "gte",
            "entry_trigger_label": "swing high",
        },
        price_lookup_fn=lambda _ticker: lookup_result,
        gap_breach_action="SKIP",
        default_strategy_mode=None,
        allow_missing_gap_guard=False,
    )

    assert row.ticker == "AAPL.NASD"
    assert row.action == "REVIEW"
    assert row.entry_price is None
    assert row.entry_price_status == "missing"
    assert row.entry_price_source == "kis_live_snapshot"
    assert row.entry_price_issue_code == "kis_live_snapshot_missing"
    assert row.entry_price_issues == ["kis_live_snapshot_missing"]
    assert row.reasons == [
        "hybrid trigger guard invalid",
        "price snapshot unavailable",
        "gap guard unavailable",
    ]
    assert issues == [
        "AAPL.NASD: hybrid trigger guard invalid",
        "AAPL.NASD: price snapshot unavailable",
        "AAPL.NASD: gap guard unavailable",
    ]
