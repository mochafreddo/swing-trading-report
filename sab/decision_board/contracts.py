"""Standard-library validation and canonicalization for Decision Board V0."""

from __future__ import annotations

import hashlib
import json
import math
import re
from datetime import datetime
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

SCHEMA_VERSION = "decision-board.v0"
_HASH_PATTERN = re.compile(r"sha256:[0-9a-f]{64}\Z")
_TIMESTAMP_PATTERN = re.compile(
    r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:Z|[+-]\d{2}:\d{2})\Z"
)
_ISSUE_CODE_PATTERN = re.compile(r"[A-Z][A-Z0-9_]*\Z")
_RUN_KINDS = frozenset({"ENTRY", "HOLDING"})
_ENTRY_ACTIONS = frozenset({"BUY", "AVOID"})
_HOLDING_ACTIONS = frozenset({"HOLD", "SELL"})


class ContractError(ValueError):
    """A Decision Board value failed validation at ``path``."""

    def __init__(self, path: str, message: str) -> None:
        self.path = path
        self.message = message
        super().__init__(f"{path}: {message}")


def canonical_json_bytes(value: Any) -> bytes:
    """Serialize a JSON value using the Decision Board canonical byte format."""

    try:
        _strict_json_value(value, "$")
        encoded = json.dumps(
            value,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        )
        return encoded.encode("utf-8")
    except ContractError:
        raise
    except (TypeError, ValueError, RecursionError, UnicodeError) as exc:
        raise ContractError("$", f"value is not canonical JSON: {exc}") from exc


def decision_payload_hash(payload: Any) -> str:
    """Return the content hash for canonical DecisionPayloadV0 bytes."""

    digest = hashlib.sha256(canonical_json_bytes(payload)).hexdigest()
    return f"sha256:{digest}"


def load_decision_board_report(path: str | Path) -> dict[str, Any]:
    """Load and validate one publishable Decision Board V0 report."""

    report_path = Path(path)
    try:
        value = json.loads(
            report_path.read_text(encoding="utf-8"),
            parse_constant=_reject_json_constant,
        )
    except (OSError, UnicodeError, ValueError) as exc:
        raise ContractError("$", f"could not load report: {exc}") from exc
    return validate_decision_board_report(value)


def validate_decision_board_report(value: Any) -> dict[str, Any]:
    """Validate and return a DecisionBoardEnvelopeV0 without coercion."""

    _strict_json_value(value, "$")
    report = _object(value, "$")
    _strict_keys(
        report,
        "$",
        required={
            "schema_version",
            "run_id",
            "created_at",
            "run_kind",
            "status",
            "issues",
        },
        optional={"metadata", "decision_payload", "decision_payload_hash"},
    )
    _literal(report["schema_version"], "$.schema_version", SCHEMA_VERSION)
    _non_empty_string(report["run_id"], "$.run_id")
    _timestamp(report["created_at"], "$.created_at")
    run_kind = _enum(report["run_kind"], "$.run_kind", _RUN_KINDS)
    status = _enum(report["status"], "$.status", {"PUBLISHED", "BLOCKED"})
    issues = _issues(report["issues"], "$.issues")
    if "metadata" in report:
        _object(report["metadata"], "$.metadata")

    if status == "BLOCKED":
        if not issues:
            raise ContractError(
                "$.issues", "BLOCKED reports require at least one issue"
            )
        for field in ("decision_payload", "decision_payload_hash"):
            if field in report:
                raise ContractError(f"$.{field}", "must be absent from BLOCKED reports")
        return report

    for field in ("decision_payload", "decision_payload_hash"):
        if field not in report:
            raise ContractError(f"$.{field}", "is required for PUBLISHED reports")
    payload = _decision_payload(report["decision_payload"], "$.decision_payload")
    if payload["run_kind"] != run_kind:
        raise ContractError(
            "$.decision_payload.run_kind", "must match the envelope run_kind"
        )
    payload_hash = _hash(report["decision_payload_hash"], "$.decision_payload_hash")
    if payload_hash != decision_payload_hash(payload):
        raise ContractError(
            "$.decision_payload_hash", "does not match the canonical decision payload"
        )
    return report


def validate_claim_validation(value: Any) -> dict[str, Any]:
    """Validate and return one ClaimValidationV0 without coercion."""

    _strict_json_value(value, "$")
    claim = _object(value, "$")
    _strict_keys(
        claim,
        "$",
        required={
            "claim_id",
            "instrument",
            "source_url",
            "publisher",
            "published_at",
            "article_content_hash",
            "supporting_span",
            "supporting_location",
            "verifier_version",
            "entailment",
        },
        optional=set(),
    )
    _non_empty_string(claim["claim_id"], "$.claim_id")
    _instrument(claim["instrument"], "$.instrument")
    _url(claim["source_url"], "$.source_url")
    _non_empty_string(claim["publisher"], "$.publisher")
    _timestamp(claim["published_at"], "$.published_at")
    _hash(claim["article_content_hash"], "$.article_content_hash")
    _non_empty_string(claim["supporting_span"], "$.supporting_span")
    _supporting_location(claim["supporting_location"], "$.supporting_location")
    _non_empty_string(claim["verifier_version"], "$.verifier_version")
    _enum(
        claim["entailment"],
        "$.entailment",
        {"SUPPORTED", "CONTRADICTED", "UNCLEAR"},
    )
    return claim


def validate_decision_payload(value: Any) -> dict[str, Any]:
    """Validate and return one publishable DecisionPayloadV0 without coercion."""

    _strict_json_value(value, "$")
    return _decision_payload(value, "$")


def _decision_payload(value: Any, path: str) -> dict[str, Any]:
    payload = _object(value, path)
    _strict_keys(
        payload,
        path,
        required={"run_kind", "sealed_input_hash", "items"},
        optional=set(),
    )
    run_kind = _enum(payload["run_kind"], f"{path}.run_kind", _RUN_KINDS)
    _hash(payload["sealed_input_hash"], f"{path}.sealed_input_hash")
    items = _array(payload["items"], f"{path}.items")
    for index, item in enumerate(items):
        _decision_item(item, f"{path}.items[{index}]", run_kind)
    return payload


def _decision_item(value: Any, path: str, run_kind: str) -> None:
    item = _object(value, path)
    _strict_keys(
        item,
        path,
        required={"instrument", "status", "issues", "evidence"},
        optional={"action"},
    )
    _instrument(item["instrument"], f"{path}.instrument")
    status = _enum(item["status"], f"{path}.status", {"DECIDED", "REVIEW"})
    issues = _issues(item["issues"], f"{path}.issues")
    evidence = _array(item["evidence"], f"{path}.evidence")
    for index, reference in enumerate(evidence):
        _evidence_reference(reference, f"{path}.evidence[{index}]")

    if status == "REVIEW":
        if "action" in item:
            raise ContractError(f"{path}.action", "must be absent for REVIEW items")
        if not issues:
            raise ContractError(f"{path}.issues", "REVIEW items require an issue")
        return

    if "action" not in item:
        raise ContractError(f"{path}.action", "is required for DECIDED items")
    allowed_actions = _ENTRY_ACTIONS if run_kind == "ENTRY" else _HOLDING_ACTIONS
    _enum(item["action"], f"{path}.action", allowed_actions)


def _instrument(value: Any, path: str) -> None:
    instrument = _object(value, path)
    fields = {
        "market",
        "canonical_ticker",
        "exchange",
        "company_name",
        "identity_source",
        "identity_version",
    }
    _strict_keys(instrument, path, required=fields, optional=set())
    _literal(instrument["market"], f"{path}.market", "US")
    for field in fields - {"market"}:
        _non_empty_string(instrument[field], f"{path}.{field}")


def _evidence_reference(value: Any, path: str) -> None:
    reference = _object(value, path)
    _strict_keys(
        reference,
        path,
        required={"claim_id", "entailment"},
        optional=set(),
    )
    _non_empty_string(reference["claim_id"], f"{path}.claim_id")
    _literal(reference["entailment"], f"{path}.entailment", "SUPPORTED")


def _supporting_location(value: Any, path: str) -> None:
    location = _object(value, path)
    _strict_keys(
        location,
        path,
        required={"kind", "start", "end"},
        optional=set(),
    )
    _literal(location["kind"], f"{path}.kind", "TEXT_OFFSETS")
    start = _integer(location["start"], f"{path}.start", minimum=0)
    end = _integer(location["end"], f"{path}.end", minimum=1)
    if end <= start:
        raise ContractError(f"{path}.end", "must be greater than start")


def _issues(value: Any, path: str) -> list[Any]:
    issues = _array(value, path)
    for index, value_item in enumerate(issues):
        item_path = f"{path}[{index}]"
        issue = _object(value_item, item_path)
        _strict_keys(
            issue,
            item_path,
            required={"code", "message"},
            optional={"path", "metadata"},
        )
        code = _non_empty_string(issue["code"], f"{item_path}.code")
        if not _ISSUE_CODE_PATTERN.fullmatch(code):
            raise ContractError(f"{item_path}.code", "must be an uppercase issue code")
        _non_empty_string(issue["message"], f"{item_path}.message")
        if "path" in issue:
            segments = _array(issue["path"], f"{item_path}.path")
            for segment_index, segment in enumerate(segments):
                _string(segment, f"{item_path}.path[{segment_index}]")
        if "metadata" in issue:
            _object(issue["metadata"], f"{item_path}.metadata")
    return issues


def _strict_keys(
    value: dict[str, Any], path: str, *, required: set[str], optional: set[str]
) -> None:
    missing = required - value.keys()
    if missing:
        field = min(missing)
        raise ContractError(f"{path}.{field}", "is required")
    unknown = value.keys() - required - optional
    if unknown:
        field = min(unknown)
        raise ContractError(f"{path}.{field}", "unknown field")


def _reject_json_constant(constant: str) -> None:
    raise ValueError(f"non-finite JSON constant is forbidden: {constant}")


def _strict_json_value(
    value: Any,
    path: str,
    active_containers: set[int] | None = None,
) -> None:
    if active_containers is None:
        active_containers = set()
    value_type = type(value)
    if value is None or value_type in {bool, int}:
        return
    if value_type is str:
        _unicode_scalar_string(value, path)
        return
    if value_type is float:
        if math.isfinite(value):
            return
        raise ContractError(path, "non-finite numbers are not strict JSON values")
    if value_type in {list, dict}:
        container_id = id(value)
        if container_id in active_containers:
            raise ContractError(path, "cycle detected in JSON container")
        active_containers.add(container_id)
        try:
            if value_type is list:
                for index, item in enumerate(value):
                    _strict_json_value(
                        item,
                        f"{path}[{index}]",
                        active_containers,
                    )
                return
            for key, item in value.items():
                if not isinstance(key, str):
                    raise ContractError(
                        path, "object keys must be strings in strict JSON"
                    )
                _unicode_scalar_string(key, path)
                _strict_json_value(item, f"{path}.{key}", active_containers)
            return
        finally:
            active_containers.remove(container_id)
    raise ContractError(path, f"{value_type.__name__} is not a strict JSON value")


def _unicode_scalar_string(value: str, path: str) -> None:
    try:
        value.encode("utf-8")
    except UnicodeEncodeError as exc:
        raise ContractError(path, "must contain only Unicode scalar values") from exc


def _object(value: Any, path: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ContractError(path, "must be an object")
    return value


def _array(value: Any, path: str) -> list[Any]:
    if not isinstance(value, list):
        raise ContractError(path, "must be an array")
    return value


def _string(value: Any, path: str) -> str:
    if not isinstance(value, str):
        raise ContractError(path, "must be a string")
    return value


def _non_empty_string(value: Any, path: str) -> str:
    text = _string(value, path)
    if not text:
        raise ContractError(path, "must not be empty")
    return text


def _integer(value: Any, path: str, *, minimum: int) -> int:
    if type(value) is not int:
        raise ContractError(path, "must be an integer")
    if value < minimum:
        raise ContractError(path, f"must be greater than or equal to {minimum}")
    return value


def _url(value: Any, path: str) -> str:
    text = _non_empty_string(value, path)
    if re.search(r"[\s\x00-\x1f\x7f]", text):
        raise ContractError(path, "must not contain whitespace or control characters")
    try:
        parsed = urlsplit(text)
        hostname = parsed.hostname
        _ = parsed.port
    except ValueError as exc:
        raise ContractError(path, "must be a valid absolute HTTP(S) URL") from exc
    if parsed.scheme.lower() not in {"http", "https"} or not hostname:
        raise ContractError(path, "must be an absolute HTTP(S) URL")
    try:
        hostname.encode("idna")
    except UnicodeError as exc:
        raise ContractError(path, "must contain a valid host") from exc
    return text


def _literal(value: Any, path: str, expected: str) -> str:
    text = _string(value, path)
    if text != expected:
        raise ContractError(path, f"must be {expected!r}")
    return text


def _enum(value: Any, path: str, allowed: set[str] | frozenset[str]) -> str:
    text = _string(value, path)
    if text not in allowed:
        choices = ", ".join(sorted(allowed))
        raise ContractError(path, f"must be one of: {choices}")
    return text


def _hash(value: Any, path: str) -> str:
    text = _string(value, path)
    if not _HASH_PATTERN.fullmatch(text):
        raise ContractError(
            path, "must be sha256: followed by 64 lowercase hex characters"
        )
    return text


def _timestamp(value: Any, path: str) -> str:
    text = _string(value, path)
    if not _TIMESTAMP_PATTERN.fullmatch(text):
        raise ContractError(path, "must be a timezone-aware ISO-8601 timestamp")
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ContractError(path, "must be a valid ISO-8601 timestamp") from exc
    if parsed.utcoffset() is None:
        raise ContractError(path, "must include a timezone offset")
    return text
