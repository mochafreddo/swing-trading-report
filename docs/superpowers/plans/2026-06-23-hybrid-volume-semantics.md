# Hybrid Volume Semantics Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Normalize `sma_ema_hybrid` buy volume confirmation so pullback, breakout, and reversal patterns all compare the signal candle against a pre-signal average volume baseline.

**Architecture:** Keep the existing report contract and scoring shape. Change the internal `avg_vol` meaning so every successful hybrid buy detector returns the average volume of the preceding `strategy.hybrid.volume_lookback_days` completed candles, excluding the signal candle; scoring continues to read `pattern_context["avg_vol"]`.

**Tech Stack:** Python 3.14, pytest, existing `sab.signals.hybrid_buy` detector helpers, deterministic scan replay fixtures, `uv`, `just`, Markdown docs.

## Global Constraints

- Do not change default hybrid threshold values.
- Do not add a new configuration flag for legacy volume behavior.
- Do not redesign the full scoring model.
- Do not build or extend historical profitability backtesting.
- Do not change sell-side volume behavior; current hybrid sell logic does not directly use volume.
- Preserve the public report shape: candidate fields such as `pattern`, `pattern_reasons`, `score_notes`, `reasons[].id`, and `volume_confirmation` remain in place.
- Use Korean Conventional Commit messages.

---

## File Structure

- Modify `sab/signals/hybrid_buy.py`: own the shared pre-signal volume baseline helper and detector usage.
- Modify `tests/test_hybrid_buy_state.py`: add focused detector regressions that fail under the old signal-inclusive average.
- Modify `docs/STRATEGY.md`: document the shared hybrid buy volume confirmation rule.
- Modify `TODOS.md`: move the active volume semantics item to Completed after tests and docs pass.
- Optionally modify `tests/fixtures/replay_eod/scan/kr_hybrid_pullback_volume_confirmation/expected.buy.json`: refresh only if replay output legitimately changes.
- Optionally modify `tests/fixtures/replay_eod/scan/us_hybrid_rsi_oversold_reversal/expected.buy.json`: refresh only if replay output legitimately changes.

## Task 1: Normalize Detector Volume Baseline

**Files:**
- Modify: `tests/test_hybrid_buy_state.py`
- Modify: `sab/signals/hybrid_buy.py`

**Interfaces:**
- Consumes: `HybridEvaluationSettings`, `HybridPattern`, `_detect_trend_pullback_bounce()`, `_detect_rsi_oversold_reversal()`, and `_settings()` from `tests/test_hybrid_buy_state.py`.
- Produces: `_volume_stats(candles: list[dict[str, Any]], lookback_days: int) -> tuple[float, float]` where the second tuple value is the average volume excluding the latest signal candle.

- [ ] **Step 1: Write the failing detector tests**

Append these tests near the existing pullback/reversal detector tests in `tests/test_hybrid_buy_state.py`:

```python
def test_pullback_volume_thrust_uses_pre_signal_average() -> None:
    settings = _settings()
    settings.volume_lookback_days = 3
    closes = [105.0, 100.0, 98.0, 99.0, 101.0]
    sma_trend = [95.0] * 5
    ema_short = [104.0, 101.0, 99.0, 100.0, 102.0]
    ema_mid = [90.0] * 5
    rsi_vals = [55.0] * 5
    candles = [
        {
            "open": 105.0,
            "high": 106.0,
            "low": 104.0,
            "close": 105.0,
            "volume": 100.0,
        },
        {
            "open": 100.0,
            "high": 101.0,
            "low": 99.0,
            "close": 100.0,
            "volume": 100.0,
        },
        {
            "open": 98.0,
            "high": 99.0,
            "low": 97.0,
            "close": 98.0,
            "volume": 300.0,
        },
        {
            "open": 99.0,
            "high": 100.0,
            "low": 98.0,
            "close": 99.0,
            "volume": 100.0,
        },
        {
            "open": 100.0,
            "high": 102.0,
            "low": 99.0,
            "close": 101.0,
            "volume": 180.0,
        },
    ]

    ok, reasons, pattern, context = _detect_trend_pullback_bounce(
        closes,
        sma_trend,
        ema_short,
        ema_mid,
        rsi_vals,
        candles,
        settings,
    )

    assert ok is True
    assert pattern == HybridPattern.TREND_PULLBACK_BOUNCE
    assert reasons == ["Bullish candle with rising volume"]
    assert context["avg_vol"] == pytest.approx((100.0 + 300.0 + 100.0) / 3)
    assert context["trigger_bullish_vol"] is True


def test_pullback_heavy_selling_uses_pre_signal_average() -> None:
    settings = _settings()
    settings.volume_lookback_days = 3
    closes = [105.0, 100.0, 98.0, 99.0, 101.0]
    sma_trend = [95.0] * 5
    ema_short = [104.0, 101.0, 99.0, 100.0, 102.0]
    ema_mid = [90.0] * 5
    rsi_vals = [55.0] * 5
    candles = [
        {
            "open": 105.0,
            "high": 106.0,
            "low": 104.0,
            "close": 105.0,
            "volume": 100.0,
        },
        {
            "open": 100.0,
            "high": 101.0,
            "low": 99.0,
            "close": 100.0,
            "volume": 100.0,
        },
        {
            "open": 98.0,
            "high": 99.0,
            "low": 97.0,
            "close": 98.0,
            "volume": 100.0,
        },
        {
            "open": 101.0,
            "high": 102.0,
            "low": 98.0,
            "close": 99.0,
            "volume": 400.0,
        },
        {
            "open": 100.0,
            "high": 102.0,
            "low": 99.0,
            "close": 101.0,
            "volume": 1000.0,
        },
    ]

    ok, reasons, pattern, context = _detect_trend_pullback_bounce(
        closes,
        sma_trend,
        ema_short,
        ema_mid,
        rsi_vals,
        candles,
        settings,
    )

    assert ok is False
    assert reasons == ["Heavy selling volume during pullback"]
    assert pattern is None
    assert context == {}


def test_rsi_reversal_volume_confirmation_uses_pre_signal_average() -> None:
    settings = _settings()
    settings.volume_lookback_days = 3
    closes = [100.0, 99.0, 98.0, 99.0, 102.0]
    sma_trend = [90.0] * 5
    ema_short = [96.0, 96.0, 96.0, 96.0, 95.0]
    ema_mid = [94.0] * 5
    rsi_vals = [50.0, 35.0, 32.0, 38.0, 45.0]
    candles = [
        {
            "open": 100.0,
            "high": 101.0,
            "low": 99.0,
            "close": 100.0,
            "volume": 100.0,
        },
        {
            "open": 99.0,
            "high": 100.0,
            "low": 98.0,
            "close": 99.0,
            "volume": 100.0,
        },
        {
            "open": 98.0,
            "high": 99.0,
            "low": 97.0,
            "close": 98.0,
            "volume": 300.0,
        },
        {
            "open": 99.0,
            "high": 100.0,
            "low": 98.0,
            "close": 99.0,
            "volume": 100.0,
        },
        {
            "open": 99.0,
            "high": 103.0,
            "low": 94.0,
            "close": 102.0,
            "volume": 180.0,
        },
    ]

    ok, reasons, pattern, context = _detect_rsi_oversold_reversal(
        closes,
        sma_trend,
        ema_short,
        ema_mid,
        rsi_vals,
        candles,
        settings,
    )

    assert ok is True
    assert pattern == HybridPattern.RSI_OVERSOLD_REVERSAL
    assert reasons == ["Reversal off EMA short/mid with volume"]
    assert context["avg_vol"] == pytest.approx((100.0 + 300.0 + 100.0) / 3)
```

- [ ] **Step 2: Run the red tests**

Run:

```bash
UV_CACHE_DIR=.uv-cache uv run python -m pytest \
  tests/test_hybrid_buy_state.py::test_pullback_volume_thrust_uses_pre_signal_average \
  tests/test_hybrid_buy_state.py::test_pullback_heavy_selling_uses_pre_signal_average \
  tests/test_hybrid_buy_state.py::test_rsi_reversal_volume_confirmation_uses_pre_signal_average \
  -q
```

Expected: all three tests fail on the current implementation. The first and third tests fail because `avg_vol` includes the signal candle. The second test fails because the signal candle's large volume masks the heavy-selling pullback bar.

- [ ] **Step 3: Implement the shared pre-signal baseline**

In `sab/signals/hybrid_buy.py`, replace the existing `_volume_stats()` and `_avg_volume_excluding_latest()` block with this implementation:

```python
def _volume_stats(
    candles: list[dict[str, Any]], lookback_days: int
) -> tuple[float, float]:
    """Return previous-bar volume and average volume before the signal bar."""
    if not candles:
        return 0.0, 0.0
    vols: list[float] = []
    for candle in candles:
        volume, _ = _to_volume_and_invalid(candle.get("volume"))
        vols.append(volume)
    prev_vol = vols[-2] if len(vols) >= 2 else vols[-1]
    avg_vol = _avg_volume_excluding_latest(candles, lookback_days)
    return prev_vol, avg_vol


def _avg_volume_excluding_latest(
    candles: list[dict[str, Any]], lookback_days: int
) -> float:
    """Average volume over bars before the latest signal candle."""
    if len(candles) <= 1 or lookback_days <= 0:
        return 0.0
    historical = candles[:-1]
    vols: list[float] = []
    for candle in historical:
        volume, _ = _to_volume_and_invalid(candle.get("volume"))
        vols.append(volume)
    window = vols[-lookback_days:] if len(vols) >= lookback_days else vols
    return sum(window) / len(window) if window else 0.0
```

Do not change `_detect_swing_high_breakout()`; it already uses `_avg_volume_excluding_latest()`.

- [ ] **Step 4: Run the focused tests**

Run:

```bash
UV_CACHE_DIR=.uv-cache uv run python -m pytest \
  tests/test_hybrid_buy_state.py::test_pullback_volume_thrust_uses_pre_signal_average \
  tests/test_hybrid_buy_state.py::test_pullback_heavy_selling_uses_pre_signal_average \
  tests/test_hybrid_buy_state.py::test_rsi_reversal_volume_confirmation_uses_pre_signal_average \
  -q
```

Expected: all three tests pass.

- [ ] **Step 5: Run the full hybrid buy unit suite**

Run:

```bash
UV_CACHE_DIR=.uv-cache uv run python -m pytest tests/test_hybrid_buy_state.py -q
```

Expected: all tests in `tests/test_hybrid_buy_state.py` pass.

- [ ] **Step 6: Commit the detector change**

Run:

```bash
git status --short
git add sab/signals/hybrid_buy.py tests/test_hybrid_buy_state.py
git commit -m "fix(strategy): hybrid 거래량 기준을 통일"
```

Expected: the commit includes only `sab/signals/hybrid_buy.py` and `tests/test_hybrid_buy_state.py`.

## Task 2: Document and Close the TODO

**Files:**
- Modify: `docs/STRATEGY.md`
- Modify: `TODOS.md`

**Interfaces:**
- Consumes: normalized `pattern_context["avg_vol"]` semantics from Task 1.
- Produces: operator-facing strategy documentation and a completed TODO entry.

- [ ] **Step 1: Update strategy documentation**

In `docs/STRATEGY.md`, replace the current Swing high breakout volume bullet with this shared hybrid buy volume rule:

```markdown
- Hybrid buy의 볼륨 확인은 패턴별 신호봉을 제외한 직전 `strategy.hybrid.volume_lookback_days`일 평균 거래량 대비로 평가합니다.
  - 적용 대상: Trend pullback bounce, Swing high breakout, RSI oversold reversal.
  - 의도: 신호봉 당일 거래량이 자기 자신의 비교 기준선을 움직이지 않게 해 `volume > Nd avg` 해석을 고정합니다.
```

Keep the surrounding consolidation and KR breakout confirmation bullets intact.

- [ ] **Step 2: Move the active TODO to Completed**

In `TODOS.md`, remove this active bullet:

```markdown
- 2026-06-18: Review pullback/reversal volume confirmation semantics. Breakout volume uses the pre-breakout average, while pullback/reversal paths include the signal candle in the average; either normalize to pre-signal averages or document and test the intentional difference.
```

Add this entry at the top of the `## Completed` section:

```markdown
- 2026-06-23: Normalized `sma_ema_hybrid` volume confirmation semantics so breakout, pullback, and reversal compare the signal candle to the preceding N-day average; added focused detector regressions and strategy documentation.
```

- [ ] **Step 3: Verify documentation diff**

Run:

```bash
git diff -- docs/STRATEGY.md TODOS.md
```

Expected: the diff documents one shared hybrid buy volume baseline and moves only the active TODO item to Completed.

- [ ] **Step 4: Commit documentation**

Run:

```bash
git status --short
git add docs/STRATEGY.md TODOS.md
git commit -m "docs(strategy): hybrid 거래량 기준을 문서화"
```

Expected: the commit includes only `docs/STRATEGY.md` and `TODOS.md`.

## Task 3: Replay and Quality Verification

**Files:**
- Optionally modify: `tests/fixtures/replay_eod/scan/kr_hybrid_pullback_volume_confirmation/expected.buy.json`
- Optionally modify: `tests/fixtures/replay_eod/scan/us_hybrid_rsi_oversold_reversal/expected.buy.json`

**Interfaces:**
- Consumes: normalized detector behavior and docs from Tasks 1 and 2.
- Produces: verified replay fixtures and final Python quality evidence.

- [ ] **Step 1: Run scan replay tests**

Run:

```bash
UV_CACHE_DIR=.uv-cache uv run python -m pytest tests/test_replay_eod_scan.py -q
```

Expected: replay tests pass. If the only failures are deterministic `expected.buy.json` diffs caused by the normalized `avg_vol` baseline, continue to Step 2. If failures are behavioral mismatches such as missing candidates, wrong patterns, wrong quality states, or new system issues, stop and inspect the failing replay case before refreshing artifacts.

- [ ] **Step 2: Refresh affected replay artifacts when Step 1 shows only expected JSON drift**

Run this command only for deterministic expected-artifact drift:

```bash
UV_CACHE_DIR=.uv-cache uv run python scripts/update_scan_replay_expected.py \
  tests/fixtures/replay_eod/scan/kr_hybrid_pullback_volume_confirmation \
  tests/fixtures/replay_eod/scan/us_hybrid_rsi_oversold_reversal
```

Expected: the command exits 0 and rewrites only the affected `expected.buy.json` files.

- [ ] **Step 3: Re-run replay tests after any refresh**

Run:

```bash
UV_CACHE_DIR=.uv-cache uv run python -m pytest tests/test_replay_eod_scan.py -q
```

Expected: replay tests pass.

- [ ] **Step 4: Run formatting and static checks**

Run:

```bash
UV_CACHE_DIR=.uv-cache uv run ruff check sab/signals/hybrid_buy.py tests/test_hybrid_buy_state.py
UV_CACHE_DIR=.uv-cache uv run ruff format --check sab/signals/hybrid_buy.py tests/test_hybrid_buy_state.py
UV_CACHE_DIR=.uv-cache uv run mypy --config-file pyproject.toml
```

Expected: all commands pass.

- [ ] **Step 5: Run the preferred Python quality gate**

Run:

```bash
just quality
```

Expected: `just quality` passes. If it cannot run because of missing local tool installation, run `mise exec -- just quality`. If the broad gate is blocked by an unrelated environmental failure, record the exact failure and keep the successful targeted pytest, replay, ruff, and mypy evidence in the final handoff.

- [ ] **Step 6: Commit replay artifact changes when they exist**

Run:

```bash
git status --short
git add tests/fixtures/replay_eod/scan/kr_hybrid_pullback_volume_confirmation/expected.buy.json tests/fixtures/replay_eod/scan/us_hybrid_rsi_oversold_reversal/expected.buy.json
git diff --cached --quiet || git commit -m "test(strategy): hybrid 거래량 replay 기대값 갱신"
```

Expected: if replay artifacts changed, they are committed separately. If no replay artifacts changed, `git diff --cached --quiet` exits 0 and no commit is created.

## Self-Review Checklist

- Spec coverage: Task 1 covers pre-signal averages for pullback and reversal while keeping breakout unchanged; Task 2 covers `docs/STRATEGY.md` and `TODOS.md`; Task 3 covers replay and final quality gates.
- Placeholder scan: this plan has no unresolved implementation placeholders.
- Type consistency: `_volume_stats()` continues returning `tuple[float, float]`, and existing detector call sites continue reading `prev_vol` and `avg_vol` without interface changes.
- Scope check: no config flags, threshold changes, sell-side changes, or historical backtest work are included.
