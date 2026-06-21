from __future__ import annotations

import json
import logging
import math
import os
from collections.abc import Callable, Mapping
from typing import Any

from .ai_brief_candidates import (
    AiBriefEntryCandidate,
    classify_ai_brief_entry_rows,
)
from .ai_brief_eval_common import normalize_market, resolve_entry_report_market
from .ai_brief_providers import (
    DEFAULT_MODEL_TIMEOUT_SECONDS,
    MODEL_PROVIDER_FAKE,
    MODEL_PROVIDER_OPENAI,
    PRESELECTION_LIMIT,
    AiBriefProviderContractError,
    AiBriefProviderError,
    AiBriefProviderTimeoutError,
    FakeAiBriefProvider,
    OpenAiBriefProvider,
)
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
from .config import ConfigLoadError, load_config
from .observability import current_run_id
from .report.ai_brief_report import AiBriefValidationError, write_ai_brief_report
from .report.supabase_storage import SupabaseStorageError, maybe_upload_report_artifact
from .tickers import infer_market_from_ticker

logger = logging.getLogger(__name__)

_MODEL_PROVIDER_FAKE = MODEL_PROVIDER_FAKE
_MODEL_PROVIDER_OPENAI = MODEL_PROVIDER_OPENAI
_DEFAULT_MODEL_NAME = "fake-ai-brief-v1"
_DEFAULT_MODEL_TIMEOUT_SECONDS = DEFAULT_MODEL_TIMEOUT_SECONDS
_PRESELECTION_LIMIT = PRESELECTION_LIMIT
_ALLOWED_MODEL_PROVIDERS = frozenset({_MODEL_PROVIDER_FAKE, _MODEL_PROVIDER_OPENAI})
_SUPPORTED_ENTRY_ACTIONS = frozenset({"ENTER", "REVIEW", "SKIP"})
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
_FIXED_API_SOURCE_PROVIDERS = frozenset(
    {
        SOURCE_PROVIDER_FINNHUB,
        SOURCE_PROVIDER_POLYGON_NEWS,
        SOURCE_PROVIDER_ALPHA_VANTAGE_NEWS,
        SOURCE_PROVIDER_MARKETAUX_NEWS,
        SOURCE_PROVIDER_BENZINGA_NEWS,
        SOURCE_PROVIDER_NAVER_NEWS,
    }
)


def _source_provider_retryable(source_provider: str) -> bool:
    return source_provider in _TIMEOUT_SOURCE_PROVIDERS


def _model_provider_retryable(exc: AiBriefProviderError) -> bool:
    return isinstance(exc, AiBriefProviderTimeoutError)


def _normalize_model_provider(value: str | None) -> str:
    provider = str(value or _MODEL_PROVIDER_FAKE).strip().lower()
    if provider not in _ALLOWED_MODEL_PROVIDERS:
        raise ValueError(
            f"model_provider must be one of {sorted(_ALLOWED_MODEL_PROVIDERS)}"
        )
    return provider


def _normalize_model_name(*, provider: str, value: str | None) -> str:
    model_name = str(value or _DEFAULT_MODEL_NAME).strip()
    if provider == _MODEL_PROVIDER_OPENAI:
        env_model = os.getenv("OPENAI_AI_BRIEF_MODEL")
        if (not value or model_name == _DEFAULT_MODEL_NAME) and env_model:
            model_name = env_model.strip()
        if not model_name or model_name == _DEFAULT_MODEL_NAME:
            raise ValueError(
                "--model-provider openai requires --model-name or OPENAI_AI_BRIEF_MODEL"
            )
    if not model_name:
        raise ValueError("model_name must not be empty")
    return model_name


def _read_env_float(name: str, *, error_message: str) -> float | None:
    raw = os.getenv(name)
    if raw is None or not raw.strip():
        return None
    try:
        return float(raw)
    except ValueError as exc:
        raise ValueError(error_message) from exc


def _normalize_model_timeout_seconds(value: float | None) -> float:
    if value is None:
        value = _read_env_float(
            "AI_BRIEF_MODEL_TIMEOUT_SECONDS",
            error_message="AI_BRIEF_MODEL_TIMEOUT_SECONDS must be a number",
        )
        if value is None:
            return _DEFAULT_MODEL_TIMEOUT_SECONDS
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
                "--source-timeout-seconds is only valid with "
                "a source provider chain containing http-json, finnhub, "
                "polygon-news, alpha-vantage-news, marketaux-news, "
                "benzinga-news, or naver-news"
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


def _source_chain_env_value(market: str, explicit_chain: str | None) -> str | None:
    explicit = str(explicit_chain or "").strip()
    if explicit:
        return explicit
    market_value = os.getenv(f"AI_BRIEF_SOURCE_PROVIDER_CHAIN_{market}")
    if market_value and market_value.strip():
        return market_value
    global_value = os.getenv("AI_BRIEF_SOURCE_PROVIDER_CHAIN")
    if global_value and global_value.strip():
        return global_value
    return None


def _resolve_source_provider_chain(
    *,
    target_market: str,
    normalized_source_provider: str,
    source_provider: str | None,
    source_report_path: str | None,
    source_api_url: str | None,
    source_provider_chain: str | None,
) -> tuple[str, ...]:
    configured = parse_source_provider_chain(str(source_provider_chain or "").strip())
    if configured:
        return configured
    if (
        str(source_provider or "").strip()
        or str(source_report_path or "").strip()
        or str(source_api_url or "").strip()
    ):
        return (normalized_source_provider,)
    configured = parse_source_provider_chain(
        _source_chain_env_value(target_market, None)
    )
    if configured:
        return configured
    return (normalized_source_provider,)


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
    *, report_market: object, market_override: str | None
) -> str:
    return resolve_entry_report_market(
        report_market=report_market,
        market_override=market_override,
    )


def _filter_rows_for_market(
    rows: list[dict[str, Any]], *, market: str
) -> list[dict[str, Any]]:
    filtered: list[dict[str, Any]] = []
    for row in rows:
        ticker = str(row.get("ticker") or "").strip()
        if not ticker:
            raise ValueError("entry row ticker is required")
        if infer_market_from_ticker(ticker) == market:
            filtered.append(row)
    return filtered


def _validate_supported_entry_actions(rows: list[dict[str, Any]]) -> None:
    for row in rows:
        action = str(row.get("action") or "").strip().upper()
        if action not in _SUPPORTED_ENTRY_ACTIONS:
            ticker = str(row.get("ticker") or "").strip() or "-"
            raise ValueError(
                "entry row action must be ENTER, REVIEW, or SKIP: "
                f"ticker={ticker}, action={action or '-'}"
            )


def _load_buy_enrichment(
    path: str | None,
) -> tuple[dict[str, dict[str, Any]], list[dict[str, object]]]:
    if path is None:
        return {}, []
    try:
        report = _load_json_object(path, label="buy report")
        candidates = _as_mapping_rows(report.get("candidates"), field_name="candidates")
    except ValueError as exc:
        return {}, [
            {
                "ticker": None,
                "code": "buy_report_enrichment_unavailable",
                "severity": "WARN",
                "message": str(exc),
            }
        ]

    by_ticker: dict[str, dict[str, Any]] = {}
    for candidate in candidates:
        ticker = str(candidate.get("ticker") or "").strip()
        if ticker:
            by_ticker[ticker] = candidate
    return by_ticker, []


def _extract_buy_reason_labels(candidate: Mapping[str, Any] | None) -> list[str]:
    if candidate is None:
        return []
    labels: list[str] = []
    raw_reasons = candidate.get("reasons")
    if isinstance(raw_reasons, list):
        for raw_reason in raw_reasons[:3]:
            if isinstance(raw_reason, Mapping):
                label = str(raw_reason.get("label") or "").strip()
                if label:
                    labels.append(label)
            elif isinstance(raw_reason, str) and raw_reason.strip():
                labels.append(raw_reason.strip())
    return labels


def _build_model_candidate(
    classified: AiBriefEntryCandidate, buy_candidate: Mapping[str, Any] | None
) -> dict[str, object]:
    entry = classified.entry
    ticker = str(entry.get("ticker") or "").strip()
    raw_reasons = entry.get("reasons")
    name = None
    if buy_candidate is not None:
        raw_name = buy_candidate.get("name")
        if raw_name is not None and str(raw_name).strip():
            name = str(raw_name).strip()
    row = {
        "ticker": ticker,
        "name": name,
        "action": classified.action,
        "ai_role": classified.role,
        "ai_role_reason": classified.reason,
        "entry_reasons": [
            str(reason).strip() for reason in raw_reasons if str(reason).strip()
        ]
        if isinstance(raw_reasons, list)
        else [],
        "buy_reason_labels": _extract_buy_reason_labels(buy_candidate),
        "entry_price": entry.get("entry_price"),
        "gap_pct": entry.get("gap_pct"),
        "gap_guard_pct": entry.get("gap_guard_pct"),
        "strategy_mode": entry.get("strategy_mode"),
        "pattern": entry.get("pattern"),
        "entry_state": entry.get("entry_state"),
        "sources": [],
    }
    for field_name in (
        "implementation_ready",
        "investment_readiness",
        "investment_readiness_reasons",
        "liquidity_exit_capacity",
        "liquidity_warnings",
        "downside_risk",
        "portfolio_exposure_buckets",
    ):
        if field_name in entry:
            row[field_name] = entry.get(field_name)
    return row


def _build_excluded_candidate(
    classified: AiBriefEntryCandidate,
) -> dict[str, object]:
    return {
        "ticker": classified.ticker,
        "action": classified.action,
        "reason": classified.reason,
    }


def _build_cap_excluded_candidate(candidate: Mapping[str, object]) -> dict[str, object]:
    return {
        "ticker": str(candidate["ticker"]),
        "action": str(candidate.get("action") or ""),
        "reason": f"preselection cap {_PRESELECTION_LIMIT} exceeded",
    }


def _entry_system_issues(source_report: Mapping[str, Any]) -> list[dict[str, object]]:
    raw_issues = source_report.get("system_issues")
    if not isinstance(raw_issues, list):
        return []
    issues: list[dict[str, object]] = []
    for raw_issue in raw_issues:
        message = str(raw_issue).strip()
        if not message:
            continue
        issues.append(
            {
                "ticker": None,
                "code": "source_entry_system_issue",
                "severity": "WARN",
                "message": message,
            }
        )
    return issues


def _build_summary(
    *,
    entry_count: int,
    recommendable_count: int,
    watch_count: int,
    preselected_count: int,
    recommendation_count: int,
    excluded_count: int,
    vetoed_count: int,
    cap_excluded_count: int,
    source_issue_count: int,
    system_issue_count: int,
) -> dict[str, object]:
    return {
        "entry_count": entry_count,
        "recommendable_count": recommendable_count,
        "watch_count": watch_count,
        "preselected_count": preselected_count,
        "recommendation_count": recommendation_count,
        "excluded_count": excluded_count,
        "vetoed_count": vetoed_count,
        "cap_excluded_count": cap_excluded_count,
        "source_issue_count": source_issue_count,
        "system_issue_count": system_issue_count,
    }


def _build_provider(
    *,
    model_provider: str,
    model_name: str,
    model_timeout_seconds: float,
) -> FakeAiBriefProvider | OpenAiBriefProvider:
    if model_provider == _MODEL_PROVIDER_FAKE:
        return FakeAiBriefProvider(model_name=model_name)

    api_key = str(os.getenv("OPENAI_API_KEY") or "").strip()
    if not api_key:
        raise ValueError(
            "--model-provider openai requires OPENAI_API_KEY in the environment"
        )
    return OpenAiBriefProvider(
        model_name=model_name,
        api_key=api_key,
        timeout_seconds=model_timeout_seconds,
    )


def _provider_system_issue(exc: AiBriefProviderError) -> dict[str, object]:
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


def _fallback_watch_candidate(candidate: Mapping[str, object]) -> dict[str, object]:
    ticker = str(candidate["ticker"])
    reason = str(
        candidate.get("ai_role_reason") or "entry trigger is pending re-confirmation"
    ).strip()
    sources = candidate.get("sources")
    source_rows = (
        [dict(source) for source in sources if isinstance(source, Mapping)]
        if isinstance(sources, list)
        else []
    )
    row: dict[str, object] = {
        "ticker": ticker,
        "action": "WATCH",
        "reason": reason,
        "retrigger_conditions": [
            "price must satisfy the original entry trigger again",
            "manual review must confirm source and market context",
        ],
        "sources": source_rows,
    }
    name = str(candidate.get("name") or "").strip()
    if name:
        row["name"] = name
    return row


def _fallback_watch_candidates(
    candidates: list[dict[str, object]],
) -> list[dict[str, object]]:
    return [_fallback_watch_candidate(candidate) for candidate in candidates]


def run_ai_brief(
    *,
    entry_report_path: str,
    buy_report_path: str | None,
    market: str | None,
    model_provider: str | None,
    model_name: str | None,
    model_timeout_seconds: float | None = None,
    source_provider: str | None = None,
    source_report_path: str | None = None,
    source_provider_chain: str | None = None,
    source_api_url: str | None = None,
    source_timeout_seconds: float | None = None,
    report_date: str | None = None,
    upload: bool = False,
    report_path_callback: Callable[[str], None] | None = None,
) -> int:
    run_id = current_run_id("ai-brief")
    operation = "ai-brief"
    try:
        source_api_url_input = str(source_api_url or "").strip() or None
        normalized_market = normalize_market(market)
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
    except ValueError as exc:
        logger.error(
            "%s",
            exc,
            extra={
                "event": "ai_brief_failed",
                "run_id": run_id,
                "operation": operation,
                "status": "failed",
                "stage": "normalize_inputs",
                "error_type": type(exc).__name__,
                "retryable": False,
            },
        )
        return 1

    logger.info(
        "AI brief started",
        extra={
            "event": "ai_brief_started",
            "run_id": run_id,
            "operation": operation,
            "status": "started",
            "entry_report_path": entry_report_path,
            "buy_report_path": buy_report_path,
            "market": normalized_market,
            "model_provider": normalized_model_provider,
            "model_name": normalized_model_name,
            "source_provider": normalized_source_provider,
            "source_provider_chain": source_provider_chain,
            "upload": upload,
        },
    )

    try:
        cfg = load_config()
    except ConfigLoadError as exc:
        logger.error(
            "Configuration loading failed: %s",
            exc,
            extra={
                "event": "ai_brief_failed",
                "run_id": run_id,
                "operation": operation,
                "status": "failed",
                "stage": "load_config",
                "error_type": type(exc).__name__,
                "retryable": False,
            },
        )
        return 1

    try:
        source_report = _load_json_object(entry_report_path, label="entry report")
        entry_rows = _as_mapping_rows(
            source_report.get("entries"), field_name="entries"
        )
        target_market = _resolve_target_market(
            report_market=source_report.get("market"),
            market_override=normalized_market,
        )
        resolved_source_provider_chain = _resolve_source_provider_chain(
            target_market=target_market,
            normalized_source_provider=normalized_source_provider,
            source_provider=source_provider,
            source_report_path=source_report_path,
            source_api_url=source_api_url_input,
            source_provider_chain=source_provider_chain,
        )
        normalized_source_api_url = _normalize_source_api_url(
            source_providers=resolved_source_provider_chain,
            value=source_api_url_input,
        )
        normalized_source_timeout_seconds = _normalize_source_timeout_seconds(
            source_providers=resolved_source_provider_chain,
            value=source_timeout_seconds,
        )
        target_rows = _filter_rows_for_market(entry_rows, market=target_market)
        _validate_supported_entry_actions(target_rows)
        buy_enrichment, enrichment_issues = _load_buy_enrichment(buy_report_path)
    except ValueError as exc:
        logger.error(
            "%s",
            exc,
            extra={
                "event": "ai_brief_failed",
                "run_id": run_id,
                "operation": operation,
                "status": "failed",
                "stage": "load_entry_report",
                "entry_report_path": entry_report_path,
                "buy_report_path": buy_report_path,
                "error_type": type(exc).__name__,
                "retryable": False,
            },
        )
        return 1

    logger.info(
        "AI brief entry report loaded",
        extra={
            "event": "ai_brief_entry_report_loaded",
            "run_id": run_id,
            "operation": operation,
            "status": "success",
            "entry_report_path": entry_report_path,
            "buy_report_path": buy_report_path,
            "market": target_market,
            "entry_count": len(target_rows),
            "candidate_count": len(entry_rows),
            "enrichment_issue_count": len(enrichment_issues),
        },
    )

    classified_rows = classify_ai_brief_entry_rows(target_rows)
    eligible_candidates = [
        _build_model_candidate(classified, buy_enrichment.get(classified.ticker))
        for classified in classified_rows.recommendable
    ]
    watch_candidates = [
        _build_model_candidate(classified, buy_enrichment.get(classified.ticker))
        for classified in classified_rows.watch_only
    ]
    excluded_candidates = [
        _build_excluded_candidate(classified) for classified in classified_rows.excluded
    ]

    preselected_candidates = eligible_candidates[:_PRESELECTION_LIMIT]
    cap_excluded_candidates = [
        _build_cap_excluded_candidate(candidate)
        for candidate in eligible_candidates[_PRESELECTION_LIMIT:]
    ]

    system_issues = [*_entry_system_issues(source_report), *enrichment_issues]
    source_provider_issues: list[dict[str, object]] = []
    source_provider_summary: dict[str, object] = {}
    source_universe_candidates = [*eligible_candidates, *watch_candidates]
    source_universe_tickers = {
        str(candidate["ticker"]) for candidate in source_universe_candidates
    }
    recommendable_tickers = {
        str(candidate["ticker"]) for candidate in eligible_candidates
    }
    watch_ticker_set = {str(candidate["ticker"]) for candidate in watch_candidates}
    ticker_names = {
        str(candidate["ticker"]): str(candidate.get("name") or "").strip()
        for candidate in source_universe_candidates
        if str(candidate.get("name") or "").strip()
    }
    try:
        source_chain_result = load_ai_brief_source_chain(
            source_providers=resolved_source_provider_chain,
            source_report_path=source_report_path,
            source_api_url=normalized_source_api_url,
            source_timeout_seconds=normalized_source_timeout_seconds,
            source_universe_tickers=source_universe_tickers,
            recommendable_tickers=recommendable_tickers,
            watch_tickers=watch_ticker_set,
            ticker_names=ticker_names,
        )
        preselected_candidates = _attach_candidate_sources(
            preselected_candidates,
            source_chain_result.sources_by_ticker,
        )
        watch_candidates = _attach_candidate_sources(
            watch_candidates,
            source_chain_result.sources_by_ticker,
        )
        source_provider_issues = source_chain_result.source_issues
        system_issues.extend(source_chain_result.system_issues)
        source_provider_summary = source_chain_result.summary
        provider_summaries = source_provider_summary.get("providers")
        failed_provider = None
        if isinstance(provider_summaries, list):
            failed_provider = next(
                (
                    provider
                    for provider in provider_summaries
                    if isinstance(provider, Mapping)
                    and provider.get("status") == "failed"
                ),
                None,
            )
        if isinstance(failed_provider, Mapping):
            failed_provider_name = str(failed_provider.get("provider") or "")
            logger.error(
                "AI brief source provider failed",
                extra={
                    "event": "ai_brief_source_provider_failed",
                    "run_id": run_id,
                    "operation": operation,
                    "status": "degraded",
                    "source_provider": failed_provider_name,
                    "dependency": failed_provider_name,
                    "market": target_market,
                    "ticker_count": len(source_universe_candidates),
                    "source_report_path": source_report_path,
                    "error_type": "AiBriefSourceProviderError",
                    "retryable": _source_provider_retryable(failed_provider_name),
                },
            )
        logger.info(
            "AI brief source provider completed",
            extra={
                "event": "ai_brief_source_provider_completed",
                "run_id": run_id,
                "operation": operation,
                "status": "success",
                "source_provider": normalized_source_provider,
                "source_provider_chain": list(resolved_source_provider_chain),
                "dependency": ",".join(resolved_source_provider_chain),
                "market": target_market,
                "ticker_count": len(source_universe_candidates),
                "source_count": sum(
                    len(sources)
                    for sources in source_chain_result.sources_by_ticker.values()
                ),
                "source_issue_count": len(source_provider_issues),
            },
        )
    except AiBriefSourceProviderError as exc:
        logger.error(
            "AI brief source provider failed: %s",
            exc,
            extra={
                "event": "ai_brief_source_provider_failed",
                "run_id": run_id,
                "operation": operation,
                "status": "degraded",
                "source_provider": normalized_source_provider,
                "source_provider_chain": list(resolved_source_provider_chain),
                "dependency": ",".join(resolved_source_provider_chain),
                "market": target_market,
                "ticker_count": len(source_universe_candidates),
                "source_report_path": source_report_path,
                "error_type": type(exc).__name__,
                "retryable": any(
                    _source_provider_retryable(provider)
                    for provider in resolved_source_provider_chain
                ),
            },
        )
        preselected_candidates = _attach_candidate_sources(preselected_candidates, {})
        watch_candidates = _attach_candidate_sources(watch_candidates, {})
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
                "recommendable_total": len(recommendable_tickers),
                "watch_covered": 0,
                "watch_total": len(watch_ticker_set),
            },
        }
    except ValueError as exc:
        logger.error(
            "%s",
            exc,
            extra={
                "event": "ai_brief_failed",
                "run_id": run_id,
                "operation": operation,
                "status": "failed",
                "stage": "load_source_chain",
                "source_provider": normalized_source_provider,
                "source_provider_chain": list(resolved_source_provider_chain),
                "market": target_market,
                "error_type": type(exc).__name__,
                "retryable": False,
            },
        )
        return 1

    try:
        provider = _build_provider(
            model_provider=normalized_model_provider,
            model_name=normalized_model_name,
            model_timeout_seconds=normalized_model_timeout_seconds,
        )
        provider_result = provider.build_recommendations(
            recommendable_candidates=preselected_candidates,
            watch_candidates=watch_candidates,
        )
        recommendations = provider_result.recommendations
        source_issues = [*source_provider_issues, *provider_result.source_issues]
        vetoed_candidates = provider_result.vetoed_candidates
        model_watch_candidates = provider_result.watch_candidates
        logger.info(
            "AI brief model provider completed",
            extra={
                "event": "ai_brief_model_provider_completed",
                "run_id": run_id,
                "operation": operation,
                "status": "success",
                "model_provider": normalized_model_provider,
                "dependency": normalized_model_provider,
                "model_name": normalized_model_name,
                "market": target_market,
                "ticker_count": len(preselected_candidates),
                "watch_count": len(watch_candidates),
                "recommendation_count": len(recommendations),
                "vetoed_count": len(vetoed_candidates),
                "source_issue_count": len(source_issues),
            },
        )
    except AiBriefProviderError as exc:
        logger.error(
            "AI brief provider failed: %s",
            exc,
            extra={
                "event": "ai_brief_model_provider_failed",
                "run_id": run_id,
                "operation": operation,
                "status": "degraded",
                "model_provider": normalized_model_provider,
                "dependency": normalized_model_provider,
                "model_name": normalized_model_name,
                "market": target_market,
                "ticker_count": len(preselected_candidates),
                "error_type": type(exc).__name__,
                "retryable": _model_provider_retryable(exc),
            },
        )
        recommendations = []
        source_issues = source_provider_issues
        vetoed_candidates = []
        model_watch_candidates = _fallback_watch_candidates(watch_candidates)
        system_issues.append(_provider_system_issue(exc))
    except ValueError as exc:
        logger.error(
            "%s",
            exc,
            extra={
                "event": "ai_brief_failed",
                "run_id": run_id,
                "operation": operation,
                "status": "failed",
                "stage": "build_model_provider",
                "model_provider": normalized_model_provider,
                "dependency": normalized_model_provider,
                "model_name": normalized_model_name,
                "error_type": type(exc).__name__,
                "retryable": False,
            },
        )
        return 1

    artifact = {
        "source_entry_report": os.path.basename(entry_report_path),
        "source_buy_report": (
            os.path.basename(buy_report_path)
            if buy_report_path
            else source_report.get("source_buy_report")
        ),
        "market": target_market,
        "model_provider": normalized_model_provider,
        "model_name": normalized_model_name,
        "summary": _build_summary(
            entry_count=len(target_rows),
            recommendable_count=len(eligible_candidates),
            watch_count=len(watch_candidates),
            preselected_count=len(preselected_candidates),
            recommendation_count=len(recommendations),
            excluded_count=len(excluded_candidates),
            vetoed_count=len(vetoed_candidates),
            cap_excluded_count=len(cap_excluded_candidates),
            source_issue_count=len(source_issues),
            system_issue_count=len(system_issues),
        ),
        "recommendations": recommendations,
        "excluded_candidates": excluded_candidates,
        "vetoed_candidates": vetoed_candidates,
        "watch_candidates": model_watch_candidates,
        "cap_excluded_candidates": cap_excluded_candidates,
        "source_issues": source_issues,
        "system_issues": system_issues,
        "eligible_tickers": [
            str(candidate["ticker"]) for candidate in preselected_candidates
        ],
        "watch_tickers": [str(candidate["ticker"]) for candidate in watch_candidates],
        "source_provider_summary": source_provider_summary,
    }

    try:
        out_path = write_ai_brief_report(
            report_dir=cfg.report_dir,
            artifact=artifact,
            artifact_date=report_date,
        )
    except AiBriefValidationError as exc:
        logger.error(
            "AI brief validation failed: %s",
            exc,
            extra={
                "event": "ai_brief_failed",
                "run_id": run_id,
                "operation": operation,
                "status": "failed",
                "stage": "write_report",
                "market": target_market,
                "report_date": report_date,
                "error_type": type(exc).__name__,
                "retryable": False,
            },
        )
        return 1

    logger.info(
        "AI brief written to: %s",
        out_path,
        extra={
            "event": "ai_brief_report_written",
            "run_id": run_id,
            "operation": operation,
            "status": "success",
            "market": target_market,
            "report_path": out_path,
            "report_date": report_date,
            "recommendation_count": len(recommendations),
            "source_issue_count": len(source_issues),
            "system_issue_count": len(system_issues),
        },
    )
    if report_path_callback is not None:
        report_path_callback(out_path)
    try:
        uploaded_key = maybe_upload_report_artifact(
            artifact_path=out_path,
            run_type="ai-brief",
            logger=logger,
            force=upload,
        )
    except SupabaseStorageError as exc:
        logger.error(
            "Supabase AI brief upload failed: %s",
            exc,
            extra={
                "event": "ai_brief_upload_failed",
                "run_id": run_id,
                "operation": operation,
                "status": "failed",
                "dependency": "supabase",
                "market": target_market,
                "report_path": out_path,
                "error_type": type(exc).__name__,
                "retryable": True,
            },
        )
        return 1
    else:
        if uploaded_key:
            logger.info(
                "AI brief uploaded to Supabase: %s",
                uploaded_key,
                extra={
                    "event": "ai_brief_upload_completed",
                    "run_id": run_id,
                    "operation": operation,
                    "status": "success",
                    "dependency": "supabase",
                    "market": target_market,
                    "report_path": out_path,
                    "storage_key": uploaded_key,
                },
            )
    completed_status = "warning" if system_issues else "success"
    completed_extra = {
        "event": "ai_brief_completed",
        "run_id": run_id,
        "operation": operation,
        "status": completed_status,
        "market": target_market,
        "report_path": out_path,
        "recommendation_count": len(recommendations),
        "source_issue_count": len(source_issues),
        "system_issue_count": len(system_issues),
    }
    if source_issues:
        logger.warning(
            "AI brief completed with source issues (%s)",
            len(source_issues),
            extra=completed_extra,
        )
    elif system_issues:
        logger.warning(
            "AI brief completed with system issues (%s)",
            len(system_issues),
            extra=completed_extra,
        )
    else:
        logger.info("AI brief completed", extra=completed_extra)
    return 0


__all__ = [
    "AiBriefProviderContractError",
    "AiBriefProviderError",
    "AiBriefProviderTimeoutError",
    "FakeAiBriefProvider",
    "OpenAiBriefProvider",
    "run_ai_brief",
]
