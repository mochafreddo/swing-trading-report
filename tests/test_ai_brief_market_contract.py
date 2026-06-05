from __future__ import annotations

import pytest
from sab.ai_brief_eval_common import (
    ENTRY_REPORT_MARKET_INVALID_MESSAGE,
    MARKET_OVERRIDE_INVALID_MESSAGE,
    MIXED_ENTRY_REPORT_MARKET_REQUIRED_MESSAGE,
    entry_report_market_mismatch_message,
    normalize_entry_report_market,
    normalize_market,
    resolve_entry_report_market,
)


def test_normalize_market_preserves_cli_override_contract() -> None:
    assert normalize_market(None) is None
    assert normalize_market("  ") is None
    assert normalize_market(" us ") == "US"
    with pytest.raises(ValueError, match=MARKET_OVERRIDE_INVALID_MESSAGE):
        normalize_market("MIXED")


def test_normalize_entry_report_market_accepts_report_level_mixed() -> None:
    assert normalize_entry_report_market(" kr ") == "KR"
    assert normalize_entry_report_market("US") == "US"
    assert normalize_entry_report_market("mixed") == "MIXED"
    with pytest.raises(ValueError, match=ENTRY_REPORT_MARKET_INVALID_MESSAGE):
        normalize_entry_report_market("EU")


def test_resolve_entry_report_market_requires_override_for_mixed_reports() -> None:
    with pytest.raises(ValueError, match=MIXED_ENTRY_REPORT_MARKET_REQUIRED_MESSAGE):
        resolve_entry_report_market(report_market="MIXED", market_override=None)

    assert (
        resolve_entry_report_market(report_market="MIXED", market_override="us") == "US"
    )


def test_resolve_entry_report_market_rejects_override_mismatch() -> None:
    expected_message = entry_report_market_mismatch_message("KR", "US")

    with pytest.raises(ValueError, match=expected_message):
        resolve_entry_report_market(report_market="US", market_override="kr")
