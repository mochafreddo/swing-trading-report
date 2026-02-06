import datetime as dt
import logging

from sab.__main__ import _configure_logging

FIXED_CREATED = dt.datetime(2025, 12, 17, 15, 56, 32, 123000, tzinfo=dt.UTC).timestamp()


def _format_root(record: logging.LogRecord) -> str:
    root = logging.getLogger()
    assert len(root.handlers) == 1
    return root.handlers[0].format(record).strip()


def test_configure_logging_default_includes_timestamp_and_logger_name(
    isolated_root_logger, monkeypatch, make_log_record
) -> None:
    monkeypatch.setenv("LOG_LEVEL", "INFO")
    monkeypatch.setenv("LOG_TZ", "utc")
    monkeypatch.delenv("LOG_FORMAT", raising=False)
    monkeypatch.delenv("LOG_DATEFMT", raising=False)

    _configure_logging()
    line = _format_root(make_log_record(created=FIXED_CREATED))

    expected_ts = dt.datetime.fromtimestamp(FIXED_CREATED, tz=dt.UTC).isoformat(
        timespec="milliseconds"
    )
    assert line == f"{expected_ts} INFO sab.test - hello"


def test_configure_logging_respects_datefmt(
    isolated_root_logger, monkeypatch, make_log_record
) -> None:
    monkeypatch.setenv("LOG_LEVEL", "INFO")
    monkeypatch.setenv("LOG_TZ", "utc")
    monkeypatch.setenv("LOG_DATEFMT", "%Y-%m-%dT%H:%M:%S%z")
    monkeypatch.delenv("LOG_FORMAT", raising=False)

    _configure_logging()
    line = _format_root(make_log_record(created=FIXED_CREATED))

    expected_ts = dt.datetime.fromtimestamp(FIXED_CREATED, tz=dt.UTC).strftime(
        "%Y-%m-%dT%H:%M:%S%z"
    )
    assert line == f"{expected_ts} INFO sab.test - hello"


def test_configure_logging_local_tz_offset(
    isolated_root_logger, monkeypatch, make_log_record
) -> None:
    monkeypatch.setenv("LOG_LEVEL", "INFO")
    monkeypatch.setenv("LOG_TZ", "local")
    monkeypatch.delenv("LOG_FORMAT", raising=False)
    monkeypatch.delenv("LOG_DATEFMT", raising=False)

    _configure_logging()
    line = _format_root(make_log_record(created=FIXED_CREATED))

    expected_ts = (
        dt.datetime.fromtimestamp(FIXED_CREATED)
        .astimezone()
        .isoformat(timespec="milliseconds")
    )
    assert line == f"{expected_ts} INFO sab.test - hello"


def test_configure_logging_invalid_tz_defaults_to_local(
    isolated_root_logger, monkeypatch, make_log_record
) -> None:
    monkeypatch.setenv("LOG_LEVEL", "INFO")
    monkeypatch.setenv("LOG_TZ", "bad-value")
    monkeypatch.delenv("LOG_FORMAT", raising=False)
    monkeypatch.delenv("LOG_DATEFMT", raising=False)

    _configure_logging()
    line = _format_root(make_log_record(created=FIXED_CREATED))

    expected_ts = (
        dt.datetime.fromtimestamp(FIXED_CREATED)
        .astimezone()
        .isoformat(timespec="milliseconds")
    )
    assert line == f"{expected_ts} INFO sab.test - hello"


def test_configure_logging_force_replaces_existing_handlers(
    isolated_root_logger, monkeypatch
) -> None:
    existing = logging.NullHandler()
    isolated_root_logger.addHandler(existing)
    assert existing in isolated_root_logger.handlers

    monkeypatch.setenv("LOG_LEVEL", "INFO")
    monkeypatch.setenv("LOG_TZ", "utc")
    monkeypatch.delenv("LOG_FORMAT", raising=False)
    monkeypatch.delenv("LOG_DATEFMT", raising=False)

    _configure_logging()

    assert existing not in isolated_root_logger.handlers
    assert len(isolated_root_logger.handlers) == 1


def test_configure_logging_respects_log_format(
    isolated_root_logger, monkeypatch, make_log_record
) -> None:
    monkeypatch.setenv("LOG_LEVEL", "INFO")
    monkeypatch.setenv("LOG_TZ", "utc")
    monkeypatch.setenv("LOG_FORMAT", "CUSTOM:%(name)s:%(message)s")
    monkeypatch.delenv("LOG_DATEFMT", raising=False)

    _configure_logging()
    line = _format_root(make_log_record(created=FIXED_CREATED))

    assert line == "CUSTOM:sab.test:hello"


def test_configure_logging_respects_log_level(
    isolated_root_logger, monkeypatch, capsys
) -> None:
    monkeypatch.setenv("LOG_LEVEL", "WARNING")
    monkeypatch.setenv("LOG_TZ", "utc")
    monkeypatch.setenv("LOG_FORMAT", "%(levelname)s %(name)s - %(message)s")
    monkeypatch.delenv("LOG_DATEFMT", raising=False)

    _configure_logging()
    capsys.readouterr()

    logger = logging.getLogger("sab.test")
    logger.info("hello")
    captured = capsys.readouterr()
    assert captured.out.strip() == ""
    assert captured.err.strip() == ""

    logger.warning("hello")
    captured = capsys.readouterr()
    line = (captured.err or captured.out).strip()
    assert line == "WARNING sab.test - hello"


def test_configure_logging_invalid_log_level_defaults_to_info(
    isolated_root_logger, monkeypatch, capsys
) -> None:
    monkeypatch.setenv("LOG_LEVEL", "NOPE")
    monkeypatch.setenv("LOG_TZ", "utc")
    monkeypatch.setenv("LOG_FORMAT", "%(levelname)s %(name)s - %(message)s")
    monkeypatch.delenv("LOG_DATEFMT", raising=False)

    _configure_logging()
    assert isolated_root_logger.level == logging.INFO
    capsys.readouterr()

    logging.getLogger("sab.test").info("hello")
    captured = capsys.readouterr()
    line = (captured.err or captured.out).strip()
    assert line == "INFO sab.test - hello"


def test_configure_logging_reconfigure_does_not_accumulate_handlers(
    isolated_root_logger, monkeypatch, make_log_record
) -> None:
    monkeypatch.setenv("LOG_LEVEL", "INFO")
    monkeypatch.setenv("LOG_TZ", "utc")
    monkeypatch.setenv("LOG_FORMAT", "A:%(message)s")
    monkeypatch.delenv("LOG_DATEFMT", raising=False)

    _configure_logging()
    assert len(isolated_root_logger.handlers) == 1
    first_handler = isolated_root_logger.handlers[0]
    assert _format_root(make_log_record(created=FIXED_CREATED)) == "A:hello"

    monkeypatch.setenv("LOG_FORMAT", "B:%(message)s")
    _configure_logging()
    assert len(isolated_root_logger.handlers) == 1
    second_handler = isolated_root_logger.handlers[0]
    assert second_handler is not first_handler
    assert _format_root(make_log_record(created=FIXED_CREATED)) == "B:hello"


def test_configure_logging_log_format_with_asctime_uses_tz(
    isolated_root_logger, monkeypatch, make_log_record
) -> None:
    monkeypatch.setenv("LOG_LEVEL", "INFO")
    monkeypatch.setenv("LOG_TZ", "utc")
    monkeypatch.setenv("LOG_FORMAT", "T=%(asctime)s %(name)s %(message)s")
    monkeypatch.delenv("LOG_DATEFMT", raising=False)

    _configure_logging()
    line = _format_root(make_log_record(created=FIXED_CREATED))

    expected_ts = dt.datetime.fromtimestamp(FIXED_CREATED, tz=dt.UTC).isoformat(
        timespec="milliseconds"
    )
    assert line == f"T={expected_ts} sab.test hello"


def test_configure_logging_log_tz_normalizes_whitespace_and_case(
    isolated_root_logger, monkeypatch, make_log_record
) -> None:
    monkeypatch.setenv("LOG_LEVEL", "INFO")
    monkeypatch.setenv("LOG_TZ", " UTC ")
    monkeypatch.delenv("LOG_FORMAT", raising=False)
    monkeypatch.delenv("LOG_DATEFMT", raising=False)

    _configure_logging()
    line = _format_root(make_log_record(created=FIXED_CREATED))

    expected_ts = dt.datetime.fromtimestamp(FIXED_CREATED, tz=dt.UTC).isoformat(
        timespec="milliseconds"
    )
    assert line == f"{expected_ts} INFO sab.test - hello"


def test_configure_logging_log_tz_defaults_to_local_when_unset(
    isolated_root_logger, monkeypatch, make_log_record
) -> None:
    monkeypatch.setenv("LOG_LEVEL", "INFO")
    monkeypatch.delenv("LOG_TZ", raising=False)
    monkeypatch.delenv("LOG_FORMAT", raising=False)
    monkeypatch.delenv("LOG_DATEFMT", raising=False)

    _configure_logging()
    line = _format_root(make_log_record(created=FIXED_CREATED))

    expected_ts = (
        dt.datetime.fromtimestamp(FIXED_CREATED)
        .astimezone()
        .isoformat(timespec="milliseconds")
    )
    assert line == f"{expected_ts} INFO sab.test - hello"
