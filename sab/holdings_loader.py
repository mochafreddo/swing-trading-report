from __future__ import annotations

import math
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .entry_pattern_contract import HOLDINGS_ENTRY_PATTERNS
from .tickers import (
    SUPPORTED_ENTRY_CURRENCIES,
    parse_ticker,
    validate_strict_holdings_ticker,
)
from .utils.yaml import unique_key_safe_loader

try:
    import yaml  # type: ignore[import-untyped]
except Exception:  # pragma: no cover - optional dependency
    yaml = None


class HoldingsLoadError(RuntimeError):
    """Raised when holdings file exists but cannot be loaded safely."""


@dataclass
class Holding:
    ticker: str
    quantity: float = 0.0
    entry_price: float = 0.0
    entry_currency: str | None = None
    entry_date: str | None = None
    strategy: str | None = None
    notes: str | None = None
    tags: list[str] = field(default_factory=list)
    stop_override: float | None = None
    target_override: float | None = None
    entry_pattern: str | None = None


@dataclass
class HoldingSettings:
    default_currency: str | None = None
    default_strategy: str | None = None
    default_tags: list[str] = field(default_factory=list)


@dataclass
class HoldingsData:
    path: Path | None
    settings: HoldingSettings
    holdings: list[Holding]


type _ParsedHoldingRow = tuple[int, dict[str, Any], str, str]


def _ensure_list(value: Any) -> list[str]:
    if isinstance(value, list):
        return [str(v) for v in value]
    if value is None:
        return []
    return [str(value)]


def _invalid_holdings_value(
    p: Path,
    detail: str,
    *,
    field_name: str,
    item_index: int | None = None,
    ticker: str | None = None,
) -> HoldingsLoadError:
    if item_index is None:
        location = f"field='{field_name}'"
    else:
        location = f"index {item_index}, ticker='{ticker or ''}', field='{field_name}'"
    return HoldingsLoadError(f"Invalid holdings value in '{p}' ({location}): {detail}")


def _missing_holdings_field(
    p: Path,
    *,
    item_index: int,
    ticker: str,
    field_name: str,
) -> HoldingsLoadError:
    return HoldingsLoadError(
        f"Missing required holdings field in "
        f"'{p}' (index {item_index}, ticker='{ticker}', field='{field_name}')."
    )


def _load_yaml_root(p: Path) -> dict[str, Any]:
    if yaml is None:
        raise HoldingsLoadError(
            f"Holdings file '{p}' exists but PyYAML is unavailable. "
            "Install dependency 'pyyaml' to parse holdings YAML."
        )

    try:
        with p.open("r", encoding="utf-8") as f:
            raw: Any = yaml.load(
                f, Loader=unique_key_safe_loader(yaml, HoldingsLoadError)
            )
    except OSError as exc:
        raise HoldingsLoadError(f"Failed to read holdings file '{p}': {exc}") from exc
    except HoldingsLoadError:
        raise
    except Exception as exc:
        raise HoldingsLoadError(f"Failed to parse holdings file '{p}': {exc}") from exc

    if raw is None:
        raw = {}
    if not isinstance(raw, dict):
        raise HoldingsLoadError(
            "Holdings file "
            f"'{p}' must have a mapping (object) at YAML root, got "
            f"{type(raw).__name__}."
        )
    return raw


def _settings_mapping(p: Path, raw: dict[str, Any]) -> dict[str, Any]:
    settings_value = raw.get("settings")
    if settings_value is None:
        return {}
    if not isinstance(settings_value, dict):
        raise HoldingsLoadError(
            "Holdings file "
            f"'{p}' field 'settings' must have a mapping (object), got "
            f"{type(settings_value).__name__}."
        )
    return settings_value


def _normalize_default_currency(p: Path, value: Any) -> str | None:
    if value is None:
        return None
    if isinstance(value, bool):
        raise _invalid_holdings_value(
            p,
            f"unsupported settings.default_currency {value!r}; "
            f"expected one of {sorted(SUPPORTED_ENTRY_CURRENCIES)}.",
            field_name="settings.default_currency",
        )
    normalized = str(value).strip().upper()
    if not normalized:
        return None
    if normalized not in SUPPORTED_ENTRY_CURRENCIES:
        raise _invalid_holdings_value(
            p,
            f"unsupported settings.default_currency {value!r}; "
            f"expected one of {sorted(SUPPORTED_ENTRY_CURRENCIES)}.",
            field_name="settings.default_currency",
        )
    return normalized


def _parse_settings(p: Path, raw: dict[str, Any]) -> HoldingSettings:
    settings_raw = _settings_mapping(p, raw)
    return HoldingSettings(
        default_currency=_normalize_default_currency(
            p, settings_raw.get("default_currency")
        ),
        default_strategy=settings_raw.get("default_strategy"),
        default_tags=_ensure_list(settings_raw.get("default_tags")),
    )


def _holdings_list(p: Path, raw: dict[str, Any]) -> list[Any]:
    holdings_value = raw.get("holdings")
    if holdings_value is None:
        return []
    if not isinstance(holdings_value, list):
        raise HoldingsLoadError(
            "Holdings file "
            f"'{p}' field 'holdings' must have a list (array), got "
            f"{type(holdings_value).__name__}."
        )
    return holdings_value


def _parse_float_or_raise(
    p: Path,
    *,
    value: Any,
    field_name: str,
    item_index: int,
    ticker: str,
    min_value: float | None = None,
) -> float:
    if isinstance(value, bool):
        raise _invalid_holdings_value(
            p,
            f"expected a finite number, got {value!r}.",
            field_name=field_name,
            item_index=item_index,
            ticker=ticker,
        )
    try:
        parsed = float(value)
    except (TypeError, ValueError) as exc:
        raise _invalid_holdings_value(
            p,
            f"expected a number, got {value!r}.",
            field_name=field_name,
            item_index=item_index,
            ticker=ticker,
        ) from exc
    if not math.isfinite(parsed):
        raise _invalid_holdings_value(
            p,
            f"expected a finite number, got {value!r}.",
            field_name=field_name,
            item_index=item_index,
            ticker=ticker,
        )
    if min_value is not None and parsed < min_value:
        raise _invalid_holdings_value(
            p,
            f"expected a number >= {min_value:g}, got {value!r}.",
            field_name=field_name,
            item_index=item_index,
            ticker=ticker,
        )
    return parsed


def _required_field_or_raise(
    p: Path,
    *,
    item: dict[str, Any],
    field_name: str,
    item_index: int,
    ticker: str,
) -> Any:
    if field_name not in item:
        raise _missing_holdings_field(
            p,
            item_index=item_index,
            ticker=ticker,
            field_name=field_name,
        )
    return item[field_name]


def _parse_ticker_or_raise(p: Path, *, item: dict[str, Any], item_index: int) -> str:
    raw_ticker = _required_field_or_raise(
        p,
        item=item,
        field_name="ticker",
        item_index=item_index,
        ticker="",
    )
    if isinstance(raw_ticker, bool) or raw_ticker is None:
        raise _invalid_holdings_value(
            p,
            f"expected a non-empty ticker string, got {raw_ticker!r}.",
            field_name="ticker",
            item_index=item_index,
            ticker="",
        )
    if not isinstance(raw_ticker, str):
        hint = ""
        if isinstance(raw_ticker, int):
            hint = " quote numeric codes like '000660' to preserve leading zeros."
        raise _invalid_holdings_value(
            p,
            f"expected a ticker string, got {raw_ticker!r}.{hint}",
            field_name="ticker",
            item_index=item_index,
            ticker="",
        )
    parsed = raw_ticker.strip()
    if not parsed:
        raise _missing_holdings_field(
            p,
            item_index=item_index,
            ticker="",
            field_name="ticker",
        )
    ticker_issue = validate_strict_holdings_ticker(parsed)
    if ticker_issue is not None:
        raise _invalid_holdings_value(
            p,
            f"{ticker_issue}.",
            field_name="ticker",
            item_index=item_index,
            ticker=parsed,
        )
    return parse_ticker(parsed).ticker


def _parse_holding_row_headers(
    p: Path, holdings_raw: list[Any]
) -> list[_ParsedHoldingRow]:
    parsed_rows: list[_ParsedHoldingRow] = []
    for item_index, item in enumerate(holdings_raw):
        if not isinstance(item, dict):
            raise HoldingsLoadError(
                "Invalid holdings item in "
                f"'{p}' (index {item_index}): expected an object, got "
                f"{type(item).__name__}."
            )
        ticker = _parse_ticker_or_raise(p, item=item, item_index=item_index)
        market = parse_ticker(ticker).market
        parsed_rows.append((item_index, item, ticker, market))
    return parsed_rows


def _validate_default_currency_for_markets(
    p: Path, *, settings: HoldingSettings, parsed_rows: list[_ParsedHoldingRow]
) -> bool:
    markets_in_holdings = {market for _, _, _, market in parsed_rows}
    has_kr_ticker = "KR" in markets_in_holdings
    has_us_ticker = "US" in markets_in_holdings
    mixed_market_holdings = has_kr_ticker and has_us_ticker

    if mixed_market_holdings and settings.default_currency is not None:
        raise _invalid_holdings_value(
            p,
            "Mixed KR/US holdings cannot use settings.default_currency; "
            "set entry_currency per row.",
            field_name="settings.default_currency",
        )
    if (
        has_us_ticker
        and not has_kr_ticker
        and settings.default_currency
        not in (
            None,
            "USD",
        )
    ):
        raise _invalid_holdings_value(
            p,
            "US-only holdings require settings.default_currency to be USD or unset.",
            field_name="settings.default_currency",
        )
    if has_kr_ticker and not has_us_ticker and settings.default_currency == "USD":
        raise _invalid_holdings_value(
            p,
            "KR-only holdings cannot set settings.default_currency=USD.",
            field_name="settings.default_currency",
        )
    return mixed_market_holdings


def _parse_entry_currency(
    p: Path,
    *,
    raw_entry_currency: Any,
    settings: HoldingSettings,
    item_index: int,
    ticker: str,
) -> tuple[str | None, bool]:
    has_explicit_entry_currency = False
    if raw_entry_currency is not None:
        if isinstance(raw_entry_currency, bool):
            raise _invalid_holdings_value(
                p,
                f"unsupported entry_currency {raw_entry_currency!r}; "
                f"expected one of {sorted(SUPPORTED_ENTRY_CURRENCIES)}.",
                field_name="entry_currency",
                item_index=item_index,
                ticker=ticker,
            )
        has_explicit_entry_currency = str(raw_entry_currency).strip() != ""
    if not has_explicit_entry_currency:
        return settings.default_currency, False

    entry_currency = str(raw_entry_currency).strip().upper()
    if entry_currency not in SUPPORTED_ENTRY_CURRENCIES:
        raise _invalid_holdings_value(
            p,
            f"unsupported entry_currency {raw_entry_currency!r}; "
            f"expected one of {sorted(SUPPORTED_ENTRY_CURRENCIES)}.",
            field_name="entry_currency",
            item_index=item_index,
            ticker=ticker,
        )
    return entry_currency, True


def _validate_entry_currency_for_market(
    p: Path,
    *,
    entry_currency: str | None,
    has_explicit_entry_currency: bool,
    mixed_market_holdings: bool,
    market: str,
    item_index: int,
    ticker: str,
) -> None:
    if mixed_market_holdings and not has_explicit_entry_currency:
        raise _invalid_holdings_value(
            p,
            "Mixed KR/US holdings require explicit entry_currency per row.",
            field_name="entry_currency",
            item_index=item_index,
            ticker=ticker,
        )
    is_us_ticker = market == "US"
    if is_us_ticker and entry_currency != "USD":
        raise _invalid_holdings_value(
            p,
            f"US ticker entry_currency must be USD, got {entry_currency!r}.",
            field_name="entry_currency",
            item_index=item_index,
            ticker=ticker,
        )
    if entry_currency == "USD" and not is_us_ticker:
        raise _invalid_holdings_value(
            p,
            "entry_currency USD requires US ticker suffix.",
            field_name="entry_currency",
            item_index=item_index,
            ticker=ticker,
        )


def _parse_optional_non_negative_float(
    p: Path,
    *,
    item: dict[str, Any],
    field_name: str,
    item_index: int,
    ticker: str,
) -> float | None:
    raw_value = item.get(field_name)
    if raw_value is None:
        return None
    return _parse_float_or_raise(
        p,
        value=raw_value,
        field_name=field_name,
        item_index=item_index,
        ticker=ticker,
        min_value=0,
    )


def _parse_entry_date(value: Any) -> str | None:
    if value is None:
        return None
    if hasattr(value, "isoformat"):
        return str(value.isoformat())
    return str(value)


def _parse_optional_text_field(
    p: Path,
    *,
    value: Any,
    field_name: str,
    item_index: int,
    ticker: str,
    max_length: int | None = None,
    allowed_values: frozenset[str] | None = None,
) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str):
        raise _invalid_holdings_value(
            p,
            f"expected a string, got {type(value).__name__}.",
            field_name=field_name,
            item_index=item_index,
            ticker=ticker,
        )
    text = value.strip()
    if max_length is not None and len(text) > max_length:
        raise _invalid_holdings_value(
            p,
            f"expected a string <= {max_length} characters, got {len(text)}.",
            field_name=field_name,
            item_index=item_index,
            ticker=ticker,
        )
    if allowed_values is not None and text and text not in allowed_values:
        allowed = ", ".join(sorted(allowed_values))
        raise _invalid_holdings_value(
            p,
            f"expected one of {allowed}.",
            field_name=field_name,
            item_index=item_index,
            ticker=ticker,
        )
    return text or None


def _parse_holding(
    p: Path,
    *,
    item_index: int,
    item: dict[str, Any],
    ticker: str,
    market: str,
    settings: HoldingSettings,
    mixed_market_holdings: bool,
) -> Holding:
    quantity = _parse_float_or_raise(
        p,
        value=_required_field_or_raise(
            p,
            item=item,
            field_name="quantity",
            item_index=item_index,
            ticker=ticker,
        ),
        field_name="quantity",
        item_index=item_index,
        ticker=ticker,
        min_value=0,
    )
    entry_price = _parse_float_or_raise(
        p,
        value=_required_field_or_raise(
            p,
            item=item,
            field_name="entry_price",
            item_index=item_index,
            ticker=ticker,
        ),
        field_name="entry_price",
        item_index=item_index,
        ticker=ticker,
        min_value=0,
    )
    if quantity > 0 and entry_price <= 0:
        raise _invalid_holdings_value(
            p,
            "active holdings (quantity > 0) require entry_price > 0.",
            field_name="entry_price",
            item_index=item_index,
            ticker=ticker,
        )

    entry_currency, has_explicit_entry_currency = _parse_entry_currency(
        p,
        raw_entry_currency=item.get("entry_currency"),
        settings=settings,
        item_index=item_index,
        ticker=ticker,
    )
    _validate_entry_currency_for_market(
        p,
        entry_currency=entry_currency,
        has_explicit_entry_currency=has_explicit_entry_currency,
        mixed_market_holdings=mixed_market_holdings,
        market=market,
        item_index=item_index,
        ticker=ticker,
    )
    entry_pattern = _parse_optional_text_field(
        p,
        value=item.get("entry_pattern"),
        field_name="entry_pattern",
        item_index=item_index,
        ticker=ticker,
        max_length=120,
        allowed_values=HOLDINGS_ENTRY_PATTERNS,
    )
    if quantity == 0 and entry_pattern is not None:
        raise _invalid_holdings_value(
            p,
            "inactive holdings entry_pattern must be null.",
            field_name="entry_pattern",
            item_index=item_index,
            ticker=ticker,
        )

    return Holding(
        ticker=ticker,
        quantity=quantity,
        entry_price=entry_price,
        entry_currency=entry_currency,
        entry_date=_parse_entry_date(item.get("entry_date")),
        strategy=item.get("strategy") or settings.default_strategy,
        notes=item.get("notes"),
        tags=_ensure_list(item.get("tags", settings.default_tags)),
        stop_override=_parse_optional_non_negative_float(
            p,
            item=item,
            field_name="stop_override",
            item_index=item_index,
            ticker=ticker,
        ),
        target_override=_parse_optional_non_negative_float(
            p,
            item=item,
            field_name="target_override",
            item_index=item_index,
            ticker=ticker,
        ),
        entry_pattern=entry_pattern,
    )


def _parse_holdings(
    p: Path,
    *,
    settings: HoldingSettings,
    parsed_rows: list[_ParsedHoldingRow],
    mixed_market_holdings: bool,
) -> list[Holding]:
    return [
        _parse_holding(
            p,
            item_index=item_index,
            item=item,
            ticker=ticker,
            market=market,
            settings=settings,
            mixed_market_holdings=mixed_market_holdings,
        )
        for item_index, item, ticker, market in parsed_rows
    ]


def load_holdings(path: str | None) -> HoldingsData:
    if not path:
        return HoldingsData(path=None, settings=HoldingSettings(), holdings=[])

    p = Path(path)
    if not p.exists():
        raise HoldingsLoadError(f"Holdings file '{p}' does not exist.")

    raw = _load_yaml_root(p)
    settings = _parse_settings(p, raw)
    parsed_rows = _parse_holding_row_headers(p, _holdings_list(p, raw))
    mixed_market_holdings = _validate_default_currency_for_markets(
        p, settings=settings, parsed_rows=parsed_rows
    )
    holdings_list = _parse_holdings(
        p,
        settings=settings,
        parsed_rows=parsed_rows,
        mixed_market_holdings=mixed_market_holdings,
    )

    return HoldingsData(path=p, settings=settings, holdings=holdings_list)
