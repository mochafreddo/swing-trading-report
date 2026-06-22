상태: Accepted

# Hybrid Volume Confirmation Semantics Design

## Goal

Close the active TODO about `sma_ema_hybrid` volume confirmation semantics by
making the current pattern-specific baselines explicit and regression-tested.

## Current Behavior

`swing_high_breakout` compares the breakout bar volume against the prior
`volume_lookback_days` average, excluding the breakout bar. This is already
documented in `docs/STRATEGY.md` and covered by
`test_swing_breakout_volume_check_uses_pre_breakout_average`.

`trend_pullback_bounce` and `rsi_oversold_reversal` use `_volume_stats()`, whose
average includes the signal bar. That means the signal candle must be strong
enough to satisfy a rolling average that includes itself, not just exceed the
pre-signal baseline.

## Decision

Keep the current behavior and document it as intentional.

The distinction is useful:

- Breakout volume is an event-vs-baseline check: the breakout bar is compared
  with the pre-breakout consolidation volume.
- Pullback and reversal volume are confirmation checks: the signal bar is part
  of the confirmation window, so the bar must hold up even after it contributes
  to the recent rolling average.

Changing pullback/reversal to pre-signal averages would alter candidate
classification and replay artifacts without profitability evidence. Historical
backtesting can revisit this later, but this task should stabilize the existing
rule semantics.

## Implementation

- Add direct characterization tests for pullback and RSI reversal volume average
  semantics in `tests/test_hybrid_buy_state.py`.
- Update `docs/STRATEGY.md` to describe the breakout versus pullback/reversal
  baseline distinction.
- Move the active `TODOS.md` item to Completed once tests and docs cover the
  decision.

## Verification

- Run the two new targeted pytest cases.
- Run `just test tests/test_hybrid_buy_state.py`.
- Run `just quality` before committing.
