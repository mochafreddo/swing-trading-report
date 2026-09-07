"""Print a synthetic A1 review projection without credentials, network or DB writes."""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from sab.portfolio_mandate.review_policy import (  # noqa: E402
    compile_portfolio_review_r1,
)
from sab.portfolio_mandate.review_projection import (  # noqa: E402
    project_mandate_review_a1,
)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--as-of", default="2026-08-28T00:25:00Z")
    parser.add_argument(
        "--review-r1",
        action="store_true",
        help="replay the frozen synthetic composite RPC snapshot",
    )
    args = parser.parse_args()
    if args.review_r1:
        envelope = json.loads(
            (
                ROOT
                / "tests/fixtures/portfolio_mandate/portfolio-review-r1.rpc.synthetic.json"
            ).read_text()
        )
        result = compile_portfolio_review_r1(
            envelope,
            review_period="2026Q2",
            broker_max_age_seconds=600,
            evidence_max_age_seconds=180 * 86400,
        )
        print(json.dumps(result, indent=2, sort_keys=True))
        return
    fixture = json.loads(
        (
            ROOT
            / "tests/fixtures/portfolio_mandate/portfolio-mandate-a1.synthetic.json"
        ).read_text()
    )
    result = project_mandate_review_a1(
        fixture, as_of=datetime.fromisoformat(args.as_of)
    )
    print(json.dumps(result, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
