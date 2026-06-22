from __future__ import annotations

import json
import shutil
import subprocess
import sys
from pathlib import Path

from scripts import update_scan_replay_expected

_SCAN_REPLAY_ROOT = Path(__file__).parent / "fixtures" / "replay_eod" / "scan"
_ROOT = Path(__file__).parents[1]


def test_refresh_case_replaces_corrupt_expected_artifact(tmp_path: Path) -> None:
    source_case_dir = _SCAN_REPLAY_ROOT / "kr_hybrid_gap_rejected"
    case_dir = tmp_path / source_case_dir.name
    shutil.copytree(source_case_dir, case_dir)
    expected_path = case_dir / "expected.buy.json"
    expected_path.write_text("{bad json\n", encoding="utf-8")

    update_scan_replay_expected._refresh_case(case_dir)

    refreshed = json.loads(expected_path.read_text(encoding="utf-8"))
    assert refreshed["summary"]["candidate_count"] == 0
    assert any("Gap " in message for message in refreshed["screen_outs"])


def test_cli_reports_invalid_case_path_without_traceback(tmp_path: Path) -> None:
    result = subprocess.run(
        [
            sys.executable,
            "scripts/update_scan_replay_expected.py",
            str(tmp_path),
        ],
        cwd=_ROOT,
        check=False,
        capture_output=True,
        text=True,
    )

    combined_output = result.stdout + result.stderr
    assert result.returncode == 1
    assert "replay case path must be under" in combined_output
    assert "Traceback" not in combined_output
