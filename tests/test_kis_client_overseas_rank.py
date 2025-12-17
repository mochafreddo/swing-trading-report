import datetime as dt
import unittest
from unittest.mock import MagicMock, patch

from sab.data.kis_client import KISClient, KISCredentials


class KISClientOverseasTradeValueRankTests(unittest.TestCase):
    def setUp(self) -> None:
        self.creds = KISCredentials(
            app_key="test-key",
            app_secret="test-secret",
            base_url="https://example.com",
            env="demo",
        )
        self.client = KISClient(self.creds, session=MagicMock(), cache_dir=None)

    def test_trade_value_rank_calls_fetch_with_expected_payload(self) -> None:
        expected = [{"ticker": "AAPL"}]
        limit = 7

        with patch.object(
            KISClient, "_fetch_overseas_rank_items", return_value=expected
        ) as mock_fetch:
            result = self.client.overseas_trade_value_rank(
                exchange="NASD",
                limit=limit,
                nday="3",
                volume_filter="1",
                price_min=12.75,
                price_max=250.2,
            )

        self.assertEqual(result, expected)
        mock_fetch.assert_called_once()
        kwargs = mock_fetch.call_args.kwargs

        self.assertEqual(kwargs["url"], self.creds.overseas_trade_value_rank_url())
        self.assertEqual(kwargs["tr_id"], "HHDFS76320010")
        self.assertEqual(kwargs["limit"], limit)
        self.assertEqual(
            kwargs["params"],
            {
                "EXCD": "NASD",
                "NDAY": "3",
                "VOL_RANG": "1",
                "PRC1": "12",
                "PRC2": "250",
            },
        )

    def test_trade_value_rank_omits_invalid_price_filters(self) -> None:
        with patch.object(KISClient, "_fetch_overseas_rank_items", return_value=[]) as mock_fetch:
            self.client.overseas_trade_value_rank(
                exchange="NYSE",
                limit=3,
                price_min=0,
                price_max=None,
            )

        mock_fetch.assert_called_once()
        params = mock_fetch.call_args.kwargs["params"]
        self.assertEqual(
            params,
            {
                "EXCD": "NYSE",
                "NDAY": "0",
                "VOL_RANG": "0",
                "PRC1": "",
                "PRC2": "",
            },
        )


class KISClientOverseasRankPaginationTests(unittest.TestCase):
    def setUp(self) -> None:
        creds = KISCredentials(
            app_key="test-key",
            app_secret="test-secret",
            base_url="https://example.com",
            env="demo",
        )
        self.client = KISClient(creds, session=MagicMock(), cache_dir=None)
        self.client._access_token = "Bearer test"
        self.client._token_expiry = dt.datetime.now(dt.UTC) + dt.timedelta(hours=1)

    def test_fetch_overseas_rank_items_paginates_with_tr_cont_and_keyb(self) -> None:
        resp1 = MagicMock()
        resp1.status_code = 200
        resp1.headers = {"tr_cont": "M"}
        resp1.json.return_value = {
            "rt_cd": "0",
            "output2": [{"SYMB": "AAA"}],
            "output1": {"keyb": "CUR1"},
        }

        resp2 = MagicMock()
        resp2.status_code = 200
        resp2.headers = {"tr_cont": ""}
        resp2.json.return_value = {
            "rt_cd": "0",
            "output2": [{"SYMB": "BBB"}],
        }

        self.client._request = MagicMock(side_effect=[resp1, resp2])

        result = self.client._fetch_overseas_rank_items(
            url="https://example.com/rank",
            tr_id="TESTTR",
            params={"EXCD": "NAS", "NDAY": "1", "VOL_RANG": "0"},
            limit=2,
        )

        self.assertEqual([r.get("SYMB") for r in result], ["AAA", "BBB"])
        self.assertEqual(self.client._request.call_count, 2)

        first_call = self.client._request.call_args_list[0].kwargs
        self.assertNotIn("tr_cont", first_call["headers"])

        second_call = self.client._request.call_args_list[1].kwargs
        self.assertEqual(second_call["headers"].get("tr_cont"), "N")
        self.assertEqual(second_call["params"].get("KEYB"), "CUR1")


if __name__ == "__main__":
    unittest.main()
