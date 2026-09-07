"""Validate explicit approval/source bindings before producing an immutable R2 packet."""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from typing import Any
from uuid import UUID

from .review_policy import _hash, _json, _time, compile_portfolio_review_r1


def canonical(value: object) -> str:
    return json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    )


@dataclass(frozen=True)
class ApprovalBinding:
    """Caller supplies these from the approved mapping, never from the RPC response."""

    owner_id: str
    version_id: str
    instrument_id: str
    source_sha256: str
    holding_sha256: str
    source_document: str = field(repr=False)


@dataclass(frozen=True)
class EvidenceBinding:
    seal_id: str
    instrument_id: str
    content_sha256: str
    source_event_time: str
    sealed_at: str
    content: str = field(repr=False)
    tier: str = "PRIMARY"


def import_review_packet(
    envelope: object,
    *,
    owner_id: str,
    approvals: tuple[ApprovalBinding, ...],
    evidence: tuple[EvidenceBinding, ...],
    review_period: str,
    broker_max_age_seconds: int,
    evidence_max_age_seconds: int,
) -> dict[str, Any]:
    """No IO. Return exact private input plus a compiler-only public projection.

    Hashes establish byte identity, not approval authority. The caller must obtain
    independent approved bindings and PRIMARY source records before calling this.
    This imports a sealed review packet, not an A1 activation or a backfill.
    """
    try:
        if str(UUID(owner_id)) != owner_id:
            raise ValueError
        if (
            not 1 <= len(approvals) <= 100
            or len(evidence) > 1000
            or any(len(a.source_document.encode()) > 2 * 1024 * 1024 for a in approvals)
            or any(len(e.content.encode()) > 1024 * 1024 for e in evidence)
        ):
            raise ValueError
        budgets = {
            "review_period": review_period,
            "broker_max_age_seconds": broker_max_age_seconds,
            "evidence_max_age_seconds": evidence_max_age_seconds,
        }
        projection = compile_portfolio_review_r1(envelope, **budgets)  # type: ignore[arg-type]
        assert isinstance(envelope, dict)
        value = _json(envelope["payload"])
        bound = {a.version_id: a for a in approvals}
        sources = {e.seal_id: e for e in evidence}
        if (
            not approvals
            or len(bound) != len(approvals)
            or len(sources) != len(evidence)
            or set(bound) != {r["mandate_version_id"] for r in value["rows"]}
        ):
            raise ValueError
        used: set[str] = set()
        for row in value["rows"]:
            approval = bound[row["mandate_version_id"]]
            original = _json(approval.source_document)
            holding = _json(row["holding_document"])
            if (
                approval.owner_id != owner_id
                or approval.instrument_id != row["instrument_id"]
                or _hash(approval.source_document) != approval.source_sha256
                or row["source_document_sha256"] != approval.source_sha256
                or row["holding_sha256"] != approval.holding_sha256
                or holding not in original["holdings"]
                or any(
                    holding[k] != expected
                    for k, expected in (
                        ("approval_state", "APPROVED"),
                        ("classification_state", "ACTIVE"),
                        ("horizon", "LONG_TERM"),
                    )
                )
            ):
                raise ValueError
            observations = {o["observation_id"]: o for o in row["observations"]}
            if len(observations) != len(row["observations"]):
                raise ValueError
            superseded: set[str] = set()
            for o in observations.values():
                source = sources[o["evidence_seal_id"]]
                used.add(source.seal_id)
                if (
                    source.tier != "PRIMARY"
                    or source.content_sha256 != _hash(source.content)
                    or source.content_sha256 != o["source_content_sha256"]
                    or source.instrument_id != row["instrument_id"]
                    or o["source_instrument_id"] != source.instrument_id
                    or _time(o["source_event_time"]) != _time(source.source_event_time)
                    or _time(o["sealed_at"]) != _time(source.sealed_at)
                    or not _time(source.source_event_time)
                    <= _time(source.sealed_at)
                    <= _time(o["recorded_at"])
                    <= _time(value["read_at"])
                ):
                    raise ValueError
                branch, trigger_index, condition_index = o["rule_path"].split("/")
                policy = holding["invalidation_policy"]
                triggers = (
                    policy["hard_triggers"]
                    if branch == "hard_triggers"
                    else policy["deterioration_rule"]["signals"]
                )
                condition = triggers[int(trigger_index)]["conditions"][
                    int(condition_index)
                ]
                if (o["metric"], o["unit"]) != (condition["metric"], condition["unit"]):
                    raise ValueError
                previous_id = o["supersedes_observation_id"]
                if previous_id is not None:
                    previous = observations[previous_id]
                    if (
                        previous_id in superseded
                        or (previous["rule_path"], previous["period_key"])
                        != (o["rule_path"], o["period_key"])
                        or _time(previous["recorded_at"]) >= _time(o["recorded_at"])
                    ):
                        raise ValueError
                    superseded.add(previous_id)
        if used != set(sources):
            raise ValueError
        # Bind compiler/configuration and the exact sealed bytes into replay identity.
        packet = {
            "schema_version": "portfolio-review-packet.r2",
            "compiler_version": "review-r1/1",
            "owner_id": owner_id,
            "input": envelope,
            "parameters": budgets,
            "approvals": [
                asdict(a) for a in sorted(approvals, key=lambda a: a.version_id)
            ],
            "sources": [asdict(e) for e in sorted(evidence, key=lambda e: e.seal_id)],
        }
        raw, result = canonical(packet), canonical(projection)
        if len(raw.encode()) > 4 * 1024 * 1024 or len(result.encode()) > 262144:
            raise ValueError
        return {
            "packet": raw,
            "packet_sha256": _hash(raw),
            "projection": result,
            "projection_sha256": _hash(result),
        }
    except Exception:
        raise ValueError("REVIEW_IMPORT_REJECTED") from None


def replay_review_packet(bundle: dict[str, Any]) -> dict[str, Any]:
    """Recompile sealed input with its original clock and budgets, compare exact bytes."""
    try:
        if _hash(bundle["packet"]) != bundle["packet_sha256"]:
            raise ValueError
        packet = _json(bundle["packet"])
        if packet["compiler_version"] != "review-r1/1":
            raise ValueError
        validated = import_review_packet(
            packet["input"],
            owner_id=packet["owner_id"],
            approvals=tuple(ApprovalBinding(**a) for a in packet["approvals"]),
            evidence=tuple(EvidenceBinding(**e) for e in packet["sources"]),
            **packet["parameters"],
        )
        if validated != bundle:
            raise ValueError
        result = compile_portfolio_review_r1(packet["input"], **packet["parameters"])
        raw = canonical(result)
        if raw != bundle["projection"] or _hash(raw) != bundle["projection_sha256"]:
            raise ValueError
        return result
    except Exception:
        raise ValueError("REVIEW_REPLAY_MISMATCH") from None
