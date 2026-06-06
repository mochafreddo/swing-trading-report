from __future__ import annotations

from types import SimpleNamespace
from typing import cast

import sab.entry as entry
from sab.config import Config


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


def test_make_price_lookup_classifies_kr_snapshot_price_shape(
    monkeypatch,
    tmp_path,
) -> None:
    fake_cfg = SimpleNamespace(
        data_dir=tmp_path.as_posix(),
        kis_app_key="k",
        kis_app_secret="s",
        kis_base_url="https://example.test",
        kis_min_interval_ms=None,
    )

    details = iter(
        [
            {"stck_cntg_hour": "090001"},
            {"stck_cntg_hour": "090001", "stck_prpr": "0"},
        ]
    )

    class _RejectingKISClient:
        def __init__(self, *_args: object, **_kwargs: object) -> None:
            pass

        def domestic_price_detail(self, *, ticker: str) -> dict[str, str]:
            assert ticker == "005930"
            return next(details)

    monkeypatch.setattr("sab.entry.KISClient", _RejectingKISClient)

    price_lookup, issues = entry._make_price_lookup(
        cfg=cast(Config, fake_cfg),
        provider="kis",
        mode="PRE_OPEN",
        market="KR",
    )

    assert issues == []
    missing_field = price_lookup("005930")
    invalid_value = price_lookup("005930")
    assert missing_field.status == "rejected"
    assert missing_field.source == "kis_live_snapshot"
    assert missing_field.issue_codes == ("kis_live_snapshot_no_supported_price_field",)
    assert invalid_value.status == "rejected"
    assert invalid_value.source == "kis_live_snapshot"
    assert invalid_value.issue_codes == ("kis_live_snapshot_invalid_price_value",)
