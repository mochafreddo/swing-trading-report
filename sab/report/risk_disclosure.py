from __future__ import annotations

from collections.abc import Iterable
from typing import Any

RISK_GUIDE_MEANING = "decision_guide_only"
RISK_EXECUTION_CAVEAT = "gap_slippage_may_exceed_guide"
RISK_ACCOUNT_LOSS_CAVEAT = "not_account_loss_limit"
RISK_GUIDE_NOTICE_KO = (
    "Stop/Target은 의사결정 가이드이며 체결 보장이나 계좌 손실 한도가 아닙니다. "
    "갭/슬리피지로 실제 체결·손실은 달라질 수 있습니다."
)
RISK_DOWNSIDE_CAVEAT = "stop_target_decision_guide_only_gap_slippage_may_exceed"
BUY_RISK_DISCLOSURE_FIELDS = ("risk_guide",)
SELL_RISK_DISCLOSURE_FIELDS = ("stop_price", "target_price")


def build_risk_disclosure(fields: Iterable[str]) -> dict[str, Any]:
    return {
        "meaning": RISK_GUIDE_MEANING,
        "fields": list(dict.fromkeys(fields)),
        "execution_caveat": RISK_EXECUTION_CAVEAT,
        "account_loss_caveat": RISK_ACCOUNT_LOSS_CAVEAT,
        "notice_ko": RISK_GUIDE_NOTICE_KO,
    }


def build_buy_risk_disclosure() -> dict[str, Any]:
    return build_risk_disclosure(BUY_RISK_DISCLOSURE_FIELDS)


def build_sell_risk_disclosure() -> dict[str, Any]:
    return build_risk_disclosure(SELL_RISK_DISCLOSURE_FIELDS)


__all__ = [
    "BUY_RISK_DISCLOSURE_FIELDS",
    "RISK_ACCOUNT_LOSS_CAVEAT",
    "RISK_DOWNSIDE_CAVEAT",
    "RISK_EXECUTION_CAVEAT",
    "RISK_GUIDE_MEANING",
    "RISK_GUIDE_NOTICE_KO",
    "SELL_RISK_DISCLOSURE_FIELDS",
    "build_buy_risk_disclosure",
    "build_risk_disclosure",
    "build_sell_risk_disclosure",
]
