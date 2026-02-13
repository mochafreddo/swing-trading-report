from __future__ import annotations

import os
from collections.abc import Iterable
from typing import Any

from ..utils.atomic_io import advisory_path_lock, atomic_write_json
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


def write_report(
    *,
    report_dir: str,
    provider: str,
    universe_count: int,
    candidates: Iterable[dict],
    failures: Iterable[str] | None = None,
    cache_hint: str | None = None,
    report_type: str = "buy",
    strategy_mode: str | None = None,
) -> str:
    _ensure_dir(report_dir)
    today, now_str, tz_label = resolve_report_timestamp()
    normalized_report_type = _normalize_report_type(report_type)

    cand_list = list(candidates)
    failures_list = list(failures or [])
    artifact: dict[str, Any] = {
        "schema": _ARTIFACT_SCHEMA,
        "type": normalized_report_type,
        "generated_at": f"{now_str} {tz_label}",
        "report_date": today,
        "provider": provider,
        "universe": {
            "count": universe_count,
        },
        "summary": {
            "universe_count": universe_count,
            "candidate_count": len(cand_list),
            "issue_count": len(failures_list),
        },
        "tickers": _collect_tickers(cand_list),
        "candidates": cand_list,
        "issues": failures_list,
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
