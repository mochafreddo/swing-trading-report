from unittest.mock import MagicMock

from sab.screener.kis_overseas_screener import KISOverseasScreener, ScreenRequest


def test_kis_overseas_screener_uses_fallback_nday_when_empty() -> None:
    client = MagicMock()

    def volume_rank(**kwargs):
        if kwargs.get("nday") == "0":
            return []
        return [{"SYMB": "AAPL"}]

    client.overseas_trade_volume_rank.side_effect = volume_rank
    screener = KISOverseasScreener(client)

    result = screener.screen(ScreenRequest(limit=5, metric="volume", nday=0, fallback_ndays=[1, 2]))

    assert result.tickers == ["AAPL.NAS"]
    assert result.metadata["nday_used"] == 1
    assert result.metadata["nday_tried"] == [0, 1]


def test_kis_overseas_screener_stops_on_first_successful_nday() -> None:
    client = MagicMock()

    def value_rank(**kwargs):
        return [{"SYMB": "MSFT"}]  # returns for preferred nday=1 immediately

    client.overseas_trade_value_rank.side_effect = value_rank
    screener = KISOverseasScreener(client)

    result = screener.screen(ScreenRequest(limit=3, metric="value", nday=1, fallback_ndays=[2, 3]))

    assert result.tickers == ["MSFT.NAS"]
    assert result.metadata["nday_used"] == 1
    assert result.metadata["nday_tried"] == [1]


def test_kis_overseas_screener_all_ndays_empty_returns_empty() -> None:
    client = MagicMock()
    client.overseas_trade_volume_rank.return_value = []
    screener = KISOverseasScreener(client)

    result = screener.screen(ScreenRequest(limit=2, metric="volume", nday=1, fallback_ndays=[2, 3]))

    assert result.tickers == []
    assert result.metadata["nday_used"] is None
    assert result.metadata["nday_tried"] == [1, 2, 3]


def test_kis_overseas_screener_deeper_fallback_succeeds() -> None:
    client = MagicMock()

    def market_cap_rank(**kwargs):
        if kwargs.get("nday") in {"1", "2"}:
            return []
        return [{"SYMB": "NVDA"}]

    client.overseas_market_cap_rank.side_effect = market_cap_rank
    screener = KISOverseasScreener(client)

    result = screener.screen(
        ScreenRequest(limit=1, metric="market_cap", nday=1, fallback_ndays=[2, 3])
    )

    assert result.tickers == ["NVDA.NAS"]
    assert result.metadata["nday_used"] == 3
    assert result.metadata["nday_tried"] == [1, 2, 3]
