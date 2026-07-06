from __future__ import annotations

import hashlib
import json
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from typing import Any, Literal

MAX_OPENAI_RESPONSE_BYTES = 1024 * 1024


@dataclass(frozen=True)
class ProviderTraceMetadata:
    prompt_version: str
    output_schema_version: str
    request_hash: str
    source_catalog_hash: str
    request_status: Literal["sent", "planned_not_sent"]


def json_hash(value: object) -> str:
    payload = json.dumps(value, sort_keys=True, separators=(",", ":")).encode()
    return "sha256:" + hashlib.sha256(payload).hexdigest()


def decode_openai_response_json(
    response: object,
    *,
    error_type: type[Exception],
    max_bytes: int = MAX_OPENAI_RESPONSE_BYTES,
) -> object:
    headers = getattr(response, "headers", None)
    headers_get = getattr(headers, "get", None)
    content_length = headers_get("content-length") if callable(headers_get) else None
    if content_length is not None:
        try:
            declared_size = int(str(content_length).strip())
        except ValueError:
            declared_size = None
        if declared_size is not None and declared_size > max_bytes:
            _close_response(response)
            raise error_type(f"OpenAI response body is too large (> {max_bytes} bytes)")

    iter_content = getattr(response, "iter_content", None)
    if callable(iter_content):
        chunks: list[bytes] = []
        total_size = 0
        for chunk in iter_content(chunk_size=64 * 1024):
            if not chunk:
                continue
            if isinstance(chunk, str):
                chunk = chunk.encode("utf-8")
            total_size += len(chunk)
            if total_size > max_bytes:
                _close_response(response)
                raise error_type(
                    f"OpenAI response body is too large ({total_size} bytes > "
                    f"{max_bytes} bytes)"
                )
            chunks.append(bytes(chunk))
        try:
            return json.loads(b"".join(chunks).decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise error_type("OpenAI response was not valid JSON") from exc

    text = str(getattr(response, "text", ""))
    if len(text.encode("utf-8")) > max_bytes:
        _close_response(response)
        raise error_type(f"OpenAI response body is too large (> {max_bytes} bytes)")
    json_loader = getattr(response, "json", None)
    if not callable(json_loader):
        raise error_type("OpenAI response was not valid JSON")
    try:
        return json_loader()
    except ValueError as exc:
        raise error_type("OpenAI response was not valid JSON") from exc


def _close_response(response: object) -> None:
    close = getattr(response, "close", None)
    if callable(close):
        close()


def normalize_provider_source_issues(
    source_issues: list[dict[str, object]],
    *,
    allowed_tickers: set[str],
    dropped_code: str,
    dropped_message: str,
) -> list[dict[str, object]]:
    normalized: list[dict[str, object]] = []
    dropped_tickers: set[str] = set()
    for issue in source_issues:
        ticker = str(issue.get("ticker") or "").strip()
        if ticker and ticker not in allowed_tickers:
            dropped_tickers.add(ticker)
            continue
        if ticker:
            issue = {**issue, "ticker": ticker}
        normalized.append(issue)
    if dropped_tickers:
        normalized.append(
            {
                "code": dropped_code,
                "severity": "WARN",
                "message": dropped_message,
                "dropped_tickers": sorted(dropped_tickers),
            }
        )
    return normalized


def parse_openai_structured_output(
    payload: object,
    *,
    error_type: type[Exception],
) -> dict[str, Any]:
    if not isinstance(payload, Mapping):
        raise error_type("OpenAI response must be an object")

    output_text = payload.get("output_text")
    if isinstance(output_text, str) and output_text.strip():
        raw_text = output_text.strip()
    else:
        raw_text = _extract_openai_output_text(payload, error_type=error_type)
    try:
        parsed = json.loads(raw_text)
    except json.JSONDecodeError as exc:
        raise error_type("OpenAI structured output was not valid JSON") from exc
    if not isinstance(parsed, dict):
        raise error_type("OpenAI structured output must be an object")
    return parsed


def _extract_openai_output_text(
    payload: Mapping[str, Any],
    *,
    error_type: type[Exception],
) -> str:
    output = payload.get("output")
    if not isinstance(output, list):
        raise error_type("OpenAI response missing output text")
    parts: list[str] = []
    for item in output:
        if not isinstance(item, Mapping):
            continue
        content = item.get("content")
        if not isinstance(content, list):
            continue
        for content_item in content:
            if not isinstance(content_item, Mapping):
                continue
            if content_item.get("type") == "output_text":
                text = str(content_item.get("text") or "").strip()
                if text:
                    parts.append(text)
    if not parts:
        raise error_type("OpenAI response missing output text")
    return "\n".join(parts)


def _source_id_for(
    ticker: str,
    index: int,
    *,
    occurrence_index: int,
    duplicate_ticker: bool,
) -> str:
    if duplicate_ticker:
        return f"{ticker}#{occurrence_index}:{index}"
    return f"{ticker}:{index}"


def candidate_source_ref_lists(
    candidates: Sequence[Mapping[str, object]],
    *,
    source_getter: Callable[[Mapping[str, object]], list[dict[str, object]]],
) -> list[list[str]]:
    ticker_counts: dict[str, int] = {}
    for candidate in candidates:
        ticker = str(candidate.get("ticker") or "").strip()
        if ticker:
            ticker_counts[ticker] = ticker_counts.get(ticker, 0) + 1

    occurrence_counts: dict[str, int] = {}
    refs_by_candidate: list[list[str]] = []
    for candidate in candidates:
        ticker = str(candidate.get("ticker") or "").strip()
        if not ticker:
            refs_by_candidate.append([])
            continue
        occurrence_counts[ticker] = occurrence_counts.get(ticker, 0) + 1
        duplicate_ticker = ticker_counts.get(ticker, 0) > 1
        refs_by_candidate.append(
            [
                _source_id_for(
                    ticker,
                    index,
                    occurrence_index=occurrence_counts[ticker],
                    duplicate_ticker=duplicate_ticker,
                )
                for index, _source in enumerate(source_getter(candidate), start=1)
            ]
        )
    return refs_by_candidate


class SourceReferenceCatalog:
    def __init__(
        self,
        candidates: Sequence[Mapping[str, object]],
        *,
        source_getter: Callable[[Mapping[str, object]], list[dict[str, object]]],
    ) -> None:
        self._source_getter = source_getter
        self._sources_by_ticker: dict[str, dict[str, dict[str, object]]] = {}
        self._sources_by_candidate_index: list[dict[str, dict[str, object]]] = []
        source_refs_by_candidate = candidate_source_ref_lists(
            candidates,
            source_getter=source_getter,
        )
        for candidate, source_refs in zip(
            candidates,
            source_refs_by_candidate,
            strict=True,
        ):
            ticker = str(candidate.get("ticker") or "").strip()
            if not ticker:
                self._sources_by_candidate_index.append({})
                continue
            rows_by_id: dict[str, dict[str, object]] = {}
            for source_id, source in zip(
                source_refs,
                source_getter(candidate),
                strict=True,
            ):
                rows_by_id[source_id] = source
                self._sources_by_ticker.setdefault(ticker, {})[source_id] = source
            self._sources_by_candidate_index.append(rows_by_id)

    def model_candidates(
        self,
        candidates: Sequence[Mapping[str, object]],
    ) -> list[dict[str, object]]:
        model_rows: list[dict[str, object]] = []
        for candidate, sources_by_id in zip(
            candidates,
            self._sources_by_candidate_index,
            strict=True,
        ):
            sources = [
                {"source_id": source_id, **source}
                for source_id, source in sources_by_id.items()
            ]
            model_rows.append({**dict(candidate), "sources": sources})
        return model_rows

    def sources_for_refs(
        self,
        *,
        ticker: str,
        source_refs: list[str],
    ) -> tuple[list[dict[str, object]], list[str]]:
        rows_by_id = self._sources_by_ticker.get(ticker, {})
        resolved: list[dict[str, object]] = []
        invalid_refs: list[str] = []
        for source_ref in source_refs:
            source = rows_by_id.get(source_ref)
            if source is None:
                invalid_refs.append(source_ref)
                continue
            resolved.append(dict(source))
        return resolved, invalid_refs

    def has_sources_for(self, ticker: str) -> bool:
        return bool(self._sources_by_ticker.get(ticker))


__all__ = [
    "ProviderTraceMetadata",
    "SourceReferenceCatalog",
    "candidate_source_ref_lists",
    "decode_openai_response_json",
    "json_hash",
    "normalize_provider_source_issues",
    "parse_openai_structured_output",
]
