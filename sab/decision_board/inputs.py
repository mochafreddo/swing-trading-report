"""Fail-closed public identity gates for Decision Board V0 inputs."""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from typing import Literal
from unicodedata import category

from sab.scheduler.holdings import BrokerSnapshotV0

from .instruments import InstrumentRefV0, VersionedInstrumentRegistryV0

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


@dataclass(frozen=True, slots=True)
class SwingApprovalResultV0:
    status: Literal["APPROVED", "REVIEW"]
    approved_ref: ApprovedSwingRefV0 | None
    issues: tuple[IdentityGateIssueV0, ...]

    def __post_init__(self) -> None:
        approved = self.status == "APPROVED"
        if approved != (self.approved_ref is not None) or approved == bool(self.issues):
            raise ValueError("invalid SwingApprovalResultV0 discriminator")


@dataclass(frozen=True, slots=True)
class EntryIdentityResultV0:
    status: Literal["APPROVED", "REVIEW"]
    instrument: InstrumentRefV0 | None
    issues: tuple[IdentityGateIssueV0, ...]

    def __post_init__(self) -> None:
        approved = self.status == "APPROVED"
        if approved != (self.instrument is not None) or approved == bool(self.issues):
            raise ValueError("invalid EntryIdentityResultV0 discriminator")


def approve_swing_snapshot_v0(
    snapshot: BrokerSnapshotV0,
    registry: VersionedInstrumentRegistryV0,
) -> tuple[SwingApprovalResultV0, ...]:
    """Approve exact active SWING rows from an already validated broker DTO."""

    if not isinstance(snapshot, BrokerSnapshotV0):
        raise TypeError("snapshot must be a validated BrokerSnapshotV0")
    ordered_holdings = sorted(
        snapshot.holdings,
        key=lambda row: _public_lookup_key(row.get("ticker")),
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
    if "ticker" not in candidate or not _valid_public_text(candidate["ticker"]):
        return _entry_review(
            "REVIEW_IDENTITY_INPUT_INVALID",
            "ENTRY identity input requires one public ticker lookup key.",
        )
    for field in set(candidate) - {"ticker"}:
        if not _valid_public_text(candidate[field]):
            return _entry_review(
                "REVIEW_IDENTITY_INPUT_INVALID",
                "ENTRY identity hints must be nonblank public strings.",
            )

    instrument = registry.resolve(candidate["ticker"])
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
    return EntryIdentityResultV0(status="APPROVED", instrument=instrument, issues=())


def project_research_instruments_v0(
    results: Iterable[SwingApprovalResultV0 | EntryIdentityResultV0],
) -> tuple[dict[str, str], ...]:
    """Project approved identities into a deterministic public-only payload."""

    instruments: dict[tuple[str, ...], InstrumentRefV0] = {}
    for result in results:
        instrument: InstrumentRefV0 | None
        if isinstance(result, SwingApprovalResultV0):
            instrument = (
                result.approved_ref.instrument
                if result.approved_ref is not None
                else None
            )
        elif isinstance(result, EntryIdentityResultV0):
            instrument = result.instrument
        else:
            raise TypeError("research projection requires typed identity gate results")
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
        instruments[key].to_public_dict()
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
    instrument = registry.resolve(holding.get("ticker"))
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
        return SwingApprovalResultV0(
            status="REVIEW", approved_ref=None, issues=tuple(issues)
        )
    assert instrument is not None
    return SwingApprovalResultV0(
        status="APPROVED",
        approved_ref=ApprovedSwingRefV0(instrument=instrument),
        issues=(),
    )


def _is_exact_swing(value: object) -> bool:
    return isinstance(value, str) and value.strip(_ASCII_WHITESPACE).upper() == "SWING"


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
    return EntryIdentityResultV0(
        status="REVIEW",
        instrument=None,
        issues=(IdentityGateIssueV0(code=code, message=message),),
    )


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
        normalized = candidate_value.strip()
        if field in {"market", "canonical_ticker", "exchange"}:
            normalized = normalized.upper()
        if normalized != expected_value:
            return True

    ticker = candidate["ticker"]
    assert isinstance(ticker, str)
    candidate_family = _ticker_exchange_family(ticker)
    canonical_family = _ticker_exchange_family(instrument.canonical_ticker)
    return (
        candidate_family is not None
        and canonical_family is not None
        and candidate_family != canonical_family
    )


def _ticker_exchange_family(ticker: str) -> str | None:
    if "." not in ticker:
        return None
    suffix = ticker.strip().upper().rsplit(".", 1)[1]
    return {
        "NAS": "NASDAQ",
        "NASDAQ": "NASDAQ",
        "NYS": "NYSE",
        "NYSE": "NYSE",
        "AMS": "AMEX",
        "AMEX": "AMEX",
    }.get(suffix)


def _holding_identity_conflicts(
    holding: Mapping[str, object], instrument: InstrumentRefV0
) -> bool:
    ticker = holding.get("ticker")
    if not isinstance(ticker, str):
        return False
    holding_family = _ticker_exchange_family(ticker)
    canonical_family = _ticker_exchange_family(instrument.canonical_ticker)
    return (
        holding_family is not None
        and canonical_family is not None
        and holding_family != canonical_family
    )


def _valid_public_text(value: object) -> bool:
    return (
        isinstance(value, str)
        and bool(value.strip())
        and not any(category(character) == "Cc" for character in value)
    )


def _public_lookup_key(value: object) -> bytes:
    if not isinstance(value, str):
        return b""
    return value.strip(_ASCII_WHITESPACE).upper().encode("utf-8")


__all__ = [
    "ApprovedSwingRefV0",
    "EntryIdentityResultV0",
    "IdentityGateIssueV0",
    "SwingApprovalResultV0",
    "approve_swing_snapshot_v0",
    "project_research_instruments_v0",
    "resolve_entry_identity_v0",
]
