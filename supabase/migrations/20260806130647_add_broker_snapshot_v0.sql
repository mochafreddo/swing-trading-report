create extension if not exists pgcrypto with schema extensions;

drop function if exists public.seal_broker_snapshot_v0(text, date, text, timestamptz, jsonb);
drop function if exists public.collect_broker_holdings_v0();

create schema if not exists broker_snapshot_private;
revoke all on schema broker_snapshot_private from public;
revoke all on schema broker_snapshot_private from anon;
revoke all on schema broker_snapshot_private from authenticated;
grant usage on schema broker_snapshot_private to service_role;

create table public.broker_snapshot_v0 (
  singleton boolean primary key default true check (singleton),
  state_key text not null,
  session_date date not null,
  status text not null check (status in ('applied', 'unchanged')),
  fresh_until timestamptz not null,
  marker_payload jsonb not null check (jsonb_typeof(marker_payload) = 'object'),
  holdings_digest text not null
    check (holdings_digest ~ '^sha256:[0-9a-f]{64}$'),
  revision bigint not null check (revision > 0),
  sealed_at timestamptz not null
);

alter table public.broker_snapshot_v0 enable row level security;
alter table public.broker_snapshot_v0 force row level security;

revoke all on table public.broker_snapshot_v0 from public;
revoke all on table public.broker_snapshot_v0 from anon;
revoke all on table public.broker_snapshot_v0 from authenticated;
grant select, insert, update on table public.broker_snapshot_v0 to service_role;

-- Canonical BrokerSnapshotV0 holdings projection.
--
-- Rows sort by canonical ticker. Numeric values use fixed decimal strings,
-- nullable/blank text is normalized to null, and tags sort by normalized text.
-- created_at/updated_at are intentionally excluded as volatile metadata.
-- The digest input is a UTF-8 length-prefixed stream. Each row begins with R;
-- scalar null is N, scalar text is S<byte-length>:<bytes>, and a tags array is
-- A<count>: followed by the same scalar encoding for each normalized tag.
create or replace function broker_snapshot_private.constant_time_text_equal_v0(
  p_left text,
  p_right text
)
returns boolean
language plpgsql
stable
security invoker
set search_path = ''
as $$
declare
  v_difference integer := 0;
begin
  if p_left is null or p_right is null
      or octet_length(p_left) <> octet_length(p_right) then
    return false;
  end if;
  for v_index in 1..octet_length(p_left)
  loop
    v_difference := v_difference | (
      get_byte(convert_to(p_left, 'UTF8'), v_index - 1)
      # get_byte(convert_to(p_right, 'UTF8'), v_index - 1)
    );
  end loop;
  return v_difference = 0;
end;
$$;

create or replace function broker_snapshot_private.collect_broker_holdings_v0()
returns table (
  holdings jsonb,
  holdings_digest text
)
language plpgsql
stable
security invoker
set search_path = ''
as $$
declare
  holding record;
  v_row jsonb;
  v_rows jsonb := '[]'::jsonb;
  v_bytes bytea := convert_to('broker-holdings-v0;', 'UTF8');
  v_value text;
  v_value_bytes bytea;
  v_values text[];
  v_tags text[];
  v_tag text;
begin
  for holding in
    select
      upper(trim(source.ticker)) as ticker,
      round(source.quantity, 6)::text as quantity,
      round(source.entry_price, 4)::text as entry_price,
      nullif(upper(trim(coalesce(source.entry_currency, ''))), '') as entry_currency,
      source.entry_date::text as entry_date,
      nullif(trim(coalesce(source.strategy, '')), '') as strategy,
      nullif(trim(coalesce(source.entry_pattern, '')), '') as entry_pattern,
      nullif(trim(coalesce(source.notes, '')), '') as notes,
      array(
        select trim(tag.value)
        from unnest(coalesce(source.tags, '{}'::text[])) as tag(value)
        where trim(tag.value) <> ''
        order by trim(tag.value) collate "C"
      ) as tags,
      case
        when source.stop_override is null then null
        else round(source.stop_override, 4)::text
      end as stop_override,
      case
        when source.target_override is null then null
        else round(source.target_override, 4)::text
      end as target_override,
      lower(trim(source.broker_state)) as broker_state,
      source.broker_missing_first_seen_date::text as broker_missing_first_seen_date,
      source.broker_missing_last_seen_date::text as broker_missing_last_seen_date,
      source.broker_missing_count,
      nullif(trim(coalesce(source.broker_missing_diff_hash, '')), '') as broker_missing_diff_hash
    from public.holdings as source
    order by upper(trim(source.ticker)) collate "C"
  loop
    v_tags := holding.tags;
    v_row := jsonb_build_object(
      'ticker', holding.ticker,
      'quantity', holding.quantity,
      'entry_price', holding.entry_price,
      'entry_currency', holding.entry_currency,
      'entry_date', holding.entry_date,
      'strategy', holding.strategy,
      'entry_pattern', holding.entry_pattern,
      'notes', holding.notes,
      'tags', to_jsonb(v_tags),
      'stop_override', holding.stop_override,
      'target_override', holding.target_override,
      'broker_state', holding.broker_state,
      'broker_missing_first_seen_date', holding.broker_missing_first_seen_date,
      'broker_missing_last_seen_date', holding.broker_missing_last_seen_date,
      'broker_missing_count', holding.broker_missing_count,
      'broker_missing_diff_hash', holding.broker_missing_diff_hash
    );
    v_rows := v_rows || jsonb_build_array(v_row);

    v_bytes := v_bytes || convert_to('R', 'UTF8');
    v_values := array[
      holding.ticker,
      holding.quantity,
      holding.entry_price,
      holding.entry_currency,
      holding.entry_date,
      holding.strategy,
      holding.entry_pattern,
      holding.notes
    ];
    foreach v_value in array v_values
    loop
      if v_value is null then
        v_bytes := v_bytes || convert_to('N', 'UTF8');
      else
        v_value_bytes := convert_to(v_value, 'UTF8');
        v_bytes := v_bytes
          || convert_to('S' || octet_length(v_value)::text || ':', 'UTF8')
          || v_value_bytes;
      end if;
    end loop;

    v_bytes := v_bytes
      || convert_to('A' || cardinality(v_tags)::text || ':', 'UTF8');
    foreach v_tag in array v_tags
    loop
      v_value_bytes := convert_to(v_tag, 'UTF8');
      v_bytes := v_bytes
        || convert_to('S' || octet_length(v_tag)::text || ':', 'UTF8')
        || v_value_bytes;
    end loop;

    v_values := array[
      holding.stop_override,
      holding.target_override,
      holding.broker_state,
      holding.broker_missing_first_seen_date,
      holding.broker_missing_last_seen_date,
      holding.broker_missing_count::text,
      holding.broker_missing_diff_hash
    ];
    foreach v_value in array v_values
    loop
      if v_value is null then
        v_bytes := v_bytes || convert_to('N', 'UTF8');
      else
        v_value_bytes := convert_to(v_value, 'UTF8');
        v_bytes := v_bytes
          || convert_to('S' || octet_length(v_value)::text || ':', 'UTF8')
          || v_value_bytes;
      end if;
    end loop;
  end loop;

  holdings := v_rows;
  holdings_digest := 'sha256:' || encode(extensions.digest(v_bytes, 'sha256'), 'hex');
  return next;
end;
$$;

create or replace function public.seal_broker_snapshot_v0(
  p_state_key text,
  p_session_date date,
  p_status text,
  p_expires_at timestamptz,
  p_marker_payload jsonb,
  p_expected_post_state_digest text
)
returns table (
  state_key text,
  session_date text,
  status text,
  fresh_until timestamptz,
  sealed_at timestamptz,
  holdings_digest text,
  revision bigint
)
language plpgsql
security invoker
set search_path = ''
as $$
declare
  v_collection record;
  v_snapshot public.broker_snapshot_v0%rowtype;
  v_marker jsonb;
  v_sealed_at timestamptz := clock_timestamp();
  v_existing_session_date date;
begin
  if p_status not in ('applied', 'unchanged') then
    raise exception 'BrokerSnapshotV0 requires a confirmed successful sync status';
  end if;
  if p_session_date is null
      or p_state_key <> 'toss-sync:success:MIXED:' || p_session_date::text then
    raise exception 'BrokerSnapshotV0 state key/session date mismatch';
  end if;
  if p_expires_at is null or p_expires_at <= v_sealed_at then
    raise exception 'BrokerSnapshotV0 fresh_until must be in the future';
  end if;
  if p_marker_payload is null or jsonb_typeof(p_marker_payload) <> 'object' then
    raise exception 'BrokerSnapshotV0 marker payload must be an object';
  end if;
  if p_expected_post_state_digest is null
      or p_expected_post_state_digest !~ '^sha256:[0-9a-f]{64}$' then
    raise exception 'BrokerSnapshotV0 expected post-state digest is invalid';
  end if;

  lock table public.holdings in share mode;
  lock table public.broker_snapshot_v0 in exclusive mode;

  -- Same-session retries are allowed and advance revision. Older sessions are
  -- rejected even if a replay supplies a new future TTL.
  select snapshot.session_date
  into v_existing_session_date
  from public.broker_snapshot_v0 as snapshot
  where snapshot.singleton;

  if found and p_session_date < v_existing_session_date then
    raise exception using
      errcode = '40001',
      message = 'BrokerSnapshotV0 session regression',
      detail = 'broker_snapshot_session_regression';
  end if;

  select *
  into strict v_collection
  from broker_snapshot_private.collect_broker_holdings_v0();

  if not broker_snapshot_private.constant_time_text_equal_v0(
    p_expected_post_state_digest,
    v_collection.holdings_digest
  ) then
    raise exception using
      errcode = '40001',
      message = 'BrokerSnapshotV0 post-state digest mismatch',
      detail = 'broker_snapshot_post_state_conflict';
  end if;

  insert into public.broker_snapshot_v0 (
    singleton,
    state_key,
    session_date,
    status,
    fresh_until,
    marker_payload,
    holdings_digest,
    revision,
    sealed_at
  ) values (
    true,
    p_state_key,
    p_session_date,
    p_status,
    p_expires_at,
    p_marker_payload,
    v_collection.holdings_digest,
    1,
    v_sealed_at
  )
  on conflict (singleton) do update
  set
    state_key = excluded.state_key,
    session_date = excluded.session_date,
    status = excluded.status,
    fresh_until = excluded.fresh_until,
    marker_payload = excluded.marker_payload,
    holdings_digest = excluded.holdings_digest,
    revision = public.broker_snapshot_v0.revision + 1,
    sealed_at = excluded.sealed_at
  returning * into v_snapshot;

  v_marker := p_marker_payload || jsonb_build_object(
    'scope', 'MIXED',
    'sessionDate', p_session_date::text,
    'status', p_status,
    'snapshotDigest', v_snapshot.holdings_digest,
    'snapshotRevision', v_snapshot.revision,
    'sealedAt', v_snapshot.sealed_at
  );

  update public.broker_snapshot_v0 as snapshot
  set marker_payload = v_marker
  where snapshot.singleton;

  insert into public.runtime_state (
    state_key,
    state_payload,
    expires_at
  ) values (
    p_state_key,
    v_marker,
    p_expires_at
  )
  on conflict on constraint runtime_state_pkey do update
  set
    state_payload = excluded.state_payload,
    expires_at = excluded.expires_at;

  state_key := v_snapshot.state_key;
  session_date := v_snapshot.session_date::text;
  status := v_snapshot.status;
  fresh_until := v_snapshot.fresh_until;
  sealed_at := v_snapshot.sealed_at;
  holdings_digest := v_snapshot.holdings_digest;
  revision := v_snapshot.revision;
  return next;
end;
$$;

create or replace function public.get_broker_snapshot_v0()
returns table (
  state_key text,
  session_date text,
  status text,
  fresh_until timestamptz,
  sealed_at timestamptz,
  holdings_digest text,
  revision bigint,
  marker jsonb,
  holdings jsonb
)
language plpgsql
stable
security invoker
set search_path = ''
as $$
declare
  v_snapshot public.broker_snapshot_v0%rowtype;
  v_collection record;
begin
  select snapshot.*
  into v_snapshot
  from public.broker_snapshot_v0 as snapshot
  where snapshot.singleton;

  if not found then
    return;
  end if;

  select *
  into strict v_collection
  from broker_snapshot_private.collect_broker_holdings_v0();

  state_key := v_snapshot.state_key;
  session_date := v_snapshot.session_date::text;
  status := v_snapshot.status;
  fresh_until := v_snapshot.fresh_until;
  sealed_at := v_snapshot.sealed_at;
  holdings_digest := v_snapshot.holdings_digest;
  revision := v_snapshot.revision;
  marker := v_snapshot.marker_payload;
  holdings := v_collection.holdings;
  return next;
end;
$$;

revoke all on function broker_snapshot_private.constant_time_text_equal_v0(text, text) from public;
revoke all on function broker_snapshot_private.constant_time_text_equal_v0(text, text) from anon;
revoke all on function broker_snapshot_private.constant_time_text_equal_v0(text, text) from authenticated;
grant execute on function broker_snapshot_private.constant_time_text_equal_v0(text, text) to service_role;

revoke all on function broker_snapshot_private.collect_broker_holdings_v0() from public;
revoke all on function broker_snapshot_private.collect_broker_holdings_v0() from anon;
revoke all on function broker_snapshot_private.collect_broker_holdings_v0() from authenticated;
grant execute on function broker_snapshot_private.collect_broker_holdings_v0() to service_role;

revoke all on function public.seal_broker_snapshot_v0(text, date, text, timestamptz, jsonb, text) from public;
revoke all on function public.seal_broker_snapshot_v0(text, date, text, timestamptz, jsonb, text) from anon;
revoke all on function public.seal_broker_snapshot_v0(text, date, text, timestamptz, jsonb, text) from authenticated;
grant execute on function public.seal_broker_snapshot_v0(text, date, text, timestamptz, jsonb, text) to service_role;

revoke all on function public.get_broker_snapshot_v0() from public;
revoke all on function public.get_broker_snapshot_v0() from anon;
revoke all on function public.get_broker_snapshot_v0() from authenticated;
grant execute on function public.get_broker_snapshot_v0() to service_role;
