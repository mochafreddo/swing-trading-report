from __future__ import annotations

import re
from pathlib import Path

_MIGRATIONS = Path("supabase/migrations")


def _migration_sql() -> str:
    matches = sorted(_MIGRATIONS.glob("*_add_broker_snapshot_v0.sql"))
    assert len(matches) == 1, "missing BrokerSnapshotV0 migration"
    return matches[0].read_text(encoding="utf-8")


def _normalized_sql() -> str:
    return re.sub(r"\s+", " ", _migration_sql().lower()).strip()


def test_broker_snapshot_migration_seals_persisted_rows_and_revision_atomically() -> (
    None
):
    sql = _normalized_sql()

    assert "create table public.broker_snapshot_v0" in sql
    assert "holdings_digest text not null" in sql
    assert "revision bigint not null" in sql
    assert "sealed_at timestamptz not null" in sql
    assert "create or replace function public.seal_broker_snapshot_v0" in sql
    assert "lock table public.holdings in share mode" in sql
    assert "p_expected_post_state_digest text" in sql
    assert (
        "drop function if exists public.seal_broker_snapshot_v0("
        "text, date, text, timestamptz, jsonb)" in sql
    )
    assert "broker_snapshot_private.constant_time_text_equal_v0" in sql
    assert "brokersnapshotv0 post-state digest mismatch" in sql
    assert "revision = public.broker_snapshot_v0.revision + 1" in sql
    assert "insert into public.runtime_state" in sql
    assert "on conflict on constraint runtime_state_pkey do update" in sql
    assert "snapshotdigest" in sql
    assert "snapshotrevision" in sql


def test_broker_snapshot_rejects_regressed_session_but_allows_same_session_retry() -> (
    None
):
    sql = _normalized_sql()

    assert "p_session_date < v_existing_session_date" in sql
    assert "brokersnapshotv0 session regression" in sql
    assert "p_session_date = v_existing_session_date" not in sql


def test_broker_snapshot_read_rpc_returns_one_sealed_marker_and_row_set() -> None:
    sql = _normalized_sql()

    assert "create or replace function public.get_broker_snapshot_v0" in sql
    assert "state_key text" in sql
    assert "marker jsonb" in sql
    assert "holdings jsonb" in sql
    assert "holdings_digest text" in sql
    assert "revision bigint" in sql
    assert "security invoker" in sql
    assert "security definer" not in sql


def test_broker_snapshot_rpc_is_explicitly_service_role_only_and_rls_preserving() -> (
    None
):
    sql = _normalized_sql()

    assert "alter table public.broker_snapshot_v0 enable row level security" in sql
    assert "alter table public.broker_snapshot_v0 force row level security" in sql
    assert "revoke all on table public.broker_snapshot_v0 from public" in sql
    assert "revoke all on table public.broker_snapshot_v0 from anon" in sql
    assert "revoke all on table public.broker_snapshot_v0 from authenticated" in sql
    for function in (
        "seal_broker_snapshot_v0(text, date, text, timestamptz, jsonb, text)",
        "get_broker_snapshot_v0()",
    ):
        assert f"revoke all on function public.{function} from public" in sql
        assert f"revoke all on function public.{function} from anon" in sql
        assert f"revoke all on function public.{function} from authenticated" in sql
        assert f"grant execute on function public.{function} to service_role" in sql

    assert "create schema if not exists broker_snapshot_private" in sql
    assert "revoke all on schema broker_snapshot_private from public" in sql
    assert "grant usage on schema broker_snapshot_private to service_role" in sql
    assert (
        "create or replace function broker_snapshot_private.collect_broker_holdings_v0()"
        in sql
    )
    assert "create or replace function public.collect_broker_holdings_v0()" not in sql
    assert "drop function if exists public.collect_broker_holdings_v0()" in sql
    assert (
        "grant execute on function "
        "broker_snapshot_private.collect_broker_holdings_v0() to service_role" in sql
    )


def test_broker_snapshot_canonical_projection_excludes_volatile_columns_and_orders_rows() -> (
    None
):
    sql = _normalized_sql()

    for field in (
        "ticker",
        "quantity",
        "entry_price",
        "entry_currency",
        "entry_date",
        "strategy",
        "entry_pattern",
        "notes",
        "tags",
        "stop_override",
        "target_override",
        "broker_state",
        "broker_missing_first_seen_date",
        "broker_missing_last_seen_date",
        "broker_missing_count",
        "broker_missing_diff_hash",
    ):
        assert f"'{field}'" in sql
    assert 'order by upper(trim(source.ticker)) collate "c"' in sql
    assert "where trim(tag.value) <> ''" in sql
    assert 'order by trim(tag.value) collate "c"' in sql
    assert "round(source.quantity, 6)::text" in sql
    assert "round(source.entry_price, 4)::text" in sql
    assert "round(source.stop_override, 4)::text" in sql
    assert "round(source.target_override, 4)::text" in sql
    assert "to_char(" not in sql
    assert "broker-holdings-v0;" in sql
    assert "convert_to('r', 'utf8')" in sql
    assert "convert_to('n', 'utf8')" in sql
    assert "'s' || octet_length" in sql
    assert "'a' || cardinality" in sql
    assert "source.created_at" not in sql
    assert "source.updated_at" not in sql


def test_broker_snapshot_migration_adds_no_order_or_browser_secret_boundary() -> None:
    changed_sources = "\n".join(
        (
            _normalized_sql(),
            Path("sab/scheduler/holdings.py").read_text(encoding="utf-8").lower(),
            Path("web/src/lib/toss/holdings-sync-service.ts")
            .read_text(encoding="utf-8")
            .lower(),
        )
    )

    for forbidden in (
        "create_order",
        "modify_order",
        "cancel_order",
        "conditional_order",
        "next_public_supabase_secret",
        "next_public_supabase_service_role",
        "print(config.service_role_key",
        "logger.info(config.service_role_key",
        "console.log(env.supabase.secret",
    ):
        assert forbidden not in changed_sources


def test_broker_snapshot_rollout_and_initial_state_are_durably_documented() -> None:
    architecture = Path("docs/ARCHITECTURE.md").read_text(encoding="utf-8")
    deployment = Path("docs/deployment.md").read_text(encoding="utf-8")
    combined = f"{architecture}\n{deployment}"

    assert "BrokerSnapshotV0" in architecture
    assert "migration -> Web producer -> Python consumer" in combined
    assert "initial unsealed" in combined
    assert "service-role-only" in combined
    assert "advice-only" in combined
    assert "forward-fix" in combined
