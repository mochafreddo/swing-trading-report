"""Supabase Storage consumer for immutable public Decision Board input snapshots."""

from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass, field
from typing import Protocol, cast
from urllib.parse import quote, urlsplit

import requests  # type: ignore[import-untyped]

from .cli import DecisionBoardCliConfigV0
from .compiler import (
    ApprovalStateV0,
    DependencyStateV0,
    EntryCompilerItemV0,
    EntrySignalStateV0,
    ExposureStateV0,
    HardExitStateV0,
    HoldingCompilerItemV0,
    ResearchStateV0,
)
from .contracts import canonical_json_bytes, decision_payload_hash
from .instruments import InstrumentRefV0
from .policy import select_holding_research_v0
from .production_adapter import DecisionBoardAdapterUnavailableError
from .runner import create_decision_run_request_v0

_MAX_SNAPSHOT_BYTES = 1_048_576
_HASH_PATTERN = re.compile(r"sha256:[0-9a-f]{64}\Z")
_BUCKET_PATTERN = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,127}\Z")
_SNAPSHOT_FIELDS = {"schema", "run_kind", "metadata", "items"}
_INSTRUMENT_FIELDS = {
    "market",
    "canonical_ticker",
    "exchange",
    "company_name",
    "identity_source",
    "identity_version",
}
_ENTRY_ITEM_FIELDS = {
    "item_id",
    "instrument",
    "item_state",
    "identity_state",
    "signal_state",
    "mandate_state",
    "price_state",
    "exposure_state",
}
_HOLDING_ITEM_FIELDS = {
    "item_id",
    "instrument",
    "item_state",
    "identity_state",
    "hard_exit_state",
    "broker_state",
    "candle_state",
    "rule_state",
    "research_priority",
    "research_order",
}


class DecisionInputDownloaderV0(Protocol):
    def download(self, storage_key: str, *, max_bytes: int) -> bytes: ...


@dataclass(frozen=True, slots=True)
class SupabaseDecisionInputConfigV0:
    url: str
    service_role_key: str = field(repr=False)
    bucket: str = "reports"
    timeout_seconds: float = 10.0

    def __post_init__(self) -> None:
        parsed = urlsplit(self.url)
        local_http = parsed.scheme == "http" and parsed.hostname in {
            "127.0.0.1",
            "localhost",
            "::1",
        }
        if (
            (parsed.scheme != "https" and not local_http)
            or not parsed.hostname
            or parsed.username is not None
            or parsed.password is not None
            or parsed.query
            or parsed.fragment
            or type(self.service_role_key) is not str
            or not self.service_role_key.strip()
            or self.service_role_key.startswith("sb_publishable_")
            or _BUCKET_PATTERN.fullmatch(self.bucket) is None
            or isinstance(self.timeout_seconds, bool)
            or not isinstance(self.timeout_seconds, (int, float))
            or not 0 < self.timeout_seconds <= 15
        ):
            raise ValueError("Supabase Decision Board input config is invalid")
        object.__setattr__(self, "url", self.url.rstrip("/"))

    @classmethod
    def from_env(cls) -> SupabaseDecisionInputConfigV0:
        url = str(os.getenv("SUPABASE_URL") or "").strip()
        key = str(
            os.getenv("SUPABASE_SECRET_KEY")
            or os.getenv("SUPABASE_SERVICE_ROLE_KEY")
            or ""
        ).strip()
        bucket = str(os.getenv("SUPABASE_REPORTS_BUCKET") or "reports").strip()
        if not url or not key:
            raise DecisionBoardAdapterUnavailableError(
                "Supabase Decision Board input config is unavailable"
            )
        try:
            return cls(url=url, service_role_key=key, bucket=bucket)
        except ValueError as exc:
            raise DecisionBoardAdapterUnavailableError(
                "Supabase Decision Board input config is unavailable"
            ) from exc


@dataclass(frozen=True, slots=True)
class SupabaseSnapshotDownloaderV0:
    config: SupabaseDecisionInputConfigV0

    def download(self, storage_key: str, *, max_bytes: int) -> bytes:
        if (
            type(storage_key) is not str
            or not storage_key.startswith("decision-board-inputs/v0/")
            or type(max_bytes) is not int
            or not 1 <= max_bytes <= _MAX_SNAPSHOT_BYTES
        ):
            raise ValueError("Decision Board snapshot download request is invalid")
        quoted_key = quote(storage_key, safe="/")
        url = f"{self.config.url}/storage/v1/object/{self.config.bucket}/{quoted_key}"
        session = requests.Session()
        session.trust_env = False
        response: requests.Response | None = None
        try:
            response = session.get(
                url,
                headers={
                    "Accept": "application/json",
                    "apikey": self.config.service_role_key,
                    "Authorization": f"Bearer {self.config.service_role_key}",
                },
                timeout=(
                    self.config.timeout_seconds,
                    self.config.timeout_seconds,
                ),
                allow_redirects=False,
                stream=True,
            )
            if response.status_code != 200:
                raise DecisionBoardAdapterUnavailableError(
                    "Decision Board snapshot is unavailable"
                )
            body = bytearray()
            for chunk in response.iter_content(chunk_size=64 * 1024):
                body.extend(chunk)
                if len(body) > max_bytes:
                    raise ValueError("Decision Board snapshot exceeds the byte limit")
            return bytes(body)
        except requests.RequestException as exc:
            raise DecisionBoardAdapterUnavailableError(
                "Decision Board snapshot is unavailable"
            ) from exc
        finally:
            if response is not None:
                response.close()
            session.close()


@dataclass(frozen=True, slots=True)
class SupabaseSealedRequestSourceV0:
    """Reissue one factory-owned request from a content-addressed public snapshot."""

    downloader: DecisionInputDownloaderV0

    def __post_init__(self) -> None:
        if not callable(getattr(self.downloader, "download", None)):
            raise TypeError("Decision Board snapshot downloader is unavailable")

    def load_sealed_request(self, identity: dict[str, str]) -> object:
        config = _identity_config(identity)
        digest = config.sealed_input_hash.removeprefix("sha256:")
        storage_key = f"decision-board-inputs/v0/{digest}.json"
        payload = self.downloader.download(
            storage_key,
            max_bytes=_MAX_SNAPSHOT_BYTES,
        )
        snapshot = _decode_snapshot(payload)
        if decision_payload_hash(snapshot) != config.sealed_input_hash:
            raise ValueError("Decision Board snapshot hash does not match its identity")
        if snapshot["run_kind"] != config.run_kind.value:
            raise ValueError("Decision Board snapshot lane does not match its identity")
        items = _parse_items(snapshot["items"], run_kind=config.run_kind.value)
        selection = (
            None
            if config.run_kind.value == "ENTRY"
            else select_holding_research_v0(
                cast(tuple[HoldingCompilerItemV0, ...], items)
            )
        )
        metadata = snapshot["metadata"]
        if type(metadata) is not dict:
            raise ValueError("Decision Board snapshot metadata is invalid")
        return create_decision_run_request_v0(
            run_kind=config.run_kind,
            run_id=config.run_id,
            idempotency_key=config.idempotency_key,
            created_at=config.created_at,
            sealed_input_hash=config.sealed_input_hash,
            items=items,
            selection=selection,
            upload_mode=config.upload_mode,
            metadata=metadata,
        )


def _identity_config(identity: object) -> DecisionBoardCliConfigV0:
    if (
        type(identity) is not dict
        or set(identity)
        != {
            "run_kind",
            "run_id",
            "idempotency_key",
            "created_at",
            "sealed_input_hash",
            "upload_mode",
        }
        or not all(type(value) is str for value in identity.values())
    ):
        raise ValueError("Decision Board public identity is invalid")
    return DecisionBoardCliConfigV0.from_strings(
        run_kind=identity["run_kind"],
        run_id=identity["run_id"],
        idempotency_key=identity["idempotency_key"],
        created_at=identity["created_at"],
        sealed_input_hash=identity["sealed_input_hash"],
        upload_mode=identity["upload_mode"],
        report_dir=".",
    )


def _decode_snapshot(payload: object) -> dict[str, object]:
    if type(payload) is not bytes or len(payload) > _MAX_SNAPSHOT_BYTES:
        raise ValueError("Decision Board snapshot bytes are invalid")

    def unique_object(pairs: list[tuple[str, object]]) -> dict[str, object]:
        value: dict[str, object] = {}
        for key, field_value in pairs:
            if key in value:
                raise ValueError("Decision Board snapshot contains duplicate keys")
            value[key] = field_value
        return value

    try:
        decoded = json.loads(
            payload.decode("utf-8"),
            object_pairs_hook=unique_object,
            parse_constant=lambda _value: (_ for _ in ()).throw(
                ValueError("non-finite JSON is invalid")
            ),
        )
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError("Decision Board snapshot JSON is invalid") from exc
    if (
        type(decoded) is not dict
        or set(decoded) != _SNAPSHOT_FIELDS
        or decoded["schema"] != "sab.decision_board.sealed_request.v0"
        or decoded["run_kind"] not in {"ENTRY", "HOLDING"}
        or type(decoded["items"]) is not list
    ):
        raise ValueError("Decision Board snapshot shape is invalid")
    canonical_json_bytes(decoded)
    return decoded


def _parse_items(value: object, *, run_kind: str) -> tuple[object, ...]:
    if type(value) is not list:
        raise ValueError("Decision Board snapshot items are invalid")
    expected_fields = (
        _ENTRY_ITEM_FIELDS if run_kind == "ENTRY" else _HOLDING_ITEM_FIELDS
    )
    items: list[object] = []
    for row in value:
        if type(row) is not dict or set(row) != expected_fields:
            raise ValueError("Decision Board snapshot item shape is invalid")
        instrument = _parse_instrument(row["instrument"])
        if run_kind == "ENTRY":
            items.append(
                EntryCompilerItemV0.create(
                    item_id=row["item_id"],
                    instrument=instrument,
                    item_state=ApprovalStateV0(row["item_state"]),
                    identity_state=ApprovalStateV0(row["identity_state"]),
                    signal_state=EntrySignalStateV0(row["signal_state"]),
                    mandate_state=DependencyStateV0(row["mandate_state"]),
                    price_state=DependencyStateV0(row["price_state"]),
                    exposure_state=ExposureStateV0(row["exposure_state"]),
                    research_state=ResearchStateV0.COVERAGE_GAP,
                )
            )
        else:
            items.append(
                HoldingCompilerItemV0.create(
                    item_id=row["item_id"],
                    instrument=instrument,
                    item_state=ApprovalStateV0(row["item_state"]),
                    identity_state=ApprovalStateV0(row["identity_state"]),
                    hard_exit_state=HardExitStateV0(row["hard_exit_state"]),
                    broker_state=DependencyStateV0(row["broker_state"]),
                    candle_state=DependencyStateV0(row["candle_state"]),
                    rule_state=DependencyStateV0(row["rule_state"]),
                    research_state=ResearchStateV0.COVERAGE_GAP,
                    research_priority=row["research_priority"],
                    research_order=row["research_order"],
                )
            )
    return tuple(items)


def _parse_instrument(value: object) -> InstrumentRefV0:
    if type(value) is not dict or set(value) != _INSTRUMENT_FIELDS:
        raise ValueError("Decision Board snapshot instrument is invalid")
    return InstrumentRefV0(**value)


__all__ = [
    "SupabaseDecisionInputConfigV0",
    "SupabaseSealedRequestSourceV0",
    "SupabaseSnapshotDownloaderV0",
]
