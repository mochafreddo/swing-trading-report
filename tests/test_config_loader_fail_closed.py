from __future__ import annotations

import pytest
import sab.config_loader as config_loader
from sab.config_loader import ConfigLoadError, load_yaml_config


def test_load_yaml_config_returns_empty_when_file_missing(tmp_path) -> None:
    missing = tmp_path / "missing-config.yaml"

    loaded = load_yaml_config(str(missing))

    assert loaded.raw == {}


def test_load_yaml_config_raises_on_invalid_yaml(tmp_path) -> None:
    path = tmp_path / "config.yaml"
    path.write_text("data: [\n", encoding="utf-8")

    with pytest.raises(ConfigLoadError, match="Failed to parse config file"):
        load_yaml_config(str(path))


def test_load_yaml_config_raises_on_non_mapping_root(tmp_path) -> None:
    path = tmp_path / "config.yaml"
    path.write_text("- item\n", encoding="utf-8")

    with pytest.raises(ConfigLoadError, match="must have a mapping"):
        load_yaml_config(str(path))


def test_load_yaml_config_raises_when_yaml_dependency_missing(
    tmp_path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = tmp_path / "config.yaml"
    path.write_text("data: {}\n", encoding="utf-8")
    monkeypatch.setattr(config_loader, "yaml", None)

    with pytest.raises(ConfigLoadError, match="PyYAML is unavailable"):
        config_loader.load_yaml_config(str(path))
