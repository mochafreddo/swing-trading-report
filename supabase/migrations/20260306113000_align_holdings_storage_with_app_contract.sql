drop index if exists public.holdings_ticker_canonical_unique_idx;

create or replace function public.canonical_holdings_ticker(raw_ticker text)
returns text
language plpgsql
immutable
as $$
declare
  normalized text;
  suffix text;
  base text;
  canonical_suffix text;
  canonical_base text;
begin
  normalized := upper(trim(coalesce(raw_ticker, '')));

  if normalized ~ '^\d{6}$' then
    return normalized;
  end if;

  suffix := regexp_replace(normalized, '^.*\.', '');
  base := left(normalized, length(normalized) - length(suffix) - 1);

  canonical_suffix := case suffix
    when 'NASDAQ' then 'NAS'
    when 'NASD' then 'NAS'
    when 'NAS' then 'NAS'
    when 'NYSE' then 'NYS'
    when 'NYS' then 'NYS'
    when 'AMEX' then 'AMS'
    when 'AMS' then 'AMS'
    else null
  end;

  if canonical_suffix is null then
    return normalized;
  end if;

  canonical_base := case
    when base ~ '^[A-Z][A-Z0-9]*$' then base
    when base ~ '^[A-Z][A-Z0-9]*\.[ABC]$' then base
    when base ~ '^[A-Z][A-Z0-9]*/[ABC]$' then replace(base, '/', '.')
    else null
  end;

  if canonical_base is null then
    return normalized;
  end if;

  return canonical_base || '.' || canonical_suffix;
end;
$$;

do $$
declare
  invalid_tickers text;
begin
  select string_agg(ticker, ', ' order by ticker)
  into invalid_tickers
  from public.holdings
  where not (
    public.canonical_holdings_ticker(ticker) ~ '^\d{6}$'
    or public.canonical_holdings_ticker(ticker) ~ '^[A-Z][A-Z0-9]*(\.[ABC])?\.(NAS|NYS|AMS)$'
  );

  if invalid_tickers is not null then
    raise exception using
      errcode = 'check_violation',
      message = 'Cannot align holdings storage contract while unsupported tickers exist.',
      detail = format('Unsupported holdings rows: %s', invalid_tickers),
      hint = 'Rewrite each row to a canonical holdings ticker (KR 6-digit or US BASE[.CLASS].NAS/NYS/AMS) before rerunning.';
  end if;
end
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

alter table public.holdings
  drop constraint if exists holdings_ticker_format_chk;

alter table public.holdings
  add constraint holdings_ticker_format_chk
  check (
    ticker ~ '^\d{6}$'
    or ticker ~ '^[A-Z][A-Z0-9]*(\.[ABC])?\.(NAS|NYS|AMS)$'
  );

create unique index holdings_ticker_canonical_unique_idx
on public.holdings (public.canonical_holdings_ticker(ticker));
