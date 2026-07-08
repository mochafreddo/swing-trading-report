from __future__ import annotations

from pathlib import Path

_MIGRATION = Path(
    "supabase/migrations/20260708150000_add_scheduled_toss_quarantine.sql"
)


def _sql() -> str:
    return _MIGRATION.read_text(encoding="utf-8")


def test_scheduled_toss_quarantine_migration_adds_durable_broker_state() -> None:
    sql = _sql()

    assert (
        "add column if not exists broker_state text not null default 'confirmed'" in sql
    )
    assert "add column if not exists broker_missing_first_seen_date date null" in sql
    assert "add column if not exists broker_missing_last_seen_date date null" in sql
    assert (
        "add column if not exists broker_missing_count integer not null default 0"
        in sql
    )
    assert "add column if not exists broker_missing_diff_hash text null" in sql
    assert "holdings_broker_state_check" in sql
    assert "holdings_broker_missing_evidence_check" in sql
    assert "broker_state in ('confirmed', 'not_seen_in_toss')" in sql
    assert "broker_missing_count > 0" in sql


def test_scheduled_toss_quarantine_rpc_is_non_destructive_and_cas_guarded() -> None:
    sql = _sql()
    quarantine_sql = sql.split(
        "create or replace function public.replace_holdings_v1", maxsplit=1
    )[0]
    normalized = " ".join(quarantine_sql.lower().split())

    assert "create or replace function public.apply_scheduled_toss_quarantine_v1" in sql
    assert "lock table public.holdings in share row exclusive mode" in normalized
    assert "detail = 'holdings_snapshot_conflict'" in sql
    assert "scheduled Toss quarantine omitted missing holdings" in sql
    assert "broker_state = 'not_seen_in_toss'" in sql
    assert "broker_missing_count + 1" in sql
    assert "delete from public.holdings" not in normalized


def test_replace_holdings_rpc_reuses_broker_aware_cas_before_deleting() -> None:
    sql = _sql()
    normalized = " ".join(sql.lower().split())

    assert "create or replace function public.replace_holdings_v1" in sql
    assert "'broker_state', existing.broker_state" in sql
    assert (
        "'broker_missing_first_seen_date', existing.broker_missing_first_seen_date"
        in sql
    )
    assert "from public.apply_scheduled_toss_quarantine_v1(" in normalized
    assert "where existing.ticker = any(v_delete_tickers)" in normalized
    assert "delete from public.holdings existing" in normalized


def test_scheduled_toss_quarantine_rpc_keeps_service_role_only_permissions() -> None:
    sql = _sql()

    signature = (
        "public.apply_scheduled_toss_quarantine_v1(jsonb, text[], jsonb, date, text)"
    )
    assert f"revoke all on function {signature} from anon;" in sql
    assert f"revoke all on function {signature} from authenticated;" in sql
    assert f"revoke all on function {signature} from public;" in sql
    assert f"grant execute on function {signature} to service_role;" in sql
