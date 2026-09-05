#!/usr/bin/env python3
"""Replay all frozen T19 cadences without network or production advice."""

from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from datetime import datetime
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from sab.portfolio_mandate.historical_replay import (  # noqa: E402
    replay_historical_cadence_t19,
    validate_historical_replay_candidate_t19,
)


def _load(path: Path) -> dict[str, Any]:
    def reject_duplicates(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for key, value in pairs:
            if key in result:
                raise ValueError(f"duplicate key: {key}")
            result[key] = value
        return result

    value = json.loads(
        path.read_text(encoding="utf-8"), object_pairs_hook=reject_duplicates
    )
    if not isinstance(value, dict):
        raise ValueError("manifest must be an object")
    return value


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--manifest",
        type=Path,
        default=Path(
            "tests/fixtures/portfolio_mandate/portfolio-long-term-replay-t19.candidate.json"
        ),
    )
    args = parser.parse_args()
    candidate = validate_historical_replay_candidate_t19(_load(args.manifest))
    actions: Counter[str] = Counter()
    for cadence in candidate["cadences"]:
        now = datetime.fromisoformat(cadence["scheduled_for"].replace("Z", "+00:00"))
        replay = replay_historical_cadence_t19(candidate, clock=lambda now=now: now)
        for decision in replay["decisions"]:
            actions.update(decision["expected_action_set"])
    print(
        json.dumps(
            {
                "gate_state": candidate["gate_state"],
                "case_count": len(candidate["cases"]),
                "cadence_count": len(candidate["cadences"]),
                "action_counts": dict(sorted(actions.items())),
                "approval_signature_present": candidate["approval_signature"]
                is not None,
                "network_requests": 0,
                "provider_calls": 0,
                "order_operations": 0,
            },
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
