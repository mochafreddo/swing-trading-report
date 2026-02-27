from __future__ import annotations

import pytest
from sab.config import load_watchlist
from sab.config_loader import ConfigLoadError


def test_load_watchlist_returns_empty_when_path_is_none() -> None:
    assert load_watchlist(None) == []


def test_load_watchlist_returns_empty_when_file_missing(tmp_path) -> None:
    assert load_watchlist(str(tmp_path / "missing-watchlist.txt")) == []


def test_load_watchlist_raises_on_non_numeric_bare_ticker(tmp_path) -> None:
    path = tmp_path / "watchlist.txt"
    path.write_text("AAPL\n", encoding="utf-8")

    with pytest.raises(ConfigLoadError, match="6-digit KR code"):
        load_watchlist(str(path))


def test_load_watchlist_raises_on_short_numeric_kr_ticker(tmp_path) -> None:
    path = tmp_path / "watchlist.txt"
    path.write_text("5930\n", encoding="utf-8")

    with pytest.raises(ConfigLoadError, match="6-digit KR code"):
        load_watchlist(str(path))


def test_load_watchlist_raises_on_unsupported_suffix(tmp_path) -> None:
    path = tmp_path / "watchlist.txt"
    path.write_text("AAPL.XNAS\n", encoding="utf-8")

    with pytest.raises(ConfigLoadError, match="unsupported ticker suffix"):
        load_watchlist(str(path))


def test_load_watchlist_raises_on_ambiguous_us_suffix(tmp_path) -> None:
    path = tmp_path / "watchlist.txt"
    path.write_text("AAPL.US\n", encoding="utf-8")

    with pytest.raises(ConfigLoadError, match="explicit US exchange suffix required"):
        load_watchlist(str(path))


def test_load_watchlist_normalizes_valid_tickers_and_skips_comments(tmp_path) -> None:
    path = tmp_path / "watchlist.txt"
    path.write_text(
        ("# comment\n  tsla.nas-daq  \n005930\nmsft.nas-daq  # inline comment\n\n"),
        encoding="utf-8",
    )

    assert load_watchlist(str(path)) == ["TSLA.NAS", "005930", "MSFT.NAS"]
