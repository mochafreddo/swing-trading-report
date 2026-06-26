from __future__ import annotations

import datetime as dt
import json
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path

_MAX_REPETITIONS = 3


@dataclass(frozen=True)
class ProbeItem:
    model_name: str
    timeout_seconds: float
    repetitions: int


def build_probe_plan(
    *,
    primary_model: str,
    fallback_model: str | None,
    repetitions: int,
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
    upper_name = name.upper()
    return any(token in upper_name for token in ("KEY", "SECRET", "TOKEN", "PASSWORD"))


def write_probe_row(path: Path, row: Mapping[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    safe_row = {key: value for key, value in row.items() if not _is_secret_field(key)}
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(safe_row, ensure_ascii=False, sort_keys=True))
        handle.write("\n")


def run_probe(
    *,
    primary_model: str,
    fallback_model: str | None,
    repetitions: int,
) -> int:
    plan = build_probe_plan(
        primary_model=primary_model,
        fallback_model=fallback_model,
        repetitions=repetitions,
    )
    print(f"planned_live_model_call_count={sum(item.repetitions for item in plan)}")
    return 0
