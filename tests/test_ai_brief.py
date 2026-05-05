from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import pytest
from sab.__main__ import main
from sab.ai_brief import FakeAiBriefProvider, run_ai_brief


def _entry_row(
    ticker: str,
    *,
    action: str = "ENTER",
    reasons: list[str] | None = None,
    entry_price: float | None = 101.0,
) -> dict[str, object]:
    return {
        "ticker": ticker,
        "action": action,
        "reasons": reasons or ["entry conditions satisfied"],
        "signal_close": 100.0,
        "entry_price": entry_price,
        "gap_pct": 0.01,
        "gap_guard_pct": 0.03,
        "gap_guard_up_price": 103.0,
        "gap_guard_down_price": 97.0,
        "strategy_mode": "ema_cross",
        "pattern": None,
        "entry_state": None,
    }


def _write_entry_report(
    tmp_path: Path,
    *,
    market: str = "US",
    entries: list[dict[str, object]] | None = None,
) -> Path:
    path = tmp_path / "source.entry.json"
    payload: dict[str, object] = {
        "schema": "sab.report.v1",
        "type": "entry",
        "source_buy_report": "source.buy.json",
        "market": market,
        "entries": entries
        if entries is not None
        else [_entry_row("AAPL.NAS"), _entry_row("MSFT.NAS", action="REVIEW")],
        "summary": {"entry_count": 2},
        "system_issues": [],
    }
    if market == "MIXED":
        payload["markets"] = ["KR", "US"]
    path.write_text(json.dumps(payload), encoding="utf-8")
    return path


def _write_buy_report(tmp_path: Path) -> Path:
    path = tmp_path / "source.buy.json"
    path.write_text(
        json.dumps(
            {
                "schema": "sab.report.v1",
                "type": "buy",
                "candidates": [
                    {
                        "ticker": "AAPL.NAS",
                        "name": "Apple",
                        "reasons": [{"label": "EMA cross", "status": "pass"}],
                    },
                    {
                        "ticker": "NOT-ELIGIBLE.NAS",
                        "name": "Should not appear",
                    },
                ],
            }
        ),
        encoding="utf-8",
    )
    return path


def test_run_ai_brief_writes_recommendations_from_entry_report_only(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    entry_report = _write_entry_report(tmp_path)
    buy_report = _write_buy_report(tmp_path)
    report_dir = tmp_path / "reports"
    monkeypatch.setattr(
        "sab.ai_brief.load_config",
        lambda: SimpleNamespace(report_dir=report_dir.as_posix()),
    )

    exit_code = run_ai_brief(
        entry_report_path=entry_report.as_posix(),
        buy_report_path=buy_report.as_posix(),
        market=None,
        model_provider="fake",
        model_name="fake-ai-brief-v1",
    )

    assert exit_code == 0
    payload = json.loads(next(report_dir.glob("*.ai-brief.json")).read_text())
    assert payload["market"] == "US"
    assert payload["source_entry_report"] == "source.entry.json"
    assert payload["source_buy_report"] == "source.buy.json"
    assert payload["recommendations"][0]["ticker"] == "AAPL.NAS"
    assert payload["recommendations"][0]["name"] == "Apple"
    assert payload["recommendations"][0]["confidence"] == "LOW"
    assert payload["excluded_candidates"] == [
        {
            "ticker": "MSFT.NAS",
            "action": "REVIEW",
            "reason": "entry report action was REVIEW",
        }
    ]
    assert payload["eligible_tickers"] == ["AAPL.NAS"]
    assert "NOT-ELIGIBLE.NAS" not in json.dumps(payload)


def test_run_ai_brief_keeps_running_when_optional_buy_report_is_missing(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    entry_report = _write_entry_report(tmp_path)
    report_dir = tmp_path / "reports"
    monkeypatch.setattr(
        "sab.ai_brief.load_config",
        lambda: SimpleNamespace(report_dir=report_dir.as_posix()),
    )

    exit_code = run_ai_brief(
        entry_report_path=entry_report.as_posix(),
        buy_report_path=(tmp_path / "missing.buy.json").as_posix(),
        market=None,
        model_provider="fake",
        model_name="fake-ai-brief-v1",
    )

    assert exit_code == 0
    payload = json.loads(next(report_dir.glob("*.ai-brief.json")).read_text())
    assert payload["recommendations"][0]["ticker"] == "AAPL.NAS"
    assert payload["recommendations"][0]["name"] is None
    assert len(payload["system_issues"]) == 1
    assert payload["system_issues"][0]["ticker"] is None
    assert payload["system_issues"][0]["code"] == "buy_report_enrichment_unavailable"
    assert payload["system_issues"][0]["severity"] == "WARN"
    assert "Failed to load buy report:" in payload["system_issues"][0]["message"]


def test_run_ai_brief_requires_market_for_mixed_entry_report(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    entry_report = _write_entry_report(
        tmp_path,
        market="MIXED",
        entries=[_entry_row("005930"), _entry_row("AAPL.NAS")],
    )
    report_dir = tmp_path / "reports"
    monkeypatch.setattr(
        "sab.ai_brief.load_config",
        lambda: SimpleNamespace(report_dir=report_dir.as_posix()),
    )

    exit_code = run_ai_brief(
        entry_report_path=entry_report.as_posix(),
        buy_report_path=None,
        market=None,
        model_provider="fake",
        model_name="fake-ai-brief-v1",
    )

    assert exit_code == 1
    assert list(report_dir.glob("*.ai-brief.json")) == []


def test_run_ai_brief_market_override_filters_mixed_report(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    entry_report = _write_entry_report(
        tmp_path,
        market="MIXED",
        entries=[
            _entry_row("005930"),
            _entry_row("AAPL.NAS"),
            _entry_row("MSFT.NAS", action="SKIP"),
        ],
    )
    report_dir = tmp_path / "reports"
    monkeypatch.setattr(
        "sab.ai_brief.load_config",
        lambda: SimpleNamespace(report_dir=report_dir.as_posix()),
    )

    exit_code = run_ai_brief(
        entry_report_path=entry_report.as_posix(),
        buy_report_path=None,
        market="US",
        model_provider="fake",
        model_name="fake-ai-brief-v1",
    )

    assert exit_code == 0
    payload = json.loads(next(report_dir.glob("*.ai-brief.json")).read_text())
    assert payload["market"] == "US"
    assert payload["eligible_tickers"] == ["AAPL.NAS"]
    assert [row["ticker"] for row in payload["excluded_candidates"]] == ["MSFT.NAS"]


def test_run_ai_brief_writes_empty_artifact_when_no_enter_candidates(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    entry_report = _write_entry_report(
        tmp_path,
        entries=[
            _entry_row("AAPL.NAS", action="REVIEW"),
            _entry_row("MSFT.NAS", action="SKIP"),
        ],
    )
    report_dir = tmp_path / "reports"
    monkeypatch.setattr(
        "sab.ai_brief.load_config",
        lambda: SimpleNamespace(report_dir=report_dir.as_posix()),
    )

    exit_code = run_ai_brief(
        entry_report_path=entry_report.as_posix(),
        buy_report_path=None,
        market=None,
        model_provider="fake",
        model_name="fake-ai-brief-v1",
    )

    assert exit_code == 0
    payload = json.loads(next(report_dir.glob("*.ai-brief.json")).read_text())
    assert payload["recommendations"] == []
    assert payload["eligible_tickers"] == []
    assert payload["summary"]["recommendation_count"] == 0
    assert payload["summary"]["excluded_count"] == 2


def test_run_ai_brief_applies_provider_boundary_before_output_cap(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    entries = [_entry_row(f"TICK{i}.NAS") for i in range(7)]
    entry_report = _write_entry_report(tmp_path, entries=entries)
    report_dir = tmp_path / "reports"
    seen: dict[str, object] = {}
    original_build = FakeAiBriefProvider.build_recommendations

    def spy_build(
        self: FakeAiBriefProvider,
        *,
        candidates: list[dict[str, object]],
    ) -> tuple[list[dict[str, object]], list[dict[str, object]]]:
        seen["tickers"] = [candidate["ticker"] for candidate in candidates]
        return original_build(self, candidates=candidates)

    monkeypatch.setattr(FakeAiBriefProvider, "build_recommendations", spy_build)
    monkeypatch.setattr(
        "sab.ai_brief.load_config",
        lambda: SimpleNamespace(report_dir=report_dir.as_posix()),
    )

    exit_code = run_ai_brief(
        entry_report_path=entry_report.as_posix(),
        buy_report_path=None,
        market=None,
        model_provider="fake",
        model_name="fake-ai-brief-v1",
    )

    assert exit_code == 0
    payload = json.loads(next(report_dir.glob("*.ai-brief.json")).read_text())
    assert seen["tickers"] == [f"TICK{i}.NAS" for i in range(5)]
    assert [item["ticker"] for item in payload["recommendations"]] == [
        "TICK0.NAS",
        "TICK1.NAS",
        "TICK2.NAS",
    ]
    assert [item["ticker"] for item in payload["cap_excluded_candidates"]] == [
        "TICK5.NAS",
        "TICK6.NAS",
    ]


def test_main_routes_ai_brief_command(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: dict[str, object] = {}
    monkeypatch.delenv("LOG_FORMAT", raising=False)

    def fake_run_ai_brief(**kwargs: object) -> int:
        captured.update(kwargs)
        return 0

    monkeypatch.setattr("sab.__main__.run_ai_brief", fake_run_ai_brief)

    exit_code = main(
        [
            "ai-brief",
            "--entry-report",
            "reports/source.entry.json",
            "--market",
            "US",
            "--buy-report",
            "reports/source.buy.json",
        ]
    )

    assert exit_code == 0
    assert captured == {
        "entry_report_path": "reports/source.entry.json",
        "buy_report_path": "reports/source.buy.json",
        "market": "US",
        "model_provider": "fake",
        "model_name": "fake-ai-brief-v1",
    }
