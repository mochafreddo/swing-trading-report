from __future__ import annotations

import json
import os
from datetime import UTC, datetime
from pathlib import Path

import pytest
from sab.decision_board.run_journal import RunJournalStoreV0
from sab.decision_board.run_journal_public import (
    PublicJournalReadError,
    read_public_journal_status_v0,
)
from sab.decision_board.runner import RunKindV0


def _missed(root: Path) -> Path:
    root.chmod(0o700)
    RunJournalStoreV0(root).claim(
        run_kind=RunKindV0.ENTRY,
        expected_at=datetime(2026, 8, 11, 1, 0, tzinfo=UTC),
        run_id="entry-public-reader",
        observed_at=datetime(2026, 8, 11, 1, 2, tzinfo=UTC),
        grace_seconds=60,
        stale_seconds=300,
    )
    return next(root.glob("*.json"))


def test_public_reader_reads_t9_record_without_mutation(tmp_path: Path) -> None:
    record = _missed(tmp_path)
    before = record.read_bytes()

    public = read_public_journal_status_v0(str(tmp_path), limit=1, scan_limit=10)

    assert public["count"] == 1
    assert public["records"][0]["status"] == "MISSED_EXPECTED"  # type: ignore[index]
    assert record.read_bytes() == before


def test_public_reader_rejects_duplicate_keys_and_invalid_utf8(tmp_path: Path) -> None:
    record = _missed(tmp_path)
    original = record.read_bytes()
    record.write_bytes(
        original.replace(
            b'"grace_seconds":60,',
            b'"grace_seconds":60,"grace_seconds":60,',
        )
    )
    os.chmod(record, 0o600)
    with pytest.raises(PublicJournalReadError):
        read_public_journal_status_v0(str(tmp_path), limit=1)


def test_public_reader_rejects_non_public_schema_and_issue_values(
    tmp_path: Path,
) -> None:
    record = _missed(tmp_path)
    value = json.loads(record.read_text(encoding="utf-8"))
    value["schema_version"] = "PRIVATE-SCHEMA-SENTINEL"
    record.write_text(
        json.dumps(value, sort_keys=True, separators=(",", ":")) + "\n",
        encoding="utf-8",
    )
    os.chmod(record, 0o600)
    with pytest.raises(PublicJournalReadError):
        read_public_journal_status_v0(str(tmp_path), limit=1)

    record.write_bytes(b"\xff\n")
    os.chmod(record, 0o600)
    with pytest.raises(PublicJournalReadError):
        read_public_journal_status_v0(str(tmp_path), limit=1)


def test_public_reader_enforces_scan_record_and_output_bounds(tmp_path: Path) -> None:
    record = _missed(tmp_path)
    (tmp_path / "ignored.txt").write_text("ignored", encoding="utf-8")
    with pytest.raises(PublicJournalReadError, match="scan bound"):
        read_public_journal_status_v0(str(tmp_path), limit=1, scan_limit=1)
    with pytest.raises(PublicJournalReadError, match="record"):
        read_public_journal_status_v0(
            str(tmp_path),
            limit=1,
            scan_limit=10,
            max_record_bytes=record.stat().st_size - 1,
        )
    with pytest.raises(PublicJournalReadError, match="output bound"):
        read_public_journal_status_v0(
            str(tmp_path), limit=1, scan_limit=10, max_output_bytes=1
        )
