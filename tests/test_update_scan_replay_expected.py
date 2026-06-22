from __future__ import annotations

import json
import shutil
from pathlib import Path

from scripts import update_scan_replay_expected

_SCAN_REPLAY_ROOT = Path(__file__).parent / "fixtures" / "replay_eod" / "scan"


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
