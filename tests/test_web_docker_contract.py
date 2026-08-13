from __future__ import annotations

from pathlib import Path

import yaml  # type: ignore[import-untyped]


def test_web_dockerignore_excludes_local_env_files_from_build_context() -> None:
    patterns = Path(".dockerignore").read_text(encoding="utf-8").splitlines()

    assert ".env" in patterns
    assert ".env.*" in patterns
    assert "!.env.example" in patterns


def test_web_dev_container_runs_as_non_root_with_bind_mounted_source() -> None:
    compose = yaml.safe_load(Path("docker-compose.yml").read_text(encoding="utf-8"))
    dockerfile = Path("web/Dockerfile.dev").read_text(encoding="utf-8")

    assert "./web:/app" in compose["services"]["web-dev"]["volumes"]
    assert "USER node" in dockerfile


def test_web_container_packages_bounded_t9_reader_and_read_only_journal() -> None:
    compose = yaml.safe_load(Path("docker-compose.yml").read_text(encoding="utf-8"))
    dockerfile = Path("web/Dockerfile").read_text(encoding="utf-8")

    assert compose["services"]["web"]["build"] == {
        "context": ".",
        "dockerfile": "web/Dockerfile",
    }
    assert any(
        volume.endswith(":/var/lib/sab/decision-board-journal:ro")
        for volume in compose["services"]["web"]["volumes"]
    )
    assert "DECISION_BOARD_JOURNAL_PYTHON" in compose["x-web-env"]
    assert "run_journal_public.py" in dockerfile
    assert "apk add --no-cache python3" in dockerfile


def test_scheduler_container_mounts_logs_writable_for_status_file() -> None:
    compose = yaml.safe_load(
        Path("docker-compose.scheduler.yml").read_text(encoding="utf-8")
    )

    volumes = compose["services"]["scheduler"]["volumes"]
    assert "./logs:/workspace/logs" in volumes
