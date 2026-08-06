from __future__ import annotations

import json
from dataclasses import asdict
from datetime import UTC, datetime, timedelta
from inspect import Parameter, signature
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator  # type: ignore[import-untyped]
from sab.decision_board import inputs as inputs_module
from sab.decision_board import instruments as instruments_module
from sab.decision_board.inputs import (
    SwingApprovedV0,
    SwingReviewV0,
    approve_swing_snapshot_v0,
    project_research_instruments_v0,
    resolve_entry_identity_v0,
)
from sab.decision_board.instruments import (
    InstrumentRefV0,
    InstrumentRegistryError,
    VersionedInstrumentRegistryV0,
    copy_trusted_instrument_ref_v0,
)
from sab.scheduler.holdings import (
    BrokerSnapshotError,
    BrokerSnapshotMarkerV0,
    BrokerSnapshotV0,
    broker_holdings_digest_v0,
    validate_broker_snapshot_v0,
)

_NOW = datetime(2026, 8, 6, 3, 0, tzinfo=UTC)
_PRIVATE_ACCOUNT_SENTINEL = "PRIVATE-ACCOUNT-IDENTITY-9917"


class _InstrumentRefWithPrivateOverride(InstrumentRefV0):
    account_id = _PRIVATE_ACCOUNT_SENTINEL
    projection_called = False

    def to_public_dict(self) -> dict[str, str]:
        type(self).projection_called = True
        return {**super().to_public_dict(), "account_id": self.account_id}


class _FakeRegistryV0:
    account_id = _PRIVATE_ACCOUNT_SENTINEL

    def __init__(self, resolved: object) -> None:
        self.resolved = resolved

    def resolve(self, _lookup_value: object) -> object:
        return self.resolved


class _FakeEntryApprovedV0(inputs_module.EntryIdentityApprovedV0):
    account_id = _PRIVATE_ACCOUNT_SENTINEL


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


def _snapshot(
    *holdings: dict[str, object],
    fresh_until: datetime | None = None,
    sealed_at: datetime | None = None,
    validation_now: datetime = _NOW,
) -> BrokerSnapshotV0:
    rows = list(holdings or (_holding(),))
    digest = broker_holdings_digest_v0(rows)
    seal_time = sealed_at or (_NOW - timedelta(minutes=1))
    expiry = fresh_until or (_NOW + timedelta(minutes=10))
    return validate_broker_snapshot_v0(
        [
            {
                "state_key": "toss-sync:success:MIXED:2026-08-06",
                "session_date": "2026-08-06",
                "status": "applied",
                "fresh_until": expiry.isoformat(),
                "sealed_at": seal_time.isoformat(),
                "holdings_digest": digest,
                "revision": 7,
                "marker": {
                    "scope": "MIXED",
                    "sessionDate": "2026-08-06",
                    "status": "applied",
                    "snapshotDigest": digest,
                    "snapshotRevision": 7,
                    "sealedAt": seal_time.isoformat(),
                },
                "holdings": rows,
            }
        ],
        now=validation_now,
        expected_session_date="2026-08-06",
    )


@pytest.mark.parametrize("strategy", ["SWING", " swing ", "\tSwInG\n"])
def test_exact_ascii_normalized_swing_is_approved(strategy: str) -> None:
    result = approve_swing_snapshot_v0(
        _snapshot(_holding(strategy=strategy)), _registry(), now=_NOW
    )[0]

    assert result.status == "APPROVED"
    assert result.approved_ref is not None
    assert result.approved_ref.instrument.canonical_ticker == "AUR.NAS"
    assert not hasattr(result, "issues")


@pytest.mark.parametrize(
    "strategy",
    [
        pytest.param(None, id="missing"),
        pytest.param("", id="empty"),
        pytest.param("   ", id="blank"),
        pytest.param("swing_breakout", id="substring-suffix"),
        pytest.param("long_swing", id="substring-prefix"),
        pytest.param("LONG_TERM", id="long-term"),
        pytest.param("CORE", id="core"),
        pytest.param("\N{NO-BREAK SPACE}SWING\N{NO-BREAK SPACE}", id="non-ascii-trim"),
    ],
)
def test_non_exact_or_missing_strategy_reviews(strategy: object) -> None:
    result = approve_swing_snapshot_v0(
        _snapshot(_holding(strategy=strategy, tags=["SWING"])),
        _registry(),
        now=_NOW,
    )[0]

    assert result.status == "REVIEW"
    assert not hasattr(result, "approved_ref")
    assert [issue.code for issue in result.issues] == ["REVIEW_STRATEGY_NOT_APPROVED"]


def test_non_string_strategy_is_rejected_by_snapshot_factory() -> None:
    with pytest.raises(BrokerSnapshotError) as exc_info:
        _snapshot(_holding(strategy=7))

    assert exc_info.value.code == "PAYLOAD_INVALID"


@pytest.mark.parametrize(
    "strategy",
    [
        pytest.param("\N{LATIN SMALL LETTER LONG S}wing", id="long-s"),
        pytest.param("\N{FULLWIDTH LATIN CAPITAL LETTER S}WING", id="fullwidth"),
        pytest.param("SWI\N{ZERO WIDTH SPACE}NG", id="zero-width"),
        pytest.param("SWI\N{RIGHT-TO-LEFT OVERRIDE}NG", id="bidi"),
    ],
)
def test_unicode_strategy_confusables_never_approve(strategy: str) -> None:
    result = approve_swing_snapshot_v0(
        _snapshot(_holding(strategy=strategy)), _registry(), now=_NOW
    )[0]

    assert result.status == "REVIEW"
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
        _snapshot(_holding(quantity=quantity, broker_state=broker_state)),
        _registry(),
        now=_NOW,
    )[0]

    assert result.status == "REVIEW"
    assert not hasattr(result, "approved_ref")
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
    assert type(first) is InstrumentRefV0


def test_shared_trusted_instrument_copy_rejects_subclass_and_returns_fresh_value() -> (
    None
):
    instrument = _registry().resolve("AUR.NAS")
    assert instrument is not None

    copied = copy_trusted_instrument_ref_v0(instrument)
    fake = _InstrumentRefWithPrivateOverride(**instrument.to_public_dict())

    assert copied == instrument
    assert copied is not instrument
    assert type(copied) is InstrumentRefV0
    assert copy_trusted_instrument_ref_v0(fake) is None


def test_gate_copies_exact_registry_result_into_trusted_instrument() -> None:
    supplied = InstrumentRefV0(
        market="US",
        canonical_ticker="AUR.NAS",
        exchange="NASDAQ",
        company_name="Aurora Synthetic Systems",
        identity_source="synthetic-directory",
        identity_version="fixture-2026-08-06",
    )
    registry = _FakeRegistryV0(supplied)

    result = resolve_entry_identity_v0(
        {"ticker": "AUR.NAS"},
        registry,  # type: ignore[arg-type]
    )

    assert result.status == "APPROVED"
    assert type(result.instrument) is InstrumentRefV0
    assert result.instrument is not supplied
    assert _PRIVATE_ACCOUNT_SENTINEL not in json.dumps(asdict(result))


def test_gates_reject_polymorphic_registry_result_without_private_leak() -> None:
    forged = _InstrumentRefWithPrivateOverride(
        market="US",
        canonical_ticker="AUR.NAS",
        exchange="NASDAQ",
        company_name="Aurora Synthetic Systems",
        identity_source="synthetic-directory",
        identity_version="fixture-2026-08-06",
    )
    registry = _FakeRegistryV0(forged)

    entry = resolve_entry_identity_v0(
        {"ticker": "AUR.NAS"},
        registry,  # type: ignore[arg-type]
    )
    holding = approve_swing_snapshot_v0(
        _snapshot(),
        registry,  # type: ignore[arg-type]
        now=_NOW,
    )[0]

    serialized = json.dumps(
        {"entry": asdict(entry), "holding": asdict(holding)},
        sort_keys=True,
    )
    assert entry.status == "REVIEW"
    assert holding.status == "REVIEW"
    assert _PRIVATE_ACCOUNT_SENTINEL not in serialized


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


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("canonical_ticker", "\N{LATIN CAPITAL LETTER A WITH RING ABOVE}UR.NAS"),
        ("canonical_ticker", "\N{FULLWIDTH LATIN CAPITAL LETTER A}UR.NAS"),
        ("aliases", ["AUR\N{ZERO WIDTH SPACE}.NAS"]),
        ("aliases", ["AUR\N{RIGHT-TO-LEFT OVERRIDE}.NAS"]),
        ("exchange", "NAS\N{ZERO WIDTH SPACE}"),
    ],
)
def test_registry_identity_keys_require_explicit_ascii_grammar(
    field: str, value: object
) -> None:
    with pytest.raises(InstrumentRegistryError):
        _registry(_record(**{field: value}))


@pytest.mark.parametrize(
    "market",
    [
        pytest.param("u\N{LATIN SMALL LETTER LONG S}", id="long-s"),
        pytest.param("\N{FULLWIDTH LATIN CAPITAL LETTER U}S", id="fullwidth"),
        pytest.param("U\N{ZERO WIDTH SPACE}S", id="zero-width"),
        pytest.param("U\N{RIGHT-TO-LEFT OVERRIDE}S", id="bidi"),
    ],
)
def test_registry_market_requires_exact_ascii_us(market: str) -> None:
    with pytest.raises(InstrumentRegistryError, match="INVALID_MARKET"):
        _registry(_record(market=market))


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("company_name", "Aurora\N{ZERO WIDTH SPACE}Systems"),
        ("company_name", "Aurora\N{RIGHT-TO-LEFT OVERRIDE}Systems"),
        ("company_name", "Aurora\ud800Systems"),
        ("company_name", "Aurora\ufdd0Systems"),
    ],
)
def test_public_unicode_text_rejects_format_surrogate_and_noncharacters(
    field: str, value: object
) -> None:
    with pytest.raises(InstrumentRegistryError):
        _registry(_record(**{field: value}))


@pytest.mark.parametrize(
    ("source", "version"),
    [
        ("synthetic\N{ZERO WIDTH SPACE}-directory", "fixture-v1"),
        ("synthetic-directory", "fixture\N{RIGHT-TO-LEFT OVERRIDE}-v1"),
    ],
)
def test_registry_source_and_version_reject_format_characters(
    source: str, version: str
) -> None:
    with pytest.raises(InstrumentRegistryError):
        _registry(source=source, version=version)


def test_public_unicode_text_is_nfc_normalized_consistently() -> None:
    registry = _registry(
        _record(company_name="A\N{COMBINING RING ABOVE}ngstrom Synthetic"),
        source="source-A\N{COMBINING RING ABOVE}",
        version="version-A\N{COMBINING RING ABOVE}",
    )

    instrument = registry.resolve("AUR.NAS")

    assert instrument is not None
    assert (
        instrument.company_name
        == "\N{LATIN CAPITAL LETTER A WITH RING ABOVE}ngstrom Synthetic"
    )
    assert (
        instrument.identity_source
        == "source-\N{LATIN CAPITAL LETTER A WITH RING ABOVE}"
    )
    assert (
        instrument.identity_version
        == "version-\N{LATIN CAPITAL LETTER A WITH RING ABOVE}"
    )
    equivalent_entry = resolve_entry_identity_v0(
        {
            "ticker": "AUR.NAS",
            "company_name": "A\N{COMBINING RING ABOVE}ngstrom Synthetic",
            "identity_source": "source-A\N{COMBINING RING ABOVE}",
            "identity_version": "version-A\N{COMBINING RING ABOVE}",
        },
        registry,
    )
    assert equivalent_entry.status == "APPROVED"


def test_normalized_alias_collision_is_rejected() -> None:
    with pytest.raises(InstrumentRegistryError, match="AMBIGUOUS_ALIAS"):
        _registry(
            _record(),
            _record(
                canonical_ticker="BHR.NYS",
                exchange="NYSE",
                company_name="Blue Harbor Synthetic Robotics",
                aliases=[" aur.nas "],
            ),
        )


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


def test_approved_constructors_reject_polymorphic_instrument_refs() -> None:
    forged = _InstrumentRefWithPrivateOverride(
        market="US",
        canonical_ticker="AUR.NAS",
        exchange="NASDAQ",
        company_name="Aurora Synthetic Systems",
        identity_source="synthetic-directory",
        identity_version="fixture-v1",
    )

    with pytest.raises(TypeError, match="exact InstrumentRefV0"):
        inputs_module.ApprovedSwingRefV0(instrument=forged)
    with pytest.raises(TypeError, match="exact InstrumentRefV0"):
        inputs_module.EntryIdentityApprovedV0(instrument=forged)


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

    result = approve_swing_snapshot_v0(
        _snapshot(_holding(ticker="AUR.NYS")), registry, now=_NOW
    )[0]

    assert result.status == "REVIEW"
    assert not hasattr(result, "approved_ref")
    assert [issue.code for issue in result.issues] == ["REVIEW_IDENTITY_CONFLICT"]


def test_supported_venue_families_have_one_canonical_normalizer() -> None:
    normalize = getattr(instruments_module, "normalize_us_venue_v0", None)

    assert callable(normalize)
    assert normalize("NAS") == normalize("NASDAQ") == normalize("XNAS") == "NASDAQ"
    assert normalize("NYS") == normalize("NYSE") == normalize("XNYS") == "NYSE"
    assert normalize("AMS") == normalize("AMEX") == normalize("XASE") == "AMEX"


@pytest.mark.parametrize("canonical_ticker", ["AUR.XNAS", "AUR"])
def test_holding_venue_hint_conflicts_with_authoritative_registry_exchange(
    canonical_ticker: str,
) -> None:
    registry = _registry(
        _record(canonical_ticker=canonical_ticker, aliases=["AUR.NYS"])
    )

    result = approve_swing_snapshot_v0(
        _snapshot(_holding(ticker="AUR.NYS")), registry, now=_NOW
    )[0]

    assert result.status == "REVIEW"
    assert not hasattr(result, "approved_ref")
    assert [issue.code for issue in result.issues] == ["REVIEW_IDENTITY_CONFLICT"]


def test_entry_venue_hint_conflicts_with_suffixless_authoritative_identity() -> None:
    registry = _registry(_record(canonical_ticker="AUR", aliases=["AUR.NYS"]))

    result = resolve_entry_identity_v0({"ticker": "AUR.NYS"}, registry)

    assert result.status == "REVIEW"
    assert not hasattr(result, "instrument")
    assert [issue.code for issue in result.issues] == ["REVIEW_IDENTITY_CONFLICT"]


def test_nonzero_quantity_magnitude_does_not_change_approved_reference() -> None:
    small = approve_swing_snapshot_v0(
        _snapshot(_holding(quantity="0.000001")), _registry(), now=_NOW
    )[0]
    large = approve_swing_snapshot_v0(
        _snapshot(_holding(quantity="999999.999999")), _registry(), now=_NOW
    )[0]

    assert isinstance(small, SwingApprovedV0)
    assert isinstance(large, SwingApprovedV0)
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
        now=_NOW,
    )

    assert [result.status for result in results] == ["APPROVED", "REVIEW", "REVIEW"]
    assert isinstance(results[0], SwingApprovedV0)
    assert isinstance(results[1], SwingReviewV0)
    assert isinstance(results[2], SwingReviewV0)
    assert results[0].approved_ref.instrument.canonical_ticker == "AUR.NAS"
    assert [issue.code for issue in results[1].issues] == [
        "REVIEW_STRATEGY_NOT_APPROVED"
    ]
    assert [issue.code for issue in results[2].issues] == ["REVIEW_IDENTITY_UNRESOLVED"]


def test_private_holding_values_never_reach_results_issues_or_research_projection(
    caplog: pytest.LogCaptureFixture,
) -> None:
    sentinels = {
        "quantity": "7731.000001",
        "entry_price": "9924.1234",
        "notes": "PRIVATE-NOTES-3318",
        "tags": ["PRIVATE-TAG-4485"],
        "stop_override": "8204.0000",
        "target_override": "7720.0000",
    }
    results = approve_swing_snapshot_v0(
        _snapshot(_holding(**sentinels)), _registry(), now=_NOW
    )

    serialized = json.dumps(
        {
            "results": [asdict(result) for result in results],
            "research": project_research_instruments_v0(results),
            "logs": caplog.text,
        },
        sort_keys=True,
    )
    for sentinel in (
        "7731.000001",
        "9924.1234",
        "PRIVATE-NOTES-3318",
        "PRIVATE-TAG-4485",
        "8204.0000",
        "7720.0000",
    ):
        assert sentinel not in serialized


@pytest.mark.parametrize("private_field", ["pnl", "account_id"])
def test_snapshot_factory_rejects_private_field_without_echoing_value(
    private_field: str,
) -> None:
    sentinel = f"PRIVATE-{private_field.upper()}-2290"

    with pytest.raises(BrokerSnapshotError) as exc_info:
        _snapshot(_holding(**{private_field: sentinel}))

    assert exc_info.value.code == "PAYLOAD_INVALID"
    assert sentinel not in str(exc_info.value)


def test_entry_gate_resolves_public_identity_only() -> None:
    result = resolve_entry_identity_v0(
        {"ticker": "AUR.NAS", "market": "us", "exchange": "NASDAQ"},
        _registry(),
    )

    assert result.status == "APPROVED"
    assert result.instrument is not None
    assert result.instrument.canonical_ticker == "AUR.NAS"
    assert not hasattr(result, "issues")


@pytest.mark.parametrize(
    "market",
    [
        pytest.param("u\N{LATIN SMALL LETTER LONG S}", id="long-s"),
        pytest.param("\N{FULLWIDTH LATIN CAPITAL LETTER U}S", id="fullwidth"),
        pytest.param("U\N{ZERO WIDTH SPACE}S", id="zero-width"),
        pytest.param("U\N{RIGHT-TO-LEFT OVERRIDE}S", id="bidi"),
    ],
)
def test_entry_market_confusables_are_invalid_public_input(market: str) -> None:
    result = resolve_entry_identity_v0(
        {"ticker": "AUR.NAS", "market": market},
        _registry(),
    )

    assert result.status == "REVIEW"
    assert [issue.code for issue in result.issues] == ["REVIEW_IDENTITY_INPUT_INVALID"]


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
    expected_fields = set(schema["$defs"]["InstrumentRefV0"]["properties"])
    assert set(projection[0]) == expected_fields
    assert projection[0] == {
        "market": "US",
        "canonical_ticker": "AUR.NAS",
        "exchange": "NASDAQ",
        "company_name": "Aurora Synthetic Systems",
        "identity_source": "synthetic-directory",
        "identity_version": "fixture-2026-08-06",
    }


def test_projection_rejects_forged_polymorphic_ref_without_calling_override() -> None:
    forged = _InstrumentRefWithPrivateOverride(
        market="US",
        canonical_ticker="AUR.NAS",
        exchange="NASDAQ",
        company_name="Aurora Synthetic Systems",
        identity_source="synthetic-directory",
        identity_version="fixture-v1",
    )
    result = object.__new__(inputs_module.EntryIdentityApprovedV0)
    object.__setattr__(result, "instrument", forged)
    _InstrumentRefWithPrivateOverride.projection_called = False

    with pytest.raises(TypeError, match="trusted InstrumentRefV0"):
        project_research_instruments_v0((result,))

    assert not _InstrumentRefWithPrivateOverride.projection_called


def test_projection_rejects_polymorphic_approved_variant() -> None:
    instrument = _registry().resolve("AUR.NAS")
    assert instrument is not None
    result = _FakeEntryApprovedV0(instrument=instrument)

    with pytest.raises(TypeError, match="typed identity gate results"):
        project_research_instruments_v0((result,))


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
    assert not hasattr(result, "instrument")
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
    assert not hasattr(result, "instrument")
    assert [issue.code for issue in result.issues] == ["REVIEW_IDENTITY_INPUT_INVALID"]
    assert sentinel not in serialized


def test_gate_requires_validated_broker_snapshot_type() -> None:
    with pytest.raises(TypeError, match="BrokerSnapshotV0"):
        approve_swing_snapshot_v0(
            [_holding()],  # type: ignore[arg-type]
            _registry(),
            now=_NOW,
        )


def test_gate_requires_caller_injected_now() -> None:
    parameter = signature(approve_swing_snapshot_v0).parameters.get("now")

    assert parameter is not None
    assert parameter.default is Parameter.empty


def test_gate_reviews_snapshot_that_expired_after_adapter_validation() -> None:
    snapshot = _snapshot(fresh_until=_NOW + timedelta(seconds=1))

    result = approve_swing_snapshot_v0(
        snapshot,
        _registry(),
        now=_NOW + timedelta(seconds=2),
    )[0]

    assert result.status == "REVIEW"
    assert not hasattr(result, "approved_ref")
    assert [issue.code for issue in result.issues] == ["REVIEW_SNAPSHOT_NOT_APPROVED"]


def test_gate_reviews_snapshot_sealed_after_evaluation_time() -> None:
    future_seal = _NOW + timedelta(seconds=1)
    snapshot = _snapshot(sealed_at=future_seal, validation_now=future_seal)

    result = approve_swing_snapshot_v0(snapshot, _registry(), now=_NOW)[0]

    assert result.status == "REVIEW"
    assert [issue.code for issue in result.issues] == ["REVIEW_SNAPSHOT_NOT_APPROVED"]


def test_gate_accepts_snapshot_sealed_at_evaluation_time() -> None:
    snapshot = _snapshot(sealed_at=_NOW)

    result = approve_swing_snapshot_v0(snapshot, _registry(), now=_NOW)[0]

    assert result.status == "APPROVED"


def test_gate_reviews_freshness_equal_to_evaluation_time() -> None:
    snapshot = _snapshot(fresh_until=_NOW + timedelta(seconds=1))

    result = approve_swing_snapshot_v0(
        snapshot,
        _registry(),
        now=_NOW + timedelta(seconds=1),
    )[0]

    assert result.status == "REVIEW"
    assert [issue.code for issue in result.issues] == ["REVIEW_SNAPSHOT_NOT_APPROVED"]


def test_gate_rechecks_digest_when_private_snapshot_factory_is_misused() -> None:
    valid = _snapshot()
    forged = BrokerSnapshotV0._from_validated(
        state_key=valid.state_key,
        session_date=valid.session_date,
        status=valid.status,
        fresh_until=valid.fresh_until,
        sealed_at=valid.sealed_at,
        holdings_digest="not-a-digest",
        revision=valid.revision,
        marker=BrokerSnapshotMarkerV0(
            scope="MIXED",
            session_date=valid.session_date,
            status=valid.status,
            snapshot_digest="not-a-digest",
            snapshot_revision=valid.revision,
            sealed_at=valid.sealed_at,
        ),
        holdings=valid.holdings,
    )

    result = approve_swing_snapshot_v0(forged, _registry(), now=_NOW)[0]

    assert result.status == "REVIEW"
    assert [issue.code for issue in result.issues] == ["REVIEW_SNAPSHOT_NOT_APPROVED"]


def test_gate_results_are_true_sum_types_without_opposite_fields() -> None:
    approved = approve_swing_snapshot_v0(_snapshot(), _registry(), now=_NOW)[0]
    review = approve_swing_snapshot_v0(
        _snapshot(_holding(strategy="CORE")), _registry(), now=_NOW
    )[0]
    entry_approved = resolve_entry_identity_v0({"ticker": "AUR.NAS"}, _registry())
    entry_review = resolve_entry_identity_v0({"ticker": "UNKNOWN.NAS"}, _registry())

    assert approved.status == "APPROVED"
    assert not hasattr(approved, "issues")
    assert review.status == "REVIEW"
    assert not hasattr(review, "approved_ref")
    assert entry_approved.status == "APPROVED"
    assert not hasattr(entry_approved, "issues")
    assert entry_review.status == "REVIEW"
    assert not hasattr(entry_review, "instrument")


def test_bogus_result_status_cannot_be_constructed() -> None:
    issue = inputs_module.IdentityGateIssueV0(code="REVIEW_TEST", message="Synthetic")
    constructor = inputs_module.SwingApprovalResultV0

    with pytest.raises((TypeError, ValueError)):
        constructor(  # type: ignore[operator]
            status="BOGUS",
            approved_ref=None,
            issues=(issue,),
        )


def test_result_variants_reject_opposite_payload_fields() -> None:
    instrument = _registry().resolve("AUR.NAS")
    assert instrument is not None
    approved_ref = inputs_module.ApprovedSwingRefV0(instrument=instrument)
    issue = inputs_module.IdentityGateIssueV0(code="REVIEW_TEST", message="Synthetic")

    with pytest.raises(TypeError):
        inputs_module.SwingApprovedV0(  # type: ignore[call-arg]
            approved_ref=approved_ref,
            issues=(issue,),
        )
    with pytest.raises(TypeError):
        inputs_module.SwingReviewV0(  # type: ignore[call-arg]
            issues=(issue,),
            approved_ref=approved_ref,
        )
    with pytest.raises(TypeError):
        inputs_module.EntryIdentityApprovedV0(  # type: ignore[call-arg]
            instrument=instrument,
            issues=(issue,),
        )
    with pytest.raises(TypeError):
        inputs_module.EntryIdentityReviewV0(  # type: ignore[call-arg]
            issues=(issue,),
            instrument=instrument,
        )


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
