from __future__ import annotations

import os
from collections.abc import Mapping
from typing import Any

from ..utils.atomic_io import advisory_path_lock, atomic_write_json
from .paths import ensure_dir, next_report_path
from .run_meta import build_run_meta
from .time_label import resolve_report_timestamp

_ARTIFACT_SCHEMA = "sab.report.v1"


def write_backtest_report(
    *,
    report_dir: str,
    result: dict[str, Any],
    artifact_date: str | None = None,
    run_meta: dict[str, Any] | None = None,
) -> str:
    ensure_dir(report_dir)
    period_value = result.get("period")
    period: Mapping[str, Any] = period_value if isinstance(period_value, dict) else {}
    resolved_artifact_date = artifact_date or str(period.get("end_date") or "").strip()
    today, now_str, tz_label = resolve_report_timestamp(
        artifact_date=resolved_artifact_date or None
    )

    symbols = [
        str(symbol) for symbol in result.get("symbols", []) if str(symbol or "").strip()
    ]
    markets = sorted(
        {
            str(market).strip().upper()
            for market in result.get("markets", [])
            if str(market).strip().upper() in {"KR", "US"}
        }
    )
    market = markets[0] if len(markets) == 1 else "MIXED"
    default_meta = build_run_meta(
        market=market,
        markets=markets if market == "MIXED" else None,
        session_state="AFTER_CLOSE",
        eval_index_policy="historical_prefix:v1",
        config_snapshot=result.get("config_snapshot"),
    )
    resolved_meta = run_meta or default_meta

    payload: dict[str, Any] = {
        "schema": _ARTIFACT_SCHEMA,
        "type": "backtest",
        "generated_at": f"{now_str} {tz_label}",
        "report_date": today,
        "run_id": resolved_meta["run_id"],
        "run_ts_utc": resolved_meta["run_ts_utc"],
        "git_sha": resolved_meta.get("git_sha"),
        "eval_context": resolved_meta["eval_context"],
        "config_snapshot": resolved_meta.get("config_snapshot"),
        "period": result.get("period"),
        "symbols": symbols,
        "markets": markets,
        "summary": result.get("summary"),
        "trades": result.get("trades", []),
        "equity_curve": result.get("equity_curve", []),
        "assumptions": result.get("assumptions", {}),
        "issues": result.get("issues", []),
    }

    lock_path = os.path.join(report_dir, ".backtest.report.lock")
    with advisory_path_lock(lock_path):
        out_path = next_report_path(report_dir, today, "backtest")
        atomic_write_json(out_path, payload, ensure_ascii=False, indent=2)
    return out_path


__all__ = ["write_backtest_report"]
