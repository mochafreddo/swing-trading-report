from __future__ import annotations

from sab.report.session_state import resolve_eval_markets


def test_single_kr_market_is_not_mixed() -> None:
    assert resolve_eval_markets(["KR"]) == ("KR", None, ["KR"])


def test_single_us_market_is_not_mixed() -> None:
    assert resolve_eval_markets(["US"]) == ("US", None, ["US"])


def test_both_markets_are_classified_mixed() -> None:
    assert resolve_eval_markets(["KR", "US"]) == ("MIXED", ["KR", "US"], ["KR", "US"])


def test_empty_markets_resolve_to_mixed_without_state() -> None:
    assert resolve_eval_markets([]) == ("MIXED", None, None)


def test_single_non_kr_us_market_is_mixed_and_dropped() -> None:
    # 단일이라도 KR/US가 아니면 MIXED로 분류하고, KR/US만 남긴다.
    assert resolve_eval_markets(["JP"]) == ("MIXED", None, None)


def test_mixed_markets_drop_non_kr_us_entries() -> None:
    assert resolve_eval_markets(["JP", "KR"]) == ("MIXED", ["KR"], ["KR"])
