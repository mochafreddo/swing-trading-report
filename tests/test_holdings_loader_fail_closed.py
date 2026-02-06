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


def test_load_holdings_raises_when_yaml_dependency_missing(
    tmp_path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = tmp_path / "holdings.yaml"
    path.write_text("holdings: []\n", encoding="utf-8")
    monkeypatch.setattr(holdings_loader, "yaml", None)

    with pytest.raises(HoldingsLoadError, match="PyYAML is unavailable"):
        holdings_loader.load_holdings(str(path))
