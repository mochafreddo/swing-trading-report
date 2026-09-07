"""Print a synthetic A1 review projection without credentials, network or DB writes."""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from sab.portfolio_mandate.review_projection import (  # noqa: E402
    project_mandate_review_a1,
)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--as-of", default="2026-08-28T00:25:00Z")
    args = parser.parse_args()
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
