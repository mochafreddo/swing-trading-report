#!/usr/bin/env python3
"""Run every recorded T21 capability branch without a provider transport."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from sab.portfolio_mandate.capability_probe import (  # noqa: E402
    run_recorded_capability_probe_t21,
    validate_capability_probe_package_t21,
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
        raise ValueError("recorded package must be an object")
    return value


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--fixture",
        type=Path,
        default=Path(
            "tests/fixtures/portfolio_mandate/portfolio-outcome-capability-t21.recorded.json"
        ),
    )
    parser.add_argument(
        "--artifact",
        type=Path,
        default=Path("tmp/portfolio-outcome-capability-t21.local.json"),
    )
    args = parser.parse_args()
    package = validate_capability_probe_package_t21(_load(args.fixture))
    artifacts = [
        run_recorded_capability_probe_t21(package, scenario["scenario_id"])
        for scenario in package["scenarios"]
    ]
    expected = {
        scenario["scenario_id"]: scenario["expected_result_code"]
        for scenario in package["scenarios"]
    }
    actual = {
        artifact["scenario_id"]: artifact["result_code"] for artifact in artifacts
    }
    if actual != expected:
        raise RuntimeError("recorded result codes do not match the frozen fixture")
    args.artifact.parent.mkdir(parents=True, exist_ok=True)
    temporary = args.artifact.with_suffix(args.artifact.suffix + ".tmp")
    temporary.write_text(
        json.dumps(
            {
                "schema_version": "portfolio-outcome-capability-artifact-set.t21",
                "provider_history_state": "NOT_EVALUATED",
                "artifacts": artifacts,
            },
            indent=2,
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )
    temporary.replace(args.artifact)
    print(
        json.dumps(
            {
                "provider_history_state": "NOT_EVALUATED",
                "scenario_count": len(artifacts),
                "recorded_pass_count": sum(
                    artifact["state"] == "RECORDED_FIXTURE_PASS"
                    for artifact in artifacts
                ),
                "recorded_failure_branch_count": sum(
                    artifact["state"] == "RECORDED_FIXTURE_FAIL"
                    for artifact in artifacts
                ),
                "provider_calls": 0,
                "order_operations": 0,
                "artifact_path": str(args.artifact),
            },
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
