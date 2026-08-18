from __future__ import annotations

import argparse
import datetime as dt
import json
import logging
import os
import sys
from collections.abc import Callable
from pathlib import Path
from typing import Any

from . import ai_brief_latency_probe
from .ai_brief import run_ai_brief
from .backtest import run_backtest
from .decision_board.cli import (
    DecisionBoardCliConfigV0,
    execute_decision_board_cli_v0,
    execute_decision_board_shadow_live_cli_v0,
)
from .decision_board.results import (
    DecisionRunIssueCodeV0,
    DecisionRunResultV0,
    create_decision_run_failed_v0,
    decision_run_exit_code_v0,
    serialize_decision_run_result_v0,
)
from .decision_board.run_journal import (
    ExpectedRunV0,
    RunJournalError,
    RunJournalStatusV0,
    RunJournalStoreV0,
)
from .decision_board.run_journal_cli import (
    JournalShadowProcessConfigV0,
    execute_journal_shadow_process_v0,
    parse_bounded_int_v0,
    parse_utc_rfc3339_v0,
    public_records_v0,
)
from .decision_board.run_journal_public import read_public_journal_status_v0
from .decision_board.runner import RunKindV0
from .decision_board.shadow_gate import (
    ShadowGateManifestError,
    load_shadow_gate_manifest_v0,
)
from .decision_board.shadow_ledger_prepare import (
    ShadowLedgerPreparationError,
    load_shadow_evaluation_case_plan_v0,
    prepare_shadow_evaluation_ledgers_v0,
)
from .entry import run_entry
from .env_loader import load_dotenv_if_available
from .observability import sanitize_log_text, structured_log_fields
from .scan import run_scan
from .scheduler import status_file
from .scheduler.holdings import (
    SupabaseHoldingsExportConfig,
    SupabaseHoldingsExportError,
    export_active_holdings_snapshot,
)
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
from .scheduler.sell_ai_brief_generation import (
    FAILED_SCHEDULED_SELL_AI_BRIEF_GENERATION_STATUSES,
    ScheduledSellAiBriefGenerationRequest,
    ScheduledSellAiBriefGenerationRunner,
)
from .scheduler.state import SupabaseRuntimeStateClient
from .sell import SellRunResult, run_sell, run_sell_with_result
from .sell_ai_brief import run_sell_ai_brief, run_sell_ai_brief_with_result
from .sell_ai_brief_eval import evaluate_sell_ai_brief_report

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


class _SellAiBriefGenerationNotifier:
    def __init__(self) -> None:
        self._notifier = DefaultScheduledNotifier()

    def send_blocked(self, *, scope: str, session_date: str, reason: str) -> None:
        text = (
            "SAB Sell AI Brief 보류\n"
            f"사유: {reason}\n"
            f"session {session_date} · scope {scope}\n"
            "정상 매도 판단은 생성하지 않았습니다."
        )
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

    decision_board = sub.add_parser(
        "decision-board",
        help="Run one local notification-free Decision Board shadow decision",
    )
    decision_board.add_argument("--run-kind", required=True)
    decision_board.add_argument("--run-id", required=True)
    decision_board.add_argument("--idempotency-key", required=True)
    decision_board.add_argument("--created-at", required=True)
    decision_board.add_argument("--sealed-input-hash", required=True)
    decision_board.add_argument(
        "--upload-mode",
        default="disabled",
    )
    decision_board.add_argument("--report-dir", default="reports")

    decision_board_live = sub.add_parser(
        "decision-board-shadow-live",
        help="Run one explicitly configured live-provider Decision Board shadow decision",
    )
    decision_board_live.add_argument("--run-kind", required=True)
    decision_board_live.add_argument("--run-id", required=True)
    decision_board_live.add_argument("--idempotency-key", required=True)
    decision_board_live.add_argument("--created-at", required=True)
    decision_board_live.add_argument("--sealed-input-hash", required=True)
    decision_board_live.add_argument("--gate-manifest", required=True)
    decision_board_live.add_argument("--gate-manifest-sha256", required=True)
    decision_board_live.add_argument("--input-ledger", required=True)
    decision_board_live.add_argument("--expected-action-ledger", required=True)
    decision_board_live.add_argument(
        "--upload-mode",
        default="disabled",
    )
    decision_board_live.add_argument("--report-dir", default="reports")

    shadow_gate = sub.add_parser(
        "decision-board-shadow-gate-validate",
        help="Validate one frozen Decision Board shadow gate manifest",
    )
    shadow_gate.add_argument("--manifest", required=True)
    shadow_gate.add_argument("--input-ledger", default=None)
    shadow_gate.add_argument("--expected-action-ledger", default=None)
    shadow_gate.add_argument("--require-approved", action="store_true")

    shadow_ledger_prepare = sub.add_parser(
        "decision-board-shadow-ledger-prepare",
        help="Prepare canonical local shadow ledgers without approval or live access",
    )
    shadow_ledger_prepare.add_argument("--manifest", required=True)
    shadow_ledger_prepare.add_argument("--case-plan", required=True)
    shadow_ledger_prepare.add_argument("--output-dir", required=True)

    journal_status = sub.add_parser(
        "decision-board-journal-status",
        help="Read bounded sanitized local Decision Board journal state",
    )
    journal_status.add_argument("--journal-dir", required=True)
    journal_status.add_argument("--status", action="append", default=None)
    journal_status.add_argument("--limit", default="100")
    journal_status.add_argument("--scan-limit", default="1000")
    journal_status.add_argument("--max-record-bytes", default="65536")
    journal_status.add_argument("--max-output-bytes", default="262144")

    journal_reconcile = sub.add_parser(
        "decision-board-journal-reconcile",
        help="Persist missed/stale local Decision Board observations",
    )
    journal_reconcile.add_argument("--journal-dir", required=True)
    journal_reconcile.add_argument("--run-kind", required=True)
    journal_reconcile.add_argument("--expected-at", required=True)
    journal_reconcile.add_argument("--run-id", required=True)
    journal_reconcile.add_argument("--now", required=True)
    journal_reconcile.add_argument("--grace-seconds", required=True)
    journal_reconcile.add_argument("--stale-seconds", required=True)
    journal_reconcile.add_argument("--limit", default="100")

    journal_run = sub.add_parser(
        "decision-board-journal-run",
        help="Run one local Decision Board shadow process with durable journaling",
    )
    journal_run.add_argument("--journal-dir", required=True)
    journal_run.add_argument("--run-kind", required=True)
    journal_run.add_argument("--expected-at", required=True)
    journal_run.add_argument("--run-id", required=True)
    journal_run.add_argument("--grace-seconds", required=True)
    journal_run.add_argument("--stale-seconds", required=True)
    journal_run.add_argument("--gate-manifest", default=None)
    journal_run.add_argument("--gate-manifest-sha256", default=None)
    journal_run.add_argument("--input-ledger", default=None)
    journal_run.add_argument("--expected-action-ledger", default=None)
    journal_run.add_argument("--dry-run", action="store_true")
    journal_run.add_argument("runner_args", nargs=argparse.REMAINDER)

    backtest = sub.add_parser(
        "backtest",
        help="Replay historical OHLCV through buy/sell strategy rules",
    )
    backtest.add_argument(
        "--data-file",
        required=True,
        help="Local JSON OHLCV file: ticker mapping, symbols mapping, or row list",
    )
    backtest.add_argument(
        "--tickers",
        default=None,
        help="Comma-separated ticker filter; required when data file is a row list",
    )
    backtest.add_argument("--start-date", default=None, help="YYYY-MM-DD or YYYYMMDD")
    backtest.add_argument("--end-date", default=None, help="YYYY-MM-DD or YYYYMMDD")
    backtest.add_argument(
        "--strategy-mode",
        default=None,
        choices=["ema_cross", "sma_ema_hybrid"],
        help="Buy strategy mode override",
    )
    backtest.add_argument(
        "--sell-mode",
        default=None,
        choices=["generic", "sma_ema_hybrid"],
        help="Sell strategy mode override",
    )
    backtest.add_argument(
        "--report-dir",
        default=None,
        help="Output report directory override",
    )
    backtest.add_argument(
        "--transaction-cost-bps",
        type=float,
        default=0.0,
        help="Round-trip metrics subtract this bps per side",
    )
    backtest.add_argument(
        "--slippage-bps",
        type=float,
        default=0.0,
        help="Apply bps slippage to entry and exit prices",
    )
    backtest.add_argument(
        "--position-size-pct",
        type=float,
        default=1.0,
        help="Account equity fraction allocated to each entry (0..1)",
    )
    backtest.add_argument(
        "--partial-exit-fraction",
        type=float,
        default=0.5,
        help="Fraction of remaining position closed by SELL_PARTIAL (0..1)",
    )
    backtest.add_argument(
        "--intraday-exit-policy",
        default="conservative",
        choices=["none", "conservative", "stop_first", "target_first"],
        help="Daily OHLC stop/target path approximation policy",
    )
    backtest.add_argument(
        "--assumptions-file",
        default=None,
        help="Optional JSON object documenting data/universe/benchmark assumptions",
    )
    backtest.add_argument(
        "--no-close-open-at-end",
        action="store_true",
        help="Leave final open positions marked open instead of force-closing",
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

    sell_generate_scheduled = sub.add_parser(
        "sell-ai-brief-generate-scheduled",
        help="Generate and deliver a scheduled Sell AI Brief with freshness guards",
    )
    sell_generate_scheduled.add_argument("--scope", default="MIXED", choices=["MIXED"])
    sell_generate_scheduled.add_argument("--session-date", default="")
    sell_generate_scheduled.add_argument("--runner-role", default="local-primary")
    sell_generate_scheduled.add_argument("--scheduled-tick", default="manual")
    sell_generate_scheduled.add_argument("--attempt-id", default=None)
    sell_generate_scheduled.add_argument("--run-url", default="")
    sell_generate_scheduled.add_argument("--provider", default=None)
    sell_generate_scheduled.add_argument(
        "--model-provider", default="openai", choices=["fake", "openai"]
    )
    sell_generate_scheduled.add_argument("--model-name", default=None)
    sell_generate_scheduled.add_argument("--dry-run", action="store_true")

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


def _run_decision_board_command(ns: argparse.Namespace) -> int:
    result: DecisionRunResultV0
    try:
        config = DecisionBoardCliConfigV0.from_strings(
            run_kind=ns.run_kind,
            run_id=ns.run_id,
            idempotency_key=ns.idempotency_key,
            created_at=ns.created_at,
            sealed_input_hash=ns.sealed_input_hash,
            upload_mode=ns.upload_mode,
            report_dir=ns.report_dir,
            gate_manifest_sha256=getattr(ns, "gate_manifest_sha256", None),
            gate_manifest=getattr(ns, "gate_manifest", None),
            input_ledger=getattr(ns, "input_ledger", None),
            expected_action_ledger=getattr(ns, "expected_action_ledger", None),
        )
    except TypeError, ValueError:
        result = create_decision_run_failed_v0(
            issue_code=DecisionRunIssueCodeV0.PREPARATION_INVALID
        )
    else:
        try:
            execute = (
                execute_decision_board_shadow_live_cli_v0
                if ns.cmd == "decision-board-shadow-live"
                else execute_decision_board_cli_v0
            )
            result = execute(config)
        except Exception:
            result = create_decision_run_failed_v0(
                issue_code=DecisionRunIssueCodeV0.INTERNAL_ERROR
            )
    try:
        public = serialize_decision_run_result_v0(result)
        exit_code = decision_run_exit_code_v0(result)
    except TypeError, ValueError:
        result = create_decision_run_failed_v0(
            issue_code=DecisionRunIssueCodeV0.INTERNAL_ERROR
        )
        public = serialize_decision_run_result_v0(result)
        exit_code = decision_run_exit_code_v0(result)
    stream = sys.stderr if public["status"] == "FAILED" else sys.stdout
    print(json.dumps(public, ensure_ascii=False, sort_keys=True), file=stream)
    return exit_code


def _run_decision_board_shadow_gate_validate_command(ns: argparse.Namespace) -> int:
    try:
        manifest = load_shadow_gate_manifest_v0(
            ns.manifest,
            require_approved=ns.require_approved,
            input_ledger_path=ns.input_ledger,
            expected_action_ledger_path=ns.expected_action_ledger,
        )
    except ShadowGateManifestError as exc:
        print(
            json.dumps(
                {"status": "INVALID", "exit_code": 2, "issue_code": exc.code},
                sort_keys=True,
            ),
            file=sys.stderr,
        )
        return 2
    print(json.dumps(manifest.to_public_dict(), sort_keys=True))
    return 0


def _run_decision_board_shadow_ledger_prepare_command(ns: argparse.Namespace) -> int:
    try:
        manifest = load_shadow_gate_manifest_v0(ns.manifest)
        case_plan = load_shadow_evaluation_case_plan_v0(ns.case_plan)
        result = prepare_shadow_evaluation_ledgers_v0(
            manifest=manifest,
            case_plan=case_plan,
            output_dir=ns.output_dir,
        )
    except ShadowGateManifestError, ShadowLedgerPreparationError, TypeError:
        print(
            json.dumps(
                {
                    "status": "FAILED",
                    "exit_code": 2,
                    "issue_code": "LEDGER_PREPARATION_INVALID",
                },
                sort_keys=True,
            ),
            file=sys.stderr,
        )
        return 2
    print(json.dumps(result.to_public_dict(), sort_keys=True))
    return 0


def _journal_cli_failure() -> int:
    print(
        json.dumps(
            {"status": "FAILED", "exit_code": 2, "issue_code": "JOURNAL_INVALID"},
            sort_keys=True,
        ),
        file=sys.stderr,
    )
    return 2


def _run_decision_board_journal_status_command(ns: argparse.Namespace) -> int:
    try:
        limit = parse_bounded_int_v0(ns.limit, field="limit", minimum=1, maximum=1000)
        scan_limit = parse_bounded_int_v0(
            ns.scan_limit, field="scan_limit", minimum=1, maximum=1000
        )
        max_record_bytes = parse_bounded_int_v0(
            ns.max_record_bytes,
            field="max_record_bytes",
            minimum=1,
            maximum=1024 * 1024,
        )
        max_output_bytes = parse_bounded_int_v0(
            ns.max_output_bytes,
            field="max_output_bytes",
            minimum=1,
            maximum=1024 * 1024,
        )
        statuses = (
            tuple(status.value for status in RunJournalStatusV0)
            if ns.status is None
            else tuple(RunJournalStatusV0(value).value for value in ns.status)
        )
        public = read_public_journal_status_v0(
            ns.journal_dir,
            limit=limit,
            statuses=statuses,
            scan_limit=scan_limit,
            max_record_bytes=max_record_bytes,
            max_output_bytes=max_output_bytes,
        )
        print(json.dumps(public, sort_keys=True))
        return 0
    except OSError, RunJournalError, TypeError, ValueError:
        return _journal_cli_failure()


def _run_decision_board_journal_reconcile_command(ns: argparse.Namespace) -> int:
    try:
        kind = RunKindV0(ns.run_kind.upper())
        expected = ExpectedRunV0.create(
            run_kind=kind,
            expected_at=parse_utc_rfc3339_v0(ns.expected_at, field="expected_at"),
            run_id=ns.run_id,
        )
        records = RunJournalStoreV0(ns.journal_dir).reconcile(
            expected=(expected,),
            now=parse_utc_rfc3339_v0(ns.now, field="now"),
            grace_seconds=parse_bounded_int_v0(
                ns.grace_seconds,
                field="grace_seconds",
                minimum=0,
                maximum=604800,
            ),
            stale_seconds=parse_bounded_int_v0(
                ns.stale_seconds,
                field="stale_seconds",
                minimum=1,
                maximum=604800,
            ),
            limit=parse_bounded_int_v0(
                ns.limit, field="limit", minimum=1, maximum=1000
            ),
        )
        print(json.dumps(public_records_v0(records), sort_keys=True))
        return 0
    except OSError, RunJournalError, TypeError, ValueError:
        return _journal_cli_failure()


def _run_decision_board_journal_run_command(ns: argparse.Namespace) -> int:
    try:
        config = JournalShadowProcessConfigV0.from_strings(
            run_kind=ns.run_kind,
            expected_at=ns.expected_at,
            run_id=ns.run_id,
            journal_dir=ns.journal_dir,
            grace_seconds=ns.grace_seconds,
            stale_seconds=ns.stale_seconds,
            runner_args=ns.runner_args,
            dry_run=ns.dry_run,
            gate_manifest=ns.gate_manifest,
            gate_manifest_sha256=ns.gate_manifest_sha256,
            input_ledger=ns.input_ledger,
            expected_action_ledger=ns.expected_action_ledger,
        )
        return execute_journal_shadow_process_v0(config)
    except OSError, RunJournalError, TypeError, ValueError:
        return _journal_cli_failure()


def _run_backtest_command(ns: argparse.Namespace) -> int:
    try:
        return run_backtest(
            data_file_path=ns.data_file,
            tickers=ns.tickers,
            start_date=ns.start_date,
            end_date=ns.end_date,
            strategy_mode=ns.strategy_mode,
            sell_mode=ns.sell_mode,
            report_dir=ns.report_dir,
            transaction_cost_bps=ns.transaction_cost_bps,
            slippage_bps=ns.slippage_bps,
            position_size_pct=ns.position_size_pct,
            partial_exit_fraction=ns.partial_exit_fraction,
            intraday_exit_policy=ns.intraday_exit_policy,
            assumptions_file_path=ns.assumptions_file,
            close_open_at_end=not ns.no_close_open_at_end,
        )
    except (OSError, json.JSONDecodeError, ValueError) as exc:
        print(f"backtest error: {sanitize_log_text(str(exc))}", file=sys.stderr)
        return 2


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


def _scheduled_sell_ai_brief_generation_request_from_args(
    ns: argparse.Namespace,
) -> ScheduledSellAiBriefGenerationRequest:
    return ScheduledSellAiBriefGenerationRequest(
        scope=ns.scope,
        session_date=ns.session_date,
        runner_role=ns.runner_role,
        scheduled_tick=ns.scheduled_tick,
        attempt_id=ns.attempt_id,
        run_url=ns.run_url,
        provider=ns.provider,
        model_provider=ns.model_provider,
        model_name=ns.model_name,
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


def _write_scheduled_sell_ai_brief_generation_status_file(
    *,
    status: str,
    session_date: str,
    sell_storage_key: str | None,
    sell_ai_brief_storage_key: str | None,
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
                "sell_storage_key": sell_storage_key,
                "sell_ai_brief_storage_key": sell_ai_brief_storage_key,
            },
        )
    except Exception as exc:
        logging.getLogger(__name__).warning(
            "failed to write scheduled sell AI brief generation status file: %s",
            exc,
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


def _scheduled_sell_holdings_snapshot_path(
    *, request: ScheduledSellAiBriefGenerationRequest
) -> Path:
    scope = str(request.scope or "MIXED").strip().upper() or "MIXED"
    safe_scope = "".join(
        char if char.isalnum() or char in {"-", "_"} else "_" for char in scope
    )
    session_date = str(request.session_date or "").strip()
    if not session_date:
        raise SupabaseHoldingsExportError(
            "scheduled sell holdings export requires session_date"
        )
    return Path("data") / "scheduler" / f"holdings.{safe_scope}.{session_date}.yaml"


def _run_scheduled_sell_with_supabase_holdings(
    generation_request: ScheduledSellAiBriefGenerationRequest,
) -> SellRunResult:
    try:
        holdings_path = _scheduled_sell_holdings_snapshot_path(
            request=generation_request
        )
        holding_count = export_active_holdings_snapshot(
            output_path=holdings_path,
            config=SupabaseHoldingsExportConfig.from_env(),
        )
    except SupabaseHoldingsExportError as exc:
        logging.getLogger(__name__).error(
            "Scheduled sell holdings export failed",
            extra={
                "event": "scheduled_sell_holdings_export_failed",
                "operation": "scheduled_sell_ai_brief_generation",
                "scope": generation_request.scope,
                "session_date": generation_request.session_date,
                "error": str(exc),
            },
        )
        return SellRunResult(exit_code=1, report_path=None)

    logging.getLogger(__name__).info(
        "Scheduled sell holdings snapshot exported",
        extra={
            "event": "scheduled_sell_holdings_exported",
            "operation": "scheduled_sell_ai_brief_generation",
            "scope": generation_request.scope,
            "session_date": generation_request.session_date,
            "holdings_path": holdings_path.as_posix(),
            "holding_count": holding_count,
        },
    )
    return run_sell_with_result(
        provider=generation_request.provider,
        holdings_path=holdings_path.as_posix(),
        suppress_upload=True,
        report_date=generation_request.session_date or None,
    )


def run_scheduled_sell_ai_brief_generation(
    *,
    request: ScheduledSellAiBriefGenerationRequest,
) -> int:
    runner = ScheduledSellAiBriefGenerationRunner(
        state_store=SupabaseRuntimeStateClient.from_env(),
        storage=DefaultScheduledStorage.from_env(),
        notifier=_SellAiBriefGenerationNotifier(),
        sell_runner=_run_scheduled_sell_with_supabase_holdings,
        sell_ai_brief_runner=lambda generation_request, sell_report_path: (
            run_sell_ai_brief_with_result(
                sell_report_path=sell_report_path,
                model_provider=generation_request.model_provider,
                model_name=generation_request.model_name,
                report_date=generation_request.session_date or None,
                upload=False,
            )
        ),
        evaluator=lambda sell_report_path, sell_ai_brief_report_path: (
            evaluate_sell_ai_brief_report(
                sell_report_path=sell_report_path,
                sell_ai_brief_report_path=sell_ai_brief_report_path,
            )
        ),
        delivery_runner=lambda delivery_request: ScheduledSellAiBriefDeliveryRunner(
            state_store=SupabaseRuntimeStateClient.from_env(),
            storage=DefaultScheduledStorage.from_env(),
            notifier=_SellAiBriefScheduledNotifier(),
        ).run(delivery_request),
    )
    result = runner.run(request)
    _write_scheduled_sell_ai_brief_generation_status_file(
        status=result.status,
        session_date=result.session_date,
        sell_storage_key=result.sell_storage_key,
        sell_ai_brief_storage_key=result.sell_ai_brief_storage_key,
    )
    print(
        json.dumps(
            {
                "status": result.status,
                "sell_storage_key": result.sell_storage_key,
                "sell_ai_brief_storage_key": result.sell_ai_brief_storage_key,
            }
        )
    )
    return (
        0
        if result.status not in FAILED_SCHEDULED_SELL_AI_BRIEF_GENERATION_STATUSES
        else 1
    )


def _run_scheduled_sell_ai_brief_generation_command(ns: argparse.Namespace) -> int:
    return run_scheduled_sell_ai_brief_generation(
        request=_scheduled_sell_ai_brief_generation_request_from_args(ns)
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
        "decision-board": _run_decision_board_command,
        "decision-board-shadow-live": _run_decision_board_command,
        "decision-board-shadow-gate-validate": (
            _run_decision_board_shadow_gate_validate_command
        ),
        "decision-board-shadow-ledger-prepare": (
            _run_decision_board_shadow_ledger_prepare_command
        ),
        "decision-board-journal-status": (_run_decision_board_journal_status_command),
        "decision-board-journal-reconcile": (
            _run_decision_board_journal_reconcile_command
        ),
        "decision-board-journal-run": _run_decision_board_journal_run_command,
        "backtest": _run_backtest_command,
        "ai-brief": _run_ai_brief_command,
        "sell-ai-brief": _run_sell_ai_brief_command,
        "ai-brief-scheduled": _run_scheduled_ai_brief_command,
        "sell-ai-brief-scheduled": _run_scheduled_sell_ai_brief_command,
        "sell-ai-brief-generate-scheduled": (
            _run_scheduled_sell_ai_brief_generation_command
        ),
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
