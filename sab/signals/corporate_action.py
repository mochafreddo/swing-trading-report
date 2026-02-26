from __future__ import annotations

_SPLIT_LIKE_RATIOS: tuple[float, ...] = (
    0.5,  # 2:1 split
    1 / 3,  # 3:1 split
    0.25,  # 4:1 split
    0.2,  # 5:1 split
    2.0,  # 1:2 reverse split
    3.0,  # 1:3 reverse split
    4.0,  # 1:4 reverse split
    5.0,  # 1:5 reverse split
    10.0,  # 1:10 reverse split
)


def _is_split_like_ratio(ratio: float, *, tolerance_pct: float = 0.08) -> bool:
    if ratio <= 0:
        return False
    for target in _SPLIT_LIKE_RATIOS:
        if abs(ratio - target) / target <= tolerance_pct:
            return True
    return False


def detect_corporate_action_move(
    closes: list[float], *, lookback_bars: int = 5, threshold_pct: float = 0.45
) -> float | None:
    if len(closes) < 2:
        return None
    start_idx = max(1, len(closes) - lookback_bars)
    for idx in range(start_idx, len(closes)):
        prev_close = closes[idx - 1]
        if prev_close <= 0:
            continue
        split_ratio = closes[idx] / prev_close
        change_pct = (closes[idx] - prev_close) / prev_close
        if abs(change_pct) >= threshold_pct and _is_split_like_ratio(split_ratio):
            return change_pct
    return None


__all__ = ["detect_corporate_action_move"]
