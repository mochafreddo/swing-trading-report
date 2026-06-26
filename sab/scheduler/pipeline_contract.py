from __future__ import annotations

from enum import Enum


class ScheduledPipelineMode(str, Enum):  # noqa: UP042
    SHADOW = "shadow"
    UPLOAD = "upload"


def validate_upload_enabled(
    *,
    pipeline: str,
    mode: ScheduledPipelineMode,
    github_marker_aware: bool,
) -> None:
    normalized_pipeline = str(pipeline or "").strip().lower()
    if normalized_pipeline not in {"scan", "sell"}:
        raise ValueError("pipeline must be scan or sell")

    if mode == ScheduledPipelineMode.UPLOAD and not github_marker_aware:
        raise ValueError(
            "scheduled scan/sell upload requires marker-aware GitHub fallback"
        )
