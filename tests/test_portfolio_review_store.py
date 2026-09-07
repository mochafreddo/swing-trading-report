"""Synthetic importer/transport and review-only persistence boundaries."""

import copy
import json
from dataclasses import replace
from unittest.mock import Mock

import pytest
from sab.portfolio_mandate.review_import import (
    ApprovalBinding,
    EvidenceBinding,
    canonical,
    import_review_packet,
    replay_review_packet,
)
from sab.portfolio_mandate.review_policy import _hash
from sab.portfolio_mandate.review_store import ReviewStore, compiler_sql
from sab.portfolio_mandate.review_transport import (
    AuthenticatedReviewTransport,
    ReviewSession,
)

from tests.test_portfolio_review_r1 import envelope, identity, payload


def synthetic_import(value=None, owner=None, original=None):
    value = copy.deepcopy(value if value is not None else payload())
    owner = owner or identity("owner")
    original = original or canonical(
        {"holdings": [json.loads(r["holding_document"]) for r in value["rows"]]}
    )
    approvals = []
    evidence = {}
    for row in value["rows"]:
        row["source_document_sha256"] = _hash(original)
        approvals.append(
            ApprovalBinding(
                owner,
                row["mandate_version_id"],
                row["instrument_id"],
                _hash(original),
                row["holding_sha256"],
                original,
            )
        )
        for o in row["observations"]:
            content = "Synthetic PRIMARY source; no provider request."
            o["source_content_sha256"] = _hash(content)
            evidence[o["evidence_seal_id"]] = EvidenceBinding(
                o["evidence_seal_id"],
                row["instrument_id"],
                _hash(content),
                o["source_event_time"],
                o["sealed_at"],
                content,
            )
    return envelope(value), {
        "owner_id": owner,
        "approvals": tuple(approvals),
        "evidence": tuple(evidence.values()),
        "review_period": "2026Q2",
        "broker_max_age_seconds": 600,
        "evidence_max_age_seconds": 180 * 86400,
    }


def test_import_replay_privacy_and_default_off():
    raw, bindings = synthetic_import()
    bundle = import_review_packet(raw, **bindings)
    projection = replay_review_packet(bundle)
    assert projection["rows"][0]["status"] == "THESIS_INVALIDATED_REVIEW_REQUIRED"
    assert projection["rows"][0]["action"] is None
    assert not projection["advice_enabled"]
    for key in ("holding_document", "observed_value", "source_document", "owner_id"):
        assert key not in bundle["projection"]
    rpc = Mock()
    with pytest.raises(ValueError, match="REVIEW_WRITER_DISABLED"):
        ReviewStore(rpc).commit(
            bundle,
            run_id=identity("run"),
            owner_id=identity("owner"),
            trigger_id=identity("trigger"),
        )
    rpc.assert_not_called()
    bundle["projection"] += " "
    with pytest.raises(ValueError, match="REVIEW_REPLAY_MISMATCH"):
        replay_review_packet(bundle)


@pytest.mark.parametrize(
    "fault",
    [
        "owner",
        "version",
        "source_hash",
        "holding_hash",
        "original",
        "content",
        "tier",
        "instrument",
        "seal_time",
        "rule",
        "correction",
        "future",
    ],
)
def test_import_rejects_untrusted_bindings_without_echo(fault):
    raw, bindings = synthetic_import()
    a, e = bindings["approvals"][0], bindings["evidence"][0]
    changes = {
        "owner": {"owner_id": identity("other")},
        "version": {"version_id": identity("other")},
        "source_hash": {"source_sha256": "sha256:" + "f" * 64},
        "holding_hash": {"holding_sha256": "sha256:" + "f" * 64},
        "original": {"source_document": "PRIVATE_SENTINEL"},
    }
    if fault in changes:
        bindings["approvals"] = (replace(a, **changes[fault]),)
    elif fault in {"content", "tier", "instrument", "seal_time"}:
        changes = {
            "content": {"content": "PRIVATE_SENTINEL"},
            "tier": {"tier": "SECONDARY"},
            "instrument": {"instrument_id": identity("other")},
            "seal_time": {"sealed_at": "2026-09-08T00:00:00Z"},
        }
        bindings["evidence"] = (replace(e, **changes[fault]),)
    else:
        value = json.loads(raw["payload"])
        o = value["rows"][0]["observations"][0]
        o.update(
            {
                "rule": {"rule_path": "hard_triggers/99/0"},
                "correction": {"supersedes_observation_id": identity("unknown")},
                "future": {"recorded_at": "2027-01-01T00:00:00Z"},
            }[fault]
        )
        raw = envelope(value)
    with pytest.raises(ValueError, match=r"^REVIEW_IMPORT_REJECTED$"):
        import_review_packet(raw, **bindings)


def response(body, status=200, mime="application/json"):
    result = Mock()
    result.__enter__ = Mock(return_value=result)
    result.__exit__ = Mock(return_value=False)
    result.status_code = status
    result.headers = {"content-type": mime}
    result.iter_content.return_value = [json.dumps(body).encode()]
    return result


@pytest.mark.parametrize(
    "fault",
    [
        None,
        "disabled",
        "mapping",
        "owner",
        "role",
        "anonymous",
        "redirect",
        "timeout",
        "auth401",
        "rpc403",
        "mime",
        "oversize",
        "duplicate",
    ],
)
def test_authenticated_transport_binds_verified_user_and_exact_versions(fault):
    user = {"id": identity("owner"), "role": "authenticated", "is_anonymous": False}
    if fault in {"owner", "role", "anonymous"}:
        user.update(
            {
                "owner": {"id": identity("other")},
                "role": {"role": "service_role"},
                "anonymous": {"is_anonymous": True},
            }[fault]
        )
    first = response(
        user, 302 if fault == "redirect" else 401 if fault == "auth401" else 200
    )
    second = response(
        {"ok": True},
        403 if fault == "rpc403" else 200,
        "text/html" if fault == "mime" else "application/json",
    )
    if fault == "oversize":
        second.iter_content.return_value = [b"x" * (3 * 1024 * 1024 + 1)]
    if fault == "duplicate":
        second.iter_content.return_value = [b'{"ok":true,"ok":false}']
    request = Mock(
        side_effect=TimeoutError("PRIVATE_SENTINEL")
        if fault == "timeout"
        else [first, second]
    )
    session = ReviewSession(identity("owner"), (identity("version"),), "fake-bearer")
    assert "fake-bearer" not in repr(session)
    transport = AuthenticatedReviewTransport(
        "https://fixture.invalid",
        "sb_publishable_fixture",
        session,
        request=request,
        enabled=fault != "disabled",
    )
    params = {"p_version_ids": [identity("other" if fault == "mapping" else "version")]}
    if fault:
        with pytest.raises(ValueError) as error:
            transport("read_portfolio_review_r1", params)
        assert "PRIVATE_SENTINEL" not in str(error.value)
        if fault in {"disabled", "mapping"}:
            request.assert_not_called()
    else:
        assert transport("read_portfolio_review_r1", params) == {"ok": True}
        assert [c.args[0] for c in request.call_args_list] == ["GET", "POST"]
        assert all(c.kwargs["allow_redirects"] is False for c in request.call_args_list)
        assert all(c.kwargs["timeout"] == (3, 10) for c in request.call_args_list)


def test_outcome_never_invents_execution_and_sql_cannot_escape():
    rpc = Mock()
    store = ReviewStore(rpc, enabled=True)
    args = {
        "owner_id": identity("owner"),
        "run_id": identity("run"),
        "outcome_id": identity("outcome"),
    }
    for status in ("EXECUTED", "PARTIALLY_EXECUTED", "NO_ACTION"):
        with pytest.raises(ValueError, match="REVIEW_OUTCOME_REJECTED"):
            store.record_outcome(**args, status=status)
    rpc.assert_not_called()
    store.record_outcome(**args, status="UNLINKED")
    assert rpc.call_args.args[1]["p_basis"] == "ORDER_AGGREGATE_ONLY"
    store.record_outcome(
        **args, status="NO_ACTION", confirmed_actor_id=identity("owner")
    )
    sql = compiler_sql("record_outcome_r2", rpc.call_args.args[1])
    assert "set standard_conforming_strings=on" in sql
    with pytest.raises(ValueError, match="REVIEW_RPC_INVALID"):
        compiler_sql("drop table", {})
