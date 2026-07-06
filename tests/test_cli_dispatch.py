import argparse
from types import SimpleNamespace

import pytest
import sab.__main__ as sab_main
from sab.scheduler.runner import ScheduledAiBriefRequest
from sab.scheduler.sell_ai_brief_delivery import (
    ScheduledSellAiBriefDeliveryRequest,
)


class HelpTrackingParser(argparse.ArgumentParser):
    def __init__(self) -> None:
        super().__init__(prog="sab-test")
        self.help_printed = False

    def print_help(self, file=None) -> None:
        self.help_printed = True


def _parse_args(args: list[str]) -> argparse.Namespace:
    return sab_main._build_parser().parse_args(args)


def test_dispatch_command_routes_scan_options(monkeypatch) -> None:
    calls: list[dict[str, object]] = []

    def run_scan(**kwargs) -> int:
        calls.append(kwargs)
        return 17

    monkeypatch.setattr(sab_main, "run_scan", run_scan)

    ns = _parse_args(
        [
            "scan",
            "--limit",
            "3",
            "--watchlist",
            "watchlist.txt",
            "--provider",
            "pykrx",
            "--screener-limit",
            "10",
            "--universe",
            "both",
            "--markets",
            "KR,US",
        ]
    )

    assert sab_main._dispatch_command(ns, argparse.ArgumentParser()) == 17
    assert calls == [
        {
            "limit": 3,
            "watchlist_path": "watchlist.txt",
            "provider": "pykrx",
            "screener_limit": 10,
            "universe": "both",
            "markets": "KR,US",
        }
    ]


def test_dispatch_command_routes_sell_options(monkeypatch) -> None:
    calls: list[dict[str, object]] = []

    def run_sell(**kwargs) -> int:
        calls.append(kwargs)
        return 19

    monkeypatch.setattr(sab_main, "run_sell", run_sell)

    ns = _parse_args(
        [
            "sell",
            "--provider",
            "kis",
            "--holdings",
            "holdings.generated.yaml",
        ]
    )

    assert sab_main._dispatch_command(ns, argparse.ArgumentParser()) == 19
    assert calls == [
        {
            "provider": "kis",
            "holdings_path": "holdings.generated.yaml",
        }
    ]


def test_dispatch_command_routes_entry_options(monkeypatch) -> None:
    calls: list[dict[str, object]] = []

    def run_entry(**kwargs) -> int:
        calls.append(kwargs)
        return 29

    monkeypatch.setattr(sab_main, "run_entry", run_entry)

    ns = _parse_args(
        [
            "entry",
            "--buy-report",
            "reports/2026-06-13.buy.json",
            "--provider",
            "kis",
            "--mode",
            "PRE_OPEN",
            "--market",
            "US",
            "--upload",
        ]
    )

    assert sab_main._dispatch_command(ns, argparse.ArgumentParser()) == 29
    assert calls == [
        {
            "buy_report_path": "reports/2026-06-13.buy.json",
            "provider": "kis",
            "mode": "PRE_OPEN",
            "market": "US",
            "upload": True,
        }
    ]


def test_dispatch_command_routes_ai_brief_options(monkeypatch) -> None:
    calls: list[dict[str, object]] = []

    def run_ai_brief(**kwargs) -> int:
        calls.append(kwargs)
        return 23

    monkeypatch.setattr(sab_main, "run_ai_brief", run_ai_brief)

    ns = _parse_args(
        [
            "ai-brief",
            "--entry-report",
            "reports/2026-06-13.entry.json",
            "--buy-report",
            "reports/2026-06-13.buy.json",
            "--market",
            "US",
            "--model-provider",
            "openai",
            "--model-name",
            "gpt-example",
            "--model-timeout-seconds",
            "15",
            "--source-provider",
            "http-json",
            "--source-report",
            "sources.json",
            "--source-api-url",
            "https://example.test/sources",
            "--source-timeout-seconds",
            "5",
            "--article-reader",
            "lightpanda",
            "--article-reader-max-urls",
            "3",
            "--article-reader-timeout-seconds",
            "4.5",
            "--article-reader-max-excerpt-chars",
            "900",
            "--report-date",
            "2026-06-13",
            "--upload",
        ]
    )

    assert sab_main._dispatch_command(ns, argparse.ArgumentParser()) == 23
    assert calls == [
        {
            "entry_report_path": "reports/2026-06-13.entry.json",
            "buy_report_path": "reports/2026-06-13.buy.json",
            "market": "US",
            "model_provider": "openai",
            "model_name": "gpt-example",
            "model_timeout_seconds": 15.0,
            "source_provider": "http-json",
            "source_report_path": "sources.json",
            "source_api_url": "https://example.test/sources",
            "source_timeout_seconds": 5.0,
            "article_reader": "lightpanda",
            "article_reader_max_urls": 3,
            "article_reader_timeout_seconds": 4.5,
            "article_reader_max_excerpt_chars": 900,
            "report_date": "2026-06-13",
            "upload": True,
        }
    ]


def test_dispatch_command_routes_sell_ai_brief_options(monkeypatch) -> None:
    calls: list[dict[str, object]] = []

    def run_sell_ai_brief(**kwargs) -> int:
        calls.append(kwargs)
        return 41

    monkeypatch.setattr(sab_main, "run_sell_ai_brief", run_sell_ai_brief)

    ns = _parse_args(
        [
            "sell-ai-brief",
            "--sell-report",
            "reports/2026-06-13.sell.json",
            "--model-provider",
            "openai",
            "--model-name",
            "gpt-example",
            "--model-timeout-seconds",
            "15",
            "--source-provider",
            "http-json",
            "--source-report",
            "sources.json",
            "--source-api-url",
            "https://example.test/sources",
            "--source-timeout-seconds",
            "5",
            "--article-reader",
            "lightpanda",
            "--article-reader-max-urls",
            "3",
            "--article-reader-timeout-seconds",
            "4.5",
            "--article-reader-max-excerpt-chars",
            "900",
            "--report-date",
            "2026-06-13",
            "--upload",
        ]
    )

    assert sab_main._dispatch_command(ns, argparse.ArgumentParser()) == 41
    assert calls == [
        {
            "sell_report_path": "reports/2026-06-13.sell.json",
            "model_provider": "openai",
            "model_name": "gpt-example",
            "model_timeout_seconds": 15.0,
            "source_provider": "http-json",
            "source_report_path": "sources.json",
            "source_api_url": "https://example.test/sources",
            "source_timeout_seconds": 5.0,
            "article_reader": "lightpanda",
            "article_reader_max_urls": 3,
            "article_reader_timeout_seconds": 4.5,
            "article_reader_max_excerpt_chars": 900,
            "report_date": "2026-06-13",
            "upload": True,
        }
    ]


def test_dispatch_command_routes_ai_brief_latency_probe_options(monkeypatch) -> None:
    calls: list[dict[str, object]] = []

    def run_probe(**kwargs) -> int:
        calls.append(kwargs)
        return 37

    monkeypatch.setattr(
        sab_main,
        "ai_brief_latency_probe",
        SimpleNamespace(run_probe=run_probe),
        raising=False,
    )

    ns = _parse_args(
        [
            "ai-brief-latency-probe",
            "--primary-model",
            "gpt-5.5",
            "--fallback-model",
            "gpt-5.4-mini",
            "--repetitions",
            "2",
        ]
    )

    assert sab_main._dispatch_command(ns, argparse.ArgumentParser()) == 37
    assert calls == [
        {
            "primary_model": "gpt-5.5",
            "fallback_model": "gpt-5.4-mini",
            "repetitions": 2,
        }
    ]


@pytest.mark.parametrize("repetitions", ["0", "4"])
def test_ai_brief_latency_probe_repetitions_parse_error(repetitions: str) -> None:
    with pytest.raises(SystemExit) as exc_info:
        _parse_args(
            [
                "ai-brief-latency-probe",
                "--primary-model",
                "gpt-5.5",
                "--repetitions",
                repetitions,
            ]
        )

    assert exc_info.value.code == 2


def test_dispatch_command_routes_scheduled_ai_brief_options(monkeypatch) -> None:
    calls: list[dict[str, object]] = []

    def run_scheduled_ai_brief(
        *,
        request: ScheduledAiBriefRequest,
        guard_only: bool,
    ) -> int:
        calls.append({"request": request, "guard_only": guard_only})
        return 31

    monkeypatch.setattr(sab_main, "run_scheduled_ai_brief", run_scheduled_ai_brief)

    ns = _parse_args(
        [
            "ai-brief-scheduled",
            "--market",
            "KR",
            "--schedule-role",
            "early-monitor",
            "--runner-role",
            "local-primary",
            "--scheduled-tick",
            "2026-06-13T08:00:00+09:00",
            "--attempt-id",
            "attempt-1",
            "--run-url",
            "https://github.example/runs/1",
            "--source-provider",
            "naver-news",
            "--model-provider",
            "fake",
            "--dry-run",
            "--guard-only",
        ]
    )

    assert sab_main._dispatch_command(ns, argparse.ArgumentParser()) == 31
    assert calls == [
        {
            "request": ScheduledAiBriefRequest(
                market="KR",
                schedule_role="early-monitor",
                runner_role="local-primary",
                scheduled_tick="2026-06-13T08:00:00+09:00",
                attempt_id="attempt-1",
                dry_run=True,
                run_url="https://github.example/runs/1",
                source_provider="naver-news",
                model_provider="fake",
            ),
            "guard_only": True,
        }
    ]
    request = calls[0]["request"]
    assert not hasattr(request, "fallback_model")
    assert not hasattr(request, "fallback_timeout_seconds")


def test_dispatch_command_routes_scheduled_sell_ai_brief_options(
    monkeypatch,
) -> None:
    calls: list[dict[str, object]] = []

    def run_scheduled_sell_ai_brief_delivery(
        *,
        request: ScheduledSellAiBriefDeliveryRequest,
    ) -> int:
        calls.append({"request": request})
        return 43

    monkeypatch.setattr(
        sab_main,
        "run_scheduled_sell_ai_brief_delivery",
        run_scheduled_sell_ai_brief_delivery,
        raising=False,
    )

    ns = _parse_args(
        [
            "sell-ai-brief-scheduled",
            "--sell-ai-brief-report",
            "reports/2026-07-06.sell-ai-brief.json",
            "--scope",
            "MIXED",
            "--session-date",
            "2026-07-06",
            "--runner-role",
            "local-primary",
            "--scheduled-tick",
            "manual",
            "--attempt-id",
            "try-1",
            "--run-url",
            "https://example.test/run",
            "--dry-run",
        ]
    )

    assert sab_main._dispatch_command(ns, argparse.ArgumentParser()) == 43
    assert calls == [
        {
            "request": ScheduledSellAiBriefDeliveryRequest(
                sell_ai_brief_report_path="reports/2026-07-06.sell-ai-brief.json",
                scope="MIXED",
                session_date="2026-07-06",
                runner_role="local-primary",
                scheduled_tick="manual",
                attempt_id="try-1",
                run_url="https://example.test/run",
                dry_run=True,
            )
        }
    ]


def test_run_scheduled_sell_ai_brief_delivery_maps_status_to_exit_code(
    monkeypatch,
) -> None:
    statuses_to_expected = {
        "artifact_invalid": 1,
        "artifact_marker_invalid": 1,
        "lock_lost_before_upload": 1,
        "notification_sent_marker_invalid": 1,
        "notification_sent_marker_failed": 1,
        "upload_failed": 1,
        "dry_run": 0,
        "success_marker_skip": 0,
        "lock_held_skip": 0,
        "completed": 0,
        "completion_repaired": 0,
        "notification_claim_held": 0,
        "notification_reconciled": 0,
    }

    class FakeRunner:
        def __init__(self, *, status: str) -> None:
            self._status = status

        def run(
            self,
            request: ScheduledSellAiBriefDeliveryRequest,
        ) -> SimpleNamespace:
            assert (
                request.sell_ai_brief_report_path
                == "reports/2026-07-06.sell-ai-brief.json"
            )
            return SimpleNamespace(
                status=self._status,
                session_date="2026-07-06",
                storage_key="reports/2026-07-06.sell-ai-brief.json",
            )

    monkeypatch.setattr(
        sab_main.ScheduledSellAiBriefDeliveryRunner,
        "__init__",
        lambda self, *, state_store, storage, notifier: None,
    )
    monkeypatch.setattr(
        sab_main.ScheduledSellAiBriefDeliveryRunner,
        "run",
        lambda self, request: FakeRunner(status=self._status).run(request),  # type: ignore[attr-defined]
        raising=False,
    )
    monkeypatch.setattr(
        sab_main.SupabaseRuntimeStateClient,
        "from_env",
        classmethod(lambda cls: object()),
    )
    monkeypatch.setattr(
        sab_main.DefaultScheduledStorage,
        "from_env",
        classmethod(lambda cls: object()),
    )
    monkeypatch.setattr(
        sab_main, "_write_scheduled_sell_ai_brief_status_file", lambda **kwargs: None
    )

    request = ScheduledSellAiBriefDeliveryRequest(
        sell_ai_brief_report_path="reports/2026-07-06.sell-ai-brief.json"
    )
    for status, expected_exit in statuses_to_expected.items():
        monkeypatch.setattr(
            sab_main.ScheduledSellAiBriefDeliveryRunner,
            "run",
            lambda self, request, *, _status=status: SimpleNamespace(
                status=_status,
                session_date="2026-07-06",
                storage_key="reports/2026-07-06.sell-ai-brief.json",
            ),
            raising=False,
        )
        assert (
            sab_main.run_scheduled_sell_ai_brief_delivery(request=request)
            == expected_exit
        )


def test_dispatch_command_prints_help_for_missing_command() -> None:
    parser = HelpTrackingParser()

    assert sab_main._dispatch_command(_parse_args([]), parser) == 2
    assert parser.help_printed is True
