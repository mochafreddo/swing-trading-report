from __future__ import annotations

import pytest
import sab.holdings_loader as holdings_loader
from sab.holdings_loader import HoldingsLoadError, load_holdings


def test_load_holdings_returns_empty_when_path_none() -> None:
    loaded = load_holdings(None)

    assert loaded.path is None
    assert loaded.holdings == []


def test_load_holdings_returns_empty_when_file_missing(tmp_path) -> None:
    missing = tmp_path / "missing-holdings.yaml"

    loaded = load_holdings(str(missing))

    assert loaded.path == missing
    assert loaded.holdings == []


def test_load_holdings_raises_on_invalid_yaml(tmp_path) -> None:
    path = tmp_path / "holdings.yaml"
    path.write_text("holdings: [\n", encoding="utf-8")

    with pytest.raises(HoldingsLoadError, match="Failed to parse holdings file"):
        load_holdings(str(path))


def test_load_holdings_raises_on_non_mapping_root(tmp_path) -> None:
    path = tmp_path / "holdings.yaml"
    path.write_text("- ticker: AAPL\n", encoding="utf-8")

    with pytest.raises(HoldingsLoadError, match="must have a mapping"):
        load_holdings(str(path))


def test_load_holdings_raises_on_non_mapping_settings(tmp_path) -> None:
    path = tmp_path / "holdings.yaml"
    path.write_text("settings:\n  - invalid\nholdings: []\n", encoding="utf-8")

    with pytest.raises(HoldingsLoadError, match="field 'settings' must have a mapping"):
        load_holdings(str(path))


def test_load_holdings_raises_on_non_list_holdings(tmp_path) -> None:
    path = tmp_path / "holdings.yaml"
    path.write_text("settings: {}\nholdings: {}\n", encoding="utf-8")

    with pytest.raises(HoldingsLoadError, match="field 'holdings' must have a list"):
        load_holdings(str(path))


def test_load_holdings_raises_on_non_mapping_holding_item(tmp_path) -> None:
    path = tmp_path / "holdings.yaml"
    path.write_text("holdings:\n  - invalid\n", encoding="utf-8")

    with pytest.raises(HoldingsLoadError, match="index 0"):
        load_holdings(str(path))


def test_load_holdings_raises_on_missing_ticker(tmp_path) -> None:
    path = tmp_path / "holdings.yaml"
    path.write_text(
        "holdings:\n  - quantity: 1\n    entry_price: 100\n",
        encoding="utf-8",
    )

    with pytest.raises(HoldingsLoadError, match="field='ticker'"):
        load_holdings(str(path))


@pytest.mark.parametrize(
    "ticker_value",
    ["null", "true", "{value: AAPL}", "[AAPL]"],
)
def test_load_holdings_raises_on_invalid_ticker_types(
    tmp_path, ticker_value: str
) -> None:
    path = tmp_path / "holdings.yaml"
    path.write_text(
        (
            "holdings:\n"
            f"  - ticker: {ticker_value}\n"
            "    quantity: 1\n"
            "    entry_price: 100\n"
        ),
        encoding="utf-8",
    )

    with pytest.raises(HoldingsLoadError) as exc_info:
        load_holdings(str(path))

    message = str(exc_info.value)
    assert "field='ticker'" in message
    assert "index 0" in message


def test_load_holdings_raises_when_yaml_dependency_missing(
    tmp_path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = tmp_path / "holdings.yaml"
    path.write_text("holdings: []\n", encoding="utf-8")
    monkeypatch.setattr(holdings_loader, "yaml", None)

    with pytest.raises(HoldingsLoadError, match="PyYAML is unavailable"):
        holdings_loader.load_holdings(str(path))


def test_load_holdings_raises_on_invalid_quantity_with_context(tmp_path) -> None:
    path = tmp_path / "holdings.yaml"
    path.write_text(
        (
            "holdings:\n"
            "  - ticker: AAPL\n"
            "    quantity: invalid\n"
            "    entry_price: 120.5\n"
        ),
        encoding="utf-8",
    )

    with pytest.raises(HoldingsLoadError) as exc_info:
        load_holdings(str(path))

    message = str(exc_info.value)
    assert "index 0" in message
    assert "ticker='AAPL'" in message
    assert "field='quantity'" in message


def test_load_holdings_raises_on_invalid_entry_price_with_context(tmp_path) -> None:
    path = tmp_path / "holdings.yaml"
    path.write_text(
        (
            "holdings:\n"
            "  - ticker: MSFT\n"
            "    quantity: 1\n"
            "    entry_price: 300\n"
            "  - ticker: NVDA\n"
            "    quantity: 2\n"
            "    entry_price: invalid\n"
        ),
        encoding="utf-8",
    )

    with pytest.raises(HoldingsLoadError) as exc_info:
        load_holdings(str(path))

    message = str(exc_info.value)
    assert "index 1" in message
    assert "ticker='NVDA'" in message
    assert "field='entry_price'" in message


@pytest.mark.parametrize(
    ("yaml_body", "field_name"),
    [
        (
            ("holdings:\n  - ticker: AAPL\n    entry_price: 120.5\n"),
            "quantity",
        ),
        (
            ("holdings:\n  - ticker: AAPL\n    quantity: 10\n"),
            "entry_price",
        ),
    ],
)
def test_load_holdings_raises_on_missing_required_numeric_fields(
    tmp_path, yaml_body: str, field_name: str
) -> None:
    path = tmp_path / "holdings.yaml"
    path.write_text(yaml_body, encoding="utf-8")

    with pytest.raises(HoldingsLoadError) as exc_info:
        load_holdings(str(path))

    message = str(exc_info.value)
    assert "Missing required holdings field" in message
    assert "index 0" in message
    assert "ticker='AAPL'" in message
    assert f"field='{field_name}'" in message


@pytest.mark.parametrize(
    ("yaml_body", "field_name"),
    [
        (
            ("holdings:\n  - ticker: AAPL\n    quantity: -1\n    entry_price: 120.5\n"),
            "quantity",
        ),
        (
            ("holdings:\n  - ticker: AAPL\n    quantity: 1\n    entry_price: -120.5\n"),
            "entry_price",
        ),
    ],
)
def test_load_holdings_raises_on_negative_required_numeric_fields(
    tmp_path, yaml_body: str, field_name: str
) -> None:
    path = tmp_path / "holdings.yaml"
    path.write_text(yaml_body, encoding="utf-8")

    with pytest.raises(HoldingsLoadError) as exc_info:
        load_holdings(str(path))

    message = str(exc_info.value)
    assert "expected a number >= 0" in message
    assert "index 0" in message
    assert "ticker='AAPL'" in message
    assert f"field='{field_name}'" in message


@pytest.mark.parametrize(
    ("yaml_body", "field_name"),
    [
        (
            (
                "holdings:\n"
                "  - ticker: AAPL\n"
                "    quantity: true\n"
                "    entry_price: 120.5\n"
            ),
            "quantity",
        ),
        (
            ("holdings:\n  - ticker: AAPL\n    quantity: 1\n    entry_price: .inf\n"),
            "entry_price",
        ),
        (
            ("holdings:\n  - ticker: AAPL\n    quantity: 1\n    entry_price: .nan\n"),
            "entry_price",
        ),
    ],
)
def test_load_holdings_raises_on_non_finite_or_boolean_numeric_fields(
    tmp_path, yaml_body: str, field_name: str
) -> None:
    path = tmp_path / "holdings.yaml"
    path.write_text(yaml_body, encoding="utf-8")

    with pytest.raises(HoldingsLoadError) as exc_info:
        load_holdings(str(path))

    message = str(exc_info.value)
    assert "expected a finite number" in message
    assert "index 0" in message
    assert "ticker='AAPL'" in message
    assert f"field='{field_name}'" in message


@pytest.mark.parametrize(
    ("yaml_body", "field_name"),
    [
        (
            (
                "holdings:\n"
                "  - ticker: AAPL\n"
                "    quantity: 1\n"
                "    entry_price: 100\n"
                "    stop_override: true\n"
            ),
            "stop_override",
        ),
        (
            (
                "holdings:\n"
                "  - ticker: AAPL\n"
                "    quantity: 1\n"
                "    entry_price: 100\n"
                "    target_override: .nan\n"
            ),
            "target_override",
        ),
    ],
)
def test_load_holdings_raises_on_invalid_optional_numeric_overrides(
    tmp_path, yaml_body: str, field_name: str
) -> None:
    path = tmp_path / "holdings.yaml"
    path.write_text(yaml_body, encoding="utf-8")

    with pytest.raises(HoldingsLoadError) as exc_info:
        load_holdings(str(path))

    message = str(exc_info.value)
    assert "expected a finite number" in message
    assert "index 0" in message
    assert "ticker='AAPL'" in message
    assert f"field='{field_name}'" in message
