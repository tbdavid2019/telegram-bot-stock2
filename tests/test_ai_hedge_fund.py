"""Contract tests for the AI Hedge Fund API v2 client."""

import unittest

from handlers.general import build_help_update_stamp
from tools.ai_hedge_fund import (
    ALL_ANALYST_KEYS,
    HedgeFundAPIError,
    build_analysis_payload,
    build_backtest_payload,
    build_round_table_payload,
    get_symbol_entry,
)


class AIHedgeFundPayloadTests(unittest.TestCase):
    def test_help_update_stamp_contains_version_and_taipei_date(self):
        stamp = build_help_update_stamp()

        self.assertIn("v2.17.1", stamp)
        self.assertIn("2026-10-15", stamp)
        self.assertNotIn("2026-10-20", stamp)

    def test_analysis_payload_uses_v2_defaults_and_all_sixteen_analysts(self):
        payload = build_analysis_payload("TSLA,NVDA")

        self.assertEqual(payload["tickers"], "TSLA,NVDA")
        self.assertEqual(payload["modelName"], "openai/gpt-oss-20b")
        self.assertEqual(payload["modelProvider"], "Groq")
        self.assertTrue(payload["enableRoundTable"])
        self.assertEqual(payload["roundTableRounds"], 2)
        self.assertEqual(len(payload["selectedAnalysts"]), 16)
        self.assertEqual(payload["selectedAnalysts"], list(ALL_ANALYST_KEYS))
        self.assertIn("stanley_druckenmiller", payload["selectedAnalysts"])
        self.assertIn("decision_model", payload["selectedAnalysts"])
        self.assertEqual(payload["initialCash"], 100000)

    def test_analysis_payload_rejects_initial_cash_under_one_hundred(self):
        with self.assertRaises(HedgeFundAPIError):
            build_analysis_payload("TSLA", initial_cash=50)
        with self.assertRaises(HedgeFundAPIError):
            build_analysis_payload("TSLA", initial_cash=0)
        with self.assertRaises(HedgeFundAPIError):
            build_analysis_payload("TSLA", initial_cash=-100)

    def test_initial_cash_rejects_nan_and_infinities(self):
        for invalid_cash in (float("nan"), float("inf"), float("-inf"), True, False):
            with self.assertRaises(HedgeFundAPIError):
                build_analysis_payload("TSLA", initial_cash=invalid_cash)
            with self.assertRaises(HedgeFundAPIError):
                build_backtest_payload(
                    run_id="test-run",
                    tickers=["TSLA"],
                    start_date="2026-01-01",
                    end_date="2026-02-01",
                    initial_cash=invalid_cash,
                )

    def test_backtest_payload_rejects_initial_cash_under_one_hundred(self):
        with self.assertRaises(HedgeFundAPIError):
            build_backtest_payload(
                run_id="test-run",
                tickers=["TSLA"],
                start_date="2026-01-01",
                end_date="2026-02-01",
                initial_cash=99.9,
            )

    def test_extract_cash_option_aliases_and_conflicts(self):
        from handlers.ai_cmds import _extract_cash_option

        # Default
        self.assertEqual(_extract_cash_option({}), 100000.0)

        # All aliases supported
        self.assertEqual(_extract_cash_option({"cash": "50000"}), 50000.0)
        self.assertEqual(_extract_cash_option({"initial_cash": "60000"}), 60000.0)
        self.assertEqual(_extract_cash_option({"capital": "70000"}), 70000.0)
        self.assertEqual(_extract_cash_option({"initialcapital": "80000"}), 80000.0)
        self.assertEqual(_extract_cash_option({"initialcash": "90000"}), 90000.0)

        # Identical duplicate aliases
        self.assertEqual(_extract_cash_option({"cash": "50000", "capital": "50000"}), 50000.0)

        # Conflicting duplicate aliases rejected
        with self.assertRaises(HedgeFundAPIError) as ctx:
            _extract_cash_option({"cash": "50000", "capital": "60000"})
        self.assertIn("矛盾", str(ctx.exception))

        # Non-numeric rejected
        with self.assertRaises(HedgeFundAPIError):
            _extract_cash_option({"cash": "invalid"})
        with self.assertRaises(HedgeFundAPIError):
            _extract_cash_option({"initial_cash": ""})

        # NaN and Inf rejected
        with self.assertRaises(HedgeFundAPIError):
            _extract_cash_option({"cash": "nan"})
        with self.assertRaises(HedgeFundAPIError):
            _extract_cash_option({"capital": "inf"})

    def test_analysis_payload_preserves_optional_point_in_time_portfolio(self):
        portfolio = {
            "as_of": "2026-10-10",
            "cash": 50000,
            "currency": "USD",
            "positions": [
                {
                    "ticker": "AAPL",
                    "quantity": 10,
                    "average_entry_price": 180,
                    "currency": "USD",
                }
            ],
        }

        payload = build_analysis_payload(
            ["AAPL", "2330.TW"],
            portfolio=portfolio,
            point_in_time=True,
            start_date="2026-01-01",
            end_date="2026-10-10",
        )

        self.assertEqual(payload["tickers"], "AAPL,2330.TW")
        self.assertEqual(payload["portfolio"], portfolio)
        self.assertTrue(payload["pointInTime"])
        self.assertEqual(payload["startDate"], "2026-01-01")
        self.assertEqual(payload["endDate"], "2026-10-10")

    def test_round_table_payload_requires_object_signals(self):
        payload = build_round_table_payload(
            "NVDA",
            {"cathie_wood": {"NVDA": {"signal": "bullish"}}},
        )

        self.assertEqual(payload["tickers"], "NVDA")
        self.assertEqual(payload["numRounds"], 2)
        self.assertIn("analystSignals", payload)

        with self.assertRaises(HedgeFundAPIError):
            build_round_table_payload("NVDA", [])

    def test_backtest_payload_supports_grid_controls(self):
        payload = build_backtest_payload(
            run_id="trial-1",
            tickers=["AAPL", "2330.TW"],
            start_date="2026-01-05",
            end_date="2026-01-30",
            daily_rebalance_policy="none",
            transaction_fee_rate=0.002,
            slippage_rate=0.001,
            margin_ratio=0.4,
        )

        self.assertEqual(payload["runId"], "trial-1")
        self.assertEqual(payload["tickers"], ["AAPL", "2330.TW"])
        self.assertEqual(payload["dailyRebalancePolicy"], "none")
        self.assertEqual(payload["transactionFeeRate"], 0.002)
        self.assertEqual(payload["slippageRate"], 0.001)
        self.assertEqual(payload["marginRatio"], 0.4)

    def test_symbol_lookup_is_case_insensitive_without_cross_symbol_fallback(self):
        data = {
            "AAPL": {"action": "buy"},
            "NVDA": {"action": "hold"},
        }

        self.assertEqual(get_symbol_entry(data, "aapl"), {"action": "buy"})
        self.assertIsNone(get_symbol_entry(data, "TSLA"))

    def test_portfolio_rejects_non_numeric_position_values(self):
        with self.assertRaises(HedgeFundAPIError):
            build_analysis_payload(
                "AAPL",
                portfolio={
                    "as_of": "2026-10-10",
                    "cash": 1000,
                    "currency": "USD",
                    "positions": [
                        {
                            "ticker": "AAPL",
                            "quantity": "ten",
                            "average_entry_price": 180,
                            "currency": "USD",
                        }
                    ],
                },
            )

    def test_client_async_and_task_endpoints(self):
        from tools.ai_hedge_fund import HedgeFundAPIClient

        client = HedgeFundAPIClient("https://hedgeapi.afpicapital.com")
        self.assertEqual(client.analysis_async_url, "https://hedgeapi.afpicapital.com/api/analysis/async")
        self.assertEqual(client.task_url, "https://hedgeapi.afpicapital.com/api/task")


class AIHedgeFundAsyncClientTests(unittest.IsolatedAsyncioTestCase):
    async def test_analyze_async_posts_to_correct_url(self):
        from unittest import mock
        from tools.ai_hedge_fund import HedgeFundAPIClient

        client = HedgeFundAPIClient("https://hedgeapi.afpicapital.com")
        mock_resp = mock.MagicMock()
        mock_resp.status_code = 202
        mock_resp.json.return_value = {"taskId": "task-123", "status": "pending"}

        with mock.patch("httpx.AsyncClient.request", new_callable=mock.AsyncMock) as mock_request:
            mock_request.return_value = mock_resp
            result = await client.analyze_async({"tickers": "TSLA"})
            self.assertEqual(result["taskId"], "task-123")
            mock_request.assert_called_once_with(
                "POST", "https://hedgeapi.afpicapital.com/api/analysis/async", json={"tickers": "TSLA"}
            )

    async def test_get_task_status_gets_correct_url(self):
        from unittest import mock
        from tools.ai_hedge_fund import HedgeFundAPIClient

        client = HedgeFundAPIClient("https://hedgeapi.afpicapital.com")
        mock_resp = mock.MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {"status": "completed", "result": {}}

        with mock.patch("httpx.AsyncClient.request", new_callable=mock.AsyncMock) as mock_request:
            mock_request.return_value = mock_resp
            result = await client.get_task_status("task-123")
            self.assertEqual(result["status"], "completed")
            mock_request.assert_called_once_with(
                "GET", "https://hedgeapi.afpicapital.com/api/task/task-123", json=None
            )

    async def test_get_task_status_rejects_empty_id(self):
        from tools.ai_hedge_fund import HedgeFundAPIClient, HedgeFundAPIError

        client = HedgeFundAPIClient()
        with self.assertRaises(HedgeFundAPIError):
            await client.get_task_status("")
        with self.assertRaises(HedgeFundAPIError):
            await client.get_task_status("   ")


if __name__ == "__main__":
    unittest.main()
