from __future__ import annotations

import json
import logging
import os
from typing import Any

from ..utils.atomic_io import atomic_write_json

logger = logging.getLogger(__name__)


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
    try:
        with open(p, encoding="utf-8") as f:
            return json.load(f)
    except FileNotFoundError:
        logger.debug(
            "Cache file not found",
            extra={
                "event": "cache_miss",
                "operation": "load_json_cache",
                "status": "miss",
                "cache_key": key,
                "cache_path": p,
            },
        )
        return None
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        logger.warning(
            "Ignoring unreadable cache file",
            extra={
                "event": "cache_load_failed",
                "operation": "load_json_cache",
                "status": "degraded",
                "cache_key": key,
                "cache_path": p,
                "error_type": type(exc).__name__,
                "retryable": isinstance(exc, OSError),
            },
        )
        return None
