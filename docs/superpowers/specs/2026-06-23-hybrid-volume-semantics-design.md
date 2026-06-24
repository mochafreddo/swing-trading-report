상태: Accepted
Date: 2026-06-23

# Hybrid Volume Semantics Design

## Problem Brief

### Context

The `sma_ema_hybrid` buy evaluator has three major pattern paths:

- `trend_pullback_bounce`
- `swing_high_breakout`
- `rsi_oversold_reversal`

`swing_high_breakout` already evaluates volume confirmation against the average
volume from the bars before the breakout signal bar. The strategy document also
states this explicitly.

The pullback and reversal paths use `_volume_stats(candles, lookback_days)`,
which computes the average from the latest `N` candles including the signal
candle. That creates a subtle semantic split:

- breakout: signal volume is compared with a pre-signal baseline;
- pullback/reversal: signal volume contributes to the baseline it must beat.

The same pullback/reversal average also flows into the candidate score's
`volume_confirmation` reason and the pullback heavy-selling guard.

### Goal

Normalize hybrid buy volume confirmation semantics so all pattern paths compare
the signal candle against a pre-signal volume baseline and protect that contract
with focused tests and strategy documentation.

### Non-Goals

- Do not change default hybrid threshold values.
- Do not add a new configuration flag for legacy volume behavior.
- Do not redesign the full scoring model.
- Do not build or extend historical profitability backtesting.
- Do not change sell-side volume behavior; current hybrid sell logic does not
  directly use volume.

## Recommended Approach

Use a single pre-signal volume baseline for every hybrid buy pattern.

The implementation should replace the pullback/reversal use of the
signal-inclusive average with an explicit helper whose meaning is clear from the
name. The helper should use the previous `volume_lookback_days` completed bars,
excluding the candidate signal bar. The result should be carried in
`pattern_context["avg_vol"]` so detection, scoring, report reasons, and replay
artifacts all describe the same baseline.

## Approaches Considered

### Approach A: Normalize All Hybrid Buy Volume Confirmation

All pattern paths use the same pre-signal average baseline.

Tradeoff: this can move a few boundary candidates because the denominator
changes, but the rule meaning becomes consistent and easier to explain.

Recommendation: use this approach.

### Approach B: Preserve Current Behavior and Document the Difference

Keep breakout as pre-signal and pullback/reversal as signal-inclusive, then add
tests documenting the difference.

Tradeoff: this avoids behavior changes, but it preserves a rule split without a
clear trading rationale. It also leaves score explanations harder to interpret.

### Approach C: Normalize Confirmation and Redesign Pullback Heavy Selling

Use pre-signal volume confirmation and separately evaluate heavy-selling volume
against only the pullback window.

Tradeoff: this is more expressive, but it changes two concepts in one pass. The
first safe change should only normalize the shared baseline. A later follow-up
can revisit whether the heavy-selling guard deserves a pullback-window-specific
baseline.

## Design Summary

The design keeps the current public report shape. Candidate fields such as
`pattern`, `pattern_reasons`, `score_notes`, `reasons[].id`, and
`volume_confirmation` remain in place.

The behavior change is internal:

- `_avg_volume_excluding_latest()` or an equivalent clearly named helper is the
  canonical signal-excluding volume average helper.
- `_detect_trend_pullback_bounce()` stores that helper's result as
  `pattern_context["avg_vol"]`.
- `_detect_rsi_oversold_reversal()` uses the same baseline for the strong
  bullish volume check and stores it in `pattern_context["avg_vol"]`.
- `_detect_swing_high_breakout()` keeps using the same baseline it already uses.
- `_score_hybrid_candidate()` continues to read `pattern_context["avg_vol"]`;
  after this change the value has one meaning for all three patterns.

## Component Design

### `sab/signals/hybrid_buy.py`

Keep volume data validation unchanged. Missing and non-finite volume remain
system issues before pattern detection.

Refine helper usage:

- Preserve `prev_vol` behavior for pullback's "rising volume versus yesterday"
  check.
- Compute `avg_vol` from the previous `volume_lookback_days` candles, excluding
  the latest candle.
- Use `today_volume > max(prev_vol, avg_vol)` for pullback volume thrust.
- Use `today_volume >= avg_vol`, with the existing `avg_vol == 0.0` fallback,
  for reversal strong bullish volume.
- Use the same `avg_vol` in heavy-selling detection for this pass. This keeps
  scope small while removing signal-candle self-influence.

### `tests/test_hybrid_buy_state.py`

Add focused regression tests around the helper consumers:

- pullback volume thrust should pass when today's volume beats the previous
  two-bar baseline but would fail if today's candle were included in a two-day
  average;
- reversal volume confirmation should pass under the same boundary condition;
- pullback heavy-selling should still detect a high-volume red pullback bar even
  when the signal candle has very large volume.

Existing contract tests that monkeypatch pattern contexts should remain useful
because they verify the report/scoring contract independently of detector
internals.

### `tests/fixtures/replay_eod/scan/*`

Run the existing scan replay tests after the logic change. Update expected
artifacts only if deterministic outputs legitimately change.

The current `kr_hybrid_pullback_volume_confirmation` and
`us_hybrid_rsi_oversold_reversal` cases are the main fixture-level guards for
the affected paths.

### `docs/STRATEGY.md`

Document a single hybrid buy volume rule:

- volume confirmation compares the signal candle to the average volume of the
  preceding `strategy.hybrid.volume_lookback_days` completed candles;
- the signal candle is excluded from that average for breakout, pullback, and
  reversal paths;
- the intent is to avoid letting the signal candle move its own baseline.

### `TODOS.md`

After implementation and verification, move the active TODO to `Completed` with
a short note that the behavior was normalized, tested, and documented.

## Data Flow

1. `evaluate_ticker_hybrid()` validates the candle series and volume data.
2. `_detect_hybrid_pattern()` tries pullback, breakout, then reversal.
3. Each successful detector returns `pattern_context["avg_vol"]` with the
   pre-signal baseline.
4. `_resolve_hybrid_entry_state()` uses pattern-specific flags as before.
5. `_score_hybrid_candidate()` reads `pattern_context["avg_vol"]` and today's
   volume to decide whether to add the `volume_confirmation` score reason.
6. The report builder emits the same candidate fields and reason identifiers.

## Error Handling

No new error class or configuration validation is required.

The existing invalid volume behavior remains:

- missing volume values produce the existing missing-volume system issue;
- non-finite volume values produce the existing non-finite-volume system issue;
- zero average dollar volume still blocks candidates through the existing
  liquidity gate.

For very short candle series, the pre-signal average helper returns `0.0`, which
matches current fallback behavior and keeps detector behavior stable for small
unit fixtures.

## Testing Strategy

Run the narrow tests first:

```bash
just test tests/test_hybrid_buy_state.py
```

Then run replay coverage for scan artifacts:

```bash
just test tests/test_replay_eod_scan.py
```

For final Python-side confidence, run:

```bash
just quality
```

If `just quality` is too broad for the active environment, run the targeted
pytest commands plus:

```bash
just ruff
just mypy
```

## Acceptance Criteria

- Pullback, breakout, and reversal volume confirmation all use a pre-signal
  volume average.
- The signal candle no longer contributes to `pattern_context["avg_vol"]`.
- Candidate scoring still emits `volume_confirmation` when today's volume meets
  the normalized baseline.
- Focused tests fail on the old signal-inclusive pullback/reversal behavior and
  pass on the normalized behavior.
- `docs/STRATEGY.md` states the shared volume baseline semantics.
- The active TODO is moved to `Completed` after verification.
