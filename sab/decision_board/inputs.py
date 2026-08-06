"""Fail-closed public identity gates for Decision Board V0 inputs."""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from dataclasses import field as dataclass_field
from datetime import datetime
from decimal import Decimal, InvalidOperation
from typing import Literal

from sab.scheduler.holdings import BrokerSnapshotV0

from .instruments import (
    InstrumentRefV0,
    VersionedInstrumentRegistryV0,
    _copy_trusted_instrument_ref_v0,
    _normalize_us_market_v0,
    normalize_identity_key_v0,
    normalize_public_text_v0,
    normalize_us_venue_v0,
    ticker_venue_hint_v0,
)

_ASCII_WHITESPACE = " \t\n\r\f\v"
_ENTRY_PUBLIC_FIELDS = {
    "ticker",
    "market",
    "canonical_ticker",
    "exchange",
    "company_name",
    "identity_source",
    "identity_version",
}


@dataclass(frozen=True, slots=True)
class IdentityGateIssueV0:
    """A public, typed issue that intentionally carries no raw input values."""

    code: str
    message: str


@dataclass(frozen=True, slots=True)
class ApprovedSwingRefV0:
    """A directional-eligible holding identity without account-private fields."""

    instrument: InstrumentRefV0

    def __post_init__(self) -> None:
        trusted = _copy_trusted_instrument_ref_v0(self.instrument)
        if trusted is None:
            raise TypeError("ApprovedSwingRefV0 requires exact InstrumentRefV0")
        object.__setattr__(self, "instrument", trusted)


@dataclass(frozen=True, slots=True)
class SwingApprovedV0:
    approved_ref: ApprovedSwingRefV0
    status: Literal["APPROVED"] = dataclass_field(default="APPROVED", init=False)

    def __post_init__(self) -> None:
        if type(self.approved_ref) is not ApprovedSwingRefV0:
            raise TypeError("SwingApprovedV0 requires exact ApprovedSwingRefV0")


@dataclass(frozen=True, slots=True)
class SwingReviewV0:
    issues: tuple[IdentityGateIssueV0, ...]
    status: Literal["REVIEW"] = dataclass_field(default="REVIEW", init=False)

    def __post_init__(self) -> None:
        if not self.issues or not all(
            isinstance(issue, IdentityGateIssueV0) for issue in self.issues
        ):
            raise ValueError("SwingReviewV0 requires typed issues")


type SwingApprovalResultV0 = SwingApprovedV0 | SwingReviewV0


@dataclass(frozen=True, slots=True)
class EntryIdentityApprovedV0:
    instrument: InstrumentRefV0
    status: Literal["APPROVED"] = dataclass_field(default="APPROVED", init=False)

    def __post_init__(self) -> None:
        trusted = _copy_trusted_instrument_ref_v0(self.instrument)
        if trusted is None:
            raise TypeError("EntryIdentityApprovedV0 requires exact InstrumentRefV0")
        object.__setattr__(self, "instrument", trusted)


@dataclass(frozen=True, slots=True)
class EntryIdentityReviewV0:
    issues: tuple[IdentityGateIssueV0, ...]
    status: Literal["REVIEW"] = dataclass_field(default="REVIEW", init=False)

    def __post_init__(self) -> None:
        if not self.issues or not all(
            isinstance(issue, IdentityGateIssueV0) for issue in self.issues
        ):
            raise ValueError("EntryIdentityReviewV0 requires typed issues")


type EntryIdentityResultV0 = EntryIdentityApprovedV0 | EntryIdentityReviewV0


def approve_swing_snapshot_v0(
    snapshot: BrokerSnapshotV0,
    registry: VersionedInstrumentRegistryV0,
    *,
    now: datetime,
) -> tuple[SwingApprovalResultV0, ...]:
    """Approve exact active SWING rows from an already validated broker DTO."""

    if not isinstance(snapshot, BrokerSnapshotV0):
        raise TypeError("snapshot must be a validated BrokerSnapshotV0")
    ordered_holdings = sorted(
        snapshot.holdings,
        key=lambda row: _public_lookup_key(row.ticker),
    )
    if snapshot.approval_issue_code(now=now) is not None:
        return tuple(
            SwingReviewV0(
                issues=(
                    IdentityGateIssueV0(
                        code="REVIEW_SNAPSHOT_NOT_APPROVED",
                        message="Broker snapshot seal is not approved at evaluation time.",
                    ),
                ),
            )
            for _holding in ordered_holdings
        )
    return tuple(_approve_holding(row, registry) for row in ordered_holdings)


def resolve_entry_identity_v0(
    candidate: Mapping[str, object],
    registry: VersionedInstrumentRegistryV0,
) -> EntryIdentityResultV0:
    """Resolve a strict public-only ENTRY candidate through the registry."""

    if not isinstance(candidate, Mapping) or set(candidate) - _ENTRY_PUBLIC_FIELDS:
        return _entry_review(
            "REVIEW_IDENTITY_INPUT_INVALID",
            "ENTRY identity input must contain public identity fields only.",
        )
    if (
        "ticker" not in candidate
        or normalize_identity_key_v0(candidate["ticker"]) is None
    ):
        return _entry_review(
            "REVIEW_IDENTITY_INPUT_INVALID",
            "ENTRY identity input requires one public ticker lookup key.",
        )
    for field in set(candidate) - {"ticker"}:
        value = candidate[field]
        if field == "canonical_ticker":
            valid = normalize_identity_key_v0(value) is not None
        elif field == "exchange":
            valid = normalize_us_venue_v0(value) is not None
        elif field == "market":
            valid = _normalize_us_market_v0(value) is not None
        else:
            valid = normalize_public_text_v0(value) is not None
        if not valid:
            return _entry_review(
                "REVIEW_IDENTITY_INPUT_INVALID",
                "ENTRY identity hints must be nonblank public strings.",
            )

    instrument = _resolve_trusted_instrument_v0(registry, candidate["ticker"])
    if instrument is None:
        return _entry_review(
            "REVIEW_IDENTITY_UNRESOLVED",
            "ENTRY identity did not resolve in the sealed registry.",
        )
    if _candidate_conflicts(candidate, instrument):
        return _entry_review(
            "REVIEW_IDENTITY_CONFLICT",
            "ENTRY identity conflicts with the sealed registry binding.",
        )
    return EntryIdentityApprovedV0(instrument=instrument)


def project_research_instruments_v0(
    results: Iterable[SwingApprovalResultV0 | EntryIdentityResultV0],
) -> tuple[dict[str, str], ...]:
    """Project approved identities into a deterministic public-only payload."""

    instruments: dict[tuple[str, ...], InstrumentRefV0] = {}
    for result in results:
        instrument: InstrumentRefV0 | None
        if type(result) is SwingApprovedV0:
            if type(result.approved_ref) is not ApprovedSwingRefV0:
                raise TypeError("research projection requires trusted InstrumentRefV0")
            instrument = _copy_trusted_instrument_ref_v0(result.approved_ref.instrument)
        elif type(result) is EntryIdentityApprovedV0:
            instrument = _copy_trusted_instrument_ref_v0(result.instrument)
        elif type(result) in {SwingReviewV0, EntryIdentityReviewV0}:
            instrument = None
        else:
            raise TypeError("research projection requires typed identity gate results")
        if (
            type(result) in {SwingApprovedV0, EntryIdentityApprovedV0}
            and instrument is None
        ):
            raise TypeError("research projection requires trusted InstrumentRefV0")
        if instrument is None:
            continue
        key = (
            instrument.market,
            instrument.canonical_ticker,
            instrument.exchange,
            instrument.company_name,
            instrument.identity_source,
            instrument.identity_version,
        )
        instruments[key] = instrument
    return tuple(
        {
            "market": instruments[key].market,
            "canonical_ticker": instruments[key].canonical_ticker,
            "exchange": instruments[key].exchange,
            "company_name": instruments[key].company_name,
            "identity_source": instruments[key].identity_source,
            "identity_version": instruments[key].identity_version,
        }
        for key in sorted(
            instruments, key=lambda item: tuple(v.encode("utf-8") for v in item)
        )
    )


def _approve_holding(
    holding: Mapping[str, object],
    registry: VersionedInstrumentRegistryV0,
) -> SwingApprovalResultV0:
    issues: list[IdentityGateIssueV0] = []
    if not _is_active_confirmed_holding(holding):
        issues.append(
            IdentityGateIssueV0(
                code="REVIEW_HOLDING_NOT_ACTIVE",
                message="Holding is not an active confirmed broker position.",
            )
        )
    if not _is_exact_swing(holding.get("strategy")):
        issues.append(
            IdentityGateIssueV0(
                code="REVIEW_STRATEGY_NOT_APPROVED",
                message="Holding strategy is not exact normalized SWING.",
            )
        )
    instrument = _resolve_trusted_instrument_v0(registry, holding.get("ticker"))
    if instrument is None:
        issues.append(
            IdentityGateIssueV0(
                code="REVIEW_IDENTITY_UNRESOLVED",
                message="Holding identity did not resolve in the sealed registry.",
            )
        )
    elif _holding_identity_conflicts(holding, instrument):
        issues.append(
            IdentityGateIssueV0(
                code="REVIEW_IDENTITY_CONFLICT",
                message="Holding identity conflicts with the sealed registry binding.",
            )
        )
    if issues:
        return SwingReviewV0(issues=tuple(issues))
    assert instrument is not None
    return SwingApprovedV0(
        approved_ref=ApprovedSwingRefV0(instrument=instrument),
    )


def _is_exact_swing(value: object) -> bool:
    if not isinstance(value, str):
        return False
    normalized = value.strip(_ASCII_WHITESPACE)
    return (
        normalized.isascii() and normalized.isalpha() and normalized.upper() == "SWING"
    )


def _is_active_confirmed_holding(holding: Mapping[str, object]) -> bool:
    if holding.get("broker_state") != "confirmed":
        return False
    quantity = holding.get("quantity")
    if isinstance(quantity, bool) or not isinstance(
        quantity, (int, float, str, Decimal)
    ):
        return False
    try:
        return Decimal(str(quantity)).is_finite() and Decimal(str(quantity)) > 0
    except InvalidOperation, ValueError:
        return False


def _entry_review(code: str, message: str) -> EntryIdentityResultV0:
    return EntryIdentityReviewV0(
        issues=(IdentityGateIssueV0(code=code, message=message),),
    )


def _resolve_trusted_instrument_v0(
    registry: object, lookup_value: object
) -> InstrumentRefV0 | None:
    resolver = getattr(registry, "resolve", None)
    if not callable(resolver):
        return None
    try:
        resolved = resolver(lookup_value)
    except Exception:
        return None
    return _copy_trusted_instrument_ref_v0(resolved)


def _candidate_conflicts(
    candidate: Mapping[str, object], instrument: InstrumentRefV0
) -> bool:
    expected = {
        "market": instrument.market,
        "canonical_ticker": instrument.canonical_ticker,
        "exchange": instrument.exchange,
        "company_name": instrument.company_name,
        "identity_source": instrument.identity_source,
        "identity_version": instrument.identity_version,
    }
    for field, expected_value in expected.items():
        if field not in candidate:
            continue
        candidate_value = candidate[field]
        assert isinstance(candidate_value, str)
        if field == "exchange":
            normalized_venue = normalize_us_venue_v0(candidate_value)
            if normalized_venue != instrument.exchange:
                return True
            continue
        if field == "canonical_ticker":
            normalized = normalize_identity_key_v0(candidate_value)
        elif field == "market":
            normalized = _normalize_us_market_v0(candidate_value)
        else:
            normalized = normalize_public_text_v0(candidate_value)
        if normalized != expected_value:
            return True

    ticker = candidate["ticker"]
    assert isinstance(ticker, str)
    candidate_venue = ticker_venue_hint_v0(ticker)
    return candidate_venue is not None and candidate_venue != instrument.exchange


def _holding_identity_conflicts(
    holding: Mapping[str, object], instrument: InstrumentRefV0
) -> bool:
    ticker = holding.get("ticker")
    if not isinstance(ticker, str):
        return False
    holding_venue = ticker_venue_hint_v0(ticker)
    return holding_venue is not None and holding_venue != instrument.exchange


def _public_lookup_key(value: object) -> bytes:
    normalized = normalize_identity_key_v0(value)
    if normalized is None:
        return b""
    return normalized.encode("ascii")


__all__ = [
    "ApprovedSwingRefV0",
    "EntryIdentityApprovedV0",
    "EntryIdentityResultV0",
    "EntryIdentityReviewV0",
    "IdentityGateIssueV0",
    "SwingApprovalResultV0",
    "SwingApprovedV0",
    "SwingReviewV0",
    "approve_swing_snapshot_v0",
    "project_research_instruments_v0",
    "resolve_entry_identity_v0",
]
