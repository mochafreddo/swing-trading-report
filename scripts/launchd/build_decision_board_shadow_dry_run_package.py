"""Build two disabled, unscheduled Decision Board wrapper dry-run plists."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from sab.decision_board.launchd_package import (  # noqa: E402
    ShadowLaunchdPackageError,
    build_decision_board_launchd_dry_run_package_v0,
)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Build disabled, schedule-free wrapper dry-run plists."
    )
    parser.add_argument(
        "--manifest",
        default=str(ROOT / "config" / "decision-board-shadow-gate.proposed.json"),
    )
    parser.add_argument("--session", required=True)
    parser.add_argument("--journal-dir", required=True)
    parser.add_argument("--output-dir", required=True)
    parser.add_argument("--report-dir", default=str(ROOT / "reports"))
    parser.add_argument("--require-approved", action="store_true")
    parser.add_argument("--input-ledger", default=None)
    parser.add_argument("--expected-action-ledger", default=None)
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = _parser()
    args = parser.parse_args(argv)
    try:
        result = build_decision_board_launchd_dry_run_package_v0(
            manifest_path=args.manifest,
            session=args.session,
            repo_root=ROOT,
            journal_dir=args.journal_dir,
            output_dir=args.output_dir,
            report_dir=args.report_dir,
            require_approved=args.require_approved,
            input_ledger_path=args.input_ledger,
            expected_action_ledger_path=args.expected_action_ledger,
        )
    except ShadowLaunchdPackageError:
        print(
            json.dumps(
                {
                    "status": "FAILED",
                    "exit_code": 2,
                    "issue_code": "PACKAGE_INVALID",
                },
                sort_keys=True,
            ),
            file=sys.stderr,
        )
        return 2
    print(json.dumps(result.to_public_dict(), sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
