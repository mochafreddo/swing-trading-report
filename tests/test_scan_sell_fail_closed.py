from __future__ import annotations

from unittest.mock import patch

import pytest
from sab.config_loader import ConfigLoadError
from sab.holdings_loader import HoldingsLoadError
from sab.scan import run_scan
from sab.sell import run_sell


@pytest.mark.parametrize(
    "err",
    [ConfigLoadError("bad config"), HoldingsLoadError("bad holdings")],
)
def test_run_scan_returns_1_when_config_loading_fails(err: Exception) -> None:
    with patch("sab.scan.load_config", side_effect=err):
        code = run_scan(
            limit=None,
            watchlist_path=None,
            provider=None,
            screener_limit=None,
            universe=None,
        )

    assert code == 1


@pytest.mark.parametrize(
    "err",
    [ConfigLoadError("bad config"), HoldingsLoadError("bad holdings")],
)
def test_run_sell_returns_1_when_config_loading_fails(err: Exception) -> None:
    with patch("sab.sell.load_config", side_effect=err):
        code = run_sell(provider=None)

    assert code == 1
