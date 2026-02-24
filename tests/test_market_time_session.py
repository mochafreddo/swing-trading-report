import datetime as dt
import tempfile
from zoneinfo import ZoneInfo

from sab.utils.market_time import (
    STATE_AFTER_CLOSE,
    STATE_CLOSED,
    STATE_INTRADAY,
    STATE_PRE_OPEN,
    is_us_market_open,
    us_market_status,
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


def test_us_market_status_respects_holiday_calendar(tmp_path) -> None:
    data_dir = tmp_path.as_posix()
    holidays_path = tmp_path / "holidays_us.json"
    holidays_path.write_text(
        '{"20261225": {"note": "Christmas", "is_open": false}}',
        encoding="utf-8",
    )
    now = dt.datetime(2026, 12, 25, 15, 0, tzinfo=ZoneInfo("America/New_York"))

    assert is_us_market_open(now, data_dir=data_dir) is False
    assert us_market_status(now, data_dir=data_dir) == "closed"


def test_us_session_info_early_close_uses_custom_close_time(tmp_path) -> None:
    data_dir = tmp_path.as_posix()
    holidays_path = tmp_path / "holidays_us.json"
    holidays_path.write_text(
        '{"20251224": {"note": "Early close 13:00 ET", "is_open": true}}',
        encoding="utf-8",
    )
    now = dt.datetime(2025, 12, 24, 14, 30, tzinfo=ZoneInfo("America/New_York"))

    info = us_session_info(now=now, data_dir=data_dir)

    assert info["state"] == STATE_AFTER_CLOSE
    assert info["preferred_nday"] == 0
    assert is_us_market_open(now, data_dir=data_dir) is False


def test_us_session_info_early_close_parses_korean_hour_note(tmp_path) -> None:
    data_dir = tmp_path.as_posix()
    holidays_path = tmp_path / "holidays_us.json"
    holidays_path.write_text(
        '{"20251224": {"note": "조기폐장 13시", "is_open": true}}',
        encoding="utf-8",
    )
    now = dt.datetime(2025, 12, 24, 14, 30, tzinfo=ZoneInfo("America/New_York"))

    info = us_session_info(now=now, data_dir=data_dir)

    assert info["state"] == STATE_AFTER_CLOSE
    assert info["preferred_nday"] == 0
    assert is_us_market_open(now, data_dir=data_dir) is False


def test_us_session_info_early_close_parses_korean_1si_as_13(tmp_path) -> None:
    data_dir = tmp_path.as_posix()
    holidays_path = tmp_path / "holidays_us.json"
    holidays_path.write_text(
        '{"20251224": {"note": "조기폐장 1시", "is_open": true}}',
        encoding="utf-8",
    )
    now = dt.datetime(2025, 12, 24, 12, 30, tzinfo=ZoneInfo("America/New_York"))

    info = us_session_info(now=now, data_dir=data_dir)

    assert info["close_time"] == dt.time(13, 0)
    assert info["state"] == STATE_INTRADAY
    assert info["preferred_nday"] == 1
    assert is_us_market_open(now, data_dir=data_dir) is True


def test_us_session_info_early_close_parses_english_1pm_without_ampm(
    tmp_path,
) -> None:
    data_dir = tmp_path.as_posix()
    holidays_path = tmp_path / "holidays_us.json"
    holidays_path.write_text(
        '{"20251224": {"note": "Early close 1:00 ET", "is_open": true}}',
        encoding="utf-8",
    )
    now = dt.datetime(2025, 12, 24, 12, 30, tzinfo=ZoneInfo("America/New_York"))

    info = us_session_info(now=now, data_dir=data_dir)

    assert info["close_time"] == dt.time(13, 0)
    assert info["state"] == STATE_INTRADAY
    assert info["preferred_nday"] == 1
    assert is_us_market_open(now, data_dir=data_dir) is True


def test_us_session_info_early_close_prefers_close_time_when_open_time_also_present(
    tmp_path,
) -> None:
    data_dir = tmp_path.as_posix()
    holidays_path = tmp_path / "holidays_us.json"
    holidays_path.write_text(
        '{"20251224": {"note": "Open 09:30 ET, Early close 1:00 ET", "is_open": true}}',
        encoding="utf-8",
    )
    now = dt.datetime(2025, 12, 24, 12, 30, tzinfo=ZoneInfo("America/New_York"))

    info = us_session_info(now=now, data_dir=data_dir)

    assert info["close_time"] == dt.time(13, 0)
    assert info["state"] == STATE_INTRADAY
    assert info["preferred_nday"] == 1
    assert is_us_market_open(now, data_dir=data_dir) is True


def test_us_session_info_early_close_parses_time_range_end_as_close(tmp_path) -> None:
    data_dir = tmp_path.as_posix()
    holidays_path = tmp_path / "holidays_us.json"
    holidays_path.write_text(
        '{"20251224": {"note": "Short session 09:30-13:00", "is_open": true}}',
        encoding="utf-8",
    )
    now = dt.datetime(2025, 12, 24, 12, 30, tzinfo=ZoneInfo("America/New_York"))

    info = us_session_info(now=now, data_dir=data_dir)

    assert info["close_time"] == dt.time(13, 0)
    assert info["state"] == STATE_INTRADAY
    assert info["preferred_nday"] == 1
    assert is_us_market_open(now, data_dir=data_dir) is True


def test_us_session_info_early_close_prefers_labeled_close_time(tmp_path) -> None:
    data_dir = tmp_path.as_posix()
    holidays_path = tmp_path / "holidays_us.json"
    holidays_path.write_text(
        '{"20251224": {"note": "Early close: open 09:30, close 13:00", "is_open": true}}',
        encoding="utf-8",
    )
    now = dt.datetime(2025, 12, 24, 12, 30, tzinfo=ZoneInfo("America/New_York"))

    info = us_session_info(now=now, data_dir=data_dir)

    assert info["close_time"] == dt.time(13, 0)
    assert info["state"] == STATE_INTRADAY
    assert info["preferred_nday"] == 1
    assert is_us_market_open(now, data_dir=data_dir) is True


def test_us_session_info_early_close_ignores_regular_close_label(tmp_path) -> None:
    data_dir = tmp_path.as_posix()
    holidays_path = tmp_path / "holidays_us.json"
    holidays_path.write_text(
        '{"20251224": {"note": "Early close: close 1:00 PM (regular close 4:00 PM)", "is_open": true}}',
        encoding="utf-8",
    )
    now = dt.datetime(2025, 12, 24, 12, 30, tzinfo=ZoneInfo("America/New_York"))

    info = us_session_info(now=now, data_dir=data_dir)

    assert info["close_time"] == dt.time(13, 0)
    assert info["state"] == STATE_INTRADAY
    assert info["preferred_nday"] == 1
    assert is_us_market_open(now, data_dir=data_dir) is True


def test_us_session_info_early_close_prefers_non_regular_close_with_slash(
    tmp_path,
) -> None:
    data_dir = tmp_path.as_posix()
    holidays_path = tmp_path / "holidays_us.json"
    holidays_path.write_text(
        '{"20251224": {"note": "Half day regular close 4:00 PM / close 1:00 PM", "is_open": true}}',
        encoding="utf-8",
    )
    now = dt.datetime(2025, 12, 24, 14, 30, tzinfo=ZoneInfo("America/New_York"))

    info = us_session_info(now=now, data_dir=data_dir)

    assert info["close_time"] == dt.time(13, 0)
    assert info["state"] == STATE_AFTER_CLOSE
    assert info["preferred_nday"] == 0
    assert is_us_market_open(now, data_dir=data_dir) is False


def test_us_early_close_time_reuses_cached_holiday_load(tmp_path, monkeypatch) -> None:
    import sab.utils.market_time as mt

    data_dir = tmp_path.as_posix()
    holidays_path = tmp_path / "holidays_us.json"
    holidays_path.write_text(
        '{"20251224": {"note": "Early close 13:00 ET", "is_open": true}}',
        encoding="utf-8",
    )
    day = dt.date(2025, 12, 24)

    if hasattr(mt, "_US_CACHED_HOLIDAYS_BY_DIR"):
        mt._US_CACHED_HOLIDAYS_BY_DIR.clear()

    original_loader = mt.load_cached_holidays
    calls = {"count": 0}

    def _counting_loader(cache_dir: str, country_code: str):
        calls["count"] += 1
        return original_loader(cache_dir, country_code)

    monkeypatch.setattr(mt, "load_cached_holidays", _counting_loader)

    assert mt.us_early_close_time(day, data_dir=data_dir) == dt.time(13, 0)
    assert mt.us_early_close_time(day, data_dir=data_dir) == dt.time(13, 0)
    assert calls["count"] == 1
