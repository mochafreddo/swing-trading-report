from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

AiBriefEvalStatus = Literal["PASS", "WARN", "FAIL"]
AiBriefEvalSeverity = Literal["WARN", "FAIL"]


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
