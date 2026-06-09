from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .env_loader import getenv

try:
    import yaml  # type: ignore[import-untyped]
except Exception:  # pragma: no cover - optional dependency
    yaml = None


class ConfigLoadError(RuntimeError):
    """Raised when config.yaml exists but cannot be loaded safely."""


_YAML_MERGE_TAG = "tag:yaml.org,2002:merge"


def _construct_mapping_key_for_duplicate_check(
    loader: Any, key_node: Any, deep: bool
) -> Any:
    if getattr(key_node, "tag", None) == _YAML_MERGE_TAG:
        return "<<"
    return loader.construct_object(key_node, deep=deep)


def _reject_duplicate_mapping_keys(loader: Any, node: Any, deep: bool) -> None:
    seen_keys: list[Any] = []
    for key_node, _value_node in node.value:
        key = _construct_mapping_key_for_duplicate_check(loader, key_node, deep)
        if any(key == seen_key for seen_key in seen_keys):
            raise ConfigLoadError(f"duplicate YAML key {key!r}")
        try:
            hash(key)
        except TypeError as exc:
            raise ConfigLoadError(f"unhashable YAML key {key!r}") from exc
        seen_keys.append(key)


def _construct_mapping_without_duplicate_keys(
    loader: Any, node: Any, deep: bool = False
) -> dict[Any, Any]:
    _reject_duplicate_mapping_keys(loader, node, deep)
    loader.flatten_mapping(node)
    _reject_duplicate_mapping_keys(loader, node, deep)

    mapping: dict[Any, Any] = {}
    for key_node, value_node in node.value:
        key = loader.construct_object(key_node, deep=deep)
        value = loader.construct_object(value_node, deep=deep)
        try:
            mapping[key] = value
        except TypeError as exc:
            raise ConfigLoadError(f"unhashable YAML key {key!r}") from exc

    return mapping


def _unique_key_safe_loader() -> type[Any]:
    class UniqueKeySafeLoader(yaml.SafeLoader):
        pass

    UniqueKeySafeLoader.add_constructor(
        yaml.resolver.BaseResolver.DEFAULT_MAPPING_TAG,
        _construct_mapping_without_duplicate_keys,
    )
    return UniqueKeySafeLoader


@dataclass
class ConfigData:
    raw: dict[str, Any]
    loaded: bool = False
    resolved_path: str | None = None


def load_yaml_config(path: str | None = None) -> ConfigData:
    env_path = getenv("SAB_CONFIG")
    if path is None and env_path is not None and not env_path.strip():
        raise ConfigLoadError("SAB_CONFIG must not be blank.")
    resolved_path = path if path is not None else (env_path or "config.yaml")
    p = Path(resolved_path)
    if not p.exists():
        if path is not None:
            raise ConfigLoadError(f"Config file '{p}' does not exist.")
        if env_path:
            raise ConfigLoadError(f"SAB_CONFIG points to missing config file '{p}'.")
        return ConfigData(raw={})

    if yaml is None:
        raise ConfigLoadError(
            f"Config file '{p}' exists but PyYAML is unavailable. "
            "Install dependency 'pyyaml' to parse YAML config."
        )

    try:
        with p.open("r", encoding="utf-8") as f:
            loaded: Any = yaml.load(f, Loader=_unique_key_safe_loader())
    except OSError as exc:
        raise ConfigLoadError(f"Failed to read config file '{p}': {exc}") from exc
    except Exception as exc:
        raise ConfigLoadError(f"Failed to parse config file '{p}': {exc}") from exc

    if loaded is None:
        return ConfigData(raw={}, loaded=True, resolved_path=str(p))
    if not isinstance(loaded, dict):
        raise ConfigLoadError(
            "Config file "
            f"'{p}' must have a mapping (object) at YAML root, got "
            f"{type(loaded).__name__}."
        )

    return ConfigData(raw=loaded, loaded=True, resolved_path=str(p))
