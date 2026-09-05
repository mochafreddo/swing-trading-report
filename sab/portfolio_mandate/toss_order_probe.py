"""Bounded, default-deny Toss CLOSED-order probe; never constructs fill events."""

from __future__ import annotations

import http.client
import json
import re
import signal
import time
from datetime import date, datetime
from decimal import Decimal
from typing import Any
from urllib.parse import urlencode

MAX_BYTES = 1_048_576
MAX_PAGES = 4
MAX_SECONDS = 30
_CLOSED_STATUSES = frozenset(
    {
        "FILLED",
        "CANCELED",
        "REJECTED",
        "REPLACED",
        "CANCEL_REJECTED",
        "REPLACE_REJECTED",
        "PARTIAL_FILLED",
    }
)


class _Stop(Exception):
    """Only fixed result codes may escape the in-memory processing boundary."""


def _decode(body: bytes) -> dict[str, Any]:
    def unique(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for key, value in pairs:
            if key in result:
                raise _Stop("MALFORMED_PAYLOAD")
            result[key] = value
        return result

    def reject_constant(_: str) -> None:
        raise _Stop("MALFORMED_PAYLOAD")

    try:
        value = json.loads(
            body.decode("utf-8"),
            object_pairs_hook=unique,
            parse_constant=reject_constant,
        )
    except ValueError, UnicodeError, RecursionError:
        raise _Stop("MALFORMED_PAYLOAD") from None
    if type(value) is not dict:
        raise _Stop("MALFORMED_PAYLOAD")
    return value


def _number(value: Any) -> Decimal:
    if (
        type(value) is not str
        or len(value) > 30
        or not re.fullmatch(r"\d+(?:\.\d+)?", value)
    ):
        raise _Stop("MALFORMED_PAYLOAD")
    return Decimal(value)


def _timestamp(value: Any) -> None:
    if type(value) is not str or len(value) > 64:
        raise _Stop("MALFORMED_PAYLOAD")
    try:
        if datetime.fromisoformat(value).tzinfo is None:
            raise ValueError
    except ValueError:
        raise _Stop("MALFORMED_PAYLOAD") from None


def _aggregate(order: Any) -> tuple[str, bool, bool]:
    """Validate an aggregate in memory; return identity and capability flags only."""
    if type(order) is not dict:
        raise _Stop("MALFORMED_PAYLOAD")
    for key in (
        "orderId",
        "symbol",
        "side",
        "orderType",
        "timeInForce",
        "status",
        "currency",
    ):
        if type(order.get(key)) is not str or not 0 < len(order[key]) <= 512:
            raise _Stop("MALFORMED_PAYLOAD")
    if order["status"] not in _CLOSED_STATUSES:
        raise _Stop("UNSUPPORTED_ORDER_STATUS")
    if order["side"] not in {"BUY", "SELL"} or order["currency"] not in {"KRW", "USD"}:
        raise _Stop("MALFORMED_PAYLOAD")
    _timestamp(order.get("orderedAt"))
    quantity = _number(order.get("quantity"))
    execution = order.get("execution")
    if type(execution) is not dict:
        raise _Stop("MALFORMED_PAYLOAD")
    required = {
        "filledQuantity",
        "averageFilledPrice",
        "filledAmount",
        "commission",
        "tax",
        "filledAt",
        "settlementDate",
    }
    if not required.issubset(execution):
        raise _Stop("MALFORMED_PAYLOAD")
    filled = _number(execution["filledQuantity"])
    if order.get("orderAmount") is None and filled > quantity:
        raise _Stop("MALFORMED_PAYLOAD")
    for key in ("averageFilledPrice", "filledAmount", "commission", "tax"):
        if execution[key] is not None:
            _number(execution[key])
    if execution["filledAt"] is not None:
        _timestamp(execution["filledAt"])
    if execution["settlementDate"] is not None:
        try:
            date.fromisoformat(execution["settlementDate"])
        except ValueError, TypeError:
            raise _Stop("MALFORMED_PAYLOAD") from None
    if filled > 0 and (
        execution["averageFilledPrice"] is None or execution["filledAt"] is None
    ):
        raise _Stop("MALFORMED_PAYLOAD")
    return (
        order["orderId"],
        order["status"] == "PARTIAL_FILLED",
        order["status"] in {"CANCELED", "REPLACED"},
    )


def run_toss_order_probe_t21(
    client_id: str,
    client_secret: str,
    account_seq: str,
    from_date: str,
    to_date: str,
    *,
    approved: bool = False,
) -> dict[str, Any]:
    """One token POST and up to four CLOSED-order GETs, with sanitized output only.

    The caller must obtain specific approval; a previous KIS approval is not valid.
    No files, token cache, proxy, retry, redirect, scheduler or generic URL input.
    Unix main-thread execution is required for the hard wall-clock deadline.
    """
    result: dict[str, Any] = {
        "schema_version": "toss-order-aggregate-probe.t21",
        "provider_history_state": "NOT_EVALUATED",
        "result_code": "APPROVAL_REQUIRED",
        "request_count": 0,
        "page_count": 0,
        "response_byte_count": 0,
        "elapsed_ms": 0,
        "partial_fill_state": "NOT_OBSERVED",
        "correction_cancel_state": "NOT_OBSERVED",
        "individual_fill_lineage": "NOT_EVALUATED",
        "retention_window": "NOT_EVALUATED",
        "manual_order_coverage": "NOT_EVALUATED",
        "oauth_read_only_scope": "NOT_EVALUATED",
        "order_operations": 0,
    }
    if approved is not True:
        return result
    try:
        start, end = date.fromisoformat(from_date), date.fromisoformat(to_date)
        if (
            start.isoformat() != from_date
            or end.isoformat() != to_date
            or not 0 <= (end - start).days < 30
        ):
            raise ValueError
        if any(
            type(v) is not str
            or not 0 < len(v) <= 4096
            or any(ord(c) < 32 or ord(c) > 126 for c in v)
            for v in (client_id, client_secret, account_seq)
        ):
            raise ValueError
        if not re.fullmatch(r"[1-9]\d{0,18}", account_seq):
            raise ValueError
    except ValueError, TypeError:
        result["result_code"] = "INVALID_INPUT"
        return result

    begun = time.monotonic()

    def timeout_handler(*_: Any) -> None:
        raise _Stop("TIMEOUT")

    try:
        if signal.getitimer(signal.ITIMER_REAL) != (0.0, 0.0):
            result["result_code"] = "DEADLINE_UNAVAILABLE"
            return result
        previous_handler = signal.signal(signal.SIGALRM, timeout_handler)
    except ValueError, AttributeError:
        result["result_code"] = "DEADLINE_UNAVAILABLE"
        return result

    def request(
        *, token: str | None = None, cursor: str | None = None
    ) -> dict[str, Any]:
        if result["request_count"] >= 5:
            raise _Stop("REQUEST_BUDGET_EXCEEDED")
        remaining = MAX_SECONDS - (time.monotonic() - begun)
        if remaining <= 0:
            raise _Stop("TIMEOUT")
        if result["response_byte_count"] >= MAX_BYTES:
            raise _Stop("BYTE_BUDGET_EXCEEDED")
        headers = {"Accept": "application/json", "Accept-Encoding": "identity"}
        if token is None:
            method, path = "POST", "/oauth2/token"
            body: str | None = urlencode(
                {
                    "grant_type": "client_credentials",
                    "client_id": client_id,
                    "client_secret": client_secret,
                }
            )
            headers["Content-Type"] = "application/x-www-form-urlencoded"
        else:
            method = "GET"
            params = {
                "status": "CLOSED",
                "limit": "20",
                "from": from_date,
                "to": to_date,
            }
            if cursor is not None:
                params["cursor"] = cursor
            path, body = "/api/v1/orders?" + urlencode(params), None
            headers.update(
                {
                    "Authorization": "Bearer " + token,
                    "X-Tossinvest-Account": account_seq,
                }
            )
        connection = http.client.HTTPSConnection(
            "openapi.tossinvest.com", timeout=remaining
        )
        connection.debuglevel = 0
        try:
            result["request_count"] += 1
            if token is not None:
                result["page_count"] += 1
            connection.request(method, path, body=body, headers=headers)
            response = connection.getresponse()
            if response.status != 200:
                if 300 <= response.status < 400:
                    raise _Stop("REDIRECT_FORBIDDEN")
                if response.status in {401, 403, 429}:
                    raise _Stop(f"HTTP_{response.status}")
                raise _Stop("HTTP_5XX" if response.status >= 500 else "HTTP_ERROR")
            chunks: list[bytes] = []
            while True:
                capacity = MAX_BYTES - result["response_byte_count"]
                if capacity <= 0:
                    raise _Stop("BYTE_BUDGET_EXCEEDED")
                chunk = response.read(min(65536, capacity))
                result["response_byte_count"] += len(chunk)
                chunks.append(chunk)
                if not chunk or response.isclosed():
                    break
            return _decode(b"".join(chunks))
        finally:
            connection.close()

    try:
        signal.setitimer(signal.ITIMER_REAL, MAX_SECONDS)
        token = request().get("access_token")
        if (
            type(token) is not str
            or not 0 < len(token) <= 16384
            or any(ord(c) < 33 or ord(c) > 126 for c in token)
        ):
            raise _Stop("MALFORMED_TOKEN")
        cursor: str | None = None
        seen_cursors: set[str] = set()
        seen_orders: set[str] = set()
        partial, correction = False, False
        for _ in range(MAX_PAGES):
            payload = request(token=token, cursor=cursor)
            page = payload.get("result")
            if (
                type(page) is not dict
                or type(page.get("orders")) is not list
                or type(page.get("hasNext")) is not bool
                or "nextCursor" not in page
            ):
                raise _Stop("MALFORMED_PAYLOAD")
            if len(page["orders"]) > 20:
                raise _Stop("MALFORMED_PAYLOAD")
            for order in page["orders"]:
                identity, has_partial, has_correction = _aggregate(order)
                if identity in seen_orders:
                    raise _Stop("DUPLICATE_ORDER")
                seen_orders.add(identity)
                partial, correction = (
                    partial or has_partial,
                    correction or has_correction,
                )
            cursor = page["nextCursor"]
            if not page["hasNext"]:
                if cursor is not None:
                    raise _Stop("MALFORMED_PAYLOAD")
                result.update(
                    {
                        "result_code": "COMPLETE_ORDER_AGGREGATE"
                        if seen_orders
                        else "COMPLETE_NO_ORDERS",
                        "provider_history_state": "ORDER_AGGREGATE_OBSERVED"
                        if seen_orders
                        else "QUERY_SUCCEEDED_NO_ORDERS",
                        "partial_fill_state": "OBSERVED_ORDER_AGGREGATE"
                        if partial
                        else "NOT_OBSERVED",
                        "correction_cancel_state": "OBSERVED_ORDER_STATE_ONLY"
                        if correction
                        else "NOT_OBSERVED",
                    }
                )
                break
            if type(cursor) is not str or not 0 < len(cursor) <= 8192:
                raise _Stop("MALFORMED_PAYLOAD")
            if cursor in seen_cursors:
                raise _Stop("CURSOR_LOOP")
            seen_cursors.add(cursor)
        else:
            raise _Stop("INCOMPLETE_PAGE_BUDGET")
    except _Stop as error:
        result["result_code"] = str(error)
    except TimeoutError:
        result["result_code"] = "TIMEOUT"
    except Exception:
        # Transport/parser exceptions can contain URLs, headers or private payloads.
        # Never log/re-raise them across the sanitized one-shot boundary.
        result["result_code"] = "TRANSPORT_OR_INTERNAL_ERROR"
    finally:
        signal.setitimer(signal.ITIMER_REAL, 0)
        signal.signal(signal.SIGALRM, previous_handler)
        result["elapsed_ms"] = round((time.monotonic() - begun) * 1000)
    return result
