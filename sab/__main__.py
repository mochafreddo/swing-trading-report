from __future__ import annotations

import argparse
import datetime as dt
import logging
import os
import sys

from .scan import run_scan
from .sell import run_sell


def _load_dotenv_if_available() -> None:
    try:
        from dotenv import load_dotenv  # type: ignore

        load_dotenv(override=False)
    except Exception:
        pass


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

        def formatTime(self, record: logging.LogRecord, datefmt: str | None = None) -> str:
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
    p = argparse.ArgumentParser(prog="sab", description="Swing Alert Bot — on-demand report")
    sub = p.add_subparsers(dest="cmd")

    s = sub.add_parser("scan", help="Collect -> evaluate -> write markdown report")
    s.add_argument("--limit", type=int, default=None, help="Max tickers to evaluate")
    s.add_argument("--watchlist", type=str, default=None, help="Path to watchlist file")
    s.add_argument(
        "--provider",
        type=str,
        default=None,
        choices=["kis", "pykrx"],
        help="Data provider override",
    )
    s.add_argument("--screener-limit", type=int, default=None, help="Override screener top-N size")
    s.add_argument(
        "--universe",
        type=str,
        default=None,
        choices=["watchlist", "screener", "both"],
        help="Universe selection: watchlist only, screener only, or both",
    )

    sell = sub.add_parser("sell", help="Evaluate holdings against sell/review rules")
    sell.add_argument(
        "--provider",
        type=str,
        default=None,
        choices=["kis", "pykrx"],
        help="Data provider override",
    )
    return p


def main(argv: list[str] | None = None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    _load_dotenv_if_available()
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
        )

    if ns.cmd == "sell":
        return run_sell(provider=ns.provider)

    parser.print_help()
    return 2


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
