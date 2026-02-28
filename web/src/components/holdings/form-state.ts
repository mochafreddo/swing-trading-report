export interface HoldingFormState {
  ticker: string;
  quantity: string;
  entry_price: string;
  entry_currency: string;
  entry_date: string;
  strategy: string;
  notes: string;
  tags: string;
  stop_override: string;
  target_override: string;
}

function formatTodayLocalDate(): string {
  const now = new Date();
  const local = new Date(now.getTime() - now.getTimezoneOffset() * 60_000);
  return local.toISOString().slice(0, 10);
}

export function createEmptyHoldingForm(): HoldingFormState {
  return {
    ticker: "",
    quantity: "",
    entry_price: "",
    entry_currency: "USD",
    entry_date: formatTodayLocalDate(),
    strategy: "swing",
    notes: "",
    tags: "",
    stop_override: "",
    target_override: "",
  };
}

export const EMPTY_FORM: HoldingFormState = createEmptyHoldingForm();
