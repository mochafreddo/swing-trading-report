alter table public.holdings
  add column if not exists entry_pattern text null;

do $$
declare
  invalid_tickers text;
begin
  select string_agg(ticker, ', ' order by ticker)
  into invalid_tickers
  from public.holdings
  where entry_pattern is not null
    and (
      char_length(entry_pattern) > 120
      or entry_pattern not in (
        'trend_pullback_bounce',
        'swing_high_breakout',
        'rsi_oversold_reversal'
      )
      or quantity = 0
    );

  if invalid_tickers is not null then
    raise exception using
      errcode = 'check_violation',
      message = 'Cannot add holdings entry_pattern constraints while invalid rows exist.',
      detail = format('Invalid holdings rows: %s', invalid_tickers),
      hint = 'Clear or fix entry_pattern on inactive, unknown, or overlong rows before rerunning.';
  end if;
end
$$;

alter table public.holdings
  drop constraint if exists holdings_entry_pattern_length_check;

alter table public.holdings
  add constraint holdings_entry_pattern_length_check
  check (entry_pattern is null or char_length(entry_pattern) <= 120);

alter table public.holdings
  drop constraint if exists holdings_entry_pattern_value_check;

alter table public.holdings
  add constraint holdings_entry_pattern_value_check
  check (
    entry_pattern is null
    or entry_pattern in (
      'trend_pullback_bounce',
      'swing_high_breakout',
      'rsi_oversold_reversal'
    )
  );

alter table public.holdings
  drop constraint if exists holdings_entry_pattern_active_quantity_check;

alter table public.holdings
  add constraint holdings_entry_pattern_active_quantity_check
  check (entry_pattern is null or quantity > 0);

-- Phase A is schema/RPC preparation only. Keep non-null writes closed until
-- runtime export/backup paths select and own entry_pattern. The runtime
-- enablement migration drops this constraint after deployed-secret PostgREST
-- smoke proves exports and writes preserve the field.
alter table public.holdings
  drop constraint if exists holdings_entry_pattern_write_closed_check;

alter table public.holdings
  add constraint holdings_entry_pattern_write_closed_check
  check (entry_pattern is null);

-- Do not backfill processed Add Buy replay payloads. The existing
-- jsonb_populate_record(null::public.holdings, result_payload) replay
-- path exposes missing nullable entry_pattern values as null without
-- mutating historical event payloads or updated_at timestamps.

create or replace function public.replace_holdings_v1(
  p_holdings jsonb default '[]'::jsonb
)
returns table(
  inserted_count integer,
  updated_count integer,
  deleted_count integer,
  unchanged_count integer
)
language plpgsql
as $$
declare
  v_inserted_count integer := 0;
  v_updated_count integer := 0;
  v_deleted_count integer := 0;
  v_unchanged_count integer := 0;
  v_duplicate_tickers text;
begin
  if p_holdings is null then
    p_holdings := '[]'::jsonb;
  end if;

  if jsonb_typeof(p_holdings) <> 'array' then
    raise exception 'p_holdings must be a JSON array';
  end if;

  lock table public.holdings in share row exclusive mode;

  if exists (
    select 1
    from jsonb_array_elements(p_holdings) as incoming(item)
    where incoming.item ? 'entry_pattern'
      and incoming.item->'entry_pattern' <> 'null'::jsonb
      and jsonb_typeof(incoming.item->'entry_pattern') <> 'string'
  ) then
    raise exception 'incoming holdings entry_pattern must be a string';
  end if;

  if exists (
    select 1
    from jsonb_array_elements(p_holdings) as incoming(item)
    where incoming.item ? 'entry_pattern'
      and incoming.item->'entry_pattern' <> 'null'::jsonb
      and jsonb_typeof(incoming.item->'entry_pattern') = 'string'
      and char_length(nullif(trim(incoming.item->>'entry_pattern'), '')) > 120
  ) then
    raise exception 'incoming holdings entry_pattern must be <= 120 chars';
  end if;

  if exists (
    select 1
    from jsonb_array_elements(p_holdings) as incoming(item)
    where incoming.item ? 'entry_pattern'
      and incoming.item->'entry_pattern' <> 'null'::jsonb
      and jsonb_typeof(incoming.item->'entry_pattern') = 'string'
      and nullif(trim(incoming.item->>'entry_pattern'), '') is not null
      and nullif(trim(incoming.item->>'entry_pattern'), '') not in (
        'trend_pullback_bounce',
        'swing_high_breakout',
        'rsi_oversold_reversal'
      )
  ) then
    raise exception 'incoming holdings entry_pattern must be one of trend_pullback_bounce, swing_high_breakout, rsi_oversold_reversal';
  end if;

  if exists (
    select 1
    from jsonb_array_elements(p_holdings) as incoming(item)
    where incoming.item ? 'entry_pattern'
      and incoming.item->'entry_pattern' <> 'null'::jsonb
      and jsonb_typeof(incoming.item->'entry_pattern') = 'string'
      and nullif(trim(incoming.item->>'entry_pattern'), '') is not null
  ) then
    raise exception 'incoming holdings entry_pattern writes are disabled until runtime export paths own entry_pattern';
  end if;

  drop table if exists pg_temp.incoming_holdings;

  create temporary table incoming_holdings (
    ticker text not null,
    quantity numeric(20, 6) not null,
    entry_price numeric(20, 4) not null,
    entry_currency text null,
    entry_date date null,
    strategy text null,
    has_entry_pattern boolean not null,
    entry_pattern text null,
    notes text null,
    tags text[] not null default '{}'::text[],
    stop_override numeric(20, 4) null,
    target_override numeric(20, 4) null
  ) on commit drop;

  insert into incoming_holdings (
    ticker,
    quantity,
    entry_price,
    entry_currency,
    entry_date,
    strategy,
    has_entry_pattern,
    entry_pattern,
    notes,
    tags,
    stop_override,
    target_override
  )
  select
    trim(coalesce(item.ticker, '')),
    round(item.quantity::numeric, 6),
    round(item.entry_price::numeric, 4),
    nullif(upper(trim(coalesce(item.entry_currency, ''))), ''),
    item.entry_date,
    nullif(trim(coalesce(item.strategy, '')), ''),
    incoming.item ? 'entry_pattern',
    nullif(trim(coalesce(item.entry_pattern, '')), ''),
    nullif(trim(coalesce(item.notes, '')), ''),
    coalesce(item.tags, '{}'::text[]),
    case
      when item.stop_override is null then null
      else round(item.stop_override::numeric, 4)
    end,
    case
      when item.target_override is null then null
      else round(item.target_override::numeric, 4)
    end
  from jsonb_array_elements(p_holdings) as incoming(item)
  cross join lateral jsonb_to_record(incoming.item) as item(
    ticker text,
    quantity numeric,
    entry_price numeric,
    entry_currency text,
    entry_date date,
    strategy text,
    entry_pattern text,
    notes text,
    tags text[],
    stop_override numeric,
    target_override numeric
  );

  if exists (
    select 1
    from incoming_holdings
    where quantity = 0
      and has_entry_pattern
      and entry_pattern is not null
  ) then
    raise exception 'inactive holdings entry_pattern must be null';
  end if;

  if exists (
    select 1
    from incoming_holdings incoming
    join public.holdings existing
      on existing.ticker = incoming.ticker
    where incoming.quantity > 0
      and existing.quantity > 0
      and existing.entry_pattern is not null
      and not incoming.has_entry_pattern
      and (
        existing.entry_price is distinct from incoming.entry_price
        or existing.entry_date is distinct from incoming.entry_date
        or existing.strategy is distinct from incoming.strategy
      )
  ) then
    raise exception 'incoming holdings entry_pattern must be explicit when entry identity or strategy changes';
  end if;

  if exists (
    select 1
    from incoming_holdings
    where ticker = ''
  ) then
    raise exception 'incoming holdings rows must include a non-empty ticker';
  end if;

  select string_agg(canonical_ticker, ', ' order by canonical_ticker)
  into v_duplicate_tickers
  from (
    select public.canonical_holdings_ticker(ticker) as canonical_ticker
    from incoming_holdings
    group by public.canonical_holdings_ticker(ticker)
    having count(*) > 1
  ) duplicates;

  if v_duplicate_tickers is not null then
    raise exception using
      errcode = '23505',
      message = 'incoming holdings contain duplicate tickers',
      detail = format('Duplicate canonical tickers: %s', v_duplicate_tickers);
  end if;

  select count(*)
  into v_unchanged_count
  from public.holdings existing
  join incoming_holdings incoming
    on incoming.ticker = existing.ticker
  where existing.quantity is not distinct from incoming.quantity
    and existing.entry_price is not distinct from incoming.entry_price
    and existing.entry_currency is not distinct from incoming.entry_currency
    and existing.entry_date is not distinct from incoming.entry_date
    and existing.strategy is not distinct from incoming.strategy
    and existing.entry_pattern is not distinct from (
      case
        when incoming.quantity = 0 then null
        when incoming.has_entry_pattern then incoming.entry_pattern
        else existing.entry_pattern
      end
    )
    and existing.notes is not distinct from incoming.notes
    and existing.tags is not distinct from incoming.tags
    and existing.stop_override is not distinct from incoming.stop_override
    and existing.target_override is not distinct from incoming.target_override;

  with updated_rows as (
    update public.holdings existing
    set
      quantity = incoming.quantity,
      entry_price = incoming.entry_price,
      entry_currency = incoming.entry_currency,
      entry_date = incoming.entry_date,
      strategy = incoming.strategy,
      entry_pattern = case
        when incoming.quantity = 0 then null
        when incoming.has_entry_pattern then incoming.entry_pattern
        else existing.entry_pattern
      end,
      notes = incoming.notes,
      tags = incoming.tags,
      stop_override = incoming.stop_override,
      target_override = incoming.target_override
    from incoming_holdings incoming
    where incoming.ticker = existing.ticker
      and (
        existing.quantity is distinct from incoming.quantity
        or existing.entry_price is distinct from incoming.entry_price
        or existing.entry_currency is distinct from incoming.entry_currency
        or existing.entry_date is distinct from incoming.entry_date
        or existing.strategy is distinct from incoming.strategy
        or existing.entry_pattern is distinct from (
          case
            when incoming.quantity = 0 then null
            when incoming.has_entry_pattern then incoming.entry_pattern
            else existing.entry_pattern
          end
        )
        or existing.notes is distinct from incoming.notes
        or existing.tags is distinct from incoming.tags
        or existing.stop_override is distinct from incoming.stop_override
        or existing.target_override is distinct from incoming.target_override
      )
    returning 1
  )
  select count(*) into v_updated_count from updated_rows;

  with inserted_rows as (
    insert into public.holdings (
      ticker,
      quantity,
      entry_price,
      entry_currency,
      entry_date,
      strategy,
      entry_pattern,
      notes,
      tags,
      stop_override,
      target_override
    )
    select
      incoming.ticker,
      incoming.quantity,
      incoming.entry_price,
      incoming.entry_currency,
      incoming.entry_date,
      incoming.strategy,
      case
        when incoming.quantity = 0 then null
        else incoming.entry_pattern
      end,
      incoming.notes,
      incoming.tags,
      incoming.stop_override,
      incoming.target_override
    from incoming_holdings incoming
    left join public.holdings existing
      on existing.ticker = incoming.ticker
    where existing.ticker is null
    returning 1
  )
  select count(*) into v_inserted_count from inserted_rows;

  with deleted_rows as (
    delete from public.holdings existing
    where not exists (
      select 1
      from incoming_holdings incoming
      where incoming.ticker = existing.ticker
    )
    returning 1
  )
  select count(*) into v_deleted_count from deleted_rows;

  inserted_count := v_inserted_count;
  updated_count := v_updated_count;
  deleted_count := v_deleted_count;
  unchanged_count := v_unchanged_count;
  return next;
end;
$$;

-- Recreate public.holdings_add_buy_v1 with the same signature,
-- idempotency fingerprint, and replay branch as the current Add Buy RPC.
-- The only behavior change is the non-replay update block: active holdings
-- preserve entry_pattern, while inactive-to-active reactivation clears it.
-- Do not add p_entry_pattern and do not include entry_pattern in the
-- idempotency request fingerprint.
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
    entry_date = v_new_entry_date,
    entry_pattern = case
      when coalesce(v_target.quantity, 0) = 0 then null
      else v_target.entry_pattern
    end
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
