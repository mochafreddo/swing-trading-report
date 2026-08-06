from __future__ import annotations

import json
from dataclasses import asdict
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator  # type: ignore[import-untyped]
from sab.decision_board.inputs import (
    approve_swing_snapshot_v0,
    project_research_instruments_v0,
    resolve_entry_identity_v0,
)
from sab.decision_board.instruments import (
    InstrumentRefV0,
    InstrumentRegistryError,
    VersionedInstrumentRegistryV0,
)
from sab.scheduler.holdings import BrokerSnapshotV0

_NOW = datetime(2026, 8, 6, 3, 0, tzinfo=UTC)


def _record(**overrides: object) -> dict[str, object]:
    record: dict[str, object] = {
        "market": "US",
        "canonical_ticker": "AUR.NAS",
        "exchange": "NASDAQ",
        "company_name": "Aurora Synthetic Systems",
        "aliases": ["AURORA.O"],
    }
    record.update(overrides)
    return record


def _registry(
    *records: dict[str, object],
    source: object = "synthetic-directory",
    version: object = "fixture-2026-08-06",
) -> VersionedInstrumentRegistryV0:
    return VersionedInstrumentRegistryV0(
        identity_source=source,
        identity_version=version,
        records=records or (_record(),),
    )


def _holding(**overrides: object) -> dict[str, object]:
    holding: dict[str, object] = {
        "ticker": "AUR.NAS",
        "quantity": "2.000000",
        "entry_price": "190.5000",
        "entry_currency": "USD",
        "entry_date": "2026-08-01",
        "strategy": "SWING",
        "entry_pattern": None,
        "notes": None,
        "tags": [],
        "stop_override": None,
        "target_override": None,
        "broker_state": "confirmed",
        "broker_missing_first_seen_date": None,
        "broker_missing_last_seen_date": None,
        "broker_missing_count": 0,
        "broker_missing_diff_hash": None,
    }
    holding.update(overrides)
    return holding


def _snapshot(*holdings: dict[str, object]) -> BrokerSnapshotV0:
    return BrokerSnapshotV0(
        state_key="toss-sync:success:MIXED:2026-08-06",
        session_date="2026-08-06",
        status="applied",
        fresh_until=_NOW + timedelta(minutes=10),
        sealed_at=_NOW,
        holdings_digest="sha256:" + "a" * 64,
        revision=7,
        marker={"status": "applied"},
        holdings=holdings or (_holding(),),
    )


@pytest.mark.parametrize("strategy", ["SWING", " swing ", "\tSwInG\n"])
def test_exact_ascii_normalized_swing_is_approved(strategy: str) -> None:
    result = approve_swing_snapshot_v0(
        _snapshot(_holding(strategy=strategy)), _registry()
    )[0]

    assert result.status == "APPROVED"
    assert result.approved_ref is not None
    assert result.approved_ref.instrument.canonical_ticker == "AUR.NAS"
    assert result.issues == ()


@pytest.mark.parametrize(
    "strategy",
    [
        pytest.param(None, id="missing"),
        pytest.param("", id="empty"),
        pytest.param("   ", id="blank"),
        pytest.param(7, id="non-string"),
        pytest.param("swing_breakout", id="substring-suffix"),
        pytest.param("long_swing", id="substring-prefix"),
        pytest.param("LONG_TERM", id="long-term"),
        pytest.param("CORE", id="core"),
        pytest.param("\N{NO-BREAK SPACE}SWING\N{NO-BREAK SPACE}", id="non-ascii-trim"),
    ],
)
def test_non_exact_or_missing_strategy_reviews(strategy: object) -> None:
    result = approve_swing_snapshot_v0(
        _snapshot(_holding(strategy=strategy, tags=["SWING"])), _registry()
    )[0]

    assert result.status == "REVIEW"
    assert result.approved_ref is None
    assert [issue.code for issue in result.issues] == ["REVIEW_STRATEGY_NOT_APPROVED"]


@pytest.mark.parametrize(
    ("quantity", "broker_state"),
    [
        pytest.param("0.000000", "confirmed", id="zero"),
        pytest.param("2.000000", "not_seen_in_toss", id="not-confirmed"),
    ],
)
def test_inactive_or_unconfirmed_holding_reviews(
    quantity: str, broker_state: str
) -> None:
    result = approve_swing_snapshot_v0(
        _snapshot(_holding(quantity=quantity, broker_state=broker_state)), _registry()
    )[0]

    assert result.status == "REVIEW"
    assert result.approved_ref is None
    assert [issue.code for issue in result.issues] == ["REVIEW_HOLDING_NOT_ACTIVE"]


def test_resolved_identity_preserves_authoritative_source_and_version() -> None:
    registry = _registry()

    first = registry.resolve("AUR.NAS")
    second = registry.resolve("aur.nas")

    assert first is not None
    assert first == second
    assert first is not second
    assert asdict(first) == {
        "market": "US",
        "canonical_ticker": "AUR.NAS",
        "exchange": "NASDAQ",
        "company_name": "Aurora Synthetic Systems",
        "identity_source": "synthetic-directory",
        "identity_version": "fixture-2026-08-06",
    }


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("company_name", ""),
        ("exchange", " "),
        ("canonical_ticker", "AUR\x00.NAS"),
        ("company_name", "Aurora\N{NEXT LINE}Systems"),
        ("company_name", "\tAurora Synthetic Systems"),
        ("market", "KR"),
    ],
)
def test_registry_rejects_invalid_public_identity_fields(
    field: str, value: object
) -> None:
    with pytest.raises(InstrumentRegistryError):
        _registry(_record(**{field: value}))


@pytest.mark.parametrize(
    ("source", "version"),
    [
        ("", "fixture-v1"),
        ("synthetic-directory", ""),
        (None, "fixture-v1"),
        ("synthetic-directory", None),
    ],
)
def test_registry_requires_explicit_nonblank_source_and_version(
    source: object, version: object
) -> None:
    with pytest.raises(InstrumentRegistryError):
        _registry(source=source, version=version)


def test_registry_rejects_duplicate_canonical_ticker() -> None:
    with pytest.raises(InstrumentRegistryError, match="DUPLICATE_CANONICAL"):
        _registry(_record(), _record(company_name="Aurora Synthetic Two"))


def test_registry_rejects_ambiguous_alias() -> None:
    with pytest.raises(InstrumentRegistryError, match="AMBIGUOUS_ALIAS"):
        _registry(
            _record(),
            _record(
                canonical_ticker="BHR.NYS",
                exchange="NYSE",
                company_name="Blue Harbor Synthetic Robotics",
                aliases=["AURORA.O"],
            ),
        )


def test_registry_rejects_unknown_record_fields() -> None:
    with pytest.raises(InstrumentRegistryError, match="INVALID_RECORD"):
        _registry(_record(account_id="private-smuggling"))


def test_instrument_ref_rejects_invalid_direct_construction() -> None:
    with pytest.raises(InstrumentRegistryError):
        InstrumentRefV0(
            market="KR",
            canonical_ticker="AUR.NAS",
            exchange="NASDAQ",
            company_name="Aurora Synthetic Systems",
            identity_source="synthetic-directory",
            identity_version="fixture-v1",
        )


def test_explicit_alias_resolves_but_unregistered_suffix_guess_does_not() -> None:
    registry = _registry()

    alias = registry.resolve(" aurora.o ")

    assert alias is not None
    assert alias.canonical_ticker == "AUR.NAS"
    assert registry.resolve("AUR.US") is None
    assert registry.resolve("AUR.NYS") is None
    assert registry.resolve("AUR") is None
    assert registry.resolve("\tAUR.NAS") is None


def test_holding_alias_with_conflicting_exchange_reviews() -> None:
    registry = _registry(_record(aliases=["AUR.NYS"]))

    result = approve_swing_snapshot_v0(_snapshot(_holding(ticker="AUR.NYS")), registry)[
        0
    ]

    assert result.status == "REVIEW"
    assert result.approved_ref is None
    assert [issue.code for issue in result.issues] == ["REVIEW_IDENTITY_CONFLICT"]


def test_nonzero_quantity_magnitude_does_not_change_approved_reference() -> None:
    small = approve_swing_snapshot_v0(
        _snapshot(_holding(quantity="0.000001")), _registry()
    )[0]
    large = approve_swing_snapshot_v0(
        _snapshot(_holding(quantity="999999.999999")), _registry()
    )[0]

    assert small.approved_ref == large.approved_ref


def test_mixed_holdings_are_isolated_and_deterministic() -> None:
    registry = _registry(
        _record(),
        _record(
            canonical_ticker="BHR.NYS",
            exchange="NYSE",
            company_name="Blue Harbor Synthetic Robotics",
            aliases=[],
        ),
    )
    results = approve_swing_snapshot_v0(
        _snapshot(
            _holding(ticker="BHR.NYS", strategy="CORE"),
            _holding(ticker="UNKNOWN.NAS"),
            _holding(ticker="AUR.NAS"),
        ),
        registry,
    )

    assert [result.status for result in results] == ["APPROVED", "REVIEW", "REVIEW"]
    assert results[0].approved_ref is not None
    assert results[0].approved_ref.instrument.canonical_ticker == "AUR.NAS"
    assert [issue.code for issue in results[1].issues] == [
        "REVIEW_STRATEGY_NOT_APPROVED"
    ]
    assert [issue.code for issue in results[2].issues] == ["REVIEW_IDENTITY_UNRESOLVED"]


def test_private_holding_values_never_reach_results_issues_or_research_projection(
    caplog: pytest.LogCaptureFixture,
) -> None:
    sentinels = {
        "quantity": "PRIVATE-QUANTITY-7731",
        "entry_price": "PRIVATE-PRICE-9924",
        "notes": "PRIVATE-NOTES-3318",
        "tags": ["PRIVATE-TAG-4485"],
        "stop_override": "PRIVATE-STOP-8204",
        "target_override": "PRIVATE-TARGET-7720",
        "pnl": "PRIVATE-PNL-6601",
        "account_id": "PRIVATE-ACCOUNT-2290",
    }
    results = approve_swing_snapshot_v0(_snapshot(_holding(**sentinels)), _registry())

    serialized = json.dumps(
        {
            "results": [asdict(result) for result in results],
            "research": project_research_instruments_v0(results),
            "logs": caplog.text,
        },
        sort_keys=True,
    )
    for sentinel in (
        "PRIVATE-QUANTITY-7731",
        "PRIVATE-PRICE-9924",
        "PRIVATE-NOTES-3318",
        "PRIVATE-TAG-4485",
        "PRIVATE-STOP-8204",
        "PRIVATE-TARGET-7720",
        "PRIVATE-PNL-6601",
        "PRIVATE-ACCOUNT-2290",
    ):
        assert sentinel not in serialized


def test_entry_gate_resolves_public_identity_only() -> None:
    result = resolve_entry_identity_v0(
        {"ticker": "AUR.NAS", "market": "us", "exchange": "NASDAQ"},
        _registry(),
    )

    assert result.status == "APPROVED"
    assert result.instrument is not None
    assert result.instrument.canonical_ticker == "AUR.NAS"
    assert result.issues == ()


def test_research_projection_matches_shared_instrument_ref_contract() -> None:
    schema = json.loads(
        Path("schemas/decision-board.v0.schema.json").read_text(encoding="utf-8")
    )
    validator = Draft202012Validator(
        {
            "$schema": schema["$schema"],
            "$defs": schema["$defs"],
            "$ref": "#/$defs/InstrumentRefV0",
        }
    )
    result = resolve_entry_identity_v0({"ticker": "AUR.NAS"}, _registry())

    projection = project_research_instruments_v0((result,))

    assert len(projection) == 1
    validator.validate(projection[0])


@pytest.mark.parametrize(
    "candidate",
    [
        pytest.param({"ticker": "UNKNOWN.NAS"}, id="unknown"),
        pytest.param(
            {"ticker": "AUR.NAS", "canonical_ticker": "AUR.NYS"},
            id="canonical-conflict",
        ),
        pytest.param(
            {"ticker": "AUR.NAS", "exchange": "NYSE"},
            id="exchange-conflict",
        ),
        pytest.param(
            {"ticker": "AUR.NAS", "identity_version": "latest"},
            id="version-conflict",
        ),
    ],
)
def test_entry_gate_fails_closed_for_unresolved_or_conflicting_identity(
    candidate: dict[str, object],
) -> None:
    result = resolve_entry_identity_v0(candidate, _registry())

    assert result.status == "REVIEW"
    assert result.instrument is None
    assert result.issues
    assert result.issues[0].code in {
        "REVIEW_IDENTITY_UNRESOLVED",
        "REVIEW_IDENTITY_CONFLICT",
    }


@pytest.mark.parametrize(
    "private_field",
    ["quantity", "entry_price", "pnl", "notes", "tags", "account_id"],
)
def test_entry_gate_rejects_private_field_smuggling(private_field: str) -> None:
    sentinel = f"PRIVATE-{private_field.upper()}-SMUGGLE"
    result = resolve_entry_identity_v0(
        {"ticker": "AUR.NAS", private_field: sentinel}, _registry()
    )

    serialized = json.dumps(asdict(result), sort_keys=True)
    assert result.status == "REVIEW"
    assert result.instrument is None
    assert [issue.code for issue in result.issues] == ["REVIEW_IDENTITY_INPUT_INVALID"]
    assert sentinel not in serialized


def test_gate_requires_validated_broker_snapshot_type() -> None:
    with pytest.raises(TypeError, match="BrokerSnapshotV0"):
        approve_swing_snapshot_v0([_holding()], _registry())  # type: ignore[arg-type]


def test_instrument_boundary_has_no_order_or_network_capability() -> None:
    from sab.decision_board import inputs, instruments

    exported_names = {
        *dir(inputs),
        *dir(instruments),
    }
    forbidden_fragments = ("order", "trade", "request", "http", "toss")

    assert not any(
        fragment in name.lower()
        for name in exported_names
        for fragment in forbidden_fragments
        if not name.startswith("__")
    )
