from __future__ import annotations

import datetime as dt
import json
import os
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .observability import is_sensitive_log_field, sanitize_log_value

_MAX_REPETITIONS = 3
DEFAULT_PRIMARY_MODEL = "gpt-5.5"
DEFAULT_FALLBACK_MODEL = "gpt-5.4-mini"


@dataclass(frozen=True)
class ProbeItem:
    model_name: str
    timeout_seconds: float
    repetitions: int


def build_probe_plan(
    *,
    primary_model: str = DEFAULT_PRIMARY_MODEL,
    fallback_model: str | None = DEFAULT_FALLBACK_MODEL,
    repetitions: int = 1,
) -> list[ProbeItem]:
    if repetitions < 1 or repetitions > _MAX_REPETITIONS:
        raise ValueError("repetitions must be <= 3 and >= 1")

    plan = [
        ProbeItem(primary_model, 20.0, repetitions),
        ProbeItem(primary_model, 30.0, repetitions),
        ProbeItem(primary_model, 60.0, repetitions),
    ]
    if fallback_model:
        plan.append(ProbeItem(fallback_model, 30.0, repetitions))
    return plan


def default_output_path(now: dt.datetime | None = None) -> Path:
    current = now or dt.datetime.now(dt.UTC)
    return (
        Path("logs/measurements/ai-brief-model-latency")
        / f"{current.date().isoformat()}.jsonl"
    )


def _is_secret_field(name: str) -> bool:
    return is_sensitive_log_field(name)


def _safe_probe_row(row: Mapping[str, object]) -> dict[str, Any]:
    safe_row: dict[str, Any] = {}
    for key, value in row.items():
        key_text = str(key)
        if _is_secret_field(key_text):
            continue
        safe_row[key_text] = sanitize_log_value(key_text, value)
    return safe_row


def write_probe_row(path: Path, row: Mapping[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    line = json.dumps(_safe_probe_row(row), ensure_ascii=False, sort_keys=True) + "\n"
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o600)
    try:
        os.write(fd, line.encode("utf-8"))
    finally:
        os.close(fd)


def run_probe(
    *,
    primary_model: str = DEFAULT_PRIMARY_MODEL,
    fallback_model: str | None = DEFAULT_FALLBACK_MODEL,
    repetitions: int = 1,
) -> int:
    plan = build_probe_plan(
        primary_model=primary_model,
        fallback_model=fallback_model,
        repetitions=repetitions,
    )
    print(f"planned_live_model_call_count={sum(item.repetitions for item in plan)}")
    return 0
