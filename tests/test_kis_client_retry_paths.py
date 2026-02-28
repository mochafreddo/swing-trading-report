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


def _set_mock_method(target: object, name: str, **kwargs: Any) -> MagicMock:
    if not hasattr(target, name):
        raise AttributeError(
            f"{type(target).__name__!s} has no attribute {name!r} to patch"
        )
    if not callable(getattr(target, name)):
        raise TypeError(
            f"{type(target).__name__!s}.{name} is not callable and cannot be mocked as a method"
        )
    mock = MagicMock(**kwargs)
    setattr(target, name, mock)
    return mock


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
    _set_mock_method(client, "_request", return_value=fresh_resp)

    client.ensure_token()

    assert client._access_token == "Bearer fresh-token"
    assert client._token_expiry is not None
    assert client.cache_status == "refresh"


def test_ensure_token_raises_for_malformed_json() -> None:
    client = KISClient(_build_creds(), session=MagicMock(), cache_dir=None)
    _set_mock_method(
        client,
        "_request",
        return_value=_response(status_code=200, payload=ValueError("bad json")),
    )

    with pytest.raises(KISAuthError, match="Token response is not JSON"):
        client.ensure_token()


def test_ensure_token_retries_on_egw00133_rate_limit() -> None:
    client = KISClient(
        _build_creds(),
        session=MagicMock(),
        cache_dir=None,
        max_attempts=2,
    )
    rate_limited = _response(
        status_code=403,
        payload={"error_code": "EGW00133", "error_description": "rate limit"},
        text='{"error_code":"EGW00133"}',
    )
    success = _response(
        status_code=200,
        payload={
            "access_token": "fresh-token",
            "token_type": "Bearer",
            "expires_in": 3600,
        },
    )
    request_mock = _set_mock_method(
        client, "_request", side_effect=[rate_limited, success]
    )

    with patch("sab.data.kis.auth.time.sleep") as mock_sleep:
        client.ensure_token()

    assert request_mock.call_count == 2
    assert mock_sleep.call_args_list == [call(60.0)]
    assert client._access_token == "Bearer fresh-token"


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

    ensure_token_mock = _set_mock_method(
        client, "ensure_token", side_effect=_refresh_token
    )
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

    request_mock = _set_mock_method(
        client, "_request", side_effect=_request_side_effect
    )

    with patch("sab.data.kis_client.time.sleep") as mock_sleep:
        rows = client._fetch_candle_chunk(
            ticker="005930",
            start_date="20240101",
            end_date="20240201",
            adjusted=True,
        )

    assert rows == success_payload["output2"]
    assert request_mock.call_count == 2
    assert ensure_token_mock.call_count == 1
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
    request_mock = _set_mock_method(
        client, "_request", side_effect=[malformed, success]
    )

    with patch("sab.data.kis_client.time.sleep") as mock_sleep:
        rows = client._fetch_candle_chunk(
            ticker="005930",
            start_date="20240101",
            end_date="20240201",
            adjusted=True,
        )

    assert rows == success_payload["output2"]
    assert request_mock.call_count == 2
    assert mock_sleep.call_args_list == [call(1.0)]


def test_daily_candles_accumulates_and_sorts_rows_from_chunk_fetches() -> None:
    client = KISClient(
        _build_creds(),
        session=MagicMock(),
        cache_dir=None,
        max_attempts=2,
        min_interval=0,
    )
    ensure_token_mock = _set_mock_method(client, "ensure_token")
    fetch_candle_chunk_mock = _set_mock_method(
        client,
        "_fetch_candle_chunk",
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
        ],
    )

    rows = client.daily_candles("005930", count=2, adjusted=True)

    assert [row["date"] for row in rows] == ["20240102", "20240103"]
    assert ensure_token_mock.call_count == 1
    assert fetch_candle_chunk_mock.call_count == 2


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

    ensure_token_mock = _set_mock_method(
        client, "ensure_token", side_effect=_fake_ensure_token
    )
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

    _set_mock_method(client, "_request", side_effect=_request_side_effect)

    with patch("sab.data.kis_client.time.sleep") as mock_sleep:
        result = client.overseas_price_detail(symbol="aapl", exchange="nasd")

    assert result == {"last": "123.45"}
    assert ensure_token_mock.call_count == 2
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

    ensure_token_mock = _set_mock_method(
        client, "ensure_token", side_effect=_fake_ensure_token
    )
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

    _set_mock_method(client, "_request", side_effect=_request_side_effect)

    with patch("sab.data.kis_client.time.sleep") as mock_sleep:
        result = client.overseas_price_detail(symbol="amzn", exchange="nasd")

    assert result == {"last": "456.78"}
    assert ensure_token_mock.call_count == 2
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

    ensure_token_mock = _set_mock_method(
        client, "ensure_token", side_effect=_fake_ensure_token
    )
    rate_limited = _response(
        status_code=200,
        payload={"rt_cd": "1", "msg_cd": "EGW00201", "msg1": "rate limit"},
    )
    success = _response(
        status_code=200,
        payload={"rt_cd": "0", "output": [{"last": "999.99"}]},
    )
    request_mock = _set_mock_method(
        client, "_request", side_effect=[rate_limited, success]
    )

    with patch("sab.data.kis_client.time.sleep") as mock_sleep:
        result = client.overseas_price_detail(symbol="tsla", exchange="nasd")

    assert result == {"last": "999.99"}
    assert ensure_token_mock.call_count == 1
    assert request_mock.call_count == 2
    assert mock_sleep.call_args_list == [call(1.0)]


def test_volume_rank_refreshes_token_on_egw00123() -> None:
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

    ensure_token_mock = _set_mock_method(
        client, "ensure_token", side_effect=_fake_ensure_token
    )
    token_error = _response(
        status_code=200,
        payload={"rt_cd": "1", "msg_cd": "EGW00123", "msg1": "expired"},
    )
    success = _response(
        status_code=200,
        payload={
            "rt_cd": "0",
            "output": [
                {
                    "shrn_iscd": "005930",
                    "hts_kor_isnm": "SAMSUNG",
                    "stck_prpr": "70000",
                    "stck_cnt": "1000",
                    "acml_tr_pbmn": "70000000",
                }
            ],
        },
    )
    responses = iter([token_error, success])
    seen_authorizations: list[str] = []

    def _request_side_effect(*_args: Any, **kwargs: Any) -> MagicMock:
        headers = kwargs.get("headers") or {}
        seen_authorizations.append(str(headers.get("authorization") or ""))
        return next(responses)

    _set_mock_method(client, "_request", side_effect=_request_side_effect)

    with patch("sab.data.kis.ranking.time.sleep") as mock_sleep:
        rows = client.volume_rank(limit=1)

    assert rows
    assert ensure_token_mock.call_count == 2
    assert seen_authorizations == ["Bearer initial-token", "Bearer refreshed-token"]
    assert mock_sleep.call_args_list == [call(1.0)]


def test_volume_rank_keeps_refreshed_token_on_following_pages() -> None:
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

    ensure_token_mock = _set_mock_method(
        client, "ensure_token", side_effect=_fake_ensure_token
    )
    token_error = _response(
        status_code=200,
        payload={"rt_cd": "1", "msg_cd": "EGW00123", "msg1": "expired"},
    )
    page_1 = _response(
        status_code=200,
        payload={
            "rt_cd": "0",
            "output": [
                {
                    "shrn_iscd": "005930",
                    "hts_kor_isnm": "SAMSUNG",
                    "stck_prpr": "70000",
                    "stck_cnt": "1000",
                    "acml_tr_pbmn": "70000000",
                }
            ],
        },
    )
    page_1.headers = {"tr_cont": "M"}
    page_2 = _response(
        status_code=200,
        payload={
            "rt_cd": "0",
            "output": [
                {
                    "shrn_iscd": "000660",
                    "hts_kor_isnm": "SK HYNIX",
                    "stck_prpr": "100000",
                    "stck_cnt": "500",
                    "acml_tr_pbmn": "50000000",
                }
            ],
        },
    )
    page_2.headers = {}
    responses = iter([token_error, page_1, page_2])
    seen_authorizations: list[str] = []

    def _request_side_effect(*_args: Any, **kwargs: Any) -> MagicMock:
        headers = kwargs.get("headers") or {}
        seen_authorizations.append(str(headers.get("authorization") or ""))
        return next(responses)

    _set_mock_method(client, "_request", side_effect=_request_side_effect)

    with patch("sab.data.kis.ranking.time.sleep") as mock_sleep:
        rows = client.volume_rank(limit=2)

    assert [row["ticker"] for row in rows] == ["005930", "000660"]
    assert ensure_token_mock.call_count == 2
    assert seen_authorizations == [
        "Bearer initial-token",
        "Bearer refreshed-token",
        "Bearer refreshed-token",
    ]
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

    ensure_token_mock = _set_mock_method(
        client, "ensure_token", side_effect=_fake_ensure_token
    )
    malformed = _response(status_code=200, payload=ValueError("bad json"))
    success = _response(
        status_code=200,
        payload={"rt_cd": "0", "output": {"last": "77.77"}},
    )
    request_mock = _set_mock_method(
        client, "_request", side_effect=[malformed, success]
    )

    with patch("sab.data.kis_client.time.sleep") as mock_sleep:
        result = client.overseas_price_detail(symbol="msft", exchange="nasd")

    assert result == {"last": "77.77"}
    assert ensure_token_mock.call_count == 1
    assert request_mock.call_count == 2
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

    ensure_token_mock = _set_mock_method(
        client, "ensure_token", side_effect=_fake_ensure_token
    )
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
    request_mock = _set_mock_method(client, "_request", side_effect=[fail_1, fail_2])

    with (
        patch("sab.data.kis_client.time.sleep") as mock_sleep,
        pytest.raises(KISClientError, match="Overseas price detail HTTP 500"),
    ):
        client.overseas_price_detail(symbol="nvda", exchange="nasd")

    assert ensure_token_mock.call_count == 1
    assert request_mock.call_count == 2
    assert mock_sleep.call_args_list == [call(1.0)]


def test_overseas_price_detail_falls_back_to_slash_class_symbol_and_memoizes() -> None:
    client = KISClient(
        _build_creds(),
        session=MagicMock(),
        cache_dir=None,
        max_attempts=1,
        min_interval=0,
    )

    def _fake_ensure_token() -> None:
        client._access_token = "Bearer stable-token"
        client._token_expiry = _future_expiry()

    _set_mock_method(client, "ensure_token", side_effect=_fake_ensure_token)
    first_attempt_invalid = _response(
        status_code=200,
        payload={"rt_cd": "1", "msg_cd": "SYMB0001", "msg1": "invalid symbol"},
    )
    first_success = _response(
        status_code=200,
        payload={"rt_cd": "0", "output": {"last": "333.33"}},
    )
    second_success = _response(
        status_code=200,
        payload={"rt_cd": "0", "output": {"last": "444.44"}},
    )
    responses = iter([first_attempt_invalid, first_success, second_success])
    requested_symbols: list[str] = []

    def _request_side_effect(*_args: Any, **kwargs: Any) -> MagicMock:
        params = kwargs.get("params") or {}
        requested_symbols.append(str(params.get("SYMB") or ""))
        return next(responses)

    _set_mock_method(client, "_request", side_effect=_request_side_effect)

    first = client.overseas_price_detail(symbol="BRK.B", exchange="NYS")
    second = client.overseas_price_detail(symbol="BRK.B", exchange="NYS")

    assert first == {"last": "333.33"}
    assert second == {"last": "444.44"}
    assert requested_symbols == ["BRK.B", "BRK/B", "BRK/B"]


def test_fetch_overseas_candle_chunk_falls_back_to_slash_class_symbol() -> None:
    client = KISClient(
        _build_creds(),
        session=MagicMock(),
        cache_dir=None,
        max_attempts=1,
        min_interval=0,
    )
    client._access_token = "Bearer stable-token"
    client._token_expiry = _future_expiry()

    first_attempt_invalid = _response(
        status_code=200,
        payload={"rt_cd": "1", "msg_cd": "SYMB0001", "msg1": "invalid symbol"},
    )
    first_success = _response(
        status_code=200,
        payload={
            "rt_cd": "0",
            "output2": [
                {
                    "xymd": "20240102",
                    "open": "10",
                    "high": "12",
                    "low": "9",
                    "close": "11",
                    "tvol": "1000",
                }
            ],
        },
    )
    second_success = _response(
        status_code=200,
        payload={"rt_cd": "0", "output2": []},
    )
    responses = iter([first_attempt_invalid, first_success, second_success])
    requested_symbols: list[str] = []

    def _request_side_effect(*_args: Any, **kwargs: Any) -> MagicMock:
        params = kwargs.get("params") or {}
        requested_symbols.append(str(params.get("SYMB") or ""))
        return next(responses)

    _set_mock_method(client, "_request", side_effect=_request_side_effect)

    rows = client._fetch_overseas_candle_chunk(
        symbol="BRK.B",
        exchange="NYS",
        start_date="20240101",
        end_date="20240131",
        adjusted=True,
    )
    assert rows

    second_rows = client._fetch_overseas_candle_chunk(
        symbol="BRK.B",
        exchange="NYS",
        start_date="20240201",
        end_date="20240228",
        adjusted=True,
    )

    assert second_rows == []
    assert requested_symbols == ["BRK.B", "BRK/B", "BRK/B"]


def test_overseas_daily_candles_falls_back_to_slash_on_empty_class_symbol() -> None:
    client = KISClient(
        _build_creds(),
        session=MagicMock(),
        cache_dir=None,
        max_attempts=1,
        min_interval=0,
    )
    client._access_token = "Bearer stable-token"
    client._token_expiry = _future_expiry()

    empty_rows = _response(
        status_code=200,
        payload={"rt_cd": "0", "output2": []},
    )
    first_success = _response(
        status_code=200,
        payload={
            "rt_cd": "0",
            "output2": [
                {
                    "xymd": "20240102",
                    "open": "10",
                    "high": "12",
                    "low": "9",
                    "close": "11",
                    "tvol": "1000",
                }
            ],
        },
    )
    second_success = _response(
        status_code=200,
        payload={
            "rt_cd": "0",
            "output2": [
                {
                    "xymd": "20240103",
                    "open": "11",
                    "high": "13",
                    "low": "10",
                    "close": "12",
                    "tvol": "1100",
                }
            ],
        },
    )
    responses = iter([empty_rows, first_success, second_success])
    requested_symbols: list[str] = []

    def _request_side_effect(*_args: Any, **kwargs: Any) -> MagicMock:
        params = kwargs.get("params") or {}
        requested_symbols.append(str(params.get("SYMB") or ""))
        return next(responses)

    _set_mock_method(client, "_request", side_effect=_request_side_effect)

    first_rows = client.overseas_daily_candles(
        symbol="BRK.B",
        exchange="NYS",
        count=1,
        adjusted=True,
    )
    second_rows = client.overseas_daily_candles(
        symbol="BRK.B",
        exchange="NYS",
        count=1,
        adjusted=True,
    )

    assert first_rows and first_rows[0]["close"] == 11.0
    assert second_rows and second_rows[0]["close"] == 12.0
    assert requested_symbols == ["BRK.B", "BRK/B", "BRK/B"]


def test_overseas_price_detail_does_not_fallback_on_rate_limit_error() -> None:
    client = KISClient(
        _build_creds(),
        session=MagicMock(),
        cache_dir=None,
        max_attempts=1,
        min_interval=0,
    )

    def _fake_ensure_token() -> None:
        client._access_token = "Bearer stable-token"
        client._token_expiry = _future_expiry()

    _set_mock_method(client, "ensure_token", side_effect=_fake_ensure_token)
    request_mock = _set_mock_method(
        client,
        "_request",
        return_value=_response(
            status_code=200,
            payload={"rt_cd": "1", "msg_cd": "EGW00201", "msg1": "rate limit"},
        ),
    )

    with pytest.raises(
        KISClientError, match="KIS overseas price detail error: rate limit"
    ):
        client.overseas_price_detail(symbol="BRK.B", exchange="NYS")

    assert request_mock.call_count == 1


def test_fetch_overseas_candle_chunk_does_not_fallback_on_non_symbol_error() -> None:
    client = KISClient(
        _build_creds(),
        session=MagicMock(),
        cache_dir=None,
        max_attempts=1,
        min_interval=0,
    )
    client._access_token = "Bearer stable-token"
    client._token_expiry = _future_expiry()
    request_mock = _set_mock_method(
        client,
        "_request",
        return_value=_response(
            status_code=200,
            payload={"rt_cd": "1", "msg_cd": "EGW99999", "msg1": "internal"},
        ),
    )

    with pytest.raises(KISClientError, match="KIS overseas error: internal"):
        client._fetch_overseas_candle_chunk(
            symbol="BRK.B",
            exchange="NYS",
            start_date="20240101",
            end_date="20240131",
            adjusted=True,
        )

    assert request_mock.call_count == 1
