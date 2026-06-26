from __future__ import annotations

import json
from pathlib import Path

import pytest
from sab import ai_brief_latency_probe


def test_probe_plan_defaults_to_bounded_call_count() -> None:
    plan = ai_brief_latency_probe.build_probe_plan()

    assert [item.timeout_seconds for item in plan] == [20.0, 30.0, 60.0, 30.0]
    assert [item.model_name for item in plan] == [
        "gpt-5.5",
        "gpt-5.5",
        "gpt-5.5",
        "gpt-5.4-mini",
    ]
    assert sum(item.repetitions for item in plan) == 4


def test_probe_rejects_repetition_above_default_cap() -> None:
    with pytest.raises(ValueError, match="repetitions must be <= 3"):
        ai_brief_latency_probe.build_probe_plan(
            primary_model="gpt-5.5",
            fallback_model="gpt-5.4-mini",
            repetitions=4,
        )


def test_probe_writes_jsonl_with_sorted_no_secret_fields(tmp_path: Path) -> None:
    output = tmp_path / "latency.jsonl"
    ai_brief_latency_probe.write_probe_row(
        output,
        {
            "timestamp": "2026-06-26T12:00:00Z",
            "market": "US",
            "model_name": "gpt-5.5",
            "timeout_seconds": 20.0,
            "attempt_number": 1,
            "status": "success",
            "duration_ms": 1234,
            "recommendation_count": 1,
            "vetoed_count": 0,
            "watch_count": 0,
            "OPENAI_API_KEY": "sk-test-secret",
            "response": {
                "headers": {"Authorization": "Bearer nested-secret-token"},
                "message": "request failed api_key=nested-api-key",
            },
        },
    )
    ai_brief_latency_probe.write_probe_row(
        output,
        {
            "timestamp": "2026-06-26T12:01:00Z",
            "market": "US",
            "model_name": "gpt-5.4-mini",
            "timeout_seconds": 30.0,
            "attempt_number": 2,
            "status": "timeout",
            "duration_ms": 30000,
        },
    )

    lines = output.read_text(encoding="utf-8").splitlines()
    file_text = output.read_text(encoding="utf-8")
    assert len(lines) == 2
    assert lines[0].startswith('{"attempt_number":')
    assert "OPENAI_API_KEY" not in file_text
    assert "nested-secret-token" not in file_text
    assert "nested-api-key" not in file_text

    payload = json.loads(lines[0])
    assert payload["status"] == "success"
    assert payload["duration_ms"] == 1234
    assert "response" not in payload


def test_probe_write_uses_single_append_write(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    output = tmp_path / "latency.jsonl"
    writes: list[bytes] = []
    real_write = ai_brief_latency_probe.os.write

    def fake_write(fd: int, data: bytes) -> int:
        writes.append(data)
        return real_write(fd, data)

    monkeypatch.setattr(ai_brief_latency_probe.os, "write", fake_write)

    ai_brief_latency_probe.write_probe_row(output, {"status": "success"})

    assert len(writes) == 1
    assert writes[0].endswith(b"\n")
    assert json.loads(output.read_text(encoding="utf-8")) == {"status": "success"}


def test_probe_write_raises_on_short_append_write(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    output = tmp_path / "latency.jsonl"

    def fake_write(_fd: int, data: bytes) -> int:
        return len(data) - 1

    monkeypatch.setattr(ai_brief_latency_probe.os, "write", fake_write)

    with pytest.raises(OSError, match="short write"):
        ai_brief_latency_probe.write_probe_row(output, {"status": "success"})
