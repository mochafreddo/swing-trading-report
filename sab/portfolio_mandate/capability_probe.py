"""Recorded, redacted provider capability probe runner for T21."""

from __future__ import annotations

import copy
import re
from typing import Any, Literal, TypedDict, cast
from urllib.parse import urlsplit

_HASH = re.compile(r"sha256:[0-9a-f]{64}\Z")
_ALLOWED_RESULT_CODES = frozenset(
    {
        "COMPLETE",
        "INCOMPLETE_PAGINATION",
        "DUPLICATE_FILL",
        "CURSOR_LOOP",
        "TIMEOUT",
        "HTTP_401",
        "HTTP_403",
        "HTTP_429",
        "HTTP_5XX",
        "MALFORMED_PAYLOAD",
        "REQUEST_BUDGET_EXCEEDED",
        "PAGE_BUDGET_EXCEEDED",
        "BYTE_BUDGET_EXCEEDED",
        "TIME_BUDGET_EXCEEDED",
    }
)
_SENSITIVE_FIELDS = frozenset(
    {
        "account_id",
        "account_number",
        "account_product_code",
        "app_key",
        "app_secret",
        "token",
        "quantity",
        "price",
        "profit_loss",
        "raw_payload",
    }
)


class CapabilityProbeContractError(ValueError):
    """A T21 probe package failed closed."""

    def __init__(self, path: str, message: str) -> None:
        self.path = path
        self.message = message
        super().__init__(f"{path}: {message}")


class CapabilityProbeArtifact(TypedDict):
    schema_version: Literal["portfolio-outcome-capability-artifact.t21"]
    provider_history_state: Literal["NOT_EVALUATED"]
    input_mode: Literal["RECORDED_REDACTED"]
    scenario_id: str
    state: Literal["RECORDED_FIXTURE_PASS", "RECORDED_FIXTURE_FAIL"]
    result_code: str
    requests_attempted: int
    pages_seen: int
    response_bytes: int
    elapsed_ms: int
    capabilities: dict[str, str]
    provider_calls: Literal[0]
    order_operations: Literal[0]


def _object(value: Any, path: str, keys: set[str]) -> dict[str, Any]:
    if type(value) is not dict:
        raise CapabilityProbeContractError(path, "must be an object")
    if set(value) != keys:
        raise CapabilityProbeContractError(path, f"must contain exactly {sorted(keys)}")
    return value


def _text(value: Any, path: str) -> str:
    if type(value) is not str or not value or value != value.strip():
        raise CapabilityProbeContractError(path, "must be non-empty trimmed text")
    return value


def _non_negative_integer(value: Any, path: str) -> int:
    if type(value) is not int or value < 0:
        raise CapabilityProbeContractError(path, "must be a non-negative integer")
    return value


def _reject_sensitive_fields(value: Any, path: str = "$") -> None:
    if type(value) is dict:
        for key, nested in value.items():
            if key in _SENSITIVE_FIELDS:
                raise CapabilityProbeContractError(
                    f"{path}.{key}", "sensitive provider data is forbidden"
                )
            _reject_sensitive_fields(nested, f"{path}.{key}")
    elif type(value) is list:
        for index, nested in enumerate(value):
            _reject_sensitive_fields(nested, f"{path}[{index}]")


def validate_capability_probe_package_t21(value: Any) -> dict[str, Any]:
    """Validate and copy a provider-free recorded probe package."""

    _reject_sensitive_fields(value)
    package = _object(
        value,
        "$",
        {
            "schema_version",
            "input_mode",
            "provider",
            "provider_history_state",
            "probe_contract",
            "scenarios",
        },
    )
    if package["schema_version"] != "portfolio-outcome-capability.t21":
        raise CapabilityProbeContractError("$.schema_version", "must be T21")
    if package["input_mode"] != "RECORDED_REDACTED":
        raise CapabilityProbeContractError("$.input_mode", "must be RECORDED_REDACTED")
    if package["provider"] != "KIS":
        raise CapabilityProbeContractError(
            "$.provider", "must be the explicitly scoped KIS provider"
        )
    if package["provider_history_state"] != "NOT_EVALUATED":
        raise CapabilityProbeContractError(
            "$.provider_history_state", "must remain NOT_EVALUATED before a live probe"
        )

    contract = _object(
        package["probe_contract"],
        "$.probe_contract",
        {
            "requests",
            "budgets",
            "credential_boundary",
            "capabilities",
            "stored_metadata",
            "forbidden_metadata",
            "forbidden_operations",
        },
    )
    requests = contract["requests"]
    if type(requests) is not list or len(requests) != 3:
        raise CapabilityProbeContractError(
            "$.probe_contract.requests",
            "must contain exactly token exchange and two GET history requests",
        )
    expected_requests = [
        (
            "oauth_token_exchange",
            "POST",
            "https://openapi.koreainvestment.com:9443/oauth2/tokenP",
        ),
        (
            "domestic_order_history",
            "GET",
            "https://openapi.koreainvestment.com:9443/uapi/domestic-stock/v1/trading/inquire-daily-ccld",
        ),
        (
            "overseas_order_history",
            "GET",
            "https://openapi.koreainvestment.com:9443/uapi/overseas-stock/v1/trading/inquire-ccnl",
        ),
    ]
    for index, (request, expected) in enumerate(
        zip(requests, expected_requests, strict=True)
    ):
        request = _object(
            request,
            f"$.probe_contract.requests[{index}]",
            {"name", "method", "endpoint"},
        )
        name, method, endpoint = expected
        if request["name"] != name or request["method"] != method:
            required_method = "POST" if index == 0 else "GET"
            raise CapabilityProbeContractError(
                f"$.probe_contract.requests[{index}]",
                f"must be the frozen {required_method} request",
            )
        parsed = urlsplit(
            _text(request["endpoint"], f"$.probe_contract.requests[{index}].endpoint")
        )
        if (
            request["endpoint"] != endpoint
            or parsed.query
            or parsed.fragment
            or parsed.hostname != "openapi.koreainvestment.com"
        ):
            raise CapabilityProbeContractError(
                f"$.probe_contract.requests[{index}].endpoint",
                "must match the exact approved read-only probe endpoint",
            )

    budgets = _object(
        contract["budgets"],
        "$.probe_contract.budgets",
        {"max_requests", "max_pages", "max_response_bytes", "max_elapsed_ms"},
    )
    expected_budgets = {
        "max_requests": 8,
        "max_pages": 4,
        "max_response_bytes": 1_048_576,
        "max_elapsed_ms": 30_000,
    }
    if budgets != expected_budgets:
        raise CapabilityProbeContractError(
            "$.probe_contract.budgets", "must equal the frozen bounded one-shot budget"
        )
    credential_boundary = _object(
        contract["credential_boundary"],
        "$.probe_contract.credential_boundary",
        {
            "required_inputs",
            "usage",
            "token_exchange",
            "persistence",
            "logging",
        },
    )
    expected_credential_boundary = {
        "required_inputs": [
            "app_key",
            "app_secret",
            "account_number",
            "account_product_code",
        ],
        "usage": "USER_APPROVED_PROCESS_MEMORY_ONLY_ONE_SHOT",
        "token_exchange": "ONE_POST_ONLY",
        "persistence": "FORBIDDEN",
        "logging": "FORBIDDEN",
    }
    if credential_boundary != expected_credential_boundary:
        raise CapabilityProbeContractError(
            "$.probe_contract.credential_boundary",
            "must equal the frozen one-shot credential boundary",
        )
    capabilities = _object(
        contract["capabilities"],
        "$.probe_contract.capabilities",
        {
            "oauth_scope",
            "history_retention_window",
            "pagination_cursor",
            "partial_fill",
            "correction_cancel",
            "fill_identity",
            "outage_behavior",
        },
    )
    if any(type(value) is not str or not value for value in capabilities.values()):
        raise CapabilityProbeContractError(
            "$.probe_contract.capabilities", "must define every probe question"
        )
    stored_metadata = contract["stored_metadata"]
    forbidden_metadata = contract["forbidden_metadata"]
    forbidden_operations = contract["forbidden_operations"]
    expected_stored_metadata = [
        "scenario_id",
        "result_code",
        "request_count",
        "page_count",
        "response_byte_count",
        "elapsed_ms",
        "capability_states",
    ]
    if stored_metadata != expected_stored_metadata:
        raise CapabilityProbeContractError(
            "$.probe_contract.stored_metadata",
            "must equal the frozen sanitized metadata allowlist",
        )
    if type(forbidden_metadata) is not list or not _SENSITIVE_FIELDS.issubset(
        forbidden_metadata
    ):
        raise CapabilityProbeContractError(
            "$.probe_contract.forbidden_metadata",
            "must forbid every sensitive provider field",
        )
    if forbidden_operations != ["ORDER_CREATE", "ORDER_MODIFY", "ORDER_CANCEL"]:
        raise CapabilityProbeContractError(
            "$.probe_contract.forbidden_operations",
            "must permanently forbid every order mutation",
        )

    scenarios = package["scenarios"]
    if type(scenarios) is not list or len(scenarios) != 14:
        raise CapabilityProbeContractError(
            "$.scenarios", "must contain all fourteen recorded branches"
        )
    scenario_ids: set[str] = set()
    for scenario_index, raw_scenario in enumerate(scenarios):
        path = f"$.scenarios[{scenario_index}]"
        scenario_keys = {"scenario_id", "expected_result_code", "pages"}
        if type(raw_scenario) is dict and "prior_request_attempts" in raw_scenario:
            scenario_keys.add("prior_request_attempts")
        scenario = _object(raw_scenario, path, scenario_keys)
        scenario_id = _text(scenario["scenario_id"], f"{path}.scenario_id")
        if scenario_id in scenario_ids:
            raise CapabilityProbeContractError(f"{path}.scenario_id", "must be unique")
        scenario_ids.add(scenario_id)
        if scenario["expected_result_code"] not in _ALLOWED_RESULT_CODES:
            raise CapabilityProbeContractError(
                f"{path}.expected_result_code", "is unsupported"
            )
        _non_negative_integer(
            scenario.get("prior_request_attempts", 0),
            f"{path}.prior_request_attempts",
        )
        pages = scenario["pages"]
        if type(pages) is not list or not pages:
            raise CapabilityProbeContractError(
                f"{path}.pages", "must be a non-empty array"
            )
        for page_index, raw_page in enumerate(pages):
            page_path = f"{path}.pages[{page_index}]"
            page = _object(
                raw_page,
                page_path,
                {
                    "request_cursor",
                    "next_cursor",
                    "transport_state",
                    "http_status",
                    "payload_state",
                    "body_bytes",
                    "elapsed_ms",
                    "fills",
                },
            )
            for cursor_key in ("request_cursor", "next_cursor"):
                cursor = page[cursor_key]
                if cursor is not None and (type(cursor) is not str or not cursor):
                    raise CapabilityProbeContractError(
                        f"{page_path}.{cursor_key}", "must be null or text"
                    )
            if page["transport_state"] not in {"RESPONSE", "TIMEOUT"}:
                raise CapabilityProbeContractError(
                    f"{page_path}.transport_state", "is unsupported"
                )
            status = page["http_status"]
            if status is not None and (
                type(status) is not int or not 100 <= status <= 599
            ):
                raise CapabilityProbeContractError(
                    f"{page_path}.http_status", "must be a status code"
                )
            if page["payload_state"] not in {"VALID", "MALFORMED", "ABSENT"}:
                raise CapabilityProbeContractError(
                    f"{page_path}.payload_state", "is unsupported"
                )
            _non_negative_integer(page["body_bytes"], f"{page_path}.body_bytes")
            _non_negative_integer(page["elapsed_ms"], f"{page_path}.elapsed_ms")
            fills = page["fills"]
            if type(fills) is not list:
                raise CapabilityProbeContractError(
                    f"{page_path}.fills", "must be an array"
                )
            for fill_index, raw_fill in enumerate(fills):
                fill_path = f"{page_path}.fills[{fill_index}]"
                fill = _object(raw_fill, fill_path, {"fill_identity_hash", "state"})
                if (
                    _HASH.fullmatch(
                        _text(
                            fill["fill_identity_hash"],
                            f"{fill_path}.fill_identity_hash",
                        )
                    )
                    is None
                ):
                    raise CapabilityProbeContractError(
                        f"{fill_path}.fill_identity_hash", "must be a hash"
                    )
                if fill["state"] not in {
                    "PARTIALLY_FILLED",
                    "FILLED",
                    "CORRECTED",
                    "CANCELED",
                }:
                    raise CapabilityProbeContractError(
                        f"{fill_path}.state", "is unsupported"
                    )
    return copy.deepcopy(package)


def _scenario_result(
    scenario: dict[str, Any], budgets: dict[str, int]
) -> tuple[str, int, int, int, int, set[str]]:
    requests = cast(int, scenario.get("prior_request_attempts", 0))
    pages_seen = 0
    response_bytes = 0
    elapsed_ms = 0
    expected_cursor: str | None = None
    seen_cursors: set[str] = set()
    fill_identities: set[str] = set()
    fill_states: set[str] = set()
    for page in scenario["pages"]:
        requests += 1
        if requests > budgets["max_requests"]:
            return (
                "REQUEST_BUDGET_EXCEEDED",
                requests,
                pages_seen,
                response_bytes,
                elapsed_ms,
                fill_states,
            )
        pages_seen += 1
        if pages_seen > budgets["max_pages"]:
            return (
                "PAGE_BUDGET_EXCEEDED",
                requests,
                pages_seen,
                response_bytes,
                elapsed_ms,
                fill_states,
            )
        response_bytes += cast(int, page["body_bytes"])
        if response_bytes > budgets["max_response_bytes"]:
            return (
                "BYTE_BUDGET_EXCEEDED",
                requests,
                pages_seen,
                response_bytes,
                elapsed_ms,
                fill_states,
            )
        elapsed_ms += cast(int, page["elapsed_ms"])
        if elapsed_ms > budgets["max_elapsed_ms"]:
            return (
                "TIME_BUDGET_EXCEEDED",
                requests,
                pages_seen,
                response_bytes,
                elapsed_ms,
                fill_states,
            )
        if page["transport_state"] == "TIMEOUT":
            return (
                "TIMEOUT",
                requests,
                pages_seen,
                response_bytes,
                elapsed_ms,
                fill_states,
            )
        status = page["http_status"]
        if status in {401, 403, 429}:
            return (
                f"HTTP_{status}",
                requests,
                pages_seen,
                response_bytes,
                elapsed_ms,
                fill_states,
            )
        if type(status) is int and 500 <= status <= 599:
            return (
                "HTTP_5XX",
                requests,
                pages_seen,
                response_bytes,
                elapsed_ms,
                fill_states,
            )
        if page["payload_state"] != "VALID":
            return (
                "MALFORMED_PAYLOAD",
                requests,
                pages_seen,
                response_bytes,
                elapsed_ms,
                fill_states,
            )
        request_cursor = page["request_cursor"]
        if request_cursor != expected_cursor:
            return (
                "INCOMPLETE_PAGINATION",
                requests,
                pages_seen,
                response_bytes,
                elapsed_ms,
                fill_states,
            )
        if request_cursor is not None:
            if request_cursor in seen_cursors:
                return (
                    "CURSOR_LOOP",
                    requests,
                    pages_seen,
                    response_bytes,
                    elapsed_ms,
                    fill_states,
                )
            seen_cursors.add(request_cursor)
        for fill in page["fills"]:
            identity = fill["fill_identity_hash"]
            if identity in fill_identities:
                return (
                    "DUPLICATE_FILL",
                    requests,
                    pages_seen,
                    response_bytes,
                    elapsed_ms,
                    fill_states,
                )
            fill_identities.add(identity)
            fill_states.add(fill["state"])
        expected_cursor = page["next_cursor"]
        if expected_cursor is not None and expected_cursor in seen_cursors:
            return (
                "CURSOR_LOOP",
                requests,
                pages_seen,
                response_bytes,
                elapsed_ms,
                fill_states,
            )
    result = "COMPLETE" if expected_cursor is None else "INCOMPLETE_PAGINATION"
    return result, requests, pages_seen, response_bytes, elapsed_ms, fill_states


def run_recorded_capability_probe_t21(
    package: dict[str, Any], scenario_id: str
) -> CapabilityProbeArtifact:
    """Run one pure recorded branch without transport, credentials, or writes."""

    validated = validate_capability_probe_package_t21(package)
    scenario = next(
        (
            candidate
            for candidate in validated["scenarios"]
            if candidate["scenario_id"] == scenario_id
        ),
        None,
    )
    if scenario is None:
        raise CapabilityProbeContractError("scenario_id", "does not exist")
    budgets = cast(dict[str, int], validated["probe_contract"]["budgets"])
    result_code, requests, pages, byte_count, elapsed_ms, fill_states = (
        _scenario_result(scenario, budgets)
    )
    success = result_code == "COMPLETE"
    capabilities = {
        "oauth_scope": "NOT_EVALUATED",
        "history_retention_window": (
            "RECORDED_FIXTURE_ONLY" if success else "NOT_EVALUATED"
        ),
        "pagination_cursor": (
            "COMPLETE_RECORDED" if success else "RECORDED_FAILURE_CLASSIFIED"
        ),
        "partial_fill": (
            "OBSERVED_RECORDED"
            if "PARTIALLY_FILLED" in fill_states
            else "NOT_EVALUATED"
        ),
        "correction_cancel": (
            "OBSERVED_RECORDED"
            if {"CORRECTED", "CANCELED"}.issubset(fill_states)
            else "NOT_EVALUATED"
        ),
        "fill_identity": (
            "UNIQUE_RECORDED" if success else "RECORDED_FAILURE_CLASSIFIED"
        ),
        "outage_behavior": (
            "NOT_TRIGGERED" if success else "RECORDED_FAILURE_CLASSIFIED"
        ),
    }
    return CapabilityProbeArtifact(
        schema_version="portfolio-outcome-capability-artifact.t21",
        provider_history_state="NOT_EVALUATED",
        input_mode="RECORDED_REDACTED",
        scenario_id=scenario_id,
        state="RECORDED_FIXTURE_PASS" if success else "RECORDED_FIXTURE_FAIL",
        result_code=result_code,
        requests_attempted=requests,
        pages_seen=pages,
        response_bytes=byte_count,
        elapsed_ms=elapsed_ms,
        capabilities=capabilities,
        provider_calls=0,
        order_operations=0,
    )


__all__ = [
    "CapabilityProbeArtifact",
    "CapabilityProbeContractError",
    "run_recorded_capability_probe_t21",
    "validate_capability_probe_package_t21",
]
