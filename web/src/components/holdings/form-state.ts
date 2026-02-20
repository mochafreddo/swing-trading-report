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

export const EMPTY_FORM: HoldingFormState = {
  ticker: "",
  quantity: "",
  entry_price: "",
  entry_currency: "",
  entry_date: "",
  strategy: "",
  notes: "",
  tags: "",
  stop_override: "",
  target_override: "",
};
