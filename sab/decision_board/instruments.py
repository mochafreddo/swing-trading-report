"""Pure public instrument identity values for Decision Board V0."""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from typing import Any
from unicodedata import category

_RECORD_FIELDS = {
    "market",
    "canonical_ticker",
    "exchange",
    "company_name",
    "aliases",
}
_REQUIRED_RECORD_FIELDS = _RECORD_FIELDS - {"aliases"}
_ASCII_WHITESPACE = " \t\n\r\f\v"


class InstrumentRegistryError(ValueError):
    """An explicit versioned registry could not be constructed safely."""

    def __init__(self, code: str, message: str) -> None:
        self.code = code
        super().__init__(f"{code}: {message}")


@dataclass(frozen=True, slots=True)
class InstrumentRefV0:
    """Immutable research-safe identity matching the shared V0 contract."""

    market: str
    canonical_ticker: str
    exchange: str
    company_name: str
    identity_source: str
    identity_version: str

    def __post_init__(self) -> None:
        market = _required_text(self.market, field="market").upper()
        if market != "US":
            raise InstrumentRegistryError(
                "INVALID_MARKET", "V0 instrument market must be US"
            )
        canonical_ticker = _required_text(
            self.canonical_ticker, field="canonical_ticker"
        ).upper()
        exchange = _required_text(self.exchange, field="exchange").upper()
        _validate_registry_identity_consistency(canonical_ticker, exchange)
        object.__setattr__(self, "market", market)
        object.__setattr__(self, "canonical_ticker", canonical_ticker)
        object.__setattr__(self, "exchange", exchange)
        object.__setattr__(
            self,
            "company_name",
            _required_text(self.company_name, field="company_name"),
        )
        object.__setattr__(
            self,
            "identity_source",
            _required_text(self.identity_source, field="identity_source"),
        )
        object.__setattr__(
            self,
            "identity_version",
            _required_text(self.identity_version, field="identity_version"),
        )

    def to_public_dict(self) -> dict[str, str]:
        """Return a fresh JSON-ready representation with public fields only."""

        return {
            "market": self.market,
            "canonical_ticker": self.canonical_ticker,
            "exchange": self.exchange,
            "company_name": self.company_name,
            "identity_source": self.identity_source,
            "identity_version": self.identity_version,
        }


@dataclass(frozen=True, slots=True)
class _RegistryBinding:
    market: str
    canonical_ticker: str
    exchange: str
    company_name: str


@dataclass(frozen=True, slots=True, init=False)
class VersionedInstrumentRegistryV0:
    """An immutable, caller-supplied authoritative US identity registry."""

    identity_source: str
    identity_version: str
    _bindings: tuple[_RegistryBinding, ...]
    _lookup: tuple[tuple[str, int], ...]

    def __init__(
        self,
        *,
        identity_source: object,
        identity_version: object,
        records: Iterable[Mapping[str, object]],
    ) -> None:
        source = _required_text(identity_source, field="identity_source")
        version = _required_text(identity_version, field="identity_version")
        bindings: list[_RegistryBinding] = []
        aliases_by_index: list[tuple[str, ...]] = []

        try:
            supplied_records = tuple(records)
        except TypeError as exc:
            raise InstrumentRegistryError(
                "INVALID_RECORD", "records must be an iterable of public objects"
            ) from exc

        canonical_owners: dict[str, int] = {}
        for index, raw in enumerate(supplied_records):
            binding, aliases = _parse_record(raw)
            if binding.canonical_ticker in canonical_owners:
                raise InstrumentRegistryError(
                    "DUPLICATE_CANONICAL",
                    "canonical ticker entries must be unique",
                )
            canonical_owners[binding.canonical_ticker] = index
            bindings.append(binding)
            aliases_by_index.append(aliases)

        lookup_owners = dict(canonical_owners)
        for index, aliases in enumerate(aliases_by_index):
            for alias in aliases:
                existing = lookup_owners.get(alias)
                if existing is not None:
                    code = "DUPLICATE_ALIAS" if existing == index else "AMBIGUOUS_ALIAS"
                    raise InstrumentRegistryError(
                        code,
                        "aliases must map to exactly one canonical instrument",
                    )
                lookup_owners[alias] = index

        object.__setattr__(self, "identity_source", source)
        object.__setattr__(self, "identity_version", version)
        object.__setattr__(self, "_bindings", tuple(bindings))
        object.__setattr__(
            self,
            "_lookup",
            tuple(
                sorted(lookup_owners.items(), key=lambda item: item[0].encode("utf-8"))
            ),
        )

    def resolve(self, lookup_value: object) -> InstrumentRefV0 | None:
        """Resolve only an explicit canonical or alias key; never infer a suffix."""

        lookup_key = _lookup_text(lookup_value)
        if lookup_key is None:
            return None
        binding_index = next(
            (index for key, index in self._lookup if key == lookup_key), None
        )
        if binding_index is None:
            return None
        binding = self._bindings[binding_index]
        return InstrumentRefV0(
            market=binding.market,
            canonical_ticker=binding.canonical_ticker,
            exchange=binding.exchange,
            company_name=binding.company_name,
            identity_source=self.identity_source,
            identity_version=self.identity_version,
        )


def _parse_record(raw: object) -> tuple[_RegistryBinding, tuple[str, ...]]:
    if not isinstance(raw, Mapping):
        raise InstrumentRegistryError(
            "INVALID_RECORD", "each registry record must be a public object"
        )
    fields = set(raw)
    if not all(isinstance(field, str) for field in fields):
        raise InstrumentRegistryError(
            "INVALID_RECORD", "registry record fields must be strings"
        )
    if fields - _RECORD_FIELDS or _REQUIRED_RECORD_FIELDS - fields:
        raise InstrumentRegistryError(
            "INVALID_RECORD", "registry record has an invalid public field set"
        )

    market = _required_text(raw["market"], field="market").upper()
    if market != "US":
        raise InstrumentRegistryError("INVALID_MARKET", "V0 registry market must be US")
    canonical_ticker = _required_text(
        raw["canonical_ticker"], field="canonical_ticker"
    ).upper()
    exchange = _required_text(raw["exchange"], field="exchange").upper()
    company_name = _required_text(raw["company_name"], field="company_name")
    _validate_registry_identity_consistency(canonical_ticker, exchange)

    raw_aliases: Any = raw.get("aliases", ())
    if isinstance(raw_aliases, (str, bytes)) or not isinstance(raw_aliases, Iterable):
        raise InstrumentRegistryError("INVALID_RECORD", "aliases must be an array")
    aliases: list[str] = []
    for alias in raw_aliases:
        normalized = _required_text(alias, field="alias").upper()
        if normalized in aliases:
            raise InstrumentRegistryError(
                "DUPLICATE_ALIAS", "aliases must not contain duplicate keys"
            )
        aliases.append(normalized)
    return (
        _RegistryBinding(
            market=market,
            canonical_ticker=canonical_ticker,
            exchange=exchange,
            company_name=company_name,
        ),
        tuple(aliases),
    )


def _required_text(value: object, *, field: str) -> str:
    if not isinstance(value, str):
        raise InstrumentRegistryError(
            "INVALID_IDENTITY", f"{field} must be a nonblank string"
        )
    if _has_control_character(value):
        raise InstrumentRegistryError(
            "INVALID_IDENTITY", f"{field} must be a nonblank public string"
        )
    normalized = value.strip()
    if not normalized:
        raise InstrumentRegistryError(
            "INVALID_IDENTITY", f"{field} must be a nonblank public string"
        )
    return normalized


def _lookup_text(value: object) -> str | None:
    if not isinstance(value, str) or _has_control_character(value):
        return None
    normalized = value.strip(_ASCII_WHITESPACE)
    if not normalized:
        return None
    return normalized.upper()


def _has_control_character(value: str) -> bool:
    return any(category(character) == "Cc" for character in value)


def _validate_registry_identity_consistency(
    canonical_ticker: str, exchange: str
) -> None:
    ticker_family = _ticker_exchange_family(canonical_ticker)
    exchange_family = _exchange_family(exchange)
    if (
        ticker_family is not None
        and exchange_family is not None
        and ticker_family != exchange_family
    ):
        raise InstrumentRegistryError(
            "IDENTITY_CONFLICT",
            "canonical ticker and exchange identify different venues",
        )


def _ticker_exchange_family(ticker: str) -> str | None:
    if "." not in ticker:
        return None
    return _exchange_family(ticker.rsplit(".", 1)[1])


def _exchange_family(exchange: str) -> str | None:
    normalized = exchange.strip().upper()
    families = {
        "NAS": "NASDAQ",
        "NASDAQ": "NASDAQ",
        "XNAS": "NASDAQ",
        "NYS": "NYSE",
        "NYSE": "NYSE",
        "XNYS": "NYSE",
        "AMS": "AMEX",
        "AMEX": "AMEX",
        "XASE": "AMEX",
    }
    return families.get(normalized)


__all__ = [
    "InstrumentRefV0",
    "InstrumentRegistryError",
    "VersionedInstrumentRegistryV0",
]
