from __future__ import annotations

import datetime as dt


def offset_iso(now: dt.datetime | None = None) -> str:
    if now is None:
        aware = dt.datetime.now().astimezone()
    elif now.tzinfo is None:
        local_tz = dt.datetime.now().astimezone().tzinfo or dt.UTC
        aware = now.replace(tzinfo=local_tz)
    else:
        aware = now
    return aware.replace(microsecond=0).isoformat(timespec="seconds")


def parse_iso_offset_datetime(
    value: object,
    *,
    field_name: str,
    empty_message: str | None = None,
) -> dt.datetime:
    text = str(value or "").strip()
    if not text:
        raise ValueError(empty_message or f"{field_name} is required")
    try:
        parsed = dt.datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError(f"{field_name} must be an ISO 8601 datetime") from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError(f"{field_name} must include a UTC offset")
    return parsed
