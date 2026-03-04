create table if not exists public.holdings_add_buy_events (
  canonical_ticker text not null,
  idempotency_key text not null,
  request_fingerprint text not null,
  processed boolean not null default false,
  result_payload jsonb null,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  primary key (canonical_ticker, idempotency_key)
);

alter table public.holdings_add_buy_events
add column if not exists request_fingerprint text;

update public.holdings_add_buy_events
set request_fingerprint = coalesce(request_fingerprint, 'legacy')
where request_fingerprint is null;

alter table public.holdings_add_buy_events
alter column request_fingerprint set not null;

create index if not exists holdings_add_buy_events_processed_created_at_idx
on public.holdings_add_buy_events (processed, created_at);

create or replace function public.cleanup_holdings_add_buy_events(
  p_retention interval default interval '90 days',
  p_batch_size integer default 500
)
returns integer
language plpgsql
as $$
declare
  v_deleted integer := 0;
begin
  if p_batch_size is null or p_batch_size <= 0 then
    raise exception 'batch_size must be > 0';
  end if;

  with deleted_rows as (
    delete from public.holdings_add_buy_events
    where ctid in (
      select ctid
      from public.holdings_add_buy_events
      where processed = true
        and created_at < now() - p_retention
      order by created_at asc
      limit p_batch_size
    )
    returning 1
  )
  select count(*) into v_deleted from deleted_rows;

  return v_deleted;
end;
$$;

drop trigger if exists holdings_add_buy_events_set_updated_at
on public.holdings_add_buy_events;

create trigger holdings_add_buy_events_set_updated_at
before update on public.holdings_add_buy_events
for each row
execute function public.set_updated_at();

alter table public.holdings_add_buy_events enable row level security;
alter table public.holdings_add_buy_events force row level security;

revoke all on table public.holdings_add_buy_events from anon;
revoke all on table public.holdings_add_buy_events from authenticated;

drop function if exists public.holdings_add_buy_v1(
  text,
  numeric,
  numeric,
  date
);

create or replace function public.holdings_add_buy_v1(
  p_ticker text,
  p_buy_quantity numeric,
  p_buy_price numeric,
  p_buy_date date default null,
  p_idempotency_key text default null
)
returns setof public.holdings
language plpgsql
as $$
declare
  v_ticker_key text := trim(coalesce(p_ticker, ''));
  v_idempotency_key text := trim(coalesce(p_idempotency_key, ''));
  v_canonical_ticker text;
  v_request_fingerprint text;
  v_event public.holdings_add_buy_events%rowtype;
  v_target public.holdings%rowtype;
  v_updated public.holdings%rowtype;
  v_required_currency text;
  v_currency text;
  v_new_quantity numeric(20, 6);
  v_new_entry_price numeric(20, 4);
  v_new_entry_date date;
begin
  if v_ticker_key = '' then
    raise exception 'ticker is required';
  end if;

  if v_idempotency_key = '' then
    raise exception 'idempotency_key is required';
  end if;

  if char_length(v_idempotency_key) > 128 then
    raise exception 'idempotency_key must be <= 128 chars';
  end if;

  if v_idempotency_key !~* '^[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$' then
    raise exception 'idempotency_key must be a UUID';
  end if;

  if p_buy_quantity is null or p_buy_quantity <= 0 then
    raise exception 'buy_quantity must be > 0';
  end if;

  if p_buy_price is null or p_buy_price <= 0 then
    raise exception 'buy_price must be > 0';
  end if;

  v_canonical_ticker := public.canonical_holdings_ticker(v_ticker_key);
  v_request_fingerprint := md5(
    concat_ws(
      '|',
      v_canonical_ticker,
      round(p_buy_quantity, 6)::text,
      round(p_buy_price, 4)::text,
      coalesce(p_buy_date::text, '')
    )
  );

  insert into public.holdings_add_buy_events (
    canonical_ticker,
    idempotency_key,
    request_fingerprint
  ) values (
    v_canonical_ticker,
    v_idempotency_key,
    v_request_fingerprint
  )
  on conflict (canonical_ticker, idempotency_key) do nothing;

  select *
  into v_event
  from public.holdings_add_buy_events
  where canonical_ticker = v_canonical_ticker
    and idempotency_key = v_idempotency_key
  limit 1
  for update;

  if v_event.request_fingerprint is distinct from v_request_fingerprint then
    raise exception
      'idempotency_key payload mismatch for ticker %',
      v_canonical_ticker
    using
      errcode = '23505',
      detail = 'holdings_add_buy_idempotency_payload_mismatch';
  end if;

  if v_event.processed then
    if v_event.result_payload is null then
      return;
    end if;

    return query
    select *
    from jsonb_populate_record(null::public.holdings, v_event.result_payload);
    return;
  end if;

  select *
  into v_target
  from public.holdings
  where public.canonical_holdings_ticker(ticker) = v_canonical_ticker
  limit 1
  for update;

  if not found then
    update public.holdings_add_buy_events
    set
      processed = true,
      result_payload = null
    where canonical_ticker = v_canonical_ticker
      and idempotency_key = v_idempotency_key;
    return;
  end if;

  v_required_currency := case
    when v_target.ticker ~ '^\d{6}$' then 'KRW'
    else 'USD'
  end;

  v_currency := upper(trim(coalesce(v_target.entry_currency, '')));
  if v_currency = '' then
    v_currency := v_required_currency;
  elsif v_currency <> v_required_currency then
    raise exception
      'entry_currency mismatch for ticker %: expected %, got %',
      v_target.ticker,
      v_required_currency,
      v_currency;
  end if;

  if v_target.quantity > 0 and coalesce(v_target.entry_price, 0) <= 0 then
    raise exception
      'existing holding has non-positive entry_price for positive quantity (ticker %)',
      v_target.ticker;
  end if;

  v_new_quantity := round((coalesce(v_target.quantity, 0)::numeric + p_buy_quantity), 6);
  if v_new_quantity <= 0 then
    raise exception 'resulting quantity must be > 0';
  end if;

  if coalesce(v_target.quantity, 0) = 0 then
    v_new_entry_price := round(p_buy_price, 4);
  else
    v_new_entry_price := round(
      (
        (v_target.quantity::numeric * v_target.entry_price::numeric)
        + (p_buy_quantity * p_buy_price)
      ) / v_new_quantity,
      4
    );
  end if;

  v_new_entry_date := v_target.entry_date;
  if p_buy_date is not null and (v_new_entry_date is null or p_buy_date < v_new_entry_date) then
    v_new_entry_date := p_buy_date;
  end if;

  update public.holdings
  set
    quantity = v_new_quantity,
    entry_price = v_new_entry_price,
    entry_currency = v_currency,
    entry_date = v_new_entry_date
  where ticker = v_target.ticker
  returning *
  into v_updated;

  update public.holdings_add_buy_events
  set
    processed = true,
    result_payload = to_jsonb(v_updated)
  where canonical_ticker = v_canonical_ticker
    and idempotency_key = v_idempotency_key;

  return query
  select *
  from public.holdings
  where ticker = v_updated.ticker;
end;
$$;

revoke all on function public.holdings_add_buy_v1(
  text,
  numeric,
  numeric,
  date,
  text
) from anon;

revoke all on function public.holdings_add_buy_v1(
  text,
  numeric,
  numeric,
  date,
  text
) from authenticated;

revoke all on function public.cleanup_holdings_add_buy_events(
  interval,
  integer
) from anon;

revoke all on function public.cleanup_holdings_add_buy_events(
  interval,
  integer
) from authenticated;
