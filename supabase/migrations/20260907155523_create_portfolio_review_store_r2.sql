-- R2 review-only persistence. Apply only to a new disposable database until approved.
-- No role membership, login, runtime toggle, provider or notification is enabled here.
create role portfolio_mandate_review_compiler_r2 nologin nosuperuser nocreatedb
  nocreaterole noinherit noreplication nobypassrls;
grant usage on schema portfolio_mandate_private to portfolio_mandate_review_compiler_r2;

create table public.portfolio_mandate_review_packet_r2 (
  packet_id uuid primary key,
  owner_id uuid not null,
  packet text not null check (octet_length(packet) between 1 and 4194304),
  packet_sha256 text generated always as
    ('sha256:' || encode(extensions.digest(packet, 'sha256'), 'hex')) stored,
  check (packet::jsonb ->> 'schema_version' = 'portfolio-review-packet.r2'),
  check ((packet::jsonb ->> 'owner_id')::uuid = owner_id)
);

create table public.portfolio_mandate_review_run_r2 (
  run_id uuid primary key references public.portfolio_mandate_review_packet_r2(packet_id),
  sequence bigint generated always as identity unique,
  owner_id uuid not null,
  trigger_id uuid not null,
  revision integer not null check (revision > 0),
  version_ids uuid[] not null check (cardinality(version_ids) between 1 and 100),
  supersedes_run_id uuid unique references public.portfolio_mandate_review_run_r2(run_id),
  status text not null check (status in ('COMPILED','BLOCKED')),
  projection text not null check (octet_length(projection) between 1 and 262144),
  projection_sha256 text generated always as
    ('sha256:' || encode(extensions.digest(projection, 'sha256'), 'hex')) stored,
  recorded_at timestamptz not null default statement_timestamp(),
  unique(owner_id, trigger_id, revision),
  check (supersedes_run_id is distinct from run_id)
);
create index portfolio_mandate_review_run_r2_owner_idx
  on public.portfolio_mandate_review_run_r2(owner_id, sequence desc);

create table public.portfolio_mandate_review_decision_r2 (
  decision_id uuid primary key,
  run_id uuid not null references public.portfolio_mandate_review_run_r2(run_id),
  mandate_version_id uuid not null references public.portfolio_mandate_version_a1(mandate_version_id),
  review_row jsonb not null,
  unique(run_id, mandate_version_id),
  check (review_row -> 'action' is not distinct from 'null'::jsonb)
);

create table public.portfolio_mandate_review_journal_r2 (
  run_id uuid primary key references public.portfolio_mandate_review_run_r2(run_id),
  event text not null check (event in ('REVIEW_COMMITTED','REVIEW_BLOCKED')),
  recorded_at timestamptz not null default statement_timestamp()
);
create index portfolio_mandate_review_decision_r2_version_idx
  on public.portfolio_mandate_review_decision_r2(mandate_version_id);

create table public.portfolio_mandate_review_outcome_r2 (
  outcome_id uuid primary key,
  sequence bigint generated always as identity unique,
  run_id uuid not null references public.portfolio_mandate_review_run_r2(run_id),
  owner_id uuid not null,
  status text not null check (status in ('UNLINKED','AMBIGUOUS','NO_ACTION')),
  basis text not null check (basis in ('ORDER_AGGREGATE_ONLY','USER_CONFIRMED_NO_ACTION')),
  supersedes_outcome_id uuid unique references public.portfolio_mandate_review_outcome_r2(outcome_id),
  recorded_at timestamptz not null default statement_timestamp(),
  check ((status = 'NO_ACTION') = (basis = 'USER_CONFIRMED_NO_ACTION')),
  check (supersedes_outcome_id is distinct from outcome_id)
);
create index portfolio_mandate_review_outcome_r2_run_idx
  on public.portfolio_mandate_review_outcome_r2(run_id);

create table public.portfolio_mandate_review_outbox_r2 (
  decision_id uuid primary key references public.portfolio_mandate_review_decision_r2(decision_id),
  destination text not null check (destination = 'LOCAL_REVIEW_SINK'),
  -- Receipt is the local sink: no outbound adapter, address or private payload.
  received_at timestamptz
);

do $$
declare t text;
begin
  foreach t in array array['packet','run','decision','journal','outcome','outbox'] loop
    execute format('alter table public.portfolio_mandate_review_%s_r2 enable row level security', t);
    execute format('alter table public.portfolio_mandate_review_%s_r2 force row level security', t);
    execute format('revoke all on public.portfolio_mandate_review_%s_r2 from public, anon, authenticated, service_role, portfolio_mandate_candidate_submitter_a1, portfolio_mandate_review_compiler_r2', t);
    if t <> 'outbox' then
      execute format('create trigger review_%s_r2_append_only before update or delete on public.portfolio_mandate_review_%s_r2 for each row execute function public.reject_portfolio_mandate_event_mutation_a1()', t, t);
    end if;
  end loop;
end $$;

create function portfolio_mandate_private.commit_review_r2(
  p_run_id uuid, p_owner_id uuid, p_trigger_id uuid, p_revision integer,
  p_supersedes uuid, p_bundle jsonb
) returns jsonb language plpgsql security definer set search_path = '' as $$
declare
  v_packet jsonb; v_projection jsonb; v_ids uuid[]; v_old record; v_prev record;
  v_row jsonb; v_decision_id uuid; v_blocked boolean; v_input jsonb; v_previous_input jsonb;
  v_observation public.portfolio_mandate_review_observation_r1%rowtype;
begin
  -- TODO: owner-wide serialization caps parallel imports for one owner; use cohort
  -- locks if measured load requires independent cohorts to commit concurrently.
  perform pg_advisory_xact_lock(hashtextextended(p_owner_id::text, 2));
  v_packet := (p_bundle ->> 'packet')::jsonb;
  v_input := (v_packet #>> '{input,payload}')::jsonb;
  v_projection := (p_bundle ->> 'projection')::jsonb;
  if p_owner_id is null or p_run_id is null or p_trigger_id is null
    or p_revision is null or p_revision < 1
    or v_packet ->> 'schema_version' is distinct from 'portfolio-review-packet.r2'
    or v_packet ->> 'compiler_version' is distinct from 'review-r1/1'
    or v_input->>'schema_version' is distinct from 'portfolio-review-input.r1'
    or jsonb_typeof(v_packet->'sources') is distinct from 'array'
    or jsonb_typeof(v_packet->'approvals') is distinct from 'array'
    or v_input->>'read_at' is null
    or v_packet ->> 'owner_id' is distinct from p_owner_id::text
    or v_projection ->> 'schema_version' is distinct from 'portfolio-review.r1'
    or v_projection ->> 'mode' is distinct from 'LOCAL_ONLY'
    or v_projection -> 'advice_enabled' is distinct from 'false'::jsonb
    or v_projection->>'as_of' is distinct from v_input->>'read_at'
    or v_projection->>'review_period' is distinct from v_packet#>>'{parameters,review_period}'
    or (v_projection->>'as_of')::timestamptz > statement_timestamp()
    or (v_projection - array['schema_version','mode','advice_enabled','as_of','review_period','rows']) <> '{}'::jsonb
    or jsonb_typeof(v_projection -> 'rows') is distinct from 'array'
    or p_bundle ->> 'packet_sha256' is distinct from
      'sha256:' || encode(extensions.digest(p_bundle ->> 'packet','sha256'),'hex')
    or p_bundle ->> 'projection_sha256' is distinct from
      'sha256:' || encode(extensions.digest(p_bundle ->> 'projection','sha256'),'hex')
  then raise exception 'REVIEW_STORE_INVALID' using errcode = '22023'; end if;
  select array_agg((r ->> 'mandate_version_id')::uuid order by r ->> 'mandate_version_id')
    into v_ids from jsonb_array_elements(v_projection -> 'rows') r;
  if coalesce(cardinality(v_ids),0) not between 1 and 100
    or cardinality(v_ids) <> (select count(distinct x) from unnest(v_ids) x)
    or cardinality(v_ids) <> (select count(*) from public.portfolio_mandate_version_a1 v
      join public.portfolio_mandate_a1 m using(mandate_id)
      where v.mandate_version_id = any(v_ids) and m.owner_actor_id = p_owner_id)
  then raise exception 'REVIEW_STORE_OWNER_VERSION_MISMATCH' using errcode = '42501'; end if;
  if exists(select 1 from jsonb_array_elements(v_packet->'sources') source
    where source->>'tier' is distinct from 'PRIMARY'
      or source->>'content_sha256' is distinct from 'sha256:' || encode(extensions.digest(source->>'content','sha256'),'hex')
      or not exists(select 1 from public.portfolio_mandate_evidence_seal_a1 e
        where e.evidence_seal_id=(source->>'seal_id')::uuid
          and e.instrument_id=(source->>'instrument_id')::uuid
          and e.source_event_time=(source->>'source_event_time')::timestamptz
          and e.sealed_at=(source->>'sealed_at')::timestamptz)) then
    raise exception 'REVIEW_SOURCE_SEAL_MISMATCH' using errcode='22023';
  end if;
  for v_row in select * from jsonb_array_elements(v_projection -> 'rows') loop
    if v_row -> 'action' is distinct from 'null'::jsonb
      or v_row ->> 'status' is null
      or v_row ->> 'status' not in ('BLOCKED','REVIEW_REQUIRED','NO_TRIGGER_OBSERVED','THESIS_INVALIDATED_REVIEW_REQUIRED')
      or (v_row - array['mandate_version_id','instrument_id','status','action','issue_codes',
        'matched_hard_trigger_count','deterioration_confirmed','current_observation_count','superseded_observation_count']) <> '{}'::jsonb
      or jsonb_typeof(v_row->'issue_codes') is distinct from 'array'
      or exists(select 1 from jsonb_array_elements_text(v_row->'issue_codes') issue where issue not in (
        'ALLOCATION_REBASE_REQUIRED','ANNUAL_REVIEW_DUE','BROKER_STALE_OR_MISSING','CONDITION_MAPPING_REQUIRED',
        'EVIDENCE_STALE_OR_MISMATCHED','MANDATE_NOT_ACTIVE','MANDATE_OUTSIDE_EFFECTIVE_WINDOW','OBSERVATION_MISSING_OR_CONFLICTED',
        'PERIOD_MAPPING_REQUIRED','POLICY_MISSING','POLICY_NOT_VISIBLE','SLICE_INELIGIBLE','SPECIAL_RULE_REQUIRES_REVIEW','UNSTRUCTURED_RULE_REQUIRES_REVIEW'))
      or not exists (select 1 from public.portfolio_mandate_version_a1 v
        join public.portfolio_mandate_a1 m using(mandate_id)
        where v.mandate_version_id=(v_row->>'mandate_version_id')::uuid
          and m.instrument_id=(v_row->>'instrument_id')::uuid)
    then raise exception 'REVIEW_STORE_INVALID' using errcode='22023'; end if;
  end loop;
  select r.*, p.packet into v_old from public.portfolio_mandate_review_run_r2 r
    join public.portfolio_mandate_review_packet_r2 p on p.packet_id=r.run_id
    where r.owner_id=p_owner_id and r.trigger_id=p_trigger_id and r.revision=p_revision;
  if found then
    if v_old.run_id <> p_run_id or v_old.packet <> p_bundle->>'packet'
      or v_old.projection <> p_bundle->>'projection'
      or v_old.supersedes_run_id is distinct from p_supersedes
    then raise exception 'REVIEW_IDEMPOTENCY_CONFLICT' using errcode='23505'; end if;
    return jsonb_build_object('run_id',v_old.run_id,'status',v_old.status,'duplicate',true);
  end if;
  if exists(select 1 from public.portfolio_mandate_review_run_r2 r
      where r.owner_id=p_owner_id and r.version_ids && v_ids
        and (r.projection::jsonb->>'as_of')::timestamptz > (v_projection->>'as_of')::timestamptz) then
    raise exception 'REVIEW_STALE_SNAPSHOT' using errcode='22023';
  end if;
  if p_supersedes is not null then
    select * into v_prev from public.portfolio_mandate_review_run_r2 where run_id=p_supersedes;
    if not found or v_prev.owner_id<>p_owner_id or v_prev.version_ids<>v_ids
      or v_prev.trigger_id<>p_trigger_id or v_prev.revision+1<>p_revision
      or (v_prev.projection::jsonb->>'as_of')::timestamptz >= (v_projection->>'as_of')::timestamptz
    then raise exception 'REVIEW_CORRECTION_INVALID' using errcode='22023'; end if;
    select (packet::jsonb#>>'{input,payload}')::jsonb into v_previous_input
      from public.portfolio_mandate_review_packet_r2 where packet_id=p_supersedes;
    if exists(select 1 from jsonb_array_elements(v_previous_input->'rows') old_row
      where not exists(select 1 from jsonb_array_elements(v_input->'rows') new_row
        where new_row->>'mandate_version_id'=old_row->>'mandate_version_id'
          and new_row->>'holding_sha256'=old_row->>'holding_sha256'
          and new_row->>'source_document_sha256'=old_row->>'source_document_sha256'
          and (new_row->'observations') @> (old_row->'observations'))) then
      raise exception 'REVIEW_OBSERVATION_HISTORY_CHANGED' using errcode='22023';
    end if;
  elsif p_revision<>1 then
    raise exception 'REVIEW_CORRECTION_INVALID' using errcode='22023';
  end if;
  -- Import approved original policy and observations in this SAME transaction.
  -- Existing IDs must match in full; corrections append rather than overwrite.
  for v_row in select * from jsonb_array_elements(v_input->'rows') loop
    if not ((v_row->>'mandate_version_id')::uuid = any(v_ids))
      or not exists(select 1 from public.portfolio_mandate_version_a1 v
        where v.mandate_version_id=(v_row->>'mandate_version_id')::uuid
          and v.approval_state='APPROVED' and v.classification_state='ACTIVE' and v.horizon='LONG_TERM') then
      raise exception 'REVIEW_IMPORT_VERSION_MISMATCH' using errcode='22023';
    end if;
    insert into public.portfolio_mandate_review_policy_r1(mandate_version_id,source_document_sha256,holding_document,recorded_at)
      values((v_row->>'mandate_version_id')::uuid,v_row->>'source_document_sha256',v_row->>'holding_document',(v_row->>'policy_recorded_at')::timestamptz)
      on conflict(mandate_version_id) do nothing;
    if not exists(select 1 from public.portfolio_mandate_review_policy_r1 p
      where p.mandate_version_id=(v_row->>'mandate_version_id')::uuid
        and p.holding_document=v_row->>'holding_document'
        and p.holding_sha256=v_row->>'holding_sha256'
        and p.source_document_sha256=v_row->>'source_document_sha256'
        and p.recorded_at=(v_row->>'policy_recorded_at')::timestamptz) then
      raise exception 'REVIEW_IMPORT_POLICY_CONFLICT' using errcode='23505';
    end if;
    for v_observation in select (jsonb_populate_record(null::public.portfolio_mandate_review_observation_r1,
        o || jsonb_build_object('mandate_version_id',v_row->>'mandate_version_id'))).*
      from jsonb_array_elements(v_row->'observations') o order by (o->>'recorded_at')::timestamptz,o->>'observation_id'
    loop
      insert into public.portfolio_mandate_review_observation_r1 select v_observation.*
        on conflict(observation_id) do nothing;
      if not exists(select 1 from public.portfolio_mandate_review_observation_r1 o where o is not distinct from v_observation) then
        raise exception 'REVIEW_IMPORT_OBSERVATION_CONFLICT' using errcode='23505';
      end if;
    end loop;
  end loop;
  v_blocked := exists(select 1 from jsonb_array_elements(v_projection->'rows') r where r->>'status'='BLOCKED');
  insert into public.portfolio_mandate_review_packet_r2(packet_id,owner_id,packet)
    values(p_run_id,p_owner_id,p_bundle->>'packet');
  insert into public.portfolio_mandate_review_run_r2(run_id,owner_id,trigger_id,revision,version_ids,supersedes_run_id,status,projection)
    values(p_run_id,p_owner_id,p_trigger_id,p_revision,v_ids,p_supersedes,
      case when v_blocked then 'BLOCKED' else 'COMPILED' end,p_bundle->>'projection');
  if not v_blocked then
    for v_row in select * from jsonb_array_elements(v_projection->'rows') loop
      v_decision_id := extensions.gen_random_uuid();
      insert into public.portfolio_mandate_review_decision_r2 values(v_decision_id,p_run_id,(v_row->>'mandate_version_id')::uuid,v_row);
      insert into public.portfolio_mandate_review_outbox_r2 values(v_decision_id,'LOCAL_REVIEW_SINK',null);
    end loop;
  end if;
  insert into public.portfolio_mandate_review_journal_r2(run_id,event)
    values(p_run_id,case when v_blocked then 'REVIEW_BLOCKED' else 'REVIEW_COMMITTED' end);
  return jsonb_build_object('run_id',p_run_id,'status',case when v_blocked then 'BLOCKED' else 'COMPILED' end,'duplicate',false);
end $$;
revoke all on function portfolio_mandate_private.commit_review_r2(uuid,uuid,uuid,integer,uuid,jsonb) from public,anon,authenticated,service_role;
grant execute on function portfolio_mandate_private.commit_review_r2(uuid,uuid,uuid,integer,uuid,jsonb) to portfolio_mandate_review_compiler_r2;

create function portfolio_mandate_private.read_store_r2(p_version_ids uuid[])
returns jsonb language plpgsql stable security definer set search_path='' as $$
declare v_rows jsonb;
begin
  -- Reuse R1's role and complete exact-owner/version validation, with one snapshot.
  perform portfolio_mandate_private.read_review_r1(p_version_ids);
  select coalesce(jsonb_agg(jsonb_build_object(
    'mandate_version_id', requested.id, 'run_id', latest.run_id,
    'run_status', latest.status, 'review', latest.row,
    'as_of',latest.as_of, 'outcomes',coalesce((
      select jsonb_agg(jsonb_build_object('outcome_id',o.outcome_id,'status',o.status,'basis',o.basis,
        'supersedes_outcome_id',o.supersedes_outcome_id) order by o.sequence)
      from public.portfolio_mandate_review_outcome_r2 o where o.run_id=latest.run_id
    ),'[]'::jsonb)) order by requested.id),'[]'::jsonb) into v_rows
  from unnest(p_version_ids) requested(id)
  left join lateral (
    select r.run_id,r.status,row,r.projection::jsonb->>'as_of' as as_of
    from public.portfolio_mandate_review_run_r2 r,
      jsonb_array_elements(r.projection::jsonb->'rows') row
    where r.owner_id=auth.uid() and row->>'mandate_version_id'=requested.id::text
    order by r.sequence desc limit 1
  ) latest on true;
  return jsonb_build_object('schema_version','portfolio-review-store.r2','mode','LOCAL_ONLY',
    'advice_enabled',false,'rows',v_rows);
end $$;
revoke all on function portfolio_mandate_private.read_store_r2(uuid[]) from public,anon,authenticated,service_role;
grant execute on function portfolio_mandate_private.read_store_r2(uuid[]) to authenticated;
create function public.read_portfolio_review_store_r2(p_version_ids uuid[])
returns jsonb language sql stable security invoker set search_path='' as $$
  select portfolio_mandate_private.read_store_r2(p_version_ids);
$$;
revoke all on function public.read_portfolio_review_store_r2(uuid[]) from public,anon,authenticated,service_role;
grant execute on function public.read_portfolio_review_store_r2(uuid[]) to authenticated;

create function portfolio_mandate_private.record_outcome_r2(
  p_owner_id uuid,p_run_id uuid,p_outcome_id uuid,p_status text,p_basis text,p_supersedes uuid
) returns void language plpgsql security definer set search_path='' as $$
declare v_old record;
begin
  perform pg_advisory_xact_lock(hashtextextended(p_owner_id::text,2));
  if p_status='NO_ACTION' and (auth.uid() is distinct from p_owner_id
    or (nullif(current_setting('request.jwt.claims',true),'')::jsonb->>'role') is distinct from 'authenticated') then
    raise exception 'REVIEW_OUTCOME_CONFIRMATION_REQUIRED' using errcode='42501';
  end if;
  if not exists(select 1 from public.portfolio_mandate_review_run_r2 where run_id=p_run_id and owner_id=p_owner_id) then
    raise exception 'REVIEW_OUTCOME_OWNER_MISMATCH' using errcode='42501';
  end if;
  select * into v_old from public.portfolio_mandate_review_outcome_r2 where outcome_id=p_outcome_id;
  if found then
    if v_old.owner_id<>p_owner_id or v_old.run_id<>p_run_id or v_old.status is distinct from p_status
      or v_old.basis is distinct from p_basis or v_old.supersedes_outcome_id is distinct from p_supersedes then
      raise exception 'REVIEW_OUTCOME_CONFLICT' using errcode='23505';
    end if;
    return;
  end if;
  if p_supersedes is not null and not exists(select 1 from public.portfolio_mandate_review_outcome_r2
      where outcome_id=p_supersedes and owner_id=p_owner_id and run_id=p_run_id) then
    raise exception 'REVIEW_OUTCOME_CORRECTION_INVALID' using errcode='22023';
  end if;
  insert into public.portfolio_mandate_review_outcome_r2(outcome_id,run_id,owner_id,status,basis,supersedes_outcome_id)
    values(p_outcome_id,p_run_id,p_owner_id,p_status,p_basis,p_supersedes);
end $$;
revoke all on function portfolio_mandate_private.record_outcome_r2(uuid,uuid,uuid,text,text,uuid) from public,anon,authenticated,service_role;
grant execute on function portfolio_mandate_private.record_outcome_r2(uuid,uuid,uuid,text,text,uuid) to portfolio_mandate_review_compiler_r2;

create function portfolio_mandate_private.confirm_no_action_r2(p_run_id uuid,p_outcome_id uuid,p_supersedes uuid)
returns void language plpgsql security definer set search_path='' as $$
begin
  if auth.uid() is null or (nullif(current_setting('request.jwt.claims',true),'')::jsonb->>'role') is distinct from 'authenticated' then
    raise exception 'REVIEW_OUTCOME_CONFIRMATION_REQUIRED' using errcode='42501';
  end if;
  perform portfolio_mandate_private.record_outcome_r2(auth.uid(),p_run_id,p_outcome_id,'NO_ACTION','USER_CONFIRMED_NO_ACTION',p_supersedes);
end $$;
revoke all on function portfolio_mandate_private.confirm_no_action_r2(uuid,uuid,uuid) from public,anon,authenticated,service_role;
grant execute on function portfolio_mandate_private.confirm_no_action_r2(uuid,uuid,uuid) to authenticated;
create function public.confirm_portfolio_review_no_action_r2(p_run_id uuid,p_outcome_id uuid,p_supersedes uuid)
returns void language sql security invoker set search_path='' as $$
  select portfolio_mandate_private.confirm_no_action_r2(p_run_id,p_outcome_id,p_supersedes);
$$;
revoke all on function public.confirm_portfolio_review_no_action_r2(uuid,uuid,uuid) from public,anon,authenticated,service_role;
grant execute on function public.confirm_portfolio_review_no_action_r2(uuid,uuid,uuid) to authenticated;

create function portfolio_mandate_private.receive_local_outbox_r2(p_owner_id uuid)
returns integer language plpgsql security definer set search_path='' as $$
declare v_count integer;
begin
  -- A transactionally idempotent database sink. Never an external delivery claim.
  update public.portfolio_mandate_review_outbox_r2 o set received_at=statement_timestamp()
    from public.portfolio_mandate_review_decision_r2 d,public.portfolio_mandate_review_run_r2 r
    where o.decision_id=d.decision_id and d.run_id=r.run_id and r.owner_id=p_owner_id
      and o.received_at is null and not exists(select 1 from public.portfolio_mandate_review_run_r2 newer where newer.supersedes_run_id=r.run_id);
  get diagnostics v_count = row_count;
  return v_count;
end $$;
revoke all on function portfolio_mandate_private.receive_local_outbox_r2(uuid) from public,anon,authenticated,service_role;
grant execute on function portfolio_mandate_private.receive_local_outbox_r2(uuid) to portfolio_mandate_review_compiler_r2;
