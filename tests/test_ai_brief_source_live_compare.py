from __future__ import annotations

import datetime as dt
import json
from pathlib import Path

import pytest
from sab import ai_brief_source_live_compare as live_compare
from sab.ai_brief_sources import (
    AiBriefSourceProviderResult,
    AiBriefSourceProviderTimeoutError,
)
from scripts.compare_ai_brief_live_sources import main as live_compare_main

EVAL_NOW = dt.datetime(2026, 5, 13, 9, 0, tzinfo=dt.UTC)


def _write_entry_report(
    tmp_path: Path,
    *,
    market: str,
    entries: list[dict[str, object]],
) -> Path:
    path = tmp_path / "source.entry.json"
    payload: dict[str, object] = {
        "schema": "sab.report.v1",
        "type": "entry",
        "market": market,
        "entries": entries,
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
                    {"ticker": "005930", "name": "삼성전자"},
                    {"ticker": "AAPL.NAS", "name": "Apple"},
                ],
            }
        ),
        encoding="utf-8",
    )
    return path


def _enter_row(ticker: str, *, action: str = "ENTER") -> dict[str, object]:
    return {
        "ticker": ticker,
        "action": action,
    }


def _source(title: str, url: str) -> dict[str, object]:
    return {
        "title": title,
        "url": url,
        "published_at": (EVAL_NOW - dt.timedelta(hours=1)).isoformat(),
    }


def test_live_source_spec_parser_binds_single_http_json_to_env(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("AI_BRIEF_SOURCE_API_URL", "https://source.example/api")

    specs = live_compare.parse_live_source_provider_specs(
        provider_values=["json=http-json", "polygon=polygon-news"],
        source_api_url_values=[],
    )

    assert specs == [
        live_compare.AiBriefLiveSourceProviderSpec(
            label="json",
            provider="http-json",
            source_api_url="https://source.example/api",
        ),
        live_compare.AiBriefLiveSourceProviderSpec(
            label="polygon",
            provider="polygon-news",
            source_api_url=None,
        ),
    ]


def test_live_source_spec_parser_accepts_alpha_vantage_news_provider() -> None:
    specs = live_compare.parse_live_source_provider_specs(
        provider_values=["av=alpha-vantage-news", "polygon=polygon-news"],
        source_api_url_values=[],
    )

    assert specs == [
        live_compare.AiBriefLiveSourceProviderSpec(
            label="av",
            provider="alpha-vantage-news",
            source_api_url=None,
        ),
        live_compare.AiBriefLiveSourceProviderSpec(
            label="polygon",
            provider="polygon-news",
            source_api_url=None,
        ),
    ]


def test_live_source_spec_parser_accepts_marketaux_news_provider() -> None:
    specs = live_compare.parse_live_source_provider_specs(
        provider_values=["marketaux=marketaux-news", "polygon=polygon-news"],
        source_api_url_values=[],
    )

    assert specs == [
        live_compare.AiBriefLiveSourceProviderSpec(
            label="marketaux",
            provider="marketaux-news",
            source_api_url=None,
        ),
        live_compare.AiBriefLiveSourceProviderSpec(
            label="polygon",
            provider="polygon-news",
            source_api_url=None,
        ),
    ]


@pytest.mark.parametrize(
    ("provider_values", "source_api_url_values", "message"),
    [
        (["only=finnhub"], [], "at least two"),
        (["bad label=finnhub", "naver=naver-news"], [], "label"),
        (["same=finnhub", "same=naver-news"], [], "duplicate"),
        (["same=finnhub", "SAME=naver-news"], [], "duplicate"),
        (["rss=rss", "naver=naver-news"], [], "provider"),
        (["json", "naver=naver-news"], [], "LABEL=VALUE"),
        (["json=", "naver=naver-news"], [], "value"),
        (
            ["json=http-json", "naver=naver-news"],
            ["missing=https://source.example/api"],
            "unknown",
        ),
        (
            ["json=http-json", "naver=naver-news"],
            [
                "json=https://source.example/api",
                "JSON=https://other-source.example/api",
            ],
            "duplicate",
        ),
        (
            ["finnhub=finnhub", "naver=naver-news"],
            ["finnhub=https://source.example/api"],
            "http-json",
        ),
        (
            ["json=http-json", "other-json=http-json"],
            [],
            "http-json providers require",
        ),
    ],
)
def test_live_source_spec_parser_rejects_invalid_specs(
    monkeypatch: pytest.MonkeyPatch,
    provider_values: list[str],
    source_api_url_values: list[str],
    message: str,
) -> None:
    monkeypatch.delenv("AI_BRIEF_SOURCE_API_URL", raising=False)

    with pytest.raises(ValueError, match=message):
        live_compare.parse_live_source_provider_specs(
            provider_values=provider_values,
            source_api_url_values=source_api_url_values,
        )


def test_live_source_compare_captures_providers_and_preserves_naver_names(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    entry_report = _write_entry_report(
        tmp_path,
        market="KR",
        entries=[_enter_row("005930"), _enter_row("000660", action="REVIEW")],
    )
    buy_report = _write_buy_report(tmp_path)
    output_dir = tmp_path / "live-sources"
    calls: list[dict[str, object]] = []

    def fake_load_ai_brief_sources(**kwargs: object) -> AiBriefSourceProviderResult:
        calls.append(kwargs)
        provider = kwargs["source_provider"]
        if provider == "naver-news":
            title = "Naver Samsung source"
            url = "https://news.example/naver-samsung"
        else:
            title = "HTTP Samsung source"
            url = "https://news.example/http-samsung"
        return AiBriefSourceProviderResult(
            sources_by_ticker={"005930": [_source(title, url)]},
            source_issues=[],
        )

    monkeypatch.setattr(
        live_compare,
        "load_ai_brief_sources",
        fake_load_ai_brief_sources,
    )

    result = live_compare.compare_ai_brief_live_sources(
        entry_report_path=entry_report.as_posix(),
        provider_specs=[
            live_compare.AiBriefLiveSourceProviderSpec(
                label="naver",
                provider="naver-news",
            ),
            live_compare.AiBriefLiveSourceProviderSpec(
                label="json",
                provider="http-json",
                source_api_url="https://source.example/api",
            ),
        ],
        buy_report_path=buy_report.as_posix(),
        market=None,
        source_timeout_seconds=4.5,
        minimum_coverage_ratio=1.0,
        now=EVAL_NOW,
        output_dir=output_dir.as_posix(),
    )

    assert result.status == "PASS"
    assert result.summary["pass_count"] == 2
    assert [report["label"] for report in result.reports] == ["naver", "json"]
    assert [report.label for report in result.source_reports] == ["naver", "json"]
    assert calls[0]["eligible_tickers"] == {"005930"}
    assert calls[0]["ticker_names"] == {"005930": "삼성전자"}
    assert calls[0]["source_timeout_seconds"] == 4.5
    assert calls[1]["source_api_url"] == "https://source.example/api"

    naver_payload = json.loads(Path(result.source_reports[0].path).read_text())
    assert naver_payload["schema"] == "sab.ai_brief_sources.v1"
    assert naver_payload["type"] == "ai_brief_sources"
    assert naver_payload["label"] == "naver"
    assert naver_payload["provider"] == "naver-news"
    assert naver_payload["status"] == "PASS"
    assert naver_payload["sources"] == [
        {
            "ticker": "005930",
            "title": "Naver Samsung source",
            "url": "https://news.example/naver-samsung",
            "published_at": "2026-05-13T08:00:00+00:00",
        }
    ]
    assert Path(result.source_reports[0].path).parent == output_dir

    json_payload = json.loads(Path(result.source_reports[1].path).read_text())
    assert json_payload["label"] == "json"
    assert json_payload["provider"] == "http-json"
    assert json_payload["status"] == "PASS"
    assert json_payload["summary"] == {
        "source_count": 1,
        "covered_ticker_count": 1,
        "covered_tickers": ["005930"],
        "issue_count": 0,
    }
    assert json_payload["sources"] == [
        {
            "ticker": "005930",
            "title": "HTTP Samsung source",
            "url": "https://news.example/http-samsung",
            "published_at": "2026-05-13T08:00:00+00:00",
        }
    ]


def test_live_source_compare_captures_marketaux_news_provider(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    entry_report = _write_entry_report(
        tmp_path,
        market="US",
        entries=[_enter_row("AAPL.NAS")],
    )
    calls: list[dict[str, object]] = []

    def fake_load_ai_brief_sources(**kwargs: object) -> AiBriefSourceProviderResult:
        calls.append(kwargs)
        provider = kwargs["source_provider"]
        title = (
            "Marketaux Apple source"
            if provider == "marketaux-news"
            else "HTTP Apple source"
        )
        return AiBriefSourceProviderResult(
            sources_by_ticker={
                "AAPL.NAS": [_source(title, "https://news.example/aapl")]
            },
            source_issues=[],
        )

    monkeypatch.setattr(
        live_compare,
        "load_ai_brief_sources",
        fake_load_ai_brief_sources,
    )

    result = live_compare.compare_ai_brief_live_sources(
        entry_report_path=entry_report.as_posix(),
        provider_specs=[
            live_compare.AiBriefLiveSourceProviderSpec(
                label="marketaux",
                provider="marketaux-news",
            ),
            live_compare.AiBriefLiveSourceProviderSpec(
                label="json",
                provider="http-json",
                source_api_url="https://source.example/api",
            ),
        ],
        now=EVAL_NOW,
        output_dir=(tmp_path / "live-sources").as_posix(),
    )

    assert result.status == "PASS"
    assert calls[0]["source_provider"] == "marketaux-news"
    assert calls[0]["eligible_tickers"] == {"AAPL.NAS"}
    payload = json.loads(Path(result.source_reports[0].path).read_text())
    assert payload["provider"] == "marketaux-news"
    assert payload["sources"][0]["title"] == "Marketaux Apple source"


def test_live_source_compare_records_provider_failure_as_failed_report(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    entry_report = _write_entry_report(
        tmp_path,
        market="US",
        entries=[_enter_row("AAPL.NAS")],
    )

    def fake_load_ai_brief_sources(**kwargs: object) -> AiBriefSourceProviderResult:
        if kwargs["source_provider"] == "polygon-news":
            raise AiBriefSourceProviderTimeoutError(
                "Polygon News source request timed out"
            )
        return AiBriefSourceProviderResult(
            sources_by_ticker={
                "AAPL.NAS": [_source("HTTP Apple source", "https://news.example/aapl")]
            },
            source_issues=[],
        )

    monkeypatch.setattr(
        live_compare,
        "load_ai_brief_sources",
        fake_load_ai_brief_sources,
    )

    result = live_compare.compare_ai_brief_live_sources(
        entry_report_path=entry_report.as_posix(),
        provider_specs=[
            live_compare.AiBriefLiveSourceProviderSpec(
                label="json",
                provider="http-json",
                source_api_url="https://source.example/api",
            ),
            live_compare.AiBriefLiveSourceProviderSpec(
                label="polygon",
                provider="polygon-news",
            ),
        ],
        now=EVAL_NOW,
        output_dir=(tmp_path / "live-sources").as_posix(),
    )

    assert result.status == "FAIL"
    assert result.summary["fail_count"] == 1
    assert result.source_reports[1].status == "FAIL"
    failure_payload = json.loads(Path(result.source_reports[1].path).read_text())
    assert failure_payload["sources"] == []
    assert failure_payload["issues"] == [
        {
            "ticker": None,
            "code": "source_provider_timeout",
            "severity": "ERROR",
            "message": "Polygon News source request timed out",
        }
    ]


def test_live_source_compare_rejects_invalid_timeout_before_provider_calls(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    entry_report = _write_entry_report(
        tmp_path,
        market="US",
        entries=[_enter_row("AAPL.NAS")],
    )

    def fail_load_ai_brief_sources(**_kwargs: object) -> AiBriefSourceProviderResult:
        raise AssertionError("invalid CLI input should fail before provider calls")

    monkeypatch.setattr(
        live_compare,
        "load_ai_brief_sources",
        fail_load_ai_brief_sources,
    )

    with pytest.raises(ValueError, match="source_timeout_seconds"):
        live_compare.compare_ai_brief_live_sources(
            entry_report_path=entry_report.as_posix(),
            provider_specs=[
                live_compare.AiBriefLiveSourceProviderSpec(
                    label="json",
                    provider="http-json",
                    source_api_url="https://source.example/api",
                ),
                live_compare.AiBriefLiveSourceProviderSpec(
                    label="finnhub",
                    provider="finnhub",
                ),
            ],
            source_timeout_seconds=0,
            now=EVAL_NOW,
            output_dir=(tmp_path / "live-sources").as_posix(),
        )


def test_live_source_compare_skips_live_providers_when_no_eligible_tickers(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    entry_report = _write_entry_report(
        tmp_path,
        market="US",
        entries=[_enter_row("AAPL.NAS", action="REVIEW")],
    )

    def fail_load_ai_brief_sources(**_kwargs: object) -> AiBriefSourceProviderResult:
        raise AssertionError("no eligible tickers should skip live provider calls")

    monkeypatch.setattr(
        live_compare,
        "load_ai_brief_sources",
        fail_load_ai_brief_sources,
    )

    result = live_compare.compare_ai_brief_live_sources(
        entry_report_path=entry_report.as_posix(),
        provider_specs=[
            live_compare.AiBriefLiveSourceProviderSpec(
                label="json",
                provider="http-json",
                source_api_url="https://source.example/api",
            ),
            live_compare.AiBriefLiveSourceProviderSpec(
                label="finnhub",
                provider="finnhub",
            ),
        ],
        buy_report_path=(tmp_path / "missing.buy.json").as_posix(),
        now=EVAL_NOW,
        output_dir=(tmp_path / "live-sources").as_posix(),
    )

    assert result.status == "FAIL"
    assert [report.status for report in result.source_reports] == ["FAIL", "FAIL"]
    report_issues = result.reports[0]["issues"]
    assert isinstance(report_issues, list)
    assert report_issues[0]["code"] == "entry_report_no_eligible_tickers"
    payload = json.loads(Path(result.source_reports[0].path).read_text())
    assert payload["sources"] == []
    assert payload["issues"] == [
        {
            "ticker": None,
            "code": "entry_report_no_eligible_tickers",
            "severity": "ERROR",
            "message": "entry report contains no ENTER candidates to compare",
        }
    ]


def test_live_source_compare_script_outputs_json_and_returns_nonzero_for_fail(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    class FakeResult:
        status = "FAIL"

        def to_dict(self) -> dict[str, object]:
            return {
                "status": "FAIL",
                "summary": {"fail_count": 1},
                "reports": [],
                "source_reports": [],
            }

    captured_kwargs: dict[str, object] = {}

    def fake_compare(**kwargs: object) -> FakeResult:
        captured_kwargs.update(kwargs)
        return FakeResult()

    monkeypatch.setattr(
        live_compare,
        "compare_ai_brief_live_sources",
        fake_compare,
    )

    exit_code = live_compare_main(
        [
            "--entry-report",
            "reports/example.entry.json",
            "--provider",
            "json=http-json",
            "--provider",
            "polygon=polygon-news",
            "--source-api-url",
            "json=https://source.example/api",
            "--output-dir",
            tmp_path.as_posix(),
            "--now",
            "2026-05-13T09:00:00+00:00",
            "--pretty",
        ]
    )

    out = capsys.readouterr().out
    assert exit_code == 1
    assert out.startswith("{\n  ")
    assert json.loads(out)["status"] == "FAIL"
    assert captured_kwargs["entry_report_path"] == "reports/example.entry.json"
    assert captured_kwargs["output_dir"] == tmp_path.as_posix()
    assert captured_kwargs["now"] == EVAL_NOW
    assert captured_kwargs["provider_specs"] == [
        live_compare.AiBriefLiveSourceProviderSpec(
            label="json",
            provider="http-json",
            source_api_url="https://source.example/api",
        ),
        live_compare.AiBriefLiveSourceProviderSpec(
            label="polygon",
            provider="polygon-news",
        ),
    ]


def test_live_source_compare_script_returns_zero_for_pass(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    class FakeResult:
        status = "PASS"

        def to_dict(self) -> dict[str, object]:
            return {
                "status": "PASS",
                "summary": {"pass_count": 2},
                "reports": [],
                "source_reports": [],
            }

    monkeypatch.setattr(
        live_compare,
        "compare_ai_brief_live_sources",
        lambda **_kwargs: FakeResult(),
    )

    exit_code = live_compare_main(
        [
            "--entry-report",
            "reports/example.entry.json",
            "--provider",
            "json=http-json",
            "--provider",
            "polygon=polygon-news",
            "--source-api-url",
            "json=https://source.example/api",
        ]
    )

    out = capsys.readouterr().out
    assert exit_code == 0
    assert not out.startswith("{\n")
    assert json.loads(out)["status"] == "PASS"


def test_live_source_compare_script_returns_zero_for_warn(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    class FakeResult:
        status = "WARN"

        def to_dict(self) -> dict[str, object]:
            return {
                "status": "WARN",
                "summary": {"warn_count": 1},
                "reports": [],
                "source_reports": [],
            }

    monkeypatch.setattr(
        live_compare,
        "compare_ai_brief_live_sources",
        lambda **_kwargs: FakeResult(),
    )

    exit_code = live_compare_main(
        [
            "--entry-report",
            "reports/example.entry.json",
            "--provider",
            "finnhub=finnhub",
            "--provider",
            "naver=naver-news",
        ]
    )

    out = capsys.readouterr().out
    assert exit_code == 0
    assert json.loads(out)["status"] == "WARN"
