from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Evaluate captured AI Brief source payload quality offline."
    )
    parser.add_argument(
        "--entry-report",
        required=True,
        help="Entry report JSON used to derive eligible ENTER tickers",
    )
    parser.add_argument(
        "--source-report",
        required=True,
        help="Captured source report JSON compatible with sab.ai_brief_sources.v1",
    )
    parser.add_argument(
        "--market",
        choices=["KR", "US"],
        default=None,
        help="Single market to evaluate; required for MIXED entry reports",
    )
    parser.add_argument(
        "--minimum-coverage-ratio",
        type=float,
        default=1.0,
        help="Minimum eligible ticker source coverage ratio required to pass",
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
    from sab.ai_brief_source_eval import (
        evaluate_ai_brief_source_report,
        parse_eval_now,
    )

    parser = _build_parser()
    ns = parser.parse_args(argv)
    try:
        now = parse_eval_now(ns.now) if ns.now else None
        result = evaluate_ai_brief_source_report(
            entry_report_path=ns.entry_report,
            source_report_path=ns.source_report,
            market=ns.market,
            minimum_coverage_ratio=ns.minimum_coverage_ratio,
            now=now,
        )
    except ValueError as exc:
        parser.error(str(exc))

    print(
        json.dumps(
            result.to_dict(),
            ensure_ascii=False,
            indent=2 if ns.pretty else None,
            sort_keys=True,
        )
    )
    return 1 if result.status == "FAIL" else 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
