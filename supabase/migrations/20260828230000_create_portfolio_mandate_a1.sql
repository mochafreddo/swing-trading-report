-- Applying this create-only A1 migration outside a disposable database requires
-- separate approval.
-- The objects are additive and do not transfer ownership from legacy writers.

create extension if not exists btree_gist with schema extensions;
create extension if not exists pgcrypto with schema extensions;

do $$
begin
  if exists (
    select 1 from pg_catalog.pg_roles
    where rolname = 'portfolio_mandate_candidate_submitter_a1'
  ) then
    raise exception 'candidate submitter role must not pre-exist A1 migration'
      using errcode = '42501', detail = 'CANDIDATE_ROLE_ALREADY_EXISTS';
  end if;
  execute 'create role portfolio_mandate_candidate_submitter_a1 nologin noinherit nosuperuser nocreatedb nocreaterole noreplication nobypassrls';
end;
$$;

create table public.portfolio_mandate_issuer_a1 (
  issuer_id uuid primary key,
  legal_name text not null check (btrim(legal_name) <> ''),
  created_at timestamptz not null default clock_timestamp(),
  schema_version text not null default 'portfolio-mandate.a1'
    check (schema_version = 'portfolio-mandate.a1')
);

create table public.portfolio_mandate_issuer_identifier_a1 (
  issuer_id uuid not null
    references public.portfolio_mandate_issuer_a1(issuer_id),
  identifier_scheme text not null
    check (identifier_scheme ~ '^[A-Z][A-Z0-9_]{0,31}$'),
  identifier_value text not null check (btrim(identifier_value) <> ''),
  created_at timestamptz not null default clock_timestamp(),
  primary key (issuer_id, identifier_scheme, identifier_value),
  unique (identifier_scheme, identifier_value)
);

create table public.portfolio_mandate_instrument_a1 (
  instrument_id uuid primary key,
  issuer_id uuid not null
    references public.portfolio_mandate_issuer_a1(issuer_id),
  security_type text not null
    check (security_type in ('COMMON_STOCK', 'PREFERRED_STOCK', 'ETF')),
  currency text not null check (currency ~ '^[A-Z]{3}$'),
  created_at timestamptz not null default clock_timestamp(),
  schema_version text not null default 'portfolio-mandate.a1'
    check (schema_version = 'portfolio-mandate.a1'),
  unique (instrument_id, issuer_id)
);

create table public.portfolio_mandate_listing_alias_a1 (
  listing_alias_id uuid primary key,
  instrument_id uuid not null
    references public.portfolio_mandate_instrument_a1(instrument_id),
  exchange_mic text not null check (exchange_mic ~ '^[A-Z0-9]{4}$'),
  ticker text not null check (ticker ~ '^[A-Z][A-Z0-9./-]{0,31}$'),
  valid_from timestamptz not null,
  valid_to timestamptz null,
  registry_version text not null check (btrim(registry_version) <> ''),
  created_at timestamptz not null default clock_timestamp(),
  check (valid_to is null or valid_to > valid_from),
  constraint portfolio_mandate_listing_alias_a1_no_overlap
    exclude using gist (
      exchange_mic with =,
      ticker with =,
      tstzrange(valid_from, valid_to, '[)') with &&
    )
);

create table public.portfolio_mandate_issuer_evidence_policy_a1 (
  issuer_id uuid not null
    references public.portfolio_mandate_issuer_a1(issuer_id),
  instrument_id uuid not null,
  policy_version text not null check (btrim(policy_version) <> ''),
  created_at timestamptz not null default clock_timestamp(),
  primary key (issuer_id, instrument_id, policy_version),
  foreign key (instrument_id, issuer_id)
    references public.portfolio_mandate_instrument_a1(instrument_id, issuer_id)
);

create table public.portfolio_mandate_evidence_seal_a1 (
  evidence_seal_id uuid primary key,
  command_id uuid not null unique,
  source_id uuid not null,
  instrument_id uuid not null,
  issuer_id uuid not null,
  registry_version text not null check (btrim(registry_version) <> ''),
  source_event_time timestamptz not null,
  source_identifier_scheme text not null,
  source_identifier_value text not null,
  evidence_scope text not null check (evidence_scope in ('ISSUER', 'INSTRUMENT')),
  exchange_mic text not null,
  ticker text not null,
  sealed_at timestamptz not null,
  actor_kind text not null check (actor_kind = 'SOURCE_VALIDATOR'),
  created_at timestamptz not null default clock_timestamp(),
  foreign key (instrument_id, issuer_id)
    references public.portfolio_mandate_instrument_a1(instrument_id, issuer_id),
  foreign key (issuer_id, source_identifier_scheme, source_identifier_value)
    references public.portfolio_mandate_issuer_identifier_a1(
      issuer_id,
      identifier_scheme,
      identifier_value
    )
);

create unique index portfolio_mandate_evidence_seal_a1_source_uidx
on public.portfolio_mandate_evidence_seal_a1 (
  source_id,
  instrument_id,
  registry_version
);

create or replace function public.seal_evidence_identity_a1(
  p_command_id uuid,
  p_evidence_seal_id uuid,
  p_source_id uuid,
  p_instrument_id uuid,
  p_registry_version text,
  p_source_event_time timestamptz,
  p_source_identifier_scheme text,
  p_source_identifier_value text,
  p_evidence_scope text,
  p_exchange_mic text,
  p_ticker text,
  p_sealed_at timestamptz,
  p_actor_kind text
)
returns table (
  evidence_seal_id uuid,
  result_status text
)
language plpgsql
security definer
set search_path = pg_catalog, public
as $$
declare
  v_existing public.portfolio_mandate_evidence_seal_a1%rowtype;
  v_issuer_id uuid;
  v_alias_count integer;
begin
  if p_actor_kind <> 'SOURCE_VALIDATOR' then
    raise exception 'actor is not authorized to seal evidence identity'
      using errcode = '42501', detail = 'ACTOR_NOT_AUTHORIZED';
  end if;

  perform pg_catalog.pg_advisory_xact_lock(
    pg_catalog.hashtextextended('portfolio-mandate-command:' || p_command_id::text, 0)
  );
  perform pg_catalog.pg_advisory_xact_lock(
    pg_catalog.hashtextextended('portfolio-mandate-source:' || p_source_id::text, 0)
  );

  select seal.*
  into v_existing
  from public.portfolio_mandate_evidence_seal_a1 as seal
  where seal.command_id = p_command_id
  for update;

  if found then
    if v_existing.evidence_seal_id is distinct from p_evidence_seal_id
      or v_existing.source_id is distinct from p_source_id
      or v_existing.instrument_id is distinct from p_instrument_id
      or v_existing.registry_version is distinct from p_registry_version
      or v_existing.source_event_time is distinct from p_source_event_time
      or v_existing.source_identifier_scheme
        is distinct from p_source_identifier_scheme
      or v_existing.source_identifier_value
        is distinct from p_source_identifier_value
      or v_existing.evidence_scope is distinct from p_evidence_scope
      or v_existing.exchange_mic is distinct from p_exchange_mic
      or v_existing.ticker is distinct from p_ticker
      or v_existing.sealed_at is distinct from p_sealed_at
      or v_existing.actor_kind is distinct from p_actor_kind
    then
      raise exception 'evidence command idempotency conflict'
        using errcode = '23505', detail = 'IDEMPOTENCY_CONFLICT';
    end if;
    return query select v_existing.evidence_seal_id, 'ALREADY_SEALED'::text;
    return;
  end if;

  select instrument.issuer_id
  into v_issuer_id
  from public.portfolio_mandate_instrument_a1 as instrument
  where instrument.instrument_id = p_instrument_id
  for share;

  if v_issuer_id is null then
    raise exception 'instrument identity is not registered'
      using errcode = '23503', detail = 'INSTRUMENT_NOT_FOUND';
  end if;

  if exists (
    select 1
    from public.portfolio_mandate_evidence_seal_a1 as prior
    where prior.source_id = p_source_id
      and (
        prior.issuer_id <> v_issuer_id
        or prior.evidence_scope = 'INSTRUMENT'
        or p_evidence_scope = 'INSTRUMENT'
      )
      and prior.instrument_id <> p_instrument_id
  ) then
    raise exception 'evidence source is already sealed to another scope'
      using errcode = '23505', detail = 'SOURCE_SCOPE_CONFLICT';
  end if;

  select count(*)
  into v_alias_count
  from public.portfolio_mandate_listing_alias_a1 as alias
  where alias.instrument_id = p_instrument_id
    and alias.exchange_mic = p_exchange_mic
    and alias.ticker = p_ticker
    and alias.registry_version = p_registry_version
    and p_source_event_time >= alias.valid_from
    and (alias.valid_to is null or p_source_event_time < alias.valid_to);

  if v_alias_count <> 1 then
    raise exception 'alias does not resolve exactly at source event time'
      using errcode = '23514', detail = 'ALIAS_IDENTITY_AMBIGUOUS';
  end if;

  if not exists (
    select 1
    from public.portfolio_mandate_issuer_identifier_a1 as identifier
    where identifier.issuer_id = v_issuer_id
      and identifier.identifier_scheme = p_source_identifier_scheme
      and identifier.identifier_value = p_source_identifier_value
  ) then
    raise exception 'source issuer identifier does not match the registry'
      using errcode = '23514', detail = 'SOURCE_IDENTITY_MISMATCH';
  end if;

  if p_evidence_scope = 'ISSUER'
    and not exists (
      select 1
      from public.portfolio_mandate_issuer_evidence_policy_a1 as policy
      where policy.issuer_id = v_issuer_id
        and policy.instrument_id = p_instrument_id
        and policy.policy_version = p_registry_version
    )
  then
    raise exception 'issuer evidence sharing is not allowed by policy'
      using errcode = '42501', detail = 'ISSUER_SCOPE_NOT_ALLOWED';
  end if;

  insert into public.portfolio_mandate_evidence_seal_a1 (
    evidence_seal_id,
    command_id,
    source_id,
    instrument_id,
    issuer_id,
    registry_version,
    source_event_time,
    source_identifier_scheme,
    source_identifier_value,
    evidence_scope,
    exchange_mic,
    ticker,
    sealed_at,
    actor_kind
  ) values (
    p_evidence_seal_id,
    p_command_id,
    p_source_id,
    p_instrument_id,
    v_issuer_id,
    p_registry_version,
    p_source_event_time,
    p_source_identifier_scheme,
    p_source_identifier_value,
    p_evidence_scope,
    p_exchange_mic,
    p_ticker,
    p_sealed_at,
    p_actor_kind
  );

  return query select p_evidence_seal_id, 'SEALED'::text;
end;
$$;

create table public.portfolio_mandate_a1 (
  mandate_id uuid primary key,
  instrument_id uuid not null
    references public.portfolio_mandate_instrument_a1(instrument_id),
  broker_position_id uuid null,
  owner_actor_id uuid not null,
  created_at timestamptz not null default clock_timestamp(),
  schema_version text not null default 'portfolio-mandate.a1'
    check (schema_version = 'portfolio-mandate.a1')
);

create table public.portfolio_mandate_version_a1 (
  mandate_version_id uuid primary key,
  mandate_id uuid not null references public.portfolio_mandate_a1(mandate_id),
  version_number bigint not null check (version_number > 0),
  supersedes_version_id uuid null,
  classification_state text not null,
  horizon text null,
  proposed_horizon text null
    check (proposed_horizon is null or proposed_horizon in ('SWING', 'LONG_TERM')),
  approval_state text not null,
  thesis text null,
  invalidation_conditions text[] not null default '{}',
  approved_by_kind text null,
  approved_at timestamptz null,
  policy_version text not null check (btrim(policy_version) <> ''),
  effective_from timestamptz null,
  effective_to timestamptz null,
  created_at timestamptz not null default clock_timestamp(),
  unique (mandate_id, version_number),
  unique (mandate_id, mandate_version_id),
  foreign key (mandate_id, supersedes_version_id)
    references public.portfolio_mandate_version_a1(
      mandate_id, mandate_version_id
    ),
  constraint portfolio_mandate_version_a1_state_check check (
    (
      classification_state = 'ACTIVE'
      and approval_state = 'APPROVED'
      and horizon is not null and horizon in ('SWING', 'LONG_TERM')
      and proposed_horizon is null
      and thesis is not null
      and btrim(thesis) <> ''
      and coalesce(array_length(invalidation_conditions, 1), 0) > 0
      and approved_by_kind = 'USER'
      and approved_at is not null
      and effective_from is not null
    )
    or (
      classification_state = 'UNCLASSIFIED'
      and approval_state in ('DRAFT', 'NEEDS_REAPPROVAL')
      and horizon is null
      and approved_by_kind is null
      and approved_at is null
      and effective_from is null
    )
    or (
      classification_state in ('EXIT_REVIEW', 'CLOSED')
      and approval_state = 'APPROVED'
      and horizon is null
      and approved_by_kind = 'USER'
      and approved_at is not null
      and effective_from is not null
    )
  ),
  check (effective_to is null or effective_from is not null),
  check (effective_to is null or effective_to > effective_from)
);

create unique index portfolio_mandate_version_a1_one_active_uidx
on public.portfolio_mandate_version_a1 (mandate_id)
where classification_state = 'ACTIVE'
  and approval_state = 'APPROVED'
  and effective_to is null;

create table public.portfolio_mandate_activation_event_a1 (
  activation_event_id uuid primary key,
  command_id uuid not null unique,
  mandate_id uuid not null references public.portfolio_mandate_a1(mandate_id),
  prior_mandate_version_id uuid not null,
  activated_mandate_version_id uuid not null,
  broker_snapshot_version bigint not null check (broker_snapshot_version > 0),
  allocation_version bigint not null check (allocation_version > 0),
  target_allocation_version bigint not null check (target_allocation_version > 0),
  actor_kind text not null check (actor_kind = 'USER'),
  actor_id uuid not null,
  foreign key (mandate_id, prior_mandate_version_id)
    references public.portfolio_mandate_version_a1(
      mandate_id, mandate_version_id
    ),
  foreign key (mandate_id, activated_mandate_version_id)
    references public.portfolio_mandate_version_a1(
      mandate_id, mandate_version_id
    ),
  event_type text not null default 'MANDATE_VERSION_ACTIVATED'
    check (event_type = 'MANDATE_VERSION_ACTIVATED'),
  created_at timestamptz not null default clock_timestamp()
);

create table public.portfolio_mandate_broker_position_a1 (
  broker_position_id uuid primary key,
  account_ref_hash text not null
    check (account_ref_hash ~ '^sha256:[0-9a-f]{64}$'),
  instrument_id uuid not null
    references public.portfolio_mandate_instrument_a1(instrument_id),
  currency text not null check (currency ~ '^[A-Z]{3}$'),
  created_at timestamptz not null default clock_timestamp(),
  unique (account_ref_hash, instrument_id),
  unique (broker_position_id, instrument_id)
);

create table public.portfolio_mandate_broker_snapshot_a1 (
  broker_position_snapshot_id uuid primary key,
  broker_position_id uuid not null
    references public.portfolio_mandate_broker_position_a1(broker_position_id),
  snapshot_version bigint not null check (snapshot_version > 0),
  quantity numeric not null check (
    quantity not in ('NaN'::numeric, 'Infinity'::numeric, '-Infinity'::numeric)
    and quantity >= 0
    and scale(quantity) <= 6
  ),
  currency text not null check (currency ~ '^[A-Z]{3}$'),
  watermark text not null check (btrim(watermark) <> ''),
  sealed_input_hash text not null
    check (sealed_input_hash ~ '^sha256:[0-9a-f]{64}$'),
  captured_at timestamptz not null,
  created_at timestamptz not null default clock_timestamp(),
  unique (broker_position_id, snapshot_version),
  unique (broker_position_id, watermark)
);

create table public.portfolio_mandate_allocation_a1 (
  allocation_id uuid primary key,
  broker_position_id uuid not null,
  allocation_version bigint not null check (allocation_version > 0),
  snapshot_version bigint not null check (snapshot_version > 0),
  active boolean not null default false,
  decision_eligible boolean not null default false,
  created_at timestamptz not null default clock_timestamp(),
  closed_at timestamptz null,
  unique (broker_position_id, allocation_version),
  foreign key (broker_position_id, snapshot_version)
    references public.portfolio_mandate_broker_snapshot_a1(
      broker_position_id,
      snapshot_version
    ),
  check ((active and closed_at is null) or (not active and closed_at is not null))
);

create unique index portfolio_mandate_allocation_a1_one_active_uidx
on public.portfolio_mandate_allocation_a1 (broker_position_id)
where active;

create table public.portfolio_mandate_position_slice_a1 (
  slice_id uuid primary key,
  allocation_id uuid not null
    references public.portfolio_mandate_allocation_a1(allocation_id),
  source_slice_id uuid null
    references public.portfolio_mandate_position_slice_a1(slice_id),
  mandate_version_id uuid null
    references public.portfolio_mandate_version_a1(mandate_version_id),
  quantity numeric not null check (
    quantity not in ('NaN'::numeric, 'Infinity'::numeric, '-Infinity'::numeric)
    and quantity >= 0
    and scale(quantity) <= 6
  ),
  currency text not null check (currency ~ '^[A-Z]{3}$'),
  classification_state text not null
    check (classification_state in ('ACTIVE', 'UNCLASSIFIED', 'PENDING_ALLOCATION')),
  decision_eligible boolean not null,
  created_at timestamptz not null default clock_timestamp(),
  check (
    (
      classification_state = 'ACTIVE'
      and mandate_version_id is not null
      and decision_eligible
    )
    or (
      classification_state in ('UNCLASSIFIED', 'PENDING_ALLOCATION')
      and mandate_version_id is null
      and not decision_eligible
    )
  )
);

create table public.portfolio_mandate_rebase_evidence_a1 (
  rebase_evidence_id uuid primary key,
  broker_position_id uuid not null,
  source_snapshot_version bigint not null,
  target_snapshot_version bigint not null,
  rebase_cause text not null,
  matched_slice_id uuid null
    references public.portfolio_mandate_position_slice_a1(slice_id),
  corporate_action_ratio numeric null check (
    corporate_action_ratio not in (
      'NaN'::numeric, 'Infinity'::numeric, '-Infinity'::numeric
    )
    and corporate_action_ratio > 0
    and scale(corporate_action_ratio) <= 8
  ),
  source_id uuid not null,
  evidence_hash text not null check (evidence_hash ~ '^sha256:[0-9a-f]{64}$'),
  verification_state text not null
    check (verification_state in ('VERIFIED', 'UNRESOLVED')),
  producer_kind text not null check (producer_kind = 'DETERMINISTIC'),
  created_at timestamptz not null default clock_timestamp(),
  foreign key (broker_position_id, source_snapshot_version)
    references public.portfolio_mandate_broker_snapshot_a1(
      broker_position_id, snapshot_version
    ),
  foreign key (broker_position_id, target_snapshot_version)
    references public.portfolio_mandate_broker_snapshot_a1(
      broker_position_id, snapshot_version
    ),
  check (target_snapshot_version > source_snapshot_version)
);

create table public.portfolio_mandate_slice_rebase_event_a1 (
  slice_rebase_event_id uuid primary key,
  command_id uuid not null unique,
  rebase_evidence_id uuid not null unique
    references public.portfolio_mandate_rebase_evidence_a1(rebase_evidence_id),
  broker_position_id uuid not null
    references public.portfolio_mandate_broker_position_a1(broker_position_id),
  source_snapshot_version bigint not null,
  target_snapshot_version bigint not null,
  source_allocation_version bigint not null,
  target_allocation_version bigint not null,
  target_quantity numeric not null check (
    target_quantity not in (
      'NaN'::numeric, 'Infinity'::numeric, '-Infinity'::numeric
    )
    and target_quantity >= 0
    and scale(target_quantity) <= 6
  ),
  rebase_cause text not null,
  issue_code text null,
  decision_eligible boolean not null,
  actor_kind text not null check (actor_kind = 'DETERMINISTIC'),
  created_at timestamptz not null default clock_timestamp(),
  check (target_snapshot_version > source_snapshot_version),
  check (target_allocation_version > source_allocation_version)
);

create unique index portfolio_mandate_slice_rebase_event_a1_identity_uidx
on public.portfolio_mandate_slice_rebase_event_a1 (
  broker_position_id, target_snapshot_version
);

create or replace function public.rebase_position_slices_a1(
  p_command_id uuid,
  p_slice_rebase_event_id uuid,
  p_rebase_evidence_id uuid,
  p_broker_position_id uuid,
  p_source_snapshot_version bigint,
  p_target_snapshot_version bigint,
  p_target_quantity numeric,
  p_currency text,
  p_rebase_cause text,
  p_matched_slice_id uuid,
  p_corporate_action_ratio numeric,
  p_expected_allocation_version bigint,
  p_actor_kind text
)
returns table (
  slice_rebase_event_id uuid,
  allocation_version bigint,
  target_snapshot_version bigint,
  decision_eligible boolean,
  result_status text
)
language plpgsql
security definer
set search_path = pg_catalog, public, extensions
as $$
declare
  v_existing public.portfolio_mandate_slice_rebase_event_a1%rowtype;
  v_rebase_evidence public.portfolio_mandate_rebase_evidence_a1%rowtype;
  v_source_allocation public.portfolio_mandate_allocation_a1%rowtype;
  v_source_snapshot public.portfolio_mandate_broker_snapshot_a1%rowtype;
  v_target_snapshot public.portfolio_mandate_broker_snapshot_a1%rowtype;
  v_target_allocation_id uuid := extensions.gen_random_uuid();
  v_target_allocation_version bigint;
  v_delta numeric;
  v_slice_total numeric;
  v_classified_total numeric;
  v_decision_eligible boolean := true;
  v_issue_code text := null;
begin
  if p_actor_kind <> 'DETERMINISTIC' then
    raise exception 'only a deterministic actor can rebase slices'
      using errcode = '42501', detail = 'ACTOR_NOT_AUTHORIZED';
  end if;

  select event.*
  into v_existing
  from public.portfolio_mandate_slice_rebase_event_a1 as event
  where event.broker_position_id = p_broker_position_id
    and event.target_snapshot_version = p_target_snapshot_version
  for update;

  if found then
    if v_existing.target_quantity <> p_target_quantity
      or v_existing.rebase_cause <> upper(p_rebase_cause)
      or v_existing.rebase_evidence_id <> p_rebase_evidence_id
    then
      raise exception 'rebase identity conflicts with an existing result'
        using errcode = '23505', detail = 'IDEMPOTENCY_CONFLICT';
    end if;
    return query
    select
      v_existing.slice_rebase_event_id,
      v_existing.target_allocation_version,
      v_existing.target_snapshot_version,
      v_existing.decision_eligible,
      'ALREADY_REBASED'::text;
    return;
  end if;

  perform 1
  from public.portfolio_mandate_broker_position_a1 as position
  where position.broker_position_id = p_broker_position_id
    and position.currency = p_currency
  for update;
  if not found then
    raise exception 'broker position or currency does not match'
      using errcode = '23503', detail = 'BROKER_POSITION_NOT_FOUND';
  end if;

  select evidence.*
  into v_rebase_evidence
  from public.portfolio_mandate_rebase_evidence_a1 as evidence
  where evidence.rebase_evidence_id = p_rebase_evidence_id
  for share;
  if v_rebase_evidence.rebase_evidence_id is null
    or v_rebase_evidence.broker_position_id <> p_broker_position_id
    or v_rebase_evidence.source_snapshot_version <> p_source_snapshot_version
    or v_rebase_evidence.target_snapshot_version <> p_target_snapshot_version
    or v_rebase_evidence.rebase_cause <> upper(p_rebase_cause)
    or v_rebase_evidence.matched_slice_id is distinct from p_matched_slice_id
    or v_rebase_evidence.corporate_action_ratio
      is distinct from p_corporate_action_ratio
    or (
      lower(p_rebase_cause) in (
        'unresolved_buy', 'ambiguous_sell', 'ambiguous_corporate_action'
      )
      and v_rebase_evidence.verification_state <> 'UNRESOLVED'
    )
    or (
      lower(p_rebase_cause) not in (
        'unresolved_buy', 'ambiguous_sell', 'ambiguous_corporate_action'
      )
      and v_rebase_evidence.verification_state <> 'VERIFIED'
    )
  then
    raise exception 'rebase evidence does not match the command'
      using errcode = '23514', detail = 'REBASE_EVIDENCE_MISMATCH';
  end if;

  select allocation.*
  into v_source_allocation
  from public.portfolio_mandate_allocation_a1 as allocation
  where allocation.broker_position_id = p_broker_position_id
    and allocation.active
  for update;

  if v_source_allocation.allocation_id is null
    or v_source_allocation.allocation_version <> p_expected_allocation_version
  then
    raise exception 'expected_allocation_version is stale'
      using errcode = '40001', detail = 'STALE_ALLOCATION_VERSION';
  end if;
  if v_source_allocation.snapshot_version <> p_source_snapshot_version then
    raise exception 'source snapshot does not match the active allocation'
      using errcode = '40001', detail = 'STALE_SOURCE_SNAPSHOT';
  end if;

  select snapshot.*
  into v_source_snapshot
  from public.portfolio_mandate_broker_snapshot_a1 as snapshot
  where snapshot.broker_position_id = p_broker_position_id
    and snapshot.snapshot_version = p_source_snapshot_version
  for share;
  select snapshot.*
  into v_target_snapshot
  from public.portfolio_mandate_broker_snapshot_a1 as snapshot
  where snapshot.broker_position_id = p_broker_position_id
    and snapshot.snapshot_version = p_target_snapshot_version
  for share;

  if v_target_snapshot.broker_position_snapshot_id is null
    or v_target_snapshot.quantity <> p_target_quantity
    or v_target_snapshot.currency <> p_currency
  then
    raise exception 'target snapshot quantity or currency does not match'
      using errcode = '23514', detail = 'TARGET_SNAPSHOT_MISMATCH';
  end if;
  if exists (
    select 1
    from public.portfolio_mandate_broker_snapshot_a1 as newer
    where newer.broker_position_id = p_broker_position_id
      and newer.snapshot_version > p_target_snapshot_version
  ) then
    raise exception 'newer broker snapshot exists'
      using errcode = '40001', detail = 'NEWER_SNAPSHOT_REQUIRES_RETRY';
  end if;

  v_delta := p_target_quantity - v_source_snapshot.quantity;
  v_target_allocation_version := v_source_allocation.allocation_version + 1;
  insert into public.portfolio_mandate_allocation_a1 (
    allocation_id,
    broker_position_id,
    allocation_version,
    snapshot_version,
    active,
    decision_eligible,
    closed_at
  ) values (
    v_target_allocation_id,
    p_broker_position_id,
    v_target_allocation_version,
    p_target_snapshot_version,
    false,
    false,
    clock_timestamp()
  );

  case lower(p_rebase_cause)
    when 'zero_delta' then
      if v_delta <> 0 or p_matched_slice_id is not null then
        raise exception 'zero delta evidence does not match quantity delta'
          using errcode = '23514', detail = 'REBASE_CAUSE_MISMATCH';
      end if;
      insert into public.portfolio_mandate_position_slice_a1 (
        slice_id, allocation_id, source_slice_id, mandate_version_id, quantity,
        currency, classification_state, decision_eligible
      )
      select
        extensions.gen_random_uuid(), v_target_allocation_id, source_slice.slice_id,
        source_slice.mandate_version_id, source_slice.quantity, source_slice.currency,
        source_slice.classification_state, source_slice.decision_eligible
      from public.portfolio_mandate_position_slice_a1 as source_slice
      where source_slice.allocation_id = v_source_allocation.allocation_id;
    when 'unique_buy' then
      if v_delta <= 0 or p_matched_slice_id is null then
        raise exception 'unique buy evidence does not match quantity delta'
          using errcode = '23514', detail = 'REBASE_CAUSE_MISMATCH';
      end if;
      insert into public.portfolio_mandate_position_slice_a1 (
        slice_id, allocation_id, source_slice_id, mandate_version_id, quantity,
        currency, classification_state, decision_eligible
      )
      select
        extensions.gen_random_uuid(), v_target_allocation_id, source_slice.slice_id,
        source_slice.mandate_version_id,
        source_slice.quantity + case
          when source_slice.slice_id = p_matched_slice_id then v_delta else 0 end,
        source_slice.currency, source_slice.classification_state,
        source_slice.decision_eligible
      from public.portfolio_mandate_position_slice_a1 as source_slice
      where source_slice.allocation_id = v_source_allocation.allocation_id;
    when 'unresolved_buy' then
      if v_delta <= 0 or p_matched_slice_id is not null then
        raise exception 'unresolved buy evidence does not match quantity delta'
          using errcode = '23514', detail = 'REBASE_CAUSE_MISMATCH';
      end if;
      insert into public.portfolio_mandate_position_slice_a1 (
        slice_id, allocation_id, source_slice_id, mandate_version_id, quantity,
        currency, classification_state, decision_eligible
      )
      select
        extensions.gen_random_uuid(), v_target_allocation_id, source_slice.slice_id,
        source_slice.mandate_version_id, source_slice.quantity, source_slice.currency,
        source_slice.classification_state, source_slice.decision_eligible
      from public.portfolio_mandate_position_slice_a1 as source_slice
      where source_slice.allocation_id = v_source_allocation.allocation_id;
      insert into public.portfolio_mandate_position_slice_a1 (
        slice_id, allocation_id, source_slice_id, mandate_version_id, quantity,
        currency, classification_state, decision_eligible
      ) values (
        extensions.gen_random_uuid(), v_target_allocation_id, null, null, v_delta,
        p_currency, 'UNCLASSIFIED', false
      );
      v_decision_eligible := false;
    when 'unique_sell' then
      if v_delta >= 0 or p_matched_slice_id is null then
        raise exception 'unique sell evidence does not match quantity delta'
          using errcode = '23514', detail = 'REBASE_CAUSE_MISMATCH';
      end if;
      if exists (
        select 1
        from public.portfolio_mandate_position_slice_a1 as source_slice
        where source_slice.allocation_id = v_source_allocation.allocation_id
          and source_slice.slice_id = p_matched_slice_id
          and source_slice.quantity + v_delta < 0
      ) then
        raise exception 'matched slice would become negative'
          using errcode = '23514', detail = 'NEGATIVE_SLICE_QUANTITY';
      end if;
      insert into public.portfolio_mandate_position_slice_a1 (
        slice_id, allocation_id, source_slice_id, mandate_version_id, quantity,
        currency, classification_state, decision_eligible
      )
      select
        extensions.gen_random_uuid(), v_target_allocation_id, source_slice.slice_id,
        source_slice.mandate_version_id,
        source_slice.quantity + case
          when source_slice.slice_id = p_matched_slice_id then v_delta else 0 end,
        source_slice.currency, source_slice.classification_state,
        source_slice.decision_eligible
      from public.portfolio_mandate_position_slice_a1 as source_slice
      where source_slice.allocation_id = v_source_allocation.allocation_id
        and source_slice.quantity + case
          when source_slice.slice_id = p_matched_slice_id then v_delta else 0 end > 0;
    when 'ambiguous_sell' then
      v_decision_eligible := false;
      insert into public.portfolio_mandate_position_slice_a1 (
        slice_id, allocation_id, source_slice_id, mandate_version_id, quantity,
        currency, classification_state, decision_eligible
      ) values (
        extensions.gen_random_uuid(), v_target_allocation_id, null, null,
        p_target_quantity, p_currency, 'PENDING_ALLOCATION', false
      );
    when 'position_closed' then
      if p_target_quantity <> 0 then
        raise exception 'position closed rebase requires zero target quantity'
          using errcode = '23514', detail = 'REBASE_CAUSE_MISMATCH';
      end if;
      v_decision_eligible := false;
    when 'verified_corporate_action' then
      if p_corporate_action_ratio is null or p_corporate_action_ratio <= 0 then
        raise exception 'verified corporate action requires a positive ratio'
          using errcode = '23514', detail = 'REBASE_CAUSE_MISMATCH';
      end if;
      insert into public.portfolio_mandate_position_slice_a1 (
        slice_id, allocation_id, source_slice_id, mandate_version_id, quantity,
        currency, classification_state, decision_eligible
      )
      select
        extensions.gen_random_uuid(), v_target_allocation_id, source_slice.slice_id,
        source_slice.mandate_version_id,
        source_slice.quantity * p_corporate_action_ratio,
        source_slice.currency, source_slice.classification_state,
        source_slice.decision_eligible
      from public.portfolio_mandate_position_slice_a1 as source_slice
      where source_slice.allocation_id = v_source_allocation.allocation_id;
    when 'ambiguous_corporate_action' then
      v_decision_eligible := false;
      v_issue_code := 'CORPORATE_ACTION_AMBIGUOUS';
      insert into public.portfolio_mandate_position_slice_a1 (
        slice_id, allocation_id, source_slice_id, mandate_version_id, quantity,
        currency, classification_state, decision_eligible
      ) values (
        extensions.gen_random_uuid(), v_target_allocation_id, null, null,
        p_target_quantity, p_currency, 'PENDING_ALLOCATION', false
      );
    else
      raise exception 'unsupported rebase cause'
        using errcode = '23514', detail = 'REBASE_CAUSE_UNSUPPORTED';
  end case;

  select coalesce(sum(position_slice.quantity), 0)
  into v_slice_total
  from public.portfolio_mandate_position_slice_a1 as position_slice
  where position_slice.allocation_id = v_target_allocation_id;
  if v_slice_total <> p_target_quantity then
    raise exception 'target slice quantity mismatch'
      using errcode = '23514', detail = 'SLICE_QUANTITY_MISMATCH';
  end if;

  select coalesce(sum(position_slice.quantity), 0)
  into v_classified_total
  from public.portfolio_mandate_position_slice_a1 as position_slice
  where position_slice.allocation_id = v_target_allocation_id
    and position_slice.classification_state = 'ACTIVE';
  if v_classified_total > p_target_quantity then
    raise exception 'classified slice quantity exceeds broker quantity'
      using errcode = '23514', detail = 'CLASSIFIED_QUANTITY_OVERFLOW';
  end if;

  update public.portfolio_mandate_allocation_a1 as allocation
  set active = false, closed_at = clock_timestamp()
  where allocation.allocation_id = v_source_allocation.allocation_id;
  update public.portfolio_mandate_allocation_a1 as allocation
  set
    active = true,
    closed_at = null,
    decision_eligible = v_decision_eligible
  where allocation.allocation_id = v_target_allocation_id;

  insert into public.portfolio_mandate_slice_rebase_event_a1 (
    slice_rebase_event_id,
    command_id,
    rebase_evidence_id,
    broker_position_id,
    source_snapshot_version,
    target_snapshot_version,
    source_allocation_version,
    target_allocation_version,
    target_quantity,
    rebase_cause,
    issue_code,
    decision_eligible,
    actor_kind
  ) values (
    p_slice_rebase_event_id,
    p_command_id,
    p_rebase_evidence_id,
    p_broker_position_id,
    p_source_snapshot_version,
    p_target_snapshot_version,
    v_source_allocation.allocation_version,
    v_target_allocation_version,
    p_target_quantity,
    upper(p_rebase_cause),
    v_issue_code,
    v_decision_eligible,
    p_actor_kind
  );

  return query
  select
    p_slice_rebase_event_id,
    v_target_allocation_version,
    p_target_snapshot_version,
    v_decision_eligible,
    'REBASED'::text;
end;
$$;

alter table public.portfolio_mandate_a1
add constraint portfolio_mandate_a1_broker_position_fk
foreign key (broker_position_id, instrument_id)
references public.portfolio_mandate_broker_position_a1(
  broker_position_id, instrument_id
);

create table public.portfolio_mandate_issuer_lineage_event_a1 (
  issuer_lineage_event_id uuid primary key,
  predecessor_issuer_id uuid not null
    references public.portfolio_mandate_issuer_a1(issuer_id),
  successor_issuer_id uuid not null
    references public.portfolio_mandate_issuer_a1(issuer_id),
  event_type text not null check (event_type in ('MERGER', 'SPLIT', 'CORRECTION')),
  supersedes_event_id uuid null
    references public.portfolio_mandate_issuer_lineage_event_a1(issuer_lineage_event_id),
  registry_version text not null,
  published_at timestamptz not null,
  check (predecessor_issuer_id <> successor_issuer_id)
);

create table public.portfolio_mandate_journal_event_a1 (
  journal_event_id uuid primary key,
  command_id uuid not null unique,
  aggregate_id uuid not null
    references public.portfolio_mandate_a1(mandate_id),
  aggregate_version_id uuid not null
    references public.portfolio_mandate_version_a1(mandate_version_id),
  event_type text not null,
  actor_kind text not null,
  event_payload jsonb not null,
  supersedes_event_id uuid null
    references public.portfolio_mandate_journal_event_a1(journal_event_id),
  published_at timestamptz not null
);

create table public.portfolio_mandate_decision_projection_a1 (
  decision_id uuid primary key,
  mandate_version_id uuid not null
    references public.portfolio_mandate_version_a1(mandate_version_id),
  slice_id uuid null
    references public.portfolio_mandate_position_slice_a1(slice_id),
  source_journal_event_id uuid not null
    references public.portfolio_mandate_journal_event_a1(journal_event_id),
  projection_status text not null
    check (projection_status in ('ACTIVE', 'SUPERSEDED')),
  eligible boolean not null,
  projection_version bigint not null check (projection_version > 0),
  created_at timestamptz not null default clock_timestamp(),
  superseded_at timestamptz null,
  check (
    (projection_status = 'ACTIVE' and eligible and superseded_at is null)
    or (projection_status = 'SUPERSEDED' and not eligible and superseded_at is not null)
  )
);

create table public.portfolio_mandate_predicate_definition_a1 (
  predicate_id uuid not null,
  mandate_version_id uuid not null
    references public.portfolio_mandate_version_a1(mandate_version_id),
  predicate_schema_version text not null check (btrim(predicate_schema_version) <> ''),
  metric text not null check (metric ~ '^[A-Z][A-Z0-9_]{0,63}$'),
  comparison_operator text not null
    check (comparison_operator in ('LT', 'LTE', 'EQ', 'GTE', 'GT')),
  threshold_value numeric not null check (
    threshold_value not in (
      'NaN'::numeric, 'Infinity'::numeric, '-Infinity'::numeric
    )
    and scale(threshold_value) <= 6
  ),
  expected_unit text not null check (btrim(expected_unit) <> ''),
  expected_period text not null check (btrim(expected_period) <> ''),
  approval_state text not null check (approval_state = 'APPROVED'),
  approved_by_kind text not null check (approved_by_kind = 'USER'),
  created_at timestamptz not null default clock_timestamp(),
  unique (predicate_id, mandate_version_id)
);

create table public.portfolio_mandate_predicate_authority_event_a1 (
  predicate_authority_event_id uuid primary key,
  command_id uuid not null unique,
  mandate_version_id uuid not null
    references public.portfolio_mandate_version_a1(mandate_version_id),
  predicate_id uuid not null,
  event_type text not null,
  producer_kind text not null,
  actor_kind text not null,
  policy_effect text not null
    check (policy_effect in ('SELL_ELIGIBLE', 'REVIEW_ONLY', 'PROVENANCE_ONLY')),
  source_id uuid not null,
  evidence_seal_id uuid not null
    references public.portfolio_mandate_evidence_seal_a1(evidence_seal_id),
  source_span text null,
  observed_metric text null,
  observed_value numeric null check (
    observed_value not in (
      'NaN'::numeric, 'Infinity'::numeric, '-Infinity'::numeric
    )
    and scale(observed_value) <= 6
  ),
  unit text null,
  period text null,
  parser_version text null,
  predicate_schema_version text null,
  actor_id text null,
  reason text null,
  structured_surface boolean not null,
  free_text_only boolean not null,
  issue_code text null,
  supersedes_event_id uuid null,
  published_at timestamptz not null,
  unique (predicate_authority_event_id, mandate_version_id, predicate_id),
  foreign key (predicate_id, mandate_version_id)
    references public.portfolio_mandate_predicate_definition_a1(
      predicate_id, mandate_version_id
    ),
  foreign key (supersedes_event_id, mandate_version_id, predicate_id)
    references public.portfolio_mandate_predicate_authority_event_a1(
      predicate_authority_event_id, mandate_version_id, predicate_id
    )
);

create or replace function public.reject_portfolio_mandate_event_mutation_a1()
returns trigger
language plpgsql
security invoker
set search_path = pg_catalog
as $$
begin
  raise exception 'published Portfolio Mandate events are append-only'
    using errcode = '55000', detail = 'APPEND_ONLY_EVENT';
end;
$$;

create trigger portfolio_mandate_issuer_lineage_event_a1_append_only
before update or delete on public.portfolio_mandate_issuer_lineage_event_a1
for each row execute function public.reject_portfolio_mandate_event_mutation_a1();
create trigger portfolio_mandate_evidence_seal_a1_append_only
before update or delete on public.portfolio_mandate_evidence_seal_a1
for each row execute function public.reject_portfolio_mandate_event_mutation_a1();
create trigger portfolio_mandate_activation_event_a1_append_only
before update or delete on public.portfolio_mandate_activation_event_a1
for each row execute function public.reject_portfolio_mandate_event_mutation_a1();
create trigger portfolio_mandate_slice_rebase_event_a1_append_only
before update or delete on public.portfolio_mandate_slice_rebase_event_a1
for each row execute function public.reject_portfolio_mandate_event_mutation_a1();
create trigger portfolio_mandate_rebase_evidence_a1_append_only
before update or delete on public.portfolio_mandate_rebase_evidence_a1
for each row execute function public.reject_portfolio_mandate_event_mutation_a1();
create trigger portfolio_mandate_journal_event_a1_append_only
before update or delete on public.portfolio_mandate_journal_event_a1
for each row execute function public.reject_portfolio_mandate_event_mutation_a1();
create trigger portfolio_mandate_predicate_authority_event_a1_append_only
before update or delete on public.portfolio_mandate_predicate_authority_event_a1
for each row execute function public.reject_portfolio_mandate_event_mutation_a1();
create trigger portfolio_mandate_predicate_definition_a1_append_only
before update or delete on public.portfolio_mandate_predicate_definition_a1
for each row execute function public.reject_portfolio_mandate_event_mutation_a1();

create or replace function public.record_predicate_authority_a1(
  p_command_id uuid,
  p_predicate_authority_event_id uuid,
  p_mandate_version_id uuid,
  p_predicate_id uuid,
  p_event_type text,
  p_producer_kind text,
  p_actor_kind text,
  p_source_id uuid,
  p_evidence_seal_id uuid,
  p_source_span text,
  p_observed_metric text,
  p_observed_value numeric,
  p_unit text,
  p_period text,
  p_parser_version text,
  p_predicate_schema_version text,
  p_actor_id text,
  p_reason text,
  p_structured_surface boolean,
  p_free_text_only boolean,
  p_supersedes_event_id uuid,
  p_published_at timestamptz
)
returns table (
  predicate_authority_event_id uuid,
  stored_event_type text,
  policy_effect text,
  result_status text
)
language plpgsql
security definer
set search_path = pg_catalog, public
as $$
declare
  v_existing public.portfolio_mandate_predicate_authority_event_a1%rowtype;
  v_definition public.portfolio_mandate_predicate_definition_a1%rowtype;
  v_authenticated_actor_id uuid := auth.uid();
  v_owner_actor_id uuid;
  v_request_claims text := nullif(
    current_setting('request.jwt.claims', true),
    ''
  );
  v_request_role text := coalesce(
    nullif(current_setting('request.jwt.claim.role', true), ''),
    case when v_request_claims is null
      then null
      else v_request_claims::jsonb ->> 'role'
    end
  );
  v_event_type text := upper(p_event_type);
  v_policy_effect text;
  v_issue_code text := null;
begin
  if v_request_role = 'authenticated' then
    if v_event_type not in ('USER_PREDICATE_CONFIRMED', 'PREDICATE_SUPERSEDED')
      or p_producer_kind <> 'USER'
      or p_actor_kind <> 'USER'
    then
      raise exception 'authenticated callers may only write user authority'
        using errcode = '42501', detail = 'ACTOR_NOT_AUTHORIZED';
    end if;
    if v_authenticated_actor_id is null
      or p_actor_id is distinct from v_authenticated_actor_id::text
    then
      raise exception 'predicate confirmation actor does not match auth.uid()'
        using errcode = '42501', detail = 'ACTOR_IDENTITY_MISMATCH';
    end if;
    select mandate.owner_actor_id
    into v_owner_actor_id
    from public.portfolio_mandate_version_a1 as version
    join public.portfolio_mandate_a1 as mandate
      on mandate.mandate_id = version.mandate_id
    where version.mandate_version_id = p_mandate_version_id;
    if v_owner_actor_id is distinct from v_authenticated_actor_id then
      raise exception 'predicate authority actor does not own mandate'
        using errcode = '42501', detail = 'ACTOR_NOT_AUTHORIZED';
    end if;
  elsif p_producer_kind = 'USER' or p_actor_kind = 'USER' then
    raise exception 'user predicate authority requires an authenticated request'
      using errcode = '42501', detail = 'AUTHENTICATED_USER_REQUIRED';
  end if;

  select event.*
  into v_existing
  from public.portfolio_mandate_predicate_authority_event_a1 as event
  where event.command_id = p_command_id
  for update;
  if found then
    if v_existing.predicate_authority_event_id
        is distinct from p_predicate_authority_event_id
      or v_existing.mandate_version_id <> p_mandate_version_id
      or v_existing.predicate_id <> p_predicate_id
      or v_existing.event_type is distinct from v_event_type
      or v_existing.producer_kind is distinct from p_producer_kind
      or v_existing.actor_kind is distinct from p_actor_kind
      or v_existing.source_id is distinct from p_source_id
      or v_existing.evidence_seal_id is distinct from p_evidence_seal_id
      or v_existing.source_span is distinct from p_source_span
      or v_existing.observed_metric is distinct from p_observed_metric
      or v_existing.observed_value is distinct from p_observed_value
      or v_existing.unit is distinct from p_unit
      or v_existing.period is distinct from p_period
      or v_existing.parser_version is distinct from p_parser_version
      or v_existing.predicate_schema_version
        is distinct from p_predicate_schema_version
      or v_existing.actor_id is distinct from p_actor_id
      or v_existing.reason is distinct from p_reason
      or v_existing.structured_surface is distinct from p_structured_surface
      or v_existing.free_text_only is distinct from p_free_text_only
      or v_existing.supersedes_event_id is distinct from p_supersedes_event_id
      or v_existing.published_at is distinct from p_published_at
    then
      raise exception 'predicate authority command idempotency conflict'
        using errcode = '23505', detail = 'IDEMPOTENCY_CONFLICT';
    end if;
    return query
    select
      v_existing.predicate_authority_event_id,
      v_existing.event_type,
      v_existing.policy_effect,
      'ALREADY_RECORDED'::text;
    return;
  end if;

  if not exists (
    select 1
    from public.portfolio_mandate_evidence_seal_a1 as seal
    join public.portfolio_mandate_version_a1 as version
      on version.mandate_version_id = p_mandate_version_id
    join public.portfolio_mandate_a1 as mandate
      on mandate.mandate_id = version.mandate_id
    where seal.evidence_seal_id = p_evidence_seal_id
      and seal.source_id = p_source_id
      and seal.instrument_id = mandate.instrument_id
  ) then
    raise exception 'predicate source seal does not match the mandate instrument'
      using errcode = '23514', detail = 'PREDICATE_SOURCE_SEAL_MISMATCH';
  end if;

  if p_actor_kind in ('AI', 'RESEARCH_ADAPTER')
    and upper(p_event_type) <> 'PREDICATE_CANDIDATE'
  then
    raise exception 'research actor cannot write predicate authority'
      using errcode = '42501', detail = 'ACTOR_NOT_AUTHORIZED';
  end if;

  if p_free_text_only then
    raise exception 'free-text rationale does not create an authority event'
      using errcode = '23514', detail = 'FREE_TEXT_REVIEW_REQUIRED';
  end if;

  if lower(p_event_type) <> 'predicate_superseded'
    and p_supersedes_event_id is not null
  then
    raise exception 'only a correction can supersede an authority event'
      using errcode = '23514', detail = 'UNEXPECTED_SUPERSEDES_EVENT';
  end if;

  case lower(p_event_type)
    when 'predicate_fulfilled' then
      if p_producer_kind <> 'DETERMINISTIC_PARSER'
        or p_actor_kind <> 'DETERMINISTIC'
      then
        raise exception 'predicate fulfillment producer is not authorized'
          using errcode = '42501', detail = 'ACTOR_NOT_AUTHORIZED';
      end if;
      if not p_structured_surface then
        raise exception 'unknown parser surface requires user review'
          using errcode = '23514', detail = 'UNKNOWN_PARSER_SURFACE';
      elsif p_observed_value in (
        'NaN'::numeric, 'Infinity'::numeric, '-Infinity'::numeric
      ) then
        raise exception 'predicate observed value must be finite'
          using errcode = '23514', detail = 'PREDICATE_NUMERIC_NOT_FINITE';
      elsif p_source_span is null
        or p_observed_metric is null
        or p_observed_value is null
        or p_unit is null
        or p_period is null
        or p_parser_version is null
        or p_predicate_schema_version is null
      then
        raise exception 'verified parser event is missing typed audit fields'
          using errcode = '23514', detail = 'PREDICATE_AUDIT_FIELDS_MISSING';
      else
        select definition.*
        into v_definition
        from public.portfolio_mandate_predicate_definition_a1 as definition
        where definition.predicate_id = p_predicate_id
          and definition.mandate_version_id = p_mandate_version_id
          and definition.predicate_schema_version = p_predicate_schema_version;
        if not found then
          raise exception 'verified parser event is missing an approved definition'
            using errcode = '23514', detail = 'PREDICATE_AUDIT_FIELDS_MISSING';
        end if;
        if p_observed_metric is distinct from v_definition.metric
          or p_unit is distinct from v_definition.expected_unit
          or p_period is distinct from v_definition.expected_period
          or (case v_definition.comparison_operator
            when 'LT' then p_observed_value < v_definition.threshold_value
            when 'LTE' then p_observed_value <= v_definition.threshold_value
            when 'EQ' then p_observed_value = v_definition.threshold_value
            when 'GTE' then p_observed_value >= v_definition.threshold_value
            when 'GT' then p_observed_value > v_definition.threshold_value
            else false
          end) is not true
        then
          raise exception 'observed metric does not satisfy the approved predicate'
            using errcode = '23514', detail = 'PREDICATE_NOT_FULFILLED';
        end if;
        v_policy_effect := 'SELL_ELIGIBLE';
      end if;
    when 'user_predicate_confirmed' then
      if p_producer_kind <> 'USER'
        or p_actor_kind <> 'USER'
        or p_actor_id is null
        or p_reason is null
        or p_source_span is null
        or p_predicate_schema_version is null
        or not p_structured_surface
        or p_free_text_only
        or not exists (
          select 1
          from public.portfolio_mandate_predicate_definition_a1 as definition
          where definition.predicate_id = p_predicate_id
            and definition.mandate_version_id = p_mandate_version_id
            and definition.predicate_schema_version = p_predicate_schema_version
        )
      then
        raise exception 'user confirmation is missing full audit fields'
          using errcode = '23514', detail = 'USER_CONFIRMATION_INCOMPLETE';
      end if;
      v_policy_effect := 'SELL_ELIGIBLE';
    when 'predicate_candidate' then
      if p_producer_kind <> 'AI' or p_actor_kind <> 'RESEARCH_ADAPTER' then
        raise exception 'predicate candidate must come from the research adapter'
          using errcode = '42501', detail = 'ACTOR_NOT_AUTHORIZED';
      end if;
      v_policy_effect := 'REVIEW_ONLY';
    when 'provenance_validated' then
      if p_producer_kind <> 'SOURCE_VALIDATOR'
        or p_actor_kind <> 'SOURCE_VALIDATOR'
      then
        raise exception 'source validator can only confirm provenance'
          using errcode = '42501', detail = 'ACTOR_NOT_AUTHORIZED';
      end if;
      if p_source_span is null or not p_structured_surface then
        raise exception 'provenance validation is missing structured audit fields'
          using errcode = '23514', detail = 'PROVENANCE_AUDIT_FIELDS_MISSING';
      end if;
      v_policy_effect := 'PROVENANCE_ONLY';
    when 'predicate_superseded' then
      if p_supersedes_event_id is null
        or p_reason is null
        or not p_structured_surface
        or p_free_text_only
        or not (
          (
            p_producer_kind = 'DETERMINISTIC_PARSER'
            and p_actor_kind = 'DETERMINISTIC'
          )
          or (p_producer_kind = 'USER' and p_actor_kind = 'USER')
        )
        or not exists (
          select 1
          from public.portfolio_mandate_predicate_authority_event_a1 as prior
          where prior.predicate_authority_event_id = p_supersedes_event_id
            and prior.mandate_version_id = p_mandate_version_id
            and prior.predicate_id = p_predicate_id
            and prior.event_type = 'PREDICATE_FULFILLED'
            and prior.published_at < p_published_at
        )
      then
        raise exception 'predicate correction must supersede an authority event'
          using errcode = '23514', detail = 'SUPERSEDING_EVENT_REQUIRED';
      end if;
      v_policy_effect := 'REVIEW_ONLY';
    else
      raise exception 'predicate authority event type is unsupported'
        using errcode = '23514', detail = 'PREDICATE_EVENT_UNSUPPORTED';
  end case;

  insert into public.portfolio_mandate_predicate_authority_event_a1 (
    predicate_authority_event_id,
    command_id,
    mandate_version_id,
    predicate_id,
    event_type,
    producer_kind,
    actor_kind,
    policy_effect,
    source_id,
    evidence_seal_id,
    source_span,
    observed_metric,
    observed_value,
    unit,
    period,
    parser_version,
    predicate_schema_version,
    actor_id,
    reason,
    structured_surface,
    free_text_only,
    issue_code,
    supersedes_event_id,
    published_at
  ) values (
    p_predicate_authority_event_id,
    p_command_id,
    p_mandate_version_id,
    p_predicate_id,
    v_event_type,
    p_producer_kind,
    p_actor_kind,
    v_policy_effect,
    p_source_id,
    p_evidence_seal_id,
    p_source_span,
    p_observed_metric,
    p_observed_value,
    p_unit,
    p_period,
    p_parser_version,
    p_predicate_schema_version,
    p_actor_id,
    p_reason,
    p_structured_surface,
    p_free_text_only,
    v_issue_code,
    p_supersedes_event_id,
    p_published_at
  );

  return query
  select
    p_predicate_authority_event_id,
    v_event_type,
    v_policy_effect,
    'RECORDED'::text;
end;
$$;

create or replace function public.submit_predicate_candidate_a1(
  p_command_id uuid,
  p_predicate_authority_event_id uuid,
  p_mandate_version_id uuid,
  p_predicate_id uuid,
  p_source_id uuid,
  p_evidence_seal_id uuid,
  p_source_span text,
  p_predicate_schema_version text,
  p_reason text,
  p_structured_surface boolean,
  p_free_text_only boolean,
  p_published_at timestamptz
)
returns table (
  predicate_authority_event_id uuid,
  stored_event_type text,
  policy_effect text,
  result_status text
)
language sql
security definer
set search_path = pg_catalog, public
as $$
  select *
  from public.record_predicate_authority_a1(
    p_command_id,
    p_predicate_authority_event_id,
    p_mandate_version_id,
    p_predicate_id,
    'PREDICATE_CANDIDATE',
    'AI',
    'RESEARCH_ADAPTER',
    p_source_id,
    p_evidence_seal_id,
    p_source_span,
    null,
    null,
    null,
    null,
    null,
    p_predicate_schema_version,
    null,
    p_reason,
    p_structured_surface,
    p_free_text_only,
    null,
    p_published_at
  );
$$;

-- A failed command relies on PostgreSQL transaction rollback. Do not catch and
-- continue after a domain, journal, slice, or projection write fails.
create or replace function public.activate_mandate_version_a1(
  p_command_id uuid,
  p_activation_event_id uuid,
  p_mandate_id uuid,
  p_draft_mandate_version_id uuid,
  p_expected_mandate_version_id uuid,
  p_broker_snapshot_version bigint,
  p_allocation_version bigint
)
returns table (
  activation_event_id uuid,
  mandate_version_id uuid,
  result_status text
)
language plpgsql
security definer
set search_path = pg_catalog, public, extensions
as $$
declare
  v_existing public.portfolio_mandate_activation_event_a1%rowtype;
  v_mandate public.portfolio_mandate_a1%rowtype;
  v_active_version_id uuid;
  v_draft public.portfolio_mandate_version_a1%rowtype;
  v_source_allocation public.portfolio_mandate_allocation_a1%rowtype;
  v_target_allocation_id uuid := extensions.gen_random_uuid();
  v_target_allocation_version bigint;
  v_source_quantity numeric;
  v_target_quantity numeric;
  v_now timestamptz := clock_timestamp();
  v_actor_id uuid := auth.uid();
  v_request_claims text := nullif(
    current_setting('request.jwt.claims', true),
    ''
  );
  v_request_role text := coalesce(
    nullif(current_setting('request.jwt.claim.role', true), ''),
    case when v_request_claims is null
      then null
      else v_request_claims::jsonb ->> 'role'
    end
  );
begin
  if v_request_role <> 'authenticated' or v_actor_id is null then
    raise exception 'mandate activation requires an authenticated user'
      using errcode = '42501', detail = 'AUTHENTICATED_USER_REQUIRED';
  end if;

  select event.*
  into v_existing
  from public.portfolio_mandate_activation_event_a1 as event
  where event.command_id = p_command_id
  for update;
  if found then
    if v_existing.activation_event_id <> p_activation_event_id
      or v_existing.mandate_id <> p_mandate_id
      or v_existing.prior_mandate_version_id <> p_expected_mandate_version_id
      or v_existing.activated_mandate_version_id <> p_draft_mandate_version_id
      or v_existing.broker_snapshot_version <> p_broker_snapshot_version
      or v_existing.allocation_version <> p_allocation_version
      or v_existing.actor_kind <> 'USER'
      or v_existing.actor_id <> v_actor_id
    then
      raise exception 'activation command idempotency conflict'
        using errcode = '23505', detail = 'IDEMPOTENCY_CONFLICT';
    end if;
    return query
    select
      v_existing.activation_event_id,
      v_existing.activated_mandate_version_id,
      'ALREADY_ACTIVATED'::text;
    return;
  end if;

  select mandate.*
  into v_mandate
  from public.portfolio_mandate_a1 as mandate
  where mandate.mandate_id = p_mandate_id
  for update;
  if v_mandate.mandate_id is null then
    raise exception 'mandate does not exist'
      using errcode = '23503', detail = 'MANDATE_NOT_FOUND';
  end if;
  if v_mandate.owner_actor_id <> v_actor_id then
    raise exception 'activation actor does not own mandate'
      using errcode = '42501', detail = 'ACTOR_NOT_AUTHORIZED';
  end if;
  select version.mandate_version_id
  into v_active_version_id
  from public.portfolio_mandate_version_a1 as version
  where version.mandate_id = p_mandate_id
    and version.classification_state = 'ACTIVE'
    and version.approval_state = 'APPROVED'
    and version.effective_to is null
  for update;
  if v_active_version_id is distinct from p_expected_mandate_version_id then
    raise exception 'expected mandate version is stale'
      using errcode = '40001', detail = 'STALE_MANDATE_VERSION';
  end if;

  select version.*
  into v_draft
  from public.portfolio_mandate_version_a1 as version
  where version.mandate_version_id = p_draft_mandate_version_id
    and version.mandate_id = p_mandate_id
  for update;
  if v_draft.mandate_version_id is null
    or v_draft.classification_state <> 'UNCLASSIFIED'
    or v_draft.approval_state not in ('DRAFT', 'NEEDS_REAPPROVAL')
    or v_draft.proposed_horizon is null
    or v_draft.thesis is null
    or btrim(v_draft.thesis) = ''
    or coalesce(array_length(v_draft.invalidation_conditions, 1), 0) = 0
  then
    raise exception 'draft mandate version is incomplete'
      using errcode = '23514', detail = 'INCOMPLETE_MANDATE_DRAFT';
  end if;
  if v_draft.supersedes_version_id is distinct from p_expected_mandate_version_id then
    raise exception 'draft does not supersede the exact expected mandate version'
      using errcode = '23514', detail = 'DRAFT_LINEAGE_MISMATCH';
  end if;

  select allocation.*
  into v_source_allocation
  from public.portfolio_mandate_allocation_a1 as allocation
  where allocation.broker_position_id = v_mandate.broker_position_id
    and allocation.active
  for update;
  if v_source_allocation.allocation_id is null
    or v_source_allocation.allocation_version <> p_allocation_version
  then
    raise exception 'active allocation changed before activation'
      using errcode = '40001', detail = 'STALE_ALLOCATION_VERSION';
  end if;
  if v_source_allocation.snapshot_version <> p_broker_snapshot_version
    or exists (
      select 1
      from public.portfolio_mandate_broker_snapshot_a1 as newer
      where newer.broker_position_id = v_mandate.broker_position_id
        and newer.snapshot_version > p_broker_snapshot_version
    )
  then
    raise exception 'broker snapshot advanced before activation'
      using errcode = '40001', detail = 'SNAPSHOT_RACE_REQUIRES_REBASE';
  end if;
  if not exists (
    select 1
    from public.portfolio_mandate_position_slice_a1 as source_slice
    where source_slice.allocation_id = v_source_allocation.allocation_id
      and source_slice.mandate_version_id = p_expected_mandate_version_id
      and source_slice.classification_state = 'ACTIVE'
      and source_slice.decision_eligible
  ) then
    raise exception 'no active slice is bound to the expected mandate version'
      using errcode = '23514', detail = 'ACTIVATION_EXPECTED_SLICE_MISSING';
  end if;

  v_target_allocation_version := v_source_allocation.allocation_version + 1;
  insert into public.portfolio_mandate_allocation_a1 (
    allocation_id,
    broker_position_id,
    allocation_version,
    snapshot_version,
    active,
    decision_eligible,
    closed_at
  ) values (
    v_target_allocation_id,
    v_source_allocation.broker_position_id,
    v_target_allocation_version,
    v_source_allocation.snapshot_version,
    false,
    false,
    v_now
  );
  insert into public.portfolio_mandate_position_slice_a1 (
    slice_id,
    allocation_id,
    source_slice_id,
    mandate_version_id,
    quantity,
    currency,
    classification_state,
    decision_eligible
  )
  select
    extensions.gen_random_uuid(),
    v_target_allocation_id,
    source_slice.slice_id,
    case
      when source_slice.mandate_version_id = p_expected_mandate_version_id
        then p_draft_mandate_version_id
      else source_slice.mandate_version_id
    end,
    source_slice.quantity,
    source_slice.currency,
    source_slice.classification_state,
    source_slice.decision_eligible
  from public.portfolio_mandate_position_slice_a1 as source_slice
  where source_slice.allocation_id = v_source_allocation.allocation_id;

  select coalesce(sum(source_slice.quantity), 0)
  into v_source_quantity
  from public.portfolio_mandate_position_slice_a1 as source_slice
  where source_slice.allocation_id = v_source_allocation.allocation_id;
  select coalesce(sum(target_slice.quantity), 0)
  into v_target_quantity
  from public.portfolio_mandate_position_slice_a1 as target_slice
  where target_slice.allocation_id = v_target_allocation_id;
  if v_source_quantity <> v_target_quantity then
    raise exception 'slice rebind quantity mismatch'
      using errcode = '23514', detail = 'ACTIVATION_SLICE_REBIND_FAILED';
  end if;

  update public.portfolio_mandate_allocation_a1 as allocation
  set active = false, closed_at = v_now
  where allocation.allocation_id = v_source_allocation.allocation_id;
  update public.portfolio_mandate_allocation_a1 as allocation
  set
    active = true,
    decision_eligible = v_source_allocation.decision_eligible,
    closed_at = null
  where allocation.allocation_id = v_target_allocation_id;
  update public.portfolio_mandate_version_a1 as version
  set effective_to = v_now
  where version.mandate_version_id = v_active_version_id;
  update public.portfolio_mandate_version_a1 as version
  set
    classification_state = 'ACTIVE',
    horizon = version.proposed_horizon,
    proposed_horizon = null,
    approval_state = 'APPROVED',
    approved_by_kind = 'USER',
    approved_at = v_now,
    effective_from = v_now
  where version.mandate_version_id = p_draft_mandate_version_id;

  insert into public.portfolio_mandate_journal_event_a1 (
    journal_event_id,
    command_id,
    aggregate_id,
    aggregate_version_id,
    event_type,
    actor_kind,
    event_payload,
    published_at
  ) values (
    p_activation_event_id,
    p_command_id,
    p_mandate_id,
    p_draft_mandate_version_id,
    'MANDATE_VERSION_ACTIVATED',
    'USER',
    jsonb_build_object(
      'prior_mandate_version_id', p_expected_mandate_version_id,
      'target_allocation_version', v_target_allocation_version,
      'broker_snapshot_version', p_broker_snapshot_version,
      'actor_id', v_actor_id
    ),
    v_now
  );
  insert into public.portfolio_mandate_journal_event_a1 (
    journal_event_id,
    command_id,
    aggregate_id,
    aggregate_version_id,
    event_type,
    actor_kind,
    event_payload,
    published_at
  )
  select
    extensions.gen_random_uuid(),
    extensions.gen_random_uuid(),
    p_mandate_id,
    p_expected_mandate_version_id,
    'DECISION_SUPERSEDED',
    'USER',
    jsonb_build_object(
      'decision_id', projection.decision_id,
      'activated_mandate_version_id', p_draft_mandate_version_id
    ),
    v_now
  from public.portfolio_mandate_decision_projection_a1 as projection
  where projection.mandate_version_id = p_expected_mandate_version_id
    and projection.projection_status = 'ACTIVE';
  update public.portfolio_mandate_decision_projection_a1 as projection
  set
    projection_status = 'SUPERSEDED',
    eligible = false,
    superseded_at = v_now
  where projection.mandate_version_id = p_expected_mandate_version_id
    and projection.projection_status = 'ACTIVE';
  insert into public.portfolio_mandate_activation_event_a1 (
    activation_event_id,
    command_id,
    mandate_id,
    prior_mandate_version_id,
    activated_mandate_version_id,
    broker_snapshot_version,
    allocation_version,
    target_allocation_version,
    actor_kind,
    actor_id
  ) values (
    p_activation_event_id,
    p_command_id,
    p_mandate_id,
    v_active_version_id,
    p_draft_mandate_version_id,
    p_broker_snapshot_version,
    p_allocation_version,
    v_target_allocation_version,
    'USER',
    v_actor_id
  );

  return query
  select p_activation_event_id, p_draft_mandate_version_id, 'ACTIVATED'::text;
end;
$$;

alter table public.portfolio_mandate_issuer_a1 enable row level security;
alter table public.portfolio_mandate_issuer_a1 force row level security;
alter table public.portfolio_mandate_issuer_identifier_a1 enable row level security;
alter table public.portfolio_mandate_issuer_identifier_a1 force row level security;
alter table public.portfolio_mandate_instrument_a1 enable row level security;
alter table public.portfolio_mandate_instrument_a1 force row level security;
alter table public.portfolio_mandate_listing_alias_a1 enable row level security;
alter table public.portfolio_mandate_listing_alias_a1 force row level security;
alter table public.portfolio_mandate_issuer_evidence_policy_a1 enable row level security;
alter table public.portfolio_mandate_issuer_evidence_policy_a1 force row level security;
alter table public.portfolio_mandate_evidence_seal_a1 enable row level security;
alter table public.portfolio_mandate_evidence_seal_a1 force row level security;
alter table public.portfolio_mandate_a1 enable row level security;
alter table public.portfolio_mandate_a1 force row level security;
alter table public.portfolio_mandate_version_a1 enable row level security;
alter table public.portfolio_mandate_version_a1 force row level security;
alter table public.portfolio_mandate_activation_event_a1 enable row level security;
alter table public.portfolio_mandate_activation_event_a1 force row level security;
alter table public.portfolio_mandate_broker_position_a1 enable row level security;
alter table public.portfolio_mandate_broker_position_a1 force row level security;
alter table public.portfolio_mandate_broker_snapshot_a1 enable row level security;
alter table public.portfolio_mandate_broker_snapshot_a1 force row level security;
alter table public.portfolio_mandate_allocation_a1 enable row level security;
alter table public.portfolio_mandate_allocation_a1 force row level security;
alter table public.portfolio_mandate_position_slice_a1 enable row level security;
alter table public.portfolio_mandate_position_slice_a1 force row level security;
alter table public.portfolio_mandate_rebase_evidence_a1 enable row level security;
alter table public.portfolio_mandate_rebase_evidence_a1 force row level security;
alter table public.portfolio_mandate_slice_rebase_event_a1 enable row level security;
alter table public.portfolio_mandate_slice_rebase_event_a1 force row level security;
alter table public.portfolio_mandate_issuer_lineage_event_a1 enable row level security;
alter table public.portfolio_mandate_issuer_lineage_event_a1 force row level security;
alter table public.portfolio_mandate_journal_event_a1 enable row level security;
alter table public.portfolio_mandate_journal_event_a1 force row level security;
alter table public.portfolio_mandate_decision_projection_a1 enable row level security;
alter table public.portfolio_mandate_decision_projection_a1 force row level security;
alter table public.portfolio_mandate_predicate_definition_a1 enable row level security;
alter table public.portfolio_mandate_predicate_definition_a1 force row level security;
alter table public.portfolio_mandate_predicate_authority_event_a1 enable row level security;
alter table public.portfolio_mandate_predicate_authority_event_a1 force row level security;

grant usage on schema public to service_role;
grant usage on schema public to authenticated;
grant usage on schema public to portfolio_mandate_candidate_submitter_a1;

revoke all on table public.portfolio_mandate_issuer_a1 from service_role;
revoke all on table public.portfolio_mandate_issuer_identifier_a1 from service_role;
revoke all on table public.portfolio_mandate_instrument_a1 from service_role;
revoke all on table public.portfolio_mandate_listing_alias_a1 from service_role;
revoke all on table public.portfolio_mandate_issuer_evidence_policy_a1 from service_role;
revoke all on table public.portfolio_mandate_evidence_seal_a1 from service_role;
revoke all on table public.portfolio_mandate_a1 from service_role;
revoke all on table public.portfolio_mandate_version_a1 from service_role;
revoke all on table public.portfolio_mandate_activation_event_a1 from service_role;
revoke all on table public.portfolio_mandate_broker_position_a1 from service_role;
revoke all on table public.portfolio_mandate_broker_snapshot_a1 from service_role;
revoke all on table public.portfolio_mandate_allocation_a1 from service_role;
revoke all on table public.portfolio_mandate_position_slice_a1 from service_role;
revoke all on table public.portfolio_mandate_rebase_evidence_a1 from service_role;
revoke all on table public.portfolio_mandate_slice_rebase_event_a1 from service_role;
revoke all on table public.portfolio_mandate_issuer_lineage_event_a1 from service_role;
revoke all on table public.portfolio_mandate_journal_event_a1 from service_role;
revoke all on table public.portfolio_mandate_decision_projection_a1 from service_role;
revoke all on table public.portfolio_mandate_predicate_definition_a1 from service_role;
revoke all on table public.portfolio_mandate_predicate_authority_event_a1 from service_role;

revoke all on table public.portfolio_mandate_issuer_a1 from public;
revoke all on table public.portfolio_mandate_issuer_a1 from anon;
revoke all on table public.portfolio_mandate_issuer_a1 from authenticated;
revoke all on table public.portfolio_mandate_issuer_identifier_a1 from public;
revoke all on table public.portfolio_mandate_issuer_identifier_a1 from anon;
revoke all on table public.portfolio_mandate_issuer_identifier_a1 from authenticated;
revoke all on table public.portfolio_mandate_instrument_a1 from public;
revoke all on table public.portfolio_mandate_instrument_a1 from anon;
revoke all on table public.portfolio_mandate_instrument_a1 from authenticated;
revoke all on table public.portfolio_mandate_listing_alias_a1 from public;
revoke all on table public.portfolio_mandate_listing_alias_a1 from anon;
revoke all on table public.portfolio_mandate_listing_alias_a1 from authenticated;
revoke all on table public.portfolio_mandate_issuer_evidence_policy_a1 from public;
revoke all on table public.portfolio_mandate_issuer_evidence_policy_a1 from anon;
revoke all on table public.portfolio_mandate_issuer_evidence_policy_a1 from authenticated;
revoke all on table public.portfolio_mandate_evidence_seal_a1 from public;
revoke all on table public.portfolio_mandate_evidence_seal_a1 from anon;
revoke all on table public.portfolio_mandate_evidence_seal_a1 from authenticated;
revoke all on table public.portfolio_mandate_a1 from public;
revoke all on table public.portfolio_mandate_a1 from anon;
revoke all on table public.portfolio_mandate_a1 from authenticated;
revoke all on table public.portfolio_mandate_version_a1 from public;
revoke all on table public.portfolio_mandate_version_a1 from anon;
revoke all on table public.portfolio_mandate_version_a1 from authenticated;
revoke all on table public.portfolio_mandate_activation_event_a1 from public;
revoke all on table public.portfolio_mandate_activation_event_a1 from anon;
revoke all on table public.portfolio_mandate_activation_event_a1 from authenticated;
revoke all on table public.portfolio_mandate_broker_position_a1 from public;
revoke all on table public.portfolio_mandate_broker_position_a1 from anon;
revoke all on table public.portfolio_mandate_broker_position_a1 from authenticated;
revoke all on table public.portfolio_mandate_broker_snapshot_a1 from public;
revoke all on table public.portfolio_mandate_broker_snapshot_a1 from anon;
revoke all on table public.portfolio_mandate_broker_snapshot_a1 from authenticated;
revoke all on table public.portfolio_mandate_allocation_a1 from public;
revoke all on table public.portfolio_mandate_allocation_a1 from anon;
revoke all on table public.portfolio_mandate_allocation_a1 from authenticated;
revoke all on table public.portfolio_mandate_position_slice_a1 from public;
revoke all on table public.portfolio_mandate_position_slice_a1 from anon;
revoke all on table public.portfolio_mandate_position_slice_a1 from authenticated;
revoke all on table public.portfolio_mandate_rebase_evidence_a1 from public;
revoke all on table public.portfolio_mandate_rebase_evidence_a1 from anon;
revoke all on table public.portfolio_mandate_rebase_evidence_a1 from authenticated;
revoke all on table public.portfolio_mandate_slice_rebase_event_a1 from public;
revoke all on table public.portfolio_mandate_slice_rebase_event_a1 from anon;
revoke all on table public.portfolio_mandate_slice_rebase_event_a1 from authenticated;
revoke all on table public.portfolio_mandate_issuer_lineage_event_a1 from public;
revoke all on table public.portfolio_mandate_issuer_lineage_event_a1 from anon;
revoke all on table public.portfolio_mandate_issuer_lineage_event_a1 from authenticated;
revoke all on table public.portfolio_mandate_journal_event_a1 from public;
revoke all on table public.portfolio_mandate_journal_event_a1 from anon;
revoke all on table public.portfolio_mandate_journal_event_a1 from authenticated;
revoke all on table public.portfolio_mandate_decision_projection_a1 from public;
revoke all on table public.portfolio_mandate_decision_projection_a1 from anon;
revoke all on table public.portfolio_mandate_decision_projection_a1 from authenticated;
revoke all on table public.portfolio_mandate_predicate_definition_a1 from public;
revoke all on table public.portfolio_mandate_predicate_definition_a1 from anon;
revoke all on table public.portfolio_mandate_predicate_definition_a1 from authenticated;
revoke all on table public.portfolio_mandate_predicate_authority_event_a1 from public;
revoke all on table public.portfolio_mandate_predicate_authority_event_a1 from anon;
revoke all on table public.portfolio_mandate_predicate_authority_event_a1 from authenticated;

grant select on table public.portfolio_mandate_issuer_a1 to service_role;
grant select on table public.portfolio_mandate_issuer_identifier_a1 to service_role;
grant select on table public.portfolio_mandate_instrument_a1 to service_role;
grant select on table public.portfolio_mandate_listing_alias_a1 to service_role;
grant select on table public.portfolio_mandate_issuer_evidence_policy_a1 to service_role;
grant select on table public.portfolio_mandate_evidence_seal_a1 to service_role;
grant select on table public.portfolio_mandate_a1 to service_role;
grant select on table public.portfolio_mandate_version_a1 to service_role;
grant select on table public.portfolio_mandate_activation_event_a1 to service_role;
grant select on table public.portfolio_mandate_broker_position_a1 to service_role;
grant select on table public.portfolio_mandate_broker_snapshot_a1 to service_role;
grant select on table public.portfolio_mandate_allocation_a1 to service_role;
grant select on table public.portfolio_mandate_position_slice_a1 to service_role;
grant select on table public.portfolio_mandate_rebase_evidence_a1 to service_role;
grant select on table public.portfolio_mandate_slice_rebase_event_a1 to service_role;
grant select on table public.portfolio_mandate_issuer_lineage_event_a1 to service_role;
grant select on table public.portfolio_mandate_journal_event_a1 to service_role;
grant select on table public.portfolio_mandate_decision_projection_a1 to service_role;
grant select on table public.portfolio_mandate_predicate_definition_a1 to service_role;
grant select on table public.portfolio_mandate_predicate_authority_event_a1 to service_role;

revoke all on function public.seal_evidence_identity_a1(uuid, uuid, uuid, uuid, text, timestamptz, text, text, text, text, text, timestamptz, text) from public;
revoke all on function public.seal_evidence_identity_a1(uuid, uuid, uuid, uuid, text, timestamptz, text, text, text, text, text, timestamptz, text) from anon;
revoke all on function public.seal_evidence_identity_a1(uuid, uuid, uuid, uuid, text, timestamptz, text, text, text, text, text, timestamptz, text) from authenticated;
grant execute on function public.seal_evidence_identity_a1(uuid, uuid, uuid, uuid, text, timestamptz, text, text, text, text, text, timestamptz, text) to service_role;
revoke all on function public.activate_mandate_version_a1(uuid, uuid, uuid, uuid, uuid, bigint, bigint) from public;
revoke all on function public.activate_mandate_version_a1(uuid, uuid, uuid, uuid, uuid, bigint, bigint) from anon;
revoke all on function public.activate_mandate_version_a1(uuid, uuid, uuid, uuid, uuid, bigint, bigint) from service_role;
grant execute on function public.activate_mandate_version_a1(uuid, uuid, uuid, uuid, uuid, bigint, bigint) to authenticated;
revoke all on function public.rebase_position_slices_a1(uuid, uuid, uuid, uuid, bigint, bigint, numeric, text, text, uuid, numeric, bigint, text) from public;
revoke all on function public.rebase_position_slices_a1(uuid, uuid, uuid, uuid, bigint, bigint, numeric, text, text, uuid, numeric, bigint, text) from anon;
revoke all on function public.rebase_position_slices_a1(uuid, uuid, uuid, uuid, bigint, bigint, numeric, text, text, uuid, numeric, bigint, text) from authenticated;
grant execute on function public.rebase_position_slices_a1(uuid, uuid, uuid, uuid, bigint, bigint, numeric, text, text, uuid, numeric, bigint, text) to service_role;
revoke all on function public.reject_portfolio_mandate_event_mutation_a1() from public;
revoke all on function public.reject_portfolio_mandate_event_mutation_a1() from anon;
revoke all on function public.reject_portfolio_mandate_event_mutation_a1() from authenticated;
revoke all on function public.record_predicate_authority_a1(uuid, uuid, uuid, uuid, text, text, text, uuid, uuid, text, text, numeric, text, text, text, text, text, text, boolean, boolean, uuid, timestamptz) from public;
revoke all on function public.record_predicate_authority_a1(uuid, uuid, uuid, uuid, text, text, text, uuid, uuid, text, text, numeric, text, text, text, text, text, text, boolean, boolean, uuid, timestamptz) from anon;
revoke all on function public.record_predicate_authority_a1(uuid, uuid, uuid, uuid, text, text, text, uuid, uuid, text, text, numeric, text, text, text, text, text, text, boolean, boolean, uuid, timestamptz) from authenticated;
grant execute on function public.record_predicate_authority_a1(uuid, uuid, uuid, uuid, text, text, text, uuid, uuid, text, text, numeric, text, text, text, text, text, text, boolean, boolean, uuid, timestamptz) to service_role;
grant execute on function public.record_predicate_authority_a1(uuid, uuid, uuid, uuid, text, text, text, uuid, uuid, text, text, numeric, text, text, text, text, text, text, boolean, boolean, uuid, timestamptz) to authenticated;
revoke all on function public.submit_predicate_candidate_a1(uuid, uuid, uuid, uuid, uuid, uuid, text, text, text, boolean, boolean, timestamptz) from public;
revoke all on function public.submit_predicate_candidate_a1(uuid, uuid, uuid, uuid, uuid, uuid, text, text, text, boolean, boolean, timestamptz) from anon;
revoke all on function public.submit_predicate_candidate_a1(uuid, uuid, uuid, uuid, uuid, uuid, text, text, text, boolean, boolean, timestamptz) from authenticated;
grant execute on function public.submit_predicate_candidate_a1(uuid, uuid, uuid, uuid, uuid, uuid, text, text, text, boolean, boolean, timestamptz) to portfolio_mandate_candidate_submitter_a1;
