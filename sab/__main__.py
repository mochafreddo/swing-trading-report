from __future__ import annotations

import argparse
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
    logging.basicConfig(level=level, format="%(levelname)s - %(message)s")


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
