from __future__ import annotations

from pathlib import Path

import pytest
from sab.holdings_loader import HoldingsLoadError, load_holdings


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
            "    entry_pattern: swing_high_breakout\n"
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
    assert loaded.holdings[1].entry_pattern == "swing_high_breakout"
    assert loaded.holdings[1].tags == ["us"]


@pytest.mark.parametrize(
    ("entry_pattern_yaml", "expected"),
    [
        ("", None),
        ("    entry_pattern: null\n", None),
        ('    entry_pattern: ""\n', None),
        ('    entry_pattern: "   "\n', None),
    ],
)
def test_loader_accepts_nullable_entry_pattern_values(
    tmp_path: Path, entry_pattern_yaml: str, expected: str | None
) -> None:
    path = tmp_path / "holdings.yaml"
    path.write_text(
        "holdings:\n"
        "  - ticker: AAPL.NAS\n"
        "    quantity: 1\n"
        "    entry_price: 100\n"
        "    entry_currency: USD\n"
        f"{entry_pattern_yaml}",
        encoding="utf-8",
    )

    loaded = load_holdings(path.as_posix())

    assert loaded.holdings[0].entry_pattern == expected


@pytest.mark.parametrize(
    "entry_pattern_yaml",
    [
        "    entry_pattern:\n      - swing_high_breakout\n",
        "    entry_pattern:\n      value: swing_high_breakout\n",
        "    entry_pattern: true\n",
        "    entry_pattern: 123\n",
    ],
)
def test_loader_rejects_non_string_entry_pattern(
    tmp_path: Path, entry_pattern_yaml: str
) -> None:
    path = tmp_path / "holdings.yaml"
    path.write_text(
        "holdings:\n"
        "  - ticker: AAPL.NAS\n"
        "    quantity: 1\n"
        "    entry_price: 100\n"
        "    entry_currency: USD\n"
        f"{entry_pattern_yaml}",
        encoding="utf-8",
    )

    with pytest.raises(HoldingsLoadError) as excinfo:
        load_holdings(path.as_posix())

    message = str(excinfo.value)
    assert "field='entry_pattern'" in message
    assert "expected a string" in message


def test_loader_rejects_overlong_entry_pattern(tmp_path: Path) -> None:
    path = tmp_path / "holdings.yaml"
    path.write_text(
        "holdings:\n"
        "  - ticker: AAPL.NAS\n"
        "    quantity: 1\n"
        "    entry_price: 100\n"
        "    entry_currency: USD\n"
        f"    entry_pattern: {'x' * 121}\n",
        encoding="utf-8",
    )

    with pytest.raises(HoldingsLoadError) as excinfo:
        load_holdings(path.as_posix())

    message = str(excinfo.value)
    assert "field='entry_pattern'" in message
    assert "<= 120" in message


def test_loader_rejects_unknown_entry_pattern(tmp_path: Path) -> None:
    path = tmp_path / "holdings.yaml"
    path.write_text(
        "holdings:\n"
        "  - ticker: AAPL.NAS\n"
        "    quantity: 1\n"
        "    entry_price: 100\n"
        "    entry_currency: USD\n"
        "    entry_pattern: not_a_breakout\n",
        encoding="utf-8",
    )

    with pytest.raises(HoldingsLoadError) as excinfo:
        load_holdings(path.as_posix())

    message = str(excinfo.value)
    assert "field='entry_pattern'" in message
    assert "expected one of" in message


def test_loader_rejects_inactive_holding_entry_pattern(tmp_path: Path) -> None:
    path = tmp_path / "holdings.yaml"
    path.write_text(
        "holdings:\n"
        "  - ticker: AAPL.NAS\n"
        "    quantity: 0\n"
        "    entry_price: 100\n"
        "    entry_currency: USD\n"
        "    entry_pattern: swing_high_breakout\n",
        encoding="utf-8",
    )

    with pytest.raises(HoldingsLoadError) as excinfo:
        load_holdings(path.as_posix())

    message = str(excinfo.value)
    assert "field='entry_pattern'" in message
    assert "inactive holdings entry_pattern must be null" in message


@pytest.mark.parametrize(
    "entry_pattern_yaml",
    [
        "",
        "    entry_pattern: null\n",
        '    entry_pattern: ""\n',
        '    entry_pattern: "   "\n',
    ],
)
def test_loader_accepts_empty_inactive_holding_entry_pattern(
    tmp_path: Path, entry_pattern_yaml: str
) -> None:
    path = tmp_path / "holdings.yaml"
    path.write_text(
        "holdings:\n"
        "  - ticker: AAPL.NAS\n"
        "    quantity: 0\n"
        "    entry_price: 0\n"
        "    entry_currency: USD\n"
        f"{entry_pattern_yaml}",
        encoding="utf-8",
    )

    loaded = load_holdings(path.as_posix())

    assert loaded.holdings[0].entry_pattern is None


def test_current_hybrid_buy_patterns_are_covered_by_holdings_storage_contract() -> None:
    from sab.entry_pattern_contract import HOLDINGS_ENTRY_PATTERN_VALUES
    from sab.signals.hybrid_buy import HybridPattern

    assert {pattern.value for pattern in HybridPattern}.issubset(
        set(HOLDINGS_ENTRY_PATTERN_VALUES)
    )
