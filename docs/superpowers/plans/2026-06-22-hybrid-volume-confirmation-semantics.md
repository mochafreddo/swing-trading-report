# Hybrid Volume Confirmation Semantics Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Document and regression-test the intentional volume baseline distinction across hybrid buy patterns.

**Architecture:** Keep production behavior unchanged. Add focused characterization coverage for `trend_pullback_bounce` and `rsi_oversold_reversal`, then update strategy/TODO documentation to match the tested contract.

**Tech Stack:** Python 3.14, pytest via `just test`, project docs in Markdown.

## Global Constraints

- Do not change hybrid buy production behavior in this task.
- Keep edits limited to hybrid buy tests and documentation unless a failing test exposes a production mismatch.
- Use repository-local commands: `just test ...` and `just quality`.
- Move the active TODO only after tests and strategy docs cover the decision.

---

### Task 1: Characterize Pullback Volume Baseline

**Files:**
- Modify: `tests/test_hybrid_buy_state.py`

**Interfaces:**
- Consumes: `_detect_trend_pullback_bounce(...)`
- Produces: A regression test proving pullback volume confirmation uses a signal-inclusive rolling average.

- [ ] **Step 1: Write the failing test**

Add a test where the signal bar volume is above the pre-signal average but below the signal-inclusive average. Expected result: no `Bullish candle with rising volume` trigger.

- [ ] **Step 2: Run test to verify behavior is covered**

Run: `just test tests/test_hybrid_buy_state.py::test_pullback_volume_confirmation_uses_signal_inclusive_average -q`

- [ ] **Step 3: Adjust only if the current behavior contradicts the design**

No production edit is expected. If the test fails because the trigger appears, inspect `_volume_stats()` usage before changing code.

- [ ] **Step 4: Re-run the targeted test**

Run: `just test tests/test_hybrid_buy_state.py::test_pullback_volume_confirmation_uses_signal_inclusive_average -q`

### Task 2: Characterize RSI Reversal Volume Baseline

**Files:**
- Modify: `tests/test_hybrid_buy_state.py`

**Interfaces:**
- Consumes: `_detect_rsi_oversold_reversal(...)`
- Produces: A regression test proving RSI reversal volume confirmation uses a signal-inclusive rolling average.

- [ ] **Step 1: Write the failing test**

Add a test where the signal bar volume is above the pre-signal average but below the signal-inclusive average. Expected result: the reversal is rejected with `No strong bullish candle with rising volume`.

- [ ] **Step 2: Run test to verify behavior is covered**

Run: `just test tests/test_hybrid_buy_state.py::test_rsi_reversal_volume_confirmation_uses_signal_inclusive_average -q`

- [ ] **Step 3: Adjust only if the current behavior contradicts the design**

No production edit is expected. If the test unexpectedly passes as a reversal, inspect `_volume_stats()` usage before changing code.

- [ ] **Step 4: Re-run the targeted test**

Run: `just test tests/test_hybrid_buy_state.py::test_rsi_reversal_volume_confirmation_uses_signal_inclusive_average -q`

### Task 3: Update Documentation and TODO State

**Files:**
- Modify: `docs/STRATEGY.md`
- Modify: `TODOS.md`

**Interfaces:**
- Consumes: The tested semantics from Tasks 1 and 2.
- Produces: Operator-facing documentation and closed TODO state.

- [ ] **Step 1: Update strategy docs**

Document that breakout uses a pre-signal baseline, while pullback/reversal use a signal-inclusive rolling average.

- [ ] **Step 2: Move TODO item**

Move the 2026-06-18 active item about volume confirmation semantics to Completed with the decision summary.

- [ ] **Step 3: Run targeted hybrid buy tests**

Run: `just test tests/test_hybrid_buy_state.py -q`

- [ ] **Step 4: Run the final quality gate**

Run: `just quality`
