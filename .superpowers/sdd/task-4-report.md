# Task 4 Report

## What changed

- Added eight replay scan fixture directories under `tests/fixtures/replay_eod/scan/`:
  - `us_hybrid_strong_rs_breakout`
  - `kr_hybrid_weak_rs_pullback`
  - `us_hybrid_high_vol_tight_stop`
  - `kr_hybrid_gap_rejected`
  - `us_hybrid_sideways_consolidation`
  - `kr_hybrid_falling_regime_blocked`
  - `kr_hybrid_pullback_volume_confirmation`
  - `us_hybrid_rsi_oversold_reversal`
- Added each case's `case.yaml`, `config.yaml`, `watchlist.txt`, `adjusted_market_data.json`, `raw_market_data.json`, and generated `expected.buy.json`.
- Reused compact deterministic candle shapes:
  - synthetic US breakout data for quality-A breakout and tight-stop breakout-B
  - synthetic US RSI reversal data for quality-A oversold reversal
  - adapted existing KR pullback fixture data for quality-A pullback, weak-RS pullback-B, gap rejection, and falling-regime block
- Made one small replay-test-only adjustment in `tests/test_replay_eod_scan.py`:
  - added an autouse monkeypatch so replay tests prefer fixture-backed benchmark candles for RS/market-regime benchmark resolution before falling back to provider logic
  - this was required so the falling-regime fixture could honestly exercise the benchmark-driven block path instead of the benchmark-unavailable fallback path

## Tests run

1. `UV_CACHE_DIR=.uv-cache uv run python scripts/update_scan_replay_expected.py tests/fixtures/replay_eod/scan/us_hybrid_strong_rs_breakout tests/fixtures/replay_eod/scan/kr_hybrid_weak_rs_pullback tests/fixtures/replay_eod/scan/us_hybrid_high_vol_tight_stop tests/fixtures/replay_eod/scan/kr_hybrid_gap_rejected tests/fixtures/replay_eod/scan/us_hybrid_sideways_consolidation tests/fixtures/replay_eod/scan/kr_hybrid_falling_regime_blocked tests/fixtures/replay_eod/scan/kr_hybrid_pullback_volume_confirmation tests/fixtures/replay_eod/scan/us_hybrid_rsi_oversold_reversal`
   - passed
2. `rg -n '"quality_state": "A"|"quality_state": "B"|"risk_alignment": "tight_stop_vs_volatility"|Gap .*exceeds|Market regime filter blocked|rsi_oversold_reversal|trend_pullback_bounce|swing_high_breakout' tests/fixtures/replay_eod/scan`
   - passed
3. `UV_CACHE_DIR=.uv-cache uv run python -m pytest tests/test_replay_eod_scan.py -q`
   - passed (`25 passed`)

## Files changed

- `tests/test_replay_eod_scan.py`
- `tests/fixtures/replay_eod/scan/us_hybrid_strong_rs_breakout/*`
- `tests/fixtures/replay_eod/scan/kr_hybrid_weak_rs_pullback/*`
- `tests/fixtures/replay_eod/scan/us_hybrid_high_vol_tight_stop/*`
- `tests/fixtures/replay_eod/scan/kr_hybrid_gap_rejected/*`
- `tests/fixtures/replay_eod/scan/us_hybrid_sideways_consolidation/*`
- `tests/fixtures/replay_eod/scan/kr_hybrid_falling_regime_blocked/*`
- `tests/fixtures/replay_eod/scan/kr_hybrid_pullback_volume_confirmation/*`
- `tests/fixtures/replay_eod/scan/us_hybrid_rsi_oversold_reversal/*`

## Self-review

- Verified every new fixture directory satisfies the replay helper file contract.
- Verified the generated artifacts match their metadata outcomes:
  - breakout A
  - weak-RS pullback B
  - tight-stop breakout B
  - gap rejection screen-out
  - falling-regime screen-out
  - pullback A
  - RSI reversal A
- Kept production strategy defaults and signal logic untouched.
- Kept the metadata coverage gate intact.

## Concerns

- `tests/test_replay_eod_scan.py` now owns a replay-only benchmark-resolution patch because benchmark candles otherwise bypass fixture data and go straight to provider clients. This keeps the replay matrix honest, but the benchmark-fixture behavior still lives in the test layer rather than the shared helper/updater path.
