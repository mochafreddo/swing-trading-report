from __future__ import annotations

import tomllib
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]


def test_ruff_extend_exclude_does_not_shadow_package_data_modules() -> None:
    with (REPO_ROOT / "pyproject.toml").open("rb") as file:
        pyproject = tomllib.load(file)

    ruff_config = pyproject["tool"]["ruff"]
    extend_exclude = ruff_config["extend-exclude"]

    assert "data" not in extend_exclude, (
        "Bare 'data' excludes sab/data from repo-wide Ruff checks. "
        "Use a root-scoped pattern for generated data artifacts."
    )
