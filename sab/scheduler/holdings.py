from __future__ import annotations

import json
import os
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.parse import urlencode

import requests  # type: ignore[import-untyped]
import yaml  # type: ignore[import-untyped]


class SupabaseHoldingsExportError(RuntimeError):
    """Raised when scheduled holdings export cannot produce a safe snapshot."""


@dataclass(frozen=True)
class SupabaseHoldingsExportConfig:
    url: str
    service_role_key: str
    timeout_seconds: float = 10.0

    @classmethod
    def from_env(cls) -> SupabaseHoldingsExportConfig:
        url = str(os.getenv("SUPABASE_URL") or "").strip().rstrip("/")
        key = str(
            os.getenv("SUPABASE_SECRET_KEY")
            or os.getenv("SUPABASE_SERVICE_ROLE_KEY")
            or ""
        ).strip()
        if not url or not key:
            raise SupabaseHoldingsExportError(
                "SUPABASE_URL and SUPABASE_SECRET_KEY/SUPABASE_SERVICE_ROLE_KEY "
                "must be set for scheduled holdings export"
            )
        if key.startswith("sb_publishable_"):
            raise SupabaseHoldingsExportError(
                "publishable Supabase keys are not allowed for holdings export"
            )
        return cls(url=url, service_role_key=key)


_HOLDINGS_FIELDS = (
    "ticker",
    "quantity",
    "entry_price",
    "entry_currency",
    "entry_date",
    "strategy",
    "notes",
    "tags",
    "stop_override",
    "target_override",
)
_OPTIONAL_FIELDS = tuple(field for field in _HOLDINGS_FIELDS if field != "ticker")


def _headers(config: SupabaseHoldingsExportConfig) -> dict[str, str]:
    return {
        "apikey": config.service_role_key,
        "authorization": f"Bearer {config.service_role_key}",
        "accept": "application/json",
    }


def _active_quantity(value: object) -> bool:
    if isinstance(value, bool) or value is None:
        return False
    if not isinstance(value, (int, float, str)):
        return False
    try:
        return float(value) > 0
    except TypeError, ValueError:
        return False


def _normalize_rows(payload: object) -> list[dict[str, object]]:
    if not isinstance(payload, list):
        raise SupabaseHoldingsExportError("Supabase holdings response must be a list")
    rows: list[dict[str, object]] = []
    for raw in payload:
        if not isinstance(raw, dict):
            continue
        ticker = str(raw.get("ticker") or "").strip()
        if not ticker or not _active_quantity(raw.get("quantity")):
            continue
        item: dict[str, object] = {"ticker": ticker}
        for field_name in _OPTIONAL_FIELDS:
            value = raw.get(field_name)
            if value is not None:
                item[field_name] = value
        rows.append(item)
    return rows


def export_active_holdings_snapshot(
    *,
    output_path: Path,
    config: SupabaseHoldingsExportConfig,
    session: Any | None = None,
) -> int:
    query = urlencode(
        {
            "select": ",".join(_HOLDINGS_FIELDS),
            "quantity": "gt.0",
            "order": "ticker.asc",
        }
    )
    active_session = session or requests.Session()
    response = active_session.get(
        f"{config.url}/rest/v1/holdings?{query}",
        headers=_headers(config),
        timeout=config.timeout_seconds,
    )
    if response.status_code != 200:
        text = str(getattr(response, "text", "") or "").strip()
        raise SupabaseHoldingsExportError(
            f"failed to fetch active holdings: {text or response.status_code}"
        )
    try:
        payload = response.json()
    except json.JSONDecodeError as exc:
        raise SupabaseHoldingsExportError("failed to parse holdings JSON") from exc
    holdings = _normalize_rows(payload)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(
        yaml.safe_dump(
            {"holdings": holdings},
            allow_unicode=True,
            sort_keys=False,
        ),
        encoding="utf-8",
    )
    return len(holdings)


@contextmanager
def temporary_holdings_file(path: Path) -> Iterator[None]:
    previous = os.environ.get("HOLDINGS_FILE")
    os.environ["HOLDINGS_FILE"] = path.as_posix()
    try:
        yield
    finally:
        if previous is None:
            os.environ.pop("HOLDINGS_FILE", None)
        else:
            os.environ["HOLDINGS_FILE"] = previous


__all__ = [
    "SupabaseHoldingsExportConfig",
    "SupabaseHoldingsExportError",
    "export_active_holdings_snapshot",
    "temporary_holdings_file",
]
