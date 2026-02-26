from __future__ import annotations

import datetime as dt
import os
import subprocess
import uuid
from typing import Any

_ALLOWED_MARKETS = {"KR", "US", "MIXED"}
_ALLOWED_SESSION_STATES = {"PRE_OPEN", "INTRADAY", "AFTER_CLOSE"}


def _resolve_git_sha() -> str | None:
    env_sha = (os.getenv("GITHUB_SHA") or "").strip()
    if env_sha:
        return env_sha

    try:
        completed = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            check=True,
            capture_output=True,
            text=True,
            timeout=2.0,
        )
    except Exception:
        return None

    resolved = completed.stdout.strip()
    return resolved or None


def _normalize_market(value: str) -> str:
    market = value.strip().upper()
    if market not in _ALLOWED_MARKETS:
        raise ValueError(f"market must be one of {_ALLOWED_MARKETS}")
    return market


def _normalize_session_state(value: str) -> str:
    session_state = value.strip().upper()
    if session_state not in _ALLOWED_SESSION_STATES:
        raise ValueError(f"session_state must be one of {_ALLOWED_SESSION_STATES}")
    return session_state


def _format_utc_iso(now: dt.datetime) -> str:
    aware = now
    if aware.tzinfo is None:
        aware = aware.replace(tzinfo=dt.UTC)
    else:
        aware = aware.astimezone(dt.UTC)
    return aware.replace(microsecond=0).isoformat().replace("+00:00", "Z")


def build_run_meta(
    *,
    market: str,
    session_state: str,
    eval_index_policy: str,
    config_snapshot: dict[str, Any] | None,
    markets: list[str] | None = None,
    now: dt.datetime | None = None,
    run_id: str | None = None,
) -> dict[str, Any]:
    normalized_market = _normalize_market(market)
    normalized_session_state = _normalize_session_state(session_state)

    timestamp = now or dt.datetime.now(dt.UTC)
    resolved_run_id = run_id or str(uuid.uuid4())
    eval_context: dict[str, Any] = {
        "market": normalized_market,
        "session_state": normalized_session_state,
        "eval_index_policy": eval_index_policy,
    }
    if normalized_market == "MIXED" and markets:
        normalized_markets = sorted(
            {
                str(item).strip().upper()
                for item in markets
                if str(item).strip().upper() in {"KR", "US"}
            }
        )
        if normalized_markets:
            eval_context["markets"] = normalized_markets

    return {
        "run_id": resolved_run_id,
        "run_ts_utc": _format_utc_iso(timestamp),
        "git_sha": _resolve_git_sha(),
        "eval_context": eval_context,
        "config_snapshot": config_snapshot,
    }


__all__ = ["build_run_meta"]
