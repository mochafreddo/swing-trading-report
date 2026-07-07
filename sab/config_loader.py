from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .env_loader import getenv
from .utils.yaml import unique_key_safe_loader

try:
    import yaml  # type: ignore[import-untyped]
except Exception:  # pragma: no cover - optional dependency
    yaml = None


class ConfigLoadError(RuntimeError):
    """Raised when config.yaml exists but cannot be loaded safely."""


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
            loaded: Any = yaml.load(
                f, Loader=unique_key_safe_loader(yaml, ConfigLoadError)
            )
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
