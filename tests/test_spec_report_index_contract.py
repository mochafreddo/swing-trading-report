from __future__ import annotations

from pathlib import Path


def test_spec_defines_report_index_contract() -> None:
    text = Path("docs/spec-v1.1.md").read_text(encoding="utf-8")

    required_snippets = [
        "### 4.3 Postgres: `report_index` (필수)",
        "`report_key` TEXT PRIMARY KEY",
        "`report_type` TEXT NOT NULL (`buy`, `sell`만 허용)",
        "`duplicate_index` INTEGER NOT NULL DEFAULT 0 (`>= 0`)",
        "`report_index_type_date_duplicate_key_idx`",
        "`report_index_date_duplicate_key_idx`",
        "`POST /rest/v1/report_index?on_conflict=report_key`",
        "`report_date.desc,duplicate_index.desc,report_key.desc`",
        "ticker 검색(`q`)은 `tickers_hydrated=true` 행만 대상으로 한다.",
    ]

    missing = [snippet for snippet in required_snippets if snippet not in text]
    assert missing == [], (
        f"docs/spec-v1.1.md에 report_index 계약 필수 항목이 누락되었습니다: {missing}"
    )
