from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any

try:
    import yaml
except Exception:  # pragma: no cover - optional dependency
    yaml = None


@dataclass
class ConfigData:
    raw: dict[str, Any]


def load_yaml_config(path: str | None = None) -> ConfigData:
    path = path or os.getenv("SAB_CONFIG", "config.yaml")
    p = Path(path)
    if not p.exists():
        return ConfigData(raw={})

    data: dict[str, Any] = {}
    if yaml is None:
        return ConfigData(raw={})

    try:
        with p.open("r", encoding="utf-8") as f:
            data = yaml.safe_load(f) or {}
    except Exception:
        data = {}

    return ConfigData(raw=data)
