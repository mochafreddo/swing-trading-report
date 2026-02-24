alter table public.holdings
  drop constraint if exists holdings_ticker_format_chk;

alter table public.holdings
  add constraint holdings_ticker_format_chk
  check (
    ticker ~ '^\d{6}$'
    or ticker ~* '^[A-Z0-9]+([._/-][A-Z0-9]+)*\.(US|NASDAQ|NASD|NAS|NYSE|NYS|AMEX|AMS)$'
  );

create or replace function public.canonical_holdings_ticker(raw_ticker text)
returns text
language plpgsql
immutable
as $$
declare
  normalized text;
  suffix text;
  base text;
begin
  normalized := upper(trim(coalesce(raw_ticker, '')));

  if normalized ~ '^\d{6}$' then
    return normalized;
  end if;

  if normalized !~ '^[A-Z0-9]+([._/-][A-Z0-9]+)*\.(US|NASDAQ|NASD|NAS|NYSE|NYS|AMEX|AMS)$' then
    return normalized;
  end if;

  suffix := regexp_replace(normalized, '^.*\.', '');
  base := left(normalized, length(normalized) - length(suffix) - 1);

  if base ~ '^[A-Z0-9]+\.[A-Z0-9]+$' then
    return replace(base, '.', '/') || '.' || suffix;
  end if;

  return normalized;
end;
$$;

reindex index public.holdings_ticker_canonical_unique_idx;
