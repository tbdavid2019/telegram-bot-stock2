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

        self.assertIn("v2.16.2", stamp)
        self.assertIn("2026-10-14", stamp)
        self.assertNotIn("2026-10-20", stamp)

    def test_analysis_payload_uses_v2_defaults_and_all_fifteen_analysts(self):
        payload = build_analysis_payload("TSLA,NVDA")

        self.assertEqual(payload["tickers"], "TSLA,NVDA")
        self.assertEqual(payload["modelName"], "openai/gpt-oss-20b")
        self.assertEqual(payload["modelProvider"], "Groq")
        self.assertTrue(payload["enableRoundTable"])
        self.assertEqual(payload["roundTableRounds"], 2)
        self.assertEqual(payload["selectedAnalysts"], list(ALL_ANALYST_KEYS))
        self.assertIn("stanley_druckenmiller", payload["selectedAnalysts"])

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


if __name__ == "__main__":
    unittest.main()
