from __future__ import annotations

import datetime as dt
import json
from pathlib import Path
from types import SimpleNamespace

import pytest
from sab.__main__ import main
from sab.ai_brief import FakeAiBriefProvider, run_ai_brief
from sab.ai_brief_sources import AiBriefSourceProviderError, load_ai_brief_sources


def _fresh_published_at() -> str:
    return dt.datetime.now(dt.UTC).replace(microsecond=0).isoformat()


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


def _write_source_report(
    tmp_path: Path,
    *,
    sources: list[dict[str, object]] | None = None,
) -> Path:
    path = tmp_path / "source.sources.json"
    published_at = _fresh_published_at()
    path.write_text(
        json.dumps(
            {
                "schema": "sab.ai_brief_sources.v1",
                "type": "ai_brief_sources",
                "sources": sources
                if sources is not None
                else [
                    {
                        "ticker": "AAPL.NAS",
                        "title": "Apple supply chain update",
                        "url": "https://example.test/aapl",
                        "published_at": published_at,
                    }
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
        source_provider=None,
        source_report_path=None,
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
        source_provider=None,
        source_report_path=None,
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
        source_provider=None,
        source_report_path=None,
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
        source_provider=None,
        source_report_path=None,
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
        source_provider=None,
        source_report_path=None,
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
    ) -> object:
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
        source_provider=None,
        source_report_path=None,
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


def test_run_ai_brief_local_source_provider_enriches_fake_recommendation_sources(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    entry_report = _write_entry_report(tmp_path)
    source_report = _write_source_report(tmp_path)
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
        source_provider="local-json",
        source_report_path=source_report.as_posix(),
    )

    assert exit_code == 0
    payload = json.loads(next(report_dir.glob("*.ai-brief.json")).read_text())
    assert payload["recommendations"][0]["sources"][0]["title"] == (
        "Apple supply chain update"
    )
    assert payload["recommendations"][0]["sources"][0]["url"] == (
        "https://example.test/aapl"
    )
    assert payload["source_issues"] == []
    assert payload["summary"]["source_issue_count"] == 0


def test_run_ai_brief_source_report_implies_local_json_provider(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    entry_report = _write_entry_report(tmp_path)
    source_report = _write_source_report(tmp_path)
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
        source_provider=None,
        source_report_path=source_report.as_posix(),
    )

    assert exit_code == 0
    payload = json.loads(next(report_dir.glob("*.ai-brief.json")).read_text())
    assert payload["recommendations"][0]["sources"][0]["url"] == (
        "https://example.test/aapl"
    )


def test_run_ai_brief_local_source_provider_cannot_add_tickers(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    entry_report = _write_entry_report(tmp_path)
    source_report = _write_source_report(
        tmp_path,
        sources=[
            {
                "ticker": "NOT-ELIGIBLE.NAS",
                "title": "Unrelated source",
                "url": "https://example.test/not-eligible",
                "published_at": _fresh_published_at(),
            }
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
        source_provider="local-json",
        source_report_path=source_report.as_posix(),
    )

    assert exit_code == 0
    payload = json.loads(next(report_dir.glob("*.ai-brief.json")).read_text())
    assert payload["eligible_tickers"] == ["AAPL.NAS"]
    assert [item["ticker"] for item in payload["recommendations"]] == ["AAPL.NAS"]
    assert "NOT-ELIGIBLE.NAS" not in json.dumps(payload["recommendations"])
    assert {issue["code"] for issue in payload["source_issues"]} == {
        "local_source_unknown_ticker",
        "fake_provider_no_external_sources",
    }


def test_run_ai_brief_local_source_provider_failure_keeps_artifact(
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
        buy_report_path=None,
        market=None,
        model_provider="fake",
        model_name="fake-ai-brief-v1",
        source_provider="local-json",
        source_report_path=(tmp_path / "missing.sources.json").as_posix(),
    )

    assert exit_code == 0
    payload = json.loads(next(report_dir.glob("*.ai-brief.json")).read_text())
    assert payload["recommendations"][0]["sources"] == []
    assert payload["system_issues"][0]["code"] == "source_provider_failed"
    assert payload["summary"]["system_issue_count"] == 1


def test_load_ai_brief_sources_rejects_malformed_report(tmp_path: Path) -> None:
    path = tmp_path / "bad.sources.json"
    path.write_text(json.dumps({"sources": {}}), encoding="utf-8")

    with pytest.raises(AiBriefSourceProviderError, match="sources must be a list"):
        load_ai_brief_sources(
            source_provider="local-json",
            source_report_path=path.as_posix(),
            eligible_tickers={"AAPL.NAS"},
        )


def test_load_ai_brief_sources_reports_invalid_stale_and_capped_rows(
    tmp_path: Path,
) -> None:
    now = dt.datetime(2026, 5, 5, 9, 0, tzinfo=dt.UTC)
    stale = (now - dt.timedelta(hours=73)).isoformat()
    fresh = (now - dt.timedelta(hours=1)).isoformat()
    path = _write_source_report(
        tmp_path,
        sources=[
            "not-object",  # type: ignore[list-item]
            {"ticker": "", "title": "Missing ticker", "url": "https://example.test/a"},
            {"ticker": "AAPL.NAS", "url": "https://example.test/missing-title"},
            {"ticker": "AAPL.NAS", "title": "Missing URL", "published_at": fresh},
            {
                "ticker": "AAPL.NAS",
                "title": "Missing date",
                "url": "https://example.test/missing-date",
            },
            {
                "ticker": "AAPL.NAS",
                "title": "Bad date",
                "url": "https://example.test/bad-date",
                "published_at": "2026-05-05T09:00:00",
            },
            {
                "ticker": "AAPL.NAS",
                "title": "Old source",
                "url": "https://example.test/old",
                "published_at": stale,
            },
            {
                "ticker": "AAPL.NAS",
                "title": "Fresh 1",
                "url": "https://example.test/fresh-1",
                "published_at": fresh,
            },
            {
                "ticker": "AAPL.NAS",
                "title": "Fresh 2",
                "url": "https://example.test/fresh-2",
                "published_at": fresh,
            },
            {
                "ticker": "AAPL.NAS",
                "title": "Fresh 3",
                "url": "https://example.test/fresh-3",
                "published_at": fresh,
            },
            {
                "ticker": "AAPL.NAS",
                "title": "Fresh 4",
                "url": "https://example.test/fresh-4",
                "published_at": fresh,
            },
        ],
    )

    result = load_ai_brief_sources(
        source_provider="local-json",
        source_report_path=path.as_posix(),
        eligible_tickers={"AAPL.NAS"},
        now=now,
    )

    assert [source["url"] for source in result.sources_by_ticker["AAPL.NAS"]] == [
        "https://example.test/fresh-1",
        "https://example.test/fresh-2",
        "https://example.test/fresh-3",
    ]
    assert [issue["code"] for issue in result.source_issues] == [
        "local_source_invalid_row",
        "local_source_invalid_row",
        "local_source_invalid_row",
        "local_source_invalid_row",
        "local_source_invalid_row",
        "local_source_invalid_row",
        "local_source_stale",
        "local_source_cap_exceeded",
    ]


class _TimeoutSession:
    def post(self, *args: object, **kwargs: object) -> object:
        import sab.ai_brief_providers as ai_brief_providers

        raise ai_brief_providers.requests.Timeout("timed out")


class _HttpErrorSession:
    def post(self, *args: object, **kwargs: object) -> object:
        return _JsonResponse({"error": "server unavailable"}, status_code=503)


class _JsonResponse:
    def __init__(self, payload: dict[str, object], *, status_code: int = 200) -> None:
        self._payload = payload
        self.status_code = status_code
        self.text = json.dumps(payload)

    def json(self) -> dict[str, object]:
        return self._payload


class _OpenAiSession:
    def __init__(self, output: dict[str, object]) -> None:
        self.output = output
        self.calls: list[dict[str, object]] = []

    def post(self, url: str, **kwargs: object) -> _JsonResponse:
        self.calls.append({"url": url, **kwargs})
        return _JsonResponse(
            {
                "output": [
                    {
                        "type": "message",
                        "content": [
                            {
                                "type": "output_text",
                                "text": json.dumps(self.output),
                            }
                        ],
                    }
                ]
            }
        )


def test_run_ai_brief_openai_provider_writes_structured_recommendation(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    entry_report = _write_entry_report(tmp_path)
    report_dir = tmp_path / "reports"
    session = _OpenAiSession(
        {
            "recommendations": [
                {
                    "ticker": "AAPL.NAS",
                    "rank": 1,
                    "confidence": "LOW",
                    "rationale": ["entry setup remains valid on the provided data"],
                    "checklist": [
                        "manually confirm price, cash, and risk before order"
                    ],
                    "sources": [],
                }
            ],
            "vetoed_candidates": [],
            "source_issues": [
                {
                    "ticker": "AAPL.NAS",
                    "code": "openai_no_external_sources",
                    "severity": "WARN",
                    "message": "OpenAI provider was run without a news source provider.",
                }
            ],
        }
    )
    monkeypatch.setenv("OPENAI_API_KEY", "test-key")
    monkeypatch.setattr(
        "sab.ai_brief.load_config",
        lambda: SimpleNamespace(report_dir=report_dir.as_posix()),
    )
    monkeypatch.setattr(
        "sab.ai_brief_providers.requests.Session",
        lambda: session,
    )

    exit_code = run_ai_brief(
        entry_report_path=entry_report.as_posix(),
        buy_report_path=None,
        market=None,
        model_provider="openai",
        model_name="gpt-test",
        model_timeout_seconds=7.5,
        source_provider=None,
        source_report_path=None,
    )

    assert exit_code == 0
    payload = json.loads(next(report_dir.glob("*.ai-brief.json")).read_text())
    assert payload["model_provider"] == "openai"
    assert payload["model_name"] == "gpt-test"
    assert payload["recommendations"][0]["ticker"] == "AAPL.NAS"
    assert payload["recommendations"][0]["action"] == "ENTER"
    assert payload["source_issues"][0]["code"] == "openai_no_external_sources"
    assert session.calls[0]["url"] == "https://api.openai.com/v1/responses"
    assert session.calls[0]["timeout"] == 7.5
    request_json = session.calls[0]["json"]
    assert isinstance(request_json, dict)
    assert request_json["model"] == "gpt-test"
    assert request_json["text"]["format"]["type"] == "json_schema"  # type: ignore[index]


def test_run_ai_brief_openai_payload_includes_local_sources(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    entry_report = _write_entry_report(tmp_path)
    source_report = _write_source_report(tmp_path)
    report_dir = tmp_path / "reports"
    session = _OpenAiSession(
        {
            "recommendations": [
                {
                    "ticker": "AAPL.NAS",
                    "rank": 1,
                    "confidence": "LOW",
                    "rationale": ["source-backed context supports manual review"],
                    "checklist": ["manually confirm price and risk before order"],
                    "sources": [
                        {
                            "title": "Apple supply chain update",
                            "url": "https://example.test/aapl",
                            "published_at": _fresh_published_at(),
                        }
                    ],
                }
            ],
            "vetoed_candidates": [],
            "source_issues": [],
        }
    )
    monkeypatch.setenv("OPENAI_API_KEY", "test-key")
    monkeypatch.setattr(
        "sab.ai_brief.load_config",
        lambda: SimpleNamespace(report_dir=report_dir.as_posix()),
    )
    monkeypatch.setattr("sab.ai_brief_providers.requests.Session", lambda: session)

    exit_code = run_ai_brief(
        entry_report_path=entry_report.as_posix(),
        buy_report_path=None,
        market=None,
        model_provider="openai",
        model_name="gpt-test",
        model_timeout_seconds=7.5,
        source_provider="local-json",
        source_report_path=source_report.as_posix(),
    )

    assert exit_code == 0
    request_json = session.calls[0]["json"]
    assert isinstance(request_json, dict)
    user_content = request_json["input"][1]["content"]  # type: ignore[index]
    candidates = json.loads(user_content)["candidates"]
    assert candidates[0]["sources"][0]["url"] == "https://example.test/aapl"
    payload = json.loads(next(report_dir.glob("*.ai-brief.json")).read_text())
    assert payload["recommendations"][0]["sources"][0]["url"] == (
        "https://example.test/aapl"
    )


def test_run_ai_brief_openai_rejects_unprovided_source_url(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    entry_report = _write_entry_report(tmp_path)
    source_report = _write_source_report(tmp_path)
    report_dir = tmp_path / "reports"
    session = _OpenAiSession(
        {
            "recommendations": [
                {
                    "ticker": "AAPL.NAS",
                    "rank": 1,
                    "confidence": "LOW",
                    "rationale": ["source-backed context supports manual review"],
                    "checklist": ["manually confirm price and risk before order"],
                    "sources": [
                        {
                            "title": "Invented source",
                            "url": "https://example.test/not-supplied",
                            "published_at": _fresh_published_at(),
                        }
                    ],
                }
            ],
            "vetoed_candidates": [],
            "source_issues": [],
        }
    )
    monkeypatch.setenv("OPENAI_API_KEY", "test-key")
    monkeypatch.setattr(
        "sab.ai_brief.load_config",
        lambda: SimpleNamespace(report_dir=report_dir.as_posix()),
    )
    monkeypatch.setattr("sab.ai_brief_providers.requests.Session", lambda: session)

    exit_code = run_ai_brief(
        entry_report_path=entry_report.as_posix(),
        buy_report_path=None,
        market=None,
        model_provider="openai",
        model_name="gpt-test",
        model_timeout_seconds=7.5,
        source_provider="local-json",
        source_report_path=source_report.as_posix(),
    )

    assert exit_code == 0
    payload = json.loads(next(report_dir.glob("*.ai-brief.json")).read_text())
    assert payload["recommendations"] == []
    assert payload["system_issues"][0]["code"] == "model_provider_contract_error"
    assert "source url must be supplied" in payload["system_issues"][0]["message"]


def test_run_ai_brief_preserves_source_issues_when_openai_provider_fails(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    entry_report = _write_entry_report(tmp_path)
    source_report = _write_source_report(
        tmp_path,
        sources=[
            {
                "ticker": "NOT-ELIGIBLE.NAS",
                "title": "Unrelated source",
                "url": "https://example.test/not-eligible",
                "published_at": _fresh_published_at(),
            }
        ],
    )
    report_dir = tmp_path / "reports"
    monkeypatch.setenv("OPENAI_API_KEY", "test-key")
    monkeypatch.setattr(
        "sab.ai_brief.load_config",
        lambda: SimpleNamespace(report_dir=report_dir.as_posix()),
    )
    monkeypatch.setattr(
        "sab.ai_brief_providers.requests.Session", lambda: _TimeoutSession()
    )

    exit_code = run_ai_brief(
        entry_report_path=entry_report.as_posix(),
        buy_report_path=None,
        market=None,
        model_provider="openai",
        model_name="gpt-test",
        model_timeout_seconds=0.1,
        source_provider="local-json",
        source_report_path=source_report.as_posix(),
    )

    assert exit_code == 0
    payload = json.loads(next(report_dir.glob("*.ai-brief.json")).read_text())
    assert payload["recommendations"] == []
    assert payload["source_issues"][0]["code"] == "local_source_unknown_ticker"
    assert payload["system_issues"][0]["code"] == "model_provider_timeout"


def test_run_ai_brief_openai_timeout_writes_empty_artifact_with_system_issue(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    entry_report = _write_entry_report(tmp_path)
    report_dir = tmp_path / "reports"
    monkeypatch.setenv("OPENAI_API_KEY", "test-key")
    monkeypatch.setattr(
        "sab.ai_brief.load_config",
        lambda: SimpleNamespace(report_dir=report_dir.as_posix()),
    )
    monkeypatch.setattr(
        "sab.ai_brief_providers.requests.Session", lambda: _TimeoutSession()
    )

    exit_code = run_ai_brief(
        entry_report_path=entry_report.as_posix(),
        buy_report_path=None,
        market=None,
        model_provider="openai",
        model_name="gpt-test",
        model_timeout_seconds=0.1,
        source_provider=None,
        source_report_path=None,
    )

    assert exit_code == 0
    payload = json.loads(next(report_dir.glob("*.ai-brief.json")).read_text())
    assert payload["recommendations"] == []
    assert payload["summary"]["recommendation_count"] == 0
    assert payload["summary"]["system_issue_count"] == 1
    assert payload["system_issues"][0]["code"] == "model_provider_timeout"
    assert payload["system_issues"][0]["severity"] == "ERROR"


def test_run_ai_brief_openai_http_error_writes_empty_artifact_with_system_issue(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    entry_report = _write_entry_report(tmp_path)
    report_dir = tmp_path / "reports"
    monkeypatch.setenv("OPENAI_API_KEY", "test-key")
    monkeypatch.setattr(
        "sab.ai_brief.load_config",
        lambda: SimpleNamespace(report_dir=report_dir.as_posix()),
    )
    monkeypatch.setattr(
        "sab.ai_brief_providers.requests.Session", lambda: _HttpErrorSession()
    )

    exit_code = run_ai_brief(
        entry_report_path=entry_report.as_posix(),
        buy_report_path=None,
        market=None,
        model_provider="openai",
        model_name="gpt-test",
        model_timeout_seconds=0.1,
        source_provider=None,
        source_report_path=None,
    )

    assert exit_code == 0
    payload = json.loads(next(report_dir.glob("*.ai-brief.json")).read_text())
    assert payload["recommendations"] == []
    assert payload["summary"]["system_issue_count"] == 1
    assert payload["system_issues"][0]["code"] == "model_provider_failed"
    assert "HTTP 503" in payload["system_issues"][0]["message"]


def test_run_ai_brief_openai_contract_error_writes_empty_artifact_with_system_issue(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    entry_report = _write_entry_report(tmp_path)
    report_dir = tmp_path / "reports"
    session = _OpenAiSession(
        {
            "recommendations": [
                {
                    "ticker": "AAPL.NAS",
                    "rank": 1,
                    "confidence": "LOW",
                    "rationale": ["entry setup remains valid on the provided data"],
                    "checklist": ["manually confirm price and risk before order"],
                    "sources": [],
                }
            ],
            "vetoed_candidates": [],
            "source_issues": [],
        }
    )
    monkeypatch.setenv("OPENAI_API_KEY", "test-key")
    monkeypatch.setattr(
        "sab.ai_brief.load_config",
        lambda: SimpleNamespace(report_dir=report_dir.as_posix()),
    )
    monkeypatch.setattr("sab.ai_brief_providers.requests.Session", lambda: session)

    exit_code = run_ai_brief(
        entry_report_path=entry_report.as_posix(),
        buy_report_path=None,
        market=None,
        model_provider="openai",
        model_name="gpt-test",
        model_timeout_seconds=0.1,
        source_provider=None,
        source_report_path=None,
    )

    assert exit_code == 0
    payload = json.loads(next(report_dir.glob("*.ai-brief.json")).read_text())
    assert payload["recommendations"] == []
    assert payload["summary"]["recommendation_count"] == 0
    assert payload["summary"]["system_issue_count"] == 1
    assert payload["system_issues"][0]["code"] == "model_provider_contract_error"


def test_run_ai_brief_openai_rejects_stale_sources(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    entry_report = _write_entry_report(tmp_path)
    report_dir = tmp_path / "reports"
    session = _OpenAiSession(
        {
            "recommendations": [
                {
                    "ticker": "AAPL.NAS",
                    "rank": 1,
                    "confidence": "LOW",
                    "rationale": ["entry setup remains valid on the provided data"],
                    "checklist": ["manually confirm price and risk before order"],
                    "sources": [
                        {
                            "title": "Old source",
                            "url": "https://example.test/old",
                            "published_at": "2000-01-01T00:00:00+00:00",
                        }
                    ],
                }
            ],
            "vetoed_candidates": [],
            "source_issues": [],
        }
    )
    monkeypatch.setenv("OPENAI_API_KEY", "test-key")
    monkeypatch.setattr(
        "sab.ai_brief.load_config",
        lambda: SimpleNamespace(report_dir=report_dir.as_posix()),
    )
    monkeypatch.setattr("sab.ai_brief_providers.requests.Session", lambda: session)

    exit_code = run_ai_brief(
        entry_report_path=entry_report.as_posix(),
        buy_report_path=None,
        market=None,
        model_provider="openai",
        model_name="gpt-test",
        model_timeout_seconds=0.1,
        source_provider=None,
        source_report_path=None,
    )

    assert exit_code == 0
    payload = json.loads(next(report_dir.glob("*.ai-brief.json")).read_text())
    assert payload["recommendations"] == []
    assert payload["system_issues"][0]["code"] == "model_provider_contract_error"
    assert "within 72h" in payload["system_issues"][0]["message"]


def test_run_ai_brief_openai_invalid_source_issue_writes_contract_error_artifact(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    entry_report = _write_entry_report(tmp_path)
    report_dir = tmp_path / "reports"
    session = _OpenAiSession(
        {
            "recommendations": [
                {
                    "ticker": "AAPL.NAS",
                    "rank": 1,
                    "confidence": "LOW",
                    "rationale": ["entry setup remains valid on the provided data"],
                    "checklist": ["manually confirm price and risk before order"],
                    "sources": [],
                }
            ],
            "vetoed_candidates": [],
            "source_issues": [
                {
                    "ticker": "AAPL.NAS",
                    "code": "openai_no_external_sources",
                    "severity": "BAD",
                    "message": "OpenAI provider was run without a news source provider.",
                }
            ],
        }
    )
    monkeypatch.setenv("OPENAI_API_KEY", "test-key")
    monkeypatch.setattr(
        "sab.ai_brief.load_config",
        lambda: SimpleNamespace(report_dir=report_dir.as_posix()),
    )
    monkeypatch.setattr("sab.ai_brief_providers.requests.Session", lambda: session)

    exit_code = run_ai_brief(
        entry_report_path=entry_report.as_posix(),
        buy_report_path=None,
        market=None,
        model_provider="openai",
        model_name="gpt-test",
        model_timeout_seconds=0.1,
        source_provider=None,
        source_report_path=None,
    )

    assert exit_code == 0
    payload = json.loads(next(report_dir.glob("*.ai-brief.json")).read_text())
    assert payload["recommendations"] == []
    assert payload["system_issues"][0]["code"] == "model_provider_contract_error"


def test_run_ai_brief_openai_rejects_unknown_vetoed_candidate(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    entry_report = _write_entry_report(tmp_path)
    report_dir = tmp_path / "reports"
    session = _OpenAiSession(
        {
            "recommendations": [],
            "vetoed_candidates": [
                {
                    "ticker": "MSFT.NAS",
                    "action": "SKIP",
                    "reason": "model tried to veto an ineligible ticker",
                }
            ],
            "source_issues": [],
        }
    )
    monkeypatch.setenv("OPENAI_API_KEY", "test-key")
    monkeypatch.setattr(
        "sab.ai_brief.load_config",
        lambda: SimpleNamespace(report_dir=report_dir.as_posix()),
    )
    monkeypatch.setattr("sab.ai_brief_providers.requests.Session", lambda: session)

    exit_code = run_ai_brief(
        entry_report_path=entry_report.as_posix(),
        buy_report_path=None,
        market=None,
        model_provider="openai",
        model_name="gpt-test",
        model_timeout_seconds=0.1,
        source_provider=None,
        source_report_path=None,
    )

    assert exit_code == 0
    payload = json.loads(next(report_dir.glob("*.ai-brief.json")).read_text())
    assert payload["vetoed_candidates"] == []
    assert payload["system_issues"][0]["code"] == "model_provider_contract_error"


def test_run_ai_brief_openai_requires_real_model_name(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    entry_report = _write_entry_report(tmp_path)
    report_dir = tmp_path / "reports"
    monkeypatch.setenv("OPENAI_API_KEY", "test-key")
    monkeypatch.setattr(
        "sab.ai_brief.load_config",
        lambda: SimpleNamespace(report_dir=report_dir.as_posix()),
    )

    exit_code = run_ai_brief(
        entry_report_path=entry_report.as_posix(),
        buy_report_path=None,
        market=None,
        model_provider="openai",
        model_name="fake-ai-brief-v1",
        model_timeout_seconds=None,
        source_provider=None,
        source_report_path=None,
    )

    assert exit_code == 1
    assert list(report_dir.glob("*.ai-brief.json")) == []


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
        "model_timeout_seconds": None,
        "source_provider": None,
        "source_report_path": None,
    }


def test_main_routes_openai_ai_brief_options(monkeypatch: pytest.MonkeyPatch) -> None:
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
            "--model-provider",
            "openai",
            "--model-name",
            "gpt-test",
            "--model-timeout-seconds",
            "3.5",
            "--source-provider",
            "local-json",
            "--source-report",
            "reports/source.sources.json",
        ]
    )

    assert exit_code == 0
    assert captured == {
        "entry_report_path": "reports/source.entry.json",
        "buy_report_path": None,
        "market": None,
        "model_provider": "openai",
        "model_name": "gpt-test",
        "model_timeout_seconds": 3.5,
        "source_provider": "local-json",
        "source_report_path": "reports/source.sources.json",
    }
