from __future__ import annotations

import json
import os
import subprocess

import pytest
from sab.scheduler.holdings import broker_holdings_digest_v0

_DATABASE_URL = os.getenv("BROKER_SNAPSHOT_TEST_DATABASE_URL")
pytestmark = pytest.mark.skipif(
    not _DATABASE_URL,
    reason="BROKER_SNAPSHOT_TEST_DATABASE_URL is not configured",
)


def _psql(sql: str, *, succeeds: bool = True) -> subprocess.CompletedProcess[str]:
    assert _DATABASE_URL is not None
    result = subprocess.run(
        [
            "psql",
            "-X",
            "-v",
            "ON_ERROR_STOP=1",
            "-At",
            "-F",
            "\t",
            _DATABASE_URL,
            "-c",
            sql,
        ],
        check=False,
        capture_output=True,
        text=True,
    )
    assert (result.returncode == 0) is succeeds, result.stderr
    return result


def _reset() -> None:
    _psql("truncate public.broker_snapshot_v0, public.runtime_state, public.holdings")


@pytest.mark.parametrize("boundary", ["0.0001", "9999999999999999.9999"])
def test_numeric_20_4_boundary_matches_python_digest(boundary: str) -> None:
    _reset()
    _psql(
        "insert into public.holdings ("
        "ticker, quantity, entry_price, tags, stop_override, target_override"
        ") values ("
        f"'AAPL.NAS', 1, {boundary}, '{{}}'::text[], {boundary}, {boundary}"
        ")"
    )

    result = _psql(
        "select holdings::text, holdings_digest "
        "from broker_snapshot_private.collect_broker_holdings_v0()"
    )
    holdings_json, database_digest = result.stdout.strip().split("\t", 1)
    holdings = json.loads(holdings_json)

    assert holdings[0]["entry_price"] == boundary
    assert holdings[0]["stop_override"] == boundary
    assert holdings[0]["target_override"] == boundary
    assert broker_holdings_digest_v0(holdings) == database_digest


def test_mutation_before_seal_rejects_cas_without_advancing_revision() -> None:
    _reset()
    _psql(
        "insert into public.holdings (ticker, quantity, entry_price, tags) "
        "values ('AAPL.NAS', 1, 100, '{}'::text[])"
    )
    expected_digest = broker_holdings_digest_v0(
        [
            {
                "ticker": "AAPL.NAS",
                "quantity": "1.000000",
                "entry_price": "100.0000",
                "entry_currency": None,
                "entry_date": None,
                "strategy": None,
                "entry_pattern": None,
                "notes": None,
                "tags": [],
                "stop_override": None,
                "target_override": None,
                "broker_state": "confirmed",
                "broker_missing_first_seen_date": None,
                "broker_missing_last_seen_date": None,
                "broker_missing_count": 0,
                "broker_missing_diff_hash": None,
            }
        ]
    )
    _psql("update public.holdings set quantity = 2 where ticker = 'AAPL.NAS'")

    failed = _psql(
        "set role service_role; "
        "select * from public.seal_broker_snapshot_v0("
        "'toss-sync:success:MIXED:2026-08-06', '2026-08-06', 'applied', "
        f"now() + interval '1 day', '{{}}'::jsonb, '{expected_digest}'"
        ")",
        succeeds=False,
    )

    assert "post-state digest mismatch" in failed.stderr
    assert _psql("select count(*) from public.broker_snapshot_v0").stdout.strip() == "0"
    assert _psql("select count(*) from public.runtime_state").stdout.strip() == "0"


def test_session_regression_rolls_back_but_same_session_retry_advances() -> None:
    _reset()
    digest = broker_holdings_digest_v0([])
    seal = (
        "set role service_role; "
        "select revision from public.seal_broker_snapshot_v0("
        "'toss-sync:success:MIXED:{session}', '{session}', 'unchanged', "
        f"now() + interval '2 days', '{{{{}}}}'::jsonb, '{digest}'"
        ")"
    )

    assert _psql(seal.format(session="2026-08-06")).stdout.strip().endswith("1")
    assert _psql(seal.format(session="2026-08-06")).stdout.strip().endswith("2")
    replay = _psql(seal.format(session="2026-08-05"), succeeds=False)

    assert "session regression" in replay.stderr
    state = _psql(
        "select session_date::text, revision from public.broker_snapshot_v0"
    ).stdout.strip()
    assert state == "2026-08-06\t2"
    assert (
        _psql(
            "select count(*) from public.runtime_state "
            "where state_key = 'toss-sync:success:MIXED:2026-08-05'"
        ).stdout.strip()
        == "0"
    )
