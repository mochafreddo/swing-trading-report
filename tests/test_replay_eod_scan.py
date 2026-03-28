from __future__ import annotations

from pathlib import Path

import pytest

from tests.helpers.replay_eod import (
    ReplayScanCaseError,
    iter_scan_replay_case_dirs,
    normalize_scan_artifact,
    run_scan_replay_case,
    validate_scan_replay_case_dir,
)

_SCAN_REPLAY_ROOT = Path(__file__).parent / "fixtures" / "replay_eod" / "scan"
_SCAN_REPLAY_CASES = iter_scan_replay_case_dirs(_SCAN_REPLAY_ROOT)


@pytest.mark.parametrize("case_dir", _SCAN_REPLAY_CASES, ids=lambda path: path.name)
def test_scan_replay_cases_match_expected_artifact(
    case_dir: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    result = run_scan_replay_case(
        case_dir,
        tmp_path=tmp_path,
        monkeypatch=monkeypatch,
    )

    assert result.exit_code == 0
    assert result.normalized_actual == result.expected


def test_normalize_scan_artifact_drops_volatile_meta_and_preserves_candidate_order() -> (
    None
):
    payload = {
        "generated_at": "2026-03-28 12:00 KST",
        "run_id": "11111111-1111-1111-1111-111111111111",
        "run_ts_utc": "2026-03-28T03:00:00Z",
        "git_sha": "deadbeef",
        "report_date": "2024-01-30",
        "eval_context": {
            "market": "KR",
            "session_state": "AFTER_CLOSE",
            "eval_index_policy": "choose_eval_index:v1",
        },
        "config_snapshot": {"strategy_mode": "ema_cross"},
        "summary": {"candidate_count": 2},
        "tickers": ["B", "A"],
        "candidates": [{"ticker": "B"}, {"ticker": "A"}],
        "issues": ["warn"],
        "system_issues": [],
        "screen_outs": ["035420: EMA(20/50) cross not satisfied"],
        "provider": "pykrx",
        "schema": "sab.report.v1",
    }

    normalized = normalize_scan_artifact(payload)

    assert normalized == {
        "report_date": "2024-01-30",
        "eval_context": {
            "market": "KR",
            "session_state": "AFTER_CLOSE",
            "eval_index_policy": "choose_eval_index:v1",
        },
        "config_snapshot": {"strategy_mode": "ema_cross"},
        "summary": {"candidate_count": 2},
        "tickers": ["B", "A"],
        "candidates": [{"ticker": "B"}, {"ticker": "A"}],
        "issues": ["warn"],
        "system_issues": [],
        "screen_outs": ["035420: EMA(20/50) cross not satisfied"],
    }
    assert [candidate["ticker"] for candidate in normalized["candidates"]] == ["B", "A"]


def test_validate_scan_replay_case_dir_rejects_missing_required_files(
    tmp_path: Path,
) -> None:
    case_dir = tmp_path / "broken"
    case_dir.mkdir()
    for name, content in {
        "config.yaml": "data:\n  provider: pykrx\n",
        "watchlist.txt": "005930\n",
        "adjusted_market_data.json": "{}\n",
        "raw_market_data.json": "{}\n",
    }.items():
        (case_dir / name).write_text(content, encoding="utf-8")

    with pytest.raises(ReplayScanCaseError, match="missing required replay case files"):
        validate_scan_replay_case_dir(case_dir)
