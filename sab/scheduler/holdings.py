from __future__ import annotations

import hashlib
import json
import os
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import UTC, date, datetime
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation
from pathlib import Path
from typing import Any
from urllib.parse import urlencode

import requests  # type: ignore[import-untyped]
import yaml  # type: ignore[import-untyped]


class SupabaseHoldingsExportError(RuntimeError):
    """Raised when scheduled holdings export cannot produce a safe snapshot."""


class BrokerSnapshotError(SupabaseHoldingsExportError):
    """A sealed BrokerSnapshotV0 could not be trusted."""

    def __init__(self, code: str, message: str) -> None:
        self.code = code
        super().__init__(message)


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


@dataclass(frozen=True)
class BrokerSnapshotV0:
    state_key: str
    session_date: str
    status: str
    fresh_until: datetime
    sealed_at: datetime
    holdings_digest: str
    revision: int
    marker: dict[str, object]
    holdings: tuple[dict[str, object], ...]


_HOLDINGS_FIELDS = (
    "ticker",
    "quantity",
    "entry_price",
    "entry_currency",
    "entry_date",
    "strategy",
    "entry_pattern",
    "notes",
    "tags",
    "stop_override",
    "target_override",
    "broker_state",
    "broker_missing_first_seen_date",
    "broker_missing_last_seen_date",
    "broker_missing_count",
    "broker_missing_diff_hash",
)
_OPTIONAL_FIELDS = tuple(field for field in _HOLDINGS_FIELDS if field != "ticker")
_BROKER_SNAPSHOT_KEYS = {
    "state_key",
    "session_date",
    "status",
    "fresh_until",
    "sealed_at",
    "holdings_digest",
    "revision",
    "marker",
    "holdings",
}
_BROKER_DIGEST_PREFIX = b"broker-holdings-v0;"
_BROKER_SCALAR_FIELDS_BEFORE_TAGS = (
    "ticker",
    "quantity",
    "entry_price",
    "entry_currency",
    "entry_date",
    "strategy",
    "entry_pattern",
    "notes",
)
_BROKER_SCALAR_FIELDS_AFTER_TAGS = (
    "stop_override",
    "target_override",
    "broker_state",
    "broker_missing_first_seen_date",
    "broker_missing_last_seen_date",
    "broker_missing_count",
    "broker_missing_diff_hash",
)
_HASH_PREFIX = "sha256:"


def _snapshot_error(code: str, message: str) -> BrokerSnapshotError:
    return BrokerSnapshotError(code, message)


def _normalize_snapshot_text(
    value: object,
    field: str,
    *,
    nullable: bool = True,
    uppercase: bool = False,
    lowercase: bool = False,
) -> str | None:
    if value is None:
        if nullable:
            return None
        raise _snapshot_error("PAYLOAD_INVALID", f"{field} must be a string")
    if not isinstance(value, str):
        raise _snapshot_error("PAYLOAD_INVALID", f"{field} must be a string")
    normalized = value.strip(" ")
    if not normalized:
        if nullable:
            return None
        raise _snapshot_error("PAYLOAD_INVALID", f"{field} must not be blank")
    if uppercase:
        normalized = normalized.upper()
    if lowercase:
        normalized = normalized.lower()
    return normalized


def _normalize_snapshot_decimal(
    value: object,
    field: str,
    scale: int,
    *,
    nullable: bool = False,
) -> str | None:
    if value is None:
        if nullable:
            return None
        raise _snapshot_error("PAYLOAD_INVALID", f"{field} must be numeric")
    if isinstance(value, bool) or not isinstance(value, (int, float, str, Decimal)):
        raise _snapshot_error("PAYLOAD_INVALID", f"{field} must be numeric")
    try:
        parsed = Decimal(str(value))
        if not parsed.is_finite() or parsed < 0:
            raise InvalidOperation
        quantized = parsed.quantize(
            Decimal(1).scaleb(-scale),
            rounding=ROUND_HALF_UP,
        )
    except (InvalidOperation, ValueError) as exc:
        raise _snapshot_error(
            "PAYLOAD_INVALID", f"{field} must be a finite non-negative number"
        ) from exc
    return format(quantized, f".{scale}f")


def _normalize_snapshot_date(value: object, field: str) -> str | None:
    normalized = _normalize_snapshot_text(value, field)
    if normalized is None:
        return None
    try:
        parsed = date.fromisoformat(normalized)
    except ValueError as exc:
        raise _snapshot_error(
            "PAYLOAD_INVALID", f"{field} must be an ISO date"
        ) from exc
    if parsed.isoformat() != normalized:
        raise _snapshot_error("PAYLOAD_INVALID", f"{field} must be an ISO date")
    return normalized


def _normalize_snapshot_tags(value: object) -> list[str]:
    if not isinstance(value, list):
        raise _snapshot_error("PAYLOAD_INVALID", "tags must be a list")
    tags: list[str] = []
    for index, raw in enumerate(value):
        if not isinstance(raw, str):
            raise _snapshot_error("PAYLOAD_INVALID", f"tags[{index}] must be a string")
        normalized = raw.strip(" ")
        if normalized:
            tags.append(normalized)
    return sorted(tags, key=lambda tag: tag.encode("utf-8"))


def _normalize_broker_holding_v0(raw: object) -> dict[str, object]:
    if not isinstance(raw, dict) or set(raw) != set(_HOLDINGS_FIELDS):
        raise _snapshot_error(
            "PAYLOAD_INVALID",
            "BrokerSnapshotV0 holding row has an invalid field set",
        )
    missing_count = raw["broker_missing_count"]
    if (
        isinstance(missing_count, bool)
        or not isinstance(missing_count, int)
        or missing_count < 0
    ):
        raise _snapshot_error(
            "PAYLOAD_INVALID",
            "broker_missing_count must be a non-negative integer",
        )
    broker_state = _normalize_snapshot_text(
        raw["broker_state"],
        "broker_state",
        nullable=False,
        lowercase=True,
    )
    if broker_state not in {"confirmed", "not_seen_in_toss"}:
        raise _snapshot_error("PAYLOAD_INVALID", "broker_state is invalid")
    ticker = _normalize_snapshot_text(
        raw["ticker"],
        "ticker",
        nullable=False,
        uppercase=True,
    )
    assert ticker is not None
    return {
        "ticker": ticker,
        "quantity": _normalize_snapshot_decimal(raw["quantity"], "quantity", 6),
        "entry_price": _normalize_snapshot_decimal(
            raw["entry_price"], "entry_price", 4
        ),
        "entry_currency": _normalize_snapshot_text(
            raw["entry_currency"], "entry_currency", uppercase=True
        ),
        "entry_date": _normalize_snapshot_date(raw["entry_date"], "entry_date"),
        "strategy": _normalize_snapshot_text(raw["strategy"], "strategy"),
        "entry_pattern": _normalize_snapshot_text(
            raw["entry_pattern"], "entry_pattern"
        ),
        "notes": _normalize_snapshot_text(raw["notes"], "notes"),
        "tags": _normalize_snapshot_tags(raw["tags"]),
        "stop_override": _normalize_snapshot_decimal(
            raw["stop_override"], "stop_override", 4, nullable=True
        ),
        "target_override": _normalize_snapshot_decimal(
            raw["target_override"], "target_override", 4, nullable=True
        ),
        "broker_state": broker_state,
        "broker_missing_first_seen_date": _normalize_snapshot_date(
            raw["broker_missing_first_seen_date"],
            "broker_missing_first_seen_date",
        ),
        "broker_missing_last_seen_date": _normalize_snapshot_date(
            raw["broker_missing_last_seen_date"],
            "broker_missing_last_seen_date",
        ),
        "broker_missing_count": missing_count,
        "broker_missing_diff_hash": _normalize_snapshot_text(
            raw["broker_missing_diff_hash"], "broker_missing_diff_hash"
        ),
    }


def _normalize_broker_holdings_v0(
    rows: object,
) -> tuple[dict[str, object], ...]:
    if not isinstance(rows, list):
        raise _snapshot_error("PAYLOAD_INVALID", "holdings must be a list")
    normalized = sorted(
        (_normalize_broker_holding_v0(row) for row in rows),
        key=lambda row: str(row["ticker"]).encode("utf-8"),
    )
    tickers = [str(row["ticker"]) for row in normalized]
    if len(tickers) != len(set(tickers)):
        raise _snapshot_error(
            "PAYLOAD_INVALID", "holdings contain duplicate canonical tickers"
        )
    return tuple(normalized)


def _append_canonical_scalar(target: bytearray, value: object) -> None:
    if value is None:
        target.extend(b"N")
        return
    encoded = str(value).encode("utf-8")
    target.extend(f"S{len(encoded)}:".encode("ascii"))
    target.extend(encoded)


def broker_holdings_digest_v0(rows: object) -> str:
    """Hash the normalized persisted-holdings projection used by the V0 RPC."""

    normalized_rows = _normalize_broker_holdings_v0(rows)
    canonical = bytearray(_BROKER_DIGEST_PREFIX)
    for row in normalized_rows:
        canonical.extend(b"R")
        for field in _BROKER_SCALAR_FIELDS_BEFORE_TAGS:
            _append_canonical_scalar(canonical, row[field])
        tags = row["tags"]
        assert isinstance(tags, list)
        canonical.extend(f"A{len(tags)}:".encode("ascii"))
        for tag in tags:
            _append_canonical_scalar(canonical, tag)
        for field in _BROKER_SCALAR_FIELDS_AFTER_TAGS:
            _append_canonical_scalar(canonical, row[field])
    return _HASH_PREFIX + hashlib.sha256(canonical).hexdigest()


def _parse_snapshot_timestamp(value: object, field: str) -> datetime:
    if not isinstance(value, str) or not value.strip():
        raise _snapshot_error("PAYLOAD_INVALID", f"{field} must be a timestamp")
    try:
        parsed = datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
    except ValueError as exc:
        raise _snapshot_error(
            "PAYLOAD_INVALID", f"{field} must be a timezone-aware timestamp"
        ) from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise _snapshot_error(
            "PAYLOAD_INVALID", f"{field} must be a timezone-aware timestamp"
        )
    return parsed.astimezone(UTC)


def _parse_broker_snapshot_v0(
    payload: object,
    *,
    now: datetime,
    minimum_revision: int | None,
) -> BrokerSnapshotV0:
    if not isinstance(payload, list) or len(payload) != 1:
        raise _snapshot_error(
            "PAYLOAD_INVALID",
            "get_broker_snapshot_v0 must return exactly one row",
        )
    raw = payload[0]
    if not isinstance(raw, dict) or set(raw) != _BROKER_SNAPSHOT_KEYS:
        raise _snapshot_error(
            "PAYLOAD_INVALID", "BrokerSnapshotV0 response has an invalid field set"
        )

    revision = raw["revision"]
    if (
        isinstance(revision, bool)
        or not isinstance(revision, int)
        or revision <= 0
        or (minimum_revision is not None and revision <= minimum_revision)
    ):
        raise _snapshot_error(
            "REVISION_INVALID",
            "BrokerSnapshotV0 revision is not positive and monotonic",
        )
    session_date = _normalize_snapshot_date(raw["session_date"], "session_date")
    status = _normalize_snapshot_text(raw["status"], "status", nullable=False)
    state_key = _normalize_snapshot_text(raw["state_key"], "state_key", nullable=False)
    if (
        session_date is None
        or status not in {"applied", "unchanged"}
        or state_key != f"toss-sync:success:MIXED:{session_date}"
    ):
        raise _snapshot_error(
            "MARKER_INVALID", "BrokerSnapshotV0 marker is missing or unconfirmed"
        )

    fresh_until = _parse_snapshot_timestamp(raw["fresh_until"], "fresh_until")
    sealed_at = _parse_snapshot_timestamp(raw["sealed_at"], "sealed_at")
    if fresh_until <= now.astimezone(UTC):
        raise _snapshot_error("MARKER_EXPIRED", "BrokerSnapshotV0 marker has expired")
    if sealed_at >= fresh_until:
        raise _snapshot_error(
            "MARKER_INVALID", "BrokerSnapshotV0 sealed_at must precede fresh_until"
        )

    digest = raw["holdings_digest"]
    if (
        not isinstance(digest, str)
        or len(digest) != len(_HASH_PREFIX) + 64
        or not digest.startswith(_HASH_PREFIX)
        or any(character not in "0123456789abcdef" for character in digest[7:])
    ):
        raise _snapshot_error(
            "PAYLOAD_INVALID", "BrokerSnapshotV0 holdings_digest is invalid"
        )
    marker = raw["marker"]
    if not isinstance(marker, dict):
        raise _snapshot_error(
            "MARKER_INVALID", "BrokerSnapshotV0 marker payload is missing"
        )
    if (
        marker.get("scope") != "MIXED"
        or marker.get("sessionDate") != session_date
        or marker.get("status") != status
        or marker.get("snapshotDigest") != digest
        or marker.get("snapshotRevision") != revision
    ):
        raise _snapshot_error(
            "MARKER_INVALID", "BrokerSnapshotV0 marker payload does not match the seal"
        )
    marker_sealed_at = _parse_snapshot_timestamp(marker.get("sealedAt"), "sealedAt")
    if marker_sealed_at != sealed_at:
        raise _snapshot_error(
            "MARKER_INVALID", "BrokerSnapshotV0 marker payload does not match the seal"
        )

    normalized_rows = _normalize_broker_holdings_v0(raw["holdings"])
    recomputed = broker_holdings_digest_v0(list(normalized_rows))
    if recomputed != digest:
        raise _snapshot_error(
            "DIGEST_MISMATCH", "BrokerSnapshotV0 holdings digest does not match rows"
        )
    return BrokerSnapshotV0(
        state_key=state_key,
        session_date=session_date,
        status=status,
        fresh_until=fresh_until,
        sealed_at=sealed_at,
        holdings_digest=digest,
        revision=revision,
        marker=dict(marker),
        holdings=normalized_rows,
    )


def fetch_broker_snapshot_v0(
    *,
    config: SupabaseHoldingsExportConfig,
    session: Any | None = None,
    now: datetime | None = None,
    minimum_revision: int | None = None,
) -> BrokerSnapshotV0:
    """Read and verify one sealed marker and holdings set through one RPC call."""

    active_session = session or requests.Session()
    try:
        response = active_session.post(
            f"{config.url}/rest/v1/rpc/get_broker_snapshot_v0",
            headers={**_headers(config), "content-type": "application/json"},
            json={},
            timeout=config.timeout_seconds,
        )
    except requests.RequestException as exc:
        raise _snapshot_error(
            "RPC_UNAVAILABLE", f"get_broker_snapshot_v0 is unavailable: {exc}"
        ) from exc
    if response.status_code != 200:
        raise _snapshot_error(
            "RPC_UNAVAILABLE",
            f"get_broker_snapshot_v0 failed: {response.status_code}",
        )
    try:
        payload = response.json()
    except (json.JSONDecodeError, ValueError) as exc:
        raise _snapshot_error(
            "PAYLOAD_INVALID", "get_broker_snapshot_v0 returned invalid JSON"
        ) from exc
    current_time = now or datetime.now(UTC)
    if current_time.tzinfo is None or current_time.utcoffset() is None:
        raise ValueError("now must be timezone-aware")
    return _parse_broker_snapshot_v0(
        payload,
        now=current_time,
        minimum_revision=minimum_revision,
    )


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
        broker_state = str(raw.get("broker_state") or "confirmed").strip()
        if not broker_state:
            broker_state = "confirmed"
        for field_name in _OPTIONAL_FIELDS:
            if field_name == "entry_pattern":
                if field_name not in raw:
                    raise SupabaseHoldingsExportError(
                        "Supabase holdings response omitted entry_pattern"
                    )
                item[field_name] = raw.get(field_name)
                continue
            if field_name == "broker_state":
                if broker_state != "confirmed":
                    item[field_name] = broker_state
                continue
            if field_name.startswith("broker_missing_") and broker_state == "confirmed":
                continue
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
    try:
        response = active_session.get(
            f"{config.url}/rest/v1/holdings?{query}",
            headers=_headers(config),
            timeout=config.timeout_seconds,
        )
    except requests.RequestException as exc:
        raise SupabaseHoldingsExportError(
            f"failed to fetch active holdings: {exc}"
        ) from exc
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
    "BrokerSnapshotError",
    "BrokerSnapshotV0",
    "SupabaseHoldingsExportConfig",
    "SupabaseHoldingsExportError",
    "broker_holdings_digest_v0",
    "export_active_holdings_snapshot",
    "fetch_broker_snapshot_v0",
    "temporary_holdings_file",
]
