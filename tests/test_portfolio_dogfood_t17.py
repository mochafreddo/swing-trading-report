from __future__ import annotations

from pathlib import Path


def test_t17_records_each_package_and_promotion_boundary() -> None:
    evidence = Path("docs/portfolio-dogfood-t17.md").read_text(encoding="utf-8")

    for package in ("T13", "T14", "T15", "T16"):
        assert f"## {package}" in evidence
        assert f"{package}: `IMPLEMENTED_AND_USABLE`" in evidence

    for commit in ("800bccd", "a010c9f", "54fc984", "aba5637"):
        assert commit in evidence

    for field in (
        "Data mode",
        "기대 결과",
        "실제 결과",
        "재현 단계",
        "Sanitized evidence",
        "Regression test",
        "Fix commit",
        "남은 NOT_EVALUATED",
    ):
        assert evidence.count(field) >= 4

    assert "REQUIRES_SEPARATE_APPROVAL" in evidence
    assert "외부 호출: 0건" in evidence
    assert "주문: 0건" in evidence
