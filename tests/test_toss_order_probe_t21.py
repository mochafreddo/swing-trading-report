from __future__ import annotations

import copy
import json
from typing import Any
from urllib.parse import parse_qs, urlsplit

import pytest
from sab.portfolio_mandate import toss_order_probe as probe


def _order() -> dict[str, Any]:
    return {
        "orderId": "SYNTHETIC-ORDER-PRIVATE-SENTINEL",
        "symbol": "SYNTH",
        "side": "BUY",
        "orderType": "LIMIT",
        "timeInForce": "DAY",
        "status": "PARTIAL_FILLED",
        "quantity": "10",
        "currency": "USD",
        "orderedAt": "2026-09-01T10:00:00+09:00",
        "execution": {
            "filledQuantity": "2",
            "averageFilledPrice": "123.456",
            "filledAmount": "246.912",
            "commission": "0.1",
            "tax": "0",
            "filledAt": "2026-09-01T10:01:00+09:00",
            "settlementDate": None,
        },
    }


def _page(orders: list[dict[str, Any]], cursor: str | None = None) -> bytes:
    return json.dumps(
        {
            "result": {
                "orders": orders,
                "nextCursor": cursor,
                "hasNext": cursor is not None,
            }
        }
    ).encode()


class _Response:
    def __init__(self, body: bytes, status: int = 200) -> None:
        self.body, self.status = body, status

    def read(self, size: int) -> bytes:
        result, self.body = self.body[:size], self.body[size:]
        return result

    def isclosed(self) -> bool:
        return not self.body


def _run(
    monkeypatch: pytest.MonkeyPatch, responses: list[_Response], **kwargs: Any
) -> tuple[dict[str, Any], list[tuple[str, str]]]:
    requests: list[tuple[str, str]] = []

    class Connection:
        def __init__(self, host: str, *, timeout: float) -> None:
            assert host == "openapi.tossinvest.com"
            assert 0 < timeout <= 30

        def request(self, method: str, path: str, **options: Any) -> None:
            requests.append((method, path))

        def getresponse(self) -> _Response:
            return responses.pop(0)

        def close(self) -> None:
            pass

    monkeypatch.setattr(probe.http.client, "HTTPSConnection", Connection)
    result = probe.run_toss_order_probe_t21(
        "SYNTHETIC-CLIENT",
        "SYNTHETIC-SECRET",
        "1",
        "2026-08-07",
        "2026-09-05",
        **kwargs,
    )
    return result, requests


def _token() -> _Response:
    return _Response(b'{"access_token":"SYNTHETIC-TOKEN"}')


def test_approval_is_required_before_any_network(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    result, calls = _run(monkeypatch, [])
    assert result["result_code"] == "APPROVAL_REQUIRED"
    assert calls == []


def test_aggregate_probe_succeeds_without_fill_identity(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    result, calls = _run(
        monkeypatch, [_token(), _Response(_page([_order()]))], approved=True
    )
    assert result["result_code"] == "COMPLETE_ORDER_AGGREGATE"
    assert result["provider_history_state"] == "ORDER_AGGREGATE_OBSERVED"
    assert result["individual_fill_lineage"] == "NOT_EVALUATED"
    assert result["partial_fill_state"] == "OBSERVED_ORDER_AGGREGATE"
    assert result["order_operations"] == 0
    assert [method for method, _ in calls] == ["POST", "GET"]
    assert calls[0][1] == "/oauth2/token"
    query = parse_qs(urlsplit(calls[1][1]).query)
    assert query == {
        "status": ["CLOSED"],
        "limit": ["20"],
        "from": ["2026-08-07"],
        "to": ["2026-09-05"],
    }
    serialized = json.dumps(result)
    for sentinel in (
        "SYNTHETIC",
        "SYNTH",
        "123.456",
        "246.912",
        "orderId",
        "accountSeq",
        "access_token",
        "execution_lineages",
    ):
        assert sentinel not in serialized


@pytest.mark.parametrize(
    "status,code",
    [
        (301, "REDIRECT_FORBIDDEN"),
        (401, "HTTP_401"),
        (403, "HTTP_403"),
        (429, "HTTP_429"),
        (503, "HTTP_5XX"),
    ],
)
def test_http_failures_never_retry(
    monkeypatch: pytest.MonkeyPatch, status: int, code: str
) -> None:
    result, calls = _run(
        monkeypatch, [_Response(b"SENSITIVE ERROR", status)], approved=True
    )
    assert result["result_code"] == code
    assert len(calls) == 1
    assert "SENSITIVE" not in json.dumps(result)


def test_empty_history_is_not_observed_execution(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    result, _ = _run(monkeypatch, [_token(), _Response(_page([]))], approved=True)
    assert result["result_code"] == "COMPLETE_NO_ORDERS"
    assert result["provider_history_state"] == "QUERY_SUCCEEDED_NO_ORDERS"
    assert result["partial_fill_state"] == "NOT_OBSERVED"


def test_pagination_and_opaque_cursor_encoding(monkeypatch: pytest.MonkeyPatch) -> None:
    cursor = "SYNTHETIC/opaque?cursor=+&"
    result, calls = _run(
        monkeypatch,
        [_token(), _Response(_page([_order()], cursor)), _Response(_page([]))],
        approved=True,
    )
    assert result["result_code"] == "COMPLETE_ORDER_AGGREGATE"
    assert parse_qs(urlsplit(calls[2][1]).query)["cursor"] == [cursor]
    assert "SYNTHETIC" not in json.dumps(result)


def test_duplicate_order_and_cursor_loop_are_not_complete(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    for responses, expected in [
        (
            [
                _token(),
                _Response(_page([_order()], "cursor")),
                _Response(_page([_order()])),
            ],
            "DUPLICATE_ORDER",
        ),
        (
            [_token(), _Response(_page([], "cursor")), _Response(_page([], "cursor"))],
            "CURSOR_LOOP",
        ),
    ]:
        result, _ = _run(monkeypatch, responses, approved=True)
        assert result["result_code"] == expected
        assert result["provider_history_state"] == "NOT_EVALUATED"


def test_page_cap_is_incomplete_not_success(monkeypatch: pytest.MonkeyPatch) -> None:
    result, calls = _run(
        monkeypatch,
        [_token(), *[_Response(_page([], str(i))) for i in range(4)]],
        approved=True,
    )
    assert result["result_code"] == "INCOMPLETE_PAGE_BUDGET"
    assert len(calls) == 5


@pytest.mark.parametrize(
    "body",
    [
        b"not json",
        b'{"result":{},"result":{}}',
        b'{"result":{"orders":[],"hasNext":false,"nextCursor":"unexpected"}}',
        b"\xff",
    ],
)
def test_malformed_pages_are_sanitized(
    monkeypatch: pytest.MonkeyPatch, body: bytes
) -> None:
    result, _ = _run(monkeypatch, [_token(), _Response(body)], approved=True)
    assert result["result_code"] == "MALFORMED_PAYLOAD"


@pytest.mark.parametrize(
    "field,value",
    [
        ("filledQuantity", "NaN"),
        ("filledQuantity", "-1"),
        ("filledQuantity", "11"),
        ("averageFilledPrice", None),
        ("filledAt", "bad-date"),
    ],
)
def test_invalid_aggregate_fails_closed(
    monkeypatch: pytest.MonkeyPatch, field: str, value: Any
) -> None:
    order = copy.deepcopy(_order())
    order["execution"][field] = value
    result, _ = _run(monkeypatch, [_token(), _Response(_page([order]))], approved=True)
    assert result["result_code"] == "MALFORMED_PAYLOAD"


def test_unknown_status_is_not_silently_classified(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    order = _order()
    order["status"] = "NEW_PROVIDER_STATUS"
    result, _ = _run(monkeypatch, [_token(), _Response(_page([order]))], approved=True)
    assert result["result_code"] == "UNSUPPORTED_ORDER_STATUS"


def test_byte_budget_counts_token_and_history(monkeypatch: pytest.MonkeyPatch) -> None:
    result, calls = _run(
        monkeypatch, [_token(), _Response(b" " * 1_048_576)], approved=True
    )
    assert result["result_code"] == "BYTE_BUDGET_EXCEEDED"
    assert result["response_byte_count"] <= 1_048_576
    assert len(calls) == 2


def test_invalid_dates_or_credentials_stop_before_auth(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    for args in [
        ("id", "secret", "account-number", "2026-08-07", "2026-09-05"),
        ("id", "secret", "1", "2026-01-01", "2026-09-05"),
        ("", "secret", "1", "2026-08-07", "2026-09-05"),
    ]:
        monkeypatch.setattr(
            probe.http.client,
            "HTTPSConnection",
            lambda *a, **k: pytest.fail("network forbidden"),
        )
        result = probe.run_toss_order_probe_t21(*args, approved=True)
        assert result["result_code"] == "INVALID_INPUT"
        assert result["request_count"] == 0


@pytest.mark.parametrize(
    "failure", [TimeoutError("SENSITIVE-TOKEN"), OSError("SENSITIVE-ACCOUNT")]
)
def test_transport_exceptions_are_sanitized_and_deadline_restored(
    monkeypatch: pytest.MonkeyPatch,
    failure: Exception,
    capsys: pytest.CaptureFixture[str],
) -> None:
    previous = probe.signal.getsignal(probe.signal.SIGALRM)

    class BrokenConnection:
        def __init__(self, *args: Any, **kwargs: Any) -> None:
            pass

        def request(self, *args: Any, **kwargs: Any) -> None:
            raise failure

        def close(self) -> None:
            pass

    monkeypatch.setattr(probe.http.client, "HTTPSConnection", BrokenConnection)
    result = probe.run_toss_order_probe_t21(
        "id", "secret", "1", "2026-08-07", "2026-09-05", approved=True
    )
    assert result["result_code"] == (
        "TIMEOUT"
        if isinstance(failure, TimeoutError)
        else "TRANSPORT_OR_INTERNAL_ERROR"
    )
    assert probe.signal.getsignal(probe.signal.SIGALRM) == previous
    assert probe.signal.getitimer(probe.signal.ITIMER_REAL) == (0.0, 0.0)
    assert "SENSITIVE" not in json.dumps(result)
    assert capsys.readouterr() == ("", "")


def test_deadline_is_checked_before_another_request(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    ticks = iter([0.0, 0.1, 30.1, 30.2])
    monkeypatch.setattr(probe.time, "monotonic", lambda: next(ticks))
    result, calls = _run(monkeypatch, [_token()], approved=True)
    assert result["result_code"] == "TIMEOUT"
    assert len(calls) == 1


def test_hard_deadline_handler_interrupts_blocking_transport(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class BlockingConnection:
        def __init__(self, *args: Any, **kwargs: Any) -> None:
            pass

        def request(self, *args: Any, **kwargs: Any) -> None:
            # Trigger the installed handler without waiting or using a real socket.
            handler = probe.signal.getsignal(probe.signal.SIGALRM)
            assert callable(handler)
            handler(probe.signal.SIGALRM, None)

        def close(self) -> None:
            pass

    monkeypatch.setattr(probe.http.client, "HTTPSConnection", BlockingConnection)
    result = probe.run_toss_order_probe_t21(
        "id", "secret", "1", "2026-08-07", "2026-09-05", approved=True
    )
    assert result["result_code"] == "TIMEOUT"
    assert result["request_count"] == 1


def test_cancellation_state_is_not_correction_lineage(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    order = _order()
    order["status"] = "CANCELED"
    result, _ = _run(monkeypatch, [_token(), _Response(_page([order]))], approved=True)
    assert result["result_code"] == "COMPLETE_ORDER_AGGREGATE"
    assert result["correction_cancel_state"] == "OBSERVED_ORDER_STATE_ONLY"
    assert result["individual_fill_lineage"] == "NOT_EVALUATED"
