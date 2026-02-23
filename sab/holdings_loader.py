from __future__ import annotations

import math
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

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
        return HoldingsData(path=p, settings=HoldingSettings(), holdings=[])

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
        if isinstance(raw_ticker, int):
            ticker = str(raw_ticker)
        elif isinstance(raw_ticker, str):
            ticker = raw_ticker
        else:
            raise HoldingsLoadError(
                "Invalid holdings value in "
                f"'{p}' (index {item_index}, ticker='', field='ticker'): "
                "expected a ticker string (or integer code), got "
                f"{raw_ticker!r}."
            )
        parsed = ticker.strip()
        if not parsed:
            raise HoldingsLoadError(
                "Missing required holdings field in "
                f"'{p}' (index {item_index}, ticker='', field='ticker')."
            )
        return parsed

    holdings_list: list[Holding] = []
    for item_index, item in enumerate(holdings_raw):
        if not isinstance(item, dict):
            raise HoldingsLoadError(
                "Invalid holdings item in "
                f"'{p}' (index {item_index}): expected an object, got "
                f"{type(item).__name__}."
            )
        ticker = _parse_ticker_or_raise(item=item, item_index=item_index)

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
        )

        entry_currency = item.get("entry_currency") or settings.default_currency
        strategy = item.get("strategy") or settings.default_strategy
        tags = _ensure_list(item.get("tags", settings.default_tags))

        stop_override_raw = item.get("stop_override")
        stop_override = (
            _parse_float_or_raise(
                value=stop_override_raw,
                field_name="stop_override",
                item_index=item_index,
                ticker=ticker,
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
