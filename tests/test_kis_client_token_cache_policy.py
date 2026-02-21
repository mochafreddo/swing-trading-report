from __future__ import annotations

import datetime as dt
import json
import logging
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from sab.data.kis_client import KISClient, KISCredentials


def _build_creds() -> KISCredentials:
    return KISCredentials(
        app_key="test-key",
        app_secret="test-secret",
        base_url="https://example.com",
        env="real",
    )


def _cache_file(path: Path) -> Path:
    return path / "kis_token_real.json"


def test_cached_token_naive_expires_at_is_interpreted_as_kst(tmp_path: Path) -> None:
    _cache_file(tmp_path).write_text(
        json.dumps(
            {
                "token": "cached-naive",
                "token_type": "Bearer",
                "expires_at": "2099-01-01 12:00:00",
            }
        ),
        encoding="utf-8",
    )

    client = KISClient(_build_creds(), session=MagicMock(), cache_dir=str(tmp_path))

    expected_expiry_utc = dt.datetime(2099, 1, 1, 3, 0, 0, tzinfo=dt.UTC)
    expected_refresh = expected_expiry_utc - dt.timedelta(minutes=5)
    assert client.cache_status == "hit"
    assert client._token_expiry == expected_refresh
    assert client._access_token == "Bearer cached-naive"


def test_cached_token_timezone_aware_expires_at_is_normalized_to_utc(
    tmp_path: Path,
) -> None:
    _cache_file(tmp_path).write_text(
        json.dumps(
            {
                "token": "cached-aware",
                "token_type": "Bearer",
                "expires_at": "2099-01-01T12:00:00+09:00",
            }
        ),
        encoding="utf-8",
    )

    client = KISClient(_build_creds(), session=MagicMock(), cache_dir=str(tmp_path))

    expected_expiry_utc = dt.datetime(2099, 1, 1, 3, 0, 0, tzinfo=dt.UTC)
    expected_refresh = expected_expiry_utc - dt.timedelta(minutes=5)
    assert client.cache_status == "hit"
    assert client._token_expiry == expected_refresh
    assert client._access_token == "Bearer cached-aware"


def test_ensure_token_falls_back_to_expires_in_when_expires_at_is_invalid(
    tmp_path: Path,
    caplog: pytest.LogCaptureFixture,
) -> None:
    caplog.set_level(logging.INFO, logger="sab.data.kis_client")
    client = KISClient(_build_creds(), session=MagicMock(), cache_dir=str(tmp_path))
    fake_resp = MagicMock()
    fake_resp.status_code = 200
    fake_resp.json.return_value = {
        "access_token": "fresh-token",
        "token_type": "Bearer",
        "expires_in": 3600,
        "access_token_token_expired": "not-a-timestamp",
    }
    with patch.object(client, "_request", MagicMock(return_value=fake_resp)):
        before = dt.datetime.now(dt.UTC)
        client.ensure_token()
        after = dt.datetime.now(dt.UTC)

    assert client.cache_status == "refresh"
    assert client._access_token == "Bearer fresh-token"
    assert client._token_expiry is not None
    remaining_upper = (client._token_expiry - before).total_seconds()
    remaining_lower = (client._token_expiry - after).total_seconds()
    assert 3280 <= remaining_upper <= 3320
    assert 3280 <= remaining_lower <= 3320

    cached = json.loads(_cache_file(tmp_path).read_text(encoding="utf-8"))
    assert cached["token"] == "fresh-token"
    assert cached["expires_at"].endswith("+00:00")
    lines = [
        record.getMessage()
        for record in caplog.records
        if "KIS token refreshed (" in record.getMessage()
    ]
    assert lines == [
        f"KIS token refreshed (env=real, cache_status=refresh, cache_dir={tmp_path})"
    ]
