from __future__ import annotations

import argparse
import datetime as dt
import json
import logging
import os
import sys
from collections.abc import Callable
from typing import Any

from . import ai_brief_latency_probe
from .ai_brief import run_ai_brief
from .entry import run_entry
from .env_loader import load_dotenv_if_available
from .observability import sanitize_log_text, structured_log_fields
from .scan import run_scan
from .scheduler import status_file
from .scheduler.runner import (
    DefaultScheduledNotifier,
    DefaultScheduledStorage,
    ScheduledAiBriefRequest,
    run_scheduled_ai_brief,
)
from .scheduler.sell_ai_brief_delivery import (
    FAILED_SCHEDULED_SELL_AI_BRIEF_DELIVERY_STATUSES,
    ScheduledSellAiBriefDeliveryRequest,
    ScheduledSellAiBriefDeliveryRunner,
)
from .scheduler.state import SupabaseRuntimeStateClient
from .sell import run_sell
from .sell_ai_brief import run_sell_ai_brief

_CommandHandler = Callable[[argparse.Namespace], int]


def _bounded_probe_repetitions(value: str) -> int:
    try:
        repetitions = int(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError("repetitions must be an integer") from exc
    if repetitions < 1 or repetitions > 3:
        raise argparse.ArgumentTypeError("repetitions must be between 1 and 3")
    return repetitions


def _normalize_log_timezone(value: str | None) -> str:
    log_tz = (value or "local").strip().lower()
    if log_tz in {"local", "utc"}:
        return log_tz
    return "local"


def _format_record_time(
    record: logging.LogRecord, *, datefmt: str | None, tz: str
) -> str:
    if tz == "utc":
        ts = dt.datetime.fromtimestamp(record.created, tz=dt.UTC)
    else:
        ts = dt.datetime.fromtimestamp(record.created).astimezone()

    if datefmt:
        return ts.strftime(datefmt)
    return ts.isoformat(timespec="milliseconds")


class _TZFormatter(logging.Formatter):
    def __init__(self, fmt: str, *, datefmt: str | None, tz: str) -> None:
        super().__init__(fmt=fmt, datefmt=datefmt)
        self._tz = tz

    def formatTime(self, record: logging.LogRecord, datefmt: str | None = None) -> str:
        return _format_record_time(record, datefmt=datefmt or self.datefmt, tz=self._tz)


class _JsonFormatter(logging.Formatter):
    def __init__(self, *, datefmt: str | None, tz: str) -> None:
        super().__init__(datefmt=datefmt)
        self._tz = tz

    def format(self, record: logging.LogRecord) -> str:
        payload = {
            "timestamp": _format_record_time(record, datefmt=self.datefmt, tz=self._tz),
            "level": record.levelname,
            "logger": record.name,
            "message": sanitize_log_text(record.getMessage()),
        }
        payload.update(structured_log_fields(record))
        if record.exc_info:
            payload["exception"] = sanitize_log_text(
                self.formatException(record.exc_info)
            )
        return json.dumps(payload, ensure_ascii=False)


class _SellAiBriefScheduledNotifier:
    def __init__(self) -> None:
        self._notifier = DefaultScheduledNotifier()

    def require_telegram(self) -> None:
        self._notifier.require_telegram()

    def send_schedule(
        self,
        *,
        report: dict[str, Any],
        storage_key: str,
        text: str,
    ) -> None:
        del report, storage_key
        self._notifier.send_telegram_html_text(text)


def _build_log_formatter(
    *, log_format: str, datefmt: str | None, tz: str
) -> logging.Formatter:
    if log_format.strip().lower() == "json":
        return _JsonFormatter(datefmt=datefmt, tz=tz)
    return _TZFormatter(log_format, datefmt=datefmt, tz=tz)


def _configure_logging() -> None:
    level_name = os.getenv("LOG_LEVEL", "INFO").upper()
    level = getattr(logging, level_name, logging.INFO)

    log_format = os.getenv(
        "LOG_FORMAT",
        "%(asctime)s %(levelname)s %(name)s - %(message)s",
    )
    log_datefmt = os.getenv("LOG_DATEFMT") or None
    log_tz = _normalize_log_timezone(os.getenv("LOG_TZ"))

    handler = logging.StreamHandler()
    formatter = _build_log_formatter(
        log_format=log_format, datefmt=log_datefmt, tz=log_tz
    )
    handler.setFormatter(formatter)
    logging.basicConfig(level=level, handlers=[handler], force=True)


def _build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="sab", description="Swing Alert Bot — on-demand report"
    )
    sub = p.add_subparsers(dest="cmd")

    s = sub.add_parser("scan", help="Collect -> evaluate -> write JSON report")
    s.add_argument(
        "--limit",
        type=int,
        default=None,
        help="Max total tickers to evaluate after universe merge",
    )
    s.add_argument("--watchlist", type=str, default=None, help="Path to watchlist file")
    s.add_argument(
        "--provider",
        type=str,
        default=None,
        choices=["kis", "pykrx"],
        help="Data provider override",
    )
    s.add_argument(
        "--screener-limit",
        type=int,
        default=None,
        help="Override screener top-N size for both KR and US",
    )
    s.add_argument(
        "--universe",
        type=str,
        default=None,
        choices=["watchlist", "screener", "both"],
        help="Universe selection: watchlist only, screener only, or both",
    )
    s.add_argument(
        "--markets",
        type=str,
        default=None,
        help="Comma-separated universe markets override (e.g. KR,US)",
    )

    sell = sub.add_parser("sell", help="Evaluate holdings against sell/review rules")
    sell.add_argument(
        "--provider",
        type=str,
        default=None,
        choices=["kis", "pykrx"],
        help="Data provider override",
    )
    sell.add_argument(
        "--holdings",
        type=str,
        default=None,
        help="Path to holdings file override",
    )

    entry = sub.add_parser(
        "entry",
        help="Evaluate buy candidates for next-session entry conditions",
    )
    entry.add_argument(
        "--buy-report",
        type=str,
        default=None,
        help="Input buy report path (defaults to latest reports/*.buy.json)",
    )
    entry.add_argument(
        "--provider",
        type=str,
        default=None,
        choices=["kis", "pykrx"],
        help="Price provider override",
    )
    entry.add_argument(
        "--mode",
        type=str,
        default=None,
        choices=["PRE_OPEN", "INTRADAY", "AFTER_CLOSE"],
        help="Entry evaluation mode",
    )
    entry.add_argument(
        "--market",
        type=str,
        default=None,
        choices=["KR", "US"],
        help="Single market override",
    )
    entry.add_argument(
        "--upload",
        action="store_true",
        help="Upload entry report to Supabase Storage/report_index",
    )

    ai_brief = sub.add_parser(
        "ai-brief",
        help="Build a local AI entry brief from an entry report",
    )
    ai_brief.add_argument(
        "--entry-report",
        type=str,
        required=True,
        help="Input entry report path",
    )
    ai_brief.add_argument(
        "--market",
        type=str,
        default=None,
        choices=["KR", "US"],
        help="Single market to brief; required for MIXED entry reports",
    )
    ai_brief.add_argument(
        "--buy-report",
        type=str,
        default=None,
        help="Optional buy report path for ticker name/reason enrichment",
    )
    ai_brief.add_argument(
        "--model-provider",
        type=str,
        default="fake",
        choices=["fake", "openai"],
        help="AI model provider for the brief",
    )
    ai_brief.add_argument(
        "--model-name",
        type=str,
        default="fake-ai-brief-v1",
        help="AI model name for the brief",
    )
    ai_brief.add_argument(
        "--model-timeout-seconds",
        type=float,
        default=None,
        help="AI model provider timeout in seconds",
    )
    ai_brief.add_argument(
        "--source-provider",
        type=str,
        default=None,
        choices=[
            "none",
            "local-json",
            "http-json",
            "finnhub",
            "polygon-news",
            "alpha-vantage-news",
            "marketaux-news",
            "benzinga-news",
            "naver-news",
        ],
        help="Optional source provider for AI brief candidate context",
    )
    ai_brief.add_argument(
        "--source-report",
        type=str,
        default=None,
        help="Optional local JSON source report path",
    )
    ai_brief.add_argument(
        "--source-api-url",
        type=str,
        default=None,
        help="Optional external source API URL when source_provider=http-json",
    )
    ai_brief.add_argument(
        "--source-timeout-seconds",
        type=float,
        default=None,
        help="External source provider timeout in seconds",
    )
    ai_brief.add_argument(
        "--article-reader",
        type=str,
        default=None,
        choices=["none", "lightpanda"],
        help="Optional article reader for AI brief source URL verification",
    )
    ai_brief.add_argument(
        "--article-reader-max-urls",
        type=int,
        default=None,
        help="Maximum source URLs to read for article verification",
    )
    ai_brief.add_argument(
        "--article-reader-timeout-seconds",
        type=float,
        default=None,
        help="Article reader timeout per URL in seconds",
    )
    ai_brief.add_argument(
        "--article-reader-max-excerpt-chars",
        type=int,
        default=None,
        help="Maximum extracted article excerpt characters per source",
    )
    ai_brief.add_argument(
        "--upload",
        action="store_true",
        help="Upload AI brief report to Supabase Storage/report_index",
    )
    ai_brief.add_argument(
        "--report-date",
        type=str,
        default=None,
        help="Override AI brief artifact report_date (YYYY-MM-DD)",
    )

    sell_ai_brief = sub.add_parser(
        "sell-ai-brief",
        help="Build a local AI sell judgment brief from a sell report",
    )
    sell_ai_brief.add_argument(
        "--sell-report",
        type=str,
        required=True,
        help="Input sell report path",
    )
    sell_ai_brief.add_argument(
        "--model-provider",
        type=str,
        default="fake",
        choices=["fake", "openai"],
        help="AI model provider for the sell brief",
    )
    sell_ai_brief.add_argument(
        "--model-name",
        type=str,
        default="fake-sell-ai-brief-v1",
        help="AI model name for the sell brief",
    )
    sell_ai_brief.add_argument(
        "--model-timeout-seconds",
        type=float,
        default=None,
        help="AI model provider timeout in seconds",
    )
    sell_ai_brief.add_argument(
        "--source-provider",
        type=str,
        default=None,
        choices=[
            "none",
            "local-json",
            "http-json",
            "finnhub",
            "polygon-news",
            "alpha-vantage-news",
            "marketaux-news",
            "benzinga-news",
            "naver-news",
        ],
        help="Optional source provider for sell candidate context",
    )
    sell_ai_brief.add_argument(
        "--source-report",
        type=str,
        default=None,
        help="Optional local JSON source report path",
    )
    sell_ai_brief.add_argument(
        "--source-api-url",
        type=str,
        default=None,
        help="Optional external source API URL when source_provider=http-json",
    )
    sell_ai_brief.add_argument(
        "--source-timeout-seconds",
        type=float,
        default=None,
        help="External source provider timeout in seconds",
    )
    sell_ai_brief.add_argument(
        "--article-reader",
        type=str,
        default=None,
        choices=["none", "lightpanda"],
        help="Optional article reader for source URL verification",
    )
    sell_ai_brief.add_argument(
        "--article-reader-max-urls",
        type=int,
        default=None,
        help="Maximum source URLs to read for article verification",
    )
    sell_ai_brief.add_argument(
        "--article-reader-timeout-seconds",
        type=float,
        default=None,
        help="Article reader timeout per URL in seconds",
    )
    sell_ai_brief.add_argument(
        "--article-reader-max-excerpt-chars",
        type=int,
        default=None,
        help="Maximum extracted article excerpt characters per source",
    )
    sell_ai_brief.add_argument(
        "--upload",
        action="store_true",
        help="Upload Sell AI brief report to Supabase Storage/report_index",
    )
    sell_ai_brief.add_argument(
        "--report-date",
        type=str,
        default=None,
        help="Override Sell AI brief artifact report_date (YYYY-MM-DD)",
    )

    scheduled = sub.add_parser(
        "ai-brief-scheduled",
        help="Run scheduled AI Brief with runtime_state idempotency guards",
    )
    scheduled.add_argument("--market", required=True, choices=["KR", "US"])
    scheduled.add_argument("--schedule-role", required=True)
    scheduled.add_argument("--runner-role", required=True)
    scheduled.add_argument("--scheduled-tick", required=True)
    scheduled.add_argument("--attempt-id", default=None)
    scheduled.add_argument("--run-url", default="")
    scheduled.add_argument("--source-provider", default=None)
    scheduled.add_argument(
        "--model-provider", default="openai", choices=["fake", "openai"]
    )
    scheduled.add_argument("--dry-run", action="store_true")
    scheduled.add_argument("--guard-only", action="store_true")

    sell_scheduled = sub.add_parser(
        "sell-ai-brief-scheduled",
        help="Deliver a scheduled Sell AI Brief with idempotent upload and notify",
    )
    sell_scheduled.add_argument(
        "--sell-ai-brief-report",
        required=True,
        help="Input sell AI brief report path",
    )
    sell_scheduled.add_argument(
        "--scope", default="MIXED", choices=["KR", "US", "MIXED"]
    )
    sell_scheduled.add_argument("--session-date", default="")
    sell_scheduled.add_argument("--runner-role", default="local-primary")
    sell_scheduled.add_argument("--scheduled-tick", default="manual")
    sell_scheduled.add_argument("--attempt-id", default=None)
    sell_scheduled.add_argument("--run-url", default="")
    sell_scheduled.add_argument("--dry-run", action="store_true")

    probe = sub.add_parser(
        "ai-brief-latency-probe",
        help="Plan bounded AI Brief latency measurements without upload or notification",
    )
    probe.add_argument("--primary-model", required=True)
    probe.add_argument("--fallback-model", default=None)
    probe.add_argument("--repetitions", type=_bounded_probe_repetitions, default=1)
    return p


def _run_scan_command(ns: argparse.Namespace) -> int:
    return run_scan(
        limit=ns.limit,
        watchlist_path=ns.watchlist,
        provider=ns.provider,
        screener_limit=ns.screener_limit,
        universe=ns.universe,
        markets=ns.markets,
    )


def _run_sell_command(ns: argparse.Namespace) -> int:
    return run_sell(provider=ns.provider, holdings_path=ns.holdings)


def _run_entry_command(ns: argparse.Namespace) -> int:
    return run_entry(
        buy_report_path=ns.buy_report,
        provider=ns.provider,
        mode=ns.mode,
        market=ns.market,
        upload=ns.upload,
    )


def _run_ai_brief_command(ns: argparse.Namespace) -> int:
    return run_ai_brief(
        entry_report_path=ns.entry_report,
        buy_report_path=ns.buy_report,
        market=ns.market,
        model_provider=ns.model_provider,
        model_name=ns.model_name,
        model_timeout_seconds=ns.model_timeout_seconds,
        source_provider=ns.source_provider,
        source_report_path=ns.source_report,
        source_api_url=ns.source_api_url,
        source_timeout_seconds=ns.source_timeout_seconds,
        article_reader=ns.article_reader,
        article_reader_max_urls=ns.article_reader_max_urls,
        article_reader_timeout_seconds=ns.article_reader_timeout_seconds,
        article_reader_max_excerpt_chars=ns.article_reader_max_excerpt_chars,
        report_date=ns.report_date,
        upload=ns.upload,
    )


def _run_sell_ai_brief_command(ns: argparse.Namespace) -> int:
    return run_sell_ai_brief(
        sell_report_path=ns.sell_report,
        model_provider=ns.model_provider,
        model_name=ns.model_name,
        model_timeout_seconds=ns.model_timeout_seconds,
        source_provider=ns.source_provider,
        source_report_path=ns.source_report,
        source_api_url=ns.source_api_url,
        source_timeout_seconds=ns.source_timeout_seconds,
        article_reader=ns.article_reader,
        article_reader_max_urls=ns.article_reader_max_urls,
        article_reader_timeout_seconds=ns.article_reader_timeout_seconds,
        article_reader_max_excerpt_chars=ns.article_reader_max_excerpt_chars,
        report_date=ns.report_date,
        upload=ns.upload,
    )


def _scheduled_ai_brief_request_from_args(
    ns: argparse.Namespace,
) -> ScheduledAiBriefRequest:
    return ScheduledAiBriefRequest(
        market=ns.market,
        schedule_role=ns.schedule_role,
        runner_role=ns.runner_role,
        scheduled_tick=ns.scheduled_tick,
        attempt_id=ns.attempt_id,
        dry_run=ns.dry_run,
        run_url=ns.run_url,
        source_provider=ns.source_provider,
        model_provider=ns.model_provider,
    )


def _run_scheduled_ai_brief_command(ns: argparse.Namespace) -> int:
    return run_scheduled_ai_brief(
        request=_scheduled_ai_brief_request_from_args(ns),
        guard_only=ns.guard_only,
    )


def _scheduled_sell_ai_brief_request_from_args(
    ns: argparse.Namespace,
) -> ScheduledSellAiBriefDeliveryRequest:
    return ScheduledSellAiBriefDeliveryRequest(
        sell_ai_brief_report_path=ns.sell_ai_brief_report,
        scope=ns.scope,
        session_date=ns.session_date,
        runner_role=ns.runner_role,
        scheduled_tick=ns.scheduled_tick,
        attempt_id=ns.attempt_id,
        run_url=ns.run_url,
        dry_run=ns.dry_run,
    )


def _write_scheduled_sell_ai_brief_status_file(
    *, status: str, session_date: str, storage_key: str | None
) -> None:
    path = os.getenv("SAB_SCHEDULER_STATUS_FILE")
    if not path:
        return
    try:
        status_file.write_status_json(
            path,
            {
                "status": status,
                "session_date": session_date,
                "storage_key": storage_key,
            },
        )
    except Exception as exc:
        logging.getLogger(__name__).warning(
            "failed to write scheduled sell AI brief status file: %s", exc
        )


def run_scheduled_sell_ai_brief_delivery(
    *,
    request: ScheduledSellAiBriefDeliveryRequest,
) -> int:
    runner = ScheduledSellAiBriefDeliveryRunner(
        state_store=SupabaseRuntimeStateClient.from_env(),
        storage=DefaultScheduledStorage.from_env(),
        notifier=_SellAiBriefScheduledNotifier(),
    )
    result = runner.run(request)
    _write_scheduled_sell_ai_brief_status_file(
        status=result.status,
        session_date=result.session_date,
        storage_key=result.storage_key,
    )
    print(
        json.dumps(
            {
                "status": result.status,
                "storage_key": result.storage_key,
            }
        )
    )
    return (
        0
        if result.status not in FAILED_SCHEDULED_SELL_AI_BRIEF_DELIVERY_STATUSES
        else 1
    )


def _run_scheduled_sell_ai_brief_command(ns: argparse.Namespace) -> int:
    return run_scheduled_sell_ai_brief_delivery(
        request=_scheduled_sell_ai_brief_request_from_args(ns)
    )


def _run_ai_brief_latency_probe_command(ns: argparse.Namespace) -> int:
    return ai_brief_latency_probe.run_probe(
        primary_model=ns.primary_model,
        fallback_model=ns.fallback_model,
        repetitions=ns.repetitions,
    )


def _dispatch_command(
    ns: argparse.Namespace,
    parser: argparse.ArgumentParser,
) -> int:
    handlers: dict[str, _CommandHandler] = {
        "scan": _run_scan_command,
        "sell": _run_sell_command,
        "entry": _run_entry_command,
        "ai-brief": _run_ai_brief_command,
        "sell-ai-brief": _run_sell_ai_brief_command,
        "ai-brief-scheduled": _run_scheduled_ai_brief_command,
        "sell-ai-brief-scheduled": _run_scheduled_sell_ai_brief_command,
        "ai-brief-latency-probe": _run_ai_brief_latency_probe_command,
    }
    handler = handlers.get(ns.cmd)
    if handler is None:
        parser.print_help()
        return 2
    return handler(ns)


def main(argv: list[str] | None = None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    load_dotenv_if_available(override=False)
    _configure_logging()
    parser = _build_parser()
    ns = parser.parse_args(argv)
    return _dispatch_command(ns, parser)


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
