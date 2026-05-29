from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml  # type: ignore[import-untyped]
from sab.scheduler.holdings import (
    SupabaseHoldingsExportConfig,
    export_active_holdings_snapshot,
)


class _FakeResponse:
    def __init__(self, status_code: int, payload: object, text: str = "") -> None:
        self.status_code = status_code
        self._payload = payload
        self.text = text

    def json(self) -> object:
        return self._payload


class _FakeSession:
    def __init__(self, response: _FakeResponse) -> None:
        self._response = response
        self.get_calls: list[dict[str, Any]] = []

    def get(
        self, url: str, *, headers: dict[str, str], timeout: float
    ) -> _FakeResponse:
        self.get_calls.append({"url": url, "headers": headers, "timeout": timeout})
        return self._response


def test_export_active_holdings_snapshot_writes_entry_holdings_yaml(
    tmp_path: Path,
) -> None:
    session = _FakeSession(
        _FakeResponse(
            200,
            [
                {
                    "ticker": "AAPL.NAS",
                    "quantity": 2,
                    "entry_price": 100,
                    "entry_currency": "USD",
                    "entry_date": "2026-05-01",
                    "strategy": "sma_ema_hybrid",
                    "notes": None,
                    "tags": ["core"],
                    "stop_override": None,
                    "target_override": 130,
                },
                {
                    "ticker": "000660",
                    "quantity": 0,
                    "entry_price": 150000,
                },
            ],
        )
    )
    output = tmp_path / "holdings.generated.yaml"

    count = export_active_holdings_snapshot(
        output_path=output,
        config=SupabaseHoldingsExportConfig(
            url="https://example.supabase.co",
            service_role_key="sb_secret",
            timeout_seconds=3,
        ),
        session=session,
    )

    assert count == 1
    assert "quantity=gt.0" in str(session.get_calls[0]["url"])
    assert "select=ticker%2Cquantity%2Centry_price" in str(session.get_calls[0]["url"])
    payload = yaml.safe_load(output.read_text(encoding="utf-8"))
    assert payload == {
        "holdings": [
            {
                "ticker": "AAPL.NAS",
                "quantity": 2,
                "entry_price": 100,
                "entry_currency": "USD",
                "entry_date": "2026-05-01",
                "strategy": "sma_ema_hybrid",
                "tags": ["core"],
                "target_override": 130,
            }
        ]
    }
