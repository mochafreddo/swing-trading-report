# ruff: noqa: E402

from __future__ import annotations

import argparse
import json
import sys
import tempfile
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from tests.helpers.replay_eod import (
    ReplayScanCaseError,
    iter_scan_replay_case_dirs,
    run_scan_replay_case,
)

_DEFAULT_REPLAY_ROOT = Path("tests/fixtures/replay_eod/scan")


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Refresh scan replay expected.buy.json artifacts.",
    )
    parser.add_argument(
        "paths",
        nargs="*",
        type=Path,
        help="Replay case directory paths. Defaults to every scan replay case.",
    )
    return parser.parse_args()


def _resolve_case_dirs(paths: list[Path]) -> list[Path]:
    if paths:
        return [path for path in paths if path.is_dir()]
    return iter_scan_replay_case_dirs(_DEFAULT_REPLAY_ROOT)


def _ensure_expected_placeholder(case_dir: Path) -> None:
    expected_path = case_dir / "expected.buy.json"
    if not expected_path.exists():
        expected_path.write_text("{}\n", encoding="utf-8")


def _refresh_case(case_dir: Path) -> None:
    _ensure_expected_placeholder(case_dir)
    monkeypatch = pytest.MonkeyPatch()
    try:
        with tempfile.TemporaryDirectory(prefix=f"{case_dir.name}-replay-") as tmp_dir:
            result = run_scan_replay_case(
                case_dir,
                tmp_path=Path(tmp_dir),
                monkeypatch=monkeypatch,
            )
    finally:
        monkeypatch.undo()

    expected_path = case_dir / "expected.buy.json"
    expected_path.write_text(
        json.dumps(result.normalized_actual, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(f"updated {expected_path}")


def main() -> int:
    case_dirs = _resolve_case_dirs(_parse_args().paths)
    if not case_dirs:
        raise ReplayScanCaseError("no replay case directories found")
    for case_dir in case_dirs:
        _refresh_case(case_dir)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
