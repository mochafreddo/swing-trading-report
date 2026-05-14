from __future__ import annotations

import json
import tomllib
from pathlib import Path
from typing import Any

import yaml  # type: ignore[import-untyped]

REPO_ROOT = Path(__file__).resolve().parents[1]
RELEASE_PLEASE_V5_PIN = (
    "googleapis/release-please-action@45996ed1f6d02564a971a2fa1b5860e934307cf7"
)


def _read_json(path: str) -> dict[str, Any]:
    payload = json.loads((REPO_ROOT / path).read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise AssertionError(f"{path} must contain a JSON object")
    return payload


def _read_toml(path: str) -> dict[str, Any]:
    with (REPO_ROOT / path).open("rb") as file:
        payload = tomllib.load(file)
    if not isinstance(payload, dict):
        raise AssertionError(f"{path} must contain a TOML table")
    return payload


def _load_workflow(path: str) -> dict[Any, Any]:
    payload = yaml.safe_load((REPO_ROOT / path).read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise AssertionError(f"{path} must contain a workflow mapping")
    return payload


def _release_please_step() -> dict[Any, Any]:
    workflow = _load_workflow(".github/workflows/release-please.yml")
    steps = workflow["jobs"]["release-please"]["steps"]
    if not isinstance(steps, list):
        raise AssertionError("Release Please workflow steps must be a list")

    for step in steps:
        if isinstance(step, dict) and step.get("name") == "Run release-please":
            return step
    raise AssertionError("Release Please workflow step not found")


def _locked_project_version() -> str:
    lock = _read_toml("uv.lock")
    packages = lock.get("package")
    if not isinstance(packages, list):
        raise AssertionError("uv.lock must contain package entries")

    for package in packages:
        if isinstance(package, dict) and package.get("name") == "swing-trading-report":
            version = package.get("version")
            if isinstance(version, str):
                return version
            raise AssertionError("uv.lock project package must have a string version")

    raise AssertionError("uv.lock project package entry not found")


def test_release_please_uses_manifest_mode_without_deprecated_command() -> None:
    release_step = _release_please_step()
    release_inputs = release_step.get("with")
    if not isinstance(release_inputs, dict):
        raise AssertionError("Release Please step must define inputs")

    assert release_step["uses"] == RELEASE_PLEASE_V5_PIN
    assert "command" not in release_inputs
    assert release_inputs["config-file"] == "release-please-config.json"
    assert release_inputs["manifest-file"] == ".release-please-manifest.json"


def test_release_please_owns_python_and_web_versions() -> None:
    config = _read_json("release-please-config.json")
    root_package = config["packages"]["."]
    extra_files = root_package["extra-files"]

    assert root_package["release-type"] == "python"
    assert root_package["changelog-path"] == "CHANGELOG.md"
    assert {
        "type": "json",
        "path": "web/package.json",
        "jsonpath": "$.version",
    } in extra_files
    assert {
        "type": "toml",
        "path": "uv.lock",
        "jsonpath": '$.package[?(@.name=="swing-trading-report")].version',
    } in extra_files


def test_release_metadata_versions_stay_in_lockstep() -> None:
    manifest = _read_json(".release-please-manifest.json")
    pyproject = _read_toml("pyproject.toml")
    web_package = _read_json("web/package.json")

    expected_version = pyproject["project"]["version"]
    assert manifest["."] == expected_version
    assert web_package["version"] == expected_version
    assert _locked_project_version() == expected_version
