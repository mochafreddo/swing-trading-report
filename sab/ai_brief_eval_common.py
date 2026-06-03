from __future__ import annotations

import datetime as dt
from dataclasses import dataclass
from typing import Literal

from .utils.datetime import parse_iso_offset_datetime

AiBriefEvalStatus = Literal["PASS", "WARN", "FAIL"]
AiBriefEvalSeverity = Literal["WARN", "FAIL"]

ALLOWED_MARKETS = frozenset({"KR", "US"})
ALLOWED_CONFIDENCE = frozenset({"LOW", "MEDIUM", "HIGH"})
ALLOWED_ISSUE_SEVERITY = frozenset({"INFO", "WARN", "ERROR"})


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
        raise ValueError("market must be KR or US")
    return market


def string_list(value: object) -> list[str]:
    if not isinstance(value, list):
        return []
    return [str(item).strip() for item in value if str(item).strip()]


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
