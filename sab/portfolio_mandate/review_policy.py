"""One-snapshot composite review, with no directional advice or provider access."""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Callable
from datetime import datetime
from decimal import Decimal
from pathlib import Path
from typing import Any
from uuid import UUID

from jsonschema import (  # type: ignore[import-untyped]
    Draft202012Validator,
    FormatChecker,
)

from .outcome_history import _reject_duplicate_keys

_SCHEMA = json.loads(
    (
        Path(__file__).parents[2] / "schemas/portfolio-review-input.r1.schema.json"
    ).read_text()
)
_VALIDATOR = Draft202012Validator(_SCHEMA, format_checker=FormatChecker())
_HOLDING_VALIDATOR = Draft202012Validator(
    _SCHEMA["$defs"]["holding"], format_checker=FormatChecker()
)


def _json(raw: str) -> Any:
    return json.loads(
        raw, object_pairs_hook=_reject_duplicate_keys, parse_float=Decimal
    )


def _hash(raw: str) -> str:
    return "sha256:" + hashlib.sha256(raw.encode()).hexdigest()


def _time(value: str) -> datetime:
    result = datetime.fromisoformat(value)
    if result.utcoffset() is None:
        raise ValueError("clock offset required")
    return result


def _quarter(value: str) -> int:
    if not re.fullmatch(r"[0-9]{4}Q[1-4]", value):
        raise ValueError("invalid review quarter")
    return int(value[:4]) * 4 + int(value[-1]) - 1


def _combine(values: list[bool | None], minimum: int) -> bool | None:
    confirmed = sum(v is True for v in values)
    if confirmed >= minimum:
        return True
    if confirmed + values.count(None) < minimum:
        return False
    return None


def _condition(condition: dict[str, Any], observed: dict[str, Any]) -> bool | None:
    if (condition["metric"], condition["unit"]) != (
        observed["metric"],
        observed["unit"],
    ):
        return None
    actual, threshold, operator = (
        observed["observed_value"],
        condition["threshold"],
        condition["operator"],
    )
    if operator == "RATING_BELOW":
        return None  # No approved rating scale: do not invent an ordering.
    if operator == "EVENT_OCCURRED":
        return actual == threshold if type(actual) is type(threshold) is bool else None
    if type(threshold) is bool or type(actual) is not str:
        return None
    if not re.fullmatch(r"-?[0-9]{1,20}(?:\.[0-9]{1,8})?", actual):
        return None
    if not re.fullmatch(r"-?[0-9]{1,20}(?:\.[0-9]{1,8})?", str(threshold)):
        return None
    left, right = Decimal(actual), Decimal(str(threshold))
    return {
        "<": left < right,
        "<=": left <= right,
        ">": left > right,
        ">=": left >= right,
        "==": left == right,
    }[operator]


def _review_row(
    row: dict[str, Any],
    *,
    now: datetime,
    review_period: str,
    broker_age: int,
    evidence_age: int,
) -> dict[str, Any]:
    issues: set[str] = set()
    if (
        row["approval_state"] != "APPROVED"
        or row["classification_state"] != "ACTIVE"
        or row["horizon"] != "LONG_TERM"
    ):
        issues.add("MANDATE_NOT_ACTIVE")
    if any(
        row[k] is None or _time(row[k]) > now for k in ("approved_at", "effective_from")
    ) or (row["effective_to"] is not None and _time(row["effective_to"]) <= now):
        issues.add("MANDATE_OUTSIDE_EFFECTIVE_WINDOW")
    broker = row["broker"]
    if (
        broker is None
        or not 0 <= (now - _time(broker["captured_at"])).total_seconds() <= broker_age
    ):
        issues.add("BROKER_STALE_OR_MISSING")
    if (
        broker is None
        or broker["snapshot_version"] != broker["allocation_snapshot_version"]
    ):
        issues.add("ALLOCATION_REBASE_REQUIRED")
    if (
        broker is None
        or not broker["slices"]
        or any(
            not s["eligible"] or s["classification_state"] != "ACTIVE"
            for s in broker["slices"]
        )
    ):
        issues.add("SLICE_INELIGIBLE")
    result: dict[str, Any] = {
        "mandate_version_id": row["mandate_version_id"],
        "instrument_id": row["instrument_id"],
        "status": "BLOCKED",
        "action": None,
        "issue_codes": [],
        "matched_hard_trigger_count": 0,
        "deterioration_confirmed": False,
        "current_observation_count": 0,
        "superseded_observation_count": 0,
    }
    document = row["holding_document"]
    if document is None:
        issues.add("POLICY_MISSING")
    elif _hash(document) != row["holding_sha256"]:
        raise ValueError("policy digest mismatch")
    elif (
        row["policy_recorded_at"] is None
        or _time(row["policy_recorded_at"]) > now
        or row["source_document_sha256"] is None
    ):
        issues.add("POLICY_NOT_VISIBLE")
    if issues:
        result["issue_codes"] = sorted(issues)
        return result
    holding = _json(document)
    _HOLDING_VALIDATOR.validate(holding)
    policy = holding["invalidation_policy"]
    deterioration = policy["deterioration_rule"]
    if deterioration["minimum_matches"] > len(deterioration["signals"]):
        raise ValueError("invalid minimum matches")
    visible = [o for o in row["observations"] if _time(o["recorded_at"]) <= now]
    by_id = {o["observation_id"]: o for o in visible}
    if len(by_id) != len(visible):
        raise ValueError("duplicate observation")
    superseded: set[str] = set()
    for o in visible:
        previous_id = o["supersedes_observation_id"]
        if previous_id is not None:
            previous = by_id.get(previous_id)
            if (
                previous is None
                or previous_id in superseded
                or (previous["rule_path"], previous["period_key"])
                != (o["rule_path"], o["period_key"])
                or _time(previous["recorded_at"]) >= _time(o["recorded_at"])
            ):
                raise ValueError("invalid correction lineage")
            superseded.add(previous_id)
    current = [o for o in visible if o["observation_id"] not in superseded]
    result["current_observation_count"] = len(current)
    result["superseded_observation_count"] = len(superseded)

    def trigger_value(trigger: dict[str, Any], path: str, quarter: str) -> bool | None:
        conditions = trigger.get("conditions")
        if not conditions:
            issues.add("UNSTRUCTURED_RULE_REQUIRES_REVIEW")
            return None
        values: list[bool | None] = []
        for index, condition in enumerate(conditions):
            # Quarter observations never stand in for annual, trailing-year or event facts.
            expected_period = quarter if condition["period"] == "QUARTER" else None
            candidates = [
                o
                for o in current
                if o["rule_path"] == f"{path}/{index}"
                and o["period_key"] == expected_period
            ]
            if expected_period is None:
                issues.add("PERIOD_MAPPING_REQUIRED")
            if len(candidates) != 1:
                values.append(None)
                issues.add("OBSERVATION_MISSING_OR_CONFLICTED")
                continue
            o = candidates[0]
            if (
                o["source_instrument_id"] != row["instrument_id"]
                or not 0
                <= (now - _time(o["source_event_time"])).total_seconds()
                <= evidence_age
                or not _time(o["source_event_time"])
                <= _time(o["sealed_at"])
                <= _time(o["recorded_at"])
                <= now
            ):
                values.append(None)
                issues.add("EVIDENCE_STALE_OR_MISMATCHED")
                continue
            answer = _condition(condition, o)
            values.append(answer)
            if answer is None:
                issues.add("CONDITION_MAPPING_REQUIRED")
        return _combine(
            values, 1 if trigger.get("condition_match", "ALL") == "ANY" else len(values)
        )

    hard = [
        trigger_value(t, f"hard_triggers/{i}", review_period)
        for i, t in enumerate(policy["hard_triggers"])
    ]
    result["matched_hard_trigger_count"] = hard.count(True)
    quarters: list[bool | None] = []
    for offset in range(deterioration["consecutive_periods"]):
        year, quarter = divmod(_quarter(review_period) - offset, 4)
        values = [
            trigger_value(t, f"signals/{i}", f"{year}Q{quarter + 1}")
            for i, t in enumerate(deterioration["signals"])
        ]
        quarters.append(_combine(values, deterioration["minimum_matches"]))
    deteriorated = _combine(quarters, len(quarters))
    result["deterioration_confirmed"] = deteriorated is True
    if policy["special_review_rules"]:
        issues.add("SPECIAL_RULE_REQUIRES_REVIEW")
    if holding["review_cadence"]["annual_review_by"] <= now.date().isoformat():
        issues.add("ANNUAL_REVIEW_DUE")
    if any(v is True for v in hard) or deteriorated is True:
        result["status"] = "THESIS_INVALIDATED_REVIEW_REQUIRED"
    elif issues or any(v is None for v in hard) or deteriorated is None:
        result["status"] = "REVIEW_REQUIRED"
    else:
        result["status"] = "NO_TRIGGER_OBSERVED"
    result["issue_codes"] = sorted(issues)
    return result


def compile_portfolio_review_r1(
    envelope: object,
    *,
    review_period: str,
    broker_max_age_seconds: int,
    evidence_max_age_seconds: int,
) -> dict[str, Any]:
    """Validate the exact RPC payload bytes, then compile a private-safe projection."""
    try:
        if type(envelope) is not dict or set(envelope) != {"payload", "payload_sha256"}:
            raise ValueError("invalid envelope")
        raw = envelope["payload"]
        if (
            type(raw) is not str
            or len(raw.encode()) > 2 * 1024 * 1024
            or _hash(raw) != envelope["payload_sha256"]
        ):
            raise ValueError("invalid payload")
        if (
            type(broker_max_age_seconds) is not int
            or not 1 <= broker_max_age_seconds <= 86400
            or type(evidence_max_age_seconds) is not int
            or not 1 <= evidence_max_age_seconds <= 366 * 86400
        ):
            raise ValueError("explicit freshness budgets required")
        value = _json(raw)
        _VALIDATOR.validate(value)
        now = _time(value["read_at"])
        if _quarter(review_period) > now.year * 4 + (now.month - 1) // 3:
            raise ValueError("future review quarter")
        ids = [r["mandate_version_id"] for r in value["rows"]]
        if len(ids) != len(set(ids)):
            raise ValueError("duplicate version")
        rows = [
            _review_row(
                row,
                now=now,
                review_period=review_period,
                broker_age=broker_max_age_seconds,
                evidence_age=evidence_max_age_seconds,
            )
            for row in value["rows"]
        ]
        return {
            "schema_version": "portfolio-review.r1",
            "mode": "LOCAL_ONLY",
            "advice_enabled": False,
            "as_of": value["read_at"],
            "review_period": review_period,
            "rows": rows,
        }
    except Exception:
        # Neither validation errors nor parser exceptions may echo private input.
        raise ValueError("INVALID_PORTFOLIO_REVIEW_INPUT") from None


def read_portfolio_review_r1(
    rpc: Callable[[str, dict[str, Any]], object],
    version_ids: list[str],
    *,
    enabled: bool = False,
    review_period: str,
    broker_max_age_seconds: int,
    evidence_max_age_seconds: int,
) -> dict[str, Any]:
    """Default-off adapter; the caller owns its authorized authenticated connection."""
    if enabled is not True:
        raise ValueError("PORTFOLIO_REVIEW_DISABLED")
    try:
        if (
            not 1 <= len(version_ids) <= 100
            or len(set(version_ids)) != len(version_ids)
            or any(str(UUID(v)) != v for v in version_ids)
        ):
            raise ValueError("invalid versions")
        envelope = rpc("read_portfolio_review_r1", {"p_version_ids": version_ids})
        result = compile_portfolio_review_r1(
            envelope,
            review_period=review_period,
            broker_max_age_seconds=broker_max_age_seconds,
            evidence_max_age_seconds=evidence_max_age_seconds,
        )
        if {r["mandate_version_id"] for r in result["rows"]} != set(version_ids):
            raise ValueError("incomplete snapshot")
        return result
    except Exception:
        raise ValueError("PORTFOLIO_REVIEW_UNAVAILABLE") from None
