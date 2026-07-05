from __future__ import annotations

import pytest
import sab.holdings_loader as holdings_loader
from sab.holdings_loader import HoldingsLoadError, load_holdings


def test_load_holdings_returns_empty_when_path_none() -> None:
    loaded = load_holdings(None)

    assert loaded.path is None
    assert loaded.holdings == []


def test_load_holdings_raises_when_file_missing(tmp_path) -> None:
    missing = tmp_path / "missing-holdings.yaml"

    with pytest.raises(HoldingsLoadError, match="does not exist"):
        load_holdings(str(missing))


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


def test_load_holdings_raises_on_duplicate_top_level_yaml_key(tmp_path) -> None:
    path = tmp_path / "holdings.yaml"
    path.write_text(
        (
            "holdings: []\n"
            "holdings:\n"
            "  - ticker: AAPL.NAS\n"
            "    quantity: 1\n"
            "    entry_price: 100\n"
            "    entry_currency: USD\n"
        ),
        encoding="utf-8",
    )

    with pytest.raises(HoldingsLoadError, match="duplicate YAML key 'holdings'"):
        load_holdings(str(path))


def test_load_holdings_raises_on_duplicate_nested_yaml_key(tmp_path) -> None:
    path = tmp_path / "holdings.yaml"
    path.write_text(
        (
            "holdings:\n"
            "  - ticker: AAPL.NAS\n"
            "    quantity: 1\n"
            "    quantity: 2\n"
            "    entry_price: 100\n"
            "    entry_currency: USD\n"
        ),
        encoding="utf-8",
    )

    with pytest.raises(HoldingsLoadError, match="duplicate YAML key 'quantity'"):
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


def test_load_holdings_raises_when_kr_numeric_ticker_is_unquoted_yaml_int(
    tmp_path,
) -> None:
    path = tmp_path / "holdings.yaml"
    path.write_text(
        ("holdings:\n  - ticker: 000660\n    quantity: 1\n    entry_price: 100\n"),
        encoding="utf-8",
    )

    with pytest.raises(HoldingsLoadError, match="quote numeric codes like '000660'"):
        load_holdings(str(path))


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
            "  - ticker: 005930\n"
            "    quantity: invalid\n"
            "    entry_price: 120.5\n"
        ),
        encoding="utf-8",
    )

    with pytest.raises(HoldingsLoadError) as exc_info:
        load_holdings(str(path))

    message = str(exc_info.value)
    assert "index 0" in message
    assert "ticker='005930'" in message
    assert "field='quantity'" in message


def test_load_holdings_raises_on_invalid_entry_price_with_context(tmp_path) -> None:
    path = tmp_path / "holdings.yaml"
    path.write_text(
        (
            "holdings:\n"
            "  - ticker: 005930\n"
            "    quantity: 1\n"
            "    entry_price: 300\n"
            "  - ticker: '000660'\n"
            "    quantity: 2\n"
            "    entry_price: invalid\n"
        ),
        encoding="utf-8",
    )

    with pytest.raises(HoldingsLoadError) as exc_info:
        load_holdings(str(path))

    message = str(exc_info.value)
    assert "index 1" in message
    assert "ticker='000660'" in message
    assert "field='entry_price'" in message


@pytest.mark.parametrize(
    ("yaml_body", "field_name"),
    [
        (
            ("holdings:\n  - ticker: 005930\n    entry_price: 120.5\n"),
            "quantity",
        ),
        (
            ("holdings:\n  - ticker: 005930\n    quantity: 10\n"),
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
    assert "ticker='005930'" in message
    assert f"field='{field_name}'" in message


@pytest.mark.parametrize(
    ("yaml_body", "field_name"),
    [
        (
            (
                "holdings:\n  - ticker: 005930\n    quantity: -1\n    entry_price: 120.5\n"
            ),
            "quantity",
        ),
        (
            (
                "holdings:\n  - ticker: 005930\n    quantity: 1\n    entry_price: -120.5\n"
            ),
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
    assert "ticker='005930'" in message
    assert f"field='{field_name}'" in message


def test_load_holdings_raises_on_zero_entry_price_for_active_holding(
    tmp_path,
) -> None:
    path = tmp_path / "holdings.yaml"
    path.write_text(
        ("holdings:\n  - ticker: 005930\n    quantity: 1\n    entry_price: 0\n"),
        encoding="utf-8",
    )

    with pytest.raises(HoldingsLoadError) as exc_info:
        load_holdings(str(path))

    message = str(exc_info.value)
    assert "active holdings" in message
    assert "quantity > 0" in message
    assert "index 0" in message
    assert "ticker='005930'" in message
    assert "field='entry_price'" in message


def test_load_holdings_allows_zero_entry_price_for_inactive_holding(tmp_path) -> None:
    path = tmp_path / "holdings.yaml"
    path.write_text(
        ("holdings:\n  - ticker: 005930\n    quantity: 0\n    entry_price: 0\n"),
        encoding="utf-8",
    )

    loaded = load_holdings(str(path))

    assert len(loaded.holdings) == 1
    assert loaded.holdings[0].quantity == 0
    assert loaded.holdings[0].entry_price == 0


@pytest.mark.parametrize(
    ("yaml_body", "field_name"),
    [
        (
            (
                "holdings:\n"
                "  - ticker: 005930\n"
                "    quantity: true\n"
                "    entry_price: 120.5\n"
            ),
            "quantity",
        ),
        (
            ("holdings:\n  - ticker: 005930\n    quantity: 1\n    entry_price: .inf\n"),
            "entry_price",
        ),
        (
            ("holdings:\n  - ticker: 005930\n    quantity: 1\n    entry_price: .nan\n"),
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
    assert "ticker='005930'" in message
    assert f"field='{field_name}'" in message


@pytest.mark.parametrize(
    ("yaml_body", "field_name"),
    [
        (
            (
                "holdings:\n"
                "  - ticker: 005930\n"
                "    quantity: 1\n"
                "    entry_price: 100\n"
                "    stop_override: true\n"
            ),
            "stop_override",
        ),
        (
            (
                "holdings:\n"
                "  - ticker: 005930\n"
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
    assert "ticker='005930'" in message
    assert f"field='{field_name}'" in message


@pytest.mark.parametrize(
    ("yaml_body", "field_name"),
    [
        (
            (
                "holdings:\n"
                "  - ticker: 005930\n"
                "    quantity: 1\n"
                "    entry_price: 100\n"
                "    stop_override: -1\n"
            ),
            "stop_override",
        ),
        (
            (
                "holdings:\n"
                "  - ticker: 005930\n"
                "    quantity: 1\n"
                "    entry_price: 100\n"
                "    target_override: -0.01\n"
            ),
            "target_override",
        ),
    ],
)
def test_load_holdings_raises_on_negative_optional_numeric_overrides(
    tmp_path, yaml_body: str, field_name: str
) -> None:
    path = tmp_path / "holdings.yaml"
    path.write_text(yaml_body, encoding="utf-8")

    with pytest.raises(HoldingsLoadError) as exc_info:
        load_holdings(str(path))

    message = str(exc_info.value)
    assert "expected a number >= 0" in message
    assert "index 0" in message
    assert "ticker='005930'" in message
    assert f"field='{field_name}'" in message


def test_load_holdings_accepts_zero_optional_numeric_overrides(tmp_path) -> None:
    path = tmp_path / "holdings.yaml"
    path.write_text(
        (
            "holdings:\n"
            "  - ticker: 005930\n"
            "    quantity: 1\n"
            "    entry_price: 100\n"
            "    stop_override: 0\n"
            "    target_override: 0\n"
        ),
        encoding="utf-8",
    )

    loaded = load_holdings(str(path))

    assert len(loaded.holdings) == 1
    assert loaded.holdings[0].stop_override == 0
    assert loaded.holdings[0].target_override == 0


def test_load_holdings_raises_when_us_ticker_missing_entry_currency(tmp_path) -> None:
    path = tmp_path / "holdings.yaml"
    path.write_text(
        (
            "settings:\n"
            "  default_currency: KRW\n"
            "holdings:\n"
            "  - ticker: TSLA.NAS\n"
            "    quantity: 1\n"
            "    entry_price: 200\n"
        ),
        encoding="utf-8",
    )

    with pytest.raises(HoldingsLoadError, match="US-only holdings"):
        load_holdings(str(path))


def test_load_holdings_raises_when_us_ticker_entry_currency_not_usd(tmp_path) -> None:
    path = tmp_path / "holdings.yaml"
    path.write_text(
        (
            "holdings:\n"
            "  - ticker: TSLA.NAS\n"
            "    quantity: 1\n"
            "    entry_price: 200\n"
            "    entry_currency: KRW\n"
        ),
        encoding="utf-8",
    )

    with pytest.raises(HoldingsLoadError, match="US ticker entry_currency must be USD"):
        load_holdings(str(path))


def test_load_holdings_raises_when_usd_entry_currency_missing_us_suffix(
    tmp_path,
) -> None:
    path = tmp_path / "holdings.yaml"
    path.write_text(
        (
            "holdings:\n"
            "  - ticker: 005930\n"
            "    quantity: 1\n"
            "    entry_price: 200\n"
            "    entry_currency: USD\n"
        ),
        encoding="utf-8",
    )

    with pytest.raises(
        HoldingsLoadError, match="entry_currency USD requires US ticker suffix"
    ):
        load_holdings(str(path))


def test_load_holdings_raises_when_ticker_without_suffix_is_not_numeric(
    tmp_path,
) -> None:
    path = tmp_path / "holdings.yaml"
    path.write_text(
        (
            "holdings:\n"
            "  - ticker: AAPL\n"
            "    quantity: 1\n"
            "    entry_price: 200\n"
            "    entry_currency: KRW\n"
        ),
        encoding="utf-8",
    )

    with pytest.raises(HoldingsLoadError, match="must be a 6-digit KR code"):
        load_holdings(str(path))


def test_load_holdings_raises_when_kr_ticker_is_not_6_digits(tmp_path) -> None:
    path = tmp_path / "holdings.yaml"
    path.write_text(
        (
            "holdings:\n"
            "  - ticker: '5930'\n"
            "    quantity: 1\n"
            "    entry_price: 200\n"
            "    entry_currency: KRW\n"
        ),
        encoding="utf-8",
    )

    with pytest.raises(HoldingsLoadError, match="must be a 6-digit KR code"):
        load_holdings(str(path))


def test_load_holdings_raises_when_ticker_uses_ambiguous_us_suffix(tmp_path) -> None:
    path = tmp_path / "holdings.yaml"
    path.write_text(
        (
            "holdings:\n"
            "  - ticker: TSLA.US\n"
            "    quantity: 1\n"
            "    entry_price: 200\n"
            "    entry_currency: USD\n"
        ),
        encoding="utf-8",
    )

    with pytest.raises(HoldingsLoadError, match="explicit US exchange suffix required"):
        load_holdings(str(path))


def test_load_holdings_raises_when_ticker_suffix_is_unsupported(tmp_path) -> None:
    path = tmp_path / "holdings.yaml"
    path.write_text(
        (
            "holdings:\n"
            "  - ticker: AAPL.XNAS\n"
            "    quantity: 1\n"
            "    entry_price: 200\n"
            "    entry_currency: USD\n"
        ),
        encoding="utf-8",
    )

    with pytest.raises(HoldingsLoadError, match="unsupported ticker suffix"):
        load_holdings(str(path))


def test_load_holdings_raises_when_entry_currency_is_not_supported_code(
    tmp_path,
) -> None:
    path = tmp_path / "holdings.yaml"
    path.write_text(
        (
            "holdings:\n"
            "  - ticker: 005930\n"
            "    quantity: 1\n"
            "    entry_price: 70000\n"
            "    entry_currency: EUR\n"
        ),
        encoding="utf-8",
    )

    with pytest.raises(HoldingsLoadError, match="unsupported entry_currency"):
        load_holdings(str(path))


def test_load_holdings_raises_when_default_currency_is_not_supported_code(
    tmp_path,
) -> None:
    path = tmp_path / "holdings.yaml"
    path.write_text(
        (
            "settings:\n"
            "  default_currency: EUR\n"
            "holdings:\n"
            "  - ticker: 005930\n"
            "    quantity: 1\n"
            "    entry_price: 70000\n"
        ),
        encoding="utf-8",
    )

    with pytest.raises(
        HoldingsLoadError, match=r"unsupported settings\.default_currency"
    ):
        load_holdings(str(path))


def test_load_holdings_us_only_allows_default_usd_without_row_entry_currency(
    tmp_path,
) -> None:
    path = tmp_path / "holdings.yaml"
    path.write_text(
        (
            "settings:\n"
            "  default_currency: USD\n"
            "holdings:\n"
            "  - ticker: TSLA.NAS\n"
            "    quantity: 1\n"
            "    entry_price: 200\n"
        ),
        encoding="utf-8",
    )

    loaded = load_holdings(str(path))

    assert len(loaded.holdings) == 1
    assert loaded.holdings[0].ticker == "TSLA.NAS"
    assert loaded.holdings[0].entry_currency == "USD"


def test_load_holdings_raises_when_mixed_markets_with_default_currency(
    tmp_path,
) -> None:
    path = tmp_path / "holdings.yaml"
    path.write_text(
        (
            "settings:\n"
            "  default_currency: KRW\n"
            "holdings:\n"
            "  - ticker: 005930\n"
            "    quantity: 1\n"
            "    entry_price: 70000\n"
            "  - ticker: TSLA.NAS\n"
            "    quantity: 1\n"
            "    entry_price: 200\n"
        ),
        encoding="utf-8",
    )

    with pytest.raises(
        HoldingsLoadError,
        match=r"Mixed KR/US holdings cannot use settings\.default_currency",
    ):
        load_holdings(str(path))


def test_load_holdings_raises_when_mixed_markets_row_missing_entry_currency(
    tmp_path,
) -> None:
    path = tmp_path / "holdings.yaml"
    path.write_text(
        (
            "holdings:\n"
            "  - ticker: 005930\n"
            "    quantity: 1\n"
            "    entry_price: 70000\n"
            "    entry_currency: KRW\n"
            "  - ticker: TSLA.NAS\n"
            "    quantity: 1\n"
            "    entry_price: 200\n"
        ),
        encoding="utf-8",
    )

    with pytest.raises(
        HoldingsLoadError,
        match="Mixed KR/US holdings require explicit entry_currency per row",
    ):
        load_holdings(str(path))


def test_load_holdings_raises_when_kr_only_default_currency_is_usd(tmp_path) -> None:
    path = tmp_path / "holdings.yaml"
    path.write_text(
        (
            "settings:\n"
            "  default_currency: USD\n"
            "holdings:\n"
            "  - ticker: 005930\n"
            "    quantity: 1\n"
            "    entry_price: 70000\n"
        ),
        encoding="utf-8",
    )

    with pytest.raises(
        HoldingsLoadError,
        match=r"KR-only holdings cannot set settings\.default_currency=USD",
    ):
        load_holdings(str(path))
