from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

ENTRY_FILENAMES = {
    "page.js",
    "page.jsx",
    "page.ts",
    "page.tsx",
    "route.js",
    "route.jsx",
    "route.ts",
    "route.tsx",
}

CATCH_ALL_SEGMENT_RE = re.compile(r"^\[\[?\.\.\.[^\]]+\]?\]$")
ROUTE_GROUP_SEGMENT_RE = re.compile(r"^\([^/]+\)$")


def is_route_group_segment(segment: str) -> bool:
    # Route groups like `(console)` are not part of the URL path.
    return bool(ROUTE_GROUP_SEGMENT_RE.match(segment))


def is_parallel_route_segment(segment: str) -> bool:
    # Parallel route slots like `@modal` are not part of the URL path.
    return segment.startswith("@")


def is_url_segment(segment: str) -> bool:
    return (
        segment
        and not is_route_group_segment(segment)
        and not is_parallel_route_segment(segment)
    )


def is_catch_all_segment(segment: str) -> bool:
    return bool(CATCH_ALL_SEGMENT_RE.match(segment))


def iter_entry_files(app_dir: Path) -> list[Path]:
    if not app_dir.exists():
        return []
    return [
        path
        for path in app_dir.rglob("*")
        if path.is_file() and path.name in ENTRY_FILENAMES
    ]


def check_catch_all_is_last(app_dir: Path) -> list[str]:
    errors: list[str] = []
    for entry_file in iter_entry_files(app_dir):
        try:
            rel_dir = entry_file.parent.relative_to(app_dir)
        except ValueError:
            continue

        url_segments = [seg for seg in rel_dir.parts if is_url_segment(seg)]
        if not url_segments:
            continue

        catch_all_indices = [
            idx for idx, seg in enumerate(url_segments) if is_catch_all_segment(seg)
        ]
        if not catch_all_indices:
            continue

        last_catch_all = catch_all_indices[-1]
        if last_catch_all != len(url_segments) - 1:
            route = "/" + "/".join(url_segments)
            errors.append(
                f"{entry_file}: invalid route {route!r} (catch-all segment must be the last URL segment)"
            )

    return errors


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Static checks for Next.js App Router file-based routes.\n\n"
            "Currently verifies that catch-all segments ([...param], [[...param]]) "
            "are the last segment in a route's URL path."
        ),
    )
    parser.add_argument(
        "--app-dir",
        default="web/src/app",
        help="Path to Next.js app directory (default: web/src/app).",
    )
    return parser.parse_args(argv)


def main(argv: list[str]) -> int:
    args = parse_args(argv)
    app_dir = Path(args.app_dir)
    errors = check_catch_all_is_last(app_dir)
    if not errors:
        return 0

    print("Next.js route static check failed:")
    for error in errors:
        print(f"- {error}")
    print()
    print("Fix: move the catch-all segment to the end of the URL path.")
    return 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
