#!/usr/bin/env python3
from __future__ import annotations

import argparse
import plistlib
import sys
from collections.abc import Sequence
from pathlib import Path
from typing import Any

REPO_ROOT_FROM_SCRIPT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT_FROM_SCRIPT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT_FROM_SCRIPT))

from sab.scheduler.schedule_policy import (  # noqa: E402
    launchd_schedule_map,
    launchd_start_calendar_intervals,
)


def _interval_tuple(item: dict[str, Any], *, plist_path: str) -> tuple[int, int, int]:
    try:
        return (
            int(item["Weekday"]),
            int(item["Hour"]),
            int(item["Minute"]),
        )
    except (KeyError, TypeError, ValueError) as exc:
        raise ValueError(
            f"{plist_path}: StartCalendarInterval item must contain "
            "integer Weekday, Hour, and Minute"
        ) from exc


def _format_intervals(intervals: Sequence[tuple[int, int, int]]) -> str:
    return ", ".join(
        f"weekday={weekday} {hour:02d}:{minute:02d}"
        for weekday, hour, minute in intervals
    )


def verify_plist_timing(repo_root: Path) -> list[str]:
    failures: list[str] = []
    for relative_path, dispatch in sorted(launchd_schedule_map().items()):
        plist_path = repo_root / relative_path
        try:
            payload = plistlib.loads(plist_path.read_bytes())
        except FileNotFoundError:
            failures.append(f"{relative_path}: plist not found")
            continue
        except plistlib.InvalidFileException as exc:
            failures.append(f"{relative_path}: invalid plist: {exc}")
            continue

        intervals = payload.get("StartCalendarInterval")
        if not isinstance(intervals, list):
            failures.append(f"{relative_path}: StartCalendarInterval must be a list")
            continue

        try:
            actual = sorted(
                _interval_tuple(item, plist_path=relative_path) for item in intervals
            )
        except ValueError as exc:
            failures.append(str(exc))
            continue
        expected = sorted(
            (
                int(item["Weekday"]),
                int(item["Hour"]),
                int(item["Minute"]),
            )
            for item in launchd_start_calendar_intervals(dispatch)
        )

        if actual != expected:
            failures.append(
                f"{relative_path}: StartCalendarInterval drift for "
                f"{dispatch.schedule_role}; expected "
                f"{_format_intervals(expected)}; actual {_format_intervals(actual)}"
            )

    return failures


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Verify launchd StartCalendarInterval values against policy."
    )
    parser.add_argument(
        "--repo-root",
        type=Path,
        default=Path.cwd(),
        help="Repository root containing scripts/launchd plist files.",
    )
    args = parser.parse_args(argv)

    failures = verify_plist_timing(args.repo_root)
    if failures:
        for failure in failures:
            print(failure, file=sys.stderr)
        return 1

    print("launchd plist timing matches shared schedule policy")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
