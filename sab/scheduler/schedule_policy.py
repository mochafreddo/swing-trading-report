from __future__ import annotations

import datetime as dt
from dataclasses import dataclass
from zoneinfo import ZoneInfo

_KR_ZONE = ZoneInfo("Asia/Seoul")
_US_ZONE = ZoneInfo("America/New_York")
_LAUNCHD_WEEKDAYS = (1, 2, 3, 4, 5)
_US_ET_TO_KST_CANDIDATE_HOUR_OFFSETS = (13, 14)


@dataclass(frozen=True, slots=True)
class RoleWindow:
    start: dt.time
    end: dt.time


@dataclass(frozen=True, slots=True)
class ScheduleDispatch:
    market: str
    schedule_role: str
    runner_role: str
    scheduled_tick: str
    github_crons: tuple[str, ...] = ()
    launchd_plist_path: str | None = None
    launchd_weekdays: tuple[int, ...] = _LAUNCHD_WEEKDAYS
    launchd_kst_times: tuple[dt.time, ...] | None = None


_ROLE_WINDOWS: dict[str, dict[str, RoleWindow]] = {
    "KR": {
        "local-primary": RoleWindow(dt.time(7, 25), dt.time(8, 5)),
        "local-retry": RoleWindow(dt.time(8, 5), dt.time(8, 55)),
        "cutoff-alert": RoleWindow(dt.time(8, 55), dt.time(9, 20)),
    },
    "US": {
        "local-primary": RoleWindow(dt.time(8, 5), dt.time(8, 30)),
        "early-monitor": RoleWindow(dt.time(8, 30), dt.time(8, 45)),
        "local-retry": RoleWindow(dt.time(8, 40), dt.time(8, 55)),
        "github-fallback": RoleWindow(dt.time(8, 55), dt.time(9, 25)),
        "cutoff-alert": RoleWindow(dt.time(9, 29), dt.time(10, 0)),
    },
}

_ROLE_WINDOW_END_GRACE: dict[str, dict[str, dt.timedelta]] = {
    "US": {
        # GitHub schedule runs can start after the nominal fallback window.
        # Keep the grace before regular open; PRE_OPEN guards still decide.
        "github-fallback": dt.timedelta(minutes=4),
    },
}

_SCHEDULE_DISPATCHES: tuple[ScheduleDispatch, ...] = (
    ScheduleDispatch(
        market="US",
        schedule_role="early-monitor",
        runner_role="monitor-only",
        scheduled_tick="0830",
        github_crons=("30 12 * * 1-5", "30 13 * * 1-5"),
    ),
    ScheduleDispatch(
        market="US",
        schedule_role="github-fallback",
        runner_role="github-fallback",
        scheduled_tick="0855",
        github_crons=("55 12 * * 1-5", "55 13 * * 1-5"),
    ),
    ScheduleDispatch(
        market="US",
        schedule_role="cutoff-alert",
        runner_role="cutoff-alert",
        scheduled_tick="0929",
        github_crons=("29 13 * * 1-5", "29 14 * * 1-5"),
        launchd_plist_path=(
            "scripts/launchd/com.mochafreddo.sab.ai-brief.us.cutoff-alert.plist"
        ),
    ),
    ScheduleDispatch(
        market="US",
        schedule_role="local-primary",
        runner_role="local-primary",
        scheduled_tick="0810",
        launchd_plist_path=(
            "scripts/launchd/com.mochafreddo.sab.ai-brief.us.local-primary.plist"
        ),
    ),
    ScheduleDispatch(
        market="US",
        schedule_role="local-retry",
        runner_role="local-retry",
        scheduled_tick="0845",
        launchd_plist_path=(
            "scripts/launchd/com.mochafreddo.sab.ai-brief.us.local-retry.plist"
        ),
    ),
    ScheduleDispatch(
        market="MIXED",
        schedule_role="sell-generation",
        runner_role="local-primary",
        scheduled_tick="0725",
        launchd_plist_path=(
            "scripts/launchd/com.mochafreddo.sab.sell-ai-brief.generation.plist"
        ),
        launchd_weekdays=(2, 3, 4, 5, 6),
        launchd_kst_times=(dt.time(7, 25),),
    ),
)

_GITHUB_SCHEDULE_MAP = {
    cron: dispatch
    for dispatch in _SCHEDULE_DISPATCHES
    for cron in dispatch.github_crons
}


def _normalize_market(market: str) -> str:
    return str(market or "").strip().upper()


def _normalize_role(role: str) -> str:
    return str(role or "").strip().lower()


def _tick_time(tick: str) -> dt.time:
    normalized = str(tick or "").strip()
    if len(normalized) != 4 or not normalized.isdigit():
        raise ValueError(f"scheduled tick must use HHMM format: {tick!r}")
    return dt.time(int(normalized[:2]), int(normalized[2:]))


def market_zone(market: str) -> ZoneInfo:
    normalized = _normalize_market(market)
    if normalized == "KR":
        return _KR_ZONE
    if normalized == "US":
        return _US_ZONE
    raise ValueError("market must be KR or US")


def role_window(market: str, schedule_role: str) -> RoleWindow | None:
    return _ROLE_WINDOWS.get(_normalize_market(market), {}).get(
        _normalize_role(schedule_role)
    )


def require_role_window(market: str, schedule_role: str) -> RoleWindow:
    window = role_window(market, schedule_role)
    if window is None:
        raise KeyError(
            f"missing scheduled AI Brief role window: "
            f"{_normalize_market(market)} {_normalize_role(schedule_role)}"
        )
    return window


def role_window_end_grace(market: str, schedule_role: str) -> dt.timedelta:
    return _ROLE_WINDOW_END_GRACE.get(_normalize_market(market), {}).get(
        _normalize_role(schedule_role),
        dt.timedelta(),
    )


def role_deadline_at(
    market: str, schedule_role: str, now: dt.datetime
) -> dt.datetime | None:
    normalized_market = _normalize_market(market)
    normalized_role = _normalize_role(schedule_role)
    window = role_window(normalized_market, normalized_role)
    if window is None:
        return None
    if now.tzinfo is None:
        now = now.replace(tzinfo=dt.UTC)
    zone = market_zone(normalized_market)
    local_now = now.astimezone(zone)
    deadline_local = dt.datetime.combine(
        local_now.date(),
        window.end,
        tzinfo=zone,
    ) + role_window_end_grace(normalized_market, normalized_role)
    return deadline_local.astimezone(dt.UTC)


def is_within_role_window(*, market: str, schedule_role: str, now: dt.datetime) -> bool:
    window = role_window(market, schedule_role)
    if window is None:
        return False
    if now.tzinfo is None:
        now = now.replace(tzinfo=dt.UTC)
    local_now = now.astimezone(market_zone(market))
    grace = role_window_end_grace(market, schedule_role)
    start_at = dt.datetime.combine(
        local_now.date(),
        window.start,
        tzinfo=local_now.tzinfo,
    )
    end_at = dt.datetime.combine(
        local_now.date(),
        window.end,
        tzinfo=local_now.tzinfo,
    )
    return start_at <= local_now < end_at + grace


def github_schedule_crons() -> tuple[str, ...]:
    return tuple(
        cron for dispatch in _SCHEDULE_DISPATCHES for cron in dispatch.github_crons
    )


def github_schedule_map() -> dict[str, ScheduleDispatch]:
    return dict(_GITHUB_SCHEDULE_MAP)


def dispatch_for_github_cron(cron: str) -> ScheduleDispatch:
    try:
        return _GITHUB_SCHEDULE_MAP[cron]
    except KeyError as exc:
        raise KeyError(f"unsupported AI Brief schedule: {cron}") from exc


def launchd_schedule_map() -> dict[str, ScheduleDispatch]:
    return {
        str(dispatch.launchd_plist_path): dispatch
        for dispatch in _SCHEDULE_DISPATCHES
        if dispatch.launchd_plist_path is not None
    }


def _launchd_candidate_times(dispatch: ScheduleDispatch) -> tuple[dt.time, ...]:
    if dispatch.launchd_kst_times is not None:
        return dispatch.launchd_kst_times
    if dispatch.market != "US":
        raise ValueError("launchd scheduler policy currently supports US ET ticks")
    tick = _tick_time(dispatch.scheduled_tick)
    candidate_times = []
    for offset in _US_ET_TO_KST_CANDIDATE_HOUR_OFFSETS:
        hour = tick.hour + offset
        if hour >= 24:
            raise ValueError("launchd candidate time must not roll over KST date")
        candidate_times.append(dt.time(hour, tick.minute))
    return tuple(candidate_times)


def launchd_start_calendar_intervals(
    dispatch: ScheduleDispatch,
) -> tuple[dict[str, int], ...]:
    return tuple(
        {
            "Weekday": weekday,
            "Hour": candidate_time.hour,
            "Minute": candidate_time.minute,
        }
        for candidate_time in _launchd_candidate_times(dispatch)
        for weekday in dispatch.launchd_weekdays
    )


__all__ = [
    "RoleWindow",
    "ScheduleDispatch",
    "dispatch_for_github_cron",
    "github_schedule_crons",
    "github_schedule_map",
    "is_within_role_window",
    "launchd_schedule_map",
    "launchd_start_calendar_intervals",
    "market_zone",
    "require_role_window",
    "role_deadline_at",
    "role_window",
    "role_window_end_grace",
]
