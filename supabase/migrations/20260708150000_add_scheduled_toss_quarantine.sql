alter table public.holdings
  add column if not exists broker_state text not null default 'confirmed',
  add column if not exists broker_missing_first_seen_date date null,
  add column if not exists broker_missing_last_seen_date date null,
  add column if not exists broker_missing_count integer not null default 0,
  add column if not exists broker_missing_diff_hash text null;

do $$
begin
  alter table public.holdings
    add constraint holdings_broker_state_check
    check (broker_state in ('confirmed', 'not_seen_in_toss'));
exception
  when duplicate_object then null;
end;
$$;

do $$
begin
  alter table public.holdings
    add constraint holdings_broker_missing_evidence_check
    check (
      (
        broker_state = 'confirmed'
        and broker_missing_first_seen_date is null
        and broker_missing_last_seen_date is null
        and broker_missing_count = 0
        and broker_missing_diff_hash is null
      )
      or (
        broker_state = 'not_seen_in_toss'
        and broker_missing_first_seen_date is not null
        and broker_missing_last_seen_date is not null
        and broker_missing_last_seen_date >= broker_missing_first_seen_date
        and broker_missing_count > 0
        and broker_missing_diff_hash is not null
      )
    );
exception
  when duplicate_object then null;
end;
$$;

create or replace function public.apply_scheduled_toss_quarantine_v1(
  p_holdings jsonb default '[]'::jsonb,
  p_quarantine_tickers text[] default '{}'::text[],
  p_expected_holdings jsonb default null,
  p_session_date date default current_date,
  p_diff_hash text default null
)
returns table(
  inserted_count integer,
  updated_count integer,
  quarantined_count integer,
  unchanged_count integer
)
language plpgsql
as $$
declare
  v_inserted_count integer := 0;
  v_updated_count integer := 0;
  v_quarantined_count integer := 0;
  v_unchanged_count integer := 0;
  v_duplicate_tickers text;
  v_unaccounted_missing_tickers text;
  v_unknown_quarantine_tickers text;
begin
  if p_holdings is null then
    p_holdings := '[]'::jsonb;
  end if;

  if p_quarantine_tickers is null then
    p_quarantine_tickers := '{}'::text[];
  end if;

  if jsonb_typeof(p_holdings) <> 'array' then
    raise exception 'p_holdings must be a JSON array';
  end if;

  if p_expected_holdings is null or jsonb_typeof(p_expected_holdings) <> 'array' then
    raise exception 'p_expected_holdings must be a JSON array';
  end if;

  if p_session_date is null then
    raise exception 'p_session_date must be set';
  end if;

  if nullif(trim(coalesce(p_diff_hash, '')), '') is null then
    raise exception 'p_diff_hash must be set';
  end if;

  lock table public.holdings in share row exclusive mode;

  drop table if exists pg_temp.expected_holdings;

  create temporary table expected_holdings (
    ticker text not null,
    quantity numeric(20, 6) not null,
    entry_price numeric(20, 4) not null,
    entry_currency text null,
    entry_date date null,
    strategy text null,
    entry_pattern text null,
    notes text null,
    tags text[] not null default '{}'::text[],
    stop_override numeric(20, 4) null,
    target_override numeric(20, 4) null,
    broker_state text not null,
    broker_missing_first_seen_date date null,
    broker_missing_last_seen_date date null,
    broker_missing_count integer not null,
    broker_missing_diff_hash text null
  ) on commit drop;

  insert into expected_holdings (
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
    target_override,
    broker_state,
    broker_missing_first_seen_date,
    broker_missing_last_seen_date,
    broker_missing_count,
    broker_missing_diff_hash
  )
  select
    trim(coalesce(item.ticker, '')),
    round(item.quantity::numeric, 6),
    round(item.entry_price::numeric, 4),
    nullif(upper(trim(coalesce(item.entry_currency, ''))), ''),
    item.entry_date,
    nullif(trim(coalesce(item.strategy, '')), ''),
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
    end,
    coalesce(nullif(trim(item.broker_state), ''), 'confirmed'),
    item.broker_missing_first_seen_date,
    item.broker_missing_last_seen_date,
    coalesce(item.broker_missing_count, 0),
    nullif(trim(coalesce(item.broker_missing_diff_hash, '')), '')
  from jsonb_to_recordset(p_expected_holdings) as item(
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
    target_override numeric,
    broker_state text,
    broker_missing_first_seen_date date,
    broker_missing_last_seen_date date,
    broker_missing_count integer,
    broker_missing_diff_hash text
  );

  if exists (
    select 1
    from expected_holdings
    where ticker = ''
  ) then
    raise exception 'expected holdings rows must include a non-empty ticker';
  end if;

  if exists (
    select 1
    from (
      (
        select
          existing.ticker,
          round(existing.quantity::numeric, 6) as quantity,
          round(existing.entry_price::numeric, 4) as entry_price,
          existing.entry_currency,
          existing.entry_date,
          existing.strategy,
          existing.entry_pattern,
          existing.notes,
          existing.tags,
          case
            when existing.stop_override is null then null
            else round(existing.stop_override::numeric, 4)
          end as stop_override,
          case
            when existing.target_override is null then null
            else round(existing.target_override::numeric, 4)
          end as target_override,
          existing.broker_state,
          existing.broker_missing_first_seen_date,
          existing.broker_missing_last_seen_date,
          existing.broker_missing_count,
          existing.broker_missing_diff_hash
        from public.holdings existing
        except
        select
          expected.ticker,
          expected.quantity,
          expected.entry_price,
          expected.entry_currency,
          expected.entry_date,
          expected.strategy,
          expected.entry_pattern,
          expected.notes,
          expected.tags,
          expected.stop_override,
          expected.target_override,
          expected.broker_state,
          expected.broker_missing_first_seen_date,
          expected.broker_missing_last_seen_date,
          expected.broker_missing_count,
          expected.broker_missing_diff_hash
        from expected_holdings expected
      )
      union all
      (
        select
          expected.ticker,
          expected.quantity,
          expected.entry_price,
          expected.entry_currency,
          expected.entry_date,
          expected.strategy,
          expected.entry_pattern,
          expected.notes,
          expected.tags,
          expected.stop_override,
          expected.target_override,
          expected.broker_state,
          expected.broker_missing_first_seen_date,
          expected.broker_missing_last_seen_date,
          expected.broker_missing_count,
          expected.broker_missing_diff_hash
        from expected_holdings expected
        except
        select
          existing.ticker,
          round(existing.quantity::numeric, 6) as quantity,
          round(existing.entry_price::numeric, 4) as entry_price,
          existing.entry_currency,
          existing.entry_date,
          existing.strategy,
          existing.entry_pattern,
          existing.notes,
          existing.tags,
          case
            when existing.stop_override is null then null
            else round(existing.stop_override::numeric, 4)
          end as stop_override,
          case
            when existing.target_override is null then null
            else round(existing.target_override::numeric, 4)
          end as target_override,
          existing.broker_state,
          existing.broker_missing_first_seen_date,
          existing.broker_missing_last_seen_date,
          existing.broker_missing_count,
          existing.broker_missing_diff_hash
        from public.holdings existing
      )
    ) as snapshot_diff
    limit 1
  ) then
    raise exception using
      errcode = '40001',
      message = 'holdings snapshot changed before scheduled Toss quarantine',
      detail = 'holdings_snapshot_conflict',
      hint = 'Refetch holdings and Toss rows before retrying.';
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

  drop table if exists pg_temp.quarantine_tickers;

  create temporary table quarantine_tickers (
    ticker text primary key
  ) on commit drop;

  insert into quarantine_tickers (ticker)
  select trim(raw.ticker)
  from unnest(p_quarantine_tickers) as raw(ticker)
  where trim(raw.ticker) <> ''
  on conflict (ticker) do nothing;

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

  select string_agg(existing.ticker, ', ' order by existing.ticker)
  into v_unaccounted_missing_tickers
  from public.holdings existing
  where not exists (
    select 1
    from incoming_holdings incoming
    where incoming.ticker = existing.ticker
  )
    and not exists (
      select 1
      from quarantine_tickers quarantine
      where quarantine.ticker = existing.ticker
    );

  if v_unaccounted_missing_tickers is not null then
    raise exception using
      errcode = '40001',
      message = 'scheduled Toss quarantine omitted missing holdings',
      detail = format('Unaccounted missing tickers: %s', v_unaccounted_missing_tickers);
  end if;

  select string_agg(quarantine.ticker, ', ' order by quarantine.ticker)
  into v_unknown_quarantine_tickers
  from quarantine_tickers quarantine
  where not exists (
    select 1
    from public.holdings existing
    where existing.ticker = quarantine.ticker
  )
    or exists (
      select 1
      from incoming_holdings incoming
      where incoming.ticker = quarantine.ticker
    );

  if v_unknown_quarantine_tickers is not null then
    raise exception using
      errcode = '22023',
      message = 'scheduled Toss quarantine tickers must be existing rows absent from Toss',
      detail = format('Invalid quarantine tickers: %s', v_unknown_quarantine_tickers);
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
    and existing.target_override is not distinct from incoming.target_override
    and existing.broker_state = 'confirmed'
    and existing.broker_missing_first_seen_date is null
    and existing.broker_missing_last_seen_date is null
    and existing.broker_missing_count = 0
    and existing.broker_missing_diff_hash is null;

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
      target_override = incoming.target_override,
      broker_state = 'confirmed',
      broker_missing_first_seen_date = null,
      broker_missing_last_seen_date = null,
      broker_missing_count = 0,
      broker_missing_diff_hash = null
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
        or existing.broker_state <> 'confirmed'
        or existing.broker_missing_first_seen_date is not null
        or existing.broker_missing_last_seen_date is not null
        or existing.broker_missing_count <> 0
        or existing.broker_missing_diff_hash is not null
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
      target_override,
      broker_state,
      broker_missing_count
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
      incoming.target_override,
      'confirmed',
      0
    from incoming_holdings incoming
    left join public.holdings existing
      on existing.ticker = incoming.ticker
    where existing.ticker is null
    returning 1
  )
  select count(*) into v_inserted_count from inserted_rows;

  select count(*) into v_quarantined_count from quarantine_tickers;

  update public.holdings existing
  set
    broker_state = 'not_seen_in_toss',
    broker_missing_first_seen_date = case
      when existing.broker_state = 'not_seen_in_toss'
        then coalesce(existing.broker_missing_first_seen_date, p_session_date)
      else p_session_date
    end,
    broker_missing_last_seen_date = p_session_date,
    broker_missing_count = case
      when existing.broker_state = 'not_seen_in_toss'
        and existing.broker_missing_last_seen_date = p_session_date
        then existing.broker_missing_count
      when existing.broker_state = 'not_seen_in_toss'
        then existing.broker_missing_count + 1
      else 1
    end,
    broker_missing_diff_hash = p_diff_hash
  from quarantine_tickers quarantine
  where quarantine.ticker = existing.ticker;

  inserted_count := v_inserted_count;
  updated_count := v_updated_count;
  quarantined_count := v_quarantined_count;
  unchanged_count := v_unchanged_count;
  return next;
end;
$$;

revoke all on function public.apply_scheduled_toss_quarantine_v1(jsonb, text[], jsonb, date, text) from anon;
revoke all on function public.apply_scheduled_toss_quarantine_v1(jsonb, text[], jsonb, date, text) from authenticated;
revoke all on function public.apply_scheduled_toss_quarantine_v1(jsonb, text[], jsonb, date, text) from public;
grant execute on function public.apply_scheduled_toss_quarantine_v1(jsonb, text[], jsonb, date, text) to service_role;

create or replace function public.replace_holdings_v1(
  p_holdings jsonb default '[]'::jsonb,
  p_expected_holdings jsonb default null
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
  v_apply record;
  v_deleted_count integer := 0;
  v_delete_tickers text[] := '{}'::text[];
  v_expected_holdings jsonb;
begin
  if p_holdings is null then
    p_holdings := '[]'::jsonb;
  end if;

  if jsonb_typeof(p_holdings) <> 'array' then
    raise exception 'p_holdings must be a JSON array';
  end if;

  if p_expected_holdings is not null and jsonb_typeof(p_expected_holdings) <> 'array' then
    raise exception 'p_expected_holdings must be a JSON array';
  end if;

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

  lock table public.holdings in share row exclusive mode;

  if p_expected_holdings is null then
    select coalesce(
      jsonb_agg(
        jsonb_build_object(
          'ticker', existing.ticker,
          'quantity', round(existing.quantity::numeric, 6),
          'entry_price', round(existing.entry_price::numeric, 4),
          'entry_currency', existing.entry_currency,
          'entry_date', existing.entry_date,
          'strategy', existing.strategy,
          'entry_pattern', existing.entry_pattern,
          'notes', existing.notes,
          'tags', existing.tags,
          'stop_override', case
            when existing.stop_override is null then null
            else round(existing.stop_override::numeric, 4)
          end,
          'target_override', case
            when existing.target_override is null then null
            else round(existing.target_override::numeric, 4)
          end,
          'broker_state', existing.broker_state,
          'broker_missing_first_seen_date', existing.broker_missing_first_seen_date,
          'broker_missing_last_seen_date', existing.broker_missing_last_seen_date,
          'broker_missing_count', existing.broker_missing_count,
          'broker_missing_diff_hash', existing.broker_missing_diff_hash
        )
        order by existing.ticker
      ),
      '[]'::jsonb
    )
    into v_expected_holdings
    from public.holdings existing;
  else
    v_expected_holdings := p_expected_holdings;
  end if;

  select coalesce(array_agg(existing.ticker order by existing.ticker), '{}'::text[])
  into v_delete_tickers
  from public.holdings existing
  where not exists (
    select 1
    from jsonb_array_elements(p_holdings) as incoming(item)
    cross join lateral jsonb_to_record(incoming.item) as item(ticker text)
    where trim(coalesce(item.ticker, '')) = existing.ticker
  );

  select *
  into v_apply
  from public.apply_scheduled_toss_quarantine_v1(
    p_holdings,
    v_delete_tickers,
    v_expected_holdings,
    current_date,
    'replace_holdings_v1'
  );

  with deleted_rows as (
    delete from public.holdings existing
    where existing.ticker = any(v_delete_tickers)
    returning 1
  )
  select count(*) into v_deleted_count from deleted_rows;

  inserted_count := coalesce(v_apply.inserted_count, 0);
  updated_count := coalesce(v_apply.updated_count, 0);
  deleted_count := v_deleted_count;
  unchanged_count := coalesce(v_apply.unchanged_count, 0);
  return next;
end;
$$;

revoke all on function public.replace_holdings_v1(jsonb, jsonb) from anon;
revoke all on function public.replace_holdings_v1(jsonb, jsonb) from authenticated;
