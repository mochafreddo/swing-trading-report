from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace
from typing import Any

from sab.__main__ import main
from sab.ai_brief import run_ai_brief


def test_ai_brief_cli_forwards_report_date(monkeypatch: Any) -> None:
    captured: dict[str, object] = {}

    def _fake_run_ai_brief(**kwargs: object) -> int:
        captured.update(kwargs)
        return 0

    monkeypatch.setattr("sab.__main__.run_ai_brief", _fake_run_ai_brief)

    exit_code = main(
        [
            "ai-brief",
            "--entry-report",
            "reports/2026-05-28.entry.json",
            "--report-date",
            "2026-05-28",
        ]
    )

    assert exit_code == 0
    assert captured["report_date"] == "2026-05-28"


def test_run_ai_brief_uses_report_date_as_artifact_date(
    tmp_path: Path, monkeypatch: Any
) -> None:
    entry_report = tmp_path / "2026-05-28.entry.json"
    entry_report.write_text(
        json.dumps(
            {
                "market": "US",
                "entries": [],
                "system_issues": [],
            }
        ),
        encoding="utf-8",
    )
    captured: dict[str, object] = {}

    def _fake_load_config() -> SimpleNamespace:
        return SimpleNamespace(report_dir=tmp_path.as_posix())

    def _fake_write_ai_brief_report(**kwargs: object) -> str:
        captured.update(kwargs)
        output = tmp_path / "2026-05-28.ai-brief.json"
        output.write_text("{}", encoding="utf-8")
        return output.as_posix()

    monkeypatch.setattr("sab.ai_brief.load_config", _fake_load_config)
    monkeypatch.setattr(
        "sab.ai_brief.write_ai_brief_report", _fake_write_ai_brief_report
    )

    exit_code = run_ai_brief(
        entry_report_path=entry_report.as_posix(),
        buy_report_path=None,
        market="US",
        model_provider="fake",
        model_name="fake-ai-brief-v1",
        report_date="2026-05-28",
    )

    assert exit_code == 0
    assert captured["artifact_date"] == "2026-05-28"
