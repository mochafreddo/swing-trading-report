from __future__ import annotations

import os
import shutil
import subprocess
import uuid
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import quote, unquote, urlparse, urlunsplit

import pytest
from sab.portfolio_mandate.persistence_rehearsal import (
    PortfolioMandatePersistenceT16,
    T16ActivationCommand,
    T16DisposableTarget,
)

_MIGRATION = Path("supabase/migrations/20260828230000_create_portfolio_mandate_a1.sql")
_ALLOW_ENV = "PORTFOLIO_MANDATE_A1_ALLOW_DISPOSABLE"
_DSN_ENV = "PORTFOLIO_MANDATE_A1_TEST_DSN"
_DATA_DIR_ENV = "PORTFOLIO_MANDATE_A1_TEST_DATA_DIR"
_EXPECTED_SERVER_VERSION_NUM = "170011"
_UUID_NAMESPACE = uuid.UUID("00000000-0000-4000-8000-000000000001")


@dataclass(frozen=True)
class _DisposablePostgresConnection:
    dsn: str
    pgpass_file: Path


def _psql_environment(
    connection: _DisposablePostgresConnection | None = None,
) -> dict[str, str]:
    environment = {
        key: value for key, value in os.environ.items() if not key.startswith("PG")
    }
    for harness_key in (_ALLOW_ENV, _DSN_ENV, _DATA_DIR_ENV):
        environment.pop(harness_key, None)
    if connection is not None:
        environment["PGPASSFILE"] = str(connection.pgpass_file)
    return environment


def _canonical_disposable_dsn(dsn: str) -> str:
    parsed = urlparse(dsn)
    if parsed.scheme not in {"postgres", "postgresql"}:
        raise ValueError("disposable PostgreSQL DSN must use postgres or postgresql")
    if parsed.params or parsed.query or parsed.fragment:
        raise ValueError(
            "disposable PostgreSQL DSN cannot contain query, parameters, or fragment"
        )
    if parsed.hostname != "127.0.0.1":
        raise ValueError(
            "disposable PostgreSQL DSN must use exact loopback host 127.0.0.1"
        )
    if parsed.port is None:
        raise ValueError("disposable PostgreSQL DSN must include an explicit port")
    username = unquote(parsed.username or "")
    if not username:
        raise ValueError("disposable PostgreSQL DSN must include an explicit user")
    database = unquote(parsed.path.removeprefix("/"))
    if "/" in database or not database.startswith("portfolio_mandate_a1_test_"):
        raise ValueError(
            "disposable database name must start with portfolio_mandate_a1_test_"
        )
    credentials = quote(username, safe="")
    return (
        f"postgresql://{credentials}@127.0.0.1:{parsed.port}/{quote(database, safe='')}"
    )


def _pgpass_escape(value: str) -> str:
    return value.replace("\\", "\\\\").replace(":", "\\:")


def _disposable_identity_matches(actual: list[str], expected: list[str]) -> bool:
    return actual == expected


def _validated_disposable_data_dir(raw_path: str) -> Path:
    data_dir = Path(raw_path).resolve(strict=True)
    root = data_dir.parent
    if (
        data_dir.name != "data"
        or root.parent != Path("/private/tmp")
        or not root.name.startswith("portfolio-mandate-a1-pg17.")
    ):
        raise ValueError(
            "disposable data directory must be a dedicated "
            "/private/tmp/portfolio-mandate-a1-pg17.*/data path"
        )
    return data_dir


def _disposable_database_is_blank(preflight: str) -> bool:
    return preflight == "t,t,t,t"


def _prepare_disposable_connection(
    dsn: str,
    pgpass_file: Path,
) -> _DisposablePostgresConnection:
    canonical_dsn = _canonical_disposable_dsn(dsn)
    parsed = urlparse(dsn)
    username = unquote(parsed.username or "")
    password = unquote(parsed.password or "")
    database = unquote(parsed.path.removeprefix("/"))
    try:
        payload = (
            ":".join(
                _pgpass_escape(value)
                for value in (
                    "127.0.0.1",
                    str(parsed.port),
                    database,
                    username,
                    password,
                )
            )
            + "\n"
        ).encode()
        descriptor = os.open(
            pgpass_file,
            os.O_WRONLY | os.O_CREAT | os.O_EXCL,
            0o600,
        )
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(payload)
    except OSError:
        pgpass_file.unlink(missing_ok=True)
        raise
    return _DisposablePostgresConnection(canonical_dsn, pgpass_file)


def _psql_command(
    connection: _DisposablePostgresConnection,
    *,
    sql: str | None = None,
    file: Path | None = None,
    executable: str = "psql",
) -> list[str]:
    if (sql is None) == (file is None):
        raise ValueError("exactly one of sql or file is required")
    command = [executable, connection.dsn, "-X", "-v", "ON_ERROR_STOP=1", "-qAt"]
    if sql is not None:
        command.extend(["-c", sql])
    if file is not None:
        command.append("--single-transaction")
        command.extend(["-f", str(file)])
    return command


def _psql(
    connection: _DisposablePostgresConnection,
    *,
    sql: str | None = None,
    file: Path | None = None,
) -> str:
    executable = shutil.which("psql")
    if executable is None:
        pytest.fail("psql is required for Portfolio Mandate PostgreSQL contracts")
    completed = subprocess.run(
        _psql_command(connection, sql=sql, file=file, executable=executable),
        check=False,
        capture_output=True,
        text=True,
        env=_psql_environment(connection),
    )
    if completed.returncode != 0:
        pytest.fail(
            "psql command failed against the approved disposable database:\n"
            f"{completed.stderr}"
        )
    return completed.stdout.strip()


def _psql_error(
    connection: _DisposablePostgresConnection,
    *,
    sql: str | None = None,
    file: Path | None = None,
) -> str:
    executable = shutil.which("psql")
    if executable is None:
        pytest.fail("psql is required for Portfolio Mandate PostgreSQL contracts")
    completed = subprocess.run(
        _psql_command(connection, sql=sql, file=file, executable=executable),
        check=False,
        capture_output=True,
        text=True,
        env=_psql_environment(connection),
    )
    if completed.returncode == 0:
        pytest.fail("psql command unexpectedly succeeded")
    return completed.stderr


def _psql_process(
    connection: _DisposablePostgresConnection,
    *,
    sql: str,
) -> subprocess.Popen[str]:
    executable = shutil.which("psql")
    if executable is None:
        pytest.fail("psql is required for Portfolio Mandate PostgreSQL contracts")
    return subprocess.Popen(
        _psql_command(connection, sql=sql, executable=executable),
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        env=_psql_environment(connection),
    )


def _barrier_sql(barrier_id: int, sql: str) -> str:
    return f"""
    select pg_catalog.pg_advisory_lock_shared(31415, {barrier_id});
    do $barrier$
    declare
      deadline timestamptz := clock_timestamp() + interval '5 seconds';
    begin
      loop
        exit when (
          select count(*)
          from pg_catalog.pg_locks
          where locktype = 'advisory'
            and classid = 31415
            and objid = {barrier_id}
            and mode = 'ShareLock'
            and granted
        ) >= 2;
        if clock_timestamp() >= deadline then
          raise exception 'concurrency test barrier timed out';
        end if;
        perform pg_catalog.pg_sleep(0.01);
      end loop;
    end;
    $barrier$;
    {sql}
    select pg_catalog.pg_advisory_unlock_shared(31415, {barrier_id});
    """


def _uuid(name: str) -> str:
    return str(uuid.uuid5(_UUID_NAMESPACE, name))


def _test_dsn(
    *,
    database: str = "portfolio_mandate_a1_test_guard",
    password: str | None = None,
) -> str:
    credentials = "tester"
    if password is not None:
        credentials = f"{credentials}:{quote(password, safe='')}"
    return urlunsplit(
        (
            "postgresql",
            f"{credentials}@127.0.0.1:65439",
            f"/{quote(database, safe='')}",
            "",
            "",
        )
    )


def test_disposable_dsn_rejects_libpq_redirect_parameters() -> None:
    with pytest.raises(ValueError, match="query, parameters, or fragment"):
        _canonical_disposable_dsn(
            "postgresql://tester@127.0.0.1:65439/"
            "portfolio_mandate_a1_test_guard?hostaddr=203.0.113.1"
        )


def test_disposable_identity_rejects_wrong_postgres_patch_version() -> None:
    actual = ["127.0.0.1", "65439", "database", "/data", "tester", "170010"]
    expected = [
        "127.0.0.1",
        "65439",
        "database",
        "/data",
        "tester",
        _EXPECTED_SERVER_VERSION_NUM,
    ]

    assert not _disposable_identity_matches(actual, expected)


def test_disposable_data_dir_rejects_non_dedicated_cluster(tmp_path: Path) -> None:
    data_dir = tmp_path / "data"
    data_dir.mkdir()

    with pytest.raises(ValueError, match="dedicated"):
        _validated_disposable_data_dir(str(data_dir))


def test_disposable_database_preflight_rejects_non_blank_state() -> None:
    assert _disposable_database_is_blank("t,t,t,t")
    assert not _disposable_database_is_blank("t,f,t,t")
    assert not _disposable_database_is_blank("t,t,t,f")


def test_psql_environment_removes_inherited_connection_overrides(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("PGHOSTADDR", "203.0.113.1")
    monkeypatch.setenv("PGSERVICE", "unsafe-service")
    monkeypatch.setenv(
        _DSN_ENV,
        _test_dsn(database="db", password="synthetic-placeholder"),
    )

    environment = _psql_environment()

    assert "PGHOSTADDR" not in environment
    assert "PGSERVICE" not in environment
    assert _DSN_ENV not in environment


def test_disposable_connection_uses_protected_pgpass_without_argv_secret(
    tmp_path: Path,
) -> None:
    secret = "synthetic-secret:with\\escapes"
    connection = _prepare_disposable_connection(
        _test_dsn(password=secret),
        tmp_path / "pgpass",
    )

    command = _psql_command(connection, sql="select 1")
    environment = _psql_environment(connection)

    assert secret not in " ".join(command)
    assert secret not in connection.dsn
    assert environment["PGPASSFILE"] == str(connection.pgpass_file)
    assert connection.pgpass_file.stat().st_mode & 0o777 == 0o600


def test_file_based_migration_command_is_single_transaction(tmp_path: Path) -> None:
    connection = _prepare_disposable_connection(
        _test_dsn(password="synthetic-placeholder"),
        tmp_path / "pgpass",
    )

    command = _psql_command(connection, file=_MIGRATION)

    assert "--single-transaction" in command


def _seed_rebase_case(
    dsn: _DisposablePostgresConnection,
    *,
    case: str,
    target_quantity: str,
    cause: str,
    verification_state: str,
    matched: bool,
    corporate_action_ratio: str | None = None,
) -> dict[str, str]:
    ids = {
        name: _uuid(f"{case}:{name}")
        for name in (
            "issuer",
            "instrument",
            "position",
            "mandate",
            "version",
            "source_snapshot",
            "target_snapshot",
            "allocation",
            "slice",
            "evidence",
            "source",
            "command",
            "event",
            "owner",
        )
    }
    matched_slice = f"'{ids['slice']}'" if matched else "null"
    ratio = corporate_action_ratio if corporate_action_ratio is not None else "null"
    _psql(
        dsn,
        sql=f"""
        insert into public.portfolio_mandate_issuer_a1 (issuer_id, legal_name)
        values ('{ids["issuer"]}', 'Synthetic issuer {case}');
        insert into public.portfolio_mandate_instrument_a1 (
          instrument_id, issuer_id, security_type, currency
        ) values (
          '{ids["instrument"]}', '{ids["issuer"]}', 'COMMON_STOCK', 'USD'
        );
        insert into public.portfolio_mandate_broker_position_a1 (
          broker_position_id, account_ref_hash, instrument_id, currency
        ) values (
          '{ids["position"]}', 'sha256:{"a" * 64}', '{ids["instrument"]}', 'USD'
        );
        insert into public.portfolio_mandate_a1 (
          mandate_id, instrument_id, broker_position_id, owner_actor_id
        ) values (
          '{ids["mandate"]}', '{ids["instrument"]}', '{ids["position"]}',
          '{ids["owner"]}'
        );
        insert into public.portfolio_mandate_version_a1 (
          mandate_version_id, mandate_id, version_number, classification_state,
          horizon, approval_state, thesis, invalidation_conditions,
          approved_by_kind, approved_at, policy_version, effective_from
        ) values (
          '{ids["version"]}', '{ids["mandate"]}', 1, 'ACTIVE', 'SWING',
          'APPROVED', 'Synthetic thesis', array['Synthetic invalidation'],
          'USER', '2026-08-29T00:00:00Z', 'synthetic-v1',
          '2026-08-29T00:00:00Z'
        );
        insert into public.portfolio_mandate_broker_snapshot_a1 (
          broker_position_snapshot_id, broker_position_id, snapshot_version,
          quantity, currency, watermark, sealed_input_hash, captured_at
        ) values
          (
            '{ids["source_snapshot"]}', '{ids["position"]}', 1, 10, 'USD',
            '{case}-source', 'sha256:{"b" * 64}', '2026-08-29T00:00:00Z'
          ),
          (
            '{ids["target_snapshot"]}', '{ids["position"]}', 2,
            {target_quantity}, 'USD', '{case}-target', 'sha256:{"c" * 64}',
            '2026-08-29T00:01:00Z'
          );
        insert into public.portfolio_mandate_allocation_a1 (
          allocation_id, broker_position_id, allocation_version,
          snapshot_version, active, decision_eligible
        ) values ('{ids["allocation"]}', '{ids["position"]}', 1, 1, true, true);
        insert into public.portfolio_mandate_position_slice_a1 (
          slice_id, allocation_id, mandate_version_id, quantity, currency,
          classification_state, decision_eligible
        ) values (
          '{ids["slice"]}', '{ids["allocation"]}', '{ids["version"]}', 10, 'USD',
          'ACTIVE', true
        );
        insert into public.portfolio_mandate_rebase_evidence_a1 (
          rebase_evidence_id, broker_position_id, source_snapshot_version,
          target_snapshot_version, rebase_cause, matched_slice_id,
          corporate_action_ratio, source_id, evidence_hash,
          verification_state, producer_kind
        ) values (
          '{ids["evidence"]}', '{ids["position"]}', 1, 2, upper('{cause}'),
          {matched_slice}, {ratio}, '{ids["source"]}', 'sha256:{"d" * 64}',
          '{verification_state}', 'DETERMINISTIC'
        );
        """,
    )
    return ids


def _seed_activation_case(
    dsn: _DisposablePostgresConnection,
    *,
    case: str,
) -> dict[str, str]:
    ids = {
        name: _uuid(f"{case}:{name}")
        for name in (
            "issuer",
            "instrument",
            "position",
            "mandate",
            "active_version",
            "draft_version",
            "snapshot",
            "allocation",
            "slice",
            "source_journal",
            "source_command",
            "decision",
            "command",
            "activation_event",
            "actor",
        )
    }
    _psql(
        dsn,
        sql=f"""
        insert into public.portfolio_mandate_issuer_a1 (issuer_id, legal_name)
        values ('{ids["issuer"]}', 'Synthetic issuer {case}');
        insert into public.portfolio_mandate_instrument_a1 (
          instrument_id, issuer_id, security_type, currency
        ) values (
          '{ids["instrument"]}', '{ids["issuer"]}', 'COMMON_STOCK', 'USD'
        );
        insert into public.portfolio_mandate_broker_position_a1 (
          broker_position_id, account_ref_hash, instrument_id, currency
        ) values (
          '{ids["position"]}', 'sha256:{"e" * 64}', '{ids["instrument"]}', 'USD'
        );
        insert into public.portfolio_mandate_a1 (
          mandate_id, instrument_id, broker_position_id, owner_actor_id
        ) values (
          '{ids["mandate"]}', '{ids["instrument"]}', '{ids["position"]}',
          '{ids["actor"]}'
        );
        insert into public.portfolio_mandate_version_a1 (
          mandate_version_id, mandate_id, version_number, classification_state,
          horizon, approval_state, thesis, invalidation_conditions,
          approved_by_kind, approved_at, policy_version, effective_from
        ) values (
          '{ids["active_version"]}', '{ids["mandate"]}', 1, 'ACTIVE', 'SWING',
          'APPROVED', 'Active synthetic thesis', array['Active invalidation'],
          'USER', '2026-08-29T00:00:00Z', 'synthetic-v1',
          '2026-08-29T00:00:00Z'
        );
        insert into public.portfolio_mandate_version_a1 (
          mandate_version_id, mandate_id, version_number,
          supersedes_version_id, classification_state, horizon,
          proposed_horizon, approval_state, thesis, invalidation_conditions,
          approved_by_kind, approved_at, policy_version, effective_from
        ) values (
          '{ids["draft_version"]}', '{ids["mandate"]}', 2,
          '{ids["active_version"]}', 'UNCLASSIFIED', null, 'SWING', 'DRAFT',
          'Draft synthetic thesis', array['Draft invalidation'], null, null,
          'synthetic-v1', null
        );
        insert into public.portfolio_mandate_broker_snapshot_a1 (
          broker_position_snapshot_id, broker_position_id, snapshot_version,
          quantity, currency, watermark, sealed_input_hash, captured_at
        ) values (
          '{ids["snapshot"]}', '{ids["position"]}', 1, 10, 'USD',
          '{case}-snapshot', 'sha256:{"f" * 64}', '2026-08-29T00:00:00Z'
        );
        insert into public.portfolio_mandate_allocation_a1 (
          allocation_id, broker_position_id, allocation_version,
          snapshot_version, active, decision_eligible
        ) values ('{ids["allocation"]}', '{ids["position"]}', 1, 1, true, true);
        insert into public.portfolio_mandate_position_slice_a1 (
          slice_id, allocation_id, mandate_version_id, quantity, currency,
          classification_state, decision_eligible
        ) values (
          '{ids["slice"]}', '{ids["allocation"]}', '{ids["active_version"]}',
          10, 'USD', 'ACTIVE', true
        );
        insert into public.portfolio_mandate_journal_event_a1 (
          journal_event_id, command_id, aggregate_id, aggregate_version_id,
          event_type, actor_kind, event_payload, published_at
        ) values (
          '{ids["source_journal"]}', '{ids["source_command"]}',
          '{ids["mandate"]}', '{ids["active_version"]}', 'MANDATE_CREATED',
          'USER', '{{}}', '2026-08-29T00:00:00Z'
        );
        insert into public.portfolio_mandate_decision_projection_a1 (
          decision_id, mandate_version_id, slice_id, source_journal_event_id,
          projection_status, eligible, projection_version
        ) values (
          '{ids["decision"]}', '{ids["active_version"]}', '{ids["slice"]}',
          '{ids["source_journal"]}', 'ACTIVE', true, 1
        );
        """,
    )
    return ids


def _seed_evidence_scope_case(
    dsn: _DisposablePostgresConnection,
    *,
    case: str,
) -> dict[str, str]:
    ids = {
        name: _uuid(f"{case}:{name}")
        for name in (
            "issuer",
            "instrument_a",
            "instrument_b",
            "alias_a",
            "alias_b",
            "source",
            "command_a",
            "command_b",
            "seal_a",
            "seal_b",
        )
    }
    _psql(
        dsn,
        sql=f"""
        insert into public.portfolio_mandate_issuer_a1 (issuer_id, legal_name)
        values ('{ids["issuer"]}', 'Synthetic issuer {case}');
        insert into public.portfolio_mandate_issuer_identifier_a1 (
          issuer_id, identifier_scheme, identifier_value
        ) values ('{ids["issuer"]}', 'CIK', '0000000001');
        insert into public.portfolio_mandate_instrument_a1 (
          instrument_id, issuer_id, security_type, currency
        ) values
          ('{ids["instrument_a"]}', '{ids["issuer"]}', 'COMMON_STOCK', 'USD'),
          ('{ids["instrument_b"]}', '{ids["issuer"]}', 'COMMON_STOCK', 'USD');
        insert into public.portfolio_mandate_listing_alias_a1 (
          listing_alias_id, instrument_id, exchange_mic, ticker,
          valid_from, registry_version
        ) values
          (
            '{ids["alias_a"]}', '{ids["instrument_a"]}', 'XNAS', 'SYNA',
            '2026-01-01T00:00:00Z', 'synthetic-v1'
          ),
          (
            '{ids["alias_b"]}', '{ids["instrument_b"]}', 'XNAS', 'SYNB',
            '2026-01-01T00:00:00Z', 'synthetic-v1'
          );
        """,
    )
    return ids


def _seed_predicate_case(
    dsn: _DisposablePostgresConnection,
    *,
    case: str,
) -> dict[str, str]:
    ids = _seed_activation_case(dsn, case=case)
    ids.update(
        {
            name: _uuid(f"{case}:{name}")
            for name in (
                "source",
                "seal_command",
                "evidence_seal",
                "predicate",
                "authority_command",
                "authority_event",
                "free_text_command",
                "free_text_event",
                "candidate_command",
                "candidate_event",
            )
        }
    )
    identifier = f"SYNTHETIC-{case}"
    ticker = "S" + _uuid(f"{case}:ticker").replace("-", "")[:7].upper()
    _psql(
        dsn,
        sql=f"""
        insert into public.portfolio_mandate_issuer_identifier_a1 (
          issuer_id, identifier_scheme, identifier_value
        ) values ('{ids["issuer"]}', 'INTERNAL', '{identifier}');
        insert into public.portfolio_mandate_listing_alias_a1 (
          listing_alias_id, instrument_id, exchange_mic, ticker,
          valid_from, registry_version
        ) values (
          '{_uuid(f"{case}:alias")}', '{ids["instrument"]}', 'XNAS', '{ticker}',
          '2026-01-01T00:00:00Z', 'synthetic-v1'
        );
        insert into public.portfolio_mandate_predicate_definition_a1 (
          predicate_id, mandate_version_id, predicate_schema_version,
          metric, comparison_operator, threshold_value,
          expected_unit, expected_period, approval_state, approved_by_kind
        ) values (
          '{ids["predicate"]}', '{ids["active_version"]}', 'predicate-v1',
          'REVENUE', 'GTE', 100, 'USD', 'FY2026', 'APPROVED', 'USER'
        );
        """,
    )
    _psql(
        dsn,
        sql=f"""
        set role service_role;
        select * from public.seal_evidence_identity_a1(
          '{ids["seal_command"]}', '{ids["evidence_seal"]}', '{ids["source"]}',
          '{ids["instrument"]}', 'synthetic-v1', '2026-08-29T00:00:00Z',
          'INTERNAL', '{identifier}', 'INSTRUMENT', 'XNAS', '{ticker}',
          '2026-08-29T00:01:00Z', 'SOURCE_VALIDATOR'
        );
        """,
    )
    return ids


@pytest.fixture(scope="session")
def portfolio_mandate_postgres_dsn(
    tmp_path_factory: pytest.TempPathFactory,
    request: pytest.FixtureRequest,
) -> _DisposablePostgresConnection:
    if os.environ.get(_ALLOW_ENV) != "1":
        pytest.skip(f"set {_ALLOW_ENV}=1 for the approved disposable PostgreSQL run")
    dsn = os.environ.get(_DSN_ENV)
    if dsn is None:
        pytest.fail(f"{_DSN_ENV} is required when {_ALLOW_ENV}=1")
    expected_data_dir_raw = os.environ.get(_DATA_DIR_ENV)
    if expected_data_dir_raw is None:
        pytest.fail(f"{_DATA_DIR_ENV} is required when {_ALLOW_ENV}=1")
    try:
        harness_dir = tmp_path_factory.mktemp("portfolio-mandate-a1-harness")
        connection = _prepare_disposable_connection(dsn, harness_dir / "pgpass")
        request.addfinalizer(lambda: connection.pgpass_file.unlink(missing_ok=True))
        expected_data_dir = _validated_disposable_data_dir(expected_data_dir_raw)
    except (OSError, ValueError) as error:
        pytest.fail(str(error))
    parsed = urlparse(connection.dsn)
    database = unquote(parsed.path.removeprefix("/"))
    username = unquote(parsed.username or "")
    identity = _psql(
        connection,
        sql="""
        select concat_ws(E'\\t',
          host(inet_server_addr()),
          inet_server_port()::text,
          current_database(),
          current_setting('data_directory'),
          session_user,
          current_setting('server_version_num')
        );
        """,
    ).split("\t")
    expected_identity = [
        "127.0.0.1",
        str(parsed.port),
        database,
        str(expected_data_dir),
        username,
        _EXPECTED_SERVER_VERSION_NUM,
    ]
    if not _disposable_identity_matches(identity, expected_identity):
        pytest.fail(
            "disposable PostgreSQL server identity does not match opt-in values"
        )

    blank_state = _psql(
        connection,
        sql="""
        select concat_ws(',',
          not exists (
            select 1 from pg_catalog.pg_namespace
            where nspname not in (
              'pg_catalog', 'information_schema', 'pg_toast', 'public'
            )
              and nspname !~ '^pg_(temp|toast_temp)_'
          ),
          not exists (
            select 1 from pg_catalog.pg_class as relation
            join pg_catalog.pg_namespace as namespace
              on namespace.oid = relation.relnamespace
            where namespace.nspname = 'public'
          ),
          not exists (
            select 1 from pg_catalog.pg_proc as procedure
            join pg_catalog.pg_namespace as namespace
              on namespace.oid = procedure.pronamespace
            where namespace.nspname = 'public'
          ),
          not exists (
            select 1 from pg_catalog.pg_roles
            where rolname = 'portfolio_mandate_candidate_submitter_a1'
          )
        );
        """,
    )
    if not _disposable_database_is_blank(blank_state):
        pytest.fail(
            "disposable PostgreSQL database is not blank or candidate role exists"
        )

    _psql(
        connection,
        sql="""
        do $$
        begin
          if not exists (select 1 from pg_roles where rolname = 'anon') then
            create role anon nologin;
          end if;
          if not exists (
            select 1 from pg_roles where rolname = 'authenticated'
          ) then
            create role authenticated nologin;
          end if;
          if not exists (
            select 1 from pg_roles where rolname = 'service_role'
          ) then
            create role service_role nologin bypassrls;
          end if;
        end;
        $$;
        drop schema public cascade;
        drop schema if exists auth cascade;
        create schema public;
        create schema auth;
        create function auth.uid() returns uuid
        language sql stable
        set search_path = pg_catalog
        as $$
          select nullif(current_setting('request.jwt.claim.sub', true), '')::uuid
        $$;
        create schema if not exists extensions;
        """,
    )
    late_failure_migration = harness_dir / "late-failure-migration.sql"
    late_failure_migration.write_text(
        _MIGRATION.read_text(encoding="utf-8")
        + "\nselect 1 / 0 as deliberate_late_failure;\n",
        encoding="utf-8",
    )
    migration_error = _psql_error(connection, file=late_failure_migration)
    if "division by zero" not in migration_error:
        pytest.fail(
            "late-failure migration did not reach the rollback sentinel:\n"
            f"{migration_error}"
        )
    rollback_state = _psql(
        connection,
        sql="""
        select concat_ws(',',
          to_regclass('public.portfolio_mandate_a1') is null,
          not exists (
            select 1 from pg_roles
            where rolname = 'portfolio_mandate_candidate_submitter_a1'
          )
        );
        """,
    )
    if rollback_state != "t,t":
        pytest.fail("late migration failure left partial A1 schema or role state")
    _psql(connection, file=_MIGRATION)
    return connection


def test_a1_migration_applies_with_least_privilege_roles(
    portfolio_mandate_postgres_dsn: _DisposablePostgresConnection,
) -> None:
    privileges = _psql(
        portfolio_mandate_postgres_dsn,
        sql="""
        select concat_ws(',',
          has_schema_privilege('service_role', 'public', 'USAGE'),
          has_schema_privilege(
            'portfolio_mandate_candidate_submitter_a1', 'public', 'USAGE'
          ),
          has_table_privilege(
            'service_role',
            'public.portfolio_mandate_a1',
            'SELECT'
          ),
          has_table_privilege(
            'service_role',
            'public.portfolio_mandate_a1',
            'INSERT,UPDATE,DELETE'
          ),
          has_table_privilege(
            'portfolio_mandate_candidate_submitter_a1',
            'public.portfolio_mandate_a1',
            'SELECT,INSERT,UPDATE,DELETE'
          ),
          has_function_privilege(
            'portfolio_mandate_candidate_submitter_a1',
            'public.submit_predicate_candidate_a1('
              'uuid,uuid,uuid,uuid,uuid,uuid,text,text,text,'
              'boolean,boolean,timestamptz)',
            'EXECUTE'
          ),
          has_function_privilege(
            'portfolio_mandate_candidate_submitter_a1',
            'public.record_predicate_authority_a1('
              'uuid,uuid,uuid,uuid,text,text,text,uuid,uuid,text,text,numeric,'
              'text,text,text,text,text,text,boolean,boolean,uuid,timestamptz)',
            'EXECUTE'
          ),
          has_function_privilege(
            'authenticated',
            'public.activate_mandate_version_a1('
              'uuid,uuid,uuid,uuid,uuid,bigint,bigint)',
            'EXECUTE'
          ),
          has_function_privilege(
            'service_role',
            'public.activate_mandate_version_a1('
              'uuid,uuid,uuid,uuid,uuid,bigint,bigint)',
            'EXECUTE'
          ),
          (
            select not (
              rolcanlogin or rolinherit or rolsuper or rolcreatedb
              or rolcreaterole or rolreplication or rolbypassrls
            )
            from pg_catalog.pg_roles
            where rolname = 'portfolio_mandate_candidate_submitter_a1'
          ),
          (
            select count(*)
            from pg_catalog.pg_class as relation
            join pg_catalog.pg_namespace as namespace
              on namespace.oid = relation.relnamespace
            where namespace.nspname = 'public'
              and relation.relname like 'portfolio_mandate_%_a1'
              and relation.relkind = 'r'
              and (
                not relation.relrowsecurity
                or not relation.relforcerowsecurity
              )
          ),
          (
            select count(*)
            from pg_catalog.pg_class as relation
            join pg_catalog.pg_namespace as namespace
              on namespace.oid = relation.relnamespace
            where namespace.nspname = 'public'
              and relation.relname like 'portfolio_mandate_%_a1'
              and relation.relkind = 'r'
              and has_table_privilege(
                'service_role', relation.oid, 'INSERT,UPDATE,DELETE'
              )
          ),
          not exists (
            select 1
            from pg_catalog.pg_auth_members as membership
            join pg_catalog.pg_roles as candidate
              on candidate.oid = membership.member
            where candidate.rolname = 'portfolio_mandate_candidate_submitter_a1'
          )
        );
        """,
    )

    assert privileges == "t,t,t,f,f,t,f,t,f,t,0,0,t"


def test_migration_rejects_any_preexisting_candidate_role(
    portfolio_mandate_postgres_dsn: _DisposablePostgresConnection,
) -> None:
    error = _psql_error(
        portfolio_mandate_postgres_dsn,
        sql=_MIGRATION.read_text(encoding="utf-8"),
    )

    assert "CANDIDATE_ROLE_ALREADY_EXISTS" in error


def test_ambiguous_sell_rebase_commits_one_quarantined_allocation(
    portfolio_mandate_postgres_dsn: _DisposablePostgresConnection,
) -> None:
    ids = _seed_rebase_case(
        portfolio_mandate_postgres_dsn,
        case="ambiguous-sell",
        target_quantity="7",
        cause="ambiguous_sell",
        verification_state="UNRESOLVED",
        matched=False,
    )

    result = _psql(
        portfolio_mandate_postgres_dsn,
        sql=f"""
        set role service_role;
        select * from public.rebase_position_slices_a1(
          '{ids["command"]}', '{ids["event"]}', '{ids["evidence"]}',
          '{ids["position"]}', 1, 2, 7, 'USD', 'ambiguous_sell',
          null, null, 1, 'DETERMINISTIC'
        );
        """,
    )
    state = _psql(
        portfolio_mandate_postgres_dsn,
        sql=f"""
        set role service_role;
        select concat_ws(',',
          allocation.allocation_version,
          allocation.snapshot_version,
          allocation.active,
          allocation.decision_eligible,
          position_slice.quantity,
          position_slice.classification_state,
          rebase_event.rebase_cause,
          rebase_event.decision_eligible
        )
        from public.portfolio_mandate_allocation_a1 as allocation
        join public.portfolio_mandate_position_slice_a1 as position_slice
          on position_slice.allocation_id = allocation.allocation_id
        join public.portfolio_mandate_slice_rebase_event_a1 as rebase_event
          on rebase_event.broker_position_id = allocation.broker_position_id
          and rebase_event.target_allocation_version = allocation.allocation_version
        where allocation.broker_position_id = '{ids["position"]}'
          and allocation.active;
        """,
    )

    assert result == f"{ids['event']}|2|2|f|REBASED"
    assert state == "2,2,t,f,7,PENDING_ALLOCATION,AMBIGUOUS_SELL,f"


def test_rebase_retry_normalizes_cause_and_revalidates_actor(
    portfolio_mandate_postgres_dsn: _DisposablePostgresConnection,
) -> None:
    ids = _seed_rebase_case(
        portfolio_mandate_postgres_dsn,
        case="rebase-actor-revalidation",
        target_quantity="7",
        cause="ambiguous_sell",
        verification_state="UNRESOLVED",
        matched=False,
    )
    command = f"""
        set role service_role;
        select * from public.rebase_position_slices_a1(
          '{ids["command"]}', '{ids["event"]}', '{ids["evidence"]}',
          '{ids["position"]}', 1, 2, 7, 'USD', 'ambiguous_sell',
          null, null, 1, '{{actor}}'
        );
    """

    first_result = _psql(
        portfolio_mandate_postgres_dsn,
        sql=command.format(actor="DETERMINISTIC"),
    )
    retry_result = _psql(
        portfolio_mandate_postgres_dsn,
        sql=command.format(actor="DETERMINISTIC"),
    )
    error = _psql_error(
        portfolio_mandate_postgres_dsn,
        sql=command.format(actor="AI"),
    )

    assert first_result.endswith("|REBASED")
    assert retry_result.endswith("|ALREADY_REBASED")
    assert "ACTOR_NOT_AUTHORIZED" in error


def test_rebase_failure_rolls_back_all_allocation_slice_and_event_writes(
    portfolio_mandate_postgres_dsn: _DisposablePostgresConnection,
) -> None:
    ids = _seed_rebase_case(
        portfolio_mandate_postgres_dsn,
        case="corporate-action-rollback",
        target_quantity="19",
        cause="verified_corporate_action",
        verification_state="VERIFIED",
        matched=False,
        corporate_action_ratio="2",
    )

    error = _psql_error(
        portfolio_mandate_postgres_dsn,
        sql=f"""
        set role service_role;
        select * from public.rebase_position_slices_a1(
          '{ids["command"]}', '{ids["event"]}', '{ids["evidence"]}',
          '{ids["position"]}', 1, 2, 19, 'USD', 'verified_corporate_action',
          null, 2, 1, 'DETERMINISTIC'
        );
        """,
    )
    state = _psql(
        portfolio_mandate_postgres_dsn,
        sql=f"""
        select concat_ws(',',
          count(*) filter (where allocation.active),
          count(*),
          (select count(*)
           from public.portfolio_mandate_position_slice_a1 as position_slice
           join public.portfolio_mandate_allocation_a1 as slice_allocation
             on slice_allocation.allocation_id = position_slice.allocation_id
           where slice_allocation.broker_position_id = '{ids["position"]}'),
          (select count(*)
           from public.portfolio_mandate_slice_rebase_event_a1 as rebase_event
           where rebase_event.broker_position_id = '{ids["position"]}')
        )
        from public.portfolio_mandate_allocation_a1 as allocation
        where allocation.broker_position_id = '{ids["position"]}';
        """,
    )

    assert "SLICE_QUANTITY_MISMATCH" in error
    assert state == "1,1,1,0"


def test_concurrent_rebase_has_exactly_one_committed_target(
    portfolio_mandate_postgres_dsn: _DisposablePostgresConnection,
) -> None:
    ids = _seed_rebase_case(
        portfolio_mandate_postgres_dsn,
        case="concurrent-rebase",
        target_quantity="13",
        cause="unresolved_buy",
        verification_state="UNRESOLVED",
        matched=False,
    )
    commands = [
        (
            _uuid(f"concurrent-rebase:command:{index}"),
            _uuid(f"concurrent-rebase:event:{index}"),
        )
        for index in range(2)
    ]
    processes = [
        _psql_process(
            portfolio_mandate_postgres_dsn,
            sql=_barrier_sql(
                1001,
                f"""
                set role service_role;
                select * from public.rebase_position_slices_a1(
                  '{command_id}', '{event_id}', '{ids["evidence"]}',
                  '{ids["position"]}', 1, 2, 13, 'USD', 'unresolved_buy',
                  null, null, 1, 'DETERMINISTIC'
                );
                """,
            ),
        )
        for command_id, event_id in commands
    ]
    outcomes = [process.communicate(timeout=10) for process in processes]
    return_codes = [process.returncode for process in processes]
    state = _psql(
        portfolio_mandate_postgres_dsn,
        sql=f"""
        select concat_ws(',',
          (select count(*)
           from public.portfolio_mandate_slice_rebase_event_a1
           where broker_position_id = '{ids["position"]}'),
          (select count(*)
           from public.portfolio_mandate_allocation_a1
           where broker_position_id = '{ids["position"]}'),
          (select count(*)
           from public.portfolio_mandate_allocation_a1
           where broker_position_id = '{ids["position"]}' and active)
        );
        """,
    )

    assert any(code == 0 for code in return_codes), outcomes
    assert state == "1,2,1"


def test_activation_commits_version_slice_journal_and_projection_together(
    portfolio_mandate_postgres_dsn: _DisposablePostgresConnection,
) -> None:
    ids = _seed_activation_case(
        portfolio_mandate_postgres_dsn,
        case="activation-success",
    )

    result = _psql(
        portfolio_mandate_postgres_dsn,
        sql=f"""
        set role authenticated;
        set request.jwt.claim.role = 'authenticated';
        set request.jwt.claim.sub = '{ids["actor"]}';
        select * from public.activate_mandate_version_a1(
          '{ids["command"]}', '{ids["activation_event"]}', '{ids["mandate"]}',
          '{ids["draft_version"]}', '{ids["active_version"]}', 1, 1
        );
        """,
    )
    state = _psql(
        portfolio_mandate_postgres_dsn,
        sql=f"""
        set role service_role;
        select concat_ws(',',
          (select count(*)
           from public.portfolio_mandate_version_a1
           where mandate_id = '{ids["mandate"]}'
             and classification_state = 'ACTIVE'
             and approval_state = 'APPROVED'
             and effective_to is null),
          (select count(*)
           from public.portfolio_mandate_allocation_a1
           where broker_position_id = '{ids["position"]}' and active),
          (select count(*)
           from public.portfolio_mandate_position_slice_a1 as position_slice
           join public.portfolio_mandate_allocation_a1 as allocation
             on allocation.allocation_id = position_slice.allocation_id
           where allocation.broker_position_id = '{ids["position"]}'
             and allocation.active
             and position_slice.mandate_version_id = '{ids["draft_version"]}'),
          (select count(*)
           from public.portfolio_mandate_journal_event_a1
           where aggregate_id = '{ids["mandate"]}'
             and event_type = 'MANDATE_VERSION_ACTIVATED'),
          (select count(*)
           from public.portfolio_mandate_journal_event_a1
           where aggregate_id = '{ids["mandate"]}'
             and event_type = 'DECISION_SUPERSEDED'),
          (select count(*)
           from public.portfolio_mandate_decision_projection_a1
           where decision_id = '{ids["decision"]}'
             and projection_status = 'SUPERSEDED'
             and not eligible),
          (select count(*)
           from public.portfolio_mandate_activation_event_a1
           where mandate_id = '{ids["mandate"]}')
        );
        """,
    )

    assert result == (f"{ids['activation_event']}|{ids['draft_version']}|ACTIVATED")
    assert state == "1,1,1,1,1,1,1"


def test_t16_writer_projects_and_rebuilds_with_rollback(
    portfolio_mandate_postgres_dsn: _DisposablePostgresConnection,
) -> None:
    ids = _seed_activation_case(
        portfolio_mandate_postgres_dsn,
        case="t16-persistence-rehearsal",
    )
    command = T16ActivationCommand(
        command_id=uuid.UUID(ids["command"]),
        activation_event_id=uuid.UUID(ids["activation_event"]),
        mandate_id=uuid.UUID(ids["mandate"]),
        draft_mandate_version_id=uuid.UUID(ids["draft_version"]),
        expected_mandate_version_id=uuid.UUID(ids["active_version"]),
        actor_id=uuid.UUID(ids["actor"]),
        broker_snapshot_version=1,
        allocation_version=1,
        correction_command_id=uuid.uuid5(
            _UUID_NAMESPACE, "t16-persistence-rehearsal:correction-command"
        ),
        correction_event_id=uuid.uuid5(
            _UUID_NAMESPACE, "t16-persistence-rehearsal:correction-event"
        ),
    )
    prototype = PortfolioMandatePersistenceT16(
        lambda sql: _psql(portfolio_mandate_postgres_dsn, sql=sql),
        writer_enabled=True,
        target=T16DisposableTarget(
            port=urlparse(portfolio_mandate_postgres_dsn.dsn).port or 0,
            database_name=unquote(
                urlparse(portfolio_mandate_postgres_dsn.dsn).path.removeprefix("/")
            ),
            data_directory=os.environ[_DATA_DIR_ENV],
            session_user=unquote(
                urlparse(portfolio_mandate_postgres_dsn.dsn).username or ""
            ),
        ),
    )

    first = prototype.activate(command)
    retry = prototype.activate(command)
    projected_before = prototype.project(command)
    rehearsal = prototype.rebuild_and_rollback(command)
    projected_after = prototype.project(command)

    assert first["result_status"] == "ACTIVATED"
    assert retry["result_status"] == "ALREADY_ACTIVATED"
    assert projected_before == {
        "mandate_version_id": ids["active_version"],
        "projection_status": "SUPERSEDED",
        "eligible": False,
        "projection_version": 1,
    }
    assert rehearsal == {
        "append_only_guard": "ENFORCED",
        "correction_count": 1,
        "rebuilt_projection_count": 1,
        "transaction_outcome": "ROLLED_BACK",
    }
    assert projected_after == projected_before
    assert (
        _psql(
            portfolio_mandate_postgres_dsn,
            sql=f"""
        select count(*)
        from public.portfolio_mandate_journal_event_a1
        where journal_event_id = '{command.correction_event_id}';
        """,
        )
        == "0"
    )


def test_activation_retry_revalidates_actor_before_returning_existing_result(
    portfolio_mandate_postgres_dsn: _DisposablePostgresConnection,
) -> None:
    ids = _seed_activation_case(
        portfolio_mandate_postgres_dsn,
        case="activation-actor-revalidation",
    )
    command = f"""
        set role authenticated;
        set request.jwt.claim.role = 'authenticated';
        set request.jwt.claim.sub = '{{actor}}';
        select * from public.activate_mandate_version_a1(
          '{ids["command"]}', '{ids["activation_event"]}', '{ids["mandate"]}',
          '{ids["draft_version"]}', '{ids["active_version"]}', 1, 1
        );
    """

    first_result = _psql(
        portfolio_mandate_postgres_dsn,
        sql=command.format(actor=ids["actor"]),
    )
    retry_result = _psql(
        portfolio_mandate_postgres_dsn,
        sql=command.format(actor=ids["actor"]),
    )
    conflicting_event = _uuid("activation-actor-revalidation:conflict-event")
    conflict_error = _psql_error(
        portfolio_mandate_postgres_dsn,
        sql=command.replace(ids["activation_event"], conflicting_event).format(
            actor=ids["actor"]
        ),
    )
    other_actor_error = _psql_error(
        portfolio_mandate_postgres_dsn,
        sql=command.format(actor=_uuid("activation-actor-revalidation:other-actor")),
    )
    service_role_error = _psql_error(
        portfolio_mandate_postgres_dsn,
        sql=f"""
        set role service_role;
        select * from public.activate_mandate_version_a1(
          '{_uuid("activation-service-role:command")}',
          '{_uuid("activation-service-role:event")}', '{ids["mandate"]}',
          '{ids["draft_version"]}', '{ids["active_version"]}', 1, 1
        );
        """,
    )

    assert first_result.endswith("|ACTIVATED")
    assert retry_result.endswith("|ALREADY_ACTIVATED")
    assert "IDEMPOTENCY_CONFLICT" in conflict_error
    assert "IDEMPOTENCY_CONFLICT" in other_actor_error
    assert "permission denied for function activate_mandate_version_a1" in (
        service_role_error
    )


def test_activation_rejects_authenticated_non_owner_before_any_write(
    portfolio_mandate_postgres_dsn: _DisposablePostgresConnection,
) -> None:
    ids = _seed_activation_case(
        portfolio_mandate_postgres_dsn,
        case="activation-non-owner",
    )
    error = _psql_error(
        portfolio_mandate_postgres_dsn,
        sql=f"""
        set role authenticated;
        set request.jwt.claim.role = 'authenticated';
        set request.jwt.claim.sub = '{_uuid("activation-non-owner:other")}';
        select * from public.activate_mandate_version_a1(
          '{ids["command"]}', '{ids["activation_event"]}', '{ids["mandate"]}',
          '{ids["draft_version"]}', '{ids["active_version"]}', 1, 1
        );
        """,
    )
    event_count = _psql(
        portfolio_mandate_postgres_dsn,
        sql=f"""
        select count(*) from public.portfolio_mandate_activation_event_a1
        where mandate_id = '{ids["mandate"]}';
        """,
    )

    assert "ACTOR_NOT_AUTHORIZED" in error
    assert event_count == "0"


def test_concurrent_activation_has_exactly_one_winner(
    portfolio_mandate_postgres_dsn: _DisposablePostgresConnection,
) -> None:
    ids = _seed_activation_case(
        portfolio_mandate_postgres_dsn,
        case="concurrent-activation",
    )
    commands = [
        (
            _uuid(f"concurrent-activation:command:{index}"),
            _uuid(f"concurrent-activation:event:{index}"),
        )
        for index in range(2)
    ]
    processes = [
        _psql_process(
            portfolio_mandate_postgres_dsn,
            sql=_barrier_sql(
                1002,
                f"""
                set role authenticated;
                set request.jwt.claim.role = 'authenticated';
                set request.jwt.claim.sub = '{ids["actor"]}';
                select * from public.activate_mandate_version_a1(
                  '{command_id}', '{event_id}', '{ids["mandate"]}',
                  '{ids["draft_version"]}', '{ids["active_version"]}',
                  1, 1
                );
                """,
            ),
        )
        for command_id, event_id in commands
    ]
    outcomes = [process.communicate(timeout=10) for process in processes]
    return_codes = [process.returncode for process in processes]
    state = _psql(
        portfolio_mandate_postgres_dsn,
        sql=f"""
        select concat_ws(',',
          (select count(*)
           from public.portfolio_mandate_activation_event_a1
           where mandate_id = '{ids["mandate"]}'),
          (select count(*)
           from public.portfolio_mandate_version_a1
           where mandate_id = '{ids["mandate"]}'
             and classification_state = 'ACTIVE'
             and approval_state = 'APPROVED'
             and effective_to is null),
          (select count(*)
           from public.portfolio_mandate_allocation_a1
           where broker_position_id = '{ids["position"]}' and active)
        );
        """,
    )

    assert return_codes.count(0) == 1, outcomes
    assert state == "1,1,1"


def test_concurrent_instrument_scope_seal_has_exactly_one_winner(
    portfolio_mandate_postgres_dsn: _DisposablePostgresConnection,
) -> None:
    ids = _seed_evidence_scope_case(
        portfolio_mandate_postgres_dsn,
        case="concurrent-source-scope",
    )
    requests = (
        (ids["command_a"], ids["seal_a"], ids["instrument_a"], "SYNA"),
        (ids["command_b"], ids["seal_b"], ids["instrument_b"], "SYNB"),
    )
    processes = [
        _psql_process(
            portfolio_mandate_postgres_dsn,
            sql=_barrier_sql(
                1003,
                f"""
                set role service_role;
                select * from public.seal_evidence_identity_a1(
                  '{command_id}', '{seal_id}', '{ids["source"]}',
                  '{instrument_id}', 'synthetic-v1',
                  '2026-08-29T00:00:00Z', 'CIK', '0000000001', 'INSTRUMENT',
                  'XNAS', '{ticker}', '2026-08-29T00:01:00Z',
                  'SOURCE_VALIDATOR'
                );
                """,
            ),
        )
        for command_id, seal_id, instrument_id, ticker in requests
    ]
    outcomes = [process.communicate(timeout=10) for process in processes]
    return_codes = [process.returncode for process in processes]
    seal_count = _psql(
        portfolio_mandate_postgres_dsn,
        sql=f"""
        select count(*)
        from public.portfolio_mandate_evidence_seal_a1
        where source_id = '{ids["source"]}';
        """,
    )

    assert return_codes.count(0) == 1, outcomes
    assert any("SOURCE_SCOPE_CONFLICT" in stderr for _, stderr in outcomes)
    assert seal_count == "1"


def test_predicate_authority_requires_structured_evidence_and_is_append_only(
    portfolio_mandate_postgres_dsn: _DisposablePostgresConnection,
) -> None:
    ids = _seed_predicate_case(
        portfolio_mandate_postgres_dsn,
        case="predicate-authority",
    )
    authority_call = f"""
        set role service_role;
        select * from public.record_predicate_authority_a1(
          '{{command}}', '{{event}}', '{ids["active_version"]}',
          '{ids["predicate"]}', 'PREDICATE_FULFILLED',
          'DETERMINISTIC_PARSER', 'DETERMINISTIC', '{ids["source"]}',
          '{ids["evidence_seal"]}', 'Revenue exceeded 100 USD', 'REVENUE', 101,
          'USD', 'FY2026', 'parser-v1', 'predicate-v1', null, null,
          {{structured}}, {{free_text}}, null, '2026-08-29T00:02:00Z'
        );
    """

    result = _psql(
        portfolio_mandate_postgres_dsn,
        sql=authority_call.format(
            command=ids["authority_command"],
            event=ids["authority_event"],
            structured="true",
            free_text="false",
        ),
    )
    free_text_error = _psql_error(
        portfolio_mandate_postgres_dsn,
        sql=authority_call.format(
            command=ids["free_text_command"],
            event=ids["free_text_event"],
            structured="false",
            free_text="true",
        ),
    )
    false_predicate_error = _psql_error(
        portfolio_mandate_postgres_dsn,
        sql=authority_call.replace("'REVENUE', 101", "'REVENUE', 99").format(
            command=_uuid("predicate-authority:false-command"),
            event=_uuid("predicate-authority:false-event"),
            structured="true",
            free_text="false",
        ),
    )
    special_predicate_error = _psql_error(
        portfolio_mandate_postgres_dsn,
        sql=authority_call.replace(
            "'REVENUE', 101", "'REVENUE', 'NaN'::numeric"
        ).format(
            command=_uuid("predicate-authority:special-command"),
            event=_uuid("predicate-authority:special-event"),
            structured="true",
            free_text="false",
        ),
    )
    append_only_error = _psql_error(
        portfolio_mandate_postgres_dsn,
        sql=f"""
        update public.portfolio_mandate_predicate_authority_event_a1
        set reason = 'mutated'
        where predicate_authority_event_id = '{ids["authority_event"]}';
        """,
    )
    event_count = _psql(
        portfolio_mandate_postgres_dsn,
        sql=f"""
        select count(*)
        from public.portfolio_mandate_predicate_authority_event_a1
        where predicate_id = '{ids["predicate"]}';
        """,
    )

    assert result == (
        f"{ids['authority_event']}|PREDICATE_FULFILLED|SELL_ELIGIBLE|RECORDED"
    )
    assert "FREE_TEXT_REVIEW_REQUIRED" in free_text_error
    assert "PREDICATE_NOT_FULFILLED" in false_predicate_error
    assert "PREDICATE_NUMERIC_NOT_FINITE" in special_predicate_error
    assert "APPEND_ONLY_EVENT" in append_only_error
    assert event_count == "1"


def test_user_predicate_confirmation_requires_matching_authenticated_actor(
    portfolio_mandate_postgres_dsn: _DisposablePostgresConnection,
) -> None:
    ids = _seed_predicate_case(
        portfolio_mandate_postgres_dsn,
        case="predicate-user-confirmation",
    )
    actor_id = ids["actor"]
    call = f"""
        set role authenticated;
        set request.jwt.claim.role = 'authenticated';
        set request.jwt.claim.sub = '{actor_id}';
        select * from public.record_predicate_authority_a1(
          '{{command}}', '{{event}}', '{ids["active_version"]}',
          '{ids["predicate"]}', 'USER_PREDICATE_CONFIRMED', 'USER', 'USER',
          '{ids["source"]}', '{ids["evidence_seal"]}', 'Reviewed source span',
          null, null, null, null, null, 'predicate-v1', '{{actor}}',
          'User reviewed the exact source', true, false, null,
          '2026-08-29T00:05:00Z'
        );
    """

    result = _psql(
        portfolio_mandate_postgres_dsn,
        sql=call.format(
            command=_uuid("predicate-user-confirmation:command"),
            event=_uuid("predicate-user-confirmation:event"),
            actor=actor_id,
        ),
    )
    mismatch_error = _psql_error(
        portfolio_mandate_postgres_dsn,
        sql=call.format(
            command=_uuid("predicate-user-confirmation:mismatch-command"),
            event=_uuid("predicate-user-confirmation:mismatch-event"),
            actor=_uuid("predicate-user-confirmation:spoofed-actor"),
        ),
    )
    other_actor_id = _uuid("predicate-user-confirmation:other-actor")
    non_owner_error = _psql_error(
        portfolio_mandate_postgres_dsn,
        sql=call.replace(actor_id, other_actor_id).format(
            command=_uuid("predicate-user-confirmation:non-owner-command"),
            event=_uuid("predicate-user-confirmation:non-owner-event"),
            actor=other_actor_id,
        ),
    )
    service_role_error = _psql_error(
        portfolio_mandate_postgres_dsn,
        sql=call.replace("set role authenticated;", "set role service_role;")
        .replace("set request.jwt.claim.role = 'authenticated';", "")
        .replace(f"set request.jwt.claim.sub = '{actor_id}';", "")
        .format(
            command=_uuid("predicate-user-confirmation:service-command"),
            event=_uuid("predicate-user-confirmation:service-event"),
            actor=actor_id,
        ),
    )

    assert result.endswith("|USER_PREDICATE_CONFIRMED|SELL_ELIGIBLE|RECORDED")
    assert "ACTOR_IDENTITY_MISMATCH" in mismatch_error
    assert "ACTOR_NOT_AUTHORIZED" in non_owner_error
    assert "AUTHENTICATED_USER_REQUIRED" in service_role_error


def test_database_rejects_numeric_scales_outside_public_contract(
    portfolio_mandate_postgres_dsn: _DisposablePostgresConnection,
) -> None:
    ids = _seed_activation_case(
        portfolio_mandate_postgres_dsn,
        case="numeric-scale",
    )
    quantity_error = _psql_error(
        portfolio_mandate_postgres_dsn,
        sql=f"""
        insert into public.portfolio_mandate_broker_snapshot_a1 (
          broker_position_snapshot_id, broker_position_id, snapshot_version,
          quantity, currency, watermark, sealed_input_hash, captured_at
        ) values (
          '{_uuid("numeric-scale:snapshot")}', '{ids["position"]}', 2,
          1.0000001, 'USD', 'numeric-scale-rejected',
          'sha256:{"1" * 64}', '2026-08-29T00:02:00Z'
        );
        """,
    )
    threshold_error = _psql_error(
        portfolio_mandate_postgres_dsn,
        sql=f"""
        insert into public.portfolio_mandate_predicate_definition_a1 (
          predicate_id, mandate_version_id, predicate_schema_version, metric,
          comparison_operator, threshold_value, expected_unit, expected_period,
          approval_state, approved_by_kind
        ) values (
          '{_uuid("numeric-scale:predicate")}', '{ids["active_version"]}',
          'numeric-scale-v1', 'REVENUE', 'GTE', 1.0000001, 'USD', 'FY2026',
          'APPROVED', 'USER'
        );
        """,
    )
    special_quantity_error = _psql_error(
        portfolio_mandate_postgres_dsn,
        sql=f"""
        insert into public.portfolio_mandate_broker_snapshot_a1 (
          broker_position_snapshot_id, broker_position_id, snapshot_version,
          quantity, currency, watermark, sealed_input_hash, captured_at
        ) values (
          '{_uuid("numeric-scale:special-snapshot")}', '{ids["position"]}', 2,
          'NaN'::numeric, 'USD', 'numeric-special-rejected',
          'sha256:{"2" * 64}', '2026-08-29T00:02:00Z'
        );
        """,
    )
    special_threshold_error = _psql_error(
        portfolio_mandate_postgres_dsn,
        sql=f"""
        insert into public.portfolio_mandate_predicate_definition_a1 (
          predicate_id, mandate_version_id, predicate_schema_version, metric,
          comparison_operator, threshold_value, expected_unit, expected_period,
          approval_state, approved_by_kind
        ) values (
          '{_uuid("numeric-scale:special-predicate")}',
          '{ids["active_version"]}', 'numeric-special-v1', 'REVENUE', 'GTE',
          'Infinity'::numeric, 'USD', 'FY2026', 'APPROVED', 'USER'
        );
        """,
    )

    assert "portfolio_mandate_broker_snapshot_a1_quantity_check" in quantity_error
    assert "portfolio_mandate_predicate_definition_a1_threshold_value_check" in (
        threshold_error
    )
    assert "portfolio_mandate_broker_snapshot_a1_quantity_check" in (
        special_quantity_error
    )
    assert "portfolio_mandate_predicate_definition_a1_threshold_value_check" in (
        special_threshold_error
    )


def test_candidate_role_can_submit_review_only_but_cannot_write_authority(
    portfolio_mandate_postgres_dsn: _DisposablePostgresConnection,
) -> None:
    ids = _seed_predicate_case(
        portfolio_mandate_postgres_dsn,
        case="predicate-candidate-role",
    )

    candidate_result = _psql(
        portfolio_mandate_postgres_dsn,
        sql=f"""
        set role portfolio_mandate_candidate_submitter_a1;
        select * from public.submit_predicate_candidate_a1(
          '{ids["candidate_command"]}', '{ids["candidate_event"]}',
          '{ids["active_version"]}', '{ids["predicate"]}', '{ids["source"]}',
          '{ids["evidence_seal"]}', 'Possible predicate match', 'predicate-v1',
          'Synthetic candidate only', true, false,
          '2026-08-29T00:03:00Z'
        );
        """,
    )
    authority_error = _psql_error(
        portfolio_mandate_postgres_dsn,
        sql=f"""
        set role portfolio_mandate_candidate_submitter_a1;
        select * from public.record_predicate_authority_a1(
          '{ids["authority_command"]}', '{ids["authority_event"]}',
          '{ids["active_version"]}', '{ids["predicate"]}',
          'PREDICATE_FULFILLED', 'DETERMINISTIC_PARSER', 'DETERMINISTIC',
          '{ids["source"]}', '{ids["evidence_seal"]}', 'Revenue exceeded',
          'REVENUE', 101, 'USD', 'FY2026', 'parser-v1', 'predicate-v1', null, null,
          true, false, null, '2026-08-29T00:04:00Z'
        );
        """,
    )
    table_error = _psql_error(
        portfolio_mandate_postgres_dsn,
        sql="""
        set role portfolio_mandate_candidate_submitter_a1;
        select count(*) from public.portfolio_mandate_predicate_authority_event_a1;
        """,
    )

    assert candidate_result == (
        f"{ids['candidate_event']}|PREDICATE_CANDIDATE|REVIEW_ONLY|RECORDED"
    )
    assert "permission denied for function record_predicate_authority_a1" in (
        authority_error
    )
    assert "permission denied" in table_error
