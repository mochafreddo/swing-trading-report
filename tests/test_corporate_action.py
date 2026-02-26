from __future__ import annotations

from sab.signals.corporate_action import detect_corporate_action_move


def test_detect_corporate_action_move_returns_split_like_change() -> None:
    closes = [100.0, 50.0, 51.0]

    detected = detect_corporate_action_move(closes)

    assert detected == -0.5


def test_detect_corporate_action_move_ignores_non_split_like_jump() -> None:
    closes = [100.0, 40.0, 41.0]

    detected = detect_corporate_action_move(closes)

    assert detected is None


def test_detect_corporate_action_move_respects_lookback_window() -> None:
    closes = [100.0, 50.0, 51.0, 52.0, 53.0, 54.0, 55.0]

    detected = detect_corporate_action_move(closes, lookback_bars=3)

    assert detected is None
