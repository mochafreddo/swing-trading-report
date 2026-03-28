from __future__ import annotations

import os
from collections.abc import Iterable
from typing import Any

from ..utils.atomic_io import advisory_path_lock, atomic_write_json
from .run_meta import build_run_meta
from .time_label import resolve_report_timestamp

_ARTIFACT_SCHEMA = "sab.report.v1"
_ALLOWED_REPORT_TYPES = frozenset({"buy", "sell"})


def _ensure_dir(path: str) -> None:
    os.makedirs(path, exist_ok=True)


def _normalize_report_type(report_type: str) -> str:
    normalized = report_type.strip().lower()
    if normalized not in _ALLOWED_REPORT_TYPES:
        raise ValueError("report_type must be one of: buy, sell")
    return normalized


def _next_report_path(report_dir: str, date: str, report_type: str) -> str:
    suffix = f".{report_type}.json"
    base = os.path.join(report_dir, f"{date}{suffix}")
    if not os.path.exists(base):
        return base
    i = 1
    while True:
        path = os.path.join(report_dir, f"{date}-{i}{suffix}")
        if not os.path.exists(path):
            return path
        i += 1


def _collect_tickers(candidates: list[dict[str, Any]]) -> list[str]:
    seen: set[str] = set()
    tickers: list[str] = []
    for candidate in candidates:
        ticker_raw = candidate.get("ticker")
        if ticker_raw is None:
            continue
        ticker = str(ticker_raw).strip()
        if not ticker or ticker in seen:
            continue
        seen.add(ticker)
        tickers.append(ticker)
    return tickers


def _infer_market(candidates: list[dict[str, Any]]) -> tuple[str, list[str] | None]:
    markets: set[str] = set()
    for candidate in candidates:
        currency = str(candidate.get("currency") or "").strip().upper()
        if currency == "USD":
            markets.add("US")
        elif currency:
            markets.add("KR")
    if not markets:
        return "MIXED", None
    if len(markets) == 1:
        return next(iter(markets)), None
    return "MIXED", sorted(markets)


def write_report(
    *,
    report_dir: str,
    provider: str,
    universe_count: int,
    candidates: Iterable[dict],
    failures: Iterable[str] | None = None,
    system_issues: Iterable[str] | None = None,
    screen_outs: Iterable[str] | None = None,
    cache_hint: str | None = None,
    report_type: str = "buy",
    strategy_mode: str | None = None,
    summary_fields: dict[str, Any] | None = None,
    run_meta: dict[str, Any] | None = None,
    artifact_date: str | None = None,
) -> str:
    _ensure_dir(report_dir)
    today, now_str, tz_label = resolve_report_timestamp(artifact_date=artifact_date)
    normalized_report_type = _normalize_report_type(report_type)

    cand_list = list(candidates)
    failures_list = list(failures or [])
    system_issues_list = list(system_issues or [])
    screen_outs_list = list(screen_outs or [])
    summary: dict[str, Any] = {
        "universe_count": universe_count,
        "candidate_count": len(cand_list),
        "issue_count": len(failures_list),
        "system_issue_count": len(system_issues_list),
        "screen_out_count": len(screen_outs_list),
    }
    if summary_fields:
        summary.update(summary_fields)
    inferred_market, inferred_markets = _infer_market(cand_list)
    default_run_meta = build_run_meta(
        market=inferred_market,
        markets=inferred_markets,
        session_state="AFTER_CLOSE",
        eval_index_policy="choose_eval_index:v1",
        config_snapshot=None,
    )
    resolved_run_meta = run_meta or default_run_meta
    artifact: dict[str, Any] = {
        "schema": _ARTIFACT_SCHEMA,
        "type": normalized_report_type,
        "generated_at": f"{now_str} {tz_label}",
        "run_id": resolved_run_meta["run_id"],
        "run_ts_utc": resolved_run_meta["run_ts_utc"],
        "git_sha": resolved_run_meta.get("git_sha"),
        "eval_context": resolved_run_meta["eval_context"],
        "config_snapshot": resolved_run_meta.get("config_snapshot"),
        "report_date": today,
        "provider": provider,
        "universe": {
            "count": universe_count,
        },
        "summary": summary,
        "tickers": _collect_tickers(cand_list),
        "candidates": cand_list,
        "issues": failures_list,
        "system_issues": system_issues_list,
        "screen_outs": screen_outs_list,
    }
    if cache_hint:
        artifact["cache_hint"] = cache_hint
    if strategy_mode and normalized_report_type == "buy":
        artifact["strategy_mode"] = strategy_mode

    lock_path = os.path.join(report_dir, f".{normalized_report_type}.report.lock")
    with advisory_path_lock(lock_path):
        out_path = _next_report_path(report_dir, today, normalized_report_type)
        atomic_write_json(out_path, artifact, ensure_ascii=False, indent=2)

    return out_path
