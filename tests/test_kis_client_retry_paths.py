from __future__ import annotations

import datetime as dt
import json
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, call, patch

import pytest
from sab.data.kis_client import KISAuthError, KISClient, KISClientError, KISCredentials


def _build_creds() -> KISCredentials:
    return KISCredentials(
        app_key="test-key",
        app_secret="test-secret",
        base_url="https://example.com",
        env="real",
    )


def _cache_file(path: Path) -> Path:
    return path / "kis_token_real.json"


def _response(
    *,
    status_code: int,
    payload: dict[str, Any] | ValueError,
    text: str = "",
) -> MagicMock:
    resp = MagicMock()
    resp.status_code = status_code
    resp.text = text
    resp.headers = {}
    if isinstance(payload, ValueError):
        resp.json.side_effect = payload
    else:
        resp.json.return_value = payload
    return resp


def _future_expiry() -> dt.datetime:
    return dt.datetime.now(dt.UTC) + dt.timedelta(hours=1)


def test_ensure_token_refreshes_when_cached_token_is_stale(tmp_path: Path) -> None:
    _cache_file(tmp_path).write_text(
        json.dumps(
            {
                "token": "stale-token",
                "token_type": "Bearer",
                "expires_at": "2000-01-01T00:00:00+00:00",
            }
        ),
        encoding="utf-8",
    )

    client = KISClient(_build_creds(), session=MagicMock(), cache_dir=str(tmp_path))
    assert client.cache_status == "expired"
    assert client._access_token is None

    fresh_resp = _response(
        status_code=200,
        payload={
            "access_token": "fresh-token",
            "token_type": "Bearer",
            "expires_in": 3600,
        },
    )
    client._request = MagicMock(return_value=fresh_resp)

    client.ensure_token()

    assert client._access_token == "Bearer fresh-token"
    assert client._token_expiry is not None
    assert client.cache_status == "refresh"


def test_ensure_token_raises_for_malformed_json() -> None:
    client = KISClient(_build_creds(), session=MagicMock(), cache_dir=None)
    client._request = MagicMock(
        return_value=_response(status_code=200, payload=ValueError("bad json"))
    )

    with pytest.raises(KISAuthError, match="Token response is not JSON"):
        client.ensure_token()


def test_request_retries_with_backoff_on_429_and_503() -> None:
    session = MagicMock()
    rate_limited = _response(status_code=429, payload={"rt_cd": "1"})
    unavailable = _response(status_code=503, payload={"rt_cd": "1"})
    ok = _response(status_code=200, payload={"rt_cd": "0"})
    session.request.side_effect = [rate_limited, unavailable, ok]

    client = KISClient(
        _build_creds(),
        session=session,
        cache_dir=None,
        max_attempts=3,
        min_interval=0,
    )

    with patch("sab.data.kis_client.time.sleep") as mock_sleep:
        response = client._request("GET", "https://example.com/ping")

    assert response is ok
    assert session.request.call_count == 3
    assert mock_sleep.call_args_list == [call(1.0), call(2.0)]


def test_fetch_candle_chunk_refreshes_token_on_egw00123() -> None:
    client = KISClient(
        _build_creds(),
        session=MagicMock(),
        cache_dir=None,
        max_attempts=2,
        min_interval=0,
    )
    client._access_token = "Bearer old-token"
    client._token_expiry = _future_expiry()

    def _refresh_token() -> None:
        client._access_token = "Bearer refreshed-token"
        client._token_expiry = _future_expiry()

    client.ensure_token = MagicMock(side_effect=_refresh_token)
    token_expired = _response(
        status_code=200,
        payload={"rt_cd": "1", "msg_cd": "EGW00123", "msg1": "expired"},
    )
    success_payload = {
        "rt_cd": "0",
        "output2": [
            {
                "stck_bsop_date": "20240102",
                "stck_oprc": "10",
                "stck_hgpr": "12",
                "stck_lwpr": "9",
                "stck_clpr": "11",
                "acml_vol": "1000",
                "prdy_vrss": "1",
            }
        ],
    }
    success = _response(status_code=200, payload=success_payload)
    responses = iter([token_expired, success])
    seen_authorizations: list[str] = []

    def _request_side_effect(*_args: Any, **kwargs: Any) -> MagicMock:
        headers = kwargs.get("headers") or {}
        seen_authorizations.append(str(headers.get("authorization") or ""))
        return next(responses)

    client._request = MagicMock(side_effect=_request_side_effect)

    with patch("sab.data.kis_client.time.sleep") as mock_sleep:
        rows = client._fetch_candle_chunk(
            ticker="005930",
            start_date="20240101",
            end_date="20240201",
            adjusted=True,
        )

    assert rows == success_payload["output2"]
    assert client._request.call_count == 2
    assert client.ensure_token.call_count == 1
    assert seen_authorizations == ["Bearer old-token", "Bearer refreshed-token"]
    assert mock_sleep.call_args_list == [call(1.0)]


def test_fetch_candle_chunk_retries_when_response_json_is_malformed() -> None:
    client = KISClient(
        _build_creds(),
        session=MagicMock(),
        cache_dir=None,
        max_attempts=2,
        min_interval=0,
    )
    client._access_token = "Bearer test-token"
    client._token_expiry = _future_expiry()

    malformed = _response(status_code=200, payload=ValueError("invalid json"))
    success_payload = {
        "rt_cd": "0",
        "output2": [
            {
                "stck_bsop_date": "20240103",
                "stck_oprc": "20",
                "stck_hgpr": "21",
                "stck_lwpr": "19",
                "stck_clpr": "20",
                "acml_vol": "2000",
                "prdy_vrss": "0",
            }
        ],
    }
    success = _response(status_code=200, payload=success_payload)
    client._request = MagicMock(side_effect=[malformed, success])

    with patch("sab.data.kis_client.time.sleep") as mock_sleep:
        rows = client._fetch_candle_chunk(
            ticker="005930",
            start_date="20240101",
            end_date="20240201",
            adjusted=True,
        )

    assert rows == success_payload["output2"]
    assert client._request.call_count == 2
    assert mock_sleep.call_args_list == [call(1.0)]


def test_daily_candles_accumulates_and_sorts_rows_from_chunk_fetches() -> None:
    client = KISClient(
        _build_creds(),
        session=MagicMock(),
        cache_dir=None,
        max_attempts=2,
        min_interval=0,
    )
    client.ensure_token = MagicMock()
    client._fetch_candle_chunk = MagicMock(
        side_effect=[
            [],
            [
                {
                    "stck_bsop_date": "20240103",
                    "stck_oprc": "30",
                    "stck_hgpr": "31",
                    "stck_lwpr": "29",
                    "stck_clpr": "30",
                    "acml_vol": "3000",
                    "prdy_vrss": "1",
                },
                {
                    "stck_bsop_date": "20240102",
                    "stck_oprc": "20",
                    "stck_hgpr": "21",
                    "stck_lwpr": "19",
                    "stck_clpr": "20",
                    "acml_vol": "2000",
                    "prdy_vrss": "0",
                },
            ],
        ]
    )

    rows = client.daily_candles("005930", count=2, adjusted=True)

    assert [row["date"] for row in rows] == ["20240102", "20240103"]
    assert client.ensure_token.call_count == 1
    assert client._fetch_candle_chunk.call_count == 2


def test_overseas_price_detail_refreshes_token_on_egw00123() -> None:
    client = KISClient(
        _build_creds(),
        session=MagicMock(),
        cache_dir=None,
        max_attempts=2,
        min_interval=0,
    )
    token_values = ["Bearer initial-token", "Bearer refreshed-token"]
    token_call_count = {"value": 0}

    def _fake_ensure_token() -> None:
        idx = token_call_count["value"]
        client._access_token = token_values[min(idx, len(token_values) - 1)]
        client._token_expiry = _future_expiry()
        token_call_count["value"] += 1

    client.ensure_token = MagicMock(side_effect=_fake_ensure_token)
    token_error = _response(
        status_code=200,
        payload={"rt_cd": "1", "msg_cd": "EGW00123", "msg1": "expired"},
    )
    success = _response(
        status_code=200,
        payload={"rt_cd": "0", "output": {"last": "123.45"}},
    )
    responses = iter([token_error, success])
    seen_authorizations: list[str] = []

    def _request_side_effect(*_args: Any, **kwargs: Any) -> MagicMock:
        headers = kwargs.get("headers") or {}
        seen_authorizations.append(str(headers.get("authorization") or ""))
        return next(responses)

    client._request = MagicMock(side_effect=_request_side_effect)

    with patch("sab.data.kis_client.time.sleep") as mock_sleep:
        result = client.overseas_price_detail(symbol="aapl", exchange="nasd")

    assert result == {"last": "123.45"}
    assert client.ensure_token.call_count == 2
    assert seen_authorizations == ["Bearer initial-token", "Bearer refreshed-token"]
    assert mock_sleep.call_args_list == [call(1.0)]


def test_overseas_price_detail_refreshes_token_on_http_error_egw00123() -> None:
    client = KISClient(
        _build_creds(),
        session=MagicMock(),
        cache_dir=None,
        max_attempts=2,
        min_interval=0,
    )
    token_values = ["Bearer initial-token", "Bearer refreshed-token"]
    token_call_count = {"value": 0}

    def _fake_ensure_token() -> None:
        idx = token_call_count["value"]
        client._access_token = token_values[min(idx, len(token_values) - 1)]
        client._token_expiry = _future_expiry()
        token_call_count["value"] += 1

    client.ensure_token = MagicMock(side_effect=_fake_ensure_token)
    token_error = _response(
        status_code=401,
        payload={"msg_cd": "EGW00123", "msg1": "expired token"},
    )
    success = _response(
        status_code=200,
        payload={"rt_cd": "0", "output": {"last": "456.78"}},
    )
    responses = iter([token_error, success])
    seen_authorizations: list[str] = []

    def _request_side_effect(*_args: Any, **kwargs: Any) -> MagicMock:
        headers = kwargs.get("headers") or {}
        seen_authorizations.append(str(headers.get("authorization") or ""))
        return next(responses)

    client._request = MagicMock(side_effect=_request_side_effect)

    with patch("sab.data.kis_client.time.sleep") as mock_sleep:
        result = client.overseas_price_detail(symbol="amzn", exchange="nasd")

    assert result == {"last": "456.78"}
    assert client.ensure_token.call_count == 2
    assert seen_authorizations == ["Bearer initial-token", "Bearer refreshed-token"]
    assert mock_sleep.call_args_list == [call(1.0)]


def test_overseas_price_detail_retries_on_rate_limit_body_error() -> None:
    client = KISClient(
        _build_creds(),
        session=MagicMock(),
        cache_dir=None,
        max_attempts=2,
        min_interval=0,
    )

    def _fake_ensure_token() -> None:
        client._access_token = "Bearer stable-token"
        client._token_expiry = _future_expiry()

    client.ensure_token = MagicMock(side_effect=_fake_ensure_token)
    rate_limited = _response(
        status_code=200,
        payload={"rt_cd": "1", "msg_cd": "EGW00201", "msg1": "rate limit"},
    )
    success = _response(
        status_code=200,
        payload={"rt_cd": "0", "output": [{"last": "999.99"}]},
    )
    client._request = MagicMock(side_effect=[rate_limited, success])

    with patch("sab.data.kis_client.time.sleep") as mock_sleep:
        result = client.overseas_price_detail(symbol="tsla", exchange="nasd")

    assert result == {"last": "999.99"}
    assert client.ensure_token.call_count == 1
    assert client._request.call_count == 2
    assert mock_sleep.call_args_list == [call(1.0)]


def test_overseas_price_detail_retries_when_response_json_is_malformed() -> None:
    client = KISClient(
        _build_creds(),
        session=MagicMock(),
        cache_dir=None,
        max_attempts=2,
        min_interval=0,
    )

    def _fake_ensure_token() -> None:
        client._access_token = "Bearer stable-token"
        client._token_expiry = _future_expiry()

    client.ensure_token = MagicMock(side_effect=_fake_ensure_token)
    malformed = _response(status_code=200, payload=ValueError("bad json"))
    success = _response(
        status_code=200,
        payload={"rt_cd": "0", "output": {"last": "77.77"}},
    )
    client._request = MagicMock(side_effect=[malformed, success])

    with patch("sab.data.kis_client.time.sleep") as mock_sleep:
        result = client.overseas_price_detail(symbol="msft", exchange="nasd")

    assert result == {"last": "77.77"}
    assert client.ensure_token.call_count == 1
    assert client._request.call_count == 2
    assert mock_sleep.call_args_list == [call(1.0)]


def test_overseas_price_detail_raises_after_all_retries_fail() -> None:
    client = KISClient(
        _build_creds(),
        session=MagicMock(),
        cache_dir=None,
        max_attempts=2,
        min_interval=0,
    )

    def _fake_ensure_token() -> None:
        client._access_token = "Bearer stable-token"
        client._token_expiry = _future_expiry()

    client.ensure_token = MagicMock(side_effect=_fake_ensure_token)
    fail_1 = _response(
        status_code=500,
        payload={"rt_cd": "1", "msg_cd": "EGW99999", "msg1": "internal"},
        text="internal-1",
    )
    fail_2 = _response(
        status_code=500,
        payload={"rt_cd": "1", "msg_cd": "EGW99999", "msg1": "internal"},
        text="internal-2",
    )
    client._request = MagicMock(side_effect=[fail_1, fail_2])

    with (
        patch("sab.data.kis_client.time.sleep") as mock_sleep,
        pytest.raises(KISClientError, match="Overseas price detail HTTP 500"),
    ):
        client.overseas_price_detail(symbol="nvda", exchange="nasd")

    assert client.ensure_token.call_count == 1
    assert client._request.call_count == 2
    assert mock_sleep.call_args_list == [call(1.0)]
