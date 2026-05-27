from __future__ import annotations

import datetime as dt
from collections.abc import Iterable, Mapping
from zoneinfo import ZoneInfo

from ..data.trading_sessions import is_trading_session
from ..utils.market_time import ensure_aware_now, us_session_info

_KR_ZONE = ZoneInfo("Asia/Seoul")
_US_SESSION_STATE_MAP = {
    "pre_open": "PRE_OPEN",
    "intraday": "INTRADAY",
    "after_close": "AFTER_CLOSE",
    "closed": "AFTER_CLOSE",
}
_ALLOWED_SESSION_STATES = {"PRE_OPEN", "INTRADAY", "AFTER_CLOSE"}


def _normalize_markets(markets: Iterable[str] | None) -> list[str]:
    if markets is None:
        return []
    normalized: list[str] = []
    for market in markets:
        value = str(market or "").strip().upper()
        if value in {"KR", "US"} and value not in normalized:
            normalized.append(value)
    return normalized


def _normalize_state(value: str) -> str:
    normalized = str(value or "").strip().upper()
    if normalized in _ALLOWED_SESSION_STATES:
        return normalized
    return "AFTER_CLOSE"


def _normalize_state_map(
    session_state_by_market: Mapping[str, str] | None,
) -> dict[str, str]:
    if not session_state_by_market:
        return {}
    normalized: dict[str, str] = {}
    for market, state in session_state_by_market.items():
        normalized_market = str(market or "").strip().upper()
        if normalized_market not in {"KR", "US"}:
            continue
        normalized[normalized_market] = _normalize_state(state)
    return normalized


def _aggregate_states(states: Iterable[str]) -> str:
    unique = {_normalize_state(state) for state in states}
    if "INTRADAY" in unique:
        return "INTRADAY"
    if "PRE_OPEN" in unique:
        return "PRE_OPEN"
    return "AFTER_CLOSE"


def _resolve_kr_session_state(
    *,
    now: dt.datetime,
    data_dir: str | None,
) -> str:
    kst_now = now.astimezone(_KR_ZONE)
    session_date = kst_now.date()
    if not is_trading_session(session_date, market="KR", data_dir=data_dir):
        return "AFTER_CLOSE"
    t = kst_now.time()
    if t < dt.time(9, 0):
        return "PRE_OPEN"
    if t < dt.time(15, 30):
        return "INTRADAY"
    return "AFTER_CLOSE"


def _resolve_us_session_state(
    *,
    now: dt.datetime,
    data_dir: str | None,
) -> str:
    info = us_session_info(now=now, data_dir=data_dir)
    raw_state = str(info.get("state") or "").strip().lower()
    return _US_SESSION_STATE_MAP.get(raw_state, "AFTER_CLOSE")


def resolve_eval_markets(
    markets: list[str],
) -> tuple[str, list[str] | None, list[str] | None]:
    """정렬된 시장 목록을 단일/혼합(MIXED) 기준으로 분류한다.

    KR/US 단일 시장이면 그 시장을, 그 외(혼합·해외 등)는 ``MIXED``로 분류한다.
    반환값은 ``(eval_market, eval_markets, state_markets)``이며 ``state_markets``는
    세션 상태 조회(:func:`resolve_run_session_state`)에 넘길 시장 목록이다.
    """

    if len(markets) == 1 and markets[0] in {"KR", "US"}:
        eval_market = markets[0]
        eval_markets: list[str] | None = None
    else:
        eval_market = "MIXED"
        eval_markets = [m for m in markets if m in {"KR", "US"}] or None
    state_markets = [eval_market] if eval_market in {"KR", "US"} else eval_markets
    return eval_market, eval_markets, state_markets


def resolve_run_session_state(
    *,
    markets: Iterable[str] | None,
    data_dir: str | None,
    now: dt.datetime | None = None,
    session_state_by_market: Mapping[str, str] | None = None,
) -> str:
    normalized_state_map = _normalize_state_map(session_state_by_market)
    if normalized_state_map:
        return _aggregate_states(normalized_state_map.values())

    state_map = resolve_run_session_state_map(
        markets=markets,
        data_dir=data_dir,
        now=now,
    )
    if not state_map:
        return "AFTER_CLOSE"

    return _aggregate_states(state_map.values())


def resolve_run_session_state_map(
    *,
    markets: Iterable[str] | None,
    data_dir: str | None,
    now: dt.datetime | None = None,
) -> dict[str, str]:
    normalized_markets = _normalize_markets(markets)
    if not normalized_markets:
        return {}

    aware_now = ensure_aware_now(now)
    states: dict[str, str] = {}
    for market in normalized_markets:
        if market == "US":
            states[market] = _resolve_us_session_state(now=aware_now, data_dir=data_dir)
        else:
            states[market] = _resolve_kr_session_state(now=aware_now, data_dir=data_dir)
    return states


__all__ = [
    "resolve_eval_markets",
    "resolve_run_session_state",
    "resolve_run_session_state_map",
]
