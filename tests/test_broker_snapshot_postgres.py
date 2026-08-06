from __future__ import annotations

import json
import os
import subprocess
import time
from collections.abc import Mapping
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import pytest
from sab.scheduler.holdings import broker_holdings_digest_v0

_OPT_IN = "BROKER_SNAPSHOT_TEST_DISPOSABLE"
_DATABASE_SUFFIX = "_broker_snapshot_test"
_LOOPBACK_HOSTS = frozenset({"127.0.0.1", "localhost", "::1"})


def _validated_pg_env(source: Mapping[str, str]) -> dict[str, str]:
    if source.get("BROKER_SNAPSHOT_TEST_DATABASE_URL"):
        raise ValueError(
            "database URLs are forbidden; use libpq PG environment variables"
        )
    if source.get(_OPT_IN) != "1":
        raise ValueError(f"{_OPT_IN}=1 is required for disposable database tests")
    host = source.get("PGHOST", "").strip().lower()
    if host not in _LOOPBACK_HOSTS:
        raise ValueError("PGHOST must be an explicit loopback host")
    database = source.get("PGDATABASE", "").strip()
    if not database.endswith(_DATABASE_SUFFIX):
        raise ValueError(f"PGDATABASE must end with {_DATABASE_SUFFIX}")
    if not source.get("PGUSER", "").strip():
        raise ValueError("PGUSER must be set")

    env = dict(os.environ)
    env.pop("BROKER_SNAPSHOT_TEST_DATABASE_URL", None)
    for name in (
        "PGHOST",
        "PGPORT",
        "PGUSER",
        "PGPASSWORD",
        "PGDATABASE",
        "PGSSLMODE",
    ):
        if name in source:
            env[name] = source[name]
    return env


@pytest.mark.parametrize(
    ("overrides", "message"),
    [
        ({_OPT_IN: "0"}, f"{_OPT_IN}=1"),
        ({_OPT_IN: "1", "PGHOST": "db.example.com"}, "loopback"),
        (
            {_OPT_IN: "1", "PGHOST": "127.0.0.1", "PGDATABASE": "postgres"},
            _DATABASE_SUFFIX,
        ),
        (
            {
                _OPT_IN: "1",
                "PGHOST": "127.0.0.1",
                "PGDATABASE": f"safe{_DATABASE_SUFFIX}",
                "BROKER_SNAPSHOT_TEST_DATABASE_URL": "postgresql://forbidden",
            },
            "URLs are forbidden",
        ),
    ],
)
def test_destructive_database_misconfiguration_is_rejected_before_execution(
    overrides: dict[str, str], message: str
) -> None:
    source = {"PGUSER": "postgres", **overrides}

    with pytest.raises(ValueError, match=message):
        _validated_pg_env(source)


def _integration_env() -> dict[str, str]:
    try:
        return _validated_pg_env(os.environ)
    except ValueError as error:
        pytest.skip(str(error))


def _psql(
    sql: str,
    *,
    env: Mapping[str, str],
    succeeds: bool = True,
) -> subprocess.CompletedProcess[str]:
    result = subprocess.run(
        ["psql", "-X", "-qAt", "-v", "ON_ERROR_STOP=1", "-F", "\t", "-c", sql],
        check=False,
        capture_output=True,
        text=True,
        env=env,
    )
    assert (result.returncode == 0) is succeeds, result.stderr
    return result


def _transaction(sql: str, *, env: Mapping[str, str]) -> str:
    isolation = (
        "delete from public.broker_snapshot_v0; "
        "delete from public.runtime_state; "
        "delete from public.holdings;"
    )
    return _psql(f"begin;\n{isolation}\n{sql}\nrollback;", env=env).stdout.strip()


@pytest.mark.parametrize(
    ("quantity", "price"),
    [
        ("0.000001", "0.0001"),
        ("99999999999999.999999", "9999999999999999.9999"),
    ],
)
def test_web_mutation_rpc_preserves_numeric_boundaries_and_db_digest(
    quantity: str, price: str
) -> None:
    env = _integration_env()
    output = _transaction(
        "set role service_role; "
        "select post_state_digest from public.apply_broker_holdings_replace_v0("
        "jsonb_build_array(jsonb_build_object("
        "'ticker', 'AAPL.NAS', "
        f"'quantity', '{quantity}', 'entry_price', '{price}', "
        f"'stop_override', '{price}', 'target_override', '{price}', "
        "'tags', '[]'::jsonb)), '[]'::jsonb); "
        "select collected.holdings::text, collected.holdings_digest "
        "from broker_snapshot_private.collect_broker_holdings_v0() collected;",
        env=env,
    )
    post_digest, collected = output.splitlines()
    holdings_json, collected_digest = collected.split("\t", 1)
    holdings = json.loads(holdings_json)

    assert holdings[0]["quantity"] == quantity
    assert holdings[0]["entry_price"] == price
    assert holdings[0]["stop_override"] == price
    assert holdings[0]["target_override"] == price
    assert post_digest == collected_digest
    assert broker_holdings_digest_v0(holdings) == collected_digest


def test_normal_mutation_clears_entry_pattern_when_quantity_becomes_zero() -> None:
    env = _integration_env()
    output = _transaction(
        "insert into public.holdings (ticker, quantity, entry_price, entry_pattern, tags) "
        "values ('AAPL.NAS', 1, 100, 'trend_pullback_bounce', '{}'::text[]); "
        "set role service_role; "
        "select post_state_digest from public.apply_broker_holdings_replace_v0("
        '\'[ {"ticker":"AAPL.NAS","quantity":0,'
        '"entry_price":100,"tags":[]} ]\'::jsonb, null); '
        "select holdings.entry_pattern, collected.holdings_digest "
        "from public.holdings holdings cross join lateral "
        "broker_snapshot_private.collect_broker_holdings_v0() collected "
        "where holdings.ticker = 'AAPL.NAS';",
        env=env,
    )
    post_digest, collected = output.splitlines()
    entry_pattern, collected_digest = collected.split("\t", 1)

    assert entry_pattern == ""
    assert post_digest == collected_digest


def test_quarantine_mutation_clears_entry_pattern_when_target_becomes_zero() -> None:
    env = _integration_env()
    output = _transaction(
        "insert into public.holdings (ticker, quantity, entry_price, entry_pattern, tags) values "
        "('AAPL.NAS', 1, 100, 'trend_pullback_bounce', '{}'::text[]), "
        "('MSFT.NAS', 1, 50, null, '{}'::text[]); "
        "set role service_role; "
        "select post_state_digest from public.apply_broker_holdings_quarantine_v0("
        '\'[ {"ticker":"AAPL.NAS","quantity":0,'
        '"entry_price":100,"tags":[]} ]\'::jsonb, '
        "array['MSFT.NAS'], "
        '\'[ {"ticker":"AAPL.NAS","quantity":1,'
        '"entry_price":100,"entry_pattern":"trend_pullback_bounce",'
        '"tags":[],"broker_state":"confirmed","broker_missing_count":0},'
        '{"ticker":"MSFT.NAS","quantity":1,'
        '"entry_price":50,"entry_pattern":null,"tags":[],'
        '"broker_state":"confirmed","broker_missing_count":0} ]\'::jsonb, '
        "current_date, 'test-diff'); "
        "select holdings.entry_pattern, collected.holdings_digest "
        "from public.holdings holdings cross join lateral "
        "broker_snapshot_private.collect_broker_holdings_v0() collected "
        "where holdings.ticker = 'AAPL.NAS';",
        env=env,
    )
    post_digest, collected = output.splitlines()
    entry_pattern, collected_digest = collected.split("\t", 1)

    assert entry_pattern == ""
    assert post_digest == collected_digest


def test_replace_wrapper_returns_db_digest_after_delete() -> None:
    env = _integration_env()
    output = _transaction(
        "insert into public.holdings (ticker, quantity, entry_price, tags) values "
        "('AAPL.NAS', 1, 100, '{}'::text[]), "
        "('MSFT.NAS', 1, 50, '{}'::text[]); "
        "set role service_role; "
        "select post_state_digest from public.apply_broker_holdings_replace_v0("
        '\'[ {"ticker":"AAPL.NAS","quantity":1,'
        '"entry_price":100,"tags":[]} ]\'::jsonb, null); '
        "select count(*), collected.holdings_digest "
        "from public.holdings cross join lateral "
        "broker_snapshot_private.collect_broker_holdings_v0() collected "
        "group by collected.holdings_digest;",
        env=env,
    )
    post_digest, collected = output.splitlines()
    row_count, collected_digest = collected.split("\t", 1)

    assert row_count == "1"
    assert post_digest == collected_digest


def test_future_session_cannot_poison_revision_or_marker() -> None:
    env = _integration_env()
    current_session = datetime.now(ZoneInfo("Asia/Seoul")).date().isoformat()
    output = _transaction(
        "set role service_role; "
        "do $$ begin "
        "begin perform * from public.seal_broker_snapshot_v0("
        "'toss-sync:success:MIXED:2099-01-01', date '2099-01-01', 'unchanged', "
        "now() + interval '1 day', '{}'::jsonb, "
        "(select holdings_digest from public.capture_broker_holdings_digest_v0("
        "(select holdings_digest from public.get_broker_holdings_state_v0())))); "
        "raise exception 'future session unexpectedly accepted'; "
        "exception when serialization_failure then "
        "if sqlerrm <> 'BrokerSnapshotV0 future session' then raise; end if; end; "
        "end $$; "
        "select count(*), "
        "(select count(*) from public.runtime_state) from public.broker_snapshot_v0; "
        "select revision from public.seal_broker_snapshot_v0("
        f"'toss-sync:success:MIXED:{current_session}', date '{current_session}', "
        "'unchanged', now() + interval '1 day', '{}'::jsonb, "
        "(select holdings_digest from public.capture_broker_holdings_digest_v0("
        "(select holdings_digest from public.get_broker_holdings_state_v0()))));",
        env=env,
    ).splitlines()

    assert output[0] == "0\t0"
    assert output[1] == "1"


def test_same_session_retry_advances_and_past_session_still_fails() -> None:
    env = _integration_env()
    current = datetime.now(ZoneInfo("Asia/Seoul")).date()
    current_session = current.isoformat()
    past_session = (current - timedelta(days=1)).isoformat()
    output = _transaction(
        "set role service_role; "
        "select revision from public.seal_broker_snapshot_v0("
        f"'toss-sync:success:MIXED:{current_session}', date '{current_session}', "
        "'unchanged', now() + interval '1 day', '{}'::jsonb, "
        "(select holdings_digest from public.get_broker_holdings_state_v0())); "
        "select revision from public.seal_broker_snapshot_v0("
        f"'toss-sync:success:MIXED:{current_session}', date '{current_session}', "
        "'unchanged', now() + interval '1 day', '{}'::jsonb, "
        "(select holdings_digest from public.get_broker_holdings_state_v0())); "
        "do $$ begin begin perform * from public.seal_broker_snapshot_v0("
        f"'toss-sync:success:MIXED:{past_session}', date '{past_session}', "
        "'unchanged', now() + interval '1 day', '{}'::jsonb, "
        "(select holdings_digest from public.get_broker_holdings_state_v0())); "
        "raise exception 'past session unexpectedly accepted'; "
        "exception when serialization_failure then "
        "if sqlerrm <> 'BrokerSnapshotV0 session regression' then raise; end if; end; "
        "end $$; select session_date::text, revision from public.broker_snapshot_v0;",
        env=env,
    ).splitlines()

    assert output == ["1", "2", f"{current_session}\t2"]


def test_two_connection_writer_commit_makes_capture_and_seal_fail_closed() -> None:
    env = _integration_env()
    session = datetime.now(ZoneInfo("Asia/Seoul")).date().isoformat()
    _psql(
        "insert into public.holdings (ticker, quantity, entry_price, tags) "
        "values ('NVDA.NAS', 1, 100, '{}'::text[]) "
        "on conflict (ticker) do update set quantity = excluded.quantity, "
        "entry_price = excluded.entry_price, tags = excluded.tags;",
        env=env,
    )
    initial_digest = _psql(
        "set role service_role; select holdings_digest "
        "from public.get_broker_holdings_state_v0();",
        env=env,
    ).stdout.strip()
    _psql(
        "set role service_role; select revision from public.seal_broker_snapshot_v0("
        f"'toss-sync:success:MIXED:{session}', date '{session}', 'applied', "
        f"now() + interval '1 day', '{{}}'::jsonb, '{initial_digest}');",
        env=env,
    )
    before = _psql(
        "select snapshot.revision, md5(snapshot.marker_payload::text), "
        "md5(runtime.state_payload::text) from public.broker_snapshot_v0 snapshot "
        "join public.runtime_state runtime on runtime.state_key = snapshot.state_key;",
        env=env,
    ).stdout.strip()

    writer = subprocess.Popen(
        ["psql", "-X", "-qAt", "-v", "ON_ERROR_STOP=1"],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        env={**env, "PGAPPNAME": "broker_snapshot_writer"},
    )
    assert writer.stdin is not None and writer.stdout is not None
    writer.stdin.write(
        "begin; update public.holdings set quantity = 2 "
        "where ticker = 'NVDA.NAS'; select 'writer_locked';\n"
    )
    writer.stdin.flush()
    assert writer.stdout.readline().strip() == "writer_locked"

    seal = subprocess.Popen(
        [
            "psql",
            "-X",
            "-qAt",
            "-v",
            "ON_ERROR_STOP=1",
            "-c",
            "set role service_role; select * from public.seal_broker_snapshot_v0("
            f"'toss-sync:success:MIXED:{session}', date '{session}', 'applied', "
            f"now() + interval '1 day', '{{}}'::jsonb, '{initial_digest}');",
        ],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        env={**env, "PGAPPNAME": "broker_snapshot_seal_waiter"},
    )
    capture = subprocess.Popen(
        [
            "psql",
            "-X",
            "-qAt",
            "-v",
            "ON_ERROR_STOP=1",
            "-c",
            "set role service_role; select * from "
            "public.capture_broker_holdings_digest_v0("
            f"'{initial_digest}');",
        ],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        env={**env, "PGAPPNAME": "broker_snapshot_capture_waiter"},
    )
    time.sleep(0.2)
    assert seal.poll() is None
    assert capture.poll() is None
    waiting = _psql(
        "select string_agg(application_name, ',' order by application_name) "
        "from pg_stat_activity where wait_event_type = 'Lock' and "
        "application_name in ('broker_snapshot_seal_waiter', "
        "'broker_snapshot_capture_waiter');",
        env=env,
    ).stdout.strip()
    assert waiting == ("broker_snapshot_capture_waiter,broker_snapshot_seal_waiter")

    writer.stdin.write("commit;\\q\n")
    writer.stdin.flush()
    writer.wait(timeout=5)
    seal_stdout, seal_stderr = seal.communicate(timeout=5)
    capture_stdout, capture_stderr = capture.communicate(timeout=5)

    assert writer.returncode == 0
    assert seal.returncode != 0, seal_stdout
    assert "post-state digest mismatch" in seal_stderr
    assert capture.returncode != 0, capture_stdout
    assert "pre-state conflict" in capture_stderr
    after = _psql(
        "select snapshot.revision, md5(snapshot.marker_payload::text), "
        "md5(runtime.state_payload::text) from public.broker_snapshot_v0 snapshot "
        "join public.runtime_state runtime on runtime.state_key = snapshot.state_key;",
        env=env,
    ).stdout.strip()
    assert after == before
