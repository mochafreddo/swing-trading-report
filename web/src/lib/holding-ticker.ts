export const KR_TICKER_PATTERN = /^\d{6}$/;
export const US_TICKER_PATTERN =
  /^[A-Z0-9]+(?:[._/-][A-Z0-9]+)*\.(US|NASDAQ|NASD|NAS|NYSE|NYS|AMEX|AMS)$/;

const US_TICKER_SUFFIXES = new Set([
  "US",
  "NASDAQ",
  "NASD",
  "NAS",
  "NYSE",
  "NYS",
  "AMEX",
  "AMS",
]);

interface UsTickerParts {
  base: string;
  suffix: string;
}

function parseUsTickerParts(ticker: string): UsTickerParts | null {
  const normalized = ticker.trim().toUpperCase();
  const lastDotIndex = normalized.lastIndexOf(".");
  if (lastDotIndex <= 0) {
    return null;
  }
  const base = normalized.slice(0, lastDotIndex);
  const suffix = normalized.slice(lastDotIndex + 1);
  if (!base || !US_TICKER_SUFFIXES.has(suffix)) {
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

  const baseSegments = parts.base.split(".");
  if (
    parts.base.includes("/") ||
    baseSegments.length !== 2 ||
    baseSegments.some((segment) => !segment)
  ) {
    return normalized;
  }

  return `${baseSegments[0]}/${baseSegments[1]}.${parts.suffix}`;
}

export function buildHoldingTickerAliases(ticker: string): string[] {
  const canonical = normalizeHoldingTickerForMutation(ticker);
  const aliases = [canonical];

  const parts = parseUsTickerParts(canonical);
  if (!parts) {
    return aliases;
  }

  const baseSegments = parts.base.split("/");
  if (baseSegments.length === 2 && baseSegments.every(Boolean)) {
    const dotted = `${baseSegments[0]}.${baseSegments[1]}.${parts.suffix}`;
    if (dotted !== canonical) {
      aliases.push(dotted);
    }
  }

  return aliases;
}
