from __future__ import annotations

import argparse
import datetime as dt
import os
import sys
from collections.abc import Mapping
from pathlib import Path
from typing import Protocol, TextIO
from urllib.parse import urlsplit

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from sab.scheduler.sell_ai_brief_generation import (  # noqa: E402
    _freshness_block_reason,
)
from sab.scheduler.state import (  # noqa: E402
    RuntimeStateConfig,
    RuntimeStateEntry,
    SchedulerStateError,
    SupabaseRuntimeStateClient,
)

DEFAULT_SCHEDULER_ENV_FILE = Path(".env.scheduler.local")
DEFAULT_WEB_ENV_FILE = Path(".env")
DEFAULT_SCOPE = "MIXED"
KST = dt.timezone(dt.timedelta(hours=9), name="KST")
SCHEDULED_MARKER_KINDS = (
    "blocked",
    "notification:blocked-sent",
    "generation",
    "artifact",
    "notification:sent",
    "success",
)


class RuntimeStateReadClient(Protocol):
    def get_entry(self, key: str) -> RuntimeStateEntry | None: ...


def _strip_env_value(value: str) -> str:
    stripped = value.strip()
    if len(stripped) >= 2 and stripped[0] == stripped[-1] and stripped[0] in {"'", '"'}:
        return stripped[1:-1]
    return stripped


def load_env_file(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    if not path.exists():
        return values

    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("export "):
            line = line[len("export ") :].strip()
        key, separator, value = line.partition("=")
        normalized_key = key.strip()
        if not separator or not normalized_key:
            continue
        values[normalized_key] = _strip_env_value(value)
    return values


def load_effective_env_file(
    path: Path,
    *,
    environ: Mapping[str, str] = os.environ,
) -> dict[str, str]:
    values = load_env_file(path)
    for key, value in environ.items():
        if key in values or key.startswith("SUPABASE_"):
            values[key] = value
    return values


def load_comparison_env_file(
    path: Path,
    *,
    environ: Mapping[str, str] = os.environ,
) -> dict[str, str]:
    values = load_env_file(path)
    if values:
        return values
    return {key: value for key, value in environ.items() if key.startswith("SUPABASE_")}


def resolve_kst_session_date(now: dt.datetime | None = None) -> str:
    current = now or dt.datetime.now(dt.UTC)
    if current.tzinfo is None:
        current = current.replace(tzinfo=dt.UTC)
    return current.astimezone(KST).date().isoformat()


def _state_key(kind: str, *, scope: str, session_date: str) -> str:
    return f"scheduled-sell:{kind}:{scope}:{session_date}"


def _toss_key(*, scope: str, session_date: str) -> str:
    return f"toss-sync:success:{scope}:{session_date}"


def _normalize_scope(scope: str) -> str:
    normalized = str(scope or "").strip().upper()
    if normalized != DEFAULT_SCOPE:
        raise ValueError(
            "scheduled sell runtime_state verification currently supports MIXED"
        )
    return normalized


def _supabase_url(env: Mapping[str, str]) -> str:
    return str(env.get("SUPABASE_URL") or "").strip().rstrip("/")


def _redact_supabase_url(url: str) -> str:
    text = str(url or "").strip()
    if not text:
        return "<missing>"

    parsed = urlsplit(text)
    if parsed.hostname:
        if parsed.port:
            return f"{parsed.hostname}:{parsed.port}"
        return parsed.hostname
    return text.split("?", 1)[0].split("#", 1)[0]


def _supabase_env_match(
    scheduler_env: Mapping[str, str],
    web_env: Mapping[str, str],
) -> bool | None:
    scheduler_url = _supabase_url(scheduler_env)
    web_url = _supabase_url(web_env)
    if not scheduler_url or not web_url:
        return None
    return scheduler_url == web_url


def _format_match(value: bool | None) -> str:
    if value is None:
        return "unknown"
    return "true" if value else "false"


def _redact_secrets(message: str, env: Mapping[str, str]) -> str:
    redacted = str(message or "")
    for key_name in ("SUPABASE_SECRET_KEY", "SUPABASE_SERVICE_ROLE_KEY"):
        secret = str(env.get(key_name) or "").strip()
        if secret:
            redacted = redacted.replace(secret, "[REDACTED]")
    return redacted


def build_client_from_env(env: Mapping[str, str]) -> SupabaseRuntimeStateClient:
    url = _supabase_url(env)
    key = str(
        env.get("SUPABASE_SECRET_KEY") or env.get("SUPABASE_SERVICE_ROLE_KEY") or ""
    ).strip()
    if not url or not key:
        raise SchedulerStateError(
            "SUPABASE_URL and SUPABASE_SECRET_KEY/SUPABASE_SERVICE_ROLE_KEY "
            "must be set for scheduled sell runtime_state verification"
        )
    if key.startswith("sb_publishable_"):
        raise SchedulerStateError(
            "SUPABASE_SECRET_KEY/SUPABASE_SERVICE_ROLE_KEY must be server-side"
        )
    return SupabaseRuntimeStateClient(RuntimeStateConfig(url=url, service_role_key=key))


def _line_for_entry(key: str, entry: RuntimeStateEntry | None) -> str:
    if entry is None:
        return f"{key} missing"
    status = entry.state_payload.get("status")
    suffix = f" status={status}" if status else ""
    return f"{key} present{suffix}"


def run_verification(
    client: RuntimeStateReadClient,
    *,
    session_date: str,
    scope: str = DEFAULT_SCOPE,
    scheduler_env: Mapping[str, str],
    web_env: Mapping[str, str],
    output: TextIO = sys.stdout,
    error: TextIO = sys.stderr,
    now: dt.datetime | None = None,
) -> int:
    normalized_scope = _normalize_scope(scope)
    toss_marker_key = _toss_key(scope=normalized_scope, session_date=session_date)
    expected_keys = [
        _state_key(kind, scope=normalized_scope, session_date=session_date)
        for kind in SCHEDULED_MARKER_KINDS
    ]
    try:
        toss_entry = client.get_entry(toss_marker_key)
        expected_entries = {key: client.get_entry(key) for key in expected_keys}
    except Exception as exc:
        print(
            f"runtime_state query failed: {_redact_secrets(str(exc), scheduler_env)}",
            file=error,
        )
        return 2

    env_match = _supabase_env_match(scheduler_env, web_env)
    print(f"session_date={session_date} scope={normalized_scope}", file=output)
    print(
        "scheduler_supabase="
        f"{_redact_supabase_url(_supabase_url(scheduler_env))} "
        f"web_supabase={_redact_supabase_url(_supabase_url(web_env))} "
        f"supabase_env_match={_format_match(env_match)}",
        file=output,
    )
    print(_line_for_entry(toss_marker_key, toss_entry), file=output)
    freshness_block_reason = _freshness_block_reason(
        toss_entry,
        scope=normalized_scope,
        session_date=session_date,
        now=now or dt.datetime.now(dt.UTC),
    )
    if freshness_block_reason is not None:
        print(f"toss_freshness={freshness_block_reason}", file=output)
    for key, entry in expected_entries.items():
        print(_line_for_entry(key, entry), file=output)

    toss_ready = freshness_block_reason is None
    success_ready = (
        expected_entries[
            _state_key("success", scope=normalized_scope, session_date=session_date)
        ]
        is not None
    )
    blocked = (
        expected_entries[
            _state_key("blocked", scope=normalized_scope, session_date=session_date)
        ]
        is not None
    )

    if toss_ready and success_ready:
        print("readiness=ready", file=output)
        return 0

    readiness = "blocked" if blocked or not toss_ready else "missing"
    print(f"readiness={readiness}", file=output)
    if not toss_ready or blocked:
        print("treat_as=holdings_freshness_problem", file=output)
    return 1


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Verify scheduled Sell AI Brief runtime_state markers and Toss freshness."
        )
    )
    parser.add_argument(
        "--session-date",
        default=None,
        help="KST session date in YYYY-MM-DD format; defaults to today's KST date",
    )
    parser.add_argument(
        "--scope",
        default=DEFAULT_SCOPE,
        choices=[DEFAULT_SCOPE],
        help="Scheduled sell scope",
    )
    parser.add_argument(
        "--scheduler-env-file",
        type=Path,
        default=DEFAULT_SCHEDULER_ENV_FILE,
        help="Env file used by scripts/launchd/sab-scheduled-wrapper.sh",
    )
    parser.add_argument(
        "--web-env-file",
        type=Path,
        default=DEFAULT_WEB_ENV_FILE,
        help="Web/local env file used for Supabase URL drift comparison",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = _build_parser()
    ns = parser.parse_args(argv)
    scheduler_env_file = Path(
        os.getenv("SAB_SCHEDULER_ENV_FILE") or ns.scheduler_env_file
    )
    scheduler_env = load_effective_env_file(scheduler_env_file)
    web_env = load_comparison_env_file(ns.web_env_file)
    session_date = ns.session_date or resolve_kst_session_date()
    try:
        client = build_client_from_env(scheduler_env)
        return run_verification(
            client,
            session_date=session_date,
            scope=ns.scope,
            scheduler_env=scheduler_env,
            web_env=web_env,
        )
    except (SchedulerStateError, ValueError) as exc:
        print(
            f"scheduled sell runtime_state verification failed: {exc}", file=sys.stderr
        )
        return 2


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
