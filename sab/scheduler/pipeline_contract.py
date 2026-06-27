from __future__ import annotations

from enum import Enum


class ScheduledPipelineMode(str, Enum):  # noqa: UP042
    SHADOW = "shadow"
    UPLOAD = "upload"


def validate_upload_enabled(
    *,
    pipeline: str,
    mode: ScheduledPipelineMode | str,
    github_marker_aware: bool,
) -> None:
    normalized_pipeline = str(pipeline or "").strip().lower()
    if normalized_pipeline not in {"scan", "sell"}:
        raise ValueError("pipeline must be scan or sell")
    if isinstance(mode, ScheduledPipelineMode):
        normalized_mode = mode
    else:
        try:
            normalized_mode = ScheduledPipelineMode(str(mode).strip().lower())
        except ValueError as exc:
            raise ValueError("mode must be shadow or upload") from exc

    if normalized_mode == ScheduledPipelineMode.UPLOAD and not github_marker_aware:
        raise ValueError(
            "scheduled scan/sell upload requires marker-aware GitHub fallback"
        )
