from __future__ import annotations

import os
from collections.abc import Iterable
from dataclasses import asdict, dataclass, field
from typing import Any

from ..utils.atomic_io import advisory_path_lock, atomic_write_json
from .paths import ensure_dir, next_report_path
from .run_meta import build_run_meta
from .time_label import resolve_report_timestamp

_ARTIFACT_SCHEMA = "sab.report.v1"
_DEFAULT_INVESTMENT_READINESS_REASONS = (
    "nav_risk_budget_unavailable",
    "liquidity_exit_capacity_unavailable",
    "portfolio_exposure_context_unavailable",
    "source_fundamental_context_unavailable",
)
DEFAULT_INVESTMENT_READINESS_REASONS = _DEFAULT_INVESTMENT_READINESS_REASONS


@dataclass
class EntryReportRow:
    ticker: str
    action: str  # ENTER|REVIEW|SKIP
    reasons: list[str]
    signal_close: float | None
    entry_price: float | None
    gap_pct: float | None
    gap_guard_pct: float | None = None
    gap_guard_up_price: float | None = None
    gap_guard_down_price: float | None = None
    strategy_mode: str | None = None
    pattern: str | None = None
    entry_state: str | None = None
    entry_price_status: str | None = None
    entry_price_source: str | None = None
    entry_price_issue_code: str | None = None
    entry_price_issues: list[str] | None = None
    implementation_ready: bool = False
    investment_readiness: str = "CONTEXT_REQUIRED"
    investment_readiness_reasons: list[str] = field(
        default_factory=lambda: list(_DEFAULT_INVESTMENT_READINESS_REASONS)
    )
    liquidity_exit_capacity: dict[str, Any] | None = None
    liquidity_warnings: list[str] = field(default_factory=list)
    portfolio_exposure_buckets: list[str] = field(default_factory=list)


def write_entry_report(
    *,
    report_dir: str,
    artifact: dict[str, Any],
    entries: Iterable[EntryReportRow],
    run_meta: dict[str, Any] | None = None,
    artifact_date: str | None = None,
) -> str:
    ensure_dir(report_dir)
    today, now_str, tz_label = resolve_report_timestamp(artifact_date=artifact_date)
    rows = [asdict(row) for row in entries]

    market = str(artifact.get("market") or "MIXED").upper()
    default_meta = build_run_meta(
        market=market if market in {"KR", "US"} else "MIXED",
        session_state=str(artifact.get("mode") or "AFTER_CLOSE").upper(),
        eval_index_policy=str(artifact.get("eval_index_policy") or "entry_snapshot:v1"),
        config_snapshot=None,
        markets=artifact.get("markets") if market == "MIXED" else None,
    )
    resolved_meta = run_meta or default_meta

    payload: dict[str, Any] = {
        "schema": _ARTIFACT_SCHEMA,
        "type": "entry",
        "generated_at": f"{now_str} {tz_label}",
        "report_date": today,
        "entries": rows,
        **artifact,
        "run_id": resolved_meta["run_id"],
        "run_ts_utc": resolved_meta["run_ts_utc"],
        "git_sha": resolved_meta.get("git_sha"),
        "eval_context": resolved_meta["eval_context"],
        "config_snapshot": resolved_meta.get("config_snapshot"),
    }

    lock_path = os.path.join(report_dir, ".entry.report.lock")
    with advisory_path_lock(lock_path):
        out_path = next_report_path(report_dir, today, "entry")
        atomic_write_json(out_path, payload, ensure_ascii=False, indent=2)

    return out_path


__all__ = [
    "DEFAULT_INVESTMENT_READINESS_REASONS",
    "EntryReportRow",
    "write_entry_report",
]
