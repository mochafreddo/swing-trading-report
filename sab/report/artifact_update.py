from __future__ import annotations

import json
from collections.abc import Iterable
from pathlib import Path

from ..utils.atomic_io import atomic_write_json


def append_report_issues(
    artifact_path: str,
    *,
    issues: Iterable[str] | None = None,
    system_issues: Iterable[str] | None = None,
) -> None:
    path = Path(artifact_path)
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("report artifact must be a JSON object")

    summary = payload.get("summary")
    if summary is not None and not isinstance(summary, dict):
        raise ValueError("report artifact summary must be a JSON object")

    if issues is not None:
        issues_list = list(issues)
        payload["issues"] = issues_list
        if isinstance(summary, dict):
            summary["issue_count"] = len(issues_list)

    if system_issues is not None:
        system_issues_list = list(system_issues)
        payload["system_issues"] = system_issues_list
        if isinstance(summary, dict):
            summary["system_issue_count"] = len(system_issues_list)

    atomic_write_json(str(path), payload, ensure_ascii=False, indent=2)
