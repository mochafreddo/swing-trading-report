from __future__ import annotations

import datetime as dt
from dataclasses import dataclass
from typing import Literal

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


def parse_iso_offset_datetime(
    value: object,
    *,
    field_name: str,
    empty_message: str | None = None,
) -> dt.datetime:
    """ISO 8601 datetime을 UTC offset 포함 형태로 파싱한다.

    실패하면 ValueError를 raise하며, 호출자는 자신의 도메인 예외로 매핑할 수
    있다. `empty_message`는 빈 입력 케이스에 대한 메시지를 호출자가 보존하고
    싶을 때만 지정한다 (기본은 ``f"{field_name} is required"``).
    """

    text = str(value or "").strip()
    if not text:
        raise ValueError(empty_message or f"{field_name} is required")
    try:
        parsed = dt.datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError(f"{field_name} must be an ISO 8601 datetime") from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError(f"{field_name} must include a UTC offset")
    return parsed
