from __future__ import annotations

from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]


def test_just_exposes_live_integration_smoke_recipe() -> None:
    justfile = (REPO_ROOT / "justfile").read_text(encoding="utf-8")

    assert "live-integration-smoke *args:" in justfile
    assert "uv run python scripts/live_integration_smoke.py {{args}}" in justfile
