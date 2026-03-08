from __future__ import annotations

import datetime as _dt


def normalize_artifact_date(value: object | None) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    if not text:
        return None
    try:
        if len(text) == 10:
            return _dt.date.fromisoformat(text).isoformat()
        if len(text) == 8 and text.isdigit():
            return _dt.datetime.strptime(text, "%Y%m%d").date().isoformat()
    except ValueError:
        return None
    return None


def resolve_report_timestamp(
    now: _dt.datetime | None = None,
    *,
    artifact_date: object | None = None,
) -> tuple[str, str, str]:
    if now is None:
        aware_now = _dt.datetime.now().astimezone()
    elif now.tzinfo is None:
        local_tz = _dt.datetime.now().astimezone().tzinfo or _dt.UTC
        aware_now = now.replace(tzinfo=local_tz)
    else:
        aware_now = now

    date_str = normalize_artifact_date(artifact_date) or aware_now.strftime("%Y-%m-%d")
    time_str = aware_now.strftime("%Y-%m-%d %H:%M")
    tz_label = aware_now.tzname()
    if not tz_label:
        offset = aware_now.strftime("%z")
        tz_label = f"UTC{offset[:3]}:{offset[3:]}" if offset else "LOCAL"
    return date_str, time_str, tz_label


__all__ = ["normalize_artifact_date", "resolve_report_timestamp"]
