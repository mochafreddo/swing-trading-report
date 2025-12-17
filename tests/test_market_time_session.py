import datetime as dt
import tempfile
from zoneinfo import ZoneInfo

from sab.utils.market_time import (
    STATE_AFTER_CLOSE,
    STATE_CLOSED,
    STATE_INTRADAY,
    STATE_PRE_OPEN,
    us_session_info,
)


def _ny(dt_utc: dt.datetime) -> dt.datetime:
    if dt_utc.tzinfo is None:
        dt_utc = dt_utc.replace(tzinfo=ZoneInfo("UTC"))
    return dt_utc.astimezone(ZoneInfo("America/New_York"))


def test_us_session_info_after_close_prefers_today() -> None:
    # 2025-12-12 22:00 UTC -> 17:00 ET (after close, non-holiday)
    now = dt.datetime(2025, 12, 12, 22, 0, tzinfo=ZoneInfo("UTC"))
    with tempfile.TemporaryDirectory() as tmpdir:
        info = us_session_info(now=now, data_dir=tmpdir)
    assert info["state"] == STATE_AFTER_CLOSE
    assert info["preferred_nday"] == 0
    assert info["session_date"] == _ny(now).date()


def test_us_session_info_pre_open_prefers_previous_session() -> None:
    # 2025-12-12 11:00 UTC -> 06:00 ET (pre-open)
    now = dt.datetime(2025, 12, 12, 11, 0, tzinfo=ZoneInfo("UTC"))
    with tempfile.TemporaryDirectory() as tmpdir:
        info = us_session_info(now=now, data_dir=tmpdir)
    assert info["state"] == STATE_PRE_OPEN
    assert info["preferred_nday"] == 1


def test_us_session_info_weekend_prefers_previous_session() -> None:
    # Sunday ET
    now = dt.datetime(2025, 12, 14, 12, 0, tzinfo=ZoneInfo("UTC"))
    with tempfile.TemporaryDirectory() as tmpdir:
        info = us_session_info(now=now, data_dir=tmpdir)
    assert info["state"] == STATE_CLOSED
    assert info["preferred_nday"] == 1


def test_us_session_info_intraday_prefers_previous_session() -> None:
    # Weekday intraday -> use last confirmed close (nday=1)
    now = dt.datetime(2025, 12, 16, 15, 0, tzinfo=ZoneInfo("UTC"))  # 10:00 ET
    with tempfile.TemporaryDirectory() as tmpdir:
        info = us_session_info(now=now, data_dir=tmpdir)
    assert info["state"] == STATE_INTRADAY
    assert info["preferred_nday"] == 1


def test_us_session_info_holiday_prefers_previous_session(tmp_path) -> None:
    # Override cached holidays to mark a closure; should prefer nday=1
    data_dir = tmp_path.as_posix()
    holidays_path = tmp_path / "holidays_us.json"
    holidays_path.write_text(
        '{"20251226": {"note": "Custom Closure", "is_open": false}}', encoding="utf-8"
    )
    now = dt.datetime(2025, 12, 26, 15, 0, tzinfo=ZoneInfo("UTC"))  # Holiday override
    info = us_session_info(now=now, data_dir=data_dir)
    assert info["state"] == STATE_CLOSED
    assert info["preferred_nday"] == 1
