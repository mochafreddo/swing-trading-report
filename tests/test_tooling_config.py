from __future__ import annotations

import tomllib
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]


def _just_recipe_block(justfile: str, recipe_name: str) -> str:
    marker = f"{recipe_name}:"
    start = justfile.index(marker)
    next_recipe = justfile.find("\n\n", start)
    if next_recipe == -1:
        return justfile[start:]
    return justfile[start:next_recipe]


def test_ruff_extend_exclude_does_not_shadow_package_data_modules() -> None:
    with (REPO_ROOT / "pyproject.toml").open("rb") as file:
        pyproject = tomllib.load(file)

    ruff_config = pyproject["tool"]["ruff"]
    extend_exclude = ruff_config["extend-exclude"]

    assert "data" not in extend_exclude, (
        "Bare 'data' excludes sab/data from repo-wide Ruff checks. "
        "Use a root-scoped pattern for generated data artifacts."
    )


def test_just_web_recipes_force_mise_pinned_node_runtime() -> None:
    justfile = (REPO_ROOT / "justfile").read_text(encoding="utf-8")
    web_pnpm_recipes = [
        "web-install",
        "web-lint",
        "web-format-check",
        "web-typecheck",
        "web-test",
        "deadcode-web",
        "web-build",
    ]

    assert (
        "web_tool_path := 'PATH=\"$(mise where node)/bin:$(mise where pnpm):$PATH\"'"
        in justfile
    )
    for recipe_name in web_pnpm_recipes:
        block = _just_recipe_block(justfile, recipe_name)
        assert "{{web_tool_path}} pnpm --dir web" in block

    assert "web-python-test-setup:\n  uv sync --locked --no-dev --inexact" in justfile
    assert "web-test: web-python-test-setup" in justfile


def test_python_audit_uses_project_pinned_pip_audit() -> None:
    with (REPO_ROOT / "pyproject.toml").open("rb") as file:
        pyproject = tomllib.load(file)
    justfile = (REPO_ROOT / "justfile").read_text(encoding="utf-8")

    dev_dependencies = pyproject["dependency-groups"]["dev"]
    assert any(str(dep).startswith("pip-audit>=") for dep in dev_dependencies)

    for recipe_name in ("audit-python", "audit-python-osv"):
        block = _just_recipe_block(justfile, recipe_name)
        assert "uv run pip-audit" in block
        assert "\n  pip-audit " not in block
