from __future__ import annotations

from copy import deepcopy
from dataclasses import FrozenInstanceError, replace
from datetime import UTC, datetime
from inspect import Parameter, signature
from typing import Any

import pytest
import requests
from sab.scheduler import holdings as holdings_module
from sab.scheduler.holdings import (
    BrokerSnapshotError,
    BrokerSnapshotV0,
    SupabaseHoldingsExportConfig,
    broker_holdings_digest_v0,
    fetch_broker_snapshot_v0,
    validate_broker_snapshot_v0,
)

_NOW = datetime(2026, 8, 6, 3, 0, tzinfo=UTC)
_DIGEST = "sha256:" + "0" * 64


def _row(**overrides: object) -> dict[str, object]:
    row: dict[str, object] = {
        "ticker": "AAPL.NAS",
        "quantity": "2.000000",
        "entry_price": "190.5000",
        "entry_currency": "USD",
        "entry_date": "2026-08-01",
        "strategy": "SWING",
        "entry_pattern": "swing_high_breakout",
        "notes": "synthetic note",
        "tags": ["core", "synthetic"],
        "stop_override": "180.0000",
        "target_override": "220.0000",
        "broker_state": "confirmed",
        "broker_missing_first_seen_date": None,
        "broker_missing_last_seen_date": None,
        "broker_missing_count": 0,
        "broker_missing_diff_hash": None,
    }
    row.update(overrides)
    return row


def _digest(rows: list[dict[str, object]]) -> str:
    return broker_holdings_digest_v0(rows)


def _payload(
    *,
    rows: list[dict[str, object]] | None = None,
    digest: str | None = None,
    revision: object = 7,
    marker: object | None = None,
    fresh_until: str = "2026-08-07T15:00:00Z",
) -> list[dict[str, object]]:
    normalized_rows = rows if rows is not None else [_row()]
    computed_digest = digest or _digest(normalized_rows)
    return [
        {
            "state_key": "toss-sync:success:MIXED:2026-08-06",
            "session_date": "2026-08-06",
            "status": "applied",
            "fresh_until": fresh_until,
            "sealed_at": "2026-08-06T02:59:00Z",
            "holdings_digest": computed_digest,
            "revision": revision,
            "marker": marker
            if marker is not None
            else {
                "scope": "MIXED",
                "sessionDate": "2026-08-06",
                "status": "applied",
                "snapshotDigest": computed_digest,
                "snapshotRevision": revision,
                "sealedAt": "2026-08-06T02:59:00Z",
            },
            "holdings": normalized_rows,
        }
    ]


class _FakeResponse:
    def __init__(self, status_code: int, payload: object, text: str = "") -> None:
        self.status_code = status_code
        self._payload = payload
        self.text = text

    def json(self) -> object:
        return self._payload


class _FakeSession:
    def __init__(
        self,
        response: _FakeResponse | None = None,
        error: requests.RequestException | None = None,
    ) -> None:
        self.response = response
        self.error = error
        self.post_calls: list[dict[str, Any]] = []
        self.get_calls: list[dict[str, Any]] = []

    def post(
        self,
        url: str,
        *,
        headers: dict[str, str],
        json: dict[str, object],
        timeout: float,
    ) -> _FakeResponse:
        self.post_calls.append(
            {"url": url, "headers": headers, "json": json, "timeout": timeout}
        )
        if self.error is not None:
            raise self.error
        assert self.response is not None
        return self.response

    def get(self, *args: object, **kwargs: object) -> _FakeResponse:
        self.get_calls.append({"args": args, "kwargs": kwargs})
        raise AssertionError("BrokerSnapshotV0 must not perform a legacy holdings GET")


def _fetch(
    session: _FakeSession,
    *,
    minimum_revision: int | None = None,
) -> BrokerSnapshotV0:
    return fetch_broker_snapshot_v0(
        config=SupabaseHoldingsExportConfig(
            url="https://example.supabase.co",
            service_role_key="sb_secret_synthetic",
            timeout_seconds=3,
        ),
        session=session,
        now=_NOW,
        minimum_revision=minimum_revision,
        expected_session_date="2026-08-06",
    )


def _error_type() -> type[BrokerSnapshotError]:
    return BrokerSnapshotError


def test_broker_holdings_digest_is_deterministic_under_reordering_and_normalization() -> (
    None
):
    first = _row(
        ticker=" aapl.nas ",
        quantity=2,
        entry_price="190.5",
        tags=["synthetic", "core"],
    )
    second = _row(ticker="MSFT.NAS", quantity="1.0", entry_price=410)

    assert _digest([first, second]) == _digest(
        [
            _row(ticker="MSFT.NAS", quantity="1.000000", entry_price="410.0000"),
            _row(),
        ]
    )


def test_broker_holdings_digest_changes_for_material_row_change() -> None:
    assert _digest([_row(quantity=2)]) != _digest([_row(quantity=3)])


def test_broker_holdings_digest_drops_blank_tags_and_uses_utf8_order() -> None:
    assert _digest([_row(tags=[" 한글 ", "", " alpha ", " "])]) == _digest(
        [_row(tags=["alpha", "한글"])]
    )


def test_broker_holdings_digest_matches_database_golden_vector() -> None:
    assert _digest([_row()]) == (
        "sha256:44389ac24342a5d71a7ed7544d6cb751e52f08443094f564da2dd3270b1fcf84"
    )


def test_fetch_broker_snapshot_accepts_one_valid_sealed_rpc_response() -> None:
    payload = _payload()
    session = _FakeSession(_FakeResponse(200, payload))

    snapshot = _fetch(session)

    assert snapshot.revision == 7
    assert snapshot.holdings_digest == payload[0]["holdings_digest"]
    assert [holding.to_dict() for holding in snapshot.holdings] == [_row()]
    assert session.post_calls[0]["url"].endswith("/rest/v1/rpc/get_broker_snapshot_v0")
    assert session.post_calls[0]["json"] == {}
    assert session.get_calls == []


def test_broker_snapshot_requires_validating_factory() -> None:
    assert callable(getattr(holdings_module, "validate_broker_snapshot_v0", None))


def test_broker_snapshot_rejects_direct_arbitrary_construction() -> None:
    with pytest.raises(TypeError, match="validated factory"):
        BrokerSnapshotV0(
            state_key="toss-sync:success:MIXED:2026-08-06",
            session_date="2026-08-06",
            status="blocked",
            fresh_until=datetime(2026, 8, 7, 15, 0, tzinfo=UTC),
            sealed_at=_NOW,
            holdings_digest=_DIGEST,
            revision=0,
            marker={"private": "forged"},
            holdings=(_row(account_id="private"),),
        )


def test_fetched_broker_snapshot_is_deeply_immutable() -> None:
    snapshot = _fetch(_FakeSession(_FakeResponse(200, _payload())))

    with pytest.raises((FrozenInstanceError, TypeError, AttributeError)):
        snapshot.holdings[0]["strategy"] = "CORE"  # type: ignore[index]
    with pytest.raises((FrozenInstanceError, TypeError, AttributeError)):
        snapshot.holdings[0].tags += ("PRIVATE-MUTATION",)  # type: ignore[misc]
    with pytest.raises((FrozenInstanceError, TypeError, AttributeError)):
        snapshot.marker.status = "blocked"  # type: ignore[misc]


def test_validating_factory_revalidates_typed_holding_values() -> None:
    valid = _fetch(_FakeSession(_FakeResponse(200, _payload())))
    forged = replace(valid.holdings[0], quantity="-1.000000")
    forged_digest = (
        "sha256:9c0b23b944774939037013758b21796711b39e2cd798faa24d6dbb71e6a59555"
    )
    payload = _payload(rows=[forged], digest=forged_digest)  # type: ignore[list-item]

    with pytest.raises(BrokerSnapshotError) as exc_info:
        validate_broker_snapshot_v0(
            payload,
            now=_NOW,
            expected_session_date="2026-08-06",
        )

    assert exc_info.value.code == "PAYLOAD_INVALID"


def test_validating_factory_rejects_extra_marker_fields() -> None:
    payload = _payload()
    marker = payload[0]["marker"]
    assert isinstance(marker, dict)
    marker["unexpected"] = "private"

    with pytest.raises(BrokerSnapshotError) as exc_info:
        validate_broker_snapshot_v0(
            payload,
            now=_NOW,
            expected_session_date="2026-08-06",
        )

    assert exc_info.value.code == "MARKER_INVALID"


def test_fetch_broker_snapshot_requires_expected_session_date() -> None:
    parameter = signature(fetch_broker_snapshot_v0).parameters["expected_session_date"]

    assert parameter.default is Parameter.empty


def test_fetch_broker_snapshot_rejects_old_session_even_with_fresh_ttl() -> None:
    payload = _payload(
        marker={
            "scope": "MIXED",
            "sessionDate": "2026-08-05",
            "status": "applied",
            "snapshotDigest": _digest([_row()]),
            "snapshotRevision": 7,
            "sealedAt": "2026-08-06T02:59:00Z",
        },
    )
    payload[0]["session_date"] = "2026-08-05"
    payload[0]["state_key"] = "toss-sync:success:MIXED:2026-08-05"
    session = _FakeSession(_FakeResponse(200, payload))

    with pytest.raises(BrokerSnapshotError) as exc_info:
        _fetch(session)

    assert exc_info.value.code == "SESSION_MISMATCH"


def test_fetch_broker_snapshot_rejects_digest_mismatch() -> None:
    session = _FakeSession(_FakeResponse(200, _payload(digest=_DIGEST)))

    with pytest.raises(_error_type()) as exc_info:
        _fetch(session)

    assert exc_info.value.code == "DIGEST_MISMATCH"


def test_fetch_broker_snapshot_rejects_marker_seal_metadata_mismatch() -> None:
    payload = _payload()
    payload[0]["marker"] = {
        "scope": "MIXED",
        "sessionDate": "2026-08-06",
        "status": "applied",
        "snapshotDigest": _DIGEST,
        "snapshotRevision": 7,
        "sealedAt": "2026-08-06T02:59:00Z",
    }
    session = _FakeSession(_FakeResponse(200, payload))

    with pytest.raises(_error_type()) as exc_info:
        _fetch(session)

    assert exc_info.value.code == "MARKER_INVALID"


@pytest.mark.parametrize(
    ("payload_mutation", "expected_code"),
    [
        (lambda payload: payload[0].update(marker=None), "MARKER_INVALID"),
        (
            lambda payload: payload[0].update(fresh_until="2026-08-06T02:59:59Z"),
            "MARKER_EXPIRED",
        ),
        (
            lambda payload: payload[0].update(status="blocked"),
            "MARKER_INVALID",
        ),
    ],
)
def test_fetch_broker_snapshot_rejects_missing_stale_or_unconfirmed_marker(
    payload_mutation: Any,
    expected_code: str,
) -> None:
    payload = _payload()
    payload_mutation(payload)
    session = _FakeSession(_FakeResponse(200, payload))

    with pytest.raises(_error_type()) as exc_info:
        _fetch(session)

    assert exc_info.value.code == expected_code


@pytest.mark.parametrize("revision", [None, 0, -1, True, "7", 1.5])
def test_fetch_broker_snapshot_rejects_invalid_revision_shape(revision: object) -> None:
    session = _FakeSession(_FakeResponse(200, _payload(revision=revision)))

    with pytest.raises(_error_type()) as exc_info:
        _fetch(session)

    assert exc_info.value.code == "REVISION_INVALID"


def test_fetch_broker_snapshot_rejects_non_monotonic_revision() -> None:
    session = _FakeSession(_FakeResponse(200, _payload(revision=7)))

    with pytest.raises(_error_type()) as exc_info:
        _fetch(session, minimum_revision=7)

    assert exc_info.value.code == "REVISION_INVALID"


@pytest.mark.parametrize(
    "case",
    [
        "object",
        "empty",
        "unexpected",
        "holdings_object",
        "malformed_row",
    ],
)
def test_fetch_broker_snapshot_rejects_malformed_payload(case: str) -> None:
    payload: object
    if case == "object":
        payload = {}
    elif case == "empty":
        payload = []
    elif case == "unexpected":
        payload = [{"unexpected": True}]
    elif case == "holdings_object":
        payload = [{**_payload()[0], "holdings": {}}]
    else:
        payload = [{**_payload()[0], "holdings": [{"ticker": "AAPL.NAS"}]}]
    session = _FakeSession(_FakeResponse(200, deepcopy(payload)))

    with pytest.raises(_error_type()) as exc_info:
        _fetch(session)

    assert exc_info.value.code == "PAYLOAD_INVALID"


def test_fetch_broker_snapshot_rejects_unavailable_rpc() -> None:
    session = _FakeSession(error=requests.ConnectionError("synthetic unavailable"))

    with pytest.raises(_error_type()) as exc_info:
        _fetch(session)

    assert exc_info.value.code == "RPC_UNAVAILABLE"


def test_fetch_broker_snapshot_rejects_ambiguous_response_cardinality() -> None:
    payload = _payload()
    session = _FakeSession(_FakeResponse(200, [payload[0], deepcopy(payload[0])]))

    with pytest.raises(_error_type()) as exc_info:
        _fetch(session)

    assert exc_info.value.code == "PAYLOAD_INVALID"
