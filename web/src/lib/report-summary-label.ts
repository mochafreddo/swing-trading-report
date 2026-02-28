const SOFT_BREAK = "\u200B";
const BREAKABLE_SEPARATORS = /([_.:/-])/g;

export function formatSummaryKeyForDisplay(key: string): string {
  const trimmed = key.trim();
  if (!trimmed) {
    return "-";
  }
  return trimmed.replace(BREAKABLE_SEPARATORS, `$1${SOFT_BREAK}`);
}
