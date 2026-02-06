from __future__ import annotations

import json
import os
from typing import Any

from ..utils.atomic_io import atomic_write_json


def ensure_dir(path: str) -> None:
    os.makedirs(path, exist_ok=True)


def json_path(base_dir: str, key: str) -> str:
    safe = key.replace("/", "_")
    return os.path.join(base_dir, f"{safe}.json")


def save_json(base_dir: str, key: str, obj: Any) -> str:
    ensure_dir(base_dir)
    p = json_path(base_dir, key)
    atomic_write_json(p, obj, ensure_ascii=False)
    return p


def load_json(base_dir: str, key: str) -> Any | None:
    p = json_path(base_dir, key)
    if not os.path.exists(p):
        return None
    try:
        with open(p, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None
