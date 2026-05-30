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
  v_now timestamptz := now();
  v_ttl_seconds integer := greatest(1, p_ttl_seconds);
  v_expires_at timestamptz := v_now + make_interval(secs => v_ttl_seconds);
  v_existing_expires_at timestamptz;
begin
  if btrim(coalesce(p_state_payload ->> 'ownerToken', '')) = '' then
    raise exception 'owner token must not be blank';
  end if;

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
    p_state_payload,
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
  if btrim(coalesce(p_owner_token, '')) = '' then
    raise exception 'owner token must not be blank';
  end if;

  perform pg_advisory_xact_lock(hashtextextended(p_state_key, 0));

  delete from public.runtime_state
  where state_key = p_state_key
    and btrim(coalesce(state_payload ->> 'ownerToken', '')) <> ''
    and state_payload ->> 'ownerToken' = p_owner_token;

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

create or replace function public.renew_runtime_state_lock(
  p_state_key text,
  p_owner_token text,
  p_ttl_seconds integer
)
returns boolean
language plpgsql
as $$
declare
  v_updated_count integer := 0;
  v_expires_at timestamptz := now() + make_interval(secs => greatest(1, p_ttl_seconds));
begin
  if btrim(coalesce(p_owner_token, '')) = '' then
    raise exception 'owner token must not be blank';
  end if;

  perform pg_advisory_xact_lock(hashtextextended(p_state_key, 0));

  update public.runtime_state
  set expires_at = v_expires_at
  where state_key = p_state_key
    and expires_at > now()
    and btrim(coalesce(state_payload ->> 'ownerToken', '')) <> ''
    and state_payload ->> 'ownerToken' = p_owner_token;

  get diagnostics v_updated_count = row_count;
  return v_updated_count > 0;
end;
$$;

revoke all on function public.renew_runtime_state_lock(
  text,
  text,
  integer
) from anon;

revoke all on function public.renew_runtime_state_lock(
  text,
  text,
  integer
) from authenticated;

create or replace function public.check_runtime_state_lock_owner(
  p_state_key text,
  p_owner_token text
)
returns boolean
language sql
stable
as $$
  select case
    when btrim(coalesce(p_owner_token, '')) = '' then false
    else exists (
      select 1
      from public.runtime_state
      where state_key = p_state_key
        and expires_at > now()
        and btrim(coalesce(state_payload ->> 'ownerToken', '')) <> ''
        and state_payload ->> 'ownerToken' = p_owner_token
    )
  end;
$$;

revoke all on function public.check_runtime_state_lock_owner(
  text,
  text
) from anon;

revoke all on function public.check_runtime_state_lock_owner(
  text,
  text
) from authenticated;
