from __future__ import annotations

import math
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .tickers import (
    SUPPORTED_ENTRY_CURRENCIES,
    parse_ticker,
    validate_strict_holdings_ticker,
)

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


def _ensure_list(value: Any) -> list[str]:
    if isinstance(value, list):
        return [str(v) for v in value]
    if value is None:
        return []
    return [str(value)]


def load_holdings(path: str | None) -> HoldingsData:
    if not path:
        return HoldingsData(path=None, settings=HoldingSettings(), holdings=[])

    p = Path(path)
    if not p.exists():
        raise HoldingsLoadError(f"Holdings file '{p}' does not exist.")

    if yaml is None:
        raise HoldingsLoadError(
            f"Holdings file '{p}' exists but PyYAML is unavailable. "
            "Install dependency 'pyyaml' to parse holdings YAML."
        )

    try:
        with p.open("r", encoding="utf-8") as f:
            raw: Any = yaml.safe_load(f)
    except OSError as exc:
        raise HoldingsLoadError(f"Failed to read holdings file '{p}': {exc}") from exc
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

    settings_value = raw.get("settings")
    if settings_value is None:
        settings_raw: dict[str, Any] = {}
    elif not isinstance(settings_value, dict):
        raise HoldingsLoadError(
            "Holdings file "
            f"'{p}' field 'settings' must have a mapping (object), got "
            f"{type(settings_value).__name__}."
        )
    else:
        settings_raw = settings_value

    settings = HoldingSettings(
        default_currency=settings_raw.get("default_currency"),
        default_strategy=settings_raw.get("default_strategy"),
        default_tags=_ensure_list(settings_raw.get("default_tags")),
    )
    if settings.default_currency is not None:
        raw_default_currency = settings.default_currency
        if isinstance(raw_default_currency, bool):  # type: ignore[unreachable]
            raise HoldingsLoadError(
                "Invalid holdings value in "
                f"'{p}' (field='settings.default_currency'): "
                f"unsupported settings.default_currency {raw_default_currency!r}; "
                f"expected one of {sorted(SUPPORTED_ENTRY_CURRENCIES)}."
            )
        normalized_default_currency = str(raw_default_currency).strip().upper()
        if not normalized_default_currency:
            settings.default_currency = None
        elif normalized_default_currency not in SUPPORTED_ENTRY_CURRENCIES:
            raise HoldingsLoadError(
                "Invalid holdings value in "
                f"'{p}' (field='settings.default_currency'): "
                f"unsupported settings.default_currency {raw_default_currency!r}; "
                f"expected one of {sorted(SUPPORTED_ENTRY_CURRENCIES)}."
            )
        else:
            settings.default_currency = normalized_default_currency

    holdings_value = raw.get("holdings")
    if holdings_value is None:
        holdings_raw: list[Any] = []
    elif not isinstance(holdings_value, list):
        raise HoldingsLoadError(
            "Holdings file "
            f"'{p}' field 'holdings' must have a list (array), got "
            f"{type(holdings_value).__name__}."
        )
    else:
        holdings_raw = holdings_value

    def _parse_float_or_raise(
        *,
        value: Any,
        field_name: str,
        item_index: int,
        ticker: str,
        min_value: float | None = None,
    ) -> float:
        if isinstance(value, bool):
            raise HoldingsLoadError(
                "Invalid holdings value in "
                f"'{p}' (index {item_index}, ticker='{ticker}', field='{field_name}'): "
                f"expected a finite number, got {value!r}."
            )
        try:
            parsed = float(value)
        except (TypeError, ValueError) as exc:
            raise HoldingsLoadError(
                "Invalid holdings value in "
                f"'{p}' (index {item_index}, ticker='{ticker}', field='{field_name}'): "
                f"expected a number, got {value!r}."
            ) from exc
        if not math.isfinite(parsed):
            raise HoldingsLoadError(
                "Invalid holdings value in "
                f"'{p}' (index {item_index}, ticker='{ticker}', field='{field_name}'): "
                f"expected a finite number, got {value!r}."
            )
        if min_value is not None and parsed < min_value:
            raise HoldingsLoadError(
                "Invalid holdings value in "
                f"'{p}' (index {item_index}, ticker='{ticker}', field='{field_name}'): "
                f"expected a number >= {min_value:g}, got {value!r}."
            )
        return parsed

    def _required_field_or_raise(
        *,
        item: dict[str, Any],
        field_name: str,
        item_index: int,
        ticker: str,
    ) -> Any:
        if field_name not in item:
            raise HoldingsLoadError(
                "Missing required holdings field in "
                f"'{p}' (index {item_index}, ticker='{ticker}', field='{field_name}')."
            )
        return item[field_name]

    def _parse_ticker_or_raise(*, item: dict[str, Any], item_index: int) -> str:
        raw_ticker = _required_field_or_raise(
            item=item,
            field_name="ticker",
            item_index=item_index,
            ticker="",
        )
        if isinstance(raw_ticker, bool) or raw_ticker is None:
            raise HoldingsLoadError(
                "Invalid holdings value in "
                f"'{p}' (index {item_index}, ticker='', field='ticker'): "
                f"expected a non-empty ticker string, got {raw_ticker!r}."
            )
        if not isinstance(raw_ticker, str):
            hint = ""
            if isinstance(raw_ticker, int):
                hint = " quote numeric codes like '000660' to preserve leading zeros."
            raise HoldingsLoadError(
                "Invalid holdings value in "
                f"'{p}' (index {item_index}, ticker='', field='ticker'): "
                f"expected a ticker string, got {raw_ticker!r}.{hint}"
            )
        ticker = raw_ticker
        parsed = ticker.strip()
        if not parsed:
            raise HoldingsLoadError(
                "Missing required holdings field in "
                f"'{p}' (index {item_index}, ticker='', field='ticker')."
            )
        ticker_issue = validate_strict_holdings_ticker(parsed)
        if ticker_issue is not None:
            raise HoldingsLoadError(
                "Invalid holdings value in "
                f"'{p}' (index {item_index}, ticker='{parsed}', field='ticker'): "
                f"{ticker_issue}."
            )
        return parse_ticker(parsed).ticker

    parsed_rows: list[tuple[int, dict[str, Any], str, str]] = []
    for item_index, item in enumerate(holdings_raw):
        if not isinstance(item, dict):
            raise HoldingsLoadError(
                "Invalid holdings item in "
                f"'{p}' (index {item_index}): expected an object, got "
                f"{type(item).__name__}."
            )
        ticker = _parse_ticker_or_raise(item=item, item_index=item_index)
        market = parse_ticker(ticker).market
        parsed_rows.append((item_index, item, ticker, market))

    markets_in_holdings = {market for _, _, _, market in parsed_rows}
    has_kr_ticker = "KR" in markets_in_holdings
    has_us_ticker = "US" in markets_in_holdings
    mixed_market_holdings = has_kr_ticker and has_us_ticker

    if mixed_market_holdings and settings.default_currency is not None:
        raise HoldingsLoadError(
            "Invalid holdings value in "
            f"'{p}' (field='settings.default_currency'): "
            "Mixed KR/US holdings cannot use settings.default_currency; "
            "set entry_currency per row."
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
        raise HoldingsLoadError(
            "Invalid holdings value in "
            f"'{p}' (field='settings.default_currency'): "
            "US-only holdings require settings.default_currency to be USD or unset."
        )
    if has_kr_ticker and not has_us_ticker and settings.default_currency == "USD":
        raise HoldingsLoadError(
            "Invalid holdings value in "
            f"'{p}' (field='settings.default_currency'): "
            "KR-only holdings cannot set settings.default_currency=USD."
        )

    holdings_list: list[Holding] = []
    for item_index, item, ticker, market in parsed_rows:
        quantity = _parse_float_or_raise(
            value=_required_field_or_raise(
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
            value=_required_field_or_raise(
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

        raw_entry_currency = item.get("entry_currency")
        has_explicit_entry_currency = False
        entry_currency: str | None
        if raw_entry_currency is not None:
            if isinstance(raw_entry_currency, bool):
                raise HoldingsLoadError(
                    "Invalid holdings value in "
                    f"'{p}' (index {item_index}, ticker='{ticker}', field='entry_currency'): "
                    f"unsupported entry_currency {raw_entry_currency!r}; "
                    f"expected one of {sorted(SUPPORTED_ENTRY_CURRENCIES)}."
                )
            has_explicit_entry_currency = str(raw_entry_currency).strip() != ""
        if has_explicit_entry_currency:
            entry_currency = str(raw_entry_currency).strip().upper()
            if entry_currency not in SUPPORTED_ENTRY_CURRENCIES:
                raise HoldingsLoadError(
                    "Invalid holdings value in "
                    f"'{p}' (index {item_index}, ticker='{ticker}', field='entry_currency'): "
                    f"unsupported entry_currency {raw_entry_currency!r}; "
                    f"expected one of {sorted(SUPPORTED_ENTRY_CURRENCIES)}."
                )
        else:
            entry_currency = settings.default_currency

        if mixed_market_holdings and not has_explicit_entry_currency:
            raise HoldingsLoadError(
                "Invalid holdings value in "
                f"'{p}' (index {item_index}, ticker='{ticker}', field='entry_currency'): "
                "Mixed KR/US holdings require explicit entry_currency per row."
            )
        is_us_ticker = market == "US"
        if is_us_ticker and entry_currency != "USD":
            raise HoldingsLoadError(
                "Invalid holdings value in "
                f"'{p}' (index {item_index}, ticker='{ticker}', field='entry_currency'): "
                f"US ticker entry_currency must be USD, got {entry_currency!r}."
            )
        if entry_currency == "USD" and not is_us_ticker:
            raise HoldingsLoadError(
                "Invalid holdings value in "
                f"'{p}' (index {item_index}, ticker='{ticker}', field='entry_currency'): "
                "entry_currency USD requires US ticker suffix."
            )

        strategy = item.get("strategy") or settings.default_strategy
        tags = _ensure_list(item.get("tags", settings.default_tags))

        stop_override_raw = item.get("stop_override")
        stop_override = (
            _parse_float_or_raise(
                value=stop_override_raw,
                field_name="stop_override",
                item_index=item_index,
                ticker=ticker,
                min_value=0,
            )
            if stop_override_raw is not None
            else None
        )
        target_override_raw = item.get("target_override")
        target_override = (
            _parse_float_or_raise(
                value=target_override_raw,
                field_name="target_override",
                item_index=item_index,
                ticker=ticker,
                min_value=0,
            )
            if target_override_raw is not None
            else None
        )

        entry_date = item.get("entry_date")
        if entry_date is not None:
            if hasattr(entry_date, "isoformat"):
                entry_date = entry_date.isoformat()
            else:
                entry_date = str(entry_date)

        holding = Holding(
            ticker=ticker,
            quantity=quantity,
            entry_price=entry_price,
            entry_currency=entry_currency,
            entry_date=entry_date,
            strategy=strategy,
            notes=item.get("notes"),
            tags=tags,
            stop_override=stop_override,
            target_override=target_override,
        )

        holdings_list.append(holding)

    return HoldingsData(path=p, settings=settings, holdings=holdings_list)
