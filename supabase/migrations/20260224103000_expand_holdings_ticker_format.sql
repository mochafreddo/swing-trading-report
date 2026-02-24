alter table public.holdings
  drop constraint if exists holdings_ticker_format_chk;

alter table public.holdings
  add constraint holdings_ticker_format_chk
  check (
    ticker ~ '^\d{6}$'
    or ticker ~* '^[A-Z0-9][A-Z0-9._/-]{0,30}\.(US|NASDAQ|NASD|NAS|NYSE|NYS|AMEX|AMS)$'
  );
