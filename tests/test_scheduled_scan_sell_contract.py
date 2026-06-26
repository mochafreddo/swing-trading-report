import pytest
from sab.scheduler.pipeline_contract import (
    ScheduledPipelineMode,
    validate_upload_enabled,
)


def test_scheduled_pipeline_shadow_mode_value() -> None:
    assert ScheduledPipelineMode.SHADOW.value == "shadow"


def test_scan_upload_requires_marker_aware_github_fallback() -> None:
    with pytest.raises(ValueError, match="marker-aware GitHub fallback"):
        validate_upload_enabled(
            pipeline="scan",
            mode=ScheduledPipelineMode.UPLOAD,
            github_marker_aware=False,
        )


def test_sell_upload_succeeds_with_marker_aware_github_fallback() -> None:
    validate_upload_enabled(
        pipeline="sell",
        mode=ScheduledPipelineMode.UPLOAD,
        github_marker_aware=True,
    )


def test_shadow_mode_does_not_require_marker_aware_github_fallback() -> None:
    validate_upload_enabled(
        pipeline="scan",
        mode=ScheduledPipelineMode.SHADOW,
        github_marker_aware=False,
    )


def test_invalid_pipeline_is_rejected() -> None:
    with pytest.raises(ValueError, match="pipeline must be scan or sell"):
        validate_upload_enabled(
            pipeline="entry",
            mode=ScheduledPipelineMode.SHADOW,
            github_marker_aware=True,
        )
