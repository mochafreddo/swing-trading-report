from unittest.mock import MagicMock

import pytest
from sab.screener.kis_overseas_screener import KISOverseasScreener, ScreenRequest


def test_kis_overseas_screener_uses_fallback_nday_when_empty() -> None:
    client = MagicMock()

    def volume_rank(**kwargs):
        if kwargs.get("exchange") != "NAS":
            return []
        if kwargs.get("nday") == "0":
            return []
        return [{"SYMB": "AAPL"}]

    client.overseas_trade_volume_rank.side_effect = volume_rank
    screener = KISOverseasScreener(client)

    result = screener.screen(
        ScreenRequest(limit=5, metric="volume", nday=0, fallback_ndays=[1, 2])
    )

    assert result.tickers == ["AAPL.NAS"]
    assert result.metadata["nday_used"] == 1
    assert result.metadata["nday_tried"] == [0, 1]


def test_kis_overseas_screener_stops_on_first_successful_nday() -> None:
    client = MagicMock()

    def value_rank(**kwargs):
        if kwargs.get("exchange") != "NAS":
            return []
        return [{"SYMB": "MSFT"}]  # returns for preferred nday=1 immediately

    client.overseas_trade_value_rank.side_effect = value_rank
    screener = KISOverseasScreener(client)

    result = screener.screen(
        ScreenRequest(limit=3, metric="value", nday=1, fallback_ndays=[2, 3])
    )

    assert result.tickers == ["MSFT.NAS"]
    assert result.metadata["nday_used"] == 1
    assert result.metadata["nday_tried"] == [1]


def test_kis_overseas_screener_all_ndays_empty_returns_empty() -> None:
    client = MagicMock()
    client.overseas_trade_volume_rank.return_value = []
    screener = KISOverseasScreener(client)

    result = screener.screen(
        ScreenRequest(limit=2, metric="volume", nday=1, fallback_ndays=[2, 3])
    )

    assert result.tickers == []
    assert result.metadata["nday_used"] is None
    assert result.metadata["nday_tried"] == [1, 2, 3]


def test_kis_overseas_screener_deeper_fallback_succeeds() -> None:
    client = MagicMock()

    def market_cap_rank(**kwargs):
        if kwargs.get("exchange") != "NAS":
            return []
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


def test_kis_overseas_screener_fills_across_exchanges_until_limit() -> None:
    client = MagicMock()

    def value_rank(**kwargs):
        exchange = kwargs.get("exchange")
        if exchange == "NAS":
            return [
                {"SYMB": f"NAS{i:03d}", "ACC_TRDVAL": str(10_000 - i)}
                for i in range(1, 101)
            ]
        if exchange == "NYS":
            return [
                {"SYMB": f"NYS{i:03d}", "ACC_TRDVAL": str(9_000 - i)}
                for i in range(1, 111)
            ]
        return []

    client.overseas_trade_value_rank.side_effect = value_rank
    screener = KISOverseasScreener(client)

    result = screener.screen(ScreenRequest(limit=110, metric="value", nday=1))

    assert len(result.tickers) == 110
    assert result.tickers[:3] == ["NAS001.NAS", "NAS002.NAS", "NAS003.NAS"]
    assert result.tickers[99] == "NAS100.NAS"
    assert result.tickers[100] == "NYS001.NYS"
    assert result.tickers[-1] == "NYS010.NYS"
    assert result.metadata["selection_mode"] == "global_metric_merge"

    assert client.overseas_trade_value_rank.call_count == 3
    first_call = client.overseas_trade_value_rank.call_args_list[0].kwargs
    second_call = client.overseas_trade_value_rank.call_args_list[1].kwargs
    third_call = client.overseas_trade_value_rank.call_args_list[2].kwargs
    assert first_call["exchange"] == "NAS"
    assert first_call["limit"] == 110
    assert first_call["nday"] == "1"
    assert second_call["exchange"] == "NYS"
    assert second_call["limit"] == 110
    assert second_call["nday"] == "1"
    assert third_call["exchange"] == "AMS"
    assert third_call["limit"] == 110
    assert third_call["nday"] == "1"


def test_kis_overseas_screener_non_positive_limit_skips_api_calls() -> None:
    client = MagicMock()
    screener = KISOverseasScreener(client)

    result = screener.screen(ScreenRequest(limit=0, metric="value", nday=1))

    assert result.tickers == []
    assert result.metadata["selection_mode"] == "global_metric_merge"
    assert client.overseas_trade_value_rank.call_count == 0


def test_kis_overseas_screener_merges_by_global_metric_value() -> None:
    client = MagicMock()

    def value_rank(**kwargs):
        exchange = kwargs.get("exchange")
        if exchange == "NAS":
            return [
                {"SYMB": "NAS001", "ACC_TRDVAL": "90"},
                {"SYMB": "NAS002", "ACC_TRDVAL": "80"},
            ]
        if exchange == "NYS":
            return [
                {"SYMB": "NYS001", "ACC_TRDVAL": "95"},
                {"SYMB": "NYS002", "ACC_TRDVAL": "70"},
            ]
        return []

    client.overseas_trade_value_rank.side_effect = value_rank
    screener = KISOverseasScreener(client)

    result = screener.screen(ScreenRequest(limit=3, metric="value", nday=1))

    assert result.tickers == ["NYS001.NYS", "NAS001.NAS", "NAS002.NAS"]
    assert result.metadata["by_ticker"]["NYS001.NYS"]["metric_value"] == pytest.approx(
        95.0
    )
    assert result.metadata["by_ticker"]["NAS001.NAS"]["provider_rank"] == 1


def test_kis_overseas_screener_stable_tie_breaks_use_provider_rank_then_ticker() -> (
    None
):
    client = MagicMock()

    def value_rank(**kwargs):
        exchange = kwargs.get("exchange")
        if exchange == "NAS":
            return [
                {"SYMB": "NAS001", "ACC_TRDVAL": "100"},
                {"SYMB": "NAS002", "ACC_TRDVAL": "95"},
            ]
        if exchange == "NYS":
            return [
                {"SYMB": "NYS001", "ACC_TRDVAL": "100"},
                {"SYMB": "NYS002", "ACC_TRDVAL": "95"},
            ]
        return []

    client.overseas_trade_value_rank.side_effect = value_rank
    screener = KISOverseasScreener(client)

    result = screener.screen(ScreenRequest(limit=4, metric="value", nday=1))

    assert result.tickers == ["NAS001.NAS", "NYS001.NYS", "NAS002.NAS", "NYS002.NYS"]


def test_kis_overseas_screener_appends_exchange_for_dot_symbol_without_suffix() -> None:
    client = MagicMock()
    client.overseas_trade_volume_rank.return_value = [{"SYMB": "BRK.B"}]
    screener = KISOverseasScreener(client)

    result = screener.screen(
        ScreenRequest(limit=1, metric="volume", exchange="NYS", nday=1)
    )

    assert result.tickers == ["BRK.B.NYS"]


def test_kis_overseas_screener_normalizes_us_and_alias_suffixes() -> None:
    client = MagicMock()
    client.overseas_trade_value_rank.return_value = [
        {"SYMB": "AAPL.US"},
        {"SYMB": "MSFT.NASDAQ"},
        {"SYMB": "BRK.B"},
    ]
    screener = KISOverseasScreener(client)

    result = screener.screen(
        ScreenRequest(limit=10, metric="value", exchange="NAS", nday=1)
    )

    assert result.tickers == ["AAPL.NAS", "MSFT.NAS", "BRK.B.NAS"]


def test_kis_overseas_screener_canonicalizes_class_symbol_and_metadata_key() -> None:
    client = MagicMock()
    client.overseas_trade_value_rank.return_value = [
        {"SYMB": "BRK/B"},
    ]
    screener = KISOverseasScreener(client)

    result = screener.screen(
        ScreenRequest(limit=10, metric="value", exchange="NYS", nday=1)
    )

    assert result.tickers == ["BRK.B.NYS"]
    by_ticker = result.metadata.get("by_ticker", {})
    assert isinstance(by_ticker, dict)
    assert "BRK.B.NYS" in by_ticker
    assert "BRK/B.NYS" not in by_ticker


def test_kis_overseas_screener_fails_on_unsupported_suffix_rows() -> None:
    client = MagicMock()
    client.overseas_trade_value_rank.return_value = [
        {"SYMB": "AAPL.XNAS"},
        {"SYMB": "TSLA.NYS"},
    ]
    screener = KISOverseasScreener(client)

    with pytest.raises(ValueError, match="unsupported suffix"):
        screener.screen(ScreenRequest(limit=10, metric="value", exchange="NAS", nday=1))


def test_kis_overseas_screener_fails_on_exchange_marker_like_symbols() -> None:
    client = MagicMock()
    client.overseas_trade_value_rank.return_value = [
        {"SYMB": "AAPL.O"},
        {"SYMB": "MSFT.NAS"},
    ]
    screener = KISOverseasScreener(client)

    with pytest.raises(ValueError, match="unsupported suffix"):
        screener.screen(ScreenRequest(limit=10, metric="value", exchange="NAS", nday=1))


def test_kis_overseas_screener_fails_on_malformed_class_symbol_rows() -> None:
    client = MagicMock()
    client.overseas_trade_value_rank.return_value = [
        {"SYMB": "A..B"},
        {"SYMB": "BRK.B"},
    ]
    screener = KISOverseasScreener(client)

    with pytest.raises(ValueError, match="unsupported suffix"):
        screener.screen(ScreenRequest(limit=10, metric="value", exchange="NAS", nday=1))


def test_kis_overseas_screener_rejects_ambiguous_exchange_request() -> None:
    client = MagicMock()
    screener = KISOverseasScreener(client)

    with pytest.raises(ValueError, match="unsupported overseas exchange"):
        screener.screen(ScreenRequest(limit=1, metric="value", exchange="US", nday=1))
