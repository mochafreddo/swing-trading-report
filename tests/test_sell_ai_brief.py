from __future__ import annotations

import datetime as dt
import json
from pathlib import Path
from types import SimpleNamespace
from typing import cast

import pytest
from sab import sell_ai_brief
from sab.sell_ai_brief import run_sell_ai_brief


def _sell_row(
    ticker: str,
    *,
    action: str,
    reasons: list[str] | None = None,
) -> dict[str, object]:
    return {
        "ticker": ticker,
        "name": ticker,
        "quantity": 3,
        "entry_price": 100.0,
        "entry_date": "2026-05-01",
        "last_price": 94.0,
        "pnl_pct": -0.06,
        "action": action,
        "reasons": reasons or ["stop loss breached"],
        "stop_price": 95.0,
        "target_price": 115.0,
        "currency": "USD",
        "eval_date": "2026-05-05",
    }


def _write_sell_report(
    tmp_path: Path,
    *,
    evaluated: list[dict[str, object]] | None = None,
    market: str = "US",
) -> Path:
    path = tmp_path / "source.sell.json"
    rows = (
        evaluated if evaluated is not None else [_sell_row("AAPL.NAS", action="SELL")]
    )
    path.write_text(
        json.dumps(
            {
                "schema": "sab.report.v1",
                "type": "sell",
                "report_date": "2026-05-05",
                "market": market,
                "summary": {"evaluated_count": len(rows)},
                "evaluated": rows,
                "issues": [],
            }
        ),
        encoding="utf-8",
    )
    return path


@pytest.fixture(autouse=True)
def _fixed_now(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        sell_ai_brief,
        "_current_utc_time",
        lambda: dt.datetime(2026, 5, 5, 8, 40, tzinfo=dt.UTC),
    )


def test_run_sell_ai_brief_reviews_only_actionable_rows(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    sell_report = _write_sell_report(
        tmp_path,
        evaluated=[
            _sell_row("AAPL.NAS", action="SELL"),
            _sell_row("MSFT.NAS", action="SELL_PARTIAL"),
            _sell_row("TSLA.NAS", action="REVIEW", reasons=["market data missing"]),
            _sell_row("NVDA.NAS", action="HOLD"),
            _sell_row("BAD.NAS", action="TRIM"),
        ],
    )
    report_dir = tmp_path / "reports"
    monkeypatch.setattr(
        "sab.sell_ai_brief.load_config",
        lambda: SimpleNamespace(report_dir=report_dir.as_posix()),
    )

    exit_code = run_sell_ai_brief(
        sell_report_path=sell_report.as_posix(),
        model_provider="fake",
        model_name="fake-sell-ai-brief-v1",
        source_provider="none",
    )

    assert exit_code == 0
    payload = json.loads(next(report_dir.glob("*.sell-ai-brief.json")).read_text())
    assert payload["type"] == "sell-ai-brief"
    assert payload["source_sell_report"] == "source.sell.json"
    assert payload["actionable_tickers"] == ["AAPL.NAS", "MSFT.NAS", "TSLA.NAS"]
    assert [row["ticker"] for row in payload["judgments"]] == [
        "AAPL.NAS",
        "MSFT.NAS",
        "TSLA.NAS",
    ]
    assert [row["ticker"] for row in payload["excluded_hold_candidates"]] == [
        "NVDA.NAS"
    ]
    assert [row["ticker"] for row in payload["unsupported_action_candidates"]] == [
        "BAD.NAS"
    ]
    assert payload["summary"]["actionable_count"] == 3
    assert payload["summary"]["source_issue_count"] == 3


def test_run_sell_ai_brief_skips_model_when_no_actionable_rows(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    sell_report = _write_sell_report(
        tmp_path,
        evaluated=[_sell_row("MSFT.NAS", action="HOLD")],
    )
    report_dir = tmp_path / "reports"
    monkeypatch.setattr(
        "sab.sell_ai_brief.load_config",
        lambda: SimpleNamespace(report_dir=report_dir.as_posix()),
    )

    def fail_provider(**_kwargs: object) -> object:
        raise AssertionError("provider must not be built")

    monkeypatch.setattr("sab.sell_ai_brief._build_provider", fail_provider)

    exit_code = run_sell_ai_brief(
        sell_report_path=sell_report.as_posix(),
        model_provider="fake",
        model_name="fake-sell-ai-brief-v1",
        source_provider="none",
    )

    assert exit_code == 0
    payload = json.loads(next(report_dir.glob("*.sell-ai-brief.json")).read_text())
    assert payload["judgments"] == []
    assert payload["model_attempts"] == []
    assert payload["brief_state"] == "NO_ACTION"
    assert payload["brief_reason"] == "no_actionable_sell_candidates"


def test_run_sell_ai_brief_caps_provider_input_at_five(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    sell_report = _write_sell_report(
        tmp_path,
        evaluated=[_sell_row(f"T{i}.NAS", action="SELL") for i in range(1, 7)],
    )
    report_dir = tmp_path / "reports"
    monkeypatch.setattr(
        "sab.sell_ai_brief.load_config",
        lambda: SimpleNamespace(report_dir=report_dir.as_posix()),
    )

    exit_code = run_sell_ai_brief(
        sell_report_path=sell_report.as_posix(),
        model_provider="fake",
        model_name="fake-sell-ai-brief-v1",
        source_provider="none",
    )

    assert exit_code == 0
    payload = json.loads(next(report_dir.glob("*.sell-ai-brief.json")).read_text())
    assert payload["actionable_tickers"] == [
        "T1.NAS",
        "T2.NAS",
        "T3.NAS",
        "T4.NAS",
        "T5.NAS",
    ]
    assert [row["ticker"] for row in payload["cap_excluded_candidates"]] == ["T6.NAS"]
    assert len(payload["judgments"]) == 5
    assert payload["summary"]["actionable_count"] == 6
    assert payload["summary"]["preselected_count"] == 5
    assert payload["summary"]["cap_excluded_count"] == 1


def test_run_sell_ai_brief_uploads_with_sell_ai_brief_run_type(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    sell_report = _write_sell_report(tmp_path)
    report_dir = tmp_path / "reports"
    monkeypatch.setattr(
        "sab.sell_ai_brief.load_config",
        lambda: SimpleNamespace(report_dir=report_dir.as_posix()),
    )
    upload_calls: list[dict[str, object]] = []

    def _fake_upload(**kwargs: object) -> str:
        upload_calls.append(kwargs)
        return "2026/05/2026-05-05.sell-ai-brief.json"

    monkeypatch.setattr("sab.sell_ai_brief.maybe_upload_report_artifact", _fake_upload)

    exit_code = run_sell_ai_brief(
        sell_report_path=sell_report.as_posix(),
        model_provider="fake",
        model_name="fake-sell-ai-brief-v1",
        source_provider="none",
        upload=True,
    )

    assert exit_code == 0
    assert len(upload_calls) == 1
    assert upload_calls[0]["run_type"] == "sell-ai-brief"
    assert upload_calls[0]["force"] is True
    assert cast(str, upload_calls[0]["artifact_path"]).endswith(".sell-ai-brief.json")


def test_run_sell_ai_brief_returns_failure_when_model_provider_fails(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    sell_report = _write_sell_report(tmp_path)
    report_dir = tmp_path / "reports"
    monkeypatch.setattr(
        "sab.sell_ai_brief.load_config",
        lambda: SimpleNamespace(report_dir=report_dir.as_posix()),
    )

    class _FailingProvider:
        def build_judgments(
            self,
            *,
            actionable_candidates: list[dict[str, object]],
        ) -> object:
            raise sell_ai_brief.SellAiBriefProviderError("model request failed")

    monkeypatch.setattr(
        "sab.sell_ai_brief._build_provider",
        lambda **_kwargs: _FailingProvider(),
    )

    exit_code = run_sell_ai_brief(
        sell_report_path=sell_report.as_posix(),
        model_provider="fake",
        model_name="fake-sell-ai-brief-v1",
        source_provider="none",
    )

    assert exit_code == 1
    payload = json.loads(next(report_dir.glob("*.sell-ai-brief.json")).read_text())
    assert payload["brief_state"] == "MODEL_OR_SYSTEM_ISSUE"
    assert payload["model_attempts"][0]["status"] == "failed"


def test_run_sell_ai_brief_uses_market_chains_for_mixed_sell_reports(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    sell_report = _write_sell_report(
        tmp_path,
        market="MIXED",
        evaluated=[
            _sell_row("005930.KS", action="SELL"),
            _sell_row("AAPL.NAS", action="SELL_PARTIAL"),
        ],
    )
    report_dir = tmp_path / "reports"
    monkeypatch.setattr(
        "sab.sell_ai_brief.load_config",
        lambda: SimpleNamespace(report_dir=report_dir.as_posix()),
    )
    monkeypatch.setenv("SELL_AI_BRIEF_SOURCE_PROVIDER_CHAIN_KR", "naver-news")
    monkeypatch.setenv(
        "SELL_AI_BRIEF_SOURCE_PROVIDER_CHAIN_US", "finnhub,benzinga-news"
    )
    captured_source_chains: list[tuple[str, ...]] = []

    def _fake_source_chain(**kwargs: object) -> SimpleNamespace:
        captured_source_chains.append(cast(tuple[str, ...], kwargs["source_providers"]))
        return SimpleNamespace(
            sources_by_ticker={},
            source_issues=[],
            system_issues=[],
            summary={},
        )

    monkeypatch.setattr(
        "sab.sell_ai_brief.load_ai_brief_source_chain",
        _fake_source_chain,
    )

    exit_code = run_sell_ai_brief(
        sell_report_path=sell_report.as_posix(),
        model_provider="fake",
        model_name="fake-sell-ai-brief-v1",
    )

    assert exit_code == 0
    assert captured_source_chains == [("naver-news", "finnhub", "benzinga-news")]
