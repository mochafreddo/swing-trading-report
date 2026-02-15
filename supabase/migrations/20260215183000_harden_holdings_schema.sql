alter table public.holdings
  alter column quantity type numeric(20, 6)
  using round(quantity::numeric, 6),
  alter column entry_price type numeric(20, 4)
  using round(entry_price::numeric, 4),
  alter column stop_override type numeric(20, 4)
  using round(stop_override::numeric, 4),
  alter column target_override type numeric(20, 4)
  using round(target_override::numeric, 4);

alter table public.holdings
  drop constraint if exists holdings_quantity_nonnegative_chk,
  drop constraint if exists holdings_entry_price_nonnegative_chk,
  drop constraint if exists holdings_stop_override_nonnegative_chk,
  drop constraint if exists holdings_target_override_nonnegative_chk,
  drop constraint if exists holdings_ticker_format_chk;

alter table public.holdings
  add constraint holdings_quantity_nonnegative_chk
  check (quantity >= 0),
  add constraint holdings_entry_price_nonnegative_chk
  check (entry_price >= 0),
  add constraint holdings_stop_override_nonnegative_chk
  check (stop_override is null or stop_override >= 0),
  add constraint holdings_target_override_nonnegative_chk
  check (target_override is null or target_override >= 0),
  add constraint holdings_ticker_format_chk
  check (
    ticker ~ '^\d{6}$'
    or ticker ~* '^[A-Z0-9][A-Z0-9._-]{0,30}\.(US|NASDAQ|NASD|NAS|NYSE|NYS|AMEX|AMS)$'
  );

drop index if exists public.holdings_updated_at_idx;

create index holdings_updated_at_ticker_idx
on public.holdings (updated_at desc, ticker asc);
