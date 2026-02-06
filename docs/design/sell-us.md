# Design — U.S. Holdings Sell Logic

Goal

- Determine when to SELL, REVIEW, or HOLD existing U.S. equity positions listed in `holdings.yaml` (format `SYMBOL.EXCH`, e.g., `AAPL.NASD`, `JNJ.NYSE`).

Data Source

- KIS Developers Overseas Daily Price API: `/uapi/overseas-price/v1/quotations/dailyprice` (TR `HHDFS76240000`).
- Ticker parsing: `SYMBOL.SUFFIX` → map suffix to KIS `EXCD` code
  - `US|NASDAQ|NASD|NAS` → `NAS`
  - `NYSE|NYS` → `NYS`
  - `AMEX|AMS` → `AMS`
- Cache key: `candles_overseas_{EXCD}_{SYMBOL}` to avoid collisions with KR tickers.
- Fallback: PyKRX is KR‑only; do not fallback for overseas symbols.

Rules (reused from generic sell)

- Indicators: EMA(20/50), RSI(14), ATR(14), SMA(200) computed from daily candles.
- SELL
  - ATR trailing stop: `trail = highest_close_since_entry − k × ATR`, and SELL when `close <= trail` (`k = sell.atr_trail_multiplier`).
    - `highest_close_since_entry` is anchored by `holdings.yaml` `entry_date`; when missing/invalid, a recent window fallback is used.
  - RSI breakdown: `RSI < sell.rsi_floor_alt` (default 30).
  - EMA death cross: EMA20 crosses below EMA50.
- REVIEW
  - Price below both EMAs (when not already SELL).
  - `RSI < sell.rsi_floor` (default 50).
  - SMA200 context breach when `sell.require_sma200 = true`.
  - Time stop: `days_since_entry >= sell.time_stop_days`.
- Overrides per holding are respected: `stop_override`, `target_override`.

Config

- Shared keys (apply to US as well):
  - `sell.atr_trail_multiplier`, `sell.time_stop_days`, `sell.require_sma200`
  - `sell.ema_short`, `sell.ema_long`, `sell.rsi_period`
  - `sell.rsi_floor`, `sell.rsi_floor_alt`, `sell.min_bars`
- Per-market thresholds (US) already exist for screening in `config.yaml` (`screener.us.*`). No separate sell overrides are required initially.

FX Handling

- `sab sell` reuses `fx.resolve_fx_rate`, honoring `FX_MODE`/`USD_KRW_RATE` just like `sab scan`.
- When `FX_MODE=kis` and a `KISClient` is available, the command automatically fetches USD/KRW via `overseas-price/v1/quotations/price-detail` and caches it.
- Sell report header prints the current FX source, and USD-denominated prices display as `$X (₩Y)` in both the summary table and detail sections.

Report Output

- Same Markdown structure as KR: summary table and per-holding details.
- Currency is read from `holdings.yaml` (`entry_currency`). USD-denominated entries display both USD and converted KRW prices when an FX rate is available.

Edge Cases / Resilience

- Insufficient data: mark as `REVIEW` with reason.
- API errors: use cached candles when available; log issue in Appendix.
- No overseas fallback: for symbols with `EXCD`, PyKRX fallback is skipped.

Future Enhancements

- Intraday awareness for U.S. sessions (open/closed) in report header.
- Per-market sell overrides if needed (e.g., different ATR multiplier for US).
