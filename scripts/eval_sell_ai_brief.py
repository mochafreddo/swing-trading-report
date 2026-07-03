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
        description="Evaluate captured Sell AI Brief quality offline."
    )
    parser.add_argument(
        "--sell-report",
        required=True,
        help="Sell report JSON used to derive expected sell candidates",
    )
    parser.add_argument(
        "--sell-ai-brief-report",
        required=True,
        help="Sell AI Brief report JSON compatible with sab.sell_ai_brief.v1",
    )
    parser.add_argument(
        "--minimum-source-backed-ratio",
        type=float,
        default=1.0,
        help="Minimum judgment source-backed ratio required to pass",
    )
    parser.add_argument(
        "--now",
        type=str,
        default=None,
        help="Optional ISO 8601 timestamp for deterministic validation checks",
    )
    parser.add_argument(
        "--pretty",
        action="store_true",
        help="Pretty-print JSON output",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    from sab.sell_ai_brief_eval import (
        evaluate_sell_ai_brief_report,
        parse_eval_now,
    )

    parser = _build_parser()
    ns = parser.parse_args(argv)
    try:
        result = evaluate_sell_ai_brief_report(
            sell_report_path=ns.sell_report,
            sell_ai_brief_report_path=ns.sell_ai_brief_report,
            minimum_source_backed_ratio=ns.minimum_source_backed_ratio,
            now=parse_eval_now(ns.now) if ns.now else None,
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
