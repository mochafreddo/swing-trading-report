from __future__ import annotations

import os
from collections import Counter
from collections.abc import Iterable
from dataclasses import asdict, dataclass
from typing import Any

from ..utils.atomic_io import advisory_path_lock, atomic_write_json
from .metadata import collect_row_tickers, infer_market_from_currency
from .paths import ensure_dir, next_report_path
from .risk_disclosure import build_sell_risk_disclosure
from .run_meta import build_run_meta
from .time_label import resolve_report_timestamp

_ARTIFACT_SCHEMA = "sab.report.v1"


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
    summary_fields: dict[str, Any] | None = None,
    quantity_digits: int = 6,
    run_meta: dict[str, Any] | None = None,
    artifact_date: str | None = None,
) -> str:
    del quantity_digits  # Legacy formatting option kept for API compatibility.

    ensure_dir(report_dir)
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
    if summary_fields:
        summary.update(summary_fields)

    inferred_market, inferred_markets = infer_market_from_currency(rows)
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
        "risk_disclosure": build_sell_risk_disclosure(),
        "tickers": collect_row_tickers(rows),
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
        out_path = next_report_path(report_dir, today, "sell")
        atomic_write_json(out_path, artifact, ensure_ascii=False, indent=2)

    return out_path


__all__ = ["SellReportRow", "write_sell_report"]
