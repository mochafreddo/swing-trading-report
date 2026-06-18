from __future__ import annotations

import pytest
from sab.entry import EntryPriceLookupResult, evaluate_entry_candidates


def _available_price(_ticker: str) -> EntryPriceLookupResult:
    return EntryPriceLookupResult.available(101.0, source="test")


def _hybrid_ready_candidate(**overrides: object) -> dict[str, object]:
    candidate: dict[str, object] = {
        "ticker": "AAPL.NASD",
        "signal_price_basis": "raw",
        "close_value": 100.0,
        "gap_guard_pct_value": 0.05,
        "strategy_mode": "sma_ema_hybrid",
        "entry_state": "READY",
        "risk_alignment": "aligned",
        "risk_alignment_reasons": [],
        "quality_state": "A",
        "quality_reasons": ["entry_state_ready"],
    }
    candidate.update(overrides)
    return candidate


def test_hybrid_quality_state_a_allows_entry_when_other_guards_pass() -> None:
    rows, issues = evaluate_entry_candidates(
        candidates=[_hybrid_ready_candidate()],
        price_lookup_fn=_available_price,
    )

    assert issues == []
    assert rows[0].action == "ENTER"
    assert rows[0].reasons == ["entry conditions satisfied"]


@pytest.mark.parametrize(
    ("quality_state", "quality_reasons", "expected_reason"),
    [
        (
            "B",
            ["relative_strength_negative"],
            "hybrid quality_state B requires manual review "
            "(relative_strength_negative)",
        ),
        (
            "C",
            ["volatility_reference_unavailable"],
            "hybrid quality_state C requires manual review "
            "(volatility_reference_unavailable)",
        ),
        (
            "",
            [],
            "hybrid quality_state unavailable; manual review required",
        ),
    ],
)
def test_hybrid_quality_state_blocks_automatic_entry_after_guards_pass(
    quality_state: str,
    quality_reasons: list[str],
    expected_reason: str,
) -> None:
    rows, issues = evaluate_entry_candidates(
        candidates=[
            _hybrid_ready_candidate(
                quality_state=quality_state,
                quality_reasons=quality_reasons,
            )
        ],
        price_lookup_fn=_available_price,
    )

    assert issues == []
    assert rows[0].action == "REVIEW"
    assert rows[0].reasons == [expected_reason]
