from __future__ import annotations

import pytest
import sab.config_loader as config_loader
from sab import env_loader
from sab.config_loader import ConfigLoadError, load_yaml_config


def test_load_yaml_config_returns_empty_when_default_file_missing(
    tmp_path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("SAB_CONFIG", raising=False)

    loaded = load_yaml_config()

    assert loaded.raw == {}


def test_load_yaml_config_rejects_missing_explicit_path(tmp_path) -> None:
    missing = tmp_path / "missing-config.yaml"

    with pytest.raises(ConfigLoadError, match="does not exist"):
        load_yaml_config(str(missing))


def test_load_yaml_config_rejects_missing_sab_config_env(
    tmp_path, monkeypatch: pytest.MonkeyPatch
) -> None:
    missing = tmp_path / "missing-config.yaml"
    monkeypatch.setenv("SAB_CONFIG", str(missing))

    with pytest.raises(ConfigLoadError, match="SAB_CONFIG"):
        load_yaml_config()


def test_load_yaml_config_uses_suppressed_config_env_view(
    tmp_path, monkeypatch: pytest.MonkeyPatch
) -> None:
    default_config = tmp_path / "config.yaml"
    default_config.write_text("data:\n  screen_limit: 30\n", encoding="utf-8")
    local_config = tmp_path / "config.local.yaml"
    local_config.write_text("data:\n  screen_limit: 99\n", encoding="utf-8")
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("SAB_CONFIG", str(local_config))

    with env_loader.suppress_config_env_keys(["SAB_CONFIG"]):
        loaded = load_yaml_config()

    assert loaded.raw == {"data": {"screen_limit": 30}}


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


def test_load_yaml_config_rejects_duplicate_mapping_keys(tmp_path) -> None:
    path = tmp_path / "config.yaml"
    path.write_text(
        "entry_check:\n  fatal_missing_price_ratio: null\nentry_check:\n",
        encoding="utf-8",
    )

    with pytest.raises(ConfigLoadError, match="duplicate YAML key 'entry_check'"):
        load_yaml_config(str(path))


def test_load_yaml_config_rejects_duplicate_nested_mapping_keys(tmp_path) -> None:
    path = tmp_path / "config.yaml"
    path.write_text(
        "entry_check:\n"
        "  fatal_missing_price_ratio: 0.0\n"
        "  fatal_missing_price_ratio: 1.0\n",
        encoding="utf-8",
    )

    with pytest.raises(
        ConfigLoadError, match="duplicate YAML key 'fatal_missing_price_ratio'"
    ):
        load_yaml_config(str(path))


def test_load_yaml_config_rejects_yaml_merge_override_duplicate_key(
    tmp_path,
) -> None:
    path = tmp_path / "config.yaml"
    path.write_text(
        "defaults: &entry_defaults\n"
        "  fatal_missing_price_ratio: 1.0\n"
        "entry_check:\n"
        "  <<: *entry_defaults\n"
        "  fatal_missing_price_ratio: 0.0\n",
        encoding="utf-8",
    )

    with pytest.raises(ConfigLoadError, match="duplicate YAML key"):
        load_yaml_config(str(path))


def test_load_yaml_config_rejects_duplicate_keys_across_yaml_merge_maps(
    tmp_path,
) -> None:
    path = tmp_path / "config.yaml"
    path.write_text(
        "strict_defaults: &strict_defaults\n"
        "  fatal_missing_price_ratio: 0.0\n"
        "loose_defaults: &loose_defaults\n"
        "  fatal_missing_price_ratio: 1.0\n"
        "entry_check:\n"
        "  <<: [*strict_defaults, *loose_defaults]\n",
        encoding="utf-8",
    )

    with pytest.raises(ConfigLoadError, match="duplicate YAML key"):
        load_yaml_config(str(path))


def test_load_yaml_config_rejects_duplicate_disjoint_yaml_merge_keys(
    tmp_path,
) -> None:
    path = tmp_path / "config.yaml"
    path.write_text(
        "defaults_a: &defaults_a\n"
        "  enabled: false\n"
        "defaults_b: &defaults_b\n"
        "  fatal_missing_price_ratio: 0.0\n"
        "entry_check:\n"
        "  <<: *defaults_a\n"
        "  <<: *defaults_b\n",
        encoding="utf-8",
    )

    with pytest.raises(ConfigLoadError, match="duplicate YAML key '<<'"):
        load_yaml_config(str(path))


def test_load_yaml_config_allows_yaml_merge_without_duplicate_key(
    tmp_path,
) -> None:
    path = tmp_path / "config.yaml"
    path.write_text(
        "defaults: &entry_defaults\n"
        "  enabled: false\n"
        "entry_check:\n"
        "  <<: *entry_defaults\n"
        "  fatal_missing_price_ratio: 0.0\n",
        encoding="utf-8",
    )

    loaded = load_yaml_config(str(path))

    assert loaded.raw["entry_check"] == {
        "enabled": False,
        "fatal_missing_price_ratio": 0.0,
    }


def test_load_yaml_config_raises_when_yaml_dependency_missing(
    tmp_path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = tmp_path / "config.yaml"
    path.write_text("data: {}\n", encoding="utf-8")
    monkeypatch.setattr(config_loader, "yaml", None)

    with pytest.raises(ConfigLoadError, match="PyYAML is unavailable"):
        config_loader.load_yaml_config(str(path))
