from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

AiBriefEvalStatus = Literal["PASS", "WARN", "FAIL"]
AiBriefEvalSeverity = Literal["WARN", "FAIL"]

_ALLOWED_MARKETS = frozenset({"KR", "US"})


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
    if market not in _ALLOWED_MARKETS:
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
