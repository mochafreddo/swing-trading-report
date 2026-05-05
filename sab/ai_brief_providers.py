from __future__ import annotations

import datetime as dt
import json
from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any

import requests  # type: ignore[import-untyped]

MODEL_PROVIDER_FAKE = "fake"
MODEL_PROVIDER_OPENAI = "openai"
DEFAULT_MODEL_TIMEOUT_SECONDS = 20.0
OPENAI_RESPONSES_URL = "https://api.openai.com/v1/responses"
PRESELECTION_LIMIT = 5
RECOMMENDATION_LIMIT = 3

_ALLOWED_CONFIDENCE = frozenset({"LOW", "MEDIUM", "HIGH"})
_ALLOWED_ISSUE_SEVERITY = frozenset({"INFO", "WARN", "ERROR"})
_MAX_SOURCES_PER_TICKER = 3
_SOURCE_FRESHNESS_HOURS = 72
_AUTOMATED_ORDER_PHRASES = (
    "buy now",
    "execute order",
    "place order",
    "submit order",
    "automatic order",
    "automated order",
)


@dataclass(frozen=True)
class AiBriefProviderResult:
    recommendations: list[dict[str, object]]
    source_issues: list[dict[str, object]]
    vetoed_candidates: list[dict[str, object]] = field(default_factory=list)


class AiBriefProviderError(RuntimeError):
    code = "model_provider_failed"


class AiBriefProviderTimeoutError(AiBriefProviderError):
    code = "model_provider_timeout"


class AiBriefProviderContractError(AiBriefProviderError):
    code = "model_provider_contract_error"


class FakeAiBriefProvider:
    def __init__(self, *, model_name: str) -> None:
        self.model_name = model_name

    def build_recommendations(
        self, *, candidates: list[dict[str, object]]
    ) -> AiBriefProviderResult:
        as_of = _offset_now_iso()
        recommendations: list[dict[str, object]] = []
        source_issues: list[dict[str, object]] = []
        for rank, candidate in enumerate(candidates[:RECOMMENDATION_LIMIT], start=1):
            ticker = str(candidate["ticker"])
            sources = _candidate_sources(candidate)
            recommendations.append(
                {
                    "ticker": ticker,
                    "name": candidate.get("name"),
                    "rank": rank,
                    "action": "ENTER",
                    "confidence": "LOW",
                    "rationale": _build_fake_rationale(candidate),
                    "checklist": [
                        "entry price is still close to the entry report snapshot",
                        "gap guard, position size, and cash availability are acceptable",
                        "manually check for blocking headlines or market-wide shocks",
                    ],
                    "sources": sources,
                    "as_of": as_of,
                }
            )
            if not sources:
                source_issues.append(
                    {
                        "ticker": ticker,
                        "code": "fake_provider_no_external_sources",
                        "severity": "WARN",
                        "message": "fake provider does not collect external sources",
                    }
                )
        return AiBriefProviderResult(
            recommendations=recommendations,
            source_issues=source_issues,
        )


class OpenAiBriefProvider:
    def __init__(
        self,
        *,
        model_name: str,
        api_key: str,
        timeout_seconds: float,
        session: requests.Session | None = None,
    ) -> None:
        self.model_name = model_name
        self._api_key = api_key
        self._timeout_seconds = timeout_seconds
        self._session = session or requests.Session()

    def build_recommendations(
        self, *, candidates: list[dict[str, object]]
    ) -> AiBriefProviderResult:
        if not candidates:
            return AiBriefProviderResult(recommendations=[], source_issues=[])

        request_payload = _build_openai_request_payload(
            model_name=self.model_name,
            candidates=candidates,
        )
        try:
            response = self._session.post(
                OPENAI_RESPONSES_URL,
                headers={
                    "Authorization": f"Bearer {self._api_key}",
                    "Content-Type": "application/json",
                },
                json=request_payload,
                timeout=self._timeout_seconds,
            )
        except requests.Timeout as exc:
            raise AiBriefProviderTimeoutError("OpenAI request timed out") from exc
        except requests.RequestException as exc:
            raise AiBriefProviderError(f"OpenAI request failed: {exc}") from exc

        if response.status_code >= 400:
            raise AiBriefProviderError(
                f"OpenAI request failed with HTTP {response.status_code}: "
                f"{response.text[:200]}"
            )

        try:
            response_payload = response.json()
        except ValueError as exc:
            raise AiBriefProviderContractError(
                "OpenAI response was not valid JSON"
            ) from exc

        parsed = _parse_openai_structured_output(response_payload)
        result = _normalize_openai_provider_result(parsed, candidates=candidates)
        _validate_provider_result_contract(
            result,
            eligible_tickers={str(candidate["ticker"]) for candidate in candidates},
            source_urls_by_ticker=_source_urls_by_ticker(candidates),
        )
        return result


def _build_openai_request_payload(
    *, model_name: str, candidates: list[dict[str, object]]
) -> dict[str, object]:
    return {
        "model": model_name,
        "input": [
            {
                "role": "system",
                "content": (
                    "You summarize swing-trading entry candidates for manual "
                    "review. Return JSON only. Do not create new tickers. Do not "
                    "recommend REVIEW or SKIP rows. Do not use automated-order "
                    "language such as buy now, execute order, or place order. "
                    "Only cite sources supplied in each candidate's sources list. "
                    "Every checklist item must support a human pre-order check."
                ),
            },
            {
                "role": "user",
                "content": json.dumps(
                    {
                        "task": (
                            "Rank up to three ENTER candidates from the supplied "
                            "entry report candidates. Use only candidate.sources "
                            "for recommendation sources. If a candidate has no "
                            "usable sources, leave sources empty and add a source "
                            "issue for the ticker."
                        ),
                        "candidates": candidates,
                    },
                    ensure_ascii=False,
                    sort_keys=True,
                ),
            },
        ],
        "text": {
            "format": {
                "type": "json_schema",
                "name": "sab_ai_brief_provider_result",
                "strict": True,
                "schema": _openai_result_schema(),
            }
        },
    }


def _openai_result_schema() -> dict[str, object]:
    return {
        "type": "object",
        "additionalProperties": False,
        "required": ["recommendations", "vetoed_candidates", "source_issues"],
        "properties": {
            "recommendations": {
                "type": "array",
                "maxItems": RECOMMENDATION_LIMIT,
                "items": {
                    "type": "object",
                    "additionalProperties": False,
                    "required": [
                        "ticker",
                        "rank",
                        "confidence",
                        "rationale",
                        "checklist",
                        "sources",
                    ],
                    "properties": {
                        "ticker": {"type": "string"},
                        "rank": {"type": "integer"},
                        "confidence": {
                            "type": "string",
                            "enum": ["LOW", "MEDIUM", "HIGH"],
                        },
                        "rationale": {
                            "type": "array",
                            "items": {"type": "string"},
                        },
                        "checklist": {
                            "type": "array",
                            "items": {"type": "string"},
                        },
                        "sources": {
                            "type": "array",
                            "maxItems": 3,
                            "items": {
                                "type": "object",
                                "additionalProperties": False,
                                "required": ["title", "url", "published_at"],
                                "properties": {
                                    "title": {"type": "string"},
                                    "url": {"type": "string"},
                                    "published_at": {"type": "string"},
                                },
                            },
                        },
                    },
                },
            },
            "vetoed_candidates": {
                "type": "array",
                "items": {
                    "type": "object",
                    "additionalProperties": False,
                    "required": ["ticker", "action", "reason"],
                    "properties": {
                        "ticker": {"type": "string"},
                        "action": {"type": "string", "enum": ["PASS", "SKIP"]},
                        "reason": {"type": "string"},
                    },
                },
            },
            "source_issues": {
                "type": "array",
                "items": {
                    "type": "object",
                    "additionalProperties": False,
                    "required": ["ticker", "code", "severity", "message"],
                    "properties": {
                        "ticker": {"type": ["string", "null"]},
                        "code": {"type": "string"},
                        "severity": {
                            "type": "string",
                            "enum": ["INFO", "WARN", "ERROR"],
                        },
                        "message": {"type": "string"},
                    },
                },
            },
        },
    }


def _parse_openai_structured_output(payload: object) -> dict[str, Any]:
    if not isinstance(payload, Mapping):
        raise AiBriefProviderContractError("OpenAI response must be an object")

    output_text = payload.get("output_text")
    if isinstance(output_text, str) and output_text.strip():
        raw_text = output_text.strip()
    else:
        raw_text = _extract_openai_output_text(payload)
    try:
        parsed = json.loads(raw_text)
    except json.JSONDecodeError as exc:
        raise AiBriefProviderContractError(
            "OpenAI structured output was not valid JSON"
        ) from exc
    if not isinstance(parsed, dict):
        raise AiBriefProviderContractError("OpenAI structured output must be an object")
    return parsed


def _extract_openai_output_text(payload: Mapping[str, Any]) -> str:
    output = payload.get("output")
    if not isinstance(output, list):
        raise AiBriefProviderContractError("OpenAI response missing output text")
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
        raise AiBriefProviderContractError("OpenAI response missing output text")
    return "\n".join(parts)


def _normalize_openai_provider_result(
    parsed: Mapping[str, Any], *, candidates: list[dict[str, object]]
) -> AiBriefProviderResult:
    candidate_by_ticker = {
        str(candidate["ticker"]): candidate for candidate in candidates
    }
    recommendations: list[dict[str, object]] = []
    for raw_recommendation in _as_provider_mapping_rows(
        parsed.get("recommendations"), field_name="recommendations"
    ):
        ticker = str(raw_recommendation.get("ticker") or "").strip()
        if ticker not in candidate_by_ticker:
            raise AiBriefProviderContractError(
                f"OpenAI output included ineligible ticker {ticker!r}"
            )
        candidate = candidate_by_ticker[ticker]
        recommendations.append(
            {
                "ticker": ticker,
                "name": candidate.get("name"),
                "rank": raw_recommendation.get("rank"),
                "action": "ENTER",
                "confidence": str(
                    raw_recommendation.get("confidence") or "LOW"
                ).upper(),
                "rationale": _string_list(raw_recommendation.get("rationale")),
                "checklist": _string_list(raw_recommendation.get("checklist")),
                "sources": _as_provider_mapping_rows(
                    raw_recommendation.get("sources"), field_name="sources"
                ),
                "as_of": _offset_now_iso(),
            }
        )

    source_issues = _as_provider_mapping_rows(
        parsed.get("source_issues"), field_name="source_issues"
    )
    vetoed_candidates = _as_provider_mapping_rows(
        parsed.get("vetoed_candidates"), field_name="vetoed_candidates"
    )
    return AiBriefProviderResult(
        recommendations=recommendations,
        source_issues=source_issues,
        vetoed_candidates=vetoed_candidates,
    )


def _as_provider_mapping_rows(
    value: object, *, field_name: str
) -> list[dict[str, object]]:
    if not isinstance(value, list):
        raise AiBriefProviderContractError(f"OpenAI output {field_name} must be a list")
    rows: list[dict[str, object]] = []
    for idx, raw_row in enumerate(value):
        if not isinstance(raw_row, Mapping):
            raise AiBriefProviderContractError(
                f"OpenAI output {field_name}[{idx}] must be an object"
            )
        rows.append(dict(raw_row))
    return rows


def _provider_source_issue_tickers(source_issues: list[dict[str, object]]) -> set[str]:
    tickers: set[str] = set()
    for issue in source_issues:
        ticker = str(issue.get("ticker") or "").strip()
        if ticker:
            tickers.add(ticker)
    return tickers


def _source_urls_by_ticker(
    candidates: list[dict[str, object]],
) -> dict[str, set[str]]:
    urls_by_ticker: dict[str, set[str]] = {}
    for candidate in candidates:
        ticker = str(candidate.get("ticker") or "").strip()
        if not ticker:
            continue
        urls_by_ticker[ticker] = {
            str(source.get("url") or "").strip()
            for source in _candidate_sources(candidate)
            if str(source.get("url") or "").strip()
        }
    return urls_by_ticker


def _parse_provider_offset_datetime(value: object, *, field_name: str) -> dt.datetime:
    text = str(value or "").strip()
    if not text:
        raise AiBriefProviderContractError(f"OpenAI output {field_name} is required")
    try:
        parsed = dt.datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError as exc:
        raise AiBriefProviderContractError(
            f"OpenAI output {field_name} must be an ISO 8601 datetime"
        ) from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise AiBriefProviderContractError(
            f"OpenAI output {field_name} must include a UTC offset"
        )
    return parsed


def _validate_provider_sources(
    recommendation: Mapping[str, object],
    *,
    recommendation_index: int,
    now: dt.datetime,
    allowed_source_urls: set[str],
) -> int:
    sources = recommendation.get("sources")
    if not isinstance(sources, list):
        raise AiBriefProviderContractError(
            f"OpenAI output recommendations[{recommendation_index}].sources "
            "must be a list"
        )
    if len(sources) > _MAX_SOURCES_PER_TICKER:
        raise AiBriefProviderContractError(
            "OpenAI output recommendations[].sources must contain at most "
            f"{_MAX_SOURCES_PER_TICKER} sources"
        )
    for source_index, raw_source in enumerate(sources):
        if not isinstance(raw_source, Mapping):
            raise AiBriefProviderContractError(
                "OpenAI output recommendations"
                f"[{recommendation_index}].sources[{source_index}] must be an object"
            )
        if not str(raw_source.get("title") or "").strip():
            raise AiBriefProviderContractError("OpenAI output source title is required")
        source_url = str(raw_source.get("url") or "").strip()
        if not source_url:
            raise AiBriefProviderContractError("OpenAI output source url is required")
        published_at = _parse_provider_offset_datetime(
            raw_source.get("published_at"), field_name="source.published_at"
        )
        if now.astimezone(dt.UTC) - published_at.astimezone(dt.UTC) > dt.timedelta(
            hours=_SOURCE_FRESHNESS_HOURS
        ):
            raise AiBriefProviderContractError(
                "OpenAI output source.published_at must be within 72h"
            )
        if source_url not in allowed_source_urls:
            raise AiBriefProviderContractError(
                "OpenAI output source url must be supplied in candidate.sources"
            )
    return len(sources)


def _validate_provider_result_contract(
    result: AiBriefProviderResult,
    *,
    eligible_tickers: set[str],
    source_urls_by_ticker: dict[str, set[str]] | None = None,
) -> None:
    if len(result.recommendations) > RECOMMENDATION_LIMIT:
        raise AiBriefProviderContractError(
            f"OpenAI output recommendations must contain at most {RECOMMENDATION_LIMIT}"
        )

    _validate_provider_issue_list(result.source_issues)
    _validate_provider_vetoed_candidates(
        result.vetoed_candidates, eligible_tickers=eligible_tickers
    )
    source_issue_tickers = _provider_source_issue_tickers(result.source_issues)
    seen_ranks: set[int] = set()
    now = dt.datetime.now().astimezone()
    for idx, recommendation in enumerate(result.recommendations):
        ticker = str(recommendation.get("ticker") or "").strip()
        if ticker not in eligible_tickers:
            raise AiBriefProviderContractError(
                f"OpenAI output included ineligible ticker {ticker!r}"
            )
        rank = recommendation.get("rank")
        if isinstance(rank, bool) or not isinstance(rank, int) or rank <= 0:
            raise AiBriefProviderContractError(
                "OpenAI output recommendations[].rank must be a positive int"
            )
        if rank in seen_ranks:
            raise AiBriefProviderContractError(
                "OpenAI output recommendations[].rank must be unique"
            )
        seen_ranks.add(rank)
        confidence = str(recommendation.get("confidence") or "").strip().upper()
        if confidence not in _ALLOWED_CONFIDENCE:
            raise AiBriefProviderContractError(
                "OpenAI output recommendations[].confidence must be LOW, MEDIUM, or HIGH"
            )
        rationale = _string_list(recommendation.get("rationale"))
        checklist = _string_list(recommendation.get("checklist"))
        if not rationale:
            raise AiBriefProviderContractError(
                "OpenAI output recommendations[].rationale is required"
            )
        if not checklist:
            raise AiBriefProviderContractError(
                "OpenAI output recommendations[].checklist is required"
            )
        language_text = " ".join([*rationale, *checklist]).lower()
        if any(phrase in language_text for phrase in _AUTOMATED_ORDER_PHRASES):
            raise AiBriefProviderContractError(
                "OpenAI output must avoid automated-order language"
            )
        source_count = _validate_provider_sources(
            recommendation,
            recommendation_index=idx,
            now=now,
            allowed_source_urls=(source_urls_by_ticker or {}).get(ticker, set()),
        )
        if source_count == 0 and ticker not in source_issue_tickers:
            raise AiBriefProviderContractError(
                "OpenAI output recommendations with no sources must have a "
                "ticker source issue"
            )


def _validate_provider_issue_list(source_issues: list[dict[str, object]]) -> None:
    for idx, issue in enumerate(source_issues):
        if not str(issue.get("code") or "").strip():
            raise AiBriefProviderContractError(
                f"OpenAI output source_issues[{idx}].code is required"
            )
        if not str(issue.get("message") or "").strip():
            raise AiBriefProviderContractError(
                f"OpenAI output source_issues[{idx}].message is required"
            )
        severity = str(issue.get("severity") or "").strip().upper()
        if severity not in _ALLOWED_ISSUE_SEVERITY:
            raise AiBriefProviderContractError(
                "OpenAI output source_issues[].severity must be INFO, WARN, or ERROR"
            )


def _validate_provider_vetoed_candidates(
    vetoed_candidates: list[dict[str, object]],
    *,
    eligible_tickers: set[str],
) -> None:
    for idx, candidate in enumerate(vetoed_candidates):
        ticker = str(candidate.get("ticker") or "").strip()
        if not ticker:
            raise AiBriefProviderContractError(
                f"OpenAI output vetoed_candidates[{idx}].ticker is required"
            )
        if ticker not in eligible_tickers:
            raise AiBriefProviderContractError(
                f"OpenAI output vetoed_candidates[{idx}].ticker must be eligible"
            )
        action = str(candidate.get("action") or "").strip().upper()
        if action not in {"PASS", "SKIP"}:
            raise AiBriefProviderContractError(
                "OpenAI output vetoed_candidates[].action must be PASS or SKIP"
            )
        if not str(candidate.get("reason") or "").strip():
            raise AiBriefProviderContractError(
                f"OpenAI output vetoed_candidates[{idx}].reason is required"
            )


def _offset_now_iso() -> str:
    return dt.datetime.now().astimezone().replace(microsecond=0).isoformat()


def _string_list(value: object) -> list[str]:
    if not isinstance(value, list):
        return []
    return [str(item).strip() for item in value if str(item).strip()]


def _candidate_sources(candidate: Mapping[str, object]) -> list[dict[str, object]]:
    sources = candidate.get("sources")
    if not isinstance(sources, list):
        return []
    candidate_sources: list[dict[str, object]] = []
    for raw_source in sources[:_MAX_SOURCES_PER_TICKER]:
        if not isinstance(raw_source, Mapping):
            continue
        source: dict[str, object] = {
            "title": str(raw_source.get("title") or "").strip(),
            "url": str(raw_source.get("url") or "").strip(),
            "published_at": str(raw_source.get("published_at") or "").strip(),
        }
        if source["title"] and source["url"] and source["published_at"]:
            candidate_sources.append(source)
    return candidate_sources


def _build_fake_rationale(candidate: Mapping[str, object]) -> list[str]:
    rationale = ["entry report marked this candidate ENTER"]
    entry_reasons = candidate.get("entry_reasons")
    if isinstance(entry_reasons, list) and entry_reasons:
        rationale.append(str(entry_reasons[0]))
    buy_reason_labels = candidate.get("buy_reason_labels")
    if isinstance(buy_reason_labels, list) and buy_reason_labels:
        rationale.append(f"buy signal context: {buy_reason_labels[0]}")
    gap_pct = candidate.get("gap_pct")
    if isinstance(gap_pct, int | float):
        rationale.append(f"entry gap snapshot: {gap_pct * 100:.2f}%")
    if _candidate_sources(candidate):
        rationale.append("local source context is available for manual review")
    return rationale


__all__ = [
    "DEFAULT_MODEL_TIMEOUT_SECONDS",
    "MODEL_PROVIDER_FAKE",
    "MODEL_PROVIDER_OPENAI",
    "OPENAI_RESPONSES_URL",
    "PRESELECTION_LIMIT",
    "AiBriefProviderContractError",
    "AiBriefProviderError",
    "AiBriefProviderTimeoutError",
    "FakeAiBriefProvider",
    "OpenAiBriefProvider",
]
