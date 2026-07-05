export const KR_TICKER_PATTERN = /^\d{6}$/;
export const US_TICKER_PATTERN =
  /^[A-Z][A-Z0-9]*(?:[/.][ABC])?\.(NASDAQ|NASD|NAS|NYSE|NYS|AMEX|AMS)$/;

const US_BASE_SYMBOL_PATTERN = /^[A-Z][A-Z0-9]*$/;
const US_CLASS_DOT_SYMBOL_PATTERN = /^([A-Z][A-Z0-9]*)\.([ABC])$/;
const US_CLASS_SLASH_SYMBOL_PATTERN = /^([A-Z][A-Z0-9]*)\/([ABC])$/;

const US_TICKER_SUFFIX_TO_EXCHANGE = new Map([
  ["NASDAQ", "NAS"],
  ["NASD", "NAS"],
  ["NAS", "NAS"],
  ["NYSE", "NYS"],
  ["NYS", "NYS"],
  ["AMEX", "AMS"],
  ["AMS", "AMS"],
]);

interface UsTickerParts {
  base: string;
  suffix: string;
}

function canonicalizeUsSymbol(base: string): string | null {
  if (US_BASE_SYMBOL_PATTERN.test(base)) {
    return base;
  }
  const dotMatch = base.match(US_CLASS_DOT_SYMBOL_PATTERN);
  if (dotMatch) {
    return `${dotMatch[1]}.${dotMatch[2]}`;
  }
  const slashMatch = base.match(US_CLASS_SLASH_SYMBOL_PATTERN);
  if (slashMatch) {
    return `${slashMatch[1]}.${slashMatch[2]}`;
  }
  return null;
}

function parseUsTickerParts(ticker: string): UsTickerParts | null {
  const normalized = ticker.trim().toUpperCase();
  const lastDotIndex = normalized.lastIndexOf(".");
  if (lastDotIndex <= 0) {
    return null;
  }
  const baseRaw = normalized.slice(0, lastDotIndex);
  const base = canonicalizeUsSymbol(baseRaw);
  const suffixRaw = normalized.slice(lastDotIndex + 1);
  const suffix = US_TICKER_SUFFIX_TO_EXCHANGE.get(suffixRaw);
  if (!base || !suffix) {
    return null;
  }
  return { base, suffix };
}

export function normalizeHoldingTickerForMutation(ticker: string): string {
  const normalized = ticker.trim().toUpperCase();
  if (KR_TICKER_PATTERN.test(normalized)) {
    return normalized;
  }

  const parts = parseUsTickerParts(normalized);
  if (!parts) {
    return normalized;
  }

  return `${parts.base}.${parts.suffix}`;
}

export function parseHoldingTickerForMutation(ticker: string): string | null {
  const normalized = ticker.trim().toUpperCase();
  if (normalized.length < 1 || normalized.length > 32) {
    return null;
  }
  if (
    !KR_TICKER_PATTERN.test(normalized) &&
    !US_TICKER_PATTERN.test(normalized)
  ) {
    return null;
  }
  return normalizeHoldingTickerForMutation(normalized);
}

export function inferHoldingCurrencyForTicker(
  ticker: string,
): "KRW" | "USD" | null {
  const normalized = normalizeHoldingTickerForMutation(ticker);
  if (KR_TICKER_PATTERN.test(normalized)) {
    return "KRW";
  }
  if (US_TICKER_PATTERN.test(normalized)) {
    return "USD";
  }
  return null;
}

export function buildHoldingTickerAliases(ticker: string): string[] {
  const canonical = normalizeHoldingTickerForMutation(ticker);
  const aliases = [canonical];

  const parts = parseUsTickerParts(canonical);
  if (!parts) {
    return aliases;
  }

  const classMatch = parts.base.match(US_CLASS_DOT_SYMBOL_PATTERN);
  if (classMatch) {
    const slash = `${classMatch[1]}/${classMatch[2]}.${parts.suffix}`;
    aliases.push(slash);
  }

  return aliases;
}
