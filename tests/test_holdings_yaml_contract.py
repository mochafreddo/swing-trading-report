from __future__ import annotations

from sab.holdings_loader import load_holdings


def test_loader_accepts_export_style_holdings_yaml(tmp_path) -> None:
    path = tmp_path / "holdings.yaml"
    path.write_text(
        (
            "version: 1\n"
            "holdings:\n"
            '  - ticker: "005930"\n'
            "    quantity: 0\n"
            "    entry_price: 70000\n"
            "    entry_currency: KRW\n"
            "  - ticker: TSLA.NAS\n"
            "    quantity: 3\n"
            "    entry_price: 250.5\n"
            "    entry_currency: USD\n"
            "    entry_date: 2026-03-28\n"
            "    strategy: swing\n"
            "    notes: leader\n"
            "    tags:\n"
            "      - us\n"
            "    stop_override: 220\n"
            "    target_override: 300\n"
        ),
        encoding="utf-8",
    )

    loaded = load_holdings(str(path))

    assert [holding.ticker for holding in loaded.holdings] == ["005930", "TSLA.NAS"]
    assert loaded.holdings[0].quantity == 0
    assert loaded.holdings[1].entry_currency == "USD"
    assert loaded.holdings[1].tags == ["us"]
