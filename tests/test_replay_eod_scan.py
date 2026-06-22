from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest

from tests.helpers.replay_eod import (
    ReplayScanCaseError,
    iter_scan_replay_case_dirs,
    load_scan_replay_case_metadata,
    load_scan_replay_case_metadatas,
    normalize_scan_artifact,
    run_scan_replay_case,
    validate_scan_replay_case_dir,
)

_SCAN_REPLAY_ROOT = Path(__file__).parent / "fixtures" / "replay_eod" / "scan"
_SCAN_REPLAY_CASES = iter_scan_replay_case_dirs(_SCAN_REPLAY_ROOT)
_REQUIRED_REPLAY_MARKETS = {"KR", "US"}
_REQUIRED_REPLAY_REGIMES = {"rising", "sideways", "falling"}
_REQUIRED_REPLAY_PATTERNS = {
    "trend_pullback_bounce",
    "swing_high_breakout",
    "rsi_oversold_reversal",
}
_REQUIRED_REPLAY_OUTCOMES = {
    "candidate_quality_a",
    "candidate_quality_b",
    "rejected_by_gap",
    "blocked_by_market_regime",
}
_REQUIRED_REPLAY_THRESHOLD_AXES = {
    "rsi",
    "consolidation",
    "gap",
    "stop_alignment",
    "profit_target",
    "volume_confirmation",
}


def _build_hybrid_replay_config(
    base_config: str,
    *,
    rsi_zone_high: int = 58,
    max_gap_pct: float = 0.04,
    use_sma60_filter: bool = True,
) -> str:
    use_sma60_filter_text = "true" if use_sma60_filter else "false"
    return base_config.replace(
        "  mode: ema_cross\n",
        "  mode: sma_ema_hybrid\n",
    ).replace(
        "  rs_lookback_days: 5\n",
        f"""  rs_lookback_days: 5
  rs_benchmark_return: 0.07
  hybrid:
    sma_trend_period: 20
    ema_short_period: 10
    ema_mid_period: 21
    rsi_period: 14
    rsi_zone_low: 40
    rsi_zone_high: {rsi_zone_high}
    rsi_oversold_low: 25
    rsi_oversold_high: 38
    pullback_max_bars: 7
    breakout_consolidation_min_bars: 4
    breakout_consolidation_max_bars: 12
    breakout_consolidation_max_range_pct: 0.08
    volume_lookback_days: 3
    max_gap_pct: {max_gap_pct}
    use_sma60_filter: {use_sma60_filter_text}
    sma60_period: 55
    kr_breakout_requires_confirmation: false
""",
    )


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


def test_scan_replay_hybrid_report_preserves_hybrid_config_snapshot(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    base_config = (
        _SCAN_REPLAY_ROOT / "kr_ema_cross_baseline" / "config.yaml"
    ).read_text(encoding="utf-8")
    config_text = _build_hybrid_replay_config(base_config)
    result = run_scan_replay_case(
        _SCAN_REPLAY_ROOT / "kr_ema_cross_baseline",
        tmp_path=tmp_path,
        monkeypatch=monkeypatch,
        config_text=config_text,
    )

    snapshot = result.normalized_actual["config_snapshot"]
    assert result.exit_code == 0
    assert snapshot["strategy_mode"] == "sma_ema_hybrid"
    assert snapshot["rs_benchmark_return"] == 0.07
    assert snapshot["hybrid"] == {
        "sma_trend_period": 20,
        "ema_short_period": 10,
        "ema_mid_period": 21,
        "rsi_period": 14,
        "rsi_zone_low": 40.0,
        "rsi_zone_high": 58.0,
        "rsi_oversold_low": 25.0,
        "rsi_oversold_high": 38.0,
        "pullback_max_bars": 7,
        "breakout_consolidation_min_bars": 4,
        "breakout_consolidation_max_bars": 12,
        "breakout_consolidation_max_range_pct": 0.08,
        "volume_lookback_days": 3,
        "max_gap_pct": 0.04,
        "use_sma60_filter": True,
        "sma60_period": 55,
        "kr_breakout_requires_confirmation": False,
    }


def test_scan_replay_hybrid_report_preserves_quality_fields_and_order(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    result = run_scan_replay_case(
        _SCAN_REPLAY_ROOT / "kr_hybrid_quality_order",
        tmp_path=tmp_path,
        monkeypatch=monkeypatch,
    )

    assert result.exit_code == 0
    candidates = result.normalized_actual["candidates"]
    assert [candidate["ticker"] for candidate in candidates] == ["000660", "005930"]
    assert [
        (
            candidate["ticker"],
            candidate["risk_alignment"],
            candidate["quality_state"],
            candidate["quality_reasons"],
        )
        for candidate in candidates
    ] == [
        (
            "000660",
            "aligned",
            "A",
            ["entry_state_ready", "relative_strength_positive"],
        ),
        (
            "005930",
            "tight_stop_vs_volatility",
            "B",
            [
                "entry_state_ready",
                "relative_strength_positive",
                "risk_alignment_tight_stop",
            ],
        ),
    ]
    assert candidates[0]["score_value"] == pytest.approx(candidates[1]["score_value"])
    assert candidates[0]["rs_return_value"] == pytest.approx(
        candidates[1]["rs_return_value"]
    )
    assert (
        candidates[0]["avg_dollar_volume_value"]
        < candidates[1]["avg_dollar_volume_value"]
    )


def test_scan_replay_case_reports_missing_benchmark_from_fixture(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source_case_dir = _SCAN_REPLAY_ROOT / "kr_hybrid_falling_regime_blocked"
    case_dir = tmp_path / "source" / source_case_dir.name
    workspace_root = tmp_path / "workspace"
    shutil.copytree(source_case_dir, case_dir)

    adjusted_market_data_path = case_dir / "adjusted_market_data.json"
    adjusted_market_data = json.loads(
        adjusted_market_data_path.read_text(encoding="utf-8")
    )
    adjusted_market_data.pop("069500")
    adjusted_market_data_path.write_text(
        json.dumps(adjusted_market_data, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )

    result = run_scan_replay_case(
        case_dir,
        tmp_path=workspace_root,
        monkeypatch=monkeypatch,
    )

    messages = (
        result.normalized_actual["issues"]
        + result.normalized_actual["system_issues"]
        + result.normalized_actual["screen_outs"]
    )
    assert result.exit_code == 0
    assert any(
        "069500: Market regime benchmark unavailable from replay fixture" in message
        for message in messages
    )
    assert not any("client not initialized" in message for message in messages)
    assert result.normalized_actual["summary"]["market_regime_unavailable_count"] == 1


def test_scan_replay_metadata_covers_active_swing_threshold_matrix() -> None:
    metadata = load_scan_replay_case_metadatas(_SCAN_REPLAY_ROOT)

    markets = {case.market for case in metadata}
    regimes = {case.regime for case in metadata}
    patterns = {case.pattern for case in metadata}
    relative_strengths = {case.relative_strength for case in metadata}
    volatility_states = {case.volatility for case in metadata}
    outcomes = {case.expected_outcome for case in metadata}
    threshold_axes = set().union(*(case.threshold_axes for case in metadata))

    assert markets >= _REQUIRED_REPLAY_MARKETS
    assert regimes >= _REQUIRED_REPLAY_REGIMES
    assert patterns >= _REQUIRED_REPLAY_PATTERNS
    assert {"strong", "weak"} <= relative_strengths
    assert {"normal", "high"} <= volatility_states
    assert outcomes >= _REQUIRED_REPLAY_OUTCOMES
    assert threshold_axes >= _REQUIRED_REPLAY_THRESHOLD_AXES


def test_load_scan_replay_case_metadata_parses_valid_case(tmp_path: Path) -> None:
    case_dir = tmp_path / "valid"
    case_dir.mkdir()
    (case_dir / "case.yaml").write_text(
        "\n".join(
            [
                "schema: sab.replay.scan-case.v1",
                'purpose: "strong US breakout candidate with quality A"',
                "market: US",
                "strategy_mode: sma_ema_hybrid",
                "regime: rising",
                "pattern: swing_high_breakout",
                "relative_strength: strong",
                "volatility: normal",
                "expected_outcome: candidate_quality_a",
                "threshold_axes:",
                "  - consolidation",
                "  - volume_confirmation",
                "  - relative_strength",
                "",
            ]
        ),
        encoding="utf-8",
    )

    metadata = load_scan_replay_case_metadata(case_dir)

    assert metadata.case_dir == case_dir
    assert metadata.name == "valid"
    assert metadata.market == "US"
    assert metadata.strategy_mode == "sma_ema_hybrid"
    assert metadata.regime == "rising"
    assert metadata.pattern == "swing_high_breakout"
    assert metadata.relative_strength == "strong"
    assert metadata.volatility == "normal"
    assert metadata.expected_outcome == "candidate_quality_a"
    assert metadata.threshold_axes == frozenset(
        {"consolidation", "volume_confirmation", "relative_strength"}
    )


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("schema", "wrong.schema"),
        ("market", "JP"),
        ("strategy_mode", "hybrid"),
        ("regime", "bull"),
        ("pattern", "cup_handle"),
        ("relative_strength", "medium"),
        ("volatility", "medium"),
        ("expected_outcome", "maybe_candidate"),
    ],
)
def test_load_scan_replay_case_metadata_rejects_invalid_choices(
    tmp_path: Path,
    field: str,
    value: str,
) -> None:
    payload = {
        "schema": "sab.replay.scan-case.v1",
        "purpose": "invalid field check",
        "market": "KR",
        "strategy_mode": "sma_ema_hybrid",
        "regime": "rising",
        "pattern": "trend_pullback_bounce",
        "relative_strength": "strong",
        "volatility": "normal",
        "expected_outcome": "candidate_quality_a",
        "threshold_axes": ["rsi"],
    }
    payload[field] = value
    case_dir = tmp_path / "invalid"
    case_dir.mkdir()
    yaml_text = "\n".join(
        [
            f"schema: {payload['schema']}",
            f"purpose: {payload['purpose']!r}",
            f"market: {payload['market']}",
            f"strategy_mode: {payload['strategy_mode']}",
            f"regime: {payload['regime']}",
            f"pattern: {payload['pattern']}",
            f"relative_strength: {payload['relative_strength']}",
            f"volatility: {payload['volatility']}",
            f"expected_outcome: {payload['expected_outcome']}",
            "threshold_axes:",
            *[f"  - {axis}" for axis in payload["threshold_axes"]],
            "",
        ]
    )
    (case_dir / "case.yaml").write_text(yaml_text, encoding="utf-8")

    with pytest.raises(ReplayScanCaseError, match=field):
        load_scan_replay_case_metadata(case_dir)


def test_load_scan_replay_case_metadata_rejects_empty_threshold_axes(
    tmp_path: Path,
) -> None:
    case_dir = tmp_path / "empty_axes"
    case_dir.mkdir()
    (case_dir / "case.yaml").write_text(
        "\n".join(
            [
                "schema: sab.replay.scan-case.v1",
                'purpose: "empty axes check"',
                "market: KR",
                "strategy_mode: sma_ema_hybrid",
                "regime: rising",
                "pattern: trend_pullback_bounce",
                "relative_strength: strong",
                "volatility: normal",
                "expected_outcome: candidate_quality_a",
                "threshold_axes: []",
                "",
            ]
        ),
        encoding="utf-8",
    )

    with pytest.raises(ReplayScanCaseError, match="threshold_axes"):
        load_scan_replay_case_metadata(case_dir)


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
