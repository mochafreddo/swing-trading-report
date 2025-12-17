import datetime as dt
from zoneinfo import ZoneInfo

from sab.scan import _format_ny_now_for_log


def test_format_ny_now_for_log_datetime() -> None:
    ny_now = dt.datetime(2025, 12, 17, 10, 0, tzinfo=ZoneInfo("America/New_York"))
    assert _format_ny_now_for_log({"ny_now": ny_now}) == "2025-12-17T10:00:00-05:00"


def test_format_ny_now_for_log_none() -> None:
    assert _format_ny_now_for_log({"ny_now": None}) == "-"
    assert _format_ny_now_for_log({}) == "-"


def test_format_ny_now_for_log_non_datetime_values() -> None:
    assert (
        _format_ny_now_for_log({"ny_now": "2025-12-17T10:00:00-05:00"})
        == "2025-12-17T10:00:00-05:00"
    )
    assert _format_ny_now_for_log({"ny_now": 123}) == "123"
