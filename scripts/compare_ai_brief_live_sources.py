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
        description=(
            "Capture multiple live AI Brief source providers and compare their "
            "payload quality."
        )
    )
    parser.add_argument(
        "--entry-report",
        required=True,
        help="Entry report JSON used to derive eligible ENTER tickers",
    )
    parser.add_argument(
        "--provider",
        action="append",
        default=[],
        metavar="LABEL=PROVIDER",
        help=(
            "Live source provider to capture; repeat at least twice. PROVIDER is "
            "http-json, finnhub, polygon-news, alpha-vantage-news, or naver-news."
        ),
    )
    parser.add_argument(
        "--source-api-url",
        action="append",
        default=[],
        metavar="LABEL=URL",
        help=(
            "External source API URL for a LABEL whose provider is http-json. "
            "Repeat when comparing multiple http-json endpoints."
        ),
    )
    parser.add_argument(
        "--buy-report",
        default=None,
        help="Optional buy report path for ticker name enrichment",
    )
    parser.add_argument(
        "--market",
        choices=["KR", "US"],
        default=None,
        help="Single market to evaluate; required for MIXED entry reports",
    )
    parser.add_argument(
        "--source-timeout-seconds",
        type=float,
        default=None,
        help="External source provider timeout in seconds",
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
        "--output-dir",
        default=None,
        help=(
            "Directory for captured source reports; defaults to a directory next "
            "to the entry report"
        ),
    )
    parser.add_argument(
        "--pretty",
        action="store_true",
        help="Pretty-print JSON output",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    from sab.ai_brief_source_eval import parse_eval_now
    from sab.ai_brief_source_live_compare import (
        compare_ai_brief_live_sources,
        parse_live_source_provider_specs,
    )

    parser = _build_parser()
    ns = parser.parse_args(argv)
    try:
        provider_specs = parse_live_source_provider_specs(
            provider_values=ns.provider,
            source_api_url_values=ns.source_api_url,
        )
        now = parse_eval_now(ns.now) if ns.now else None
        result = compare_ai_brief_live_sources(
            entry_report_path=ns.entry_report,
            provider_specs=provider_specs,
            buy_report_path=ns.buy_report,
            market=ns.market,
            source_timeout_seconds=ns.source_timeout_seconds,
            minimum_coverage_ratio=ns.minimum_coverage_ratio,
            now=now,
            output_dir=ns.output_dir,
        )
    except (OSError, ValueError) as exc:
        parser.error(str(exc))

    result_payload = result.to_dict()
    print(
        json.dumps(
            result_payload,
            ensure_ascii=False,
            indent=2 if ns.pretty else None,
            sort_keys=True,
        )
    )
    return 1 if result_payload["status"] == "FAIL" else 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
