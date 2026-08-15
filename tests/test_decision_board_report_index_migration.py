from __future__ import annotations

import re
from pathlib import Path

_MIGRATIONS = Path("supabase/migrations")


def _sql() -> str:
    matches = sorted(_MIGRATIONS.glob("*_add_decision_board_report_index.sql"))
    assert len(matches) == 1, "missing Decision Board report-index migration"
    return re.sub(r"\s+", " ", matches[0].read_text(encoding="utf-8").lower())


def test_migration_is_additive_and_preserves_legacy_shape() -> None:
    sql = _sql()

    for column in (
        "run_kind text null",
        "run_id text null",
        "idempotency_key text null",
    ):
        assert f"add column if not exists {column}" in sql
    assert "add column if not exists decision_created_at timestamptz null" in sql
    assert "'decision-board'" in sql
    assert "drop column" not in sql
    assert "delete from public.report_index" not in sql
    assert "update public.report_index" not in sql


def test_migration_enforces_decision_board_identity_and_latest_order() -> None:
    sql = _sql()

    assert "run_kind in ('entry', 'holding')" in sql
    assert "idempotency_key ~ '^sha256:[0-9a-f]{64}$'" in sql
    assert "report_index_decision_board_identity_uidx" in sql
    assert "bucket_id, report_type, run_kind, idempotency_key" in sql
    assert "report_index_decision_board_run_id_uidx" in sql
    assert "bucket_id, report_type, run_kind, run_id" in sql
    assert "report_index_decision_board_latest_idx" in sql
    assert "decision_created_at desc, run_id desc, report_key desc" in sql
    assert "where report_type = 'decision-board'" in sql


def test_identity_unique_index_is_inferable_by_postgrest_upsert() -> None:
    sql = _sql()
    identity_index = sql.split(
        "create unique index if not exists report_index_decision_board_identity_uidx",
        1,
    )[1].split("create unique index", 1)[0]

    assert "where " not in identity_index


def test_migration_keeps_rls_force_and_private_grants_explicit() -> None:
    sql = _sql()

    assert "alter table public.report_index enable row level security" in sql
    assert "alter table public.report_index force row level security" in sql
    assert "revoke all on table public.report_index from anon" in sql
    assert "revoke all on table public.report_index from authenticated" in sql
    assert (
        "grant select, insert, update, delete on table public.report_index to service_role"
        in sql
    )
    assert "security definer" not in sql
