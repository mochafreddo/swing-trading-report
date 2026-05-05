from __future__ import annotations

import argparse
import datetime as dt
import logging
import os
import sys

from .ai_brief import run_ai_brief
from .entry import run_entry
from .env_loader import load_dotenv_if_available
from .scan import run_scan
from .sell import run_sell


def _configure_logging() -> None:
    level_name = os.getenv("LOG_LEVEL", "INFO").upper()
    level = getattr(logging, level_name, logging.INFO)

    log_format = os.getenv(
        "LOG_FORMAT",
        "%(asctime)s %(levelname)s %(name)s - %(message)s",
    )
    log_datefmt = os.getenv("LOG_DATEFMT") or None
    log_tz = (os.getenv("LOG_TZ") or "local").strip().lower()
    if log_tz not in {"local", "utc"}:
        log_tz = "local"

    class _TZFormatter(logging.Formatter):
        def __init__(self, fmt: str, *, datefmt: str | None, tz: str) -> None:
            super().__init__(fmt=fmt, datefmt=datefmt)
            self._tz = tz

        def formatTime(
            self, record: logging.LogRecord, datefmt: str | None = None
        ) -> str:
            if self._tz == "utc":
                ts = dt.datetime.fromtimestamp(record.created, tz=dt.UTC)
            else:
                ts = dt.datetime.fromtimestamp(record.created).astimezone()

            datefmt = datefmt or self.datefmt
            if datefmt:
                return ts.strftime(datefmt)
            return ts.isoformat(timespec="milliseconds")

    handler = logging.StreamHandler()
    handler.setFormatter(_TZFormatter(log_format, datefmt=log_datefmt, tz=log_tz))
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
        choices=["fake"],
        help="AI model provider for the brief",
    )
    ai_brief.add_argument(
        "--model-name",
        type=str,
        default="fake-ai-brief-v1",
        help="AI model name for the brief",
    )
    return p


def main(argv: list[str] | None = None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    load_dotenv_if_available(override=False)
    _configure_logging()
    parser = _build_parser()
    ns = parser.parse_args(argv)

    if ns.cmd == "scan":
        return run_scan(
            limit=ns.limit,
            watchlist_path=ns.watchlist,
            provider=ns.provider,
            screener_limit=ns.screener_limit,
            universe=ns.universe,
            markets=ns.markets,
        )

    if ns.cmd == "sell":
        return run_sell(provider=ns.provider, holdings_path=ns.holdings)

    if ns.cmd == "entry":
        return run_entry(
            buy_report_path=ns.buy_report,
            provider=ns.provider,
            mode=ns.mode,
            market=ns.market,
            upload=ns.upload,
        )

    if ns.cmd == "ai-brief":
        return run_ai_brief(
            entry_report_path=ns.entry_report,
            buy_report_path=ns.buy_report,
            market=ns.market,
            model_provider=ns.model_provider,
            model_name=ns.model_name,
        )

    parser.print_help()
    return 2


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
