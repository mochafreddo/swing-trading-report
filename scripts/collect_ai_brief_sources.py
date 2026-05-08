from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def _build_parser() -> argparse.ArgumentParser:
    from sab.ai_brief_source_collectors import DEFAULT_FEED_TIMEOUT_SECONDS
    from sab.ai_brief_sources import MAX_SOURCES_PER_TICKER, SOURCE_FRESHNESS_HOURS

    parser = argparse.ArgumentParser(
        description=("Convert RSS/Atom/RDF feeds into an AI Brief source payload.")
    )
    parser.add_argument(
        "--feed-catalog",
        required=True,
        help="JSON feed catalog with ticker/path or ticker/url rows",
    )
    parser.add_argument(
        "--ticker",
        action="append",
        default=[],
        help="Ticker to include; repeat to filter the feed catalog",
    )
    parser.add_argument(
        "--output",
        default=None,
        help="Optional output JSON path; stdout is used when omitted",
    )
    parser.add_argument(
        "--freshness-hours",
        type=float,
        default=SOURCE_FRESHNESS_HOURS,
        help="Maximum source age in hours",
    )
    parser.add_argument(
        "--max-sources-per-ticker",
        type=int,
        default=MAX_SOURCES_PER_TICKER,
        help="Maximum emitted source rows per ticker",
    )
    parser.add_argument(
        "--feed-timeout-seconds",
        type=float,
        default=DEFAULT_FEED_TIMEOUT_SECONDS,
        help="Timeout for each live feed URL request",
    )
    parser.add_argument(
        "--now",
        type=str,
        default=None,
        help="Optional ISO 8601 timestamp for deterministic freshness checks",
    )
    parser.add_argument(
        "--pretty",
        action="store_true",
        help="Pretty-print JSON output",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    from sab.ai_brief_source_collectors import (
        AiBriefSourceCollectorError,
        collect_ai_brief_sources,
        parse_collect_now,
    )

    parser = _build_parser()
    ns = parser.parse_args(argv)
    try:
        now = parse_collect_now(ns.now) if ns.now else None
        result = collect_ai_brief_sources(
            feed_catalog_path=ns.feed_catalog,
            tickers=set(ns.ticker) if ns.ticker else None,
            now=now,
            freshness_hours=ns.freshness_hours,
            max_sources_per_ticker=ns.max_sources_per_ticker,
            feed_timeout_seconds=ns.feed_timeout_seconds,
        )
    except (AiBriefSourceCollectorError, ValueError) as exc:
        parser.error(str(exc))

    output = json.dumps(
        result.to_dict(),
        ensure_ascii=False,
        indent=2 if ns.pretty else None,
        sort_keys=True,
    )
    if ns.output:
        try:
            output_path = Path(ns.output)
            if output_path.parent != Path("."):
                output_path.parent.mkdir(parents=True, exist_ok=True)
            output_path.write_text(f"{output}\n", encoding="utf-8")
        except OSError as exc:
            parser.error(f"failed to write output: {exc}")
    else:
        print(output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
