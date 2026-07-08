from __future__ import annotations

import datetime as dt
import json
import logging
import math
import os
import time
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import Any, cast

from .ai_brief_source_chain import (
    load_ai_brief_source_chain,
    parse_source_provider_chain,
)
from .ai_brief_sources import (
    DEFAULT_SOURCE_TIMEOUT_SECONDS,
    SOURCE_PROVIDER_ALPHA_VANTAGE_NEWS,
    SOURCE_PROVIDER_BENZINGA_NEWS,
    SOURCE_PROVIDER_FINNHUB,
    SOURCE_PROVIDER_HTTP_JSON,
    SOURCE_PROVIDER_LOCAL_JSON,
    SOURCE_PROVIDER_MARKETAUX_NEWS,
    SOURCE_PROVIDER_NAVER_NEWS,
    SOURCE_PROVIDER_NONE,
    SOURCE_PROVIDER_POLYGON_NEWS,
    AiBriefSourceProviderError,
)
from .article_reader import (
    DEFAULT_ARTICLE_READER_MAX_EXCERPT_CHARS,
    DEFAULT_ARTICLE_READER_MAX_URLS,
    DEFAULT_ARTICLE_READER_TIMEOUT_SECONDS,
    ArticleReaderName,
    ArticleReaderSettings,
    article_read_summary,
    enrich_sources_with_article_reads,
)
from .config import ConfigLoadError, load_config
from .observability import current_run_id
from .report.sell_ai_brief_report import (
    SellAiBriefValidationError,
    write_sell_ai_brief_report,
)
from .report.supabase_storage import SupabaseStorageError, maybe_upload_report_artifact
from .sell_ai_brief_candidates import (
    SellAiBriefCandidate,
    classify_sell_ai_brief_rows,
)
from .sell_ai_brief_providers import (
    DEFAULT_MODEL_TIMEOUT_SECONDS,
    MODEL_PROVIDER_FAKE,
    MODEL_PROVIDER_OPENAI,
    PRESELECTION_LIMIT,
    FakeSellAiBriefProvider,
    OpenAiSellAiBriefProvider,
    SellAiBriefProviderError,
    SellAiBriefProviderResult,
    SellAiBriefProviderTraceMetadata,
)
from .tickers import infer_market_from_ticker

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class SellAiBriefRunResult:
    exit_code: int
    report_path: str | None = None


_DEFAULT_MODEL_NAME = "fake-sell-ai-brief-v1"
_ALLOWED_MODEL_PROVIDERS = frozenset({MODEL_PROVIDER_FAKE, MODEL_PROVIDER_OPENAI})
_ALLOWED_SOURCE_PROVIDERS = frozenset(
    {
        SOURCE_PROVIDER_NONE,
        SOURCE_PROVIDER_LOCAL_JSON,
        SOURCE_PROVIDER_HTTP_JSON,
        SOURCE_PROVIDER_FINNHUB,
        SOURCE_PROVIDER_POLYGON_NEWS,
        SOURCE_PROVIDER_ALPHA_VANTAGE_NEWS,
        SOURCE_PROVIDER_MARKETAUX_NEWS,
        SOURCE_PROVIDER_BENZINGA_NEWS,
        SOURCE_PROVIDER_NAVER_NEWS,
    }
)
_TIMEOUT_SOURCE_PROVIDERS = frozenset(
    {
        SOURCE_PROVIDER_HTTP_JSON,
        SOURCE_PROVIDER_FINNHUB,
        SOURCE_PROVIDER_POLYGON_NEWS,
        SOURCE_PROVIDER_ALPHA_VANTAGE_NEWS,
        SOURCE_PROVIDER_MARKETAUX_NEWS,
        SOURCE_PROVIDER_BENZINGA_NEWS,
        SOURCE_PROVIDER_NAVER_NEWS,
    }
)
_FIXED_API_SOURCE_PROVIDERS = _TIMEOUT_SOURCE_PROVIDERS - {SOURCE_PROVIDER_HTTP_JSON}


def _current_utc_time() -> dt.datetime:
    return dt.datetime.now(dt.UTC)


def _read_env_float(name: str, *, error_message: str) -> float | None:
    raw = os.getenv(name)
    if raw is None or not raw.strip():
        return None
    try:
        return float(raw)
    except ValueError as exc:
        raise ValueError(error_message) from exc


def _read_env_int(name: str, *, error_message: str) -> int | None:
    raw = os.getenv(name)
    if raw is None or not raw.strip():
        return None
    try:
        return int(raw)
    except ValueError as exc:
        raise ValueError(error_message) from exc


def _normalize_model_provider(value: str | None) -> str:
    provider = str(value or MODEL_PROVIDER_FAKE).strip().lower()
    if provider not in _ALLOWED_MODEL_PROVIDERS:
        raise ValueError(
            f"model_provider must be one of {sorted(_ALLOWED_MODEL_PROVIDERS)}"
        )
    return provider


def _normalize_model_name(*, provider: str, value: str | None) -> str:
    model_name = str(value or _DEFAULT_MODEL_NAME).strip()
    if provider == MODEL_PROVIDER_OPENAI:
        env_model = os.getenv("OPENAI_SELL_AI_BRIEF_MODEL") or os.getenv(
            "OPENAI_AI_BRIEF_MODEL"
        )
        if (not value or model_name == _DEFAULT_MODEL_NAME) and env_model:
            model_name = env_model.strip()
        if not model_name or model_name == _DEFAULT_MODEL_NAME:
            raise ValueError(
                "--model-provider openai requires --model-name, "
                "OPENAI_SELL_AI_BRIEF_MODEL, or OPENAI_AI_BRIEF_MODEL"
            )
    if not model_name:
        raise ValueError("model_name must not be empty")
    return model_name


def _normalize_model_timeout_seconds(value: float | None) -> float:
    if value is None:
        value = _read_env_float(
            "SELL_AI_BRIEF_MODEL_TIMEOUT_SECONDS",
            error_message="SELL_AI_BRIEF_MODEL_TIMEOUT_SECONDS must be a number",
        )
        if value is None:
            value = _read_env_float(
                "AI_BRIEF_MODEL_TIMEOUT_SECONDS",
                error_message="AI_BRIEF_MODEL_TIMEOUT_SECONDS must be a number",
            )
        if value is None:
            return DEFAULT_MODEL_TIMEOUT_SECONDS
    if not math.isfinite(value) or value <= 0:
        raise ValueError("model_timeout_seconds must be positive")
    return float(value)


def _normalize_source_provider(
    *,
    value: str | None,
    source_report_path: str | None,
    source_api_url: str | None,
) -> str:
    provider = str(value or "").strip().lower()
    if not provider:
        if source_report_path and source_api_url:
            raise ValueError("use either --source-report or --source-api-url, not both")
        if source_report_path:
            return SOURCE_PROVIDER_LOCAL_JSON
        if source_api_url:
            return SOURCE_PROVIDER_HTTP_JSON
        return SOURCE_PROVIDER_NONE
    if provider not in _ALLOWED_SOURCE_PROVIDERS:
        raise ValueError(
            f"source_provider must be one of {sorted(_ALLOWED_SOURCE_PROVIDERS)}"
        )
    if provider == SOURCE_PROVIDER_LOCAL_JSON and source_api_url:
        raise ValueError("--source-provider local-json does not use --source-api-url")
    if provider == SOURCE_PROVIDER_HTTP_JSON and source_report_path:
        raise ValueError("--source-provider http-json does not use --source-report")
    if provider in _FIXED_API_SOURCE_PROVIDERS and source_report_path:
        raise ValueError(f"--source-provider {provider} does not use --source-report")
    if provider in _FIXED_API_SOURCE_PROVIDERS and source_api_url:
        raise ValueError(f"--source-provider {provider} does not use --source-api-url")
    return provider


def _normalize_source_api_url(
    *, source_providers: tuple[str, ...], value: str | None
) -> str | None:
    explicit = str(value or "").strip()
    if SOURCE_PROVIDER_HTTP_JSON not in source_providers:
        if explicit:
            raise ValueError(
                "--source-api-url is only valid with a source provider chain "
                "containing http-json"
            )
        return None
    api_url = str(explicit or os.getenv("AI_BRIEF_SOURCE_API_URL") or "").strip()
    if not api_url:
        raise ValueError(
            "--source-provider http-json requires --source-api-url or "
            "AI_BRIEF_SOURCE_API_URL"
        )
    if "\n" in api_url or "\r" in api_url:
        raise ValueError("source_api_url must be a single-line value")
    return api_url


def _normalize_source_timeout_seconds(
    *, source_providers: tuple[str, ...], value: float | None
) -> float | None:
    if not any(provider in _TIMEOUT_SOURCE_PROVIDERS for provider in source_providers):
        if value is not None:
            raise ValueError(
                "--source-timeout-seconds is only valid with a network source provider"
            )
        return None
    if value is None:
        value = _read_env_float(
            "AI_BRIEF_SOURCE_TIMEOUT_SECONDS",
            error_message="AI_BRIEF_SOURCE_TIMEOUT_SECONDS must be a number",
        )
        if value is None:
            return DEFAULT_SOURCE_TIMEOUT_SECONDS
    if not math.isfinite(value) or value <= 0:
        raise ValueError("source_timeout_seconds must be positive")
    return float(value)


def _source_provider_chain_from_env(name: str) -> tuple[str, ...] | None:
    value = os.getenv(name)
    if value and value.strip():
        return parse_source_provider_chain(value)
    return None


def _combine_market_source_provider_chains(
    *chains: tuple[str, ...] | None,
) -> tuple[str, ...]:
    providers: list[str] = []
    saw_none = False
    for chain in chains:
        if not chain:
            continue
        for provider in chain:
            if provider == SOURCE_PROVIDER_NONE:
                saw_none = True
                continue
            if provider not in providers:
                providers.append(provider)
    if providers:
        return tuple(providers)
    return (SOURCE_PROVIDER_NONE,) if saw_none else ()


def _resolve_source_provider_chain(
    *,
    target_market: str,
    normalized_source_provider: str,
    source_provider: str | None,
    source_report_path: str | None,
    source_api_url: str | None,
) -> tuple[str, ...]:
    if (
        str(source_provider or "").strip()
        or str(source_report_path or "").strip()
        or str(source_api_url or "").strip()
    ):
        return (normalized_source_provider,)
    market_chain = _source_provider_chain_from_env(
        f"SELL_AI_BRIEF_SOURCE_PROVIDER_CHAIN_{target_market}"
    )
    if market_chain:
        return market_chain
    if target_market == "MIXED":
        mixed_market_chain = _combine_market_source_provider_chains(
            _source_provider_chain_from_env("SELL_AI_BRIEF_SOURCE_PROVIDER_CHAIN_KR"),
            _source_provider_chain_from_env("SELL_AI_BRIEF_SOURCE_PROVIDER_CHAIN_US"),
        )
        if mixed_market_chain:
            return mixed_market_chain
    global_chain = _source_provider_chain_from_env(
        "SELL_AI_BRIEF_SOURCE_PROVIDER_CHAIN"
    )
    if global_chain:
        return global_chain
    fallback_chain = _source_provider_chain_from_env("AI_BRIEF_SOURCE_PROVIDER_CHAIN")
    if fallback_chain:
        return fallback_chain
    return (normalized_source_provider,)


def _normalize_article_reader(value: str | None) -> ArticleReaderName:
    reader = (
        str(value or os.getenv("AI_BRIEF_ARTICLE_READER") or "none").strip().lower()
    )
    if reader not in {"none", "lightpanda"}:
        raise ValueError("article_reader must be one of ['lightpanda', 'none']")
    return cast(ArticleReaderName, reader)


def _normalize_article_reader_max_urls(value: int | None) -> int:
    if value is None:
        value = _read_env_int(
            "AI_BRIEF_ARTICLE_READER_MAX_URLS",
            error_message="AI_BRIEF_ARTICLE_READER_MAX_URLS must be an integer",
        )
        if value is None:
            return DEFAULT_ARTICLE_READER_MAX_URLS
    if value < 0:
        raise ValueError("article_reader_max_urls must be non-negative")
    return value


def _normalize_article_reader_timeout_seconds(value: float | None) -> float:
    if value is None:
        value = _read_env_float(
            "AI_BRIEF_ARTICLE_READER_TIMEOUT_SECONDS",
            error_message="AI_BRIEF_ARTICLE_READER_TIMEOUT_SECONDS must be a number",
        )
        if value is None:
            return DEFAULT_ARTICLE_READER_TIMEOUT_SECONDS
    if not math.isfinite(value) or value <= 0:
        raise ValueError("article_reader_timeout_seconds must be positive")
    return float(value)


def _normalize_article_reader_max_excerpt_chars(value: int | None) -> int:
    if value is None:
        value = _read_env_int(
            "AI_BRIEF_ARTICLE_READER_MAX_EXCERPT_CHARS",
            error_message="AI_BRIEF_ARTICLE_READER_MAX_EXCERPT_CHARS must be an integer",
        )
        if value is None:
            return DEFAULT_ARTICLE_READER_MAX_EXCERPT_CHARS
    if value < 1:
        raise ValueError("article_reader_max_excerpt_chars must be positive")
    return value


def _normalize_article_reader_settings(
    *,
    article_reader: str | None,
    article_reader_max_urls: int | None,
    article_reader_timeout_seconds: float | None,
    article_reader_max_excerpt_chars: int | None,
) -> ArticleReaderSettings:
    return ArticleReaderSettings(
        reader=_normalize_article_reader(article_reader),
        max_urls=_normalize_article_reader_max_urls(article_reader_max_urls),
        timeout_seconds=_normalize_article_reader_timeout_seconds(
            article_reader_timeout_seconds
        ),
        max_excerpt_chars=_normalize_article_reader_max_excerpt_chars(
            article_reader_max_excerpt_chars
        ),
    )


def _load_json_object(path: str, *, label: str) -> dict[str, Any]:
    try:
        with open(path, encoding="utf-8") as fp:
            raw = json.load(fp)
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(f"Failed to load {label}: {exc}") from exc
    if not isinstance(raw, dict):
        raise ValueError(f"{label} must contain a JSON object")
    return raw


def _as_mapping_rows(value: object, *, field_name: str) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        raise ValueError(f"{field_name} must be a list")
    return [dict(item) for item in value if isinstance(item, Mapping)]


def _resolve_target_market(
    source_report: Mapping[str, Any], rows: list[dict[str, Any]]
) -> str:
    market = str(source_report.get("market") or "").strip().upper()
    if market in {"KR", "US", "MIXED"}:
        return market
    markets = source_report.get("markets")
    if isinstance(markets, list):
        normalized = sorted(
            {
                str(raw_market).strip().upper()
                for raw_market in markets
                if str(raw_market).strip().upper() in {"KR", "US"}
            }
        )
        if len(normalized) == 1:
            return normalized[0]
        if len(normalized) > 1:
            return "MIXED"
    inferred = {
        infer_market_from_ticker(ticker)
        for row in rows
        if (ticker := str(row.get("ticker") or "").strip())
    }
    inferred.discard("")
    if len(inferred) == 1:
        return next(iter(inferred))
    if len(inferred) > 1:
        return "MIXED"
    raise ValueError("sell report market must be KR, US, or MIXED")


def _build_model_candidate(classified: SellAiBriefCandidate) -> dict[str, object]:
    row = classified.row
    candidate: dict[str, object] = {
        "ticker": classified.ticker,
        "name": row.get("name"),
        "sell_action": classified.sell_action,
        "ai_role_reason": classified.reason,
        "deterministic_reasons": classified.deterministic_reasons,
        "last_price": row.get("last_price"),
        "pnl_pct": row.get("pnl_pct"),
        "stop_price": row.get("stop_price"),
        "target_price": row.get("target_price"),
        "quantity": row.get("quantity"),
        "entry_price": row.get("entry_price"),
        "entry_date": row.get("entry_date"),
        "sources": [],
    }
    for field_name in (
        "notes",
        "currency",
        "eval_date",
        "flags",
        "days_in_trade_sessions",
        "time_stop_triggered",
    ):
        if field_name in row:
            candidate[field_name] = row.get(field_name)
    return candidate


def _build_excluded_candidate(classified: SellAiBriefCandidate) -> dict[str, object]:
    row = classified.row
    payload: dict[str, object] = {
        "ticker": classified.ticker,
        "sell_action": classified.sell_action,
        "reason": classified.reason,
    }
    for field_name in (
        "broker_state",
        "broker_missing_first_seen_date",
        "broker_missing_last_seen_date",
        "broker_missing_count",
        "broker_missing_diff_hash",
    ):
        if field_name in row:
            payload[field_name] = row.get(field_name)
    return payload


def _build_cap_excluded_candidate(candidate: Mapping[str, object]) -> dict[str, object]:
    return {
        "ticker": str(candidate.get("ticker") or ""),
        "sell_action": str(candidate.get("sell_action") or ""),
        "reason": f"preselection cap {PRESELECTION_LIMIT} exceeded",
    }


def _attach_candidate_sources(
    candidates: list[dict[str, object]],
    sources_by_ticker: Mapping[str, list[dict[str, object]]],
) -> list[dict[str, object]]:
    enriched: list[dict[str, object]] = []
    for candidate in candidates:
        ticker = str(candidate["ticker"])
        enriched.append(
            {
                **candidate,
                "sources": [
                    dict(source) for source in sources_by_ticker.get(ticker, [])
                ],
            }
        )
    return enriched


def _source_sell_report_issues(
    source_report: Mapping[str, Any],
) -> list[dict[str, object]]:
    raw_issues = source_report.get("issues")
    if not isinstance(raw_issues, list):
        return []
    issues: list[dict[str, object]] = []
    for raw_issue in raw_issues:
        message = str(raw_issue).strip()
        if message:
            issues.append(
                {
                    "ticker": None,
                    "code": "source_sell_report_issue",
                    "severity": "WARN",
                    "message": message,
                }
            )
    return issues


def _build_provider(
    *,
    model_provider: str,
    model_name: str,
    model_timeout_seconds: float,
) -> FakeSellAiBriefProvider | OpenAiSellAiBriefProvider:
    if model_provider == MODEL_PROVIDER_FAKE:
        return FakeSellAiBriefProvider(model_name=model_name)
    api_key = str(os.getenv("OPENAI_API_KEY") or "").strip()
    if not api_key:
        raise ValueError(
            "--model-provider openai requires OPENAI_API_KEY in the environment"
        )
    return OpenAiSellAiBriefProvider(
        model_name=model_name,
        api_key=api_key,
        timeout_seconds=model_timeout_seconds,
    )


def _trace_metadata_fields(
    trace_metadata: SellAiBriefProviderTraceMetadata | None,
) -> dict[str, object]:
    if trace_metadata is None:
        return {}
    return {
        "prompt_version": trace_metadata.prompt_version,
        "output_schema_version": trace_metadata.output_schema_version,
        "request_hash": trace_metadata.request_hash,
        "source_catalog_hash": trace_metadata.source_catalog_hash,
        "request_status": trace_metadata.request_status,
    }


def _model_attempt_record(
    *,
    model_name: str,
    timeout_seconds: float,
    status: str,
    duration_ms: int,
    trace_metadata: SellAiBriefProviderTraceMetadata | None,
    error_type: str | None = None,
) -> dict[str, object]:
    payload: dict[str, object] = {
        "role": "primary",
        "model_name": model_name,
        "timeout_seconds": timeout_seconds,
        "status": status,
        "duration_ms": duration_ms,
        **_trace_metadata_fields(trace_metadata),
    }
    if error_type is not None:
        payload["error_type"] = error_type
    return payload


def _provider_system_issue(exc: SellAiBriefProviderError) -> dict[str, object]:
    return {
        "ticker": None,
        "code": exc.code,
        "severity": "ERROR",
        "message": str(exc),
    }


def _source_provider_system_issue(exc: AiBriefSourceProviderError) -> dict[str, object]:
    return {
        "ticker": None,
        "code": exc.code,
        "severity": "WARN",
        "message": str(exc),
    }


def _build_summary(
    *,
    evaluated_count: int,
    actionable_count: int,
    preselected_count: int,
    judgment_count: int,
    broker_state_review_count: int,
    excluded_hold_count: int,
    unsupported_action_count: int,
    vetoed_count: int,
    cap_excluded_count: int,
    source_issue_count: int,
    system_issue_count: int,
    article_summary: Mapping[str, int] | None = None,
) -> dict[str, object]:
    summary: dict[str, object] = {
        "evaluated_count": evaluated_count,
        "actionable_count": actionable_count,
        "preselected_count": preselected_count,
        "judgment_count": judgment_count,
        "broker_state_review_count": broker_state_review_count,
        "excluded_hold_count": excluded_hold_count,
        "unsupported_action_count": unsupported_action_count,
        "vetoed_count": vetoed_count,
        "cap_excluded_count": cap_excluded_count,
        "source_issue_count": source_issue_count,
        "system_issue_count": system_issue_count,
    }
    if article_summary:
        summary.update(article_summary)
    return summary


def run_sell_ai_brief(
    *,
    sell_report_path: str,
    model_provider: str | None,
    model_name: str | None,
    model_timeout_seconds: float | None = None,
    source_provider: str | None = None,
    source_report_path: str | None = None,
    source_api_url: str | None = None,
    source_timeout_seconds: float | None = None,
    article_reader: str | None = None,
    article_reader_max_urls: int | None = None,
    article_reader_timeout_seconds: float | None = None,
    article_reader_max_excerpt_chars: int | None = None,
    report_date: str | None = None,
    upload: bool = False,
    report_path_callback: Callable[[str], None] | None = None,
) -> int:
    run_id = current_run_id("sell-ai-brief")
    operation = "sell-ai-brief"
    try:
        source_api_url_input = str(source_api_url or "").strip() or None
        normalized_model_provider = _normalize_model_provider(model_provider)
        normalized_model_name = _normalize_model_name(
            provider=normalized_model_provider,
            value=model_name,
        )
        normalized_model_timeout_seconds = _normalize_model_timeout_seconds(
            model_timeout_seconds
        )
        normalized_source_provider = _normalize_source_provider(
            value=source_provider,
            source_report_path=source_report_path,
            source_api_url=source_api_url_input,
        )
        article_reader_settings = _normalize_article_reader_settings(
            article_reader=article_reader,
            article_reader_max_urls=article_reader_max_urls,
            article_reader_timeout_seconds=article_reader_timeout_seconds,
            article_reader_max_excerpt_chars=article_reader_max_excerpt_chars,
        )
    except ValueError as exc:
        logger.error(
            "%s",
            exc,
            extra={
                "event": "sell_ai_brief_failed",
                "run_id": run_id,
                "operation": operation,
                "status": "failed",
                "stage": "normalize_inputs",
            },
        )
        return 1

    try:
        cfg = load_config()
    except ConfigLoadError as exc:
        logger.error("Configuration loading failed: %s", exc)
        return 1

    try:
        source_report = _load_json_object(sell_report_path, label="sell report")
        if source_report.get("type") != "sell":
            raise ValueError("sell report type must be 'sell'")
        sell_rows = _as_mapping_rows(
            source_report.get("evaluated"),
            field_name="evaluated",
        )
        target_market = _resolve_target_market(source_report, sell_rows)
        resolved_source_provider_chain = _resolve_source_provider_chain(
            target_market=target_market,
            normalized_source_provider=normalized_source_provider,
            source_provider=source_provider,
            source_report_path=source_report_path,
            source_api_url=source_api_url_input,
        )
        normalized_source_api_url = _normalize_source_api_url(
            source_providers=resolved_source_provider_chain,
            value=source_api_url_input,
        )
        normalized_source_timeout_seconds = _normalize_source_timeout_seconds(
            source_providers=resolved_source_provider_chain,
            value=source_timeout_seconds,
        )
    except ValueError as exc:
        logger.error("%s", exc)
        return 1

    classified_rows = classify_sell_ai_brief_rows(sell_rows)
    actionable_candidates = [
        _build_model_candidate(classified) for classified in classified_rows.actionable
    ]
    preselected_candidates = actionable_candidates[:PRESELECTION_LIMIT]
    cap_excluded_candidates = [
        _build_cap_excluded_candidate(candidate)
        for candidate in actionable_candidates[PRESELECTION_LIMIT:]
    ]
    excluded_hold_candidates = [
        _build_excluded_candidate(classified)
        for classified in classified_rows.excluded_hold
    ]
    broker_state_review_candidates = [
        _build_excluded_candidate(classified)
        for classified in classified_rows.broker_state_review
    ]
    unsupported_action_candidates = [
        _build_excluded_candidate(classified)
        for classified in classified_rows.unsupported
    ]
    system_issues = [
        *_source_sell_report_issues(source_report),
        *classified_rows.system_issues,
    ]
    source_issues: list[dict[str, object]] = []
    source_provider_summary: dict[str, object] = {}
    article_summary: dict[str, int] = {}

    source_universe_tickers = {
        str(candidate["ticker"]) for candidate in preselected_candidates
    }
    ticker_names = {
        str(candidate["ticker"]): str(candidate.get("name") or "").strip()
        for candidate in preselected_candidates
        if str(candidate.get("name") or "").strip()
    }
    try:
        source_chain_result = load_ai_brief_source_chain(
            source_providers=resolved_source_provider_chain,
            source_report_path=source_report_path,
            source_api_url=normalized_source_api_url,
            source_timeout_seconds=normalized_source_timeout_seconds,
            source_universe_tickers=source_universe_tickers,
            recommendable_tickers=source_universe_tickers,
            watch_tickers=set(),
            ticker_names=ticker_names,
            now=_current_utc_time(),
        )
        sources_by_ticker = source_chain_result.sources_by_ticker
        article_issues: list[dict[str, object]] = []
        if article_reader_settings.enabled:
            sources_by_ticker, article_issues = enrich_sources_with_article_reads(
                sources_by_ticker,
                ticker_names=ticker_names,
                settings=article_reader_settings,
                now=_current_utc_time(),
            )
            article_summary = article_read_summary(sources_by_ticker)
        preselected_candidates = _attach_candidate_sources(
            preselected_candidates,
            sources_by_ticker,
        )
        source_issues = [*source_chain_result.source_issues, *article_issues]
        system_issues.extend(source_chain_result.system_issues)
        source_provider_summary = source_chain_result.summary
    except AiBriefSourceProviderError as exc:
        preselected_candidates = _attach_candidate_sources(preselected_candidates, {})
        system_issues.append(_source_provider_system_issue(exc))
        source_provider_summary = {
            "chain": list(resolved_source_provider_chain),
            "providers": [
                {
                    "provider": provider,
                    "status": "failed",
                    "code": exc.code,
                    "covered": 0,
                    "total": len(source_universe_tickers),
                }
                for provider in resolved_source_provider_chain
            ],
            "final": {
                "recommendable_covered": 0,
                "recommendable_total": len(source_universe_tickers),
                "watch_covered": 0,
                "watch_total": 0,
            },
        }

    judgments: list[dict[str, object]] = []
    vetoed_candidates: list[dict[str, object]] = []
    model_attempts: list[dict[str, object]] = []
    provider_result: SellAiBriefProviderResult | None = None
    provider_error: SellAiBriefProviderError | None = None
    if preselected_candidates:
        try:
            provider = _build_provider(
                model_provider=normalized_model_provider,
                model_name=normalized_model_name,
                model_timeout_seconds=normalized_model_timeout_seconds,
            )
            started = time.monotonic()
            provider_result = provider.build_judgments(
                actionable_candidates=preselected_candidates,
            )
            duration_ms = int((time.monotonic() - started) * 1000)
            judgments = provider_result.judgments
            source_issues = [*source_issues, *provider_result.source_issues]
            vetoed_candidates = provider_result.vetoed_candidates
            model_attempts.append(
                _model_attempt_record(
                    model_name=normalized_model_name,
                    timeout_seconds=normalized_model_timeout_seconds,
                    status="success",
                    duration_ms=duration_ms,
                    trace_metadata=provider_result.trace_metadata,
                )
            )
        except SellAiBriefProviderError as exc:
            provider_error = exc
            system_issues.append(_provider_system_issue(exc))
            model_attempts.append(
                _model_attempt_record(
                    model_name=normalized_model_name,
                    timeout_seconds=normalized_model_timeout_seconds,
                    status="failed",
                    duration_ms=0,
                    trace_metadata=exc.trace_metadata,
                    error_type=type(exc).__name__,
                )
            )
        except ValueError as exc:
            logger.error("%s", exc)
            return 1

    source_sell_report_basename = os.path.basename(sell_report_path)
    artifact: dict[str, object] = {
        "source_sell_report": source_sell_report_basename,
        "market": target_market,
        "model_provider": normalized_model_provider,
        "model_name": normalized_model_name,
        "model_attempts": model_attempts,
        "summary": _build_summary(
            evaluated_count=len(sell_rows),
            actionable_count=len(actionable_candidates),
            preselected_count=len(preselected_candidates),
            judgment_count=len(judgments),
            broker_state_review_count=len(broker_state_review_candidates),
            excluded_hold_count=len(excluded_hold_candidates),
            unsupported_action_count=len(unsupported_action_candidates),
            vetoed_count=len(vetoed_candidates),
            cap_excluded_count=len(cap_excluded_candidates),
            source_issue_count=len(source_issues),
            system_issue_count=len(system_issues),
            article_summary=article_summary,
        ),
        "tickers": [str(candidate["ticker"]) for candidate in preselected_candidates],
        "actionable_tickers": [
            str(candidate["ticker"]) for candidate in preselected_candidates
        ],
        "actionable_candidates": preselected_candidates,
        "broker_state_review_candidates": broker_state_review_candidates,
        "excluded_hold_candidates": excluded_hold_candidates,
        "unsupported_action_candidates": unsupported_action_candidates,
        "cap_excluded_candidates": cap_excluded_candidates,
        "judgments": judgments,
        "vetoed_candidates": vetoed_candidates,
        "source_issues": source_issues,
        "system_issues": system_issues,
        "source_provider_summary": source_provider_summary,
    }
    if provider_error is not None:
        logger.error("Sell AI brief provider failed: %s", provider_error)

    try:
        out_path = write_sell_ai_brief_report(
            report_dir=cfg.report_dir,
            artifact=artifact,
            now=_current_utc_time(),
            artifact_date=report_date,
        )
    except SellAiBriefValidationError as exc:
        logger.error("Sell AI brief validation failed: %s", exc)
        return 1
    logger.info("Sell AI brief written to: %s", out_path)
    if report_path_callback is not None:
        report_path_callback(out_path)
    if provider_error is not None:
        return 1

    try:
        maybe_upload_report_artifact(
            artifact_path=out_path,
            run_type="sell-ai-brief",
            logger=logger,
            force=upload,
        )
    except SupabaseStorageError as exc:
        logger.error("Supabase Sell AI brief upload failed: %s", exc)
        return 1
    return 0


def run_sell_ai_brief_with_result(
    *,
    sell_report_path: str,
    model_provider: str | None,
    model_name: str | None,
    model_timeout_seconds: float | None = None,
    source_provider: str | None = None,
    source_report_path: str | None = None,
    source_api_url: str | None = None,
    source_timeout_seconds: float | None = None,
    article_reader: str | None = None,
    article_reader_max_urls: int | None = None,
    article_reader_timeout_seconds: float | None = None,
    article_reader_max_excerpt_chars: int | None = None,
    report_date: str | None = None,
    upload: bool = False,
) -> SellAiBriefRunResult:
    report_paths: list[str] = []
    exit_code = run_sell_ai_brief(
        sell_report_path=sell_report_path,
        model_provider=model_provider,
        model_name=model_name,
        model_timeout_seconds=model_timeout_seconds,
        source_provider=source_provider,
        source_report_path=source_report_path,
        source_api_url=source_api_url,
        source_timeout_seconds=source_timeout_seconds,
        article_reader=article_reader,
        article_reader_max_urls=article_reader_max_urls,
        article_reader_timeout_seconds=article_reader_timeout_seconds,
        article_reader_max_excerpt_chars=article_reader_max_excerpt_chars,
        report_date=report_date,
        upload=upload,
        report_path_callback=report_paths.append,
    )
    return SellAiBriefRunResult(
        exit_code=exit_code,
        report_path=report_paths[-1] if report_paths else None,
    )


__all__ = [
    "FakeSellAiBriefProvider",
    "OpenAiSellAiBriefProvider",
    "SellAiBriefProviderError",
    "SellAiBriefRunResult",
    "run_sell_ai_brief",
    "run_sell_ai_brief_with_result",
]
