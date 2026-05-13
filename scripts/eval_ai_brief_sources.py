from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

_COMPARE_LABEL_RE = re.compile(r"^[A-Za-z0-9_.-]+$")


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
        default=None,
        help="Captured source report JSON compatible with sab.ai_brief_sources.v1",
    )
    parser.add_argument(
        "--compare-source-report",
        action="append",
        default=[],
        metavar="LABEL=PATH",
        help=(
            "Captured source report to compare; repeat at least twice for "
            "comparison mode"
        ),
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


def _parse_compare_source_reports(
    values: list[str],
    parser: argparse.ArgumentParser,
) -> dict[str, str]:
    if len(values) < 2:
        parser.error("--compare-source-report requires at least two LABEL=PATH values")
    reports: dict[str, str] = {}
    for raw_value in values:
        label, separator, path = raw_value.partition("=")
        if not separator:
            parser.error("--compare-source-report must use LABEL=PATH")
        label = label.strip()
        path = path.strip()
        if not label or not _COMPARE_LABEL_RE.fullmatch(label):
            parser.error("--compare-source-report label must match [A-Za-z0-9_.-]+")
        if label in reports:
            parser.error(f"duplicate --compare-source-report label {label!r}")
        if not path:
            parser.error("--compare-source-report path must not be empty")
        reports[label] = path
    return reports


def main(argv: list[str] | None = None) -> int:
    from sab.ai_brief_source_eval import (
        compare_ai_brief_source_reports,
        evaluate_ai_brief_source_report,
        parse_eval_now,
    )

    parser = _build_parser()
    ns = parser.parse_args(argv)
    compare_values = ns.compare_source_report
    if ns.source_report and compare_values:
        parser.error("--source-report cannot be used with --compare-source-report")
    if not ns.source_report and not compare_values:
        parser.error("--source-report or --compare-source-report is required")
    try:
        now = parse_eval_now(ns.now) if ns.now else None
        if compare_values:
            compare_result = compare_ai_brief_source_reports(
                entry_report_path=ns.entry_report,
                source_reports=_parse_compare_source_reports(compare_values, parser),
                market=ns.market,
                minimum_coverage_ratio=ns.minimum_coverage_ratio,
                now=now,
            )
            result_payload = compare_result.to_dict()
        else:
            eval_result = evaluate_ai_brief_source_report(
                entry_report_path=ns.entry_report,
                source_report_path=ns.source_report,
                market=ns.market,
                minimum_coverage_ratio=ns.minimum_coverage_ratio,
                now=now,
            )
            result_payload = eval_result.to_dict()
    except ValueError as exc:
        parser.error(str(exc))

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
