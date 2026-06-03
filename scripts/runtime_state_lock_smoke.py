from __future__ import annotations

import argparse
import datetime as dt
import sys
import uuid
from pathlib import Path
from typing import Protocol, TextIO

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from sab.scheduler.state import (  # noqa: E402
    RuntimeStateLockClaim,
    SchedulerStateError,
    SupabaseRuntimeStateClient,
)

DEFAULT_KEY_PREFIX = "scheduled-ai-brief:test-lock"
DEFAULT_TTL_SECONDS = 60


class RuntimeStateLockClient(Protocol):
    def claim_lock(
        self,
        *,
        key: str,
        owner_token: str,
        ttl_seconds: int,
        now: dt.datetime | None = None,
        payload: dict[str, object] | None = None,
    ) -> RuntimeStateLockClaim: ...

    def check_ownership(self, key: str, *, owner_token: str) -> bool: ...

    def renew_lock(self, key: str, *, owner_token: str, ttl_seconds: int) -> bool: ...

    def release_lock(self, key: str, *, owner_token: str) -> bool: ...


class RuntimeStateLockSmokeError(RuntimeError):
    """Raised when the synthetic runtime_state lock smoke sequence fails."""


def _utc_now() -> dt.datetime:
    return dt.datetime.now(dt.UTC)


def _normalize_timestamp(value: dt.datetime) -> dt.datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=dt.UTC)
    return value.astimezone(dt.UTC)


def _build_smoke_key(*, prefix: str, now: dt.datetime) -> str:
    timestamp = _normalize_timestamp(now).strftime("%Y%m%dT%H%M%SZ")
    return f"{prefix}:{timestamp}:{uuid.uuid4().hex[:8]}"


def _parse_expires_at(value: str, *, step: str) -> None:
    normalized = value[:-1] + "+00:00" if value.endswith("Z") else value
    try:
        dt.datetime.fromisoformat(normalized)
    except ValueError as exc:
        raise RuntimeStateLockSmokeError(
            f"{step}: expires_at is not an ISO datetime"
        ) from exc


def _expect_bool(*, step: str, actual: bool, expected: bool) -> None:
    if actual is not expected:
        raise RuntimeStateLockSmokeError(f"{step}: expected {expected}, got {actual}")


def _call_bool_step(step: str, action) -> bool:
    try:
        return bool(action())
    except SchedulerStateError as exc:
        raise RuntimeStateLockSmokeError(f"{step}: {exc}") from exc


def _print_ok(output: TextIO, step: str) -> None:
    print(f"[ok] {step}", file=output)


def _claim(
    client: RuntimeStateLockClient,
    *,
    step: str,
    key: str,
    owner_token: str,
    ttl_seconds: int,
    now: dt.datetime,
    expected_acquired: bool,
) -> RuntimeStateLockClaim:
    claim = client.claim_lock(
        key=key,
        owner_token=owner_token,
        ttl_seconds=ttl_seconds,
        now=now,
        payload={
            "source": "runtime_state_lock_smoke",
            "smokeCreatedAt": _normalize_timestamp(now).isoformat(),
        },
    )
    _expect_bool(step=step, actual=claim.acquired, expected=expected_acquired)
    _parse_expires_at(claim.expires_at, step=step)
    return claim


def run_smoke(
    client: RuntimeStateLockClient,
    *,
    now: dt.datetime | None = None,
    ttl_seconds: int = DEFAULT_TTL_SECONDS,
    key_prefix: str = DEFAULT_KEY_PREFIX,
    output: TextIO = sys.stdout,
    error: TextIO = sys.stderr,
) -> int:
    smoke_now = _normalize_timestamp(now or _utc_now())
    ttl = max(1, int(ttl_seconds))
    key = _build_smoke_key(prefix=key_prefix, now=smoke_now)
    owner_token = uuid.uuid4().hex
    wrong_owner_token = uuid.uuid4().hex
    cleanup_needed = False

    try:
        _claim(
            client,
            step="first claim",
            key=key,
            owner_token=owner_token,
            ttl_seconds=ttl,
            now=smoke_now,
            expected_acquired=True,
        )
        cleanup_needed = True
        _print_ok(output, "first claim acquired lock")

        _claim(
            client,
            step="duplicate claim",
            key=key,
            owner_token=owner_token,
            ttl_seconds=ttl,
            now=smoke_now,
            expected_acquired=False,
        )
        _print_ok(output, "duplicate claim returned acquired=false")

        wrong_owner_check = _call_bool_step(
            "wrong-owner check",
            lambda: client.check_ownership(key, owner_token=wrong_owner_token),
        )
        _expect_bool(
            step="wrong-owner check",
            actual=wrong_owner_check,
            expected=False,
        )
        _print_ok(output, "wrong-owner check returned false")

        wrong_owner_renew = _call_bool_step(
            "wrong-owner renew",
            lambda: client.renew_lock(
                key,
                owner_token=wrong_owner_token,
                ttl_seconds=ttl,
            ),
        )
        _expect_bool(
            step="wrong-owner renew",
            actual=wrong_owner_renew,
            expected=False,
        )
        _print_ok(output, "wrong-owner renew returned false")

        wrong_owner_release = _call_bool_step(
            "wrong-owner release",
            lambda: client.release_lock(key, owner_token=wrong_owner_token),
        )
        _expect_bool(
            step="wrong-owner release",
            actual=wrong_owner_release,
            expected=False,
        )
        _print_ok(output, "wrong-owner release returned false")

        correct_owner_check = _call_bool_step(
            "correct-owner check",
            lambda: client.check_ownership(key, owner_token=owner_token),
        )
        _expect_bool(
            step="correct-owner check",
            actual=correct_owner_check,
            expected=True,
        )
        _print_ok(output, "correct-owner check returned true")

        correct_owner_renew = _call_bool_step(
            "correct-owner renew",
            lambda: client.renew_lock(
                key,
                owner_token=owner_token,
                ttl_seconds=ttl,
            ),
        )
        _expect_bool(
            step="correct-owner renew",
            actual=correct_owner_renew,
            expected=True,
        )
        _print_ok(output, "correct-owner renew returned true")

        correct_owner_release = _call_bool_step(
            "correct-owner release",
            lambda: client.release_lock(key, owner_token=owner_token),
        )
        _expect_bool(
            step="correct-owner release",
            actual=correct_owner_release,
            expected=True,
        )
        cleanup_needed = False
        _print_ok(output, "correct-owner release returned true")

        _claim(
            client,
            step="post-release claim",
            key=key,
            owner_token=owner_token,
            ttl_seconds=ttl,
            now=smoke_now,
            expected_acquired=True,
        )
        cleanup_needed = True
        _print_ok(output, "post-release claim acquired lock")

        cleanup_released = _call_bool_step(
            "cleanup release",
            lambda: client.release_lock(key, owner_token=owner_token),
        )
        cleanup_needed = False
        if not cleanup_released:
            print("[warn] cleanup release returned false", file=error)
            return 1
        _print_ok(output, "cleanup release returned true")

        print(f"runtime_state lock smoke passed for {key}", file=output)
        return 0
    except (RuntimeStateLockSmokeError, SchedulerStateError) as exc:
        print(f"runtime_state lock smoke failed: {exc}", file=error)
        return 1
    finally:
        if cleanup_needed:
            try:
                cleanup_released = client.release_lock(key, owner_token=owner_token)
            except SchedulerStateError as exc:
                print(f"[warn] cleanup release failed: {exc}", file=error)
            else:
                if cleanup_released:
                    _print_ok(output, "cleanup release returned true")
                else:
                    print("[warn] cleanup release returned false", file=error)


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Smoke test Supabase runtime_state lock RPC behavior."
    )
    parser.add_argument(
        "--ttl-seconds",
        type=int,
        default=DEFAULT_TTL_SECONDS,
        help="Synthetic lock TTL in seconds",
    )
    parser.add_argument(
        "--key-prefix",
        default=DEFAULT_KEY_PREFIX,
        help="Synthetic runtime_state key prefix",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = _build_parser()
    ns = parser.parse_args(argv)
    try:
        client = SupabaseRuntimeStateClient.from_env()
    except SchedulerStateError as exc:
        print(f"runtime_state lock smoke failed: {exc}", file=sys.stderr)
        return 1
    return run_smoke(
        client,
        ttl_seconds=ns.ttl_seconds,
        key_prefix=ns.key_prefix,
    )


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
