from __future__ import annotations

import re
from pathlib import Path

from sab.entry_pattern_contract import HOLDINGS_ENTRY_PATTERN_VALUES
from sab.signals.hybrid_buy import HybridPattern

_MIGRATIONS_DIR = Path("supabase/migrations")
_MIGRATION_PATH = _MIGRATIONS_DIR / "20260609000000_add_holdings_entry_pattern.sql"
_ENABLEMENT_MIGRATION_PATH = (
    _MIGRATIONS_DIR / "20260609010000_enable_holdings_entry_pattern_writes.sql"
)
_ADD_BUY_MIGRATION_PATH = (
    _MIGRATIONS_DIR / "20260304002000_add_holdings_add_buy_idempotency.sql"
)
_SMOKE_PATH = Path("scripts/smoke_holdings_entry_pattern.sql")
_INITIAL_ENTRY_PATTERN_IDS = {
    "trend_pullback_bounce",
    "swing_high_breakout",
    "rsi_oversold_reversal",
}


def _normalize_sql(sql: str) -> str:
    normalized = re.sub(r"\s+", " ", sql.lower()).strip()
    return normalized.replace("( ", "(").replace(" )", ")")


def _strip_sql_comments(sql: str) -> str:
    without_block_comments = re.sub(r"/\*.*?\*/", "", sql, flags=re.DOTALL)
    return re.sub(r"--.*?$", "", without_block_comments, flags=re.MULTILINE)


def _extract_in_list_values_after(sql: str, marker: str) -> set[str]:
    start = sql.lower().index(marker.lower())
    segment = sql[start:]
    match = re.search(r"\bin\s*\(([^)]*)\)", segment, flags=re.IGNORECASE | re.DOTALL)
    assert match is not None, f"missing SQL IN list after {marker!r}"
    return set(re.findall(r"'([^']+)'", match.group(1)))


def _latest_entry_pattern_constraint_sql() -> str:
    candidates = [
        path
        for path in sorted(_MIGRATIONS_DIR.glob("*.sql"))
        if path.name >= _MIGRATION_PATH.name
        and "holdings_entry_pattern_value_check" in path.read_text(encoding="utf-8")
    ]
    assert candidates, "missing effective entry_pattern constraint migration"
    return candidates[-1].read_text(encoding="utf-8")


def test_holdings_entry_pattern_migration_updates_replace_holdings_contract() -> None:
    sql = _MIGRATION_PATH.read_text(encoding="utf-8")
    normalized_sql = _normalize_sql(sql)

    required_snippets = [
        "add column if not exists entry_pattern text null",
        "add constraint holdings_entry_pattern_length_check",
        "char_length(entry_pattern) <= 120",
        "add constraint holdings_entry_pattern_value_check",
        "entry_pattern in (",
        "add constraint holdings_entry_pattern_active_quantity_check",
        "entry_pattern is null or quantity > 0",
        "add constraint holdings_entry_pattern_write_closed_check",
        "entry_pattern is null",
        "lock table public.holdings in share row exclusive mode",
        "incoming holdings entry_pattern writes are disabled until runtime export paths own entry_pattern",
        "Cannot add holdings entry_pattern constraints while invalid rows exist.",
        "Clear or fix entry_pattern on inactive, unknown, or overlong rows before rerunning.",
        "jsonb_typeof(incoming.item->'entry_pattern') <> 'string'",
        "incoming holdings entry_pattern must be a string",
        "incoming holdings entry_pattern must be <= 120 chars",
        "incoming holdings entry_pattern must be one of",
        "inactive holdings entry_pattern must be null",
        "incoming holdings entry_pattern must be explicit when entry identity or strategy changes",
        "drop table if exists pg_temp.incoming_holdings",
        "nullif(trim(incoming.item->>'entry_pattern'), '') not in (",
        "has_entry_pattern boolean not null",
        "entry_pattern text null",
        "incoming.item ? 'entry_pattern'",
        "when incoming.quantity = 0 then null",
        "when incoming.has_entry_pattern then incoming.entry_pattern",
        "else existing.entry_pattern",
        "entry_pattern text null",
        "case when incoming.quantity = 0 then null else incoming.entry_pattern end",
        "jsonb_populate_record(null::public.holdings, v_event.result_payload)",
        "create or replace function public.holdings_add_buy_v1(",
        "entry_pattern = case",
        "when coalesce(v_target.quantity, 0) = 0 then null",
        "else v_target.entry_pattern",
    ]
    for snippet in required_snippets:
        assert _normalize_sql(snippet) in normalized_sql

    assert (
        _extract_in_list_values_after(sql, "holdings_entry_pattern_value_check")
        == _INITIAL_ENTRY_PATTERN_IDS
    )
    assert (
        _extract_in_list_values_after(
            sql, "nullif(trim(incoming.item->>'entry_pattern'), '') not in"
        )
        == _INITIAL_ENTRY_PATTERN_IDS
    )

    forbidden_snippets = [
        "grant execute on function public.replace_holdings_v1(jsonb) to anon",
        "grant execute on function public.replace_holdings_v1(jsonb) to authenticated",
        "grant execute on function public.replace_holdings_v1(jsonb) to public",
        "drop function public.replace_holdings_v1",
        "drop function if exists public.replace_holdings_v1",
        "drop function public.holdings_add_buy_v1",
        "drop function if exists public.holdings_add_buy_v1",
        "event.result_payload = event.result_payload || jsonb_build_object('entry_pattern', existing.entry_pattern)",
        "update public.holdings_add_buy_events event set result_payload",
        "disable row level security",
        "incoming holdings tickers must be canonical",
        "ticker <> public.canonical_holdings_ticker(ticker)",
        "revoke all on function public.replace_holdings_v1(jsonb) from public",
        "revoke all on function public.holdings_add_buy_v1(text,numeric,numeric,date,text) from public",
        "revoke all on function public.replace_holdings_v1(jsonb) from anon",
        "revoke all on function public.replace_holdings_v1(jsonb) from authenticated",
        "grant execute on function public.replace_holdings_v1(jsonb) to service_role",
        "revoke all on function public.holdings_add_buy_v1(",
        "grant execute on function public.holdings_add_buy_v1(",
    ]
    for snippet in forbidden_snippets:
        assert _normalize_sql(snippet) not in normalized_sql


def test_effective_entry_pattern_sql_allowlist_matches_storage_contract() -> None:
    effective_sql = _latest_entry_pattern_constraint_sql()

    assert _extract_in_list_values_after(
        effective_sql, "holdings_entry_pattern_value_check"
    ) == set(HOLDINGS_ENTRY_PATTERN_VALUES)


def test_runtime_enablement_migration_opens_entry_pattern_writes() -> None:
    sql = _ENABLEMENT_MIGRATION_PATH.read_text(encoding="utf-8")
    normalized_sql = _normalize_sql(_strip_sql_comments(sql))

    required_snippets = [
        "drop constraint if exists holdings_entry_pattern_write_closed_check",
        "create or replace function public.replace_holdings_v1(",
        "lock table public.holdings in share row exclusive mode",
        "incoming holdings entry_pattern must be a string",
        "incoming holdings entry_pattern must be <= 120 chars",
        "incoming holdings entry_pattern must be one of",
        "inactive holdings entry_pattern must be null",
        "incoming holdings entry_pattern must be explicit when entry identity or strategy changes",
        "when incoming.quantity = 0 then null",
        "when incoming.has_entry_pattern then incoming.entry_pattern",
        "else existing.entry_pattern",
    ]
    for snippet in required_snippets:
        assert _normalize_sql(snippet) in normalized_sql

    forbidden_snippets = [
        "incoming holdings entry_pattern writes are disabled until runtime export paths own entry_pattern",
        "add constraint holdings_entry_pattern_write_closed_check",
        "create or replace function public.holdings_add_buy_v1(",
        "grant execute on function public.replace_holdings_v1(jsonb) to",
        "revoke all on function public.replace_holdings_v1(jsonb)",
        "disable row level security",
    ]
    for snippet in forbidden_snippets:
        assert _normalize_sql(snippet) not in normalized_sql

    assert (
        _extract_in_list_values_after(
            sql, "nullif(trim(incoming.item->>'entry_pattern'), '') not in"
        )
        == _INITIAL_ENTRY_PATTERN_IDS
    )


def test_entry_pattern_smoke_matches_runtime_enablement_contract() -> None:
    sql = _SMOKE_PATH.read_text(encoding="utf-8")
    normalized_sql = _normalize_sql(_strip_sql_comments(sql))

    required_snippets = [
        "replace non-null marker stores entry_pattern",
        "replace omit keeps active entry_pattern through update",
        "replace explicit null clears entry_pattern",
        "expected inactive entry_pattern to fail",
        "inactive holdings entry_pattern must be null",
    ]
    for snippet in required_snippets:
        assert _normalize_sql(snippet) in normalized_sql

    assert (
        "incoming holdings entry_pattern writes are disabled until runtime export paths own entry_pattern"
        not in sql
    )


def test_current_buy_patterns_are_covered_by_storage_contract() -> None:
    storage_patterns = set(HOLDINGS_ENTRY_PATTERN_VALUES)
    buy_patterns = {pattern.value for pattern in HybridPattern}

    assert buy_patterns <= storage_patterns


def test_add_buy_rpc_remains_quantity_only_and_handles_entry_pattern_edges() -> None:
    historical_sql = _ADD_BUY_MIGRATION_PATH.read_text(encoding="utf-8")
    historical_function_sql = historical_sql[
        historical_sql.index("create or replace function public.holdings_add_buy_v1") :
    ]
    new_migration_raw_sql = _MIGRATION_PATH.read_text(encoding="utf-8")
    new_migration_sql = _normalize_sql(_strip_sql_comments(new_migration_raw_sql))
    historical_uuid_regex = re.search(
        r"v_idempotency_key !~\* '([^']+)'", historical_function_sql
    )
    new_uuid_regex = re.search(
        r"v_idempotency_key !~\* '([^']+)'", new_migration_raw_sql
    )

    assert "p_entry_pattern" not in historical_function_sql
    assert "p_entry_pattern" not in new_migration_sql
    assert "event.result_payload = to_jsonb(existing)" not in new_migration_sql
    assert "jsonb_build_object('entry_pattern', existing.entry_pattern)" not in (
        new_migration_sql
    )
    assert historical_uuid_regex is not None
    assert new_uuid_regex is not None
    assert new_uuid_regex.group(1) == historical_uuid_regex.group(1)

    required_snippets = [
        "create or replace function public.holdings_add_buy_v1(",
        "returns setof public.holdings",
        "returning *",
        "jsonb_populate_record(null::public.holdings, v_event.result_payload)",
        "v_request_fingerprint := md5(",
        "entry_pattern = case",
        "when coalesce(v_target.quantity, 0) = 0 then null",
        "else v_target.entry_pattern",
    ]
    for snippet in required_snippets:
        assert _normalize_sql(snippet) in new_migration_sql

    fingerprint_start = new_migration_sql.index("v_request_fingerprint := md5(")
    fingerprint_end = new_migration_sql.index(
        "insert into public.holdings_add_buy_events", fingerprint_start
    )
    fingerprint_sql = new_migration_sql[fingerprint_start:fingerprint_end]
    assert "entry_pattern" not in fingerprint_sql
