"""Provider-free typed order-history adapter seam for Portfolio Outcome T15."""

from __future__ import annotations

import json
from collections.abc import Iterable, Mapping
from copy import deepcopy
from pathlib import Path
from typing import Any, Literal, TypedDict, cast

from jsonschema import (  # type: ignore[import-untyped]
    Draft202012Validator,
    FormatChecker,
)

from .outcomes import PortfolioOutcomeContractError, validate_execution_lineages_o1

_SCHEMA_PATH = (
    Path(__file__).parents[2] / "schemas" / "portfolio-outcome-history-t15.schema.json"
)
_MAX_IMPORT_BYTES = 1_048_576


class OutcomeHistoryContractError(ValueError):
    """A T15 recorded or redacted history envelope failed closed."""

    def __init__(self, path: str, message: str) -> None:
        self.path = path
        self.message = message
        super().__init__(f"{path}: {message}")


class OutcomeHistoryT15Result(TypedDict):
    """Validated complete input for the existing O1 matcher."""

    input_mode: Literal["RECORDED", "REDACTED_IMPORT"]
    provider_history_state: Literal["NOT_EVALUATED"]
    pagination_state: Literal["COMPLETE"]
    page_count: int
    execution_lineages: list[dict[str, Any]]


def adapt_outcome_history_t15(value: Mapping[str, Any]) -> OutcomeHistoryT15Result:
    """Validate a complete provider-free page chain and flatten its lineages."""

    envelope = deepcopy(dict(value))
    _validate_schema(envelope)
    pages = cast(list[dict[str, Any]], envelope["pages"])
    expected_cursor: str | None = None
    seen_cursors: set[str] = set()
    flattened: list[dict[str, Any]] = []

    for index, page in enumerate(pages):
        request_cursor = cast(str | None, page["request_cursor"])
        if request_cursor != expected_cursor:
            raise OutcomeHistoryContractError(
                f"pages[{index}].request_cursor",
                "must equal the prior page next_cursor",
            )
        if request_cursor is not None:
            if request_cursor in seen_cursors:
                raise OutcomeHistoryContractError(
                    f"pages[{index}].request_cursor", "cursor must not repeat"
                )
            seen_cursors.add(request_cursor)
        expected_cursor = cast(str | None, page["next_cursor"])
        flattened.extend(
            deepcopy(cast(list[dict[str, Any]], page["execution_lineages"]))
        )

    if expected_cursor is not None:
        raise OutcomeHistoryContractError(
            "pages[-1].next_cursor",
            "pagination must be complete before adaptation",
        )

    try:
        validated = validate_execution_lineages_o1(flattened)
    except PortfolioOutcomeContractError as error:
        raise OutcomeHistoryContractError(
            f"execution_lineages.{error.path}", error.message
        ) from error

    return OutcomeHistoryT15Result(
        input_mode=cast(Literal["RECORDED", "REDACTED_IMPORT"], envelope["input_mode"]),
        provider_history_state="NOT_EVALUATED",
        pagination_state="COMPLETE",
        page_count=len(pages),
        execution_lineages=list(validated),
    )


def parse_redacted_outcome_history_t15_bytes(
    payload: bytes,
) -> OutcomeHistoryT15Result:
    """Parse one bounded, duplicate-key-aware redacted local import."""

    if len(payload) > _MAX_IMPORT_BYTES:
        raise OutcomeHistoryContractError("$", "payload exceeds byte limit")
    try:
        text = payload.decode("utf-8", errors="strict")
    except UnicodeDecodeError as error:
        raise OutcomeHistoryContractError("$", "payload must be UTF-8") from error
    try:
        value = json.loads(text, object_pairs_hook=_reject_duplicate_keys)
    except OutcomeHistoryContractError:
        raise
    except json.JSONDecodeError as error:
        raise OutcomeHistoryContractError("$", "payload must be valid JSON") from error
    if not isinstance(value, dict):
        raise OutcomeHistoryContractError("$", "payload must be an object")
    if value.get("input_mode") != "REDACTED_IMPORT":
        raise OutcomeHistoryContractError(
            "input_mode", "redacted import must declare REDACTED_IMPORT"
        )
    return adapt_outcome_history_t15(value)


def _reject_duplicate_keys(pairs: Iterable[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise OutcomeHistoryContractError(f"$.{key}", "duplicate key is forbidden")
        result[key] = value
    return result


def _validate_schema(value: object) -> None:
    schema = json.loads(_SCHEMA_PATH.read_text(encoding="utf-8"))
    if not isinstance(schema, dict):
        raise OutcomeHistoryContractError("$", "schema must be an object")
    Draft202012Validator.check_schema(schema)
    validator = Draft202012Validator(schema, format_checker=FormatChecker())
    errors = sorted(
        validator.iter_errors(value), key=lambda error: _json_path(error.path)
    )
    if errors:
        error = errors[0]
        raise OutcomeHistoryContractError(
            _json_path(error.absolute_path), error.message
        )


def _json_path(parts: Iterable[str | int]) -> str:
    result = ""
    for part in parts:
        result += (
            f"[{part}]" if isinstance(part, int) else ("." if result else "") + part
        )
    return result or "$"


__all__ = [
    "OutcomeHistoryContractError",
    "OutcomeHistoryT15Result",
    "adapt_outcome_history_t15",
    "parse_redacted_outcome_history_t15_bytes",
]
