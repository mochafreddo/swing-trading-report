\set ON_ERROR_STOP on

begin;

set local statement_timeout = '10s';

create or replace function pg_temp.assert_true(p_assertion text, p_ok boolean)
returns table(assertion text, ok boolean)
language plpgsql
as $$
begin
  if not p_ok then
    raise exception 'assertion failed: %', p_assertion;
  end if;

  return query select p_assertion, p_ok;
end;
$$;

select *
from pg_temp.assert_true(
  'entry_pattern column exists',
  exists (
    select 1
    from information_schema.columns
    where table_schema = 'public'
      and table_name = 'holdings'
      and column_name = 'entry_pattern'
  )
);

select *
from pg_temp.assert_true(
  'replace_holdings_v1 locks holdings table',
  position(
    'lock table public.holdings in share row exclusive mode'
    in lower(pg_get_functiondef('public.replace_holdings_v1(jsonb)'::regprocedure))
  ) > 0
);

select *
from pg_temp.assert_true(
  'add buy rpc remains quantity-only',
  position(
    'p_entry_pattern'
    in lower(
      pg_get_functiondef(
        'public.holdings_add_buy_v1(text,numeric,numeric,date,text)'::regprocedure
      )
    )
  ) = 0
);

select *
from pg_temp.assert_true(
  'reserved smoke holding is absent',
  not exists (
    select 1
    from public.holdings
    where public.canonical_holdings_ticker(ticker) = 'SABSMOKE.NAS'
  )
);

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
) values (
  'SABSMOKE.NAS',
  1,
  100,
  'USD',
  date '2026-06-09',
  'sma_ema_hybrid',
  null,
  'runtime smoke',
  array['smoke']::text[],
  null,
  null
);

create or replace function pg_temp.holdings_payload(
  p_smoke_entry_pattern jsonb default null,
  p_own_entry_pattern boolean default false,
  p_smoke_quantity numeric default null,
  p_smoke_notes text default null,
  p_smoke_entry_price numeric default null,
  p_smoke_entry_date date default null,
  p_smoke_strategy text default null
)
returns jsonb
language sql
as $$
  select jsonb_agg(
    case
      when ticker = 'SABSMOKE.NAS' and p_own_entry_pattern then
        base_row || jsonb_build_object('entry_pattern', p_smoke_entry_pattern)
      else
        base_row
    end
    order by ticker
  )
  from (
    select
      ticker,
      jsonb_build_object(
        'ticker', ticker,
        'quantity', coalesce(
          case when ticker = 'SABSMOKE.NAS' then p_smoke_quantity end,
          quantity
        ),
        'entry_price', coalesce(
          case when ticker = 'SABSMOKE.NAS' then p_smoke_entry_price end,
          entry_price
        ),
        'entry_currency', entry_currency,
        'entry_date', coalesce(
          case when ticker = 'SABSMOKE.NAS' then p_smoke_entry_date end,
          entry_date
        ),
        'strategy', coalesce(
          case when ticker = 'SABSMOKE.NAS' then p_smoke_strategy end,
          strategy
        ),
        'notes', coalesce(
          case when ticker = 'SABSMOKE.NAS' then p_smoke_notes end,
          notes
        ),
        'tags', tags,
        'stop_override', stop_override,
        'target_override', target_override
      ) as base_row
    from public.holdings
  ) rows;
$$;

select *
from public.replace_holdings_v1(
  pg_temp.holdings_payload(
    to_jsonb('swing_high_breakout'::text),
    true
  )
);

select *
from pg_temp.assert_true(
  'replace non-null marker stores entry_pattern',
  exists (
    select 1
    from public.holdings
    where ticker = 'SABSMOKE.NAS'
      and entry_pattern = 'swing_high_breakout'
  )
);

select *
from public.replace_holdings_v1(pg_temp.holdings_payload());

select *
from public.replace_holdings_v1(
  pg_temp.holdings_payload(
    null,
    false,
    null,
    'runtime smoke notes-only update'
  )
);

select *
from pg_temp.assert_true(
  'replace omit keeps active entry_pattern through update',
  exists (
    select 1
    from public.holdings
    where ticker = 'SABSMOKE.NAS'
      and notes = 'runtime smoke notes-only update'
      and entry_pattern = 'swing_high_breakout'
  )
);

select *
from public.replace_holdings_v1(
  pg_temp.holdings_payload('null'::jsonb, true)
);

select *
from pg_temp.assert_true(
  'replace explicit null clears entry_pattern',
  exists (
    select 1
    from public.holdings
    where ticker = 'SABSMOKE.NAS'
      and entry_pattern is null
  )
);

select *
from public.replace_holdings_v1(
  pg_temp.holdings_payload(
    null,
    false,
    0,
    'runtime smoke inactive omitted marker'
  )
);

select *
from pg_temp.assert_true(
  'replace inactive omitted marker stores null',
  exists (
    select 1
    from public.holdings
    where ticker = 'SABSMOKE.NAS'
      and quantity = 0
      and entry_pattern is null
  )
);

do $$
begin
  perform *
  from public.replace_holdings_v1(
    pg_temp.holdings_payload(to_jsonb('swing_high_breakout'::text), true)
  );

  raise exception 'expected inactive entry_pattern to fail';
exception
  when others then
    if sqlerrm not like '%inactive holdings entry_pattern must be null%' then
      raise;
    end if;
end;
$$;

do $$
begin
  perform *
  from public.replace_holdings_v1(
    pg_temp.holdings_payload(to_jsonb(repeat('x', 121)), true)
  );

  raise exception 'expected overlong entry_pattern to fail';
exception
  when others then
    if sqlerrm not like '%incoming holdings entry_pattern must be <= 120 chars%' then
      raise;
    end if;
end;
$$;

do $$
begin
  perform *
  from public.replace_holdings_v1(
    pg_temp.holdings_payload(to_jsonb('not_a_breakout'::text), true)
  );

  raise exception 'expected unknown entry_pattern to fail';
exception
  when others then
    if sqlerrm not like '%incoming holdings entry_pattern must be one of%' then
      raise;
    end if;
end;
$$;

update public.holdings
set
  quantity = 1,
  entry_price = 100,
  entry_currency = 'USD',
  entry_date = date '2026-06-09',
  entry_pattern = null,
  notes = 'runtime smoke add-buy active'
where ticker = 'SABSMOKE.NAS';

create temporary table smoke_add_buy_active as
select *
from public.holdings_add_buy_v1(
  'SABSMOKE.NAS',
  2,
  110,
  date '2026-06-10',
  '11111111-1111-4111-8111-111111111111'
);

select *
from pg_temp.assert_true(
  'add buy active null marker remains null',
  exists (
    select 1
    from smoke_add_buy_active
    where ticker = 'SABSMOKE.NAS'
      and quantity = 3
      and entry_pattern is null
  )
);

update public.holdings
set
  quantity = 0,
  entry_price = 0,
  entry_pattern = null,
  notes = 'runtime smoke add-buy inactive'
where ticker = 'SABSMOKE.NAS';

create temporary table smoke_add_buy_reactivate as
select *
from public.holdings_add_buy_v1(
  'SABSMOKE.NAS',
  1,
  120,
  date '2026-06-11',
  '22222222-2222-4222-8222-222222222222'
);

select *
from pg_temp.assert_true(
  'add buy inactive reactivation returns null marker',
  exists (
    select 1
    from smoke_add_buy_reactivate
    where ticker = 'SABSMOKE.NAS'
      and quantity = 1
      and entry_price = 120
      and entry_pattern is null
  )
);

create temporary table smoke_add_buy_replay as
select *
from public.holdings_add_buy_v1(
  'SABSMOKE.NAS',
  1,
  120,
  date '2026-06-11',
  '22222222-2222-4222-8222-222222222222'
);

select *
from pg_temp.assert_true(
  'add buy replay returns nullable entry_pattern shape',
  exists (
    select 1
    from smoke_add_buy_replay
    where ticker = 'SABSMOKE.NAS'
      and entry_pattern is null
  )
);

insert into public.holdings_add_buy_events (
  canonical_ticker,
  idempotency_key,
  request_fingerprint,
  processed,
  result_payload
) values (
  'SABLEGACY.NAS',
  '33333333-3333-4333-8333-333333333333',
  md5(
    concat_ws(
      '|',
      'SABLEGACY.NAS',
      round(1::numeric, 6)::text,
      round(10::numeric, 4)::text,
      date '2026-06-09'::text
    )
  ),
  true,
  jsonb_build_object(
    'ticker', 'SABLEGACY.NAS',
    'quantity', 1,
    'entry_price', 10,
    'entry_currency', 'USD',
    'entry_date', '2026-06-09',
    'strategy', null,
    'notes', null,
    'tags', array[]::text[],
    'stop_override', null,
    'target_override', null
  )
);

create temporary table smoke_legacy_event_before as
select result_payload, updated_at
from public.holdings_add_buy_events
where canonical_ticker = 'SABLEGACY.NAS'
  and idempotency_key = '33333333-3333-4333-8333-333333333333';

create temporary table smoke_legacy_replay as
select *
from public.holdings_add_buy_v1(
  'SABLEGACY.NAS',
  1,
  10,
  date '2026-06-09',
  '33333333-3333-4333-8333-333333333333'
);

select *
from pg_temp.assert_true(
  'legacy replay exposes missing entry_pattern as null',
  exists (
    select 1
    from smoke_legacy_replay
    where ticker = 'SABLEGACY.NAS'
      and entry_pattern is null
  )
);

select *
from pg_temp.assert_true(
  'legacy replay does not mutate cached event payload or timestamp',
  exists (
    select 1
    from public.holdings_add_buy_events event
    join smoke_legacy_event_before before_event
      on before_event.result_payload = event.result_payload
      and before_event.updated_at = event.updated_at
    where event.canonical_ticker = 'SABLEGACY.NAS'
      and event.idempotency_key = '33333333-3333-4333-8333-333333333333'
      and not (event.result_payload ? 'entry_pattern')
  )
);

rollback;
