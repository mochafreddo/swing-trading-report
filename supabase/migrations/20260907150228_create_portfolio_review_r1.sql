-- R1 is a read-only review extension. Existing/live application, backfill and
-- writer activation require separate approval. No order or publisher capability.
-- The original holding document is retained verbatim; no scalar SELL conversion.
create schema portfolio_mandate_private;
revoke all on schema portfolio_mandate_private from public, anon, authenticated, service_role;
grant usage on schema portfolio_mandate_private to authenticated;

create table public.portfolio_mandate_review_policy_r1 (
  mandate_version_id uuid primary key
    references public.portfolio_mandate_version_a1(mandate_version_id),
  source_document_sha256 text not null check (source_document_sha256 ~ '^sha256:[0-9a-f]{64}$'),
  holding_document text not null check (octet_length(holding_document) between 1 and 131072),
  holding_sha256 text generated always as
    ('sha256:' || encode(extensions.digest(holding_document, 'sha256'), 'hex')) stored,
  recorded_at timestamptz not null default statement_timestamp(),
  check (holding_document::jsonb ->> 'approval_state' is not distinct from 'APPROVED'),
  check (holding_document::jsonb ->> 'classification_state' is not distinct from 'ACTIVE'),
  check (holding_document::jsonb ->> 'horizon' is not distinct from 'LONG_TERM'),
  check (holding_document::jsonb #>> '{invalidation_policy,outcome}' is not distinct from 'THESIS_INVALIDATED_REVIEW_REQUIRED'),
  check (holding_document::jsonb ?& array['approval_state','classification_state','horizon','invalidation_policy','review_cadence'])
);

create table public.portfolio_mandate_review_observation_r1 (
  observation_id uuid primary key,
  mandate_version_id uuid not null
    references public.portfolio_mandate_review_policy_r1(mandate_version_id),
  rule_path text not null check (rule_path ~ '^(hard_triggers|signals)/[0-9]{1,2}/[0-9]{1,2}$'),
  period_key text not null check (period_key ~ '^([0-9]{4}Q[1-4]|[0-9]{4}|[0-9]{4}-[0-9]{2}-[0-9]{2})$'),
  metric text not null check (length(metric) between 1 and 200),
  unit text not null check (length(unit) between 1 and 100),
  observed_value jsonb not null check (jsonb_typeof(observed_value) in ('string','boolean')),
  evidence_seal_id uuid not null references public.portfolio_mandate_evidence_seal_a1(evidence_seal_id),
  source_content_sha256 text not null check (source_content_sha256 ~ '^sha256:[0-9a-f]{64}$'),
  source_tier text not null check (source_tier = 'PRIMARY'),
  authority text not null check (authority in ('USER','DETERMINISTIC_PARSER')),
  parser_version text not null check (length(parser_version) between 1 and 100),
  recorded_at timestamptz not null default statement_timestamp(),
  supersedes_observation_id uuid null unique,
  unique (observation_id, mandate_version_id, rule_path, period_key),
  foreign key (supersedes_observation_id, mandate_version_id, rule_path, period_key)
    references public.portfolio_mandate_review_observation_r1
      (observation_id, mandate_version_id, rule_path, period_key),
  check (supersedes_observation_id is distinct from observation_id)
);
create index portfolio_mandate_review_observation_r1_version_idx
  on public.portfolio_mandate_review_observation_r1(mandate_version_id, recorded_at);
create index portfolio_mandate_review_observation_r1_seal_idx
  on public.portfolio_mandate_review_observation_r1(evidence_seal_id);

create trigger portfolio_mandate_review_policy_r1_append_only
  before update or delete on public.portfolio_mandate_review_policy_r1
  for each row execute function public.reject_portfolio_mandate_event_mutation_a1();
create trigger portfolio_mandate_review_observation_r1_append_only
  before update or delete on public.portfolio_mandate_review_observation_r1
  for each row execute function public.reject_portfolio_mandate_event_mutation_a1();
alter table public.portfolio_mandate_review_policy_r1 enable row level security;
alter table public.portfolio_mandate_review_policy_r1 force row level security;
alter table public.portfolio_mandate_review_observation_r1 enable row level security;
alter table public.portfolio_mandate_review_observation_r1 force row level security;
revoke all on public.portfolio_mandate_review_policy_r1,
  public.portfolio_mandate_review_observation_r1
  from public, anon, authenticated, service_role, portfolio_mandate_candidate_submitter_a1;
-- No INSERT/UPDATE/DELETE/TRUNCATE grant or write RPC is supplied. Future backfill
-- must bind the imported document to the exact approved A1 version and owner.

create function portfolio_mandate_private.read_review_r1(p_version_ids uuid[])
returns jsonb
language plpgsql stable security definer
set search_path = ''
as $$
declare
  v_payload text;
begin
  if auth.uid() is null
    or (nullif(current_setting('request.jwt.claims', true), '')::jsonb ->> 'role')
      is distinct from 'authenticated'
  then
    raise exception 'REVIEW_READ_UNAUTHORIZED' using errcode = '42501';
  end if;
  if p_version_ids is null or cardinality(p_version_ids) not between 1 and 100
    or cardinality(p_version_ids) <> (select count(distinct x) from unnest(p_version_ids) x)
  then
    raise exception 'REVIEW_VERSION_SET_INVALID' using errcode = '22023';
  end if;
  if (select count(*) from public.portfolio_mandate_version_a1 v
      join public.portfolio_mandate_a1 m using (mandate_id)
      where v.mandate_version_id = any(p_version_ids) and m.owner_actor_id = auth.uid())
      <> cardinality(p_version_ids)
  then
    raise exception 'REVIEW_READ_UNAUTHORIZED' using errcode = '42501';
  end if;
  -- STABLE makes every subquery use the caller statement's MVCC snapshot.
  select jsonb_build_object(
    'schema_version', 'portfolio-review-input.r1',
    'read_at', statement_timestamp(),
    'rows', jsonb_agg(jsonb_build_object(
      'mandate_version_id', v.mandate_version_id,
      'instrument_id', m.instrument_id,
      'approval_state', v.approval_state,
      'classification_state', v.classification_state,
      'horizon', v.horizon,
      'approved_at', v.approved_at,
      'effective_from', v.effective_from,
      'effective_to', v.effective_to,
      'holding_document', p.holding_document,
      'holding_sha256', p.holding_sha256,
      'source_document_sha256', p.source_document_sha256,
      'policy_recorded_at', p.recorded_at,
      'broker', (select jsonb_build_object(
        'snapshot_version', b.snapshot_version, 'captured_at', b.captured_at,
        'sealed_input_hash', b.sealed_input_hash,
        'allocation_snapshot_version', a.snapshot_version,
        'allocation_version', a.allocation_version,
        'slices', coalesce((select jsonb_agg(jsonb_build_object(
          'slice_id', s.slice_id, 'eligible', s.decision_eligible and a.decision_eligible,
          'classification_state', s.classification_state
        ) order by s.slice_id) from public.portfolio_mandate_position_slice_a1 s
          where s.allocation_id = a.allocation_id and s.mandate_version_id = v.mandate_version_id), '[]'::jsonb)
        ) from public.portfolio_mandate_broker_snapshot_a1 b
          left join public.portfolio_mandate_allocation_a1 a
            on a.broker_position_id = b.broker_position_id and a.active
          where b.broker_position_id = m.broker_position_id
          order by b.snapshot_version desc limit 1),
      'observations', coalesce((select jsonb_agg(jsonb_build_object(
        'observation_id', o.observation_id, 'rule_path', o.rule_path,
        'period_key', o.period_key, 'metric', o.metric, 'unit', o.unit,
        'observed_value', o.observed_value, 'evidence_seal_id', o.evidence_seal_id,
        'source_content_sha256', o.source_content_sha256, 'source_tier', o.source_tier,
        'authority', o.authority, 'parser_version', o.parser_version,
        'recorded_at', o.recorded_at, 'supersedes_observation_id', o.supersedes_observation_id,
        'source_event_time', e.source_event_time, 'sealed_at', e.sealed_at,
        'source_instrument_id', e.instrument_id
      ) order by o.recorded_at, o.observation_id)
        from public.portfolio_mandate_review_observation_r1 o
        join public.portfolio_mandate_evidence_seal_a1 e using (evidence_seal_id)
        where o.mandate_version_id = v.mandate_version_id), '[]'::jsonb)
    ) order by v.mandate_version_id)
  )::text into v_payload
  from public.portfolio_mandate_version_a1 v
  join public.portfolio_mandate_a1 m using (mandate_id)
  left join public.portfolio_mandate_review_policy_r1 p using (mandate_version_id)
  where v.mandate_version_id = any(p_version_ids);
  return jsonb_build_object('payload', v_payload, 'payload_sha256',
    'sha256:' || encode(extensions.digest(v_payload, 'sha256'), 'hex'));
end;
$$;
revoke all on function portfolio_mandate_private.read_review_r1(uuid[])
  from public, anon, authenticated, service_role;
grant execute on function portfolio_mandate_private.read_review_r1(uuid[]) to authenticated;

create function public.read_portfolio_review_r1(p_version_ids uuid[])
returns jsonb language sql stable security invoker
set search_path = ''
as $$ select portfolio_mandate_private.read_review_r1(p_version_ids); $$;
revoke all on function public.read_portfolio_review_r1(uuid[])
  from public, anon, authenticated, service_role;
grant execute on function public.read_portfolio_review_r1(uuid[]) to authenticated;
