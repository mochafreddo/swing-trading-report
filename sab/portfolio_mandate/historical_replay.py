"""Provider-free historical LONG_TERM replay candidate for T19."""

from __future__ import annotations

import copy
import hashlib
import json
import re
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from itertools import pairwise
from typing import Any, Literal, TypedDict, cast
from urllib.parse import urlsplit

_CASE_ID = re.compile(r"[a-z0-9][a-z0-9-]{0,63}\Z")
_CIK = re.compile(r"[0-9]{10}\Z")
_ACCESSION = re.compile(r"[0-9]{10}-[0-9]{2}-[0-9]{6}\Z")
_TICKER = re.compile(r"[A-Z][A-Z0-9.-]{0,15}\Z")
_MIC = re.compile(r"X[A-Z]{3}\Z")
_SHA256 = re.compile(r"sha256:[0-9a-f]{64}\Z")

_GATE_STATE: Literal["CANDIDATE_NOT_APPROVED_NO_PRODUCTION_ADVICE"] = (
    "CANDIDATE_NOT_APPROVED_NO_PRODUCTION_ADVICE"
)
_APPROVED_STATE: Literal["APPROVED_REPLAY_ONLY_NO_PRODUCTION_ADVICE"] = (
    "APPROVED_REPLAY_ONLY_NO_PRODUCTION_ADVICE"
)
_FROZEN_ACTION_SET = frozenset(
    {
        "REVIEW_REQUIRED",
        "THESIS_UNCHANGED",
        "BLOCK_STALE",
        "BLOCK_CONFLICT",
        "BLOCK_INSUFFICIENT",
        "PREDICATE_CANDIDATE",
    }
)
_CASE_TYPES = frozenset(
    {
        "ACTUAL_INVALIDATION",
        "COUNTEREXAMPLE",
        "STALE_EVIDENCE",
        "CONFLICTING_EVIDENCE",
        "INSUFFICIENT_EVIDENCE",
        "UNCHANGED_THESIS",
    }
)


class HistoricalReplayContractError(ValueError):
    """A T19 candidate manifest failed closed."""

    def __init__(self, path: str, message: str) -> None:
        self.path = path
        self.message = message
        super().__init__(f"{path}: {message}")


class HistoricalReplayDecision(TypedDict):
    case_id: str
    expected_action_set: list[str]
    reason: str


class HistoricalReplayCadenceResult(TypedDict):
    gate_state: Literal[
        "CANDIDATE_NOT_APPROVED_NO_PRODUCTION_ADVICE",
        "APPROVED_REPLAY_ONLY_NO_PRODUCTION_ADVICE",
    ]
    cadence_id: str
    scheduled_for: str
    decisions: list[HistoricalReplayDecision]


def _object(value: Any, path: str, keys: set[str]) -> dict[str, Any]:
    if type(value) is not dict:
        raise HistoricalReplayContractError(path, "must be an object")
    if set(value) != keys:
        raise HistoricalReplayContractError(
            path, f"must contain exactly {sorted(keys)}"
        )
    return value


def _text(value: Any, path: str) -> str:
    if type(value) is not str or not value or value != value.strip():
        raise HistoricalReplayContractError(path, "must be non-empty trimmed text")
    return value


def _timestamp(value: Any, path: str) -> datetime:
    text = _text(value, path)
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError as error:
        raise HistoricalReplayContractError(
            path, "must be an ISO 8601 timestamp"
        ) from error
    if parsed.tzinfo is None or parsed.utcoffset() != timedelta(0):
        raise HistoricalReplayContractError(path, "must use an explicit UTC offset")
    return parsed.astimezone(UTC)


def _derived_action(case: dict[str, Any], path: str) -> str:
    evidence_state = case["evidence_state"]
    if evidence_state == "STALE":
        return "BLOCK_STALE"
    if evidence_state == "CONFLICTING":
        return "BLOCK_CONFLICT"
    if evidence_state == "INSUFFICIENT":
        return "BLOCK_INSUFFICIENT"
    if evidence_state != "VALID":
        raise HistoricalReplayContractError(
            f"{path}.evidence_state",
            "must be VALID, STALE, CONFLICTING, or INSUFFICIENT",
        )

    authority = case["authority"]
    result = case["predicate_result"]
    if authority == "AI_RESEARCH":
        if result != "CANDIDATE":
            raise HistoricalReplayContractError(
                f"{path}.authority", "AI_RESEARCH may only produce PREDICATE_CANDIDATE"
            )
        return "PREDICATE_CANDIDATE"
    if authority != "DETERMINISTIC_PARSER":
        raise HistoricalReplayContractError(
            f"{path}.authority", "must be AI_RESEARCH or DETERMINISTIC_PARSER"
        )
    if result == "FULFILLED":
        return "REVIEW_REQUIRED"
    if result == "NOT_FULFILLED":
        return "THESIS_UNCHANGED"
    raise HistoricalReplayContractError(
        f"{path}.predicate_result",
        "deterministic parser must produce FULFILLED or NOT_FULFILLED",
    )


def historical_replay_approval_sha256_t19(manifest: dict[str, Any]) -> str:
    """Bind the contract and user attestation; not a private-key signature."""

    unsigned = copy.deepcopy(manifest)
    unsigned["approval_signature"]["sha256"] = None
    payload = json.dumps(
        unsigned,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    )
    return f"sha256:{hashlib.sha256(payload.encode('utf-8')).hexdigest()}"


def validate_historical_replay_candidate_t19(value: Any) -> dict[str, Any]:
    """Validate and copy the frozen 12-case manifest and optional user approval."""

    manifest = _object(
        value,
        "$",
        {
            "schema_version",
            "gate_state",
            "parser_version",
            "generated_at",
            "frozen_action_set",
            "cases",
            "cadences",
            "approval_signature",
        },
    )
    if manifest["schema_version"] != "portfolio-long-term-replay.t19":
        raise HistoricalReplayContractError("$.schema_version", "must be T19")
    if manifest["gate_state"] not in (_GATE_STATE, _APPROVED_STATE):
        raise HistoricalReplayContractError(
            "$.gate_state", "must prohibit production advice"
        )
    parser_version = _text(manifest["parser_version"], "$.parser_version")
    generated_at = _timestamp(manifest["generated_at"], "$.generated_at")
    approval = manifest["approval_signature"]
    if manifest["gate_state"] == _GATE_STATE and approval is not None:
        raise HistoricalReplayContractError(
            "$.approval_signature", "must be null for an unapproved candidate"
        )
    if manifest["gate_state"] == _APPROVED_STATE:
        approval = _object(
            approval,
            "$.approval_signature",
            {
                "kind",
                "approved_by",
                "recorded_at",
                "approval_text",
                "production_advice_authorized",
                "sha256",
            },
        )
        if (
            approval["kind"] != "USER_ATTESTATION_SHA256"
            or approval["approved_by"] != "USER"
            or approval["production_advice_authorized"] is not False
        ):
            raise HistoricalReplayContractError(
                "$.approval_signature", "must record user approval for replay only"
            )
        if (
            _timestamp(approval["recorded_at"], "$.approval_signature.recorded_at")
            < generated_at
        ):
            raise HistoricalReplayContractError(
                "$.approval_signature.recorded_at", "must not precede the manifest"
            )
        _text(approval["approval_text"], "$.approval_signature.approval_text")
        if approval["sha256"] != historical_replay_approval_sha256_t19(manifest):
            raise HistoricalReplayContractError(
                "$.approval_signature.sha256", "does not match the approved contract"
            )
    frozen = manifest["frozen_action_set"]
    if (
        type(frozen) is not list
        or frozenset(frozen) != _FROZEN_ACTION_SET
        or len(frozen) != len(_FROZEN_ACTION_SET)
    ):
        raise HistoricalReplayContractError(
            "$.frozen_action_set", "must equal the complete non-directional action set"
        )

    raw_cases = manifest["cases"]
    if type(raw_cases) is not list or len(raw_cases) != 12:
        raise HistoricalReplayContractError("$.cases", "must contain exactly 12 cases")
    case_ids: set[str] = set()
    case_types: set[str] = set()
    for index, raw_case in enumerate(raw_cases):
        path = f"$.cases[{index}]"
        case = _object(
            raw_case,
            path,
            {
                "case_id",
                "case_type",
                "issuer",
                "instrument",
                "source",
                "evidence_state",
                "authority",
                "predicate_result",
                "expected_action_set",
                "reason",
            },
        )
        case_id = _text(case["case_id"], f"{path}.case_id")
        if _CASE_ID.fullmatch(case_id) is None or case_id in case_ids:
            raise HistoricalReplayContractError(
                f"{path}.case_id", "must be unique and canonical"
            )
        case_ids.add(case_id)
        case_type = _text(case["case_type"], f"{path}.case_type")
        if case_type not in _CASE_TYPES:
            raise HistoricalReplayContractError(
                f"{path}.case_type", "is not an allowed historical case type"
            )
        case_types.add(case_type)

        issuer = _object(case["issuer"], f"{path}.issuer", {"cik", "legal_name"})
        cik = _text(issuer["cik"], f"{path}.issuer.cik")
        if _CIK.fullmatch(cik) is None:
            raise HistoricalReplayContractError(
                f"{path}.issuer.cik", "must be a ten-digit CIK"
            )
        _text(issuer["legal_name"], f"{path}.issuer.legal_name")

        instrument = _object(
            case["instrument"], f"{path}.instrument", {"ticker", "exchange_mic"}
        )
        if (
            _TICKER.fullmatch(_text(instrument["ticker"], f"{path}.instrument.ticker"))
            is None
        ):
            raise HistoricalReplayContractError(
                f"{path}.instrument.ticker", "has an invalid format"
            )
        if (
            _MIC.fullmatch(
                _text(instrument["exchange_mic"], f"{path}.instrument.exchange_mic")
            )
            is None
        ):
            raise HistoricalReplayContractError(
                f"{path}.instrument.exchange_mic", "has an invalid format"
            )

        source = _object(
            case["source"],
            f"{path}.source",
            {
                "source_url",
                "accession_number",
                "published_at",
                "reporting_period",
                "supporting_span",
                "content_sha256",
                "parser_version",
            },
        )
        accession = _text(source["accession_number"], f"{path}.source.accession_number")
        if _ACCESSION.fullmatch(accession) is None:
            raise HistoricalReplayContractError(
                f"{path}.source.accession_number", "has an invalid format"
            )
        source_url = _text(source["source_url"], f"{path}.source.source_url")
        parsed_url = urlsplit(source_url)
        cik_path = str(int(cik))
        accession_path = accession.replace("-", "")
        if (
            parsed_url.scheme != "https"
            or parsed_url.hostname != "www.sec.gov"
            or f"/Archives/edgar/data/{cik_path}/{accession_path}/"
            not in parsed_url.path
        ):
            raise HistoricalReplayContractError(
                f"{path}.source.source_url",
                "must match the exact SEC issuer and accession identity",
            )
        _timestamp(source["published_at"], f"{path}.source.published_at")
        _text(source["reporting_period"], f"{path}.source.reporting_period")
        span = _text(source["supporting_span"], f"{path}.source.supporting_span")
        content_hash = _text(source["content_sha256"], f"{path}.source.content_sha256")
        expected_hash = "sha256:" + hashlib.sha256(span.encode()).hexdigest()
        if _SHA256.fullmatch(content_hash) is None or content_hash != expected_hash:
            raise HistoricalReplayContractError(
                f"{path}.source.content_sha256",
                "must seal the exact supporting_span bytes",
            )
        if source["parser_version"] != parser_version:
            raise HistoricalReplayContractError(
                f"{path}.source.parser_version",
                "must match the frozen manifest parser_version",
            )
        _text(case["reason"], f"{path}.reason")
        action = _derived_action(case, path)
        expected_actions = case["expected_action_set"]
        if (
            type(expected_actions) is not list
            or len(expected_actions) != 1
            or expected_actions[0] not in _FROZEN_ACTION_SET
        ):
            raise HistoricalReplayContractError(
                f"{path}.expected_action_set", "must stay inside frozen_action_set"
            )
        if expected_actions != [action]:
            raise HistoricalReplayContractError(
                f"{path}.expected_action_set",
                "must match fail-closed deterministic precedence",
            )

    if case_types != _CASE_TYPES:
        raise HistoricalReplayContractError(
            "$.cases", "must cover every required historical case type"
        )

    raw_cadences = manifest["cadences"]
    if type(raw_cadences) is not list or len(raw_cadences) != 4:
        raise HistoricalReplayContractError(
            "$.cadences", "must contain exactly four weekly cadences"
        )
    scheduled: list[datetime] = []
    replayed_ids: list[str] = []
    cadence_ids: set[str] = set()
    for index, raw_cadence in enumerate(raw_cadences):
        path = f"$.cadences[{index}]"
        cadence = _object(
            raw_cadence, path, {"cadence_id", "scheduled_for", "case_ids"}
        )
        cadence_id = _text(cadence["cadence_id"], f"{path}.cadence_id")
        if cadence_id in cadence_ids:
            raise HistoricalReplayContractError(f"{path}.cadence_id", "must be unique")
        cadence_ids.add(cadence_id)
        scheduled.append(_timestamp(cadence["scheduled_for"], f"{path}.scheduled_for"))
        cadence_case_ids = cadence["case_ids"]
        if (
            type(cadence_case_ids) is not list
            or len(cadence_case_ids) != 3
            or any(case_id not in case_ids for case_id in cadence_case_ids)
        ):
            raise HistoricalReplayContractError(
                f"{path}.case_ids", "must contain three known case ids"
            )
        replayed_ids.extend(cadence_case_ids)
    if any(
        later - earlier != timedelta(days=7) for earlier, later in pairwise(scheduled)
    ):
        raise HistoricalReplayContractError("$.cadences", "must be exactly weekly")
    if generated_at >= scheduled[0]:
        raise HistoricalReplayContractError(
            "$.generated_at", "must precede the first frozen cadence"
        )
    if len(replayed_ids) != len(set(replayed_ids)) or set(replayed_ids) != case_ids:
        raise HistoricalReplayContractError(
            "$.cadences", "must replay every case exactly once"
        )

    return copy.deepcopy(manifest)


def replay_historical_cadence_t19(
    manifest: dict[str, Any], *, clock: Callable[[], datetime]
) -> HistoricalReplayCadenceResult:
    """Replay one exact weekly cadence using an injected UTC clock."""

    candidate = validate_historical_replay_candidate_t19(manifest)
    now = clock()
    if now.tzinfo is None:
        raise HistoricalReplayContractError("clock", "must return an aware datetime")
    now = now.astimezone(UTC)
    cadence = next(
        (
            item
            for item in candidate["cadences"]
            if _timestamp(item["scheduled_for"], "$.cadences.scheduled_for") == now
        ),
        None,
    )
    if cadence is None:
        raise HistoricalReplayContractError("clock", "must match one frozen cadence")
    cases = {case["case_id"]: case for case in candidate["cases"]}
    decisions = [
        HistoricalReplayDecision(
            case_id=case_id,
            expected_action_set=list(cases[case_id]["expected_action_set"]),
            reason=cast(str, cases[case_id]["reason"]),
        )
        for case_id in cadence["case_ids"]
    ]
    return HistoricalReplayCadenceResult(
        gate_state=_APPROVED_STATE
        if candidate["gate_state"] == _APPROVED_STATE
        else _GATE_STATE,
        cadence_id=cadence["cadence_id"],
        scheduled_for=cadence["scheduled_for"],
        decisions=decisions,
    )


__all__ = [
    "HistoricalReplayCadenceResult",
    "HistoricalReplayContractError",
    "replay_historical_cadence_t19",
    "validate_historical_replay_candidate_t19",
]
