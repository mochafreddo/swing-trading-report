alter table public.holdings
  add constraint holdings_positive_quantity_requires_positive_entry_price_chk
  check (
    quantity = 0
    or entry_price > 0
  ) not valid;
