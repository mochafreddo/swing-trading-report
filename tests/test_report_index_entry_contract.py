from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
_MIGRATION_PATH = (
    _ROOT
    / "supabase"
    / "migrations"
    / "20260327110000_allow_entry_reports_in_report_index.sql"
)
_AI_BRIEF_MIGRATION_PATH = (
    _ROOT
    / "supabase"
    / "migrations"
    / "20260505130000_allow_ai_brief_reports_in_report_index.sql"
)
_AI_BRIEF_SKIP_MIGRATION_PATH = (
    _ROOT
    / "supabase"
    / "migrations"
    / "20260531110000_allow_ai_brief_skip_reports_in_report_index.sql"
)
_SELL_AI_BRIEF_MIGRATION_PATH = (
    _ROOT
    / "supabase"
    / "migrations"
    / "20260702093000_allow_sell_ai_brief_reports_in_report_index.sql"
)
_REPORT_INDEX_BUCKET_MIGRATION_PATH = (
    _ROOT / "supabase" / "migrations" / "20260706140000_add_report_index_bucket_id.sql"
)


def test_entry_report_index_migration_expands_constraint_and_backfill() -> None:
    sql = _MIGRATION_PATH.read_text(encoding="utf-8")

    assert "check (report_type in ('buy', 'sell', 'entry'))" in sql
    assert r"\.(buy|sell|entry)\.json$" in sql
    assert "from storage.objects as objects" in sql
    assert "on conflict (report_key) do update" in sql


def test_ai_brief_report_index_migration_expands_constraint_and_backfill() -> None:
    sql = _AI_BRIEF_MIGRATION_PATH.read_text(encoding="utf-8")

    assert "check (report_type in ('buy', 'sell', 'entry', 'ai-brief'))" in sql
    assert r"\.(buy|sell|entry|ai-brief)\.json$" in sql
    assert "from storage.objects as objects" in sql
    assert "on conflict (report_key) do update" in sql


def test_ai_brief_skip_report_index_migration_expands_constraint_and_backfill() -> None:
    sql = _AI_BRIEF_SKIP_MIGRATION_PATH.read_text(encoding="utf-8")

    assert (
        "check (report_type in ('buy', 'sell', 'entry', 'ai-brief', 'ai-brief-skip'))"
    ) in sql
    assert r"\.(buy|sell|entry|ai-brief|ai-brief-skip)\.json$" in sql
    assert "from storage.objects as objects" in sql
    assert "on conflict (report_key) do update" in sql


def test_sell_ai_brief_report_index_migration_expands_constraint_and_backfill() -> None:
    sql = _SELL_AI_BRIEF_MIGRATION_PATH.read_text(encoding="utf-8")

    assert (
        "check (report_type in ('buy', 'sell', 'entry', 'ai-brief', "
        "'ai-brief-skip', 'sell-ai-brief'))"
    ) in sql
    assert r"\.(buy|sell|entry|ai-brief|ai-brief-skip|sell-ai-brief)\.json$" in sql
    assert "from storage.objects as objects" in sql
    assert "on conflict (report_key) do update" in sql


def test_report_index_bucket_identity_migration_updates_key_contract() -> None:
    sql = _REPORT_INDEX_BUCKET_MIGRATION_PATH.read_text(encoding="utf-8")

    assert "add column if not exists bucket_id text not null default 'reports'" in sql
    assert "drop constraint if exists report_index_pkey" in sql
    assert "primary key (bucket_id, report_key)" in sql
    assert "report_index_report_key_bucket_idx" in sql
    assert "objects.bucket_id" in sql
    assert "on conflict (bucket_id, report_key) do update" in sql
