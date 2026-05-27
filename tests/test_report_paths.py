from __future__ import annotations

from pathlib import Path

from sab.report.paths import ensure_dir, next_report_path


def test_ensure_dir_creates_nested_directory(tmp_path: Path) -> None:
    target = tmp_path / "nested" / "reports"
    ensure_dir(target.as_posix())
    assert target.is_dir()


def test_ensure_dir_is_idempotent(tmp_path: Path) -> None:
    ensure_dir(tmp_path.as_posix())  # 이미 존재해도 예외가 없어야 한다.
    ensure_dir(tmp_path.as_posix())


def test_next_report_path_uses_date_and_report_type(tmp_path: Path) -> None:
    path = next_report_path(tmp_path.as_posix(), "2026-05-28", "entry")
    assert path == (tmp_path / "2026-05-28.entry.json").as_posix()


def test_next_report_path_avoids_existing_paths(tmp_path: Path) -> None:
    report_dir = tmp_path.as_posix()
    first = next_report_path(report_dir, "2026-05-28", "sell")
    Path(first).touch()
    second = next_report_path(report_dir, "2026-05-28", "sell")
    Path(second).touch()
    third = next_report_path(report_dir, "2026-05-28", "sell")

    assert first == (tmp_path / "2026-05-28.sell.json").as_posix()
    assert second == (tmp_path / "2026-05-28-1.sell.json").as_posix()
    assert third == (tmp_path / "2026-05-28-2.sell.json").as_posix()


def test_next_report_path_supports_hyphenated_report_type(tmp_path: Path) -> None:
    # "ai-brief"처럼 하이픈이 들어간 타입도 접미사에 그대로 반영돼야 한다.
    path = next_report_path(tmp_path.as_posix(), "2026-05-28", "ai-brief")
    assert path == (tmp_path / "2026-05-28.ai-brief.json").as_posix()
