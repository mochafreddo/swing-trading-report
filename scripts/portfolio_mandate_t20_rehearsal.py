#!/usr/bin/env python3
"""Run the A1 promotion/restore rehearsal on a fresh PostgreSQL 17.11 cluster."""

from __future__ import annotations

import argparse
import getpass
import hashlib
import json
import os
import shutil
import socket
import subprocess
import sys
import tempfile
import time
import uuid
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

A1_MIGRATION = Path(
    "supabase/migrations/20260828230000_create_portfolio_mandate_a1.sql"
)
R2_MIGRATION = Path(
    "supabase/migrations/20260907155523_create_portfolio_review_store_r2.sql"
)
R2_TABLES = {
    "portfolio_mandate_review_packet_r2": "packet_id",
    "portfolio_mandate_review_run_r2": "run_id",
    "portfolio_mandate_review_decision_r2": "decision_id",
    "portfolio_mandate_review_journal_r2": "run_id",
    "portfolio_mandate_review_outcome_r2": "outcome_id",
    "portfolio_mandate_review_outbox_r2": "decision_id",
}
R1_MIGRATION = Path("supabase/migrations/20260907150228_create_portfolio_review_r1.sql")
_EXPECTED_VERSION = "170011"
_DATABASE_PREFIX = "portfolio_mandate_a1_test_"
_TEMP_PREFIX = "portfolio-mandate-a1-pg17."


class RehearsalError(RuntimeError):
    """The disposable T20 rehearsal failed closed."""


@dataclass(frozen=True)
class RehearsalTarget:
    address: str
    port: int
    database: str
    data_directory: Path
    session_user: str
    server_version_num: str

    def __post_init__(self) -> None:
        resolved = self.data_directory.resolve()
        root = resolved.parent
        if self.address != "127.0.0.1":
            raise ValueError("target must use exact loopback address")
        if not 1 <= self.port <= 65535:
            raise ValueError("target must use an explicit port")
        if not self.database.startswith(_DATABASE_PREFIX):
            raise ValueError("target must use the disposable database prefix")
        if (
            resolved.name != "data"
            or root.parent != Path("/private/tmp")
            or not root.name.startswith(_TEMP_PREFIX)
        ):
            raise ValueError("target must use the dedicated disposable data directory")
        if not self.session_user:
            raise ValueError("target session user is required")
        if self.server_version_num != _EXPECTED_VERSION:
            raise ValueError("target must be PostgreSQL 17.11")

    @property
    def dsn(self) -> str:
        return (
            f"postgresql://{self.session_user}@{self.address}:"
            f"{self.port}/{self.database}"
        )


def _sanitized_environment(source: Mapping[str, str]) -> dict[str, str]:
    allowed = {
        "PATH",
        "HOME",
        "USER",
        "LOGNAME",
        "TMPDIR",
        "LANG",
        "UV_CACHE_DIR",
        "VIRTUAL_ENV",
        "PORTFOLIO_REVIEW_R2_EXPORT",
    }
    environment = {key: value for key, value in source.items() if key in allowed}
    environment["SAB_SKIP_ROOT_ENV"] = "1"
    environment["LC_ALL"] = "C"
    return environment


def _sha256_bytes(payload: bytes) -> str:
    return "sha256:" + hashlib.sha256(payload).hexdigest()


def _normalize_plain_dump(payload: str) -> bytes:
    """Remove non-semantic pg_dump framing and its per-dump restriction nonce."""
    return (
        "\n".join(
            line
            for line in payload.splitlines()
            if line and not line.startswith(("--", "\\restrict ", "\\unrestrict "))
        )
        + "\n"
    ).encode()


def _build_evidence(
    *,
    target: RehearsalTarget,
    app_revision: str,
    migration_sha256: str,
    schema_checksum: str,
    journal_checksum: str,
    projection_checksum: str,
    security_checksum: str,
    restore_seconds: float,
    cluster_stopped: bool,
    temporary_directory_removed: bool,
) -> dict[str, Any]:
    return {
        "schema_version": "portfolio-mandate-promotion-rehearsal.t20",
        "state": "IMPLEMENTED_AND_USABLE",
        "target": {
            "address": target.address,
            "port": target.port,
            "database": target.database,
            "data_directory": str(target.data_directory),
            "session_user": target.session_user,
            "server_version_num": target.server_version_num,
            "blank_state_verified": True,
        },
        "source_schema_version": "portfolio-mandate.a1",
        "target_schema_version": "portfolio-mandate.a1",
        "preflight_row_count": 0,
        "migration_path": str(A1_MIGRATION),
        "migration_sha256": migration_sha256,
        "schema_checksum": schema_checksum,
        "journal_checksum": journal_checksum,
        "projection_checksum": projection_checksum,
        "security_checksum": security_checksum,
        "restore_permissions_verified": True,
        "write_owner": target.session_user,
        "rollback_compatible_app_revision": app_revision,
        "operations": [
            "SEED",
            "MIGRATE",
            "WRITE",
            "PROJECT",
            "REBUILD",
            "BACKUP",
            "RESTORE",
            "ROLLBACK",
        ],
        "rto": {
            "target_seconds": 1800,
            "measured_seconds": round(restore_seconds, 3),
        },
        "journal_rpo": 0,
        "production_activation": False,
        "live_db_writes": 0,
        "provider_calls": 0,
        "order_operations": 0,
        "cluster_stopped": cluster_stopped,
        "temporary_directory_removed": temporary_directory_removed,
    }


def _binary(name: str) -> str:
    resolved = shutil.which(name)
    if resolved is None:
        raise RehearsalError(f"required PostgreSQL 17.11 binary is unavailable: {name}")
    return resolved


def _run(
    command: list[str],
    *,
    environment: Mapping[str, str],
    cwd: Path | None = None,
) -> str:
    completed = subprocess.run(
        command,
        check=False,
        capture_output=True,
        text=True,
        env=dict(environment),
        cwd=cwd,
    )
    if completed.returncode != 0:
        raise RehearsalError(
            f"{Path(command[0]).name} failed with exit {completed.returncode}"
        )
    return completed.stdout.strip()


def _free_loopback_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as server:
        server.bind(("127.0.0.1", 0))
        return int(server.getsockname()[1])


def _database_dsn(target: RehearsalTarget, database: str) -> str:
    if not database.startswith(_DATABASE_PREFIX):
        raise RehearsalError("restore database must use the disposable prefix")
    return (
        f"postgresql://{target.session_user}@{target.address}:{target.port}/{database}"
    )


def _psql(
    target: RehearsalTarget,
    sql: str,
    *,
    environment: Mapping[str, str],
    database: str | None = None,
) -> str:
    dsn = target.dsn if database is None else _database_dsn(target, database)
    return _run(
        [_binary("psql"), dsn, "-X", "-v", "ON_ERROR_STOP=1", "-qAt", "-c", sql],
        environment=environment,
    )


def _identity(
    target: RehearsalTarget,
    *,
    environment: Mapping[str, str],
    database: str | None = None,
) -> list[str]:
    return _psql(
        target,
        """
        select concat_ws(E'\\t',
          host(inet_server_addr()), inet_server_port()::text,
          current_database(), current_setting('data_directory'),
          session_user, current_setting('server_version_num')
        );
        """,
        environment=environment,
        database=database,
    ).split("\t")


def _verify_identity(
    target: RehearsalTarget,
    *,
    environment: Mapping[str, str],
    database: str | None = None,
) -> None:
    expected_database = target.database if database is None else database
    if not expected_database.startswith(_DATABASE_PREFIX):
        raise RehearsalError("operation database must use the disposable prefix")
    expected = [
        target.address,
        str(target.port),
        expected_database,
        str(target.data_directory),
        target.session_user,
        target.server_version_num,
    ]
    if _identity(target, environment=environment, database=database) != expected:
        raise RehearsalError("disposable operation target identity mismatch")


def _blank_state(target: RehearsalTarget, *, environment: Mapping[str, str]) -> bool:
    _verify_identity(target, environment=environment)
    return (
        _psql(
            target,
            """
            select concat_ws(',',
              not exists (
                select 1 from pg_catalog.pg_class c
                join pg_catalog.pg_namespace n on n.oid = c.relnamespace
                where n.nspname = 'public'
              ),
              not exists (
                select 1 from pg_catalog.pg_proc p
                join pg_catalog.pg_namespace n on n.oid = p.pronamespace
                where n.nspname = 'public'
              ),
              not exists (
                select 1 from pg_catalog.pg_roles
                where rolname in (
                  'anon',
                  'authenticated',
                  'service_role',
                  'portfolio_mandate_candidate_submitter_a1'
                )
              )
            );
            """,
            environment=environment,
        )
        == "t,t,t"
    )


def _dump_checksum(
    target: RehearsalTarget,
    *,
    environment: Mapping[str, str],
    database: str,
    schema_only: bool,
) -> str:
    return _sha256_bytes(
        _dump_payload(
            target,
            environment=environment,
            database=database,
            schema_only=schema_only,
        )
    )


def _dump_payload(
    target: RehearsalTarget,
    *,
    environment: Mapping[str, str],
    database: str,
    schema_only: bool,
) -> bytes:
    _verify_identity(target, environment=environment, database=database)
    command = [
        _binary("pg_dump"),
        _database_dsn(target, database),
        "--no-owner",
    ]
    if schema_only:
        command.append("--schema-only")
    else:
        command.extend(["--data-only", "--inserts"])
    return _normalize_plain_dump(_run(command, environment=environment))


def _table_checksum(
    target: RehearsalTarget,
    table: str,
    order_column: str,
    *,
    environment: Mapping[str, str],
    database: str,
) -> str:
    if {
        **R2_TABLES,
        "portfolio_mandate_journal_event_a1": "journal_event_id",
        "portfolio_mandate_decision_projection_a1": "decision_id",
        "portfolio_mandate_review_policy_r1": "mandate_version_id",
        "portfolio_mandate_review_observation_r1": "observation_id",
    }.get(table) != order_column:
        raise RehearsalError("unsupported checksum table")
    _verify_identity(target, environment=environment, database=database)
    payload = _psql(
        target,
        f"""
        select coalesce(string_agg(row_to_json(source)::text, E'\\n'
                                   order by {order_column}), '')
        from public.{table} as source;
        """,
        environment=environment,
        database=database,
    ).encode()
    return _sha256_bytes(payload)


def _security_checksum(
    target: RehearsalTarget, *, environment: Mapping[str, str], database: str
) -> str:
    """Compare effective A1 permissions, ownership and RLS after restore."""
    _verify_identity(target, environment=environment, database=database)
    payload = _psql(
        target,
        """
        select coalesce(jsonb_agg(row_data order by row_data::text)::text, '[]')
        from (
          select jsonb_build_array(
            'table', c.relname, pg_get_userbyid(c.relowner),
            c.relrowsecurity, c.relforcerowsecurity, r.rolname, privilege,
            has_table_privilege(r.oid, c.oid, privilege)
          ) as row_data
          from pg_class c join pg_namespace n on n.oid = c.relnamespace
          cross join pg_roles r
          cross join unnest(array['SELECT','INSERT','UPDATE','DELETE','TRUNCATE',
                                  'REFERENCES','TRIGGER']) privilege
          where n.nspname = 'public' and c.relkind = 'r'
            and c.relname like 'portfolio_mandate_%'
            and r.rolname in ('anon','authenticated','service_role',
                             'portfolio_mandate_candidate_submitter_a1','portfolio_mandate_review_compiler_r2')
          union all
          select jsonb_build_array(
            'function', p.proname, pg_get_function_identity_arguments(p.oid),
            pg_get_userbyid(p.proowner), p.prosecdef, p.proconfig, r.rolname,
            has_function_privilege(r.oid, p.oid, 'EXECUTE')
          )
          from pg_proc p join pg_namespace n on n.oid = p.pronamespace
          cross join pg_roles r
          where n.nspname in ('public', 'portfolio_mandate_private')
            and (p.proname like '%_a1' or p.proname like '%_r1' or p.proname like '%_r2')
            and r.rolname in ('anon','authenticated','service_role',
                             'portfolio_mandate_candidate_submitter_a1','portfolio_mandate_review_compiler_r2')
        ) permissions;
        """,
        environment=environment,
        database=database,
    )
    if payload == "[]" or not payload:
        raise RehearsalError("A1 security inventory is empty")
    return _sha256_bytes(payload.encode())


def _write_evidence(path: Path, evidence: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(
        json.dumps(evidence, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    temporary.replace(path)


def run_rehearsal(
    repo_root: Path,
    evidence_path: Path,
    *,
    include_review: bool = False,
    include_store: bool = False,
    review_ui: bool = False,
    review_ui_seconds: int = 0,
) -> dict[str, Any]:
    if not 0 <= review_ui_seconds <= 3600:
        raise ValueError("manual UI window must be 0..3600 seconds")
    review_ui = review_ui or review_ui_seconds > 0
    include_store = include_store or review_ui
    include_review = include_review or include_store
    environment = _sanitized_environment(os.environ)
    port = _free_loopback_port()
    temporary_root = Path(
        tempfile.mkdtemp(prefix=_TEMP_PREFIX, dir="/private/tmp")
    ).resolve()
    data_directory = temporary_root / "data"
    log_path = temporary_root / "postgres.log"
    database = _DATABASE_PREFIX + "t20" + uuid.uuid4().hex[:12]
    user = getpass.getuser()
    target = RehearsalTarget(
        address="127.0.0.1",
        port=port,
        database=database,
        data_directory=data_directory,
        session_user=user,
        server_version_num=_EXPECTED_VERSION,
    )
    started = False
    rehearsal_data: dict[str, Any] | None = None
    cluster_stopped = False
    temporary_directory_removed = False
    try:
        _run(
            [
                _binary("initdb"),
                "-D",
                str(data_directory),
                "-U",
                user,
                "--auth=trust",
                "--no-locale",
                "--encoding=UTF8",
            ],
            environment=environment,
        )
        _run(
            [
                _binary("pg_ctl"),
                "-D",
                str(data_directory),
                "-l",
                str(log_path),
                "-o",
                f"-h 127.0.0.1 -p {port}",
                "-w",
                "start",
            ],
            environment=environment,
        )
        started = True
        _run(
            [
                _binary("createdb"),
                "-h",
                target.address,
                "-p",
                str(target.port),
                "-U",
                target.session_user,
                target.database,
            ],
            environment=environment,
        )
        if not _blank_state(target, environment=environment):
            raise RehearsalError("disposable database is not blank")

        test_environment = dict(environment)
        test_environment.update(
            {
                "PORTFOLIO_MANDATE_A1_ALLOW_DISPOSABLE": "1",
                "PORTFOLIO_MANDATE_A1_TEST_DSN": target.dsn,
                "PORTFOLIO_MANDATE_A1_TEST_DATA_DIR": str(data_directory),
            }
        )
        if include_review:
            test_environment["PORTFOLIO_REVIEW_R1_REHEARSAL"] = "1"
        if include_store:
            test_environment["PORTFOLIO_REVIEW_R2_REHEARSAL"] = "1"
        if review_ui:
            test_environment["PORTFOLIO_REVIEW_LIVE_UI"] = "1"
            test_environment["PORTFOLIO_REVIEW_LIVE_SECONDS"] = str(review_ui_seconds)
        _run(
            [
                sys.executable,
                "-m",
                "pytest",
                "-q",
                "--junitxml=" + str(evidence_path.with_suffix(".pytest.xml")),
                "tests/test_portfolio_mandate_postgres_contracts.py",
            ],
            environment=test_environment,
            cwd=repo_root,
        )
        _verify_identity(target, environment=environment)
        if include_store:
            advisor_output = _run(
                [
                    _binary("supabase"),
                    "db",
                    "advisors",
                    "--db-url",
                    target.dsn,
                    "--type",
                    "all",
                    "--level",
                    "info",
                    "--fail-on",
                    "warn",
                    "-o",
                    "json",
                ],
                environment={**environment, "PGSSLMODE": "disable"},
                cwd=repo_root,
            )
            evidence_path.with_suffix(".advisors.json").write_text(advisor_output)

        backup_path = temporary_root / "portfolio-mandate-a1.backup"
        _verify_identity(target, environment=environment)
        _run(
            [
                _binary("pg_dump"),
                target.dsn,
                "--format=custom",
                "--no-owner",
                "--file",
                str(backup_path),
            ],
            environment=environment,
        )
        schema_checksum = _dump_checksum(
            target,
            environment=environment,
            database=target.database,
            schema_only=True,
        )
        journal_checksum = _table_checksum(
            target,
            "portfolio_mandate_journal_event_a1",
            "journal_event_id",
            environment=environment,
            database=target.database,
        )
        projection_checksum = _table_checksum(
            target,
            "portfolio_mandate_decision_projection_a1",
            "decision_id",
            environment=environment,
            database=target.database,
        )

        restore_database = _DATABASE_PREFIX + "restore" + uuid.uuid4().hex[:8]
        _run(
            [
                _binary("createdb"),
                "-h",
                target.address,
                "-p",
                str(target.port),
                "-U",
                target.session_user,
                restore_database,
            ],
            environment=environment,
        )
        _verify_identity(target, environment=environment, database=restore_database)
        restore_started = time.monotonic()
        _run(
            [
                _binary("pg_restore"),
                "--exit-on-error",
                "--no-owner",
                "--dbname",
                _database_dsn(target, restore_database),
                str(backup_path),
            ],
            environment=environment,
        )
        restore_seconds = time.monotonic() - restore_started
        _verify_identity(target, environment=environment, database=restore_database)
        if restore_seconds > 1800:
            raise RehearsalError("restore exceeded the 30 minute RTO")
        restored_schema_checksum = _dump_checksum(
            target,
            environment=environment,
            database=restore_database,
            schema_only=True,
        )
        restored_journal_checksum = _table_checksum(
            target,
            "portfolio_mandate_journal_event_a1",
            "journal_event_id",
            environment=environment,
            database=restore_database,
        )
        restored_projection_checksum = _table_checksum(
            target,
            "portfolio_mandate_decision_projection_a1",
            "decision_id",
            environment=environment,
            database=restore_database,
        )
        security_checksum = _security_checksum(
            target, environment=environment, database=target.database
        )
        checksum_matches = {
            "schema": restored_schema_checksum == schema_checksum,
            "journal": restored_journal_checksum == journal_checksum,
            "projection": restored_projection_checksum == projection_checksum,
            "security": _security_checksum(
                target, environment=environment, database=restore_database
            )
            == security_checksum,
        }
        if include_review:
            for table, key in (
                ("portfolio_mandate_review_policy_r1", "mandate_version_id"),
                ("portfolio_mandate_review_observation_r1", "observation_id"),
                *(R2_TABLES.items() if include_store else []),
            ):
                checksum_matches[table] = _table_checksum(
                    target,
                    table,
                    key,
                    environment=environment,
                    database=target.database,
                ) == _table_checksum(
                    target,
                    table,
                    key,
                    environment=environment,
                    database=restore_database,
                )
        if not all(checksum_matches.values()):
            failed = ", ".join(
                name for name, matches in checksum_matches.items() if not matches
            )
            if not checksum_matches["schema"]:
                source_lines = (
                    _dump_payload(
                        target,
                        environment=environment,
                        database=target.database,
                        schema_only=True,
                    )
                    .decode()
                    .splitlines()
                )
                restored_lines = (
                    _dump_payload(
                        target,
                        environment=environment,
                        database=restore_database,
                        schema_only=True,
                    )
                    .decode()
                    .splitlines()
                )
                differing_line = next(
                    (
                        f"line {index}: {source!r} != {restored!r}"
                        for index, (source, restored) in enumerate(
                            zip(source_lines, restored_lines, strict=False), start=1
                        )
                        if source != restored
                    ),
                    f"line-count {len(source_lines)} != {len(restored_lines)}",
                )
                failed = f"{failed}; first schema difference at {differing_line}"
            raise RehearsalError(f"restored checksum mismatch: {failed}")
        if include_store:
            # The owner is chosen as cluster owner before SET ROLE; the read RPC
            # then executes under authenticated and a read-only transaction.
            ids_sql = "select owner_id::text || '|' || version_ids::text from public.portfolio_mandate_review_run_r2 order by sequence desc limit 1;"
            owner, versions = _psql(target, ids_sql, environment=environment).split("|")
            read_sql = f'begin read only; set role authenticated; set request.jwt.claims=\'{{"role":"authenticated","sub":"{owner}"}}\'; select public.read_portfolio_review_store_r2(\'{versions}\'::uuid[]); commit;'
            source_read = _psql(target, read_sql, environment=environment)
            restored_read = _psql(
                target, read_sql, environment=environment, database=restore_database
            )
            if source_read != restored_read:
                raise RehearsalError("restored R2 read-only projection mismatch")
        _run(
            [
                _binary("dropdb"),
                "-h",
                target.address,
                "-p",
                str(target.port),
                "-U",
                target.session_user,
                restore_database,
            ],
            environment=environment,
        )
        app_revision = _run(
            ["git", "rev-parse", "HEAD"], environment=environment, cwd=repo_root
        )
        rehearsal_data = {
            "app_revision": app_revision,
            "migration_sha256": _sha256_bytes((repo_root / A1_MIGRATION).read_bytes()),
            "schema_checksum": schema_checksum,
            "journal_checksum": journal_checksum,
            "projection_checksum": projection_checksum,
            "restore_seconds": restore_seconds,
            "security_checksum": security_checksum,
        }
    finally:
        if started:
            stopped = subprocess.run(
                [
                    _binary("pg_ctl"),
                    "-D",
                    str(data_directory),
                    "-m",
                    "fast",
                    "-w",
                    "stop",
                ],
                check=False,
                capture_output=True,
                text=True,
                env=environment,
            )
            cluster_stopped = stopped.returncode == 0
        shutil.rmtree(temporary_root, ignore_errors=True)
        temporary_directory_removed = not temporary_root.exists()

    if rehearsal_data is None:
        raise RehearsalError("disposable rehearsal did not complete")
    if not cluster_stopped or not temporary_directory_removed:
        raise RehearsalError("disposable cluster cleanup was incomplete")
    evidence = _build_evidence(
        target=target,
        cluster_stopped=cluster_stopped,
        temporary_directory_removed=temporary_directory_removed,
        **rehearsal_data,
    )
    if include_review:
        evidence["review_schema_version"] = "portfolio-review.r1"
        evidence["review_migration_sha256"] = _sha256_bytes(
            (repo_root / R1_MIGRATION).read_bytes()
        )
        evidence["review_policy_and_observation_restore_verified"] = True
    if include_store:
        evidence["store_migration_sha256"] = _sha256_bytes(
            (repo_root / R2_MIGRATION).read_bytes()
        )
        evidence["store_tables_and_read_only_restore_verified"] = True
    if review_ui:
        evidence["live_synthetic_ui"] = (
            "MANUAL_WINDOW" if review_ui_seconds else "E2E_PASSED"
        )
        evidence["user_ux_evaluation"] = "NOT_EVALUATED"
    _write_evidence(evidence_path, evidence)
    return evidence


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--include-store",
        action="store_true",
        help="also verify R2 atomic review storage and read-only restore",
    )
    parser.add_argument(
        "--include-review",
        action="store_true",
        help="also verify the approved R1 extension on this new disposable cluster",
    )
    parser.add_argument(
        "--evidence",
        type=Path,
        default=Path("tmp/portfolio-mandate-t20-evidence.local.json"),
        help="gitignored local evidence output",
    )
    parser.add_argument(
        "--review-ui",
        action="store_true",
        help="exercise live disposable DB UI at port 43317 before backup/restore",
    )
    parser.add_argument(
        "--review-ui-seconds",
        type=int,
        default=0,
        help="manual window up to 3600 seconds; zero runs browser E2E",
    )
    args = parser.parse_args()
    repo_root = Path(__file__).resolve().parents[1]
    evidence_path = args.evidence
    if not evidence_path.is_absolute():
        evidence_path = repo_root / evidence_path
    evidence = run_rehearsal(
        repo_root,
        evidence_path,
        include_review=args.include_review,
        include_store=args.include_store,
        review_ui=args.review_ui,
        review_ui_seconds=args.review_ui_seconds,
    )
    print(
        json.dumps(
            {
                "state": evidence["state"],
                "rto_seconds": evidence["rto"]["measured_seconds"],
                "journal_rpo": evidence["journal_rpo"],
                "cluster_stopped": evidence["cluster_stopped"],
                "temporary_directory_removed": evidence["temporary_directory_removed"],
                "evidence_path": str(evidence_path),
            },
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
