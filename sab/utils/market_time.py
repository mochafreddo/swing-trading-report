from __future__ import annotations

import datetime as dt
import os
import re
from collections.abc import Mapping
from dataclasses import dataclass
from zoneinfo import ZoneInfo

from sab.data.holiday_cache import HolidayEntry, load_cached_holidays
from sab.data.us_calendar import load_us_trading_calendar

STATE_PRE_OPEN = "pre_open"
STATE_INTRADAY = "intraday"
STATE_AFTER_CLOSE = "after_close"
STATE_CLOSED = "closed"
_US_REGULAR_CLOSE = dt.time(16, 0)
_US_EARLY_CLOSE_HINTS = (
    "early close",
    "early-close",
    "half day",
    "half-day",
    "short session",
    "조기",
    "단축",
)
_US_HHMM_RE = re.compile(
    r"\b(?P<hour>\d{1,2})\s*:\s*(?P<minute>\d{2})\s*(?P<ampm>am|pm)?\b",
    re.IGNORECASE,
)
_US_HH_AMPM_RE = re.compile(
    r"\b(?P<hour>\d{1,2})\s*(?P<ampm>am|pm)\b",
    re.IGNORECASE,
)
_US_CLOSE_LABEL_HHMM_RE = re.compile(
    r"\b(?:close|closing)\b(?![^0-9]{0,12}\b(?:open|opening)\b)"
    r"[^0-9]{0,12}(?P<hour>\d{1,2})\s*:\s*(?P<minute>\d{2})\s*"
    r"(?P<ampm>am|pm)?\b",
    re.IGNORECASE,
)
_US_CLOSE_LABEL_HH_AMPM_RE = re.compile(
    r"\b(?:close|closing)\b(?![^0-9]{0,12}\b(?:open|opening)\b)"
    r"[^0-9]{0,12}(?P<hour>\d{1,2})\s*(?P<ampm>am|pm)\b",
    re.IGNORECASE,
)
_US_KR_HOUR_RE = re.compile(r"(?P<hour>\d{1,2})\s*시")
_US_KR_HHMM_RE = re.compile(r"(?P<hour>\d{1,2})\s*시\s*(?P<minute>\d{1,2})\s*분")
_US_KR_AMPM_RE = re.compile(r"(오전|오후)\s*(?P<hour>\d{1,2})\s*시")
_US_KR_CLOSE_LABEL_HHMM_RE = re.compile(
    r"(?:폐장|마감)[^0-9]{0,8}(?P<hour>\d{1,2})\s*시\s*(?P<minute>\d{1,2})\s*분"
)
_US_KR_CLOSE_LABEL_AMPM_RE = re.compile(
    r"(?:폐장|마감)[^0-9]{0,8}(오전|오후)\s*(?P<hour>\d{1,2})\s*시"
)
_US_KR_CLOSE_LABEL_HOUR_RE = re.compile(
    r"(?:폐장|마감)[^0-9]{0,8}(?P<hour>\d{1,2})\s*시"
)
_US_TIME_RANGE_DELIM_RE = re.compile(r"\s*(?:-|~|–|—|to)\s*", re.IGNORECASE)
_US_OPEN_CONTEXT_HINTS = ("open", "opening", "개장")
_US_REGULAR_CONTEXT_HINTS = ("regular", "normal", "정규", "통상")
_US_CONTEXT_BOUNDARY_CHARS = ",;()[]{}|/"
_US_CACHED_HOLIDAYS_BY_DIR: dict[str, tuple[float | None, dict[str, HolidayEntry]]] = {}


@dataclass(frozen=True)
class _TimeCandidate:
    parsed_time: dt.time
    start: int
    end: int


def _normalize_12h_hour(hour: int, ampm: str | None) -> int:
    if not ampm:
        return hour
    normalized_ampm = ampm.lower()
    if normalized_ampm == "am":
        return 0 if hour == 12 else hour
    if hour == 12:
        return 12
    return hour + 12


def _normalize_early_close_hour(hour: int, ampm: str | None = None) -> int:
    normalized = _normalize_12h_hour(hour, ampm)
    if ampm:
        return normalized
    # In US early-close context, ambiguous single-digit hours usually mean PM.
    if 1 <= normalized <= 7:
        return normalized + 12
    return normalized


def _resolve_data_dir(data_dir: str | None) -> str:
    return os.path.abspath(data_dir or os.getenv("SAB_DATA_DIR") or "data")


def _cached_holidays_mtime(data_dir: str) -> float | None:
    path = os.path.join(data_dir, "holidays_us.json")
    try:
        return os.path.getmtime(path)
    except OSError:
        return None


def _load_cached_us_holidays(data_dir: str | None) -> dict[str, HolidayEntry]:
    resolved_data_dir = _resolve_data_dir(data_dir)
    mtime = _cached_holidays_mtime(resolved_data_dir)
    cached_entry = _US_CACHED_HOLIDAYS_BY_DIR.get(resolved_data_dir)
    if cached_entry is not None and cached_entry[0] == mtime:
        return cached_entry[1]

    loaded = load_cached_holidays(resolved_data_dir, "US")
    _US_CACHED_HOLIDAYS_BY_DIR[resolved_data_dir] = (mtime, loaded)
    return loaded


def _us_early_close_time_from_entries(
    session_date: dt.date, cached_holidays: Mapping[str, HolidayEntry]
) -> dt.time | None:
    entry = cached_holidays.get(session_date.strftime("%Y%m%d"))
    if not entry or not entry.is_open:
        return None
    return _parse_us_early_close_time(entry.note)


def _build_time_candidate(
    *,
    hour: int,
    minute: int,
    start: int,
    end: int,
    ampm: str | None = None,
    normalize_early: bool = True,
) -> _TimeCandidate | None:
    normalized_hour = (
        _normalize_early_close_hour(hour, ampm)
        if normalize_early
        else _normalize_12h_hour(hour, ampm)
    )
    if not (0 <= normalized_hour <= 23 and 0 <= minute <= 59):
        return None
    return _TimeCandidate(dt.time(normalized_hour, minute), start=start, end=end)


def _find_hint_spans(lowered_note: str) -> list[tuple[int, int]]:
    spans: list[tuple[int, int]] = []
    for hint in _US_EARLY_CLOSE_HINTS:
        cursor = 0
        while True:
            idx = lowered_note.find(hint, cursor)
            if idx < 0:
                break
            spans.append((idx, idx + len(hint)))
            cursor = idx + 1
    spans.sort()
    return spans


def _span_distance(
    *,
    start: int,
    end: int,
    other_start: int,
    other_end: int,
) -> int:
    if end <= other_start:
        return other_start - end
    if other_end <= start:
        return start - other_end
    return 0


def _nearest_hint_distance(
    *,
    start: int,
    end: int,
    hint_spans: list[tuple[int, int]],
) -> int | None:
    if not hint_spans:
        return None
    return min(
        _span_distance(
            start=start,
            end=end,
            other_start=hint_start,
            other_end=hint_end,
        )
        for hint_start, hint_end in hint_spans
    )


def _collect_us_early_close_candidates(
    note: str, lowered_note: str
) -> list[_TimeCandidate]:
    candidates: list[_TimeCandidate] = []
    seen: set[tuple[dt.time, int, int]] = set()

    def add(candidate: _TimeCandidate | None) -> None:
        if candidate is None:
            return
        key = (candidate.parsed_time, candidate.start, candidate.end)
        if key in seen:
            return
        seen.add(key)
        candidates.append(candidate)

    for match in _US_HHMM_RE.finditer(lowered_note):
        add(
            _build_time_candidate(
                hour=int(match.group("hour")),
                minute=int(match.group("minute")),
                ampm=match.group("ampm"),
                start=match.start(),
                end=match.end(),
            )
        )

    for match in _US_HH_AMPM_RE.finditer(lowered_note):
        add(
            _build_time_candidate(
                hour=int(match.group("hour")),
                minute=0,
                ampm=match.group("ampm"),
                start=match.start(),
                end=match.end(),
            )
        )

    for match in _US_KR_HHMM_RE.finditer(note):
        add(
            _build_time_candidate(
                hour=int(match.group("hour")),
                minute=int(match.group("minute")),
                start=match.start(),
                end=match.end(),
            )
        )

    for match in _US_KR_AMPM_RE.finditer(note):
        ampm = "am" if "오전" in match.group(0) else "pm"
        add(
            _build_time_candidate(
                hour=int(match.group("hour")),
                minute=0,
                ampm=ampm,
                start=match.start(),
                end=match.end(),
                normalize_early=False,
            )
        )

    for match in _US_KR_HOUR_RE.finditer(note):
        add(
            _build_time_candidate(
                hour=int(match.group("hour")),
                minute=0,
                start=match.start(),
                end=match.end(),
            )
        )

    candidates.sort(key=lambda candidate: (candidate.start, candidate.end))
    return candidates


def _parse_labeled_close_time(note: str, lowered_note: str) -> dt.time | None:
    labeled_candidates: list[_TimeCandidate] = []

    for match in _US_CLOSE_LABEL_HHMM_RE.finditer(lowered_note):
        candidate = _build_time_candidate(
            hour=int(match.group("hour")),
            minute=int(match.group("minute")),
            ampm=match.group("ampm"),
            start=match.start(),
            end=match.end(),
        )
        if candidate is not None:
            labeled_candidates.append(candidate)

    for match in _US_CLOSE_LABEL_HH_AMPM_RE.finditer(lowered_note):
        candidate = _build_time_candidate(
            hour=int(match.group("hour")),
            minute=0,
            ampm=match.group("ampm"),
            start=match.start(),
            end=match.end(),
        )
        if candidate is not None:
            labeled_candidates.append(candidate)

    for match in _US_KR_CLOSE_LABEL_HHMM_RE.finditer(note):
        candidate = _build_time_candidate(
            hour=int(match.group("hour")),
            minute=int(match.group("minute")),
            start=match.start(),
            end=match.end(),
        )
        if candidate is not None:
            labeled_candidates.append(candidate)

    for match in _US_KR_CLOSE_LABEL_AMPM_RE.finditer(note):
        ampm = "am" if "오전" in match.group(0) else "pm"
        candidate = _build_time_candidate(
            hour=int(match.group("hour")),
            minute=0,
            ampm=ampm,
            start=match.start(),
            end=match.end(),
            normalize_early=False,
        )
        if candidate is not None:
            labeled_candidates.append(candidate)

    for match in _US_KR_CLOSE_LABEL_HOUR_RE.finditer(note):
        candidate = _build_time_candidate(
            hour=int(match.group("hour")),
            minute=0,
            start=match.start(),
            end=match.end(),
        )
        if candidate is not None:
            labeled_candidates.append(candidate)

    if not labeled_candidates:
        return None
    labeled_candidates.sort(key=lambda candidate: (candidate.start, candidate.end))

    hint_spans = _find_hint_spans(lowered_note)
    if hint_spans:
        ranked: tuple[tuple[int, int, int, int, int], _TimeCandidate] | None = None
        for candidate in labeled_candidates:
            dist = _nearest_hint_distance(
                start=candidate.start,
                end=candidate.end,
                hint_spans=hint_spans,
            )
            if dist is None:
                dist = 10_000
            regular_rank = (
                1 if _has_regular_close_context(lowered_note, candidate) else 0
            )
            key = (
                regular_rank,
                dist,
                candidate.start,
                candidate.parsed_time.hour,
                candidate.parsed_time.minute,
            )
            if ranked is None or key < ranked[0]:
                ranked = (key, candidate)
        if ranked is not None:
            return ranked[1].parsed_time

    return min(
        labeled_candidates,
        key=lambda candidate: (
            1 if _has_regular_close_context(lowered_note, candidate) else 0,
            candidate.start,
        ),
    ).parsed_time


def _has_regular_close_context(lowered_note: str, candidate: _TimeCandidate) -> bool:
    prefix_window = lowered_note[max(0, candidate.start - 48) : candidate.start]
    boundary_idx = -1
    for boundary in _US_CONTEXT_BOUNDARY_CHARS:
        boundary_idx = max(boundary_idx, prefix_window.rfind(boundary))
    clause_prefix = prefix_window[boundary_idx + 1 :]
    for token in _US_REGULAR_CONTEXT_HINTS:
        token_idx = clause_prefix.rfind(token)
        if token_idx < 0:
            continue
        trailing = clause_prefix[token_idx + len(token) :]
        if len(trailing) <= 12:
            return True
    return False


def _has_open_context(lowered_note: str, candidate: _TimeCandidate) -> bool:
    window_start = max(0, candidate.start - 16)
    window_end = min(len(lowered_note), candidate.end + 16)
    context = lowered_note[window_start:window_end]
    return any(token in context for token in _US_OPEN_CONTEXT_HINTS)


def _select_early_close_candidate(
    *,
    lowered_note: str,
    candidates: list[_TimeCandidate],
) -> _TimeCandidate | None:
    if not candidates:
        return None
    if len(candidates) == 1:
        return candidates[0]

    hint_spans = _find_hint_spans(lowered_note)

    if hint_spans:
        range_choice: tuple[tuple[int, int, int, int], _TimeCandidate] | None = None
        for idx in range(len(candidates) - 1):
            left = candidates[idx]
            right = candidates[idx + 1]
            between = lowered_note[left.end : right.start]
            if not _US_TIME_RANGE_DELIM_RE.fullmatch(between):
                continue
            dist = _nearest_hint_distance(
                start=left.start,
                end=right.end,
                hint_spans=hint_spans,
            )
            if dist is None:
                continue
            key = (
                dist,
                -right.parsed_time.hour,
                -right.parsed_time.minute,
                -right.start,
            )
            if range_choice is None or key < range_choice[0]:
                range_choice = (key, right)
        if range_choice is not None:
            return range_choice[1]

        ranked: tuple[tuple[int, int, int, int], _TimeCandidate] | None = None
        for candidate in candidates:
            dist = _nearest_hint_distance(
                start=candidate.start,
                end=candidate.end,
                hint_spans=hint_spans,
            )
            if dist is None:
                continue
            open_penalty = 8 if _has_open_context(lowered_note, candidate) else 0
            key = (
                dist + open_penalty,
                -candidate.parsed_time.hour,
                -candidate.parsed_time.minute,
                -candidate.start,
            )
            if ranked is None or key < ranked[0]:
                ranked = (key, candidate)
        if ranked is not None:
            return ranked[1]

    return max(
        candidates,
        key=lambda candidate: (
            candidate.parsed_time.hour,
            candidate.parsed_time.minute,
            candidate.start,
        ),
    )


def _parse_us_early_close_time(note: str | None) -> dt.time | None:
    if not note:
        return None
    lowered = note.lower()
    if not any(hint in lowered for hint in _US_EARLY_CLOSE_HINTS):
        return None

    labeled_close = _parse_labeled_close_time(note, lowered)
    if labeled_close is not None:
        return labeled_close

    candidates = _collect_us_early_close_candidates(note, lowered)
    selected = _select_early_close_candidate(
        lowered_note=lowered,
        candidates=candidates,
    )
    return selected.parsed_time if selected is not None else None


def us_early_close_time(
    session_date: dt.date,
    *,
    data_dir: str | None = None,
) -> dt.time | None:
    cached_holidays = _load_cached_us_holidays(data_dir)
    return _us_early_close_time_from_entries(session_date, cached_holidays)


def is_us_market_open(
    now: dt.datetime | None = None,
    *,
    data_dir: str | None = None,
) -> bool:
    info = us_session_info(now=now, data_dir=data_dir)
    return info.get("state") == STATE_INTRADAY


def us_market_status(
    now: dt.datetime | None = None,
    *,
    data_dir: str | None = None,
) -> str:
    return "open" if is_us_market_open(now, data_dir=data_dir) else "closed"


def us_session_info(
    now: dt.datetime | None = None,
    *,
    data_dir: str | None = None,
) -> dict[str, object]:
    """Return US session state and preferred nday for KIS rank calls.

    preferred_nday:
    - 0 when the prior session has closed (post 16:00 ET same day).
    - 1 when we are pre-open, intraday, weekend, or a known holiday (use last
      confirmed session).
    """
    aware_now = now
    if aware_now is None:
        aware_now = dt.datetime.now(tz=ZoneInfo("UTC"))
    elif aware_now.tzinfo is None:
        aware_now = aware_now.replace(tzinfo=ZoneInfo("UTC"))

    ny_now = aware_now.astimezone(ZoneInfo("America/New_York"))
    session_date = ny_now.date()
    weekday = ny_now.weekday()  # 0=Mon

    data_dir = _resolve_data_dir(data_dir)
    # Load holiday map (built-ins + overrides + cached KIS fetches).
    holidays = load_us_trading_calendar(data_dir)
    cached = _load_cached_us_holidays(data_dir)
    # cached values have is_open flag; treat is_open False as holiday/closure
    for key, entry in cached.items():
        if not entry.is_open:
            holidays[key] = entry.note or holidays.get(key, "")

    is_holiday = session_date.strftime("%Y%m%d") in holidays

    close_time = (
        _us_early_close_time_from_entries(session_date, cached) or _US_REGULAR_CLOSE
    )

    if weekday >= 5 or is_holiday:
        state = STATE_CLOSED
    else:
        t = ny_now.time()
        if t < dt.time(9, 30):
            state = STATE_PRE_OPEN
        elif t < close_time:
            state = STATE_INTRADAY
        else:
            state = STATE_AFTER_CLOSE

    preferred_nday = 0 if state == STATE_AFTER_CLOSE and not is_holiday else 1

    return {
        "state": state,
        "session_date": session_date,
        "is_holiday": is_holiday,
        "preferred_nday": preferred_nday,
        "ny_now": ny_now,
        "close_time": close_time,
    }


__all__ = [
    "is_us_market_open",
    "us_market_status",
    "us_session_info",
    "STATE_PRE_OPEN",
    "STATE_INTRADAY",
    "STATE_AFTER_CLOSE",
    "STATE_CLOSED",
    "us_early_close_time",
]
