export const HOLDING_ENTRY_PATTERN_VALUES = [
  "trend_pullback_bounce",
  "swing_high_breakout",
  "rsi_oversold_reversal",
] as const;

export type HoldingEntryPattern = (typeof HOLDING_ENTRY_PATTERN_VALUES)[number];

export function isHoldingEntryPattern(
  value: unknown,
): value is HoldingEntryPattern {
  return (
    typeof value === "string" &&
    (HOLDING_ENTRY_PATTERN_VALUES as readonly string[]).includes(value)
  );
}
