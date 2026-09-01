from __future__ import annotations

import re
from pathlib import Path

_MIGRATIONS = Path("supabase/migrations")


def _sql() -> str:
    matches = sorted(_MIGRATIONS.glob("*_create_portfolio_mandate_a1.sql"))
    assert len(matches) == 1, "missing create-only Portfolio Mandate A1 migration"
    return re.sub(r"\s+", " ", matches[0].read_text(encoding="utf-8").lower())


def _raw_sql() -> str:
    matches = sorted(_MIGRATIONS.glob("*_create_portfolio_mandate_a1.sql"))
    assert len(matches) == 1, "missing create-only Portfolio Mandate A1 migration"
    return matches[0].read_text(encoding="utf-8").lower()


def test_a1_migration_is_create_only_and_does_not_touch_legacy_writers() -> None:
    sql = _sql()

    for forbidden in (
        "drop table",
        "truncate ",
        "alter table public.holdings",
        "update public.holdings",
        "delete from public.holdings",
        "insert into public.holdings",
        "alter table public.report_index",
        "update public.report_index",
        "delete from public.report_index",
    ):
        assert forbidden not in sql


def test_rn1_c3_003_overlapping_alias_window_is_rejected() -> None:
    sql = _sql()

    assert "create table public.portfolio_mandate_listing_alias_a1" in sql
    assert "portfolio_mandate_listing_alias_a1_no_overlap" in sql
    assert "exclude using gist" in sql
    assert "tstzrange(valid_from, valid_to, '[)') with &&" in sql


def test_rn1_c3_009_alias_is_not_a_binding_key() -> None:
    sql = _sql()

    assert "create table public.portfolio_mandate_issuer_a1" in sql
    assert "create table public.portfolio_mandate_instrument_a1" in sql
    assert "instrument_id uuid not null" in sql
    assert "references public.portfolio_mandate_instrument_a1(instrument_id)" in sql
    assert "references public.portfolio_mandate_listing_alias_a1(ticker)" not in sql
    assert "ticker text references" not in sql


def test_rn1_c3_010_source_cannot_be_rebound_to_other_instrument() -> None:
    sql = _sql()

    assert "create table public.portfolio_mandate_evidence_seal_a1" in sql
    assert "portfolio_mandate_evidence_seal_a1_source_uidx" in sql
    assert "create or replace function public.seal_evidence_identity_a1" in sql
    assert "evidence source is already sealed to another scope" in sql
    seal = sql.split(
        "create or replace function public.seal_evidence_identity_a1", maxsplit=1
    )[1]
    lock_at = seal.index("pg_advisory_xact_lock")
    conflict_at = seal.index("evidence source is already sealed to another scope")
    assert lock_at < conflict_at


def test_identity_tables_and_rpc_are_service_role_only_with_forced_rls() -> None:
    sql = _sql()
    tables = (
        "portfolio_mandate_issuer_a1",
        "portfolio_mandate_instrument_a1",
        "portfolio_mandate_listing_alias_a1",
        "portfolio_mandate_evidence_seal_a1",
    )
    for table in tables:
        assert f"alter table public.{table} enable row level security" in sql
        assert f"alter table public.{table} force row level security" in sql
        assert f"revoke all on table public.{table} from public" in sql
        assert f"revoke all on table public.{table} from anon" in sql
        assert f"revoke all on table public.{table} from authenticated" in sql

    signature = (
        "seal_evidence_identity_a1(uuid, uuid, uuid, uuid, text, timestamptz, "
        "text, text, text, text, text, timestamptz, text)"
    )
    assert f"revoke all on function public.{signature} from public" in sql
    assert f"revoke all on function public.{signature} from anon" in sql
    assert f"revoke all on function public.{signature} from authenticated" in sql
    assert f"grant execute on function public.{signature} to service_role" in sql
    assert "grant usage on schema public to service_role" in sql
    assert "security definer" in sql
    assert "set search_path = pg_catalog, public" in sql
    assert (
        "grant insert on table public.portfolio_mandate_evidence_seal_a1 "
        "to service_role"
    ) not in sql


def test_every_a1_table_revokes_ambient_service_role_dml_before_read_grant() -> None:
    sql = _sql()
    tables = set(
        re.findall(r"create table public\.(portfolio_mandate_[a-z0-9_]+_a1)", sql)
    )

    assert tables
    for table in tables:
        revoke = f"revoke all on table public.{table} from service_role"
        grant = f"grant select on table public.{table} to service_role"
        assert revoke in sql
        assert grant in sql
        assert sql.index(revoke) < sql.index(grant)


def test_persisted_decimal_scales_match_public_contract() -> None:
    sql = _sql()

    assert "quantity >= 0 and scale(quantity) <= 6" in sql
    assert "scale(corporate_action_ratio) <= 8" in sql
    assert "target_quantity >= 0 and scale(target_quantity) <= 6" in sql
    assert "and scale(threshold_value) <= 6" in sql
    assert "and scale(observed_value) <= 6" in sql
    assert sql.count("'nan'::numeric") >= 5
    assert sql.count("'infinity'::numeric") >= 5
    assert sql.count("'-infinity'::numeric") >= 5


def test_rn1_c2_005_incomplete_draft_cannot_activate() -> None:
    sql = _sql()

    assert "create table public.portfolio_mandate_a1" in sql
    assert "create table public.portfolio_mandate_version_a1" in sql
    assert "portfolio_mandate_version_a1_state_check" in sql
    assert "proposed_horizon in ('swing', 'long_term')" in sql
    assert "coalesce(array_length(invalidation_conditions, 1), 0) > 0" in sql


def test_rn1_c2_009_one_active_approved_version_constraint() -> None:
    sql = _sql()

    assert "portfolio_mandate_version_a1_one_active_uidx" in sql
    assert "where classification_state = 'active'" in sql
    assert "and approval_state = 'approved'" in sql
    assert "and effective_to is null" in sql


def test_rn1_g003_actor_and_expected_version_are_transactional() -> None:
    sql = _sql()
    activation = sql.split(
        "create or replace function public.activate_mandate_version_a1",
        maxsplit=1,
    )[1]

    assert "create or replace function public.activate_mandate_version_a1" in sql
    assert "where mandate.mandate_id = p_mandate_id for update" in sql
    assert "v_request_role <> 'authenticated' or v_actor_id is null" in activation
    assert activation.index(
        "v_request_role <> 'authenticated' or v_actor_id is null"
    ) < activation.index("from public.portfolio_mandate_activation_event_a1")
    assert "v_active_version_id is distinct from p_expected_mandate_version_id" in sql
    assert "STALE_MANDATE_VERSION".lower() in sql


def test_rn1_c2_010_activation_is_idempotent() -> None:
    sql = _sql()

    assert "create table public.portfolio_mandate_activation_event_a1" in sql
    assert "command_id uuid not null unique" in sql
    assert "v_existing.activation_event_id <> p_activation_event_id" in sql
    assert "v_existing.prior_mandate_version_id <> p_expected_mandate_version_id" in sql
    assert "v_existing.broker_snapshot_version <> p_broker_snapshot_version" in sql
    assert "v_existing.allocation_version <> p_allocation_version" in sql
    assert "'already_activated'::text" in sql


def test_rn1_c1_001_zero_delta_copies_allocation() -> None:
    sql = _sql()
    assert "when 'zero_delta' then" in sql
    assert "source_slice.mandate_version_id" in sql


def test_rn1_c1_002_unique_buy_fill_updates_one_slice() -> None:
    sql = _sql()
    assert "when 'unique_buy' then" in sql
    assert "source_slice.slice_id = p_matched_slice_id" in sql


def test_rn1_c1_003_unresolved_buy_quarantines_delta_only() -> None:
    sql = _sql()
    branch = sql.split("when 'unresolved_buy' then", maxsplit=1)[1]
    branch = branch.split("when 'unique_sell' then", maxsplit=1)[0]
    assert "'unclassified'" in branch
    assert "v_delta" in branch
    assert "v_decision_eligible := false" in branch


def test_rn1_c1_004_unique_sell_fill_reduces_one_slice() -> None:
    sql = _sql()
    assert "when 'unique_sell' then" in sql
    assert "matched slice would become negative" in sql


def test_rn1_c1_005_ambiguous_sell_full_quarantine() -> None:
    sql = _sql()
    assert "when 'ambiguous_sell' then" in sql
    assert "'pending_allocation'" in sql


def test_rn1_c1_006_zero_position_closes_all_slices() -> None:
    sql = _sql()
    assert "when 'position_closed' then" in sql
    assert "p_target_quantity <> 0" in sql


def test_rn1_c1_007_verified_corporate_action_rebases_proportionally() -> None:
    sql = _sql()
    assert "when 'verified_corporate_action' then" in sql
    assert "p_corporate_action_ratio" in sql


def test_rn1_c1_008_ambiguous_corporate_action_blocks_run() -> None:
    sql = _sql()
    assert "when 'ambiguous_corporate_action' then" in sql
    assert "'corporate_action_ambiguous'" in sql


def test_rn1_c1_009_rebase_identity_is_idempotent() -> None:
    sql = _sql()
    assert "portfolio_mandate_slice_rebase_event_a1_identity_uidx" in sql
    assert "broker_position_id, target_snapshot_version" in sql
    assert "v_existing.rebase_cause <> upper(p_rebase_cause)" in sql
    assert "'already_rebased'::text" in sql


def test_rn1_c1_010_newer_watermark_rolls_back() -> None:
    sql = _sql()
    assert "newer broker snapshot exists" in sql
    assert "newer_snapshot_requires_retry" in sql


def test_rn1_c1_011_quantity_invariant_failure_rolls_back() -> None:
    sql = _sql()
    assert "quantity >= 0 and scale(quantity) <= 6" in sql
    assert "target slice quantity mismatch" in sql
    assert "slice_quantity_mismatch" in sql


def test_rn1_c1_012_static_shape_supports_one_winner_rebase_contract() -> None:
    sql = _sql()
    assert "for update" in sql
    assert "portfolio_mandate_allocation_a1_one_active_uidx" in sql
    assert "expected_allocation_version" in sql


def test_mandate_binds_to_a_broker_position_with_the_same_instrument() -> None:
    sql = _sql()

    assert "unique (broker_position_id, instrument_id)" in sql
    assert "foreign key (broker_position_id, instrument_id)" in sql
    assert (
        "references public.portfolio_mandate_broker_position_a1( "
        "broker_position_id, instrument_id )"
    ) in sql


def test_user_predicate_confirmation_requires_a_structured_surface() -> None:
    sql = _sql()

    branch = sql.split("when 'user_predicate_confirmed' then", maxsplit=1)[1]
    branch = branch.split("when 'predicate_candidate' then", maxsplit=1)[0]
    assert "not p_structured_surface" in branch
    assert "p_free_text_only" in branch


def test_rn1_g001_published_event_is_append_only() -> None:
    sql = _sql()
    assert "create table public.portfolio_mandate_journal_event_a1" in sql
    assert (
        "create or replace function public.reject_portfolio_mandate_event_mutation_a1"
        in sql
    )
    assert "published portfolio mandate events are append-only" in sql
    assert "before update or delete" in sql


def test_rn1_g002_event_rejects_missing_aggregate_version() -> None:
    sql = _sql()
    assert "aggregate_id uuid not null" in sql
    assert "aggregate_version_id uuid not null" in sql
    assert "references public.portfolio_mandate_version_a1(mandate_version_id)" in sql


def test_rn1_g004_failed_command_has_zero_partial_writes() -> None:
    sql = _sql()
    assert "failed command relies on postgresql transaction rollback" in sql
    assert "exception when" not in sql


def test_rn1_g005_research_adapter_has_no_domain_writer_capability() -> None:
    sql = _sql()
    assert "create role portfolio_mandate_candidate_submitter_a1" in sql
    assert "candidate_role_already_exists" in sql
    assert "must not pre-exist a1 migration" in sql
    assert (
        "grant usage on schema public to portfolio_mandate_candidate_submitter_a1"
        in sql
    )
    assert "create or replace function public.submit_predicate_candidate_a1" in sql
    assert "grant execute on function public.submit_predicate_candidate_a1" in sql
    assert "to portfolio_mandate_candidate_submitter_a1" in sql
    assert "grant execute on function public.record_predicate_authority_a1" in sql
    record_grant = sql.split(
        "grant execute on function public.record_predicate_authority_a1", maxsplit=1
    )[1].split(";", maxsplit=1)[0]
    assert "to service_role" in record_grant
    assert (
        "grant insert on table public.portfolio_mandate_a1 to service_role" not in sql
    )
    assert (
        "grant insert on table public.portfolio_mandate_predicate_authority_event_a1 "
        "to portfolio_mandate_candidate_submitter_a1"
    ) not in sql
    assert "to anon" not in sql


def test_predicate_authority_references_an_approved_exact_definition() -> None:
    sql = _sql()

    assert "create table public.portfolio_mandate_predicate_definition_a1" in sql
    assert "unique (predicate_id, mandate_version_id)" in sql
    assert "foreign key (predicate_id, mandate_version_id)" in sql


def test_predicate_fulfillment_evaluates_the_approved_typed_definition() -> None:
    sql = _sql()

    for definition_field in (
        "metric text not null",
        "comparison_operator text not null",
        "threshold_value numeric not null",
        "expected_unit text not null",
        "expected_period text not null",
    ):
        assert definition_field in sql
    assert "p_observed_value numeric" in sql
    assert "definition.comparison_operator" in sql
    assert "definition.threshold_value" in sql
    assert "p_observed_value" in sql
    assert "detail = 'predicate_not_fulfilled'" in sql


def test_predicate_authority_requires_exact_sealed_source_provenance() -> None:
    sql = _sql()

    assert "evidence_seal_id uuid not null" in sql
    assert (
        "references public.portfolio_mandate_evidence_seal_a1(evidence_seal_id)" in sql
    )
    assert "predicate source seal does not match the mandate instrument" in sql


def test_rebase_uses_persisted_verified_evidence_instead_of_caller_claims() -> None:
    sql = _sql()

    assert "create table public.portfolio_mandate_rebase_evidence_a1" in sql
    assert "p_rebase_evidence_id uuid" in sql
    assert "rebase evidence does not match the command" in sql
    assert "verification_state <> 'verified'" in sql


def test_predicate_correction_stays_on_exact_mandate_and_predicate() -> None:
    sql = _sql()

    assert "foreign key (supersedes_event_id, mandate_version_id, predicate_id)" in sql


def test_mandate_state_check_is_explicit_for_null_values() -> None:
    sql = _sql()

    assert "horizon is not null and horizon in ('swing', 'long_term')" in sql
    assert "coalesce(array_length(invalidation_conditions, 1), 0) > 0" in sql


def test_candidate_idempotency_compares_the_complete_authority_payload() -> None:
    sql = _sql()

    authority = sql.split(
        "create or replace function public.record_predicate_authority_a1", maxsplit=1
    )[1]
    idempotency = authority.split("if found then", maxsplit=1)[1].split(
        "return query", maxsplit=1
    )[0]
    assert (
        "v_existing.predicate_authority_event_id is distinct from "
        "p_predicate_authority_event_id"
    ) in idempotency
    assert "v_existing.event_type is distinct from v_event_type" in idempotency
    assert "v_existing.producer_kind is distinct from p_producer_kind" in idempotency
    assert "v_existing.actor_kind is distinct from p_actor_kind" in idempotency


def test_sql_table_elements_keep_references_attached_and_columns_separated() -> None:
    sql = _raw_sql()

    assert "supersedes_event_id uuid null,\n    references" not in sql
    assert "supersedes_event_id uuid null\n  published_at" not in sql


def test_evidence_seal_idempotency_compares_the_complete_command_payload() -> None:
    sql = _sql()
    seal = sql.split(
        "create or replace function public.seal_evidence_identity_a1", maxsplit=1
    )[1]
    idempotency = seal.split("if found then", maxsplit=1)[1].split(
        "return query", maxsplit=1
    )[0]

    for comparison in (
        "v_existing.evidence_seal_id is distinct from p_evidence_seal_id",
        "v_existing.source_id is distinct from p_source_id",
        "v_existing.instrument_id is distinct from p_instrument_id",
        "v_existing.registry_version is distinct from p_registry_version",
        "v_existing.source_event_time is distinct from p_source_event_time",
        "v_existing.source_identifier_scheme is distinct from p_source_identifier_scheme",
        "v_existing.source_identifier_value is distinct from p_source_identifier_value",
        "v_existing.evidence_scope is distinct from p_evidence_scope",
        "v_existing.exchange_mic is distinct from p_exchange_mic",
        "v_existing.ticker is distinct from p_ticker",
        "v_existing.sealed_at is distinct from p_sealed_at",
        "v_existing.actor_kind is distinct from p_actor_kind",
    ):
        assert comparison in idempotency


def test_predicate_review_paths_match_the_shared_authority_contract() -> None:
    sql = _sql()
    authority = sql.split(
        "create or replace function public.record_predicate_authority_a1", maxsplit=1
    )[1]

    assert "detail = 'unknown_parser_surface'" in authority
    assert "detail = 'free_text_review_required'" in authority
    correction = authority.split("when 'predicate_superseded' then", maxsplit=1)[1]
    correction = correction.split("else", maxsplit=1)[0]
    assert "p_reason is null" in correction
    assert "not p_structured_surface" in correction
    assert "p_free_text_only" in correction
    assert "p_actor_kind = 'deterministic'" in correction
    assert "p_actor_kind = 'user'" in correction
    assert "prior.event_type = 'predicate_fulfilled'" in correction
    assert "prior.published_at < p_published_at" in correction


def test_sql_authority_non_corrections_match_shared_validator_fields() -> None:
    sql = _sql()
    authority = sql.split(
        "create or replace function public.record_predicate_authority_a1", maxsplit=1
    )[1]

    assert "lower(p_event_type) <> 'predicate_superseded'" in authority
    assert "p_supersedes_event_id is not null" in authority
    provenance = authority.split("when 'provenance_validated' then", maxsplit=1)[1]
    provenance = provenance.split("when 'predicate_superseded' then", maxsplit=1)[0]
    assert "p_source_span is null" in provenance
    assert "not p_structured_surface" in provenance
    assert "detail = 'provenance_audit_fields_missing'" in provenance


def test_activation_appends_decision_superseding_events_before_projection_update() -> (
    None
):
    sql = _sql()
    activation = sql.split(
        "create or replace function public.activate_mandate_version_a1", maxsplit=1
    )[1]

    append_at = activation.index("'decision_superseded'")
    update_at = activation.index(
        "update public.portfolio_mandate_decision_projection_a1 as projection"
    )
    assert append_at < update_at


def test_rn1_c2_001_activation_commits_as_one_transaction() -> None:
    sql = _sql()
    activation = sql.rsplit(
        "create or replace function public.activate_mandate_version_a1", 1
    )[1]
    assert "portfolio_mandate_position_slice_a1" in activation
    assert "portfolio_mandate_journal_event_a1" in activation
    assert "portfolio_mandate_decision_projection_a1" in activation
    assert "mandate_version_activated" in activation


def test_rn1_c2_003_static_shape_locks_activation_for_one_winner_contract() -> None:
    sql = _sql()
    assert "where mandate.mandate_id = p_mandate_id for update" in sql
    assert "portfolio_mandate_version_a1_one_active_uidx" in sql


def test_activation_binds_the_actor_to_the_authenticated_request_identity() -> None:
    sql = _sql()
    activation = sql.split(
        "create or replace function public.activate_mandate_version_a1", maxsplit=1
    )[1]
    activation = activation.split("alter table", maxsplit=1)[0]

    assert "p_actor_kind text" not in activation
    assert "v_actor_id uuid := auth.uid()" in activation
    assert "v_request_role <> 'authenticated'" in activation
    assert "actor_id uuid not null" in sql
    assert "owner_actor_id uuid not null" in sql
    assert "v_mandate.owner_actor_id <> v_actor_id" in activation
    assert "grant execute on function public.activate_mandate_version_a1" in sql
    assert "to authenticated" in sql
    assert (
        "to service_role"
        not in sql.split(
            "grant execute on function public.activate_mandate_version_a1", maxsplit=1
        )[1].split(";", maxsplit=1)[0]
    )


def test_user_predicate_authority_requires_mandate_ownership() -> None:
    sql = _sql()
    function = sql.split(
        "create or replace function public.record_predicate_authority_a1",
        maxsplit=1,
    )[1].split("create or replace function", maxsplit=1)[0]

    assert "select mandate.owner_actor_id into v_owner_actor_id" in function
    assert "v_owner_actor_id is distinct from v_authenticated_actor_id" in function
    assert "detail = 'actor_not_authorized'" in function


def test_version_lineage_is_scoped_to_one_mandate_and_activation_expected_version() -> (
    None
):
    sql = _sql()
    activation = sql.split(
        "create or replace function public.activate_mandate_version_a1", maxsplit=1
    )[1]
    activation = activation.split("alter table", maxsplit=1)[0]

    assert "unique (mandate_id, mandate_version_id)" in sql
    assert "foreign key (mandate_id, supersedes_version_id)" in sql
    assert "references public.portfolio_mandate_version_a1(" in sql
    assert "mandate_id, mandate_version_id" in sql
    assert (
        "v_draft.supersedes_version_id is distinct from p_expected_mandate_version_id"
    ) in activation
    assert "detail = 'draft_lineage_mismatch'" in activation


def test_user_predicate_confirmation_binds_auth_uid_and_restricts_request_role() -> (
    None
):
    sql = _sql()
    authority = sql.split(
        "create or replace function public.record_predicate_authority_a1", maxsplit=1
    )[1]
    authority = authority.split(
        "create or replace function public.submit_predicate_candidate_a1", maxsplit=1
    )[0]

    assert "v_authenticated_actor_id uuid := auth.uid()" in authority
    assert "v_request_role = 'authenticated'" in authority
    assert "p_actor_id is distinct from v_authenticated_actor_id::text" in authority
    assert "authenticated callers may only write user authority" in authority
    assert "p_producer_kind = 'user'" in authority
    assert "p_actor_kind = 'user'" in authority
    assert "p_producer_kind = 'user' or p_actor_kind = 'user'" in authority


def test_rn1_c2_006_rebind_failure_restores_previous_state() -> None:
    sql = _sql()
    assert "slice rebind quantity mismatch" in sql
    assert "activation_slice_rebind_failed" in sql
    assert "no active slice is bound to the expected mandate version" in sql
    assert "activation_expected_slice_missing" in sql


def test_rn1_c2_007_snapshot_race_requires_rebase_first() -> None:
    sql = _sql()
    assert "broker snapshot advanced before activation" in sql
    assert "snapshot_race_requires_rebase" in sql


def test_rn1_c2_008_superseded_decision_cannot_execute() -> None:
    sql = _sql()
    assert "create table public.portfolio_mandate_decision_projection_a1" in sql
    assert "projection_status in ('active', 'superseded')" in sql
    assert "projection_status = 'superseded'" in sql
    assert "eligible = false" in sql


def test_rn1_c3_004_issuer_filing_shares_only_by_policy() -> None:
    sql = _sql()
    assert "portfolio_mandate_issuer_evidence_policy_a1" in sql
    assert "issuer evidence sharing is not allowed by policy" in sql


def test_rn1_c3_005_instrument_event_does_not_cross_class() -> None:
    sql = _sql()
    assert "prior.evidence_scope = 'instrument'" in sql
    assert "source_scope_conflict" in sql


def test_rn1_c3_007_historical_alias_uses_event_time() -> None:
    sql = _sql()
    assert "p_source_event_time >= alias.valid_from" in sql
    assert "p_source_event_time < alias.valid_to" in sql


def test_rn1_c3_008_identity_migration_preserves_old_seal() -> None:
    sql = _sql()
    assert "create table public.portfolio_mandate_issuer_lineage_event_a1" in sql
    assert "supersedes_event_id" in sql
    assert "portfolio_mandate_issuer_lineage_event_a1_append_only" in sql


def test_rn1_c5_001_verified_parser_event_can_satisfy_predicate() -> None:
    sql = _sql()
    assert "when 'predicate_fulfilled' then" in sql
    assert "p_producer_kind <> 'deterministic_parser'" in sql
    assert "'sell_eligible'" in sql


def test_rn1_c5_002_user_confirmation_requires_full_audit_fields() -> None:
    sql = _sql()
    assert "when 'user_predicate_confirmed' then" in sql
    assert "p_actor_id is null" in sql
    assert "p_reason is null" in sql


def test_rn1_c5_003_ai_candidate_cannot_create_directional_action() -> None:
    sql = _sql()
    assert "when 'predicate_candidate' then" in sql
    assert "p_producer_kind <> 'ai'" in sql
    assert "v_policy_effect := 'review_only'" in sql


def test_rn1_c5_004_validator_cannot_assert_semantics() -> None:
    sql = _sql()
    assert "when 'provenance_validated' then" in sql
    assert "p_producer_kind <> 'source_validator'" in sql
    assert "v_policy_effect := 'provenance_only'" in sql


def test_rn1_c5_005_unknown_parser_surface_fails_to_review() -> None:
    sql = _sql()
    assert "not p_structured_surface" in sql
    assert "unknown_parser_surface" in sql


def test_rn1_c5_006_restated_source_supersedes_fulfillment() -> None:
    sql = _sql()
    assert "when 'predicate_superseded' then" in sql
    assert "p_supersedes_event_id is null" in sql


def test_rn1_c5_007_free_text_never_fulfills_predicate() -> None:
    sql = _sql()
    assert "p_free_text_only" in sql
    assert "free_text_review_required" in sql
    assert "free-text rationale does not create an authority event" in sql


def test_rn1_c5_008_current_runtime_rejects_long_term_directional_advice() -> None:
    sql = _sql()
    assert "create_long_term_decision" not in sql
    assert "update public.report_index" not in sql
    assert "alter table public.report_index" not in sql


def test_portfolio_mandate_a1_disposable_verification_boundary_is_documented() -> None:
    contract = Path("docs/portfolio-mandate-a1-contract.md").read_text(encoding="utf-8")
    architecture = Path("docs/ARCHITECTURE.md").read_text(encoding="utf-8")
    strategy = Path("docs/STRATEGY.md").read_text(encoding="utf-8")

    assert "disposable PostgreSQL verified, not deployed" in contract
    assert "기존 로컬" in contract
    assert "production DB, 외부 Supabase에는 연결하거나 적용하지 않았" in contract
    assert "PortfolioMandateStore" in contract
    assert "transaction/concurrency 계약을 검증했다" in contract
    assert "Portfolio Mandate A1 비활성 계약" in architecture
    assert "loopback disposable PostgreSQL 17.11에서만" in architecture
    assert "기존 production writer" in architecture
    assert "Portfolio Mandate A1" in strategy
    assert "hard SELL" in strategy
    assert "LONG_TERM 방향성 action" in strategy


def test_t16_default_off_persistence_rehearsal_is_documented() -> None:
    contract = Path("docs/portfolio-persistence-t16-rehearsal.md").read_text(
        encoding="utf-8"
    )
    architecture = Path("docs/ARCHITECTURE.md").read_text(encoding="utf-8")

    assert "Accepted (Implemented and usable, disposable local-only)" in contract
    assert "default-off" in contract
    assert "T16DisposableTarget" in contract
    assert "같은 executor call" in contract
    assert "20260828230000_create_portfolio_mandate_a1.sql" in contract
    assert "REQUIRES_SEPARATE_APPROVAL" in contract
    assert "Portfolio Mandate T16 persistence rehearsal" in architecture
    assert "새 migration" in architecture
