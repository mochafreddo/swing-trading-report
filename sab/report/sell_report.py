from __future__ import annotations

import os
from collections import Counter
from collections.abc import Iterable
from dataclasses import asdict, dataclass
from typing import Any

from ..utils.atomic_io import advisory_path_lock, atomic_write_json
from .run_meta import build_run_meta
from .time_label import resolve_report_timestamp

_ARTIFACT_SCHEMA = "sab.report.v1"


def _ensure_dir(path: str) -> None:
    os.makedirs(path, exist_ok=True)


def _next_report_path(report_dir: str, date: str) -> str:
    suffix = ".sell.json"
    base = os.path.join(report_dir, f"{date}{suffix}")
    if not os.path.exists(base):
        return base
    i = 1
    while True:
        path = os.path.join(report_dir, f"{date}-{i}{suffix}")
        if not os.path.exists(path):
            return path
        i += 1


@dataclass
class SellReportRow:
    ticker: str
    name: str
    quantity: float | None
    entry_price: float | None
    entry_date: str | None
    last_price: float | None
    pnl_pct: float | None
    action: str
    reasons: list[str]
    stop_price: float | None
    target_price: float | None
    notes: str | None = None
    currency: str | None = None
    eval_date: str | None = None
    flags: list[str] | None = None
    days_in_trade_sessions: int | None = None
    time_stop_triggered: bool = False


def _infer_market(rows: list[dict[str, Any]]) -> tuple[str, list[str] | None]:
    markets: set[str] = set()
    for row in rows:
        currency = str(row.get("currency") or "").strip().upper()
        if currency == "USD":
            markets.add("US")
        elif currency:
            markets.add("KR")
    if not markets:
        return "MIXED", None
    if len(markets) == 1:
        return next(iter(markets)), None
    return "MIXED", sorted(markets)


def _collect_tickers(rows: list[dict[str, Any]]) -> list[str]:
    seen: set[str] = set()
    tickers: list[str] = []
    for row in rows:
        ticker_raw = row.get("ticker")
        if ticker_raw is None:
            continue
        ticker = str(ticker_raw).strip()
        if not ticker or ticker in seen:
            continue
        seen.add(ticker)
        tickers.append(ticker)
    return tickers


def _build_rules_payload(
    *,
    atr_trail_multiplier: float | None,
    time_stop_days: int | None,
    sell_mode: str | None,
    sell_mode_note: str | None,
) -> dict[str, Any] | None:
    payload: dict[str, Any] = {}
    if atr_trail_multiplier is not None:
        payload["atr_trail_multiplier"] = atr_trail_multiplier
    if time_stop_days is not None:
        payload["time_stop_days"] = time_stop_days
    if sell_mode:
        payload["sell_mode"] = sell_mode
    if sell_mode_note:
        payload["sell_mode_note"] = sell_mode_note
    return payload or None


def write_sell_report(
    *,
    report_dir: str,
    provider: str,
    evaluated: Iterable[SellReportRow],
    failures: Iterable[str] | None = None,
    cache_hint: str | None = None,
    atr_trail_multiplier: float | None = None,
    time_stop_days: int | None = None,
    fx_rate: float | None = None,
    fx_note: str | None = None,
    sell_mode: str | None = None,
    sell_mode_note: str | None = None,
    quantity_digits: int = 6,
    run_meta: dict[str, Any] | None = None,
    artifact_date: str | None = None,
) -> str:
    del quantity_digits  # Legacy formatting option kept for API compatibility.

    _ensure_dir(report_dir)
    today, now_str, tz_label = resolve_report_timestamp(artifact_date=artifact_date)

    rows = [asdict(row) for row in evaluated]
    failures_list = list(failures or [])
    action_counts = Counter(
        str(row.get("action") or "").strip().upper()
        for row in rows
        if str(row.get("action") or "").strip()
    )
    summary: dict[str, Any] = {
        "evaluated_count": len(rows),
        "issue_count": len(failures_list),
        "action_counts": dict(sorted(action_counts.items())),
    }

    inferred_market, inferred_markets = _infer_market(rows)
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
        "type": "sell",
        "generated_at": f"{now_str} {tz_label}",
        "run_id": resolved_run_meta["run_id"],
        "run_ts_utc": resolved_run_meta["run_ts_utc"],
        "git_sha": resolved_run_meta.get("git_sha"),
        "eval_context": resolved_run_meta["eval_context"],
        "config_snapshot": resolved_run_meta.get("config_snapshot"),
        "report_date": today,
        "provider": provider,
        "summary": summary,
        "tickers": _collect_tickers(rows),
        "evaluated": rows,
        "issues": failures_list,
    }
    if cache_hint:
        artifact["cache_hint"] = cache_hint
    rules = _build_rules_payload(
        atr_trail_multiplier=atr_trail_multiplier,
        time_stop_days=time_stop_days,
        sell_mode=sell_mode,
        sell_mode_note=sell_mode_note,
    )
    if rules:
        artifact["rules"] = rules

    fx_payload: dict[str, Any] = {}
    if fx_rate is not None:
        fx_payload["usd_krw_rate"] = fx_rate
    if fx_note:
        fx_payload["note"] = fx_note
    if fx_payload:
        artifact["fx"] = fx_payload

    lock_path = os.path.join(report_dir, ".sell.report.lock")
    with advisory_path_lock(lock_path):
        out_path = _next_report_path(report_dir, today)
        atomic_write_json(out_path, artifact, ensure_ascii=False, indent=2)

    return out_path


__all__ = ["SellReportRow", "write_sell_report"]
