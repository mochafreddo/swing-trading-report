#!/usr/bin/env python3
from __future__ import annotations

import json
import os
import re
import sys
import tomllib
import urllib.error
import urllib.request
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path


@dataclass(frozen=True)
class Dep:
    name: str
    raw: str
    upper_major: int | None  # e.g. "<3" -> 3, "<1" -> 1


def _parse_name(requirement: str) -> str | None:
    # Handles "pkg", "pkg>=1", "pkg[extra]>=1"
    m = re.match(r"^\s*([A-Za-z0-9_.-]+)", requirement)
    if not m:
        return None
    return m.group(1).lower().replace("_", "-")


def _parse_upper_major(requirement: str) -> int | None:
    # We only care about caps like "<3" or "<1.0". This implementation is
    # intentionally simple; we control the input in pyproject.toml.
    m = re.search(r"(?:^|,)\s*<\s*(\d+)(?:\D|$)", requirement)
    if not m:
        return None
    return int(m.group(1))


def _version_major(version: str) -> int | None:
    m = re.match(r"^\s*(\d+)", version)
    if not m:
        return None
    return int(m.group(1))


def _fetch_pypi_latest_version(package: str) -> str | None:
    url = f"https://pypi.org/pypi/{package}/json"
    req = urllib.request.Request(
        url,
        headers={
            "Accept": "application/json",
            "User-Agent": "swing-trading-report deps major-check",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            payload = json.loads(resp.read().decode("utf-8"))
    except (urllib.error.URLError, TimeoutError, json.JSONDecodeError):
        return None
    return payload.get("info", {}).get("version")


def _iter_deps(pyproject: dict) -> Iterable[Dep]:
    project = pyproject.get("project", {})
    for req in project.get("dependencies", []) or []:
        name = _parse_name(req)
        if not name:
            continue
        yield Dep(name=name, raw=req, upper_major=_parse_upper_major(req))

    for _extra, reqs in (project.get("optional-dependencies", {}) or {}).items():
        for req in reqs or []:
            name = _parse_name(req)
            if not name:
                continue
            yield Dep(name=name, raw=req, upper_major=_parse_upper_major(req))

    for _group, reqs in (pyproject.get("dependency-groups", {}) or {}).items():
        for req in reqs or []:
            name = _parse_name(req)
            if not name:
                continue
            yield Dep(name=name, raw=req, upper_major=_parse_upper_major(req))


def _read_locked_versions(lock_path: Path) -> dict[str, str]:
    data = tomllib.loads(lock_path.read_text(encoding="utf-8"))
    locked: dict[str, str] = {}
    for pkg in data.get("package", []) or []:
        name = str(pkg.get("name", "")).lower().replace("_", "-")
        version = str(pkg.get("version", ""))
        if name and version:
            locked[name] = version
    return locked


def _write_github_output(key: str, value: str) -> None:
    output_path = os.environ.get("GITHUB_OUTPUT")
    if not output_path:
        return
    with open(output_path, "a", encoding="utf-8") as f:
        f.write(f"{key}={value}\n")


def main(argv: list[str]) -> int:
    _ = argv
    root = Path.cwd()
    pyproject_path = root / "pyproject.toml"
    lock_path = root / "uv.lock"

    pyproject = tomllib.loads(pyproject_path.read_text(encoding="utf-8"))
    locked = _read_locked_versions(lock_path) if lock_path.exists() else {}

    deps = {dep.name: dep for dep in _iter_deps(pyproject)}
    results: list[tuple[str, str | None, str | None, bool, str]] = []
    has_major = False

    for name, dep in sorted(deps.items()):
        latest = _fetch_pypi_latest_version(name)
        locked_version = locked.get(name)
        latest_major = _version_major(latest) if latest else None

        if dep.upper_major is None:
            status = "UNCAPPED"
            is_major = False
        elif latest_major is None:
            status = "UNKNOWN"
            is_major = False
        else:
            capped_major = dep.upper_major - 1
            is_major = latest_major > capped_major
            status = "MAJOR_AVAILABLE" if is_major else "OK"

        has_major = has_major or is_major
        results.append((name, locked_version, latest, is_major, status))

    lines: list[str] = []
    lines.append("# 메이저 의존성 업데이트 리포트")
    lines.append("")
    lines.append(
        f"- Generated (UTC): {datetime.now(UTC).isoformat(timespec='seconds')}"
    )
    lines.append("")
    if not results:
        lines.append("- No dependencies found in pyproject.toml.")
    else:
        lines.append("| package | locked | latest | status |")
        lines.append("|---|---:|---:|---|")
        for name, locked_version, latest, _is_major, status in results:
            lines.append(
                f"| `{name}` | `{locked_version or '-'}` | `{latest or '-'}` | **{status}** |"
            )

    report = "\n".join(lines) + "\n"
    sys.stdout.write(report)

    _write_github_output("has_major", "true" if has_major else "false")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
