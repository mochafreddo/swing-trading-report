from __future__ import annotations

from pathlib import Path


def test_spec_defines_runtime_state_contract() -> None:
    text = Path("docs/spec-v1.1.md").read_text(encoding="utf-8")

    required_snippets = [
        "### 4.4 Postgres: `runtime_state` (필수)",
        "`state_key` TEXT PRIMARY KEY",
        "`state_payload` JSONB NOT NULL",
        "`expires_at` TIMESTAMPTZ NOT NULL",
        "`runtime_state_expires_at_idx`",
        "`runtime_state_login_user_expires_at_idx`",
        "`SAB_RUNTIME_STATE_STORE=memory|supabase`",
        "`POST /rest/v1/rpc/consume_login_throttle_attempt`",
    ]

    missing = [snippet for snippet in required_snippets if snippet not in text]
    assert missing == [], (
        f"docs/spec-v1.1.md에 runtime_state 계약 필수 항목이 누락되었습니다: {missing}"
    )
