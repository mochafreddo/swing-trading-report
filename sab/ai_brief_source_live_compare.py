from __future__ import annotations

import datetime as dt
import json
import math
import os
import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .ai_brief_source_eval import compare_ai_brief_source_reports
from .ai_brief_sources import (
    SOURCE_PROVIDER_ALPHA_VANTAGE_NEWS,
    SOURCE_PROVIDER_BENZINGA_NEWS,
    SOURCE_PROVIDER_FINNHUB,
    SOURCE_PROVIDER_HTTP_JSON,
    SOURCE_PROVIDER_MARKETAUX_NEWS,
    SOURCE_PROVIDER_NAVER_NEWS,
    SOURCE_PROVIDER_POLYGON_NEWS,
    SOURCE_REPORT_SCHEMA,
    SOURCE_REPORT_TYPE,
    AiBriefSourceProviderError,
    AiBriefSourceProviderResult,
    load_ai_brief_sources,
)
from .tickers import infer_market_from_ticker
from .utils.atomic_io import atomic_write_json

_ALLOWED_PROVIDER_LABEL_RE = re.compile(r"^[A-Za-z0-9_.-]+$")
_LIVE_SOURCE_PROVIDERS = frozenset(
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
_ALLOWED_MARKETS = frozenset({"KR", "US"})


@dataclass(frozen=True)
class AiBriefLiveSourceProviderSpec:
    label: str
    provider: str
    source_api_url: str | None = None


@dataclass(frozen=True)
class AiBriefLiveSourceReport:
    label: str
    provider: str
    path: str
    status: str
    source_count: int
    issue_count: int

    def to_dict(self) -> dict[str, object]:
        return {
            "label": self.label,
            "provider": self.provider,
            "path": self.path,
            "status": self.status,
            "source_count": self.source_count,
            "issue_count": self.issue_count,
        }


@dataclass(frozen=True)
class _CapturedSourceReport:
    payload: dict[str, object]
    status: str
    source_count: int
    issue_count: int


@dataclass(frozen=True)
class AiBriefLiveSourceCompareResult:
    status: str
    summary: dict[str, object]
    reports: list[dict[str, object]]
    source_reports: list[AiBriefLiveSourceReport]

    def to_dict(self) -> dict[str, object]:
        return {
            "status": self.status,
            "summary": self.summary,
            "reports": self.reports,
            "source_reports": [
                source_report.to_dict() for source_report in self.source_reports
            ],
        }


def parse_live_source_provider_specs(
    *,
    provider_values: Sequence[str],
    source_api_url_values: Sequence[str] | None = None,
) -> list[AiBriefLiveSourceProviderSpec]:
    if len(provider_values) < 2:
        raise ValueError("--provider requires at least two LABEL=PROVIDER values")
    source_api_url_values = source_api_url_values or []
    raw_source_api_urls = _parse_labeled_values(
        source_api_url_values,
        option_name="--source-api-url",
    )

    specs: list[AiBriefLiveSourceProviderSpec] = []
    seen_label_keys: set[str] = set()
    for raw_value in provider_values:
        label, provider = _parse_labeled_value(raw_value, option_name="--provider")
        provider = provider.lower()
        label_key = label.casefold()
        if label_key in seen_label_keys:
            raise ValueError(f"duplicate --provider label {label!r}")
        if provider not in _LIVE_SOURCE_PROVIDERS:
            raise ValueError(
                "provider must be one of "
                f"{sorted(_LIVE_SOURCE_PROVIDERS)}; got {provider!r}"
            )
        seen_label_keys.add(label_key)
        specs.append(
            AiBriefLiveSourceProviderSpec(
                label=label,
                provider=provider,
                source_api_url=raw_source_api_urls.get(label),
            )
        )

    for label in raw_source_api_urls:
        matching_spec = next((spec for spec in specs if spec.label == label), None)
        if matching_spec is None:
            raise ValueError(f"--source-api-url label {label!r} is unknown")
        if matching_spec.provider != SOURCE_PROVIDER_HTTP_JSON:
            raise ValueError(
                "--source-api-url can only be used with http-json providers"
            )

    return _resolve_http_json_source_api_urls(specs)


def compare_ai_brief_live_sources(
    *,
    entry_report_path: str,
    provider_specs: Sequence[AiBriefLiveSourceProviderSpec],
    buy_report_path: str | None = None,
    market: str | None = None,
    source_timeout_seconds: float | None = None,
    minimum_coverage_ratio: float = 1.0,
    now: dt.datetime | None = None,
    output_dir: str | None = None,
) -> AiBriefLiveSourceCompareResult:
    if minimum_coverage_ratio < 0 or minimum_coverage_ratio > 1:
        raise ValueError("minimum_coverage_ratio must be between 0 and 1")
    resolved_specs = _validate_provider_specs(provider_specs)
    normalized_source_timeout_seconds = _normalize_source_timeout_seconds(
        source_timeout_seconds
    )
    resolved_now = now or dt.datetime.now().astimezone()
    normalized_market = _normalize_market(market)
    eligible_tickers = _load_eligible_tickers(
        entry_report_path,
        market=normalized_market,
    )
    ticker_names = (
        _load_buy_ticker_names(
            buy_report_path,
            eligible_tickers=eligible_tickers,
        )
        if eligible_tickers
        else {}
    )
    output_path = _resolve_output_dir(
        entry_report_path=entry_report_path,
        output_dir=output_dir,
    )

    source_reports: list[AiBriefLiveSourceReport] = []
    source_report_paths: dict[str, str] = {}
    for spec in resolved_specs:
        captured = (
            _capture_source_report(
                spec=spec,
                eligible_tickers=eligible_tickers,
                ticker_names=ticker_names,
                source_timeout_seconds=normalized_source_timeout_seconds,
                generated_at=resolved_now,
            )
            if eligible_tickers
            else _no_eligible_tickers_source_report_capture(
                spec=spec,
                generated_at=resolved_now,
            )
        )
        report_path = output_path / f"{spec.label}.sources.json"
        atomic_write_json(
            report_path.as_posix(),
            captured.payload,
            ensure_ascii=False,
            indent=2,
        )
        source_reports.append(
            AiBriefLiveSourceReport(
                label=spec.label,
                provider=spec.provider,
                path=report_path.as_posix(),
                status=captured.status,
                source_count=captured.source_count,
                issue_count=captured.issue_count,
            )
        )
        source_report_paths[spec.label] = report_path.as_posix()

    compare_result = compare_ai_brief_source_reports(
        entry_report_path=entry_report_path,
        source_reports=source_report_paths,
        market=market,
        minimum_coverage_ratio=minimum_coverage_ratio,
        now=resolved_now,
    )
    return AiBriefLiveSourceCompareResult(
        status=compare_result.status,
        summary=compare_result.summary,
        reports=compare_result.reports,
        source_reports=source_reports,
    )


def _no_eligible_tickers_source_report_capture(
    *,
    spec: AiBriefLiveSourceProviderSpec,
    generated_at: dt.datetime,
) -> _CapturedSourceReport:
    return _source_report_capture(
        provider_result=AiBriefSourceProviderResult(),
        label=spec.label,
        provider=spec.provider,
        generated_at=generated_at,
        forced_status="FAIL",
        extra_issues=[
            {
                "ticker": None,
                "code": "entry_report_no_eligible_tickers",
                "severity": "ERROR",
                "message": "entry report contains no ENTER candidates to compare",
            }
        ],
    )


def _capture_source_report(
    *,
    spec: AiBriefLiveSourceProviderSpec,
    eligible_tickers: set[str],
    ticker_names: Mapping[str, str],
    source_timeout_seconds: float | None,
    generated_at: dt.datetime,
) -> _CapturedSourceReport:
    try:
        provider_result = load_ai_brief_sources(
            source_provider=spec.provider,
            source_report_path=None,
            source_api_url=spec.source_api_url,
            source_timeout_seconds=source_timeout_seconds,
            eligible_tickers=eligible_tickers,
            ticker_names=ticker_names,
            now=generated_at,
        )
        return _source_report_capture(
            provider_result=provider_result,
            label=spec.label,
            provider=spec.provider,
            generated_at=generated_at,
        )
    except AiBriefSourceProviderError as exc:
        return _source_report_capture(
            provider_result=AiBriefSourceProviderResult(),
            label=spec.label,
            provider=spec.provider,
            generated_at=generated_at,
            forced_status="FAIL",
            extra_issues=[
                {
                    "ticker": None,
                    "code": exc.code,
                    "severity": "ERROR",
                    "message": str(exc),
                }
            ],
        )


def _source_report_capture(
    *,
    provider_result: AiBriefSourceProviderResult,
    label: str,
    provider: str,
    generated_at: dt.datetime,
    forced_status: str | None = None,
    extra_issues: list[dict[str, object]] | None = None,
) -> _CapturedSourceReport:
    sources = _source_rows(provider_result.sources_by_ticker)
    issues = [*provider_result.source_issues, *(extra_issues or [])]
    covered_tickers = sorted({str(source["ticker"]) for source in sources})
    status = forced_status or ("WARN" if issues else "PASS")
    payload: dict[str, object] = {
        "schema": SOURCE_REPORT_SCHEMA,
        "type": SOURCE_REPORT_TYPE,
        "generated_at": generated_at.isoformat(),
        "status": status,
        "provider": provider,
        "label": label,
        "summary": {
            "source_count": len(sources),
            "covered_ticker_count": len(covered_tickers),
            "covered_tickers": covered_tickers,
            "issue_count": len(issues),
        },
        "sources": sources,
        "issues": issues,
    }
    return _CapturedSourceReport(
        payload=payload,
        status=status,
        source_count=len(sources),
        issue_count=len(issues),
    )


def _source_rows(
    sources_by_ticker: Mapping[str, list[dict[str, object]]],
) -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    for ticker in sorted(sources_by_ticker):
        for source in sources_by_ticker[ticker]:
            rows.append(
                {
                    "ticker": ticker,
                    "title": str(source.get("title") or "").strip(),
                    "url": str(source.get("url") or "").strip(),
                    "published_at": str(source.get("published_at") or "").strip(),
                }
            )
    return rows


def _validate_provider_specs(
    provider_specs: Sequence[AiBriefLiveSourceProviderSpec],
) -> list[AiBriefLiveSourceProviderSpec]:
    if len(provider_specs) < 2:
        raise ValueError("provider_specs must contain at least two providers")
    seen_label_keys: set[str] = set()
    normalized_specs: list[AiBriefLiveSourceProviderSpec] = []
    for spec in provider_specs:
        label = _normalize_label(spec.label, option_name="provider_specs")
        provider = str(spec.provider or "").strip().lower()
        label_key = label.casefold()
        if label_key in seen_label_keys:
            raise ValueError(f"duplicate provider label {label!r}")
        if provider not in _LIVE_SOURCE_PROVIDERS:
            raise ValueError(
                f"provider must be one of {sorted(_LIVE_SOURCE_PROVIDERS)}"
            )
        seen_label_keys.add(label_key)
        normalized_specs.append(
            AiBriefLiveSourceProviderSpec(
                label=label,
                provider=provider,
                source_api_url=_normalize_optional_url(spec.source_api_url),
            )
        )
    return _resolve_http_json_source_api_urls(normalized_specs)


def _resolve_http_json_source_api_urls(
    specs: Sequence[AiBriefLiveSourceProviderSpec],
) -> list[AiBriefLiveSourceProviderSpec]:
    missing_http_specs = [
        spec
        for spec in specs
        if spec.provider == SOURCE_PROVIDER_HTTP_JSON and spec.source_api_url is None
    ]
    if not missing_http_specs:
        return list(specs)
    env_source_api_url = _normalize_optional_url(os.getenv("AI_BRIEF_SOURCE_API_URL"))
    if len(missing_http_specs) == 1 and env_source_api_url is not None:
        missing_label = missing_http_specs[0].label
        return [
            AiBriefLiveSourceProviderSpec(
                label=spec.label,
                provider=spec.provider,
                source_api_url=env_source_api_url
                if spec.label == missing_label
                else spec.source_api_url,
            )
            for spec in specs
        ]
    raise ValueError(
        "http-json providers require --source-api-url LABEL=URL or "
        "AI_BRIEF_SOURCE_API_URL when exactly one http-json provider is missing a URL"
    )


def _parse_labeled_values(
    values: Sequence[str],
    *,
    option_name: str,
) -> dict[str, str]:
    parsed: dict[str, str] = {}
    seen_label_keys: set[str] = set()
    for raw_value in values:
        label, value = _parse_labeled_value(raw_value, option_name=option_name)
        label_key = label.casefold()
        if label_key in seen_label_keys:
            raise ValueError(f"duplicate {option_name} label {label!r}")
        seen_label_keys.add(label_key)
        parsed[label] = value
    return parsed


def _parse_labeled_value(raw_value: str, *, option_name: str) -> tuple[str, str]:
    label, separator, value = str(raw_value or "").partition("=")
    if not separator:
        raise ValueError(f"{option_name} must use LABEL=VALUE")
    label = _normalize_label(label, option_name=option_name)
    value = value.strip()
    if not value:
        raise ValueError(f"{option_name} value must not be empty")
    if "\n" in value or "\r" in value:
        raise ValueError(f"{option_name} value must be single-line")
    return label, value


def _normalize_label(value: str, *, option_name: str) -> str:
    label = str(value or "").strip()
    if not label or not _ALLOWED_PROVIDER_LABEL_RE.fullmatch(label):
        raise ValueError(f"{option_name} label must match [A-Za-z0-9_.-]+")
    return label


def _normalize_optional_url(value: object) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    if not text:
        return None
    if "\n" in text or "\r" in text:
        raise ValueError("source_api_url must be single-line")
    return text


def _normalize_source_timeout_seconds(value: float | None) -> float | None:
    if value is None:
        return None
    if not math.isfinite(value) or value <= 0:
        raise ValueError("source_timeout_seconds must be positive")
    return float(value)


def _resolve_output_dir(*, entry_report_path: str, output_dir: str | None) -> Path:
    if output_dir is not None and str(output_dir).strip():
        return Path(output_dir)
    return Path(entry_report_path).parent / "ai-brief-source-live-compare"


def _load_json_object(path: str, *, label: str) -> Mapping[str, Any]:
    try:
        with open(path, encoding="utf-8") as fp:
            payload = json.load(fp)
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(f"failed to load {label}: {exc}") from exc
    if not isinstance(payload, Mapping):
        raise ValueError(f"{label} must contain a JSON object")
    return payload


def _load_eligible_tickers(
    entry_report_path: str,
    *,
    market: str | None,
) -> set[str]:
    payload = _load_json_object(entry_report_path, label="entry report")
    target_market = _resolve_target_market(
        report_market=payload.get("market"),
        market_override=market,
    )
    rows = payload.get("entries")
    if not isinstance(rows, list):
        raise ValueError("entry report entries must be a list")
    tickers: set[str] = set()
    for raw_row in rows:
        if not isinstance(raw_row, Mapping):
            continue
        action = str(raw_row.get("action") or "").strip().upper()
        ticker = str(raw_row.get("ticker") or "").strip()
        if (
            action == "ENTER"
            and ticker
            and infer_market_from_ticker(ticker) == target_market
        ):
            tickers.add(ticker)
    return tickers


def _load_buy_ticker_names(
    path: str | None,
    *,
    eligible_tickers: set[str],
) -> dict[str, str]:
    if path is None:
        return {}
    payload = _load_json_object(path, label="buy report")
    rows = payload.get("candidates")
    if not isinstance(rows, list):
        raise ValueError("buy report candidates must be a list")
    ticker_names: dict[str, str] = {}
    for raw_row in rows:
        if not isinstance(raw_row, Mapping):
            continue
        ticker = str(raw_row.get("ticker") or "").strip()
        name = str(raw_row.get("name") or "").strip()
        if ticker in eligible_tickers and name:
            ticker_names[ticker] = name
    return ticker_names


def _normalize_market(value: str | None) -> str | None:
    if value is None:
        return None
    market = value.strip().upper()
    if not market:
        return None
    if market not in _ALLOWED_MARKETS:
        raise ValueError("market must be KR or US")
    return market


def _resolve_target_market(
    *,
    report_market: object,
    market_override: str | None,
) -> str:
    report_market_text = str(report_market or "").strip().upper()
    if report_market_text == "MIXED":
        if market_override is None:
            raise ValueError("MIXED entry report requires --market KR or --market US")
        return market_override
    if report_market_text in _ALLOWED_MARKETS:
        if market_override is not None and market_override != report_market_text:
            raise ValueError(
                f"--market {market_override} does not match entry report "
                f"{report_market_text}"
            )
        return report_market_text
    raise ValueError("entry report market must be KR, US, or MIXED")


__all__ = [
    "AiBriefLiveSourceCompareResult",
    "AiBriefLiveSourceProviderSpec",
    "AiBriefLiveSourceReport",
    "compare_ai_brief_live_sources",
    "parse_live_source_provider_specs",
]
