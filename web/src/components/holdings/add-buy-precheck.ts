import type { HoldingRecord } from "@/lib/types";
import { KR_TICKER_PATTERN, US_TICKER_PATTERN } from "@/lib/holding-ticker";

export function inferRequiredCurrency(ticker: string): string {
  return /^\d{6}$/.test(ticker) ? "KRW" : "USD";
}

export function getAddBuyPrecheckError(
  target: HoldingRecord | null,
): string | null {
  if (!target) {
    return null;
  }

  const normalizedTicker = target.ticker.trim().toUpperCase();
  const tickerSupported =
    KR_TICKER_PATTERN.test(normalizedTicker) ||
    US_TICKER_PATTERN.test(normalizedTicker);
  if (!tickerSupported) {
    return "현재 holding ticker 형식이 Add Buy 지원 형식이 아닙니다. 티커를 NAS/NYS/AMS 접미사 형식으로 수정한 뒤 Add Buy를 진행하세요.";
  }

  if (target.quantity > 0 && target.entry_price <= 0) {
    return "현재 holding 데이터가 유효하지 않습니다. quantity>0 인 경우 entry_price를 0보다 크게 수정한 뒤 Add Buy를 진행하세요.";
  }

  const requiredCurrency = inferRequiredCurrency(target.ticker);
  const existingCurrency = target.entry_currency?.trim().toUpperCase() ?? null;
  if (existingCurrency && existingCurrency !== requiredCurrency) {
    return `현재 holding 데이터가 유효하지 않습니다. entry_currency는 ${requiredCurrency}여야 합니다(현재: ${existingCurrency}).`;
  }

  return null;
}
