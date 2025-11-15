from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

try:
    import yaml
except Exception:  # pragma: no cover - optional dependency
    yaml = None


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
        return HoldingsData(path=p, settings=HoldingSettings(), holdings=[])

    try:
        with p.open("r", encoding="utf-8") as f:
            raw = yaml.safe_load(f) or {}
    except Exception:
        return HoldingsData(path=p, settings=HoldingSettings(), holdings=[])

    settings_raw: dict[str, Any] = raw.get("settings", {}) or {}
    settings = HoldingSettings(
        default_currency=settings_raw.get("default_currency"),
        default_strategy=settings_raw.get("default_strategy"),
        default_tags=_ensure_list(settings_raw.get("default_tags")),
    )

    holdings_list: list[Holding] = []
    for item in raw.get("holdings", []) or []:
        if not isinstance(item, dict):
            continue
        ticker = str(item.get("ticker", "")).strip()
        if not ticker:
            continue

        quantity = item.get("quantity", 0)
        try:
            quantity = float(quantity)
        except (TypeError, ValueError):
            quantity = 0.0

        entry_price = item.get("entry_price", 0)
        try:
            entry_price = float(entry_price)
        except (TypeError, ValueError):
            entry_price = 0.0

        entry_currency = item.get("entry_currency") or settings.default_currency
        strategy = item.get("strategy") or settings.default_strategy
        tags = _ensure_list(item.get("tags", settings.default_tags))

        def _opt_float(value: Any) -> float | None:
            if value is None:
                return None
            try:
                return float(value)
            except (TypeError, ValueError):
                return None

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
            stop_override=_opt_float(item.get("stop_override")),
            target_override=_opt_float(item.get("target_override")),
        )

        holdings_list.append(holding)

    return HoldingsData(path=p, settings=settings, holdings=holdings_list)
