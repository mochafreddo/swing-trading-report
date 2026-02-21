create table if not exists public.runtime_state (
  state_key text primary key,
  state_payload jsonb not null,
  expires_at timestamptz not null,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);

create index if not exists runtime_state_expires_at_idx
on public.runtime_state (expires_at);

create index if not exists runtime_state_login_user_expires_at_idx
on public.runtime_state (expires_at)
where state_key like 'login_throttle:user:%';

create or replace function public.set_runtime_state_updated_at()
returns trigger
language plpgsql
as $$
begin
  new.updated_at := now();
  return new;
end;
$$;

drop trigger if exists runtime_state_set_updated_at on public.runtime_state;

create trigger runtime_state_set_updated_at
before update on public.runtime_state
for each row
execute function public.set_runtime_state_updated_at();

alter table public.runtime_state enable row level security;
alter table public.runtime_state force row level security;

revoke all on table public.runtime_state from anon;
revoke all on table public.runtime_state from authenticated;

create or replace function public.consume_login_throttle_attempt(
  p_state_key text,
  p_now timestamptz,
  p_window_seconds integer,
  p_block_seconds integer,
  p_max_attempts integer,
  p_user_key_cap integer default 512
)
returns table (
  failures integer,
  window_started_at bigint,
  blocked_until bigint,
  is_blocked boolean,
  retry_after_seconds integer
)
language plpgsql
as $$
declare
  v_now timestamptz := coalesce(p_now, now());
  v_now_ms bigint := floor(extract(epoch from v_now) * 1000)::bigint;
  v_window_ms bigint := greatest(1, p_window_seconds) * 1000;
  v_block_ms bigint := greatest(1, p_block_seconds) * 1000;
  v_max_attempts integer := greatest(1, p_max_attempts);
  v_row record;
  v_expires_ms bigint;
  v_retry_seconds integer;
  v_user_key_overflow integer;
begin
  perform pg_advisory_xact_lock(hashtextextended(p_state_key, 0));

  delete from public.runtime_state
  where ctid in (
    select ctid
    from public.runtime_state
    where state_key like 'login_throttle:user:%'
      and expires_at <= v_now
    order by expires_at asc
    limit 64
  );

  select
    state_payload,
    expires_at
  into v_row
  from public.runtime_state
  where state_key = p_state_key
  for update;

  if found then
    failures := case
      when (v_row.state_payload ->> 'failures') ~ '^[0-9]+$'
        then (v_row.state_payload ->> 'failures')::integer
      else 0
    end;
    window_started_at := case
      when (v_row.state_payload ->> 'windowStartedAt') ~ '^[0-9]+$'
        then (v_row.state_payload ->> 'windowStartedAt')::bigint
      else v_now_ms
    end;
    blocked_until := case
      when (v_row.state_payload ->> 'blockedUntil') ~ '^[0-9]+$'
        then (v_row.state_payload ->> 'blockedUntil')::bigint
      else 0
    end;
  else
    failures := 0;
    window_started_at := v_now_ms;
    blocked_until := 0;
  end if;

  if blocked_until > v_now_ms then
    v_retry_seconds := greatest(
      1,
      ceil((blocked_until - v_now_ms)::numeric / 1000)::integer
    );
    is_blocked := true;
    retry_after_seconds := v_retry_seconds;
    return next;
    return;
  end if;

  if v_now_ms - window_started_at > v_window_ms
      or (blocked_until > 0 and blocked_until <= v_now_ms) then
    failures := 0;
    window_started_at := v_now_ms;
    blocked_until := 0;
  end if;

  failures := failures + 1;
  if failures >= v_max_attempts then
    blocked_until := v_now_ms + v_block_ms;
  end if;

  v_expires_ms := greatest(
    window_started_at + v_window_ms,
    blocked_until,
    v_now_ms + 1000
  );

  insert into public.runtime_state (
    state_key,
    state_payload,
    expires_at
  ) values (
    p_state_key,
    jsonb_build_object(
      'failures', failures,
      'windowStartedAt', window_started_at,
      'blockedUntil', blocked_until
    ),
    to_timestamp(v_expires_ms / 1000.0)
  )
  on conflict (state_key) do update
  set
    state_payload = excluded.state_payload,
    expires_at = excluded.expires_at,
    updated_at = now();

  if p_state_key like 'login_throttle:user:%' and p_user_key_cap > 0 then
    select count(*) - p_user_key_cap
    into v_user_key_overflow
    from public.runtime_state
    where state_key like 'login_throttle:user:%'
      and expires_at > v_now;

    if v_user_key_overflow > 0 then
      delete from public.runtime_state
      where ctid in (
        select ctid
        from public.runtime_state
        where state_key like 'login_throttle:user:%'
          and expires_at > v_now
          and state_key <> p_state_key
        order by expires_at asc
        limit v_user_key_overflow
      );
    end if;
  end if;

  is_blocked := false;
  retry_after_seconds := 0;
  return next;
end;
$$;

revoke all on function public.consume_login_throttle_attempt(
  text,
  timestamptz,
  integer,
  integer,
  integer,
  integer
) from anon;

revoke all on function public.consume_login_throttle_attempt(
  text,
  timestamptz,
  integer,
  integer,
  integer,
  integer
) from authenticated;
