from __future__ import annotations

import json
import logging
import math
import os
from collections.abc import Mapping
from typing import Any

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
from .ai_brief_sources import (
    DEFAULT_SOURCE_TIMEOUT_SECONDS,
    SOURCE_PROVIDER_FINNHUB,
    SOURCE_PROVIDER_HTTP_JSON,
    SOURCE_PROVIDER_LOCAL_JSON,
    SOURCE_PROVIDER_NONE,
    AiBriefSourceProviderError,
    load_ai_brief_sources,
)
from .config import ConfigLoadError, load_config
from .report.ai_brief_report import AiBriefValidationError, write_ai_brief_report
from .report.supabase_storage import SupabaseStorageError, maybe_upload_report_artifact
from .tickers import infer_market_from_ticker

logger = logging.getLogger(__name__)

_MODEL_PROVIDER_FAKE = MODEL_PROVIDER_FAKE
_MODEL_PROVIDER_OPENAI = MODEL_PROVIDER_OPENAI
_DEFAULT_MODEL_NAME = "fake-ai-brief-v1"
_DEFAULT_MODEL_TIMEOUT_SECONDS = DEFAULT_MODEL_TIMEOUT_SECONDS
_PRESELECTION_LIMIT = PRESELECTION_LIMIT
_ALLOWED_MARKETS = frozenset({"KR", "US"})
_ALLOWED_MODEL_PROVIDERS = frozenset({_MODEL_PROVIDER_FAKE, _MODEL_PROVIDER_OPENAI})
_ALLOWED_SOURCE_PROVIDERS = frozenset(
    {
        SOURCE_PROVIDER_NONE,
        SOURCE_PROVIDER_LOCAL_JSON,
        SOURCE_PROVIDER_HTTP_JSON,
        SOURCE_PROVIDER_FINNHUB,
    }
)
_TIMEOUT_SOURCE_PROVIDERS = frozenset(
    {SOURCE_PROVIDER_HTTP_JSON, SOURCE_PROVIDER_FINNHUB}
)


def _normalize_market(value: str | None) -> str | None:
    if value is None:
        return None
    market = value.strip().upper()
    if not market:
        return None
    if market not in _ALLOWED_MARKETS:
        raise ValueError("market must be KR or US")
    return market


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


def _normalize_model_timeout_seconds(value: float | None) -> float:
    if value is None:
        raw = os.getenv("AI_BRIEF_MODEL_TIMEOUT_SECONDS")
        if raw is None or not raw.strip():
            return _DEFAULT_MODEL_TIMEOUT_SECONDS
        try:
            value = float(raw)
        except ValueError as exc:
            raise ValueError("AI_BRIEF_MODEL_TIMEOUT_SECONDS must be a number") from exc
    if value <= 0:
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
    if provider == SOURCE_PROVIDER_FINNHUB and source_report_path:
        raise ValueError("--source-provider finnhub does not use --source-report")
    if provider == SOURCE_PROVIDER_FINNHUB and source_api_url:
        raise ValueError("--source-provider finnhub does not use --source-api-url")
    return provider


def _normalize_source_api_url(*, provider: str, value: str | None) -> str | None:
    if provider != SOURCE_PROVIDER_HTTP_JSON:
        return None
    api_url = str(value or os.getenv("AI_BRIEF_SOURCE_API_URL") or "").strip()
    if not api_url:
        raise ValueError(
            "--source-provider http-json requires --source-api-url or "
            "AI_BRIEF_SOURCE_API_URL"
        )
    if "\n" in api_url or "\r" in api_url:
        raise ValueError("source_api_url must be a single-line value")
    return api_url


def _normalize_source_timeout_seconds(
    *, provider: str, value: float | None
) -> float | None:
    if provider not in _TIMEOUT_SOURCE_PROVIDERS:
        if value is not None:
            raise ValueError(
                "--source-timeout-seconds is only valid with "
                "--source-provider http-json or finnhub"
            )
        return None
    if value is None:
        raw = os.getenv("AI_BRIEF_SOURCE_TIMEOUT_SECONDS")
        if raw is None or not raw.strip():
            return DEFAULT_SOURCE_TIMEOUT_SECONDS
        try:
            value = float(raw)
        except ValueError as exc:
            raise ValueError(
                "AI_BRIEF_SOURCE_TIMEOUT_SECONDS must be a number"
            ) from exc
    if not math.isfinite(value) or value <= 0:
        raise ValueError("source_timeout_seconds must be positive")
    return float(value)


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
    market = str(report_market or "").strip().upper()
    if market == "MIXED":
        if market_override is None:
            raise ValueError("MIXED entry report requires --market KR or --market US")
        return market_override
    if market not in _ALLOWED_MARKETS:
        raise ValueError("entry report market must be KR, US, or MIXED")
    if market_override is not None and market_override != market:
        raise ValueError(
            f"--market {market_override} does not match entry report {market}"
        )
    return market


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
    entry: Mapping[str, Any], buy_candidate: Mapping[str, Any] | None
) -> dict[str, object]:
    ticker = str(entry.get("ticker") or "").strip()
    name = None
    if buy_candidate is not None:
        raw_name = buy_candidate.get("name")
        if raw_name is not None and str(raw_name).strip():
            name = str(raw_name).strip()
    return {
        "ticker": ticker,
        "name": name,
        "entry_reasons": [
            str(reason).strip()
            for reason in entry.get("reasons", [])
            if str(reason).strip()
        ]
        if isinstance(entry.get("reasons"), list)
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


def _build_excluded_candidate(entry: Mapping[str, Any]) -> dict[str, object]:
    ticker = str(entry.get("ticker") or "").strip()
    action = str(entry.get("action") or "").strip().upper()
    return {
        "ticker": ticker,
        "action": action,
        "reason": f"entry report action was {action}",
    }


def _build_cap_excluded_candidate(candidate: Mapping[str, object]) -> dict[str, object]:
    return {
        "ticker": str(candidate["ticker"]),
        "action": "ENTER",
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
    source_api_url: str | None = None,
    source_timeout_seconds: float | None = None,
    upload: bool = False,
) -> int:
    try:
        source_api_url_input = str(source_api_url or "").strip() or None
        normalized_market = _normalize_market(market)
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
        normalized_source_api_url = _normalize_source_api_url(
            provider=normalized_source_provider,
            value=source_api_url_input,
        )
        normalized_source_timeout_seconds = _normalize_source_timeout_seconds(
            provider=normalized_source_provider,
            value=source_timeout_seconds,
        )
    except ValueError as exc:
        logger.error("%s", exc)
        return 1

    try:
        cfg = load_config()
    except ConfigLoadError as exc:
        logger.error("Configuration loading failed: %s", exc)
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
        target_rows = _filter_rows_for_market(entry_rows, market=target_market)
        buy_enrichment, enrichment_issues = _load_buy_enrichment(buy_report_path)
    except ValueError as exc:
        logger.error("%s", exc)
        return 1

    eligible_candidates: list[dict[str, object]] = []
    excluded_candidates: list[dict[str, object]] = []
    for entry in target_rows:
        ticker = str(entry.get("ticker") or "").strip()
        action = str(entry.get("action") or "").strip().upper()
        if action == "ENTER":
            eligible_candidates.append(
                _build_model_candidate(entry, buy_enrichment.get(ticker))
            )
        elif action in {"REVIEW", "SKIP"}:
            excluded_candidates.append(_build_excluded_candidate(entry))
        else:
            logger.error("entry row action must be ENTER, REVIEW, or SKIP")
            return 1

    preselected_candidates = eligible_candidates[:_PRESELECTION_LIMIT]
    cap_excluded_candidates = [
        _build_cap_excluded_candidate(candidate)
        for candidate in eligible_candidates[_PRESELECTION_LIMIT:]
    ]

    system_issues = [*_entry_system_issues(source_report), *enrichment_issues]
    source_provider_issues: list[dict[str, object]] = []
    try:
        source_provider_result = load_ai_brief_sources(
            source_provider=normalized_source_provider,
            source_report_path=source_report_path,
            source_api_url=normalized_source_api_url,
            source_timeout_seconds=normalized_source_timeout_seconds,
            eligible_tickers={
                str(candidate["ticker"]) for candidate in preselected_candidates
            },
        )
        preselected_candidates = _attach_candidate_sources(
            preselected_candidates,
            source_provider_result.sources_by_ticker,
        )
        source_provider_issues = source_provider_result.source_issues
    except AiBriefSourceProviderError as exc:
        logger.error("AI brief source provider failed: %s", exc)
        preselected_candidates = _attach_candidate_sources(preselected_candidates, {})
        system_issues.append(_source_provider_system_issue(exc))

    try:
        provider = _build_provider(
            model_provider=normalized_model_provider,
            model_name=normalized_model_name,
            model_timeout_seconds=normalized_model_timeout_seconds,
        )
        provider_result = provider.build_recommendations(
            candidates=preselected_candidates
        )
        recommendations = provider_result.recommendations
        source_issues = [*source_provider_issues, *provider_result.source_issues]
        vetoed_candidates = provider_result.vetoed_candidates
    except AiBriefProviderError as exc:
        logger.error("AI brief provider failed: %s", exc)
        recommendations = []
        source_issues = source_provider_issues
        vetoed_candidates = []
        system_issues.append(_provider_system_issue(exc))
    except ValueError as exc:
        logger.error("%s", exc)
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
        "cap_excluded_candidates": cap_excluded_candidates,
        "source_issues": source_issues,
        "system_issues": system_issues,
        "eligible_tickers": [
            str(candidate["ticker"]) for candidate in preselected_candidates
        ],
    }

    try:
        out_path = write_ai_brief_report(
            report_dir=cfg.report_dir,
            artifact=artifact,
        )
    except AiBriefValidationError as exc:
        logger.error("AI brief validation failed: %s", exc)
        return 1

    logger.info("AI brief written to: %s", out_path)
    try:
        uploaded_key = maybe_upload_report_artifact(
            artifact_path=out_path,
            run_type="ai-brief",
            logger=logger,
            force=upload,
        )
    except SupabaseStorageError as exc:
        logger.error("Supabase AI brief upload failed: %s", exc)
        return 1
    else:
        if uploaded_key:
            logger.info("AI brief uploaded to Supabase: %s", uploaded_key)
    if source_issues:
        logger.warning("AI brief completed with source issues (%s)", len(source_issues))
    return 0


__all__ = [
    "AiBriefProviderContractError",
    "AiBriefProviderError",
    "AiBriefProviderTimeoutError",
    "FakeAiBriefProvider",
    "OpenAiBriefProvider",
    "run_ai_brief",
]
