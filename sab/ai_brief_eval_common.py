from __future__ import annotations

import datetime as dt
from dataclasses import dataclass
from typing import Literal

from .utils.datetime import parse_iso_offset_datetime

AiBriefEvalStatus = Literal["PASS", "WARN", "FAIL"]
AiBriefEvalSeverity = Literal["WARN", "FAIL"]

ALLOWED_MARKETS = frozenset({"KR", "US"})
ALLOWED_ENTRY_REPORT_MARKETS = frozenset({"KR", "US", "MIXED"})
ALLOWED_CONFIDENCE = frozenset({"LOW", "MEDIUM", "HIGH"})
ALLOWED_ISSUE_SEVERITY = frozenset({"INFO", "WARN", "ERROR"})
AUTOMATED_ORDER_PHRASES = (
    "buy now",
    "sell now",
    "execute order",
    "place order",
    "place sell order",
    "submit order",
    "automatic order",
    "automated order",
    "execute sell",
    "liquidate now",
    "지금 매수",
    "지금 매도",
    "즉시 매수",
    "즉시 매도",
    "바로 매수",
    "바로 매도",
    "매수하세요",
    "매도하세요",
    "매도 주문",
    "주문 실행",
    "주문하세요",
    "자동 매수",
    "자동 매도",
    "자동 주문",
)
AUTOMATED_ORDER_PROMPT_EXAMPLES = (
    "buy now, execute order, place order, 지금 매수, or 주문 실행"
)
MARKET_OVERRIDE_INVALID_MESSAGE = "market must be KR or US"
ENTRY_REPORT_MARKET_INVALID_MESSAGE = "entry report market must be KR, US, or MIXED"
MIXED_ENTRY_REPORT_MARKET_REQUIRED_MESSAGE = (
    "MIXED entry report requires --market KR or --market US"
)


@dataclass(frozen=True)
class AiBriefEvalIssue:
    code: str
    severity: AiBriefEvalSeverity
    message: str
    ticker: str | None = None

    def to_dict(self) -> dict[str, object]:
        return {
            "ticker": self.ticker,
            "code": self.code,
            "severity": self.severity,
            "message": self.message,
        }


def normalize_market(value: str | None) -> str | None:
    if value is None:
        return None
    market = value.strip().upper()
    if not market:
        return None
    if market not in ALLOWED_MARKETS:
        raise ValueError(MARKET_OVERRIDE_INVALID_MESSAGE)
    return market


def normalize_entry_report_market(value: object) -> str:
    market = str(value or "").strip().upper()
    if market not in ALLOWED_ENTRY_REPORT_MARKETS:
        raise ValueError(ENTRY_REPORT_MARKET_INVALID_MESSAGE)
    return market


def entry_report_market_mismatch_message(
    market_override: str, report_market: str
) -> str:
    return f"--market {market_override} does not match entry report {report_market}"


def resolve_entry_report_market(
    *,
    report_market: object,
    market_override: str | None,
) -> str:
    resolved_report_market = normalize_entry_report_market(report_market)
    resolved_market_override = normalize_market(market_override)
    if resolved_report_market == "MIXED":
        if resolved_market_override is None:
            raise ValueError(MIXED_ENTRY_REPORT_MARKET_REQUIRED_MESSAGE)
        return resolved_market_override
    if (
        resolved_market_override is not None
        and resolved_market_override != resolved_report_market
    ):
        raise ValueError(
            entry_report_market_mismatch_message(
                resolved_market_override, resolved_report_market
            )
        )
    return resolved_report_market


def string_list(value: object) -> list[str]:
    if not isinstance(value, list):
        return []
    return [str(item).strip() for item in value if str(item).strip()]


def contains_automated_order_language(value: str) -> bool:
    text = value.lower()
    return any(phrase in text for phrase in AUTOMATED_ORDER_PHRASES)


def optional_text(value: object) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def parse_eval_now(value: str) -> dt.datetime:
    """평가 CLI의 ``--now`` 값을 UTC offset 포함 datetime으로 파싱한다."""

    return parse_iso_offset_datetime(
        value, field_name="now", empty_message="now must not be empty"
    )
