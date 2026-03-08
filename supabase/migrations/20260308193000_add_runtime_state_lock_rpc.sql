create or replace function public.claim_runtime_state_lock(
  p_state_key text,
  p_now timestamptz,
  p_ttl_seconds integer,
  p_state_payload jsonb default '{}'::jsonb
)
returns table (
  acquired boolean,
  expires_at timestamptz
)
language plpgsql
as $$
declare
  v_now timestamptz := coalesce(p_now, now());
  v_ttl_seconds integer := greatest(1, p_ttl_seconds);
  v_expires_at timestamptz := v_now + make_interval(secs => v_ttl_seconds);
  v_existing_expires_at timestamptz;
begin
  perform pg_advisory_xact_lock(hashtextextended(p_state_key, 0));

  delete from public.runtime_state
  where state_key = p_state_key
    and expires_at <= v_now;

  select runtime_state.expires_at
  into v_existing_expires_at
  from public.runtime_state
  where state_key = p_state_key
  for update;

  if found then
    acquired := false;
    expires_at := v_existing_expires_at;
    return next;
    return;
  end if;

  insert into public.runtime_state (
    state_key,
    state_payload,
    expires_at
  ) values (
    p_state_key,
    coalesce(p_state_payload, '{}'::jsonb),
    v_expires_at
  );

  acquired := true;
  expires_at := v_expires_at;
  return next;
end;
$$;

revoke all on function public.claim_runtime_state_lock(
  text,
  timestamptz,
  integer,
  jsonb
) from anon;

revoke all on function public.claim_runtime_state_lock(
  text,
  timestamptz,
  integer,
  jsonb
) from authenticated;

create or replace function public.release_runtime_state_lock(
  p_state_key text,
  p_owner_token text
)
returns boolean
language plpgsql
as $$
declare
  v_deleted_count integer := 0;
begin
  perform pg_advisory_xact_lock(hashtextextended(p_state_key, 0));

  delete from public.runtime_state
  where state_key = p_state_key
    and coalesce(state_payload ->> 'ownerToken', '') = coalesce(p_owner_token, '');

  get diagnostics v_deleted_count = row_count;
  return v_deleted_count > 0;
end;
$$;

revoke all on function public.release_runtime_state_lock(
  text,
  text
) from anon;

revoke all on function public.release_runtime_state_lock(
  text,
  text
) from authenticated;
