from __future__ import annotations

import os


def ensure_dir(path: str) -> None:
    os.makedirs(path, exist_ok=True)


def next_report_path(report_dir: str, date: str, report_type: str) -> str:
    """``report_dir`` 안에서 충돌하지 않는 리포트 파일 경로를 반환한다.

    기본 경로는 ``{date}.{report_type}.json``이며, 이미 존재하면 ``{date}-1``,
    ``{date}-2`` … 처럼 정수 접미사를 붙여 가장 먼저 비어 있는 경로를 고른다.
    """

    suffix = f".{report_type}.json"
    base = os.path.join(report_dir, f"{date}{suffix}")
    if not os.path.exists(base):
        return base
    i = 1
    while True:
        path = os.path.join(report_dir, f"{date}-{i}{suffix}")
        if not os.path.exists(path):
            return path
        i += 1


__all__ = ["ensure_dir", "next_report_path"]
