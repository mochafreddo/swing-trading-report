from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any

try:
    import yaml  # type: ignore[import-untyped]
except Exception:  # pragma: no cover - optional dependency
    yaml = None


class ConfigLoadError(RuntimeError):
    """Raised when config.yaml exists but cannot be loaded safely."""


@dataclass
class ConfigData:
    raw: dict[str, Any]


def load_yaml_config(path: str | None = None) -> ConfigData:
    resolved_path = (
        path if path is not None else (os.getenv("SAB_CONFIG") or "config.yaml")
    )
    p = Path(resolved_path)
    if not p.exists():
        return ConfigData(raw={})

    if yaml is None:
        raise ConfigLoadError(
            f"Config file '{p}' exists but PyYAML is unavailable. "
            "Install dependency 'pyyaml' to parse YAML config."
        )

    try:
        with p.open("r", encoding="utf-8") as f:
            loaded: Any = yaml.safe_load(f)
    except OSError as exc:
        raise ConfigLoadError(f"Failed to read config file '{p}': {exc}") from exc
    except Exception as exc:
        raise ConfigLoadError(f"Failed to parse config file '{p}': {exc}") from exc

    if loaded is None:
        return ConfigData(raw={})
    if not isinstance(loaded, dict):
        raise ConfigLoadError(
            "Config file "
            f"'{p}' must have a mapping (object) at YAML root, got "
            f"{type(loaded).__name__}."
        )

    return ConfigData(raw=loaded)
