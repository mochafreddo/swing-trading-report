"""Local-only synthetic LONG_TERM policy compiler for Portfolio Mandate T13."""

from __future__ import annotations

import copy
import re
from datetime import datetime
from typing import Any, TypedDict
from urllib.parse import urlsplit

_UUID_PATTERN = re.compile(
    r"[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}\Z"
)
_TICKER_PATTERN = re.compile(r"[A-Z][A-Z0-9]*(?:[./-][A-Z0-9]+)*\Z")
_CASE_ID_PATTERN = re.compile(r"[a-z0-9][a-z0-9-]{0,63}\Z")
_DECIMAL_PATTERN = re.compile(r"-?(?:0|[1-9][0-9]*)\.[0-9]{6}\Z")
_METRIC_PATTERN = re.compile(r"[a-z][a-z0-9_]{0,63}\Z")
_PERIOD_PATTERN = re.compile(r"[A-Z0-9][A-Z0-9._-]{0,31}\Z")
_UNIT_PATTERN = re.compile(r"[A-Z][A-Z0-9_]{0,31}\Z")
_VERSION_PATTERN = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,127}\Z")
_PRIVATE_FIELDS = frozenset(
    {
        "account_id",
        "account_ref_hash",
        "quantity",
        "entry_price",
        "profit_loss",
        "notes",
        "tags",
    }
)


class PortfolioLongTermContractError(ValueError):
    """A T13 synthetic LONG_TERM fixture failed its public contract."""

    def __init__(self, path: str, message: str) -> None:
        super().__init__(f"{path}: {message}")
        self.path = path
        self.message = message


class LongTermDecisionT13(TypedDict):
    """Public local-only projection for one synthetic LONG_TERM case."""

    case_id: str
    instrument_id: str
    canonical_ticker: str
    status: str
    action: str | None
    reason_code: str
    mode: str


def _object(value: Any, path: str) -> dict[str, Any]:
    if type(value) is not dict:
        raise PortfolioLongTermContractError(path, "must be an object")
    return value


def _keys(value: dict[str, Any], path: str, required: set[str]) -> None:
    actual = set(value)
    if actual != required:
        raise PortfolioLongTermContractError(
            path,
            f"must contain exactly {sorted(required)}",
        )


def _enum(value: Any, path: str, allowed: set[str]) -> str:
    if type(value) is not str or value not in allowed:
        raise PortfolioLongTermContractError(path, f"must be one of {sorted(allowed)}")
    return value


def _text(value: Any, path: str, *, nullable: bool = False) -> str | None:
    if nullable and value is None:
        return None
    if type(value) is not str or not value.strip() or value != value.strip():
        raise PortfolioLongTermContractError(path, "must be non-empty trimmed text")
    return value


def _pattern_text(value: Any, path: str, pattern: re.Pattern[str]) -> str:
    text = _text(value, path)
    assert text is not None
    if pattern.fullmatch(text) is None:
        raise PortfolioLongTermContractError(path, "has an invalid format")
    return text


def _date_time(value: Any, path: str) -> str:
    text = _text(value, path)
    assert text is not None
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError as error:
        raise PortfolioLongTermContractError(
            path, "must be an ISO 8601 date-time"
        ) from error
    if parsed.tzinfo is None:
        raise PortfolioLongTermContractError(path, "must include a UTC offset")
    return text


def _reject_private_fields(value: Any, path: str = "$") -> None:
    if type(value) is dict:
        for key, nested in value.items():
            if key in _PRIVATE_FIELDS:
                raise PortfolioLongTermContractError(
                    f"{path}.{key}", "private field is forbidden"
                )
            _reject_private_fields(nested, f"{path}.{key}")
    elif type(value) is list:
        for index, nested in enumerate(value):
            _reject_private_fields(nested, f"{path}[{index}]")


def validate_portfolio_long_term_t13_fixture(value: Any) -> dict[str, Any]:
    """Validate and copy one shared T13 synthetic fixture without coercion."""

    _reject_private_fields(value)
    fixture = _object(value, "$")
    _keys(
        fixture,
        "$",
        {"schema_version", "mode", "as_of", "cases", "expected_decisions"},
    )
    if fixture["schema_version"] != "portfolio-long-term.t13":
        raise PortfolioLongTermContractError(
            "$.schema_version", "must be portfolio-long-term.t13"
        )
    if fixture["mode"] != "LOCAL_ONLY":
        raise PortfolioLongTermContractError("$.mode", "must be LOCAL_ONLY")
    _date_time(fixture["as_of"], "$.as_of")
    if type(fixture["cases"]) is not list or not fixture["cases"]:
        raise PortfolioLongTermContractError("$.cases", "must be a non-empty array")

    case_ids: set[str] = set()
    for index, raw_case in enumerate(fixture["cases"]):
        path = f"$.cases[{index}]"
        case = _object(raw_case, path)
        _keys(
            case,
            path,
            {"case_id", "instrument", "mandate", "evidence", "concentration"},
        )
        case_id = _pattern_text(case["case_id"], f"{path}.case_id", _CASE_ID_PATTERN)
        if case_id in case_ids:
            raise PortfolioLongTermContractError(f"{path}.case_id", "must be unique")
        case_ids.add(case_id)

        instrument = _object(case["instrument"], f"{path}.instrument")
        _keys(
            instrument,
            f"{path}.instrument",
            {"instrument_id", "canonical_ticker", "company_name"},
        )
        instrument_id = _text(
            instrument["instrument_id"], f"{path}.instrument.instrument_id"
        )
        ticker = _text(
            instrument["canonical_ticker"], f"{path}.instrument.canonical_ticker"
        )
        _text(instrument["company_name"], f"{path}.instrument.company_name")
        if instrument_id is None or _UUID_PATTERN.fullmatch(instrument_id) is None:
            raise PortfolioLongTermContractError(
                f"{path}.instrument.instrument_id", "must be a canonical UUID"
            )
        if ticker is None or _TICKER_PATTERN.fullmatch(ticker) is None:
            raise PortfolioLongTermContractError(
                f"{path}.instrument.canonical_ticker", "must be a public ticker"
            )

        mandate = _object(case["mandate"], f"{path}.mandate")
        _keys(
            mandate,
            f"{path}.mandate",
            {
                "classification_state",
                "approval_state",
                "horizon",
                "thesis",
                "invalidation_predicate",
                "review_cadence",
            },
        )
        classification = _enum(
            mandate["classification_state"],
            f"{path}.mandate.classification_state",
            {"ACTIVE", "UNCLASSIFIED"},
        )
        approval = _enum(
            mandate["approval_state"],
            f"{path}.mandate.approval_state",
            {"APPROVED", "DRAFT"},
        )
        horizon = mandate["horizon"]
        thesis = _text(mandate["thesis"], f"{path}.mandate.thesis", nullable=True)
        predicate = mandate["invalidation_predicate"]
        if classification == "ACTIVE":
            if (
                approval != "APPROVED"
                or horizon != "LONG_TERM"
                or thesis is None
                or type(predicate) is not dict
            ):
                raise PortfolioLongTermContractError(
                    path, "ACTIVE requires approved LONG_TERM thesis and predicate"
                )
            predicate_path = f"{path}.mandate.invalidation_predicate"
            predicate_object = _object(predicate, predicate_path)
            _keys(
                predicate_object,
                predicate_path,
                {"metric", "operator", "threshold", "unit", "period"},
            )
            _pattern_text(
                predicate_object["metric"], f"{predicate_path}.metric", _METRIC_PATTERN
            )
            _enum(
                predicate_object["operator"],
                f"{predicate_path}.operator",
                {"LT", "LTE", "GT", "GTE", "EQ"},
            )
            _pattern_text(
                predicate_object["threshold"],
                f"{predicate_path}.threshold",
                _DECIMAL_PATTERN,
            )
            _pattern_text(
                predicate_object["unit"], f"{predicate_path}.unit", _UNIT_PATTERN
            )
            _pattern_text(
                predicate_object["period"], f"{predicate_path}.period", _PERIOD_PATTERN
            )
        elif (
            approval != "DRAFT"
            or horizon is not None
            or thesis is not None
            or predicate is not None
        ):
            raise PortfolioLongTermContractError(
                path, "UNCLASSIFIED must remain an unapproved no-advice draft"
            )

        cadence = _object(mandate["review_cadence"], f"{path}.mandate.review_cadence")
        _keys(cadence, f"{path}.mandate.review_cadence", {"kind", "due"})
        _enum(
            cadence["kind"],
            f"{path}.mandate.review_cadence.kind",
            {"WEEKLY", "FILING_EVENT"},
        )
        if type(cadence["due"]) is not bool:
            raise PortfolioLongTermContractError(
                f"{path}.mandate.review_cadence.due", "must be boolean"
            )

        evidence = _object(case["evidence"], f"{path}.evidence")
        _keys(
            evidence,
            f"{path}.evidence",
            {
                "validation_status",
                "source_tier",
                "filing_event",
                "predicate_evaluation",
            },
        )
        _enum(
            evidence["validation_status"],
            f"{path}.evidence.validation_status",
            {"VALID", "STALE", "CONFLICTED"},
        )
        _enum(evidence["source_tier"], f"{path}.evidence.source_tier", {"PRIMARY"})
        filing_path = f"{path}.evidence.filing_event"
        filing_event = _object(evidence["filing_event"], filing_path)
        _keys(
            filing_event,
            filing_path,
            {
                "source_id",
                "source_url",
                "publisher",
                "published_at",
                "period",
                "supporting_span",
            },
        )
        source_id = _pattern_text(
            filing_event["source_id"], f"{filing_path}.source_id", _UUID_PATTERN
        )
        assert source_id
        source_url = _text(filing_event["source_url"], f"{filing_path}.source_url")
        assert source_url is not None
        parsed_url = urlsplit(source_url)
        if parsed_url.scheme != "https" or not parsed_url.netloc:
            raise PortfolioLongTermContractError(
                f"{filing_path}.source_url", "must be an absolute HTTPS URL"
            )
        _text(filing_event["publisher"], f"{filing_path}.publisher")
        _date_time(filing_event["published_at"], f"{filing_path}.published_at")
        _pattern_text(filing_event["period"], f"{filing_path}.period", _PERIOD_PATTERN)
        _text(filing_event["supporting_span"], f"{filing_path}.supporting_span")
        evaluation = _object(
            evidence["predicate_evaluation"], f"{path}.evidence.predicate_evaluation"
        )
        _keys(
            evaluation,
            f"{path}.evidence.predicate_evaluation",
            {
                "authority",
                "result",
                "observed_value",
                "unit",
                "period",
                "parser_version",
            },
        )
        authority = _enum(
            evaluation["authority"],
            f"{path}.evidence.predicate_evaluation.authority",
            {"DETERMINISTIC_PARSER", "USER", "AI_RESEARCH"},
        )
        result = _enum(
            evaluation["result"],
            f"{path}.evidence.predicate_evaluation.result",
            {"FULFILLED", "NOT_FULFILLED", "CANDIDATE"},
        )
        _pattern_text(
            evaluation["observed_value"],
            f"{path}.evidence.predicate_evaluation.observed_value",
            _DECIMAL_PATTERN,
        )
        _pattern_text(
            evaluation["unit"],
            f"{path}.evidence.predicate_evaluation.unit",
            _UNIT_PATTERN,
        )
        _pattern_text(
            evaluation["period"],
            f"{path}.evidence.predicate_evaluation.period",
            _PERIOD_PATTERN,
        )
        parser_version = _text(
            evaluation["parser_version"],
            f"{path}.evidence.predicate_evaluation.parser_version",
            nullable=True,
        )
        if (
            parser_version is not None
            and _VERSION_PATTERN.fullmatch(parser_version) is None
        ):
            raise PortfolioLongTermContractError(
                f"{path}.evidence.predicate_evaluation.parser_version",
                "has an invalid format",
            )
        if authority == "AI_RESEARCH" and result != "CANDIDATE":
            raise PortfolioLongTermContractError(
                f"{path}.evidence.predicate_evaluation",
                "AI_RESEARCH may only produce a review-only CANDIDATE",
            )
        if authority == "AI_RESEARCH" and parser_version is not None:
            raise PortfolioLongTermContractError(
                f"{path}.evidence.predicate_evaluation.parser_version",
                "AI_RESEARCH cannot claim a deterministic parser version",
            )
        if authority == "DETERMINISTIC_PARSER" and parser_version is None:
            raise PortfolioLongTermContractError(
                f"{path}.evidence.predicate_evaluation.parser_version",
                "DETERMINISTIC_PARSER requires parser_version provenance",
            )

        concentration = _object(case["concentration"], f"{path}.concentration")
        _keys(concentration, f"{path}.concentration", {"status"})
        _enum(
            concentration["status"], f"{path}.concentration.status", {"PASS", "BREACH"}
        )

    compiled = compile_portfolio_long_term_t13(fixture)
    if fixture["expected_decisions"] != list(compiled):
        raise PortfolioLongTermContractError(
            "$.expected_decisions", "must match the deterministic policy projection"
        )
    return copy.deepcopy(fixture)


def _policy_outcome(case: dict[str, Any]) -> tuple[str, str | None, str]:
    mandate = case["mandate"]
    if mandate["classification_state"] != "ACTIVE":
        return "NO_ADVICE", None, "MANDATE_UNCLASSIFIED"
    if not mandate["review_cadence"]["due"]:
        return "NOT_DUE", None, "REVIEW_NOT_DUE"

    evidence = case["evidence"]
    if evidence["validation_status"] == "STALE":
        return "REVIEW", "REVIEW", "EVIDENCE_STALE"
    if evidence["validation_status"] == "CONFLICTED":
        return "REVIEW", "REVIEW", "EVIDENCE_CONFLICTED"
    if case["concentration"]["status"] == "BREACH":
        return "REVIEW", "REVIEW", "CONCENTRATION_BREACH"

    predicate = evidence["predicate_evaluation"]
    if predicate["authority"] == "AI_RESEARCH":
        return "REVIEW", "REVIEW", "PREDICATE_REVIEW_ONLY"
    if predicate["result"] == "FULFILLED":
        return "DECIDED", "SELL", "PREDICATE_FULFILLED"
    return "DECIDED", "HOLD", "PREDICATE_NOT_FULFILLED"


def compile_portfolio_long_term_t13(
    value: dict[str, Any],
) -> tuple[LongTermDecisionT13, ...]:
    """Compile synthetic T13 cases without external reads or writes."""

    decisions: list[LongTermDecisionT13] = []
    for case in value["cases"]:
        status, action, reason_code = _policy_outcome(case)
        decisions.append(
            LongTermDecisionT13(
                case_id=case["case_id"],
                instrument_id=case["instrument"]["instrument_id"],
                canonical_ticker=case["instrument"]["canonical_ticker"],
                status=status,
                action=action,
                reason_code=reason_code,
                mode="LOCAL_ONLY",
            )
        )
    return tuple(decisions)


__all__ = [
    "LongTermDecisionT13",
    "PortfolioLongTermContractError",
    "compile_portfolio_long_term_t13",
    "validate_portfolio_long_term_t13_fixture",
]
