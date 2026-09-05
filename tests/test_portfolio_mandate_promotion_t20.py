from __future__ import annotations

import os
from pathlib import Path

import pytest
import scripts.portfolio_mandate_t20_rehearsal as rehearsal
from scripts.portfolio_mandate_t20_rehearsal import (
    A1_MIGRATION,
    RehearsalError,
    RehearsalTarget,
    _build_evidence,
    _normalize_plain_dump,
    _sanitized_environment,
)


def test_t20_target_accepts_only_generated_disposable_loopback_identity() -> None:
    target = RehearsalTarget(
        address="127.0.0.1",
        port=65439,
        database="portfolio_mandate_a1_test_t20abc",
        data_directory=Path("/private/tmp/portfolio-mandate-a1-pg17.unit/data"),
        session_user="tester",
        server_version_num="170011",
    )

    assert target.database.startswith("portfolio_mandate_a1_test_")

    with pytest.raises(ValueError, match="loopback"):
        RehearsalTarget(
            address="db.production.example.com",
            port=5432,
            database="production",
            data_directory=Path("/var/lib/postgresql/data"),
            session_user="admin",
            server_version_num="170011",
        )


def test_t20_subprocess_environment_discards_all_inherited_pg_routing() -> None:
    environment = _sanitized_environment(
        {
            **os.environ,
            "PGHOST": "production.example.com",
            "PGSERVICE": "production",
            "PORTFOLIO_MANDATE_A1_TEST_DSN": "unsafe",
        }
    )

    assert "PGHOST" not in environment
    assert "PGSERVICE" not in environment
    assert "PORTFOLIO_MANDATE_A1_TEST_DSN" not in environment


def test_t20_blank_state_rejects_every_rehearsal_role_collision(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured_sql = ""
    target = RehearsalTarget(
        address="127.0.0.1",
        port=65439,
        database="portfolio_mandate_a1_test_t20abc",
        data_directory=Path("/private/tmp/portfolio-mandate-a1-pg17.unit/data"),
        session_user="tester",
        server_version_num="170011",
    )

    monkeypatch.setattr(rehearsal, "_verify_identity", lambda *args, **kwargs: None)

    def capture_sql(*args: object, **kwargs: object) -> str:
        nonlocal captured_sql
        captured_sql = str(args[1])
        return "t,t,t"

    monkeypatch.setattr(rehearsal, "_psql", capture_sql)

    assert rehearsal._blank_state(target, environment={}) is True
    for role in (
        "anon",
        "authenticated",
        "service_role",
        "portfolio_mandate_candidate_submitter_a1",
    ):
        assert role in captured_sql


def test_t20_restore_identity_requires_the_exact_disposable_database(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    target = RehearsalTarget(
        address="127.0.0.1",
        port=65439,
        database="portfolio_mandate_a1_test_t20abc",
        data_directory=Path("/private/tmp/portfolio-mandate-a1-pg17.unit/data"),
        session_user="tester",
        server_version_num="170011",
    )
    restore_database = "portfolio_mandate_a1_test_restoreabc"
    monkeypatch.setattr(
        rehearsal,
        "_identity",
        lambda *args, **kwargs: [
            "127.0.0.1",
            "65439",
            restore_database,
            "/private/tmp/portfolio-mandate-a1-pg17.unit/data",
            "tester",
            "170011",
        ],
    )

    rehearsal._verify_identity(target, environment={}, database=restore_database)

    with pytest.raises(RehearsalError, match="disposable prefix"):
        rehearsal._verify_identity(target, environment={}, database="production")


def test_t20_schema_checksum_ignores_pg_dump_framing_not_ddl() -> None:
    left = (
        "\\restrict nonce-a\n"
        "-- Name: public; Type: SCHEMA; Schema: -; Owner: -\n\n"
        "CREATE TABLE public.example (id integer);\n"
        "\\unrestrict nonce-a"
    )
    right = (
        "\\restrict nonce-b\n"
        "-- Name: example; Type: TABLE; Schema: public; Owner: -\n"
        "CREATE TABLE public.example (id integer);\n"
        "\\unrestrict nonce-b"
    )

    assert _normalize_plain_dump(left) == _normalize_plain_dump(right)
    assert b"CREATE TABLE public.example" in _normalize_plain_dump(left)


def test_t20_evidence_has_restore_rto_rpo_and_no_activation_claim() -> None:
    target = RehearsalTarget(
        address="127.0.0.1",
        port=65439,
        database="portfolio_mandate_a1_test_t20abc",
        data_directory=Path("/private/tmp/portfolio-mandate-a1-pg17.unit/data"),
        session_user="tester",
        server_version_num="170011",
    )

    evidence = _build_evidence(
        target=target,
        app_revision="a" * 40,
        migration_sha256="sha256:" + "b" * 64,
        schema_checksum="sha256:" + "c" * 64,
        journal_checksum="sha256:" + "d" * 64,
        projection_checksum="sha256:" + "e" * 64,
        restore_seconds=1.25,
        cluster_stopped=True,
        temporary_directory_removed=True,
    )

    assert evidence["state"] == "IMPLEMENTED_AND_USABLE"
    assert evidence["source_schema_version"] == "portfolio-mandate.a1"
    assert evidence["target_schema_version"] == "portfolio-mandate.a1"
    assert evidence["rto"]["target_seconds"] == 1800
    assert evidence["rto"]["measured_seconds"] == 1.25
    assert evidence["journal_rpo"] == 0
    assert evidence["production_activation"] is False
    assert evidence["live_db_writes"] == 0
    assert evidence["cluster_stopped"] is True
    assert evidence["temporary_directory_removed"] is True


def test_t20_reuses_the_single_existing_a1_create_only_migration() -> None:
    assert (
        Path("supabase/migrations/20260828230000_create_portfolio_mandate_a1.sql")
        == A1_MIGRATION
    )
    assert (
        A1_MIGRATION.read_text(encoding="utf-8").count(
            "create table public.portfolio_mandate_a1"
        )
        == 1
    )
