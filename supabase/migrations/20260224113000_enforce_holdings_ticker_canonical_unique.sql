create or replace function public.canonical_holdings_ticker(raw_ticker text)
returns text
language plpgsql
immutable
as $$
declare
  normalized text;
  suffix text;
  base text;
  dot_count integer;
begin
  normalized := upper(trim(coalesce(raw_ticker, '')));

  if normalized ~ '^\d{6}$' then
    return normalized;
  end if;

  if normalized !~ '^[A-Z0-9][A-Z0-9._/-]{0,30}\.(US|NASDAQ|NASD|NAS|NYSE|NYS|AMEX|AMS)$' then
    return normalized;
  end if;

  suffix := regexp_replace(normalized, '^.*\.', '');
  base := left(normalized, length(normalized) - length(suffix) - 1);
  dot_count := length(base) - length(replace(base, '.', ''));

  if position('/' in base) = 0 and dot_count = 1 then
    return replace(base, '.', '/') || '.' || suffix;
  end if;

  return normalized;
end;
$$;

with ranked as (
  select
    ticker,
    public.canonical_holdings_ticker(ticker) as canonical_ticker,
    row_number() over (
      partition by public.canonical_holdings_ticker(ticker)
      order by
        (ticker = public.canonical_holdings_ticker(ticker)) desc,
        updated_at desc,
        created_at desc,
        ticker asc
    ) as rn
  from public.holdings
),
removed as (
  delete from public.holdings h
  using ranked r
  where h.ticker = r.ticker
    and r.rn > 1
  returning h.ticker
)
update public.holdings h
set ticker = r.canonical_ticker
from ranked r
where h.ticker = r.ticker
  and r.rn = 1
  and h.ticker <> r.canonical_ticker;

create unique index if not exists holdings_ticker_canonical_unique_idx
on public.holdings (public.canonical_holdings_ticker(ticker));
